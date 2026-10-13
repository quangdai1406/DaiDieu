import numpy as np
import pytest

from recorder.wasapi import WasapiBackend, WasapiSource, int16_to_float


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.started = self.stopped = self.closed = False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


DEVICES = [
    {"index": 0, "name": "Speakers", "hostApi": 1, "maxInputChannels": 0, "defaultSampleRate": 48000.0},
    {"index": 1, "name": "Headset Mic", "hostApi": 1, "maxInputChannels": 1, "defaultSampleRate": 44100.0,
     "isLoopbackDevice": False},
    {"index": 2, "name": "Speakers [Loopback]", "hostApi": 1, "maxInputChannels": 2,
     "defaultSampleRate": 48000.0, "isLoopbackDevice": True},
    {"index": 3, "name": "MME Mic", "hostApi": 0, "maxInputChannels": 2, "defaultSampleRate": 44100.0},
]


class FakePyAudioModule:
    paInt16 = 8
    paContinue = 0
    paWASAPI = 13
    last_pa = None

    class PyAudio:
        def __init__(self):
            FakePyAudioModule.last_pa = self
            self.terminated = False
            self.stream = None
            self.open_kwargs = None

        def get_host_api_info_by_type(self, kind):
            return {"index": 1, "defaultInputDevice": 1}

        def get_default_wasapi_loopback(self):
            return DEVICES[2]

        def get_device_count(self):
            return len(DEVICES)

        def get_device_info_by_index(self, i):
            return DEVICES[i]

        def open(self, **kwargs):
            self.open_kwargs = kwargs
            self.stream = FakeStream(kwargs["stream_callback"])
            return self.stream

        def terminate(self):
            self.terminated = True


def test_int16_to_float_scales_and_shapes():
    raw = np.array([0, 16384, -32768, 32767], dtype=np.int16).tobytes()
    out = int16_to_float(raw, channels=2)
    assert out.shape == (2, 2)
    assert out[0, 1] == pytest.approx(0.5)
    assert out[1, 0] == pytest.approx(-1.0)


def test_default_mic_and_loopback_are_resolved():
    mod = FakePyAudioModule()
    mic = WasapiSource("mic", None, loopback=False, pyaudio=mod)
    assert (mic.sample_rate, mic.channels, mic.device["index"]) == (44100, 1, 1)
    loop = WasapiSource("loopback", None, loopback=True, pyaudio=mod)
    assert (loop.sample_rate, loop.channels, loop.device["index"]) == (48000, 2, 2)


def test_wrong_device_type_is_rejected():
    mod = FakePyAudioModule()
    with pytest.raises(ValueError, match="not a loopback"):
        WasapiSource("loopback", 1, loopback=True, pyaudio=mod)
    with pytest.raises(ValueError, match="not a microphone"):
        WasapiSource("mic", 2, loopback=False, pyaudio=mod)


def test_callback_timestamps_first_frame_and_converts():
    mod = FakePyAudioModule()
    source = WasapiSource("mic", None, loopback=False, pyaudio=mod, clock=lambda: 100.0)
    received = []
    source.start(lambda ts, samples: received.append((ts, samples)))
    pa = FakePyAudioModule.last_pa
    assert pa.open_kwargs["input_device_index"] == 1
    assert pa.open_kwargs["rate"] == 44100
    assert pa.stream.started

    raw = (np.ones(441, dtype=np.int16) * 16384).tobytes()
    result = pa.stream.callback(raw, 441, {}, 0)
    assert result == (None, mod.paContinue)
    ts, samples = received[0]
    assert ts == pytest.approx(100.0 - 441 / 44100)
    assert samples.shape == (441, 1)
    assert samples[0, 0] == pytest.approx(0.5)

    source.stop()
    assert pa.stream.stopped and pa.stream.closed and pa.terminated


def test_list_devices_filters_to_wasapi_inputs():
    devices = WasapiBackend(FakePyAudioModule()).list_devices()
    assert [(d["index"], d["kind"], d["default"]) for d in devices] == [
        (1, "mic", True), (2, "loopback", True)]
