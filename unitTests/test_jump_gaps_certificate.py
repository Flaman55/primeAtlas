"""WSL test: the jump gear keeps the previous block's three-gap steps only when they are proven
least (prime_sieve/engine_jump_gear.h, engine v7.4).

The header is compiled into a small driver with gcc and checked against exact integer
arithmetic:
  - jump_gaps_certified(B, T, ga, gc): for random (B, T) (B odd, even, a power of two; T from
    2 to 2^63) and pairs near the least steps (each step +-1, swapped, doubled, summed, the
    least steps of a neighbouring B or T, B gc = 0 mod 2^64, large random pairs), it accepts
    only the least steps (ga, gc) themselves, and it accepts them whenever jump_gaps()'s walk
    finds them; pairs built so that ga dc + gc da = 2^128 + 2^64 (2^64 after a u128 wrap)
    are rejected;
  - jump_block_reuse(): runs of consecutive blocks as engine v7.4 walks a residue class
    (jump_block_len() lengths, floors 25-32, Q log-uniform up to sqrt(first), spans 30 to
    2^31 at block factors 0.5 to 4 and 1e9 to 1e11 at v7.2's factor) give the same landings
    in the same order as jump_block_quick(), also when the cache starts with a wrong pair;
    short runs equal checking every q; at v7.2's factor the cache keeps the pair in more
    than 40 % of the block setups (the point of v7.4).
Run inside WSL from the repo root:
    python3 unitTests/test_jump_gaps_certificate.py
"""
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIEVE_DIR = os.path.join(ROOT, "prime_sieve")
sys.path.insert(0, SIEVE_DIR)
import work_plan_v7_2  # noqa: E402

M = 1 << 64
U64_MAX = M - 1

DRIVER = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned __int128 u128;
#include "engine_jump_gear.h"

static uint64_t out[1 << 16];

