"""WSL test: the jump gear (prime_sieve/engine_jump_gear.h) stays inside its proven range.

The header is compiled into a small driver with gcc and checked against exact integer
arithmetic:
  - jump_gear_from(): the gear is on up to first = JUMP_FIRST_MAX = (2^128 - 1) // 30 and off
    from JUMP_FIRST_MAX + 1 (30 first wraps u128 there; 2^126, the old limit, is off too), on
    up to span = 2^48 and off above it, off at jump_from = 0; when on, the lowest q is
    max(jump_from, 2 span, first // 2^62 + 1);
  - jump_block_len(): never above Q // 60, at least 1, and unchanged where that cap does not
    bind;
  - jump_block() and jump_block_quick(): random blocks with one planted landing each, at
    floors 25-32 and just below JUMP_FIRST_MAX, spans from 30 to 2^40 (some past half a turn
    of Q, where every q is checked): every landing of the block with its exact offset, in
    ascending j, the same as checking every q;
  - first >= 2^62 Q (outside the 64.64 range): both functions check every q instead of
    returning nothing.
Run inside WSL from the repo root:
    python3 unitTests/test_jump_gear_bounds.py
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIEVE_DIR = os.path.join(ROOT, "prime_sieve")
U64_MAX = (1 << 64) - 1
FIRST_MAX = ((1 << 128) - 1) // 30
SPAN_MAX = 1 << 48

DRIVER = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned __int128 u128;
#include "engine_jump_gear.h"

int main(void) {
    char op[16];
    static uint64_t out[1 << 16];
    while (scanf("%15s", op) == 1) {
        unsigned long long hi, lo, span, a, b;
        if (op[0] == 'f') {           /* from first_hi first_lo span jump_from */
            scanf("%llu %llu %llu %llu", &hi, &lo, &span, &a);
            printf("%llu\n", (unsigned long long)jump_gear_from(((u128)hi << 64) | lo, span, a));
        } else if (op[0] == 'l') {    /* len Q q_hi c */
            double c;
            scanf("%llu %llu %lf", &a, &b, &c);
            printf("%llu\n", (unsigned long long)jump_block_len(a, b, c));
        } else {                      /* block|quick first_hi first_lo span Q J */
            scanf("%llu %llu %llu %llu %llu", &hi, &lo, &span, &a, &b);
            u128 first = ((u128)hi << 64) | lo;
            uint64_t n = op[0] == 'b' ? jump_block(first, span, a, b, out)
                                      : jump_block_quick(first, span, a, b, out);
            printf("%llu", (unsigned long long)n);
            for (uint64_t i = 0; i < n; i++) printf(" %llu", (unsigned long long)out[i]);
            printf("\n");
        }
        fflush(stdout);
    }
    return 0;
}
"""


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


class Driver:

    def __init__(self, path):
        self.proc = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True)

    def ask(self, *words):
        self.proc.stdin.write(" ".join(str(w) for w in words) + "\n")
        self.proc.stdin.flush()
        return [int(w) for w in self.proc.stdout.readline().split()]

    def gear_from(self, first, span, jump_from):
        return self.ask("from", first >> 64, first & U64_MAX, span, jump_from)[0]

    def block_len(self, q, q_hi, c):
        return self.ask("len", q, q_hi, repr(c))[0]

    def block(self, quick, first, span, q, j):
        got = self.ask("quick" if quick else "block", first >> 64, first & U64_MAX, span, q, j)
        return got[1:]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait()


def build(tmp):
    src, exe = os.path.join(tmp, "gear_driver.c"), os.path.join(tmp, "gear_driver")
    with open(src, "w") as f:
        f.write(DRIVER)
    subprocess.run(["gcc", "-O2", "-Wno-unused-result", "-I", SIEVE_DIR, src, "-o", exe, "-lm"], check=True)
    return exe


def landings(first, span, q0, j_count):
    """Offsets < span of the first multiple of q0 + 30 j at or above first, j ascending."""
    out = []
    for j in range(j_count):
        q = q0 + 30 * j
        g = -first % q
        if g < span:
            out.append(g)
    return out


def coprime30(n):
    while n % 2 == 0 or n % 3 == 0 or n % 5 == 0:
        n += 1
    return n


