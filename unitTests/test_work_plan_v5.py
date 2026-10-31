"""work_plan_v5 splits one v5 sieve run into segmented slices and atomic prime batches.

Checks: slices are 64-bit-word aligned, disjoint and cover the odd-only buffer exactly;
the segmented prime range ends where the batched one starts; the equal-cost batches match
prime_sieve_v4_1's when they start at 2 and stay contiguous from any start; the segment size
setting parses its environment variable and rejects bad values. Pure Python, runs on
Windows and WSL:
    python unitTests/test_work_plan_v5.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import prime_sieve_v4_1 as reference  # noqa: E402
import work_plan_v5  # noqa: E402


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def check_slices():
    passed = True
    for n_bits in (1, 63, 64, 65, 1000, 5_000_000, 5_000_000_001):
        for n_slices in (1, 3, 48, 10_000):
            slices = work_plan_v5.plan_slices(n_bits, n_slices)
            ok = (len(slices) >= 1 and len(slices) <= n_slices
                  and slices[0][0] == 0 and slices[-1][1] == n_bits
                  and all(lo % 64 == 0 and lo < hi for lo, hi in slices)
                  and all(a[1] == b[0] for a, b in zip(slices, slices[1:])))
            passed &= check(ok, f"plan_slices({n_bits}, {n_slices}): {len(slices)} aligned "
                                f"slices covering [0, n_bits)")
    passed &= check(work_plan_v5.plan_slices(0, 48) == [], "plan_slices(0, 48) is empty")
    big = work_plan_v5.plan_slices(5_000_000_000, 48)
    sizes = [hi - lo for lo, hi in big]
    passed &= check(len(big) == 48 and max(sizes) - min(sizes) <= 64,
                    "plan_slices(5e9, 48): 48 slices within one word of each other")
    seg = work_plan_v5.segment_bits(128)
    for n_bits, n_slices, expected in ((5_000_000, 48, 4), (seg - 1, 48, 1), (seg, 48, 1),
                                       (2 * seg, 48, 2), (5_000_000_000, 48, 48),
                                       (5_000_000, 2, 2)):
        slices = work_plan_v5.plan_slices(n_bits, n_slices, min_slice_bits=seg)
        ok = (len(slices) == expected and slices[0][0] == 0 and slices[-1][1] == n_bits
              and all(lo % 64 == 0 and lo < hi for lo, hi in slices)
              and all(a[1] == b[0] for a, b in zip(slices, slices[1:]))
              and (len(slices) == 1 or all(hi - lo >= seg - 64 for lo, hi in slices)))
        passed &= check(ok, f"plan_slices({n_bits}, {n_slices}, min_slice_bits={seg}): "
                            f"{len(slices)} slices (expected {expected}), none much shorter "
                            f"than one segment")
    return passed


def check_prime_split():
    passed = True
    seg_bits = work_plan_v5.segment_bits(128)
    passed &= check(seg_bits == 128 * 1024 * 8, "segment_bits(128 KiB) = 1,048,576")
    stop = work_plan_v5.small_prime_stop(seg_bits, 10 ** 13)
    passed &= check(stop == seg_bits, "deep floor: segmented primes stop at the segment size")
    stop = work_plan_v5.small_prime_stop(seg_bits, 100_001)
    passed &= check(stop == 100_001, "L_final below the segment size: segmented primes "
                                     "cover all of [3, L_final)")
    passed &= check(work_plan_v5.small_prime_stop(seg_bits, 2) == 3,
                    "tiny L_final: stop is at least 3")
    return passed


def check_batches():
    passed = True
    for L_final, size, n in ((100_001, 10 ** 10, 48), (3_162_277_661, 10 ** 10, 48),
                             (3_162_277_660_169, 10 ** 10, 48), (4_001, 3 * 10 ** 6, 16)):
        expected = reference._build_equal_cost_batches(L_final, size, n)
        got = work_plan_v5.build_equal_cost_batches(L_final, size, n)
        passed &= check(got == expected, f"build_equal_cost_batches({L_final}) from 2 "
                                         f"equals v4.1 ({len(got)} batches)")
        for lo in (1_048_576, 8_192):
            if lo >= L_final:
                continue
            got = work_plan_v5.build_equal_cost_batches(L_final, size, n, lo=lo)
            flat = [r for batch in got for r in batch]
            ok = (len(got) >= 1 and flat[0][0] == lo and flat[-1][1] == L_final
                  and all(a[1] == b[0] for a, b in zip(flat, flat[1:]))
                  and all(a < b for a, b in flat))
            passed &= check(ok, f"build_equal_cost_batches({L_final}, lo={lo}): contiguous "
                                f"[lo, L_final) in {len(got)} batches")
    passed &= check(work_plan_v5.build_equal_cost_batches(100_001, 10 ** 10, 48,
                                                          lo=100_001) == [],
                    "build_equal_cost_batches with lo = L_final is empty")
    return passed


def check_segment_setting():
    passed = True
    name = work_plan_v5.SEGMENT_KB_ENV
    passed &= check(work_plan_v5.segment_kb_from_env({}) == work_plan_v5.DEFAULT_SEGMENT_KB,
                    f"{name} unset: default {work_plan_v5.DEFAULT_SEGMENT_KB} KiB")
    passed &= check(work_plan_v5.segment_kb_from_env({name: "32"}) == 32, f"{name}=32 -> 32")
    for bad in ("0", "-4", "abc", "1.5"):
        try:
            work_plan_v5.segment_kb_from_env({name: bad})
            raised = False
        except ValueError:
            raised = True
        passed &= check(raised, f"{name}={bad!r} raises ValueError")
    return passed


def check_bucket_setting():
    passed = True
    name = work_plan_v5.BUCKET_MB_ENV
    passed &= check(work_plan_v5.bucket_mb_from_env({}) == work_plan_v5.DEFAULT_BUCKET_MB,
                    f"{name} unset: default {work_plan_v5.DEFAULT_BUCKET_MB} MiB")
    passed &= check(work_plan_v5.bucket_mb_from_env({name: "256"}) == 256, f"{name}=256 -> 256")
    for bad in ("0", "-1", "x", "2.5"):
        try:
            work_plan_v5.bucket_mb_from_env({name: bad})
            raised = False
        except ValueError:
            raised = True
        passed &= check(raised, f"{name}={bad!r} raises ValueError")
    return passed


def check_region_setting():
    passed = True
    name = work_plan_v5.REGION_KB_ENV
    passed &= check(work_plan_v5.region_kb_from_env({}) == work_plan_v5.DEFAULT_REGION_KB,
                    f"{name} unset: default {work_plan_v5.DEFAULT_REGION_KB} KiB")
    passed &= check(work_plan_v5.region_kb_from_env({name: "4096"}) == 4096,
                    f"{name}=4096 -> 4096")
    passed &= check(work_plan_v5.region_bits(1024) == 2 ** 23, "1024 KiB region = 2^23 bits")
    for bad in ("0", "-1", "x", "2.5"):
        try:
            work_plan_v5.region_kb_from_env({name: bad})
            raised = False
        except ValueError:
            raised = True
        passed &= check(raised, f"{name}={bad!r} raises ValueError")
    return passed


def check_pieces():
    passed = True
    for L_final, size, lo in ((3_162_277_660_169, 5 * 10 ** 10, 1_048_576),
                              (3_162_277_661, 10 ** 10, 1_048_576), (100_001, 10 ** 10, 8_192)):
        for n_threads in (1, 24):
            pieces = work_plan_v5.plan_pieces(L_final, size, lo, n_threads)
            ok = (1 <= len(pieces) <= n_threads * work_plan_v5.PIECES_PER_THREAD
                  and pieces[0][0] == lo and pieces[-1][1] == L_final
                  and all(a < b for a, b in pieces)
                  and all(a[1] == b[0] for a, b in zip(pieces, pieces[1:])))
            passed &= check(ok, f"plan_pieces({L_final}, lo={lo}, {n_threads} threads): "
                                f"{len(pieces)} ascending pieces covering [lo, L_final)")
    deep = work_plan_v5.plan_pieces(3_162_277_660_169, 5 * 10 ** 10, 1_048_576, 24)
    passed &= check(len(deep) == 24 * work_plan_v5.PIECES_PER_THREAD,
                    f"deep floor, 24 threads: {24 * work_plan_v5.PIECES_PER_THREAD} pieces")
    passed &= check(work_plan_v5.plan_pieces(100_001, 10 ** 10, 100_001, 24) == [],
                    "plan_pieces with lo = L_final is empty")
    return passed


def main():
    passed = check_slices()
    passed &= check_prime_split()
    passed &= check_batches()
    passed &= check_segment_setting()
    passed &= check_bucket_setting()
    passed &= check_region_setting()
    passed &= check_pieces()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