int main(void) {
    char op[16];
    while (scanf("%15s", op) == 1) {
        unsigned long long hi, lo, span, q0, q_hi, a, b, list;
        double c;
        if (op[0] == 'c') {           /* cert B T ga gc */
            unsigned long long B, T;
            scanf("%llu %llu %llu %llu", &B, &T, &a, &b);
            printf("%d\n", jump_gaps_certified(B, T, a, b));
        } else if (op[0] == 'g') {    /* gaps B T */
            unsigned long long B, T;
            uint64_t ga = 0, gc = 0;
            scanf("%llu %llu", &B, &T);
            int found = jump_gaps(B, T, &ga, &gc);
            printf("%d %llu %llu\n", found, (unsigned long long)ga, (unsigned long long)gc);
        } else {                      /* run|quick first_hi first_lo span Q0 q_hi c ga gc list */
            scanf("%llu %llu %llu %llu %llu %lf %llu %llu %llu", &hi, &lo, &span, &q0, &q_hi, &c,
                  &a, &b, &list);
            u128 first = ((u128)hi << 64) | lo;
            jump_gaps_cache cache = {a, b, 0, 0};
            uint64_t count = 0, sum = 1469598103934665603ull, blocks = 0;
            for (uint64_t Q = q0; Q < q_hi; blocks++) {
                uint64_t J = jump_block_len(Q, q_hi, c);
                uint64_t n = op[0] == 'r' ? jump_block_reuse(first, span, Q, J, out, &cache)
                                          : jump_block_quick(first, span, Q, J, out);
                for (uint64_t i = 0; i < n; i++) {
                    sum = (sum ^ out[i]) * 1099511628211ull;
                    if (list) printf("%llu ", (unsigned long long)out[i]);
                }
                count += n;
                Q += 30 * J;
            }
            printf("| %llu %llu %llu %llu %llu\n", (unsigned long long)count,
                   (unsigned long long)sum, (unsigned long long)blocks,
                   (unsigned long long)cache.kept, (unsigned long long)cache.walked);
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
        return self.proc.stdout.readline()

    def certified(self, b, t, ga, gc):
        return int(self.ask("cert", b, t, ga, gc)) == 1

    def gaps(self, b, t):
        found, ga, gc = (int(w) for w in self.ask("gaps", b, t).split())
        return (ga, gc) if found else None

    def run(self, reuse, first, span, q0, q_hi, c, seed=(0, 0), listed=False):
        """(landings or None, count, checksum, blocks, kept, walked) of one class walk."""
        line = self.ask("run" if reuse else "quick", first >> 64, first & U64_MAX, span, q0,
                        q_hi, repr(c), seed[0], seed[1], int(listed))
        head, tail = line.split("|")
        stats = [int(w) for w in tail.split()]
        return ([int(w) for w in head.split()] if listed else None, *stats)

    def close(self):
        self.proc.stdin.close()
        self.proc.wait()


def build(tmp):
    src, exe = os.path.join(tmp, "gaps_driver.c"), os.path.join(tmp, "gaps_driver")
    with open(src, "w") as f:
        f.write(DRIVER)
    subprocess.run(["gcc", "-O2", "-Wno-unused-result", "-I", SIEVE_DIR, src, "-o", exe, "-lm"],
                   check=True)
    return exe


def first_in(a, m, lo, hi):
    """Least x >= 0 with lo <= a x mod m <= hi (0 <= lo <= hi < m); None if none."""
    if lo == 0:
        return 0
    a %= m
    if a == 0:
        return None
    k = -(-lo // a)
    if a * k <= hi:
        return k
    y = first_in(m % a, a, (-hi) % a, (-lo) % a)
    return None if y is None else -(-(lo + m * y) // a)


def least_steps(b, t):
    """The least g >= 1 with B g mod 2^64 < T, and with B g mod 2^64 > 2^64 - T."""
    # The least g with B g = 0 mod 2^64 (also below T) is 2^64 / gcd(B, 2^64).
    period = M // math.gcd(b, M)
    ga = first_in(b, M, 1, t - 1)
    ga = period if ga is None else min(ga, period)
    return ga, first_in(b, M, M - t + 1, M - 1)


def random_b(rng):
    kind = rng.randrange(4)
    if kind == 0:
        return rng.randrange(1, M) | 1
    if kind == 1:
        return rng.randrange(1, M)
    if kind == 2:
        return 1 << rng.randrange(1, 64)
    return (rng.randrange(1, 1 << 40) | 1) << rng.randrange(1, 24)


def certificate(d, rng):
    ok = True
    accepted_wrong = true_rejected = walked = near_tried = 0
    for _ in range(3000):
        b = random_b(rng)
        t = max(2, int(2 ** rng.uniform(1, 63)))
        ga, gc = least_steps(b, t)
        if gc is None:
            continue
        found = d.gaps(b, t)
        if found is not None:
            walked += 1
            if found != (ga, gc):
                ok &= check(False, f"jump_gaps({b}, {t}) = {found}, least steps {(ga, gc)}")
            if not d.certified(b, t, ga, gc):
                true_rejected += 1
        others = {(ga + 1, gc), (ga, gc + 1), (max(ga - 1, 0), gc), (ga, max(gc - 1, 0)),
                  (gc, ga), (2 * ga, gc), (ga, 2 * gc), (ga + gc, gc), (ga, ga + gc),
                  (ga + gc, ga + gc), (0, gc), (ga, 0), (1, 1),
                  (rng.randrange(M), rng.randrange(M)), (rng.randrange(1, 1 << 32), gc)}
        period = M // math.gcd(b, M)
        if period < M:
            others.add((ga, period))
            others.add((period, gc))
        for t2 in (t - 1, t + 1, t // 2, min(2 * t, M - 1)):
            if t2 >= 2:
                others.add(least_steps(b, t2))
        for b2 in ((b + 1) % M, (b - 1) % M, (b * 3) % M):
            if b2:
                others.add(least_steps(b2, t))
        for pair in others:
            if pair == (ga, gc) or pair[1] is None or max(pair) >= M:
                continue
            near_tried += 1
            if d.certified(b, t, *pair):
                accepted_wrong += 1
                if accepted_wrong <= 5:
                    print(f"FAIL: B={b} T={t} accepts {pair}, least steps {(ga, gc)}")
    ok &= check(accepted_wrong == 0 and near_tried > 30000,
                f"certificate: {near_tried} wrong pairs tried, {accepted_wrong} accepted")
    ok &= check(true_rejected == 0 and walked > 1500,
                f"certificate: least steps of {walked} walks accepted, {true_rejected} rejected")
    return ok


def wrapped_pairs(d, rng):
    """Pairs whose ga dc + gc da is 2^128 + 2^64, which a u128 sum wraps to 2^64: ga odd near
    2^64, da near 2^63, B = da / ga mod 2^64, dc solved mod da and gc = (N - ga dc) / da,
    T = max(da, dc) + 1, so every other condition of the certificate holds."""
    target = (1 << 128) + M
    built = accepted = 0
    while built < 300:
        ga = rng.randrange(1 << 63, M) | 1
        da = rng.randrange(1 << 62, 1 << 63)
        if math.gcd(ga, da) != 1:
            continue
        dc = target * pow(ga, -1, da) % da
        dc += -(-((target - (M - 1) * da) // ga - dc) // da) * da   # first dc with gc < 2^64
        gc, rest = divmod(target - ga * dc, da)
        if rest or not (0 < gc < M and 0 < dc < M):
            continue
        b = da * pow(ga, -1, M) % M
        t = max(da, dc) + 1
        if b * gc % M != (M - dc) % M or t > M - 1:
            continue
        built += 1
        accepted += d.certified(b, t, ga, gc)
    return check(accepted == 0, f"certificate: {built} pairs with ga dc + gc da = 2^128 + 2^64 "
                 f"(wraps u128 to 2^64), {accepted} accepted")


def coprime30(n):
    while n % 2 == 0 or n % 3 == 0 or n % 5 == 0:
        n += 1
    return n


def landings(first, span, q0, q_hi):
    """Offsets < span of the first multiple of q at or above first, q = q0 + 30 j < q_hi."""
    out = []
    for q in range(q0, q_hi, 30):
        g = -first % q
        if g < span:
            out.append(g)
    return out


def v7_2_factor(first, span):
    """Engine v7.2's block factor at its default knobs (work_plan_v7_2.block_factor())."""
    return work_plan_v7_2.block_factor(first, span, work_plan_v7_2.DEFAULT_BLOCK_MODEL_PCT,
                                       work_plan_v7_2.DEFAULT_JUMP_BLOCK_COST,
                                       work_plan_v7_2.DEFAULT_JUMP_LANDING_COST_PCT)


def class_runs(d, rng):
    """Walks of about 300 blocks from a Q log-uniform between the gear's start and sqrt(first)
    (where the blocks of a run are): spans of 30 to 2^31 numbers at block factors 0.5 to 4,
    and spans of 1e9 to 1e11 at v7.2's own factor (the share of kept steps is measured
    there)."""
    ok = True
    runs = bad = short = short_bad = 0
    kept = walked = 0
    for e in range(25, 33):
        for i in range(25):
            first = rng.randrange(10 ** e, 10 ** (e + 1))
            engine_like = i % 2 == 0
            if engine_like:
                span = rng.choice((10 ** 9, 10 ** 10, 10 ** 11))
                factor = v7_2_factor(first, span)
            else:
                span = 30 * (1 << rng.randrange(0, 26))
                factor = rng.choice((0.5, 1.0, 2.0, 4.0))
            c = factor * math.sqrt(span / (2 * first))
            q_lo = max(int(2 * span * (1 + factor * factor / 2)), (first >> 62) + 1, 60)
            q_top = math.isqrt(first)
            if q_lo >= q_top:
                continue
            q0 = coprime30(int(q_lo * (q_top / q_lo) ** rng.random()))
            # about 300 blocks of the class
            j_len = max(1, int(q0 * c / 30))
            q_hi = min(q0 + 30 * j_len * 300, q_top, M - 30 * 65536)
            if q_hi <= q0:
                continue
            seed = rng.choice(((0, 0), (1, 1), (rng.randrange(1, M), rng.randrange(1, M))))
            want = d.run(False, first, span, q0, q_hi, c)
            got = d.run(True, first, span, q0, q_hi, c, seed)
            runs += 1
            if engine_like:
                kept += got[4]
                walked += got[5]
            if got[1:3] != want[1:3]:
                bad += 1
                if bad <= 5:
                    print(f"FAIL: first={first} span={span} Q0={q0} q_hi={q_hi} c={c}: "
                          f"{got[1:3]} vs {want[1:3]}")
            # a short piece of the same walk, against every q
            q_short = min(q_hi, q0 + 30 * 20000)
            got_list = d.run(True, first, span, q0, q_short, c, seed, listed=True)[0]
            short += 1
            if got_list != landings(first, span, q0, q_short):
                short_bad += 1
    ok &= check(bad == 0 and runs > 150, f"class walks: {runs} runs (seeded caches included) "
                f"equal jump_block_quick()'s landings, {bad} differ")
    ok &= check(short_bad == 0 and short > 150,
                f"class walks: {short} short runs equal checking every q, {short_bad} differ")
    share = kept / max(1, kept + walked)
    ok &= check(share > 0.4 and kept + walked > 10000,
                f"class walks at v7.2's block factor: steps kept in {share:.0%} of "
                f"{kept + walked} block setups")
    return ok


def main():
    if shutil.which("gcc") is None:
        print("FAIL: gcc not found")
        sys.exit(1)
    rng = random.Random(20261112)
    tmp = tempfile.mkdtemp(prefix="jump_gaps_cert_")
    try:
        d = Driver(build(tmp))
        passed = certificate(d, rng)
        passed &= wrapped_pairs(d, rng)
        passed &= class_runs(d, rng)
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
