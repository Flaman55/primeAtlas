"""
test_assembly_layout.py -- spec tests for primeatlas/visualization/assembly/assembly_layout.py,
the arithmetic of the assembly animation: level k+1 of the wheel is p_{k+1} copies of the
period of level k with one residue class removed.

Spec:
  A. first_primes(k) is the first k primes; survivor_residues(primes) is the sorted
     residues r in [0, M) coprime to every prime, M = their product ([0] for no primes).
  B. build_steps(depth): step s uses q = the (s+1)-th prime; the period goes M -> M*q and
     the lanes (survivors per period) L -> L*(q-1), starting from M = 1, L = 1.
     removed_per_copy[j] = lanes r of the old period with (r + j*M) divisible by q; they sum
     to L (exactly one copy per lane). Known values: q=2 (1, 0); q=3 (0, 1, 0);
     q=5 (1, 0, 0, 0, 1); q=7 (1, 1, 1, 2, 1, 1, 1).
  C. next_prime is the smallest survivor > 1 of the new period, found mechanically (it
     equals the next prime after q); square = next_prime^2, and every survivor in
     (1, square) is prime.
  D. Lanes above max_lanes are not enumerated: removed_per_copy is None, the counts and
     next_prime still hold (huge periods are plain Python ints).
  E. Timeline(step_count, frames): len(PHASES) = 4 phases per step (copy, strike, prime,
     collapse), `frames` ticks per phase; total = steps * 4 * frames. locate(t) gives
     (step, phase, frac in [0, 1]); t = total is the last phase at frac 1. Phase and step
     boundaries for stepping forward/back; clamp keeps t in [0, total].

Usage:
    python unitTests/test_assembly_layout.py
"""
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


def _is_prime(n):
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


def section_a_residues():
    print("\n--- A: primes and survivor residues ---")
    from primeatlas.visualization.assembly.assembly_layout import first_primes, survivor_residues
    check(first_primes(6) == [2, 3, 5, 7, 11, 13], f"first six primes (got {first_primes(6)})")
    check(list(survivor_residues([])) == [0], "no primes: the one lane 0 (period 1)")
    check(list(survivor_residues([2, 3])) == [1, 5], "mod 6: 1, 5")
    check(list(survivor_residues([2, 3, 5])) == [1, 7, 11, 13, 17, 19, 23, 29], "mod 30: the 8 lanes")
    check(len(survivor_residues([2, 3, 5, 7])) == 48, "mod 210: 48 lanes")


def section_b_steps():
    print("\n--- B: steps ---")
    from primeatlas.visualization.assembly.assembly_layout import build_steps
    steps = build_steps(6)
    check([s.q for s in steps] == [2, 3, 5, 7, 11, 13], f"q per step (got {[s.q for s in steps]})")
    check([s.index for s in steps] == list(range(6)), "step indices")
    check([s.period_before for s in steps] == [1, 2, 6, 30, 210, 2310], "periods before")
    check([s.period_after for s in steps] == [2, 6, 30, 210, 2310, 30030], "periods after")
    check([s.lanes_before for s in steps] == [1, 1, 2, 8, 48, 480], "lanes before")
    check([s.lanes_after for s in steps] == [1, 2, 8, 48, 480, 5760], "lanes after")
    check(steps[3].primes_before == (2, 3, 5), f"primes before step 3 (got {steps[3].primes_before})")
    expected = {0: (1, 0), 1: (0, 1, 0), 2: (1, 0, 0, 0, 1), 3: (1, 1, 1, 2, 1, 1, 1)}
    for index, removed in expected.items():
        check(steps[index].removed_per_copy == removed,
              f"q={steps[index].q}: removed per copy {removed} (got {steps[index].removed_per_copy})")
    for s in steps:
        check(s.removed_per_copy is not None and sum(s.removed_per_copy) == s.lanes_before
              and len(s.removed_per_copy) == s.q,
              f"q={s.q}: q copies, removals sum to the old lanes (one per lane)")


def section_c_next_prime():
    print("\n--- C: next prime and the square ---")
    from primeatlas.visualization.assembly.assembly_layout import build_steps, survivor_residues
    steps = build_steps(7)
    check([s.next_prime for s in steps] == [3, 5, 7, 11, 13, 17, 19],
          f"next prime per step (got {[s.next_prime for s in steps]})")
    check(all(s.square == s.next_prime ** 2 for s in steps), "square = next_prime^2")
    for s in steps[:6]:
        primes = [2, 3, 5, 7, 11, 13, 17][:s.index + 1]
        lanes = survivor_residues(primes)
        period = s.period_after
        values = [int(r) + k * period for k in range(s.square // period + 1) for r in lanes]
        small = [v for v in values if 1 < v < s.square]
        check(small and all(_is_prime(v) for v in small),
              f"q={s.q}: every survivor in (1, {s.square}) is prime")


def section_d_large():
    print("\n--- D: lanes past max_lanes ---")
    from primeatlas.visualization.assembly.assembly_layout import build_steps
    steps = build_steps(12, max_lanes=1000)
    check(steps[4].removed_per_copy is not None, "48 lanes are enumerated")
    check(steps[5].removed_per_copy is not None, "480 lanes <= 1000 are enumerated")
    check(steps[6].removed_per_copy is None, "5760 lanes > 1000 are not enumerated")
    last = steps[-1]
    check(last.q == 37 and last.period_after == 7420738134810 and last.next_prime == 41,
          f"step 12: q=37, period 37#, next prime 41 (got {last.q}, {last.period_after}, {last.next_prime})")
    check(last.lanes_after == 1 * 2 * 4 * 6 * 10 * 12 * 16 * 18 * 22 * 28 * 30 * 36,
          "lanes = prod(p-1)")


def section_e_timeline():
    print("\n--- E: timeline ---")
    from primeatlas.visualization.assembly.assembly_layout import PHASES, Timeline
    check(PHASES == ("copy", "strike", "prime", "collapse"), f"phases (got {PHASES})")
    tl = Timeline(2, 3)
    check(tl.total == 24, f"total = 2 * 4 * 3 (got {tl.total})")
    check(tl.locate(0) == (0, 0, 0.0), f"t=0 (got {tl.locate(0)})")
    step, phase, frac = tl.locate(4)
    check((step, phase) == (0, 1) and abs(frac - 1 / 3) < 1e-9, f"t=4: strike at 1/3 (got {tl.locate(4)})")
    check(tl.locate(12) == (1, 0, 0.0), f"t=12: step 1 copy (got {tl.locate(12)})")
    check(tl.locate(24) == (1, 3, 1.0), f"t=total: last collapse at 1 (got {tl.locate(24)})")
    check([tl.next_boundary(t) for t in (0, 4, 23, 24)] == [3, 6, 24, 24], "next phase boundary")
    check([tl.prev_boundary(t) for t in (0, 3, 4, 24)] == [0, 0, 3, 21], "previous phase boundary")
    check([tl.next_boundary(t, per_step=True) for t in (1, 12, 24)] == [12, 24, 24], "next step boundary")
    check([tl.prev_boundary(t, per_step=True) for t in (13, 12, 0)] == [12, 0, 0], "previous step boundary")
    check(tl.clamp(-5) == 0 and tl.clamp(99) == 24 and tl.clamp(7) == 7, "clamp")


if __name__ == "__main__":
    for section in (section_a_residues, section_b_steps, section_c_next_prime, section_d_large,
                    section_e_timeline):
        try:
            section()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
