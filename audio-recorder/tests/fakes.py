"""Deterministic stand-ins for real audio devices."""


class FakeSource:
    """An AudioSource the test drives by calling ``emit``."""

    def __init__(self, name, sample_rate, fail_on_start=False):
        self.name = name
        self.sample_rate = sample_rate
        self.fail_on_start = fail_on_start
        self.started = False
        self.stopped = False
        self._callback = None

    def start(self, callback):
        if self.fail_on_start:
            raise RuntimeError(f"{self.name}: cannot open device")
        self._callback = callback
        self.started = True

    def stop(self):
        self.stopped = True

    def emit(self, timestamp, samples):
        self._callback(timestamp, samples)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakeBackend:
    """Stands in for WasapiBackend: hands out two FakeSources."""

    def __init__(self, rate=8000):
        self.mic = FakeSource("mic", rate)
        self.loopback = FakeSource("loopback", rate)
        self.fail_open = None
        self.requested = None

    def list_devices(self):
        return [{"index": 1, "name": "Headset Mic", "kind": "mic", "channels": 1,
                 "rate": 44100, "default": True},
                {"index": 2, "name": "Speakers [Loopback]", "kind": "loopback", "channels": 2,
                 "rate": 48000, "default": False}]

    def open_sources(self, mic_index, loopback_index):
        if self.fail_open:
            raise self.fail_open
        self.requested = (mic_index, loopback_index)
        return self.mic, self.loopback


class SyncRunner:
    """Runs background work immediately, like ThreadRunner but deterministic."""

    def submit(self, work, done):
        try:
            result = work()
        except BaseException as exc:  # noqa: BLE001 - mirrors ThreadRunner
            done(None, exc)
        else:
            done(result, None)


class ManualRunner:
    """Holds background work until the test calls run_all()."""

    def __init__(self):
        self.pending = []

    def submit(self, work, done):
        self.pending.append((work, done))

    def run_all(self):
        pending, self.pending = self.pending, []
        for work, done in pending:
            try:
                result = work()
            except BaseException as exc:  # noqa: BLE001
                done(None, exc)
            else:
                done(result, None)
