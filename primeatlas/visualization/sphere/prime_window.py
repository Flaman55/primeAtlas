"""
prime_window.py -- the storage primes around N as one sorted list, loaded a chunk at a
time: primality of N and the next/previous stored prime, at any scale. ArchiveStorage
reads a PrimeAtlas portal folder (shared/sources.py's load_archive/load_archive_before);
any object with the same forward/backward methods works (tests use an in-memory one).

A window holds the `chunk` stored primes below a center and the `chunk` from it on. The
storage is taken as gap-free between its first and last prime, so inside the loaded span
the list decides primality; outside it the window reloads around the asked value. A
short forward (backward) answer marks the storage's last (first) prime: past it the
answer is None (unknown), without asking the storage again.
"""

import bisect

# Upper bound handed to load_archive: past every storage floor.
_FAR_UPTO = 10 ** 60


class ArchiveStorage:
    """forward/backward over a portal folder's prime archive."""

    def __init__(self, portal_folder):
        self.portal_folder = portal_folder

    def forward(self, after_n, count):
        """The first `count` stored primes > after_n, ascending."""
        from primeatlas.visualization.shared.sources import load_archive
        return [int(v) for v in load_archive(self.portal_folder, _FAR_UPTO, from_n=max(0, int(after_n)),
                                             max_load_count=count)]

    def backward(self, before_n, count):
        """The last `count` stored primes < before_n, ascending."""
        from primeatlas.visualization.shared.sources import load_archive_before
        return [int(v) for v in load_archive_before(self.portal_folder, int(before_n), count)]


class PrimeWindow:
    def __init__(self, storage, chunk):
        self.storage = storage
        self.chunk = int(chunk)
        self.primes = []
        # The storage's first and last prime once a short answer revealed them; `_empty`
        # once a load found no prime at all.
        self._first = None
        self._last = None
        self._empty = False

    # -- loading ----------------------------------------------------------------

    def _load_at(self, center):
        """Replaces the window with the chunk below `center` and the chunk from it on."""
        back = list(self.storage.backward(center, self.chunk))
        fwd = list(self.storage.forward(center - 1, self.chunk))
        if len(back) < self.chunk:
            self._first = back[0] if back else (fwd[0] if fwd else None)
        if len(fwd) < self.chunk:
            self._last = fwd[-1] if fwd else (back[-1] if back else None)
        self.primes = back + fwd
        if not self.primes:
            self._empty = True

    def _outside_storage(self, n):
        return (self._empty or (self._last is not None and n > self._last)
                or (self._first is not None and n < self._first))

    def _covers(self, n):
        return bool(self.primes) and self.primes[0] <= n <= self.primes[-1]

    # -- queries ----------------------------------------------------------------

    def is_prime(self, n):
        """True/False from the stored list, None where the storage has no data."""
        n = int(n)
        if n < 2:
            return False
        if self._outside_storage(n):
            return None
        if not self._covers(n):
            self._load_at(n)
            if self._outside_storage(n) or not self._covers(n):
                return None
        i = bisect.bisect_left(self.primes, n)
        return i < len(self.primes) and self.primes[i] == n

    def _next_in_window(self, n):
        """The smallest window prime > n when nothing stored can lie between, else None."""
        if not self.primes or not (self.primes[0] <= n or self.primes[0] == self._first):
            return None
        i = bisect.bisect_right(self.primes, n)
        return self.primes[i] if i < len(self.primes) else None

    def _prev_in_window(self, n):
        if not self.primes or not (n <= self.primes[-1] or self.primes[-1] == self._last):
            return None
        i = bisect.bisect_left(self.primes, n)
        return self.primes[i - 1] if i > 0 else None

    def next_prime(self, n):
        """The smallest stored prime > n, or None past the storage's last prime."""
        n = int(n)
        if self._empty or (self._last is not None and n >= self._last):
            return None
        found = self._next_in_window(n)
        if found is None:
            self._load_at(n + 1)
            found = self._next_in_window(n)
        return found

    def prev_prime(self, n):
        """The largest stored prime < n, or None below the storage's first prime."""
        n = int(n)
        if self._empty or n <= 2 or (self._first is not None and n <= self._first):
            return None
        found = self._prev_in_window(n)
        if found is None:
            self._load_at(n)
            found = self._prev_in_window(n)
        return found
