"""
test_prime_window.py -- spec tests for primeatlas/visualization/sphere/prime_window.py's
PrimeWindow: the storage primes around N as a list, loaded a chunk at a time. No GL, no
disk: a fake storage stands in for the archive.

Spec:
  A. Primality from the list: is_prime(n) is True/False for every n inside the loaded span
     (from the first to the last loaded prime), False for n < 2, and loads a new chunk
     around n when n is outside it; None when the storage has nothing there (past its last
     prime, or below its first one when it does not start at 2).
  B. Chunks: every storage call asks for exactly `chunk` primes; a window holds at most
     2 * chunk primes (chunk below n, chunk from n); a lookup inside the loaded span loads
     nothing; once the storage reported its end, lookups past it load nothing again.
  C. Walking: next_prime(n) is the smallest stored prime > n, prev_prime(n) the largest
     stored prime < n, also across chunk edges (loading as needed); None past the ends.
     Walking the whole storage one prime at a time visits every stored prime in order.
  D. Big values: primes past 2**64 (Python ints) work the same way.

Usage:
    python unitTests/test_prime_window.py
"""
import bisect
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _sieve(limit):
    flags = bytearray([1]) * (limit + 1)
    flags[0:2] = b"\x00\x00"
    for i in range(2, int(limit ** 0.5) + 1):
        if flags[i]:
            flags[i * i::i] = bytearray(len(flags[i * i::i]))
    return [i for i in range(limit + 1) if flags[i]]


class FakeStorage:
    """forward(after_n, count): the first `count` stored primes > after_n; backward(before_n,
    count): the last `count` stored primes < before_n (ascending)."""

    def __init__(self, primes):
        self.primes = list(primes)
        self.calls = []

    def forward(self, after_n, count):
        self.calls.append(("forward", after_n, count))
        i = bisect.bisect_right(self.primes, after_n)
        return self.primes[i:i + count]

    def backward(self, before_n, count):
        self.calls.append(("backward", before_n, count))
        i = bisect.bisect_left(self.primes, before_n)
        return self.primes[max(0, i - count):i]


PRIMES = _sieve(20000)
PRIME_SET = set(PRIMES)


def section_a_primality():
    print("\n--- A: primality ---")
    from primeatlas.visualization.sphere.prime_window import PrimeWindow
    store = FakeStorage(PRIMES)
    w = PrimeWindow(store, chunk=100)
    got = [w.is_prime(n) for n in range(0, 3000)]
    check(got == [n in PRIME_SET for n in range(0, 3000)], "is_prime matches the stored primes on 0..2999")
    check(w.is_prime(19993) is True and w.is_prime(19995) is False, "far ahead: loads around n")
    check(w.is_prime(PRIMES[-1]) is True, "the last stored prime")
    check(w.is_prime(PRIMES[-1] + 2) is None, "past the storage end: unknown")
    high = FakeStorage([p for p in PRIMES if p > 10000])
    w = PrimeWindow(high, chunk=50)
    check(w.is_prime(9000) is None, "below a storage that starts high: unknown")
    check(w.is_prime(10007) is True and w.is_prime(10008) is False, "inside it: known")


def section_b_chunks():
    print("\n--- B: chunks ---")
    from primeatlas.visualization.sphere.prime_window import PrimeWindow
    store = FakeStorage(PRIMES)
    w = PrimeWindow(store, chunk=64)
    w.is_prime(5000)
    check(all(call[2] == 64 for call in store.calls), f"every call asks for chunk primes (got {store.calls})")
    check(len(w.primes) <= 128, f"at most 2 * chunk primes held (got {len(w.primes)})")
    before = len(store.calls)
    lo, hi = w.primes[0], w.primes[-1]
    for n in range(lo, hi + 1):
        w.is_prime(n)
    check(len(store.calls) == before, "lookups inside the loaded span load nothing")
    w.is_prime(PRIMES[-1] + 10)
    after_end = len(store.calls)
    for n in range(PRIMES[-1] + 11, PRIMES[-1] + 40):
        w.is_prime(n)
    check(len(store.calls) == after_end, "past the reported end nothing loads again")


def section_c_walking():
    print("\n--- C: walking ---")
    from primeatlas.visualization.sphere.prime_window import PrimeWindow
    store = FakeStorage(PRIMES)
    w = PrimeWindow(store, chunk=37)
    check(w.next_prime(1) == 2 and w.next_prime(2) == 3 and w.next_prime(24) == 29, "next_prime basics")
    check(w.prev_prime(3) == 2 and w.prev_prime(2) is None and w.prev_prime(30) == 29, "prev_prime basics")
    walked = [2]
    while True:
        nxt = w.next_prime(walked[-1])
        if nxt is None:
            break
        walked.append(nxt)
    check(walked == PRIMES, f"forward walk visits every stored prime ({len(walked)} of {len(PRIMES)})")
    back = [PRIMES[-1]]
    while True:
        prv = w.prev_prime(back[-1])
        if prv is None:
            break
        back.append(prv)
    check(back == PRIMES[::-1], "backward walk visits every stored prime")
    check(w.next_prime(PRIMES[-1]) is None, "next past the end: None")
    w2 = PrimeWindow(FakeStorage(PRIMES), chunk=37)
    check(w2.next_prime(15000) == min(p for p in PRIMES if p > 15000), "next from a cold window far ahead")
    check(w2.prev_prime(15000) == max(p for p in PRIMES if p < 15000), "prev from there")


def section_d_big():
    print("\n--- D: big values ---")
    from primeatlas.visualization.sphere.prime_window import PrimeWindow
    base = 2 ** 64
    big = [base + 13, base + 37, base + 51, base + 81, base + 123]
    w = PrimeWindow(FakeStorage(big), chunk=2)
    check(w.is_prime(base + 37) is True and w.is_prime(base + 38) is False, "is_prime past 2**64")
    check(w.next_prime(base + 51) == base + 81 and w.prev_prime(base + 81) == base + 51, "walking past 2**64")


def main():
    for section in (section_a_primality, section_b_chunks, section_c_walking, section_d_big):
        try:
            section()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {e!r}")
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
