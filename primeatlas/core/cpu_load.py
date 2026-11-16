"""
cpu_load.py -- how busy the whole Windows CPU is, read in this process with no admin rights:
the system's idle and total CPU counters (GetSystemTimes) and a sampler that keeps their last
seconds, so a launch can name the busy share over the seconds before it (run_load.py's
cpu_busy_before_pct). Off Windows the counters are None and every share is None.

The sampler runs on a daemon thread started with the app (start_sampling()); reading a share
never blocks. The share is the whole CPU's, Atlas's own work included.
"""
import collections
import ctypes
import os
import threading
import time

import run_load

SAMPLE_SECONDS = 1.0
KEEP_SECONDS = 30.0
# The seconds before a launch whose busy share the launch names.
BEFORE_SECONDS = 5.0


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]


def _ticks(file_time):
    return (file_time.high << 32) | file_time.low


def read_system_counters():
    """(idle, total) 100 ns ticks summed over all CPUs since boot, total = kernel + user
    (kernel time includes idle time); None off Windows or when the call fails."""
    if os.name != "nt":
        return None
    idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel),
                                                 ctypes.byref(user)):
        return None
    return _ticks(idle), _ticks(kernel) + _ticks(user)


class CpuSampler:
    """Keeps (time, counters) samples of the last `keep_seconds`; `reader` and `clock` are
    read_system_counters and time.monotonic in the app, fakes in tests."""

    def __init__(self, reader=read_system_counters, clock=time.monotonic,
                 keep_seconds=KEEP_SECONDS):
        self._reader = reader
        self._clock = clock
        self._keep_seconds = keep_seconds
        self._samples = collections.deque()
        self._lock = threading.Lock()
        self._thread = None

    def sample(self):
        counters = self._reader()
        if counters is None:
            return
        now = self._clock()
        with self._lock:
            self._samples.append((now, counters))
            while self._samples and self._samples[0][0] < now - self._keep_seconds:
                self._samples.popleft()

    def samples(self):
        with self._lock:
            return list(self._samples)

    def busy_over_last(self, seconds):
        """The busy share in percent from the newest sample at or before `seconds` back (the
        oldest when the history is shorter) to the newest sample; None with fewer than two."""
        samples = self.samples()
        if len(samples) < 2:
            return None
        newest_time, newest = samples[-1]
        start = samples[0][1]
        for when, counters in samples[:-1]:
            if when > newest_time - seconds:
                break
            start = counters
        return run_load.busy_pct(start, newest)

    def start(self, interval=SAMPLE_SECONDS):
        """Samples every `interval` seconds on a daemon thread; a second call does nothing."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, args=(interval,), daemon=True)
        self._thread.start()

    def _loop(self, interval):
        while True:
            self.sample()
            time.sleep(interval)


_shared = CpuSampler()


def start_sampling():
    """Starts the app-wide sampler (once, at app start; later calls do nothing)."""
    _shared.start()


def busy_before_launch():
    """The busy share over the last BEFORE_SECONDS, None until the sampler has two samples."""
    return _shared.busy_over_last(BEFORE_SECONDS)
