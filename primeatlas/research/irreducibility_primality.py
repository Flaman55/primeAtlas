"""
irreducibility_primality.py -- one run of isPrimeRes (irreducibility_residues.is_prime_res_steps)
for Research -> Irreducibility -> Primality, advanced in slices so the view stays responsive:
the step count, the answer and why the run ended, and the first and last steps for the table.
Also the layout condition under which the square test stops the run at isqrt(n).
"""
import math
from collections import deque

from . import irreducibility_residues as res

HEAD_ROWS = 10
"""First steps kept for the table; arbitrary."""

TAIL_ROWS = 10
"""Last steps kept for the table; arbitrary."""

REASONS = ("equal", "below", "square", "divisor", "fuel", "incompatible", "stopped")
"""Why a run ended: m = n (prime), n < m (not prime, n < 2), m^2 > n (prime), m divides n
(not prime), fuel used up, incompatible residues, stopped by the user."""


def square_test_holds(n, w):
    """(isqrt(n) + 1)^2 < W: the square of every tried divisor up to isqrt(n) + 1 stays below
    W, so its residues compare as the square itself and the run stops by isqrt(n) + 1
    (isPrimeRes_eq). Otherwise a run may go on up to n."""
    return (math.isqrt(n) + 1) ** 2 < w


def fit_target(n):
    """The number a layout has to exceed for square_test_holds(n, W)."""
    return (math.isqrt(n) + 1) ** 2


def _reason(step):
    _m, vs_m, vs_sq, rem, _answer = step
    if vs_m == 0:
        return "equal"
    if vs_m == 1:
        return "below"
    if vs_sq == 1:
        return "square"
    return "divisor" if rem == 0 else None


class PrimalityRun:
    """isPrimeRes on residues with at most fuel steps. advance(k) runs up to k more steps and
    returns done; first holds the first head steps and last the last tail steps, each as
    (index, m, m vs n, m^2 vs n, n mod m)."""

    def __init__(self, moduli, residues, fuel, head=HEAD_ROWS, tail=TAIL_ROWS):
        self.fuel = fuel
        self.steps = 0
        self.answer = None
        self.reason = None
        self.done = False
        self.first = []
        self.last = deque(maxlen=tail)
        self._head = head
        self._steps = res.is_prime_res_steps(moduli, residues)

    def _end(self, reason, answer=None):
        self.reason, self.answer, self.done = reason, answer, True

    def advance(self, count):
        for _ in range(count):
            if self.done:
                break
            if self.steps >= self.fuel:
                self._end("fuel")
                break
            step = next(self._steps, None)
            if step is None:
                self._end("incompatible")
                break
            self.steps += 1
            row = (self.steps,) + tuple(step[:4])
            if len(self.first) < self._head:
                self.first.append(row)
            self.last.append(row)
            if step[4] is not None:
                self._end(_reason(step), step[4])
            elif self.steps >= self.fuel:
                self._end("fuel")
        return self.done

    def stop(self):
        if not self.done:
            self._end("stopped")

    def current_m(self):
        """The last tried divisor, 0 before the first step."""
        return self.last[-1][1] if self.last else 0
