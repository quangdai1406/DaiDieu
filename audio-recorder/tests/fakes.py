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