def gear_on_off(d):
    ok = True
    span, jump_from = 30 * 4096, 1000
    expected = max(jump_from, 2 * span, (FIRST_MAX >> 62) + 1)
    ok &= check(d.gear_from(FIRST_MAX, span, jump_from) == expected,
                "on at first = JUMP_FIRST_MAX, lowest q = max(jump_from, 2 span, first/2^62+1)")
    for first, name in ((FIRST_MAX + 1, "JUMP_FIRST_MAX + 1"), (10 ** 37 * 12 // 10, "1.2e37"),
                        ((1 << 126) - 1, "2^126 - 1"), (1 << 126, "2^126")):
        ok &= check(d.gear_from(first, span, jump_from) == U64_MAX, f"off at first = {name}")
    first = 10 ** 30
    ok &= check(d.gear_from(first, SPAN_MAX, 1) == max(2 * SPAN_MAX, (first >> 62) + 1),
                "on at span = 2^48")
    ok &= check(d.gear_from(first, SPAN_MAX + 1, 1) == U64_MAX, "off at span = 2^48 + 1")
    ok &= check(d.gear_from(first, span, 0) == U64_MAX, "off at jump_from = 0")
    ok &= check(d.gear_from(10 ** 25, span, 10 ** 15) == 10 ** 15, "jump_from above the limits")
    return ok


def block_lengths(d, rng):
    ok = True
    for _ in range(2000):
        q = rng.randrange(60, 1 << rng.choice((8, 12, 20, 40)))
        c = rng.choice((1e-9, 1e-6, 1e-3, 0.1, 1.0, 50.0))
        q_hi = q + 30 * rng.randrange(1, 1 << 20)
        got = d.block_len(q, q_hi, c)
        jd = q * c / 30
        old = 1 if jd < 1 else min(int(jd), 65536)
        old = min(old, (q_hi - q + 29) // 30)
        want = min(old, max(q // 60, 1))
        if got != want or got > q // 60 or got < 1:
            return check(False, f"jump_block_len({q}, {q_hi}, {c}) = {got}, expected {want}")
    ok &= check(True, "jump_block_len: 2000 blocks, never above Q // 60, else unchanged")
    return ok


def planted_blocks(d, rng):
    ok = True
    groups = [("floors 25-32", [10 ** e for e in range(25, 33)]),
              ("just below JUMP_FIRST_MAX", [FIRST_MAX - (1 << 70), FIRST_MAX - (1 << 20),
                                             FIRST_MAX])]
    for name, targets in groups:
        cases = bad = 0
        for target in targets:
            for _ in range(60):
                span = 30 * rng.choice((1, 7, 1 << 10, 1 << 16, 1 << 24, 1 << 35))
                q_lo = max(2 * span, (target >> 62) + 1, 60)
                q_top = min(q_lo * rng.choice((2, 50, 10 ** 6)), (1 << 64) - 30 * 4000)
                q0 = coprime30(rng.randrange(q_lo, q_top))
                j_count = min(rng.randrange(1, 4000), q0 // 60)
                if q0 + 30 * j_count >= 1 << 64:
                    continue
                q = q0 + 30 * rng.randrange(j_count)
                first = min(-(-target // q) * q - rng.randrange(span), FIRST_MAX)
                want = landings(first, span, q0, j_count)
                for quick in (False, True):
                    cases += 1
                    got = d.block(quick, first, span, q0, j_count)
                    if got != want:
                        bad += 1
                        if bad <= 5:
                            print(f"FAIL: {'quick' if quick else 'block'} first={first} "
                                  f"span={span} Q={q0} J={j_count}: {got[:6]} vs {want[:6]}")
        ok &= check(bad == 0 and cases > 200, f"{name}: {cases} blocks with planted landings, "
                    f"{bad} differ")
    return ok


def beyond_fixed_point(d, rng):
    ok = True
    cases = bad = 0
    for _ in range(200):
        first = rng.randrange(10 ** 25, 10 ** 30)
        span = 30 * rng.randrange(1, 1 << 12)
        q0 = coprime30(rng.randrange(max(2 * span, 60), first >> 62))
        j_count = min(rng.randrange(1, 300), q0 // 60) or 1
        q = q0 + 30 * rng.randrange(j_count)
        first = first - first % q + q - rng.randrange(span)
        if not first >> 62 >= q0:
            continue
        want = landings(first, span, q0, j_count)
        for quick in (False, True):
            cases += 1
            bad += d.block(quick, first, span, q0, j_count) != want
    ok &= check(bad == 0 and cases > 100, f"first >= 2^62 Q: {cases} blocks checked q by q, "
                f"{bad} differ")
    return ok


def main():
    if shutil.which("gcc") is None:
        print("FAIL: gcc not found")
        sys.exit(1)
    rng = random.Random(20261112)
    tmp = tempfile.mkdtemp(prefix="jump_gear_bounds_")
    try:
        d = Driver(build(tmp))
        passed = gear_on_off(d)
        passed &= block_lengths(d, rng)
        passed &= planted_blocks(d, rng)
        passed &= beyond_fixed_point(d, rng)
        d.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not passed:
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    if not sys.platform.startswith("linux"):
        print("SKIPPED (WSL-only)")
        sys.exit(0)
    main()
