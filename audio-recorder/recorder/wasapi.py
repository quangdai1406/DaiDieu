"""Windows capture backend: microphone and speaker loopback via PyAudioWPatch (WASAPI).

NOTE: only the logic around the library is unit-tested (with a fake module);
real device capture has to be checked on a Windows machine.
"""

import time

import numpy as np


def _import_pyaudio():
    try:
        import pyaudiowpatch
    except ImportError as exc:
        raise SystemExit("Capture needs PyAudioWPatch on Windows: pip install PyAudioWPatch") from exc
    return pyaudiowpatch


def int16_to_float(buffer, channels):
    """Convert raw little-endian int16 bytes to float32 shaped (frames, channels)."""
    data = np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
    return data.reshape(-1, channels)


class WasapiSource:
    """One WASAPI input stream. ``loopback=True`` records what the speakers play."""

    def __init__(self, name, device_index=None, loopback=False, pyaudio=None,
                 clock=time.monotonic, frames_per_buffer=1024):
        self.name = name
        self._pa_module = pyaudio or _import_pyaudio()
        self._pa = self._pa_module.PyAudio()
        self._clock = clock
        self._frames_per_buffer = frames_per_buffer
        self._stream = None
        self.device = self._resolve_device(device_index, loopback)
        self.sample_rate = int(self.device["defaultSampleRate"])
        self.channels = int(self.device["maxInputChannels"])

    def _resolve_device(self, index, loopback):
        pa, mod = self._pa, self._pa_module
        if index is None:
            if loopback:
                return pa.get_default_wasapi_loopback()
            host = pa.get_host_api_info_by_type(mod.paWASAPI)
            index = host["defaultInputDevice"]
        info = pa.get_device_info_by_index(index)
        if bool(info.get("isLoopbackDevice")) != loopback:
            kind = "a loopback (speaker) device" if loopback else "a microphone"
            raise ValueError(f"device {index} ({info['name']}) is not {kind}; see `devices`")
        return info

    def start(self, callback):
        mod = self._pa_module

        def on_audio(in_data, frame_count, time_info, status):
            # Timestamp the first frame of this buffer on the shared monotonic clock.
            timestamp = self._clock() - frame_count / self.sample_rate
            callback(timestamp, int16_to_float(in_data, self.channels))
            return (None, mod.paContinue)

        self._stream = self._pa.open(
            format=mod.paInt16, channels=self.channels, rate=self.sample_rate, input=True,
            input_device_index=self.device["index"], frames_per_buffer=self._frames_per_buffer,
            stream_callback=on_audio)
        self._stream.start_stream()

    def stop(self):
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        self._pa.terminate()


class WasapiBackend:
    def __init__(self, pyaudio=None):
        self._pa_module = pyaudio

    def _module(self):
        self._pa_module = self._pa_module or _import_pyaudio()
        return self._pa_module

    def list_devices(self):
        """Return ``[{index, name, kind, channels, rate, default}]`` for WASAPI inputs."""
        mod = self._module()
        pa = mod.PyAudio()
        try:
            wasapi = pa.get_host_api_info_by_type(mod.paWASAPI)
            default_mic = wasapi["defaultInputDevice"]
            try:
                default_loop = pa.get_default_wasapi_loopback()["index"]
            except Exception:
                default_loop = None
            devices = []
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info["hostApi"] != wasapi["index"] or info["maxInputChannels"] < 1:
                    continue
                loop = bool(info.get("isLoopbackDevice"))
                devices.append({
                    "index": info["index"], "name": info["name"],
                    "kind": "loopback" if loop else "mic",
                    "channels": int(info["maxInputChannels"]),
                    "rate": int(info["defaultSampleRate"]),
                    "default": info["index"] == (default_loop if loop else default_mic),
                })
            return devices
        finally:
            pa.terminate()

    def open_sources(self, mic_index=None, loopback_index=None):
        mod = self._module()
        mic = WasapiSource("mic", mic_index, loopback=False, pyaudio=mod)
        try:
            loopback = WasapiSource("loopback", loopback_index, loopback=True, pyaudio=mod)
        except Exception:
            mic.stop()
            raise
        return mic, loopback
