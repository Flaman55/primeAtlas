"""run_budget picks how many windows one sieve run takes, from the floor and the RAM free in WSL.

Checks: the v4.1 recommendation (and generation.recommended_max_windows, which delegates
here) is exactly the formula the Generation tab's Auto button used
so far (half the free RAM over window_m // 8 bytes, clamped to [1, 1000]); the v5 target
grows with the floor (1000 windows at shallow floors, the knob's value at floor 25, more
above), scales with the window width and follows the knob; the v5 footprint is the odd-only
buffer plus bucket memory plus a fixed overhead and stays within the measured peak PSS; a v5
recommendation never exceeds the RAM budget, shrinks bucket memory before windows on a small
machine and never raises it above the knob; no RAM reading gives no recommendation. Pure
Python, runs on Windows and WSL:
    python unitTests/test_run_budget.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

from primeatlas.generation import generation, run_budget  # noqa: E402

GB = 10 ** 9
MIB = 2 ** 20
W = 10_000_000


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def old_recommendation(available, window_m=W, safety_fraction=0.5):
    """The Auto button's formula before run_budget existed (v4.1 buffer only)."""
    if not available or available <= 0:
        return None
    return max(1, min(1000, int((available * safety_fraction) // (window_m // 8))))


def check_v41_unchanged():
    passed = True
    mismatches = []
    for available in (1, 10 ** 6, 5 * 10 ** 8, 3_500_000_000, 8 * GB, 32 * GB, 10 ** 13):
        for window_m in (10 ** 6, 999_999, W):
            for floor in (0, 10, 19, 25, 30):
                got = run_budget.recommend_run(available, "v4.1", floor, window_m)
                if got.windows != old_recommendation(available, window_m):
                    mismatches.append((available, window_m, floor, got.windows))
            if generation.recommended_max_windows(available, window_m) !=                     old_recommendation(available, window_m):
                mismatches.append(("generation", available, window_m))
    passed &= check(not mismatches, f"v4.1 matches the old Auto formula everywhere "
                                    f"(mismatches: {mismatches[:3]})")
    passed &= check(generation.recommended_max_windows(None) is None,
                    "generation.recommended_max_windows: no RAM reading -> None")
    passed &= check(run_budget.recommend_run(None, "v4.1", 25, W) is None,
                    "v4.1: no RAM reading -> no recommendation")
    passed &= check(run_budget.recommend_run(0, "v5", 25, W) is None,
                    "v5: zero RAM reading -> no recommendation")
    return passed


def check_target():
    passed = True
    t = run_budget.target_windows
    passed &= check(t("v4.1", 25, W) == 1000, "v4.1 target stays 1000 at floor 25")
    passed &= check(t("v5", 25, W) == run_budget.DEFAULT_TARGET_WINDOWS_AT_25 == 5000,
                    f"v5 target at floor 25 is the knob's default 5000 (got {t('v5', 25, W)})")
    passed &= check(all(t("v5", f, W) == 1000 for f in range(0, 23)),
                    "v5 target is 1000 windows at floors 0..22")
    series = [t("v5", f, W) for f in range(0, 31)]
    passed &= check(all(a <= b for a, b in zip(series, series[1:])),
                    f"v5 target never shrinks with the floor ({series[22:28]})")
    passed &= check(1000 < t("v5", 24, W) < 5000 < t("v5", 26, W),
                    f"v5 target between floors: 24 -> {t('v5', 24, W)}, 26 -> {t('v5', 26, W)}")
    passed &= check(t("v5", 25, W // 10) == 50_000,
                    f"v5 target at floor 25 keeps the tape length for 1e6-wide windows "
                    f"(got {t('v5', 25, W // 10)})")
    passed &= check(t("v5", 25, W, target_at_25=2000) == 2000,
                    "v5 target follows the knob (2000 at floor 25)")
    passed &= check(t("v5", 25, W, target_at_25=10) == 1000,
                    "v5 target never drops below 1000 windows")
    return passed


def check_footprint():
    passed = True
    fp = run_budget.run_footprint_bytes
    passed &= check(fp("v4.1", 1000, W, 1024) == 1000 * (W // 8),
                    "v4.1 footprint is the full bit buffer only")
    passed &= check(fp("v5", 1000, W, 1024) == 1000 * (W // 16) + 1024 * MIB
                    + run_budget.V5_OVERHEAD_BYTES,
                    "v5 footprint = odd-only buffer + buckets + overhead")
    # Peak PSS measured at 24 workers (bench_ref v5_step6b): (windows, bucket MiB, MB).
    measured = [(1000, 1024, 1686.2), (5000, 1024, 4093.7), (5000, 4096, 7145.8)]
    covered = [fp("v5", w, W, mb) / MIB >= pss for w, mb, pss in measured]
    passed &= check(all(covered), f"v5 footprint covers every measured peak PSS ({covered})")
    return passed


def check_v5_recommendation():
    passed = True
    rec = run_budget.recommend_run
    big = rec(64 * GB, "v5", 25, W)
    passed &= check(big.windows == 5000 and big.bucket_mb == 1024,
                    f"64 GB free @25: 5000 windows, 1024 MiB buckets (got {big})")
    passed &= check(rec(64 * GB, "v5", 19, W).windows == 1000,
                    "64 GB free @19: target 1000 windows")
    small = rec(3_500_000_000, "v5", 25, W)   # 8 GB host: WSL keeps about half
    used = run_budget.run_footprint_bytes("v5", small.windows, W, small.bucket_mb)
    passed &= check(used <= 0.5 * 3_500_000_000,
                    f"3.5 GB free @25: footprint {used / GB:.2f} GB within half the free RAM")
    passed &= check(small.bucket_mb < 1024 and small.windows > 1000,
                    f"3.5 GB free @25: buckets shrink before windows (got {small})")
    passed &= check(rec(3_500_000_000, "v5", 25, W, bucket_mb=128).bucket_mb == 128,
                    "a bucket knob below the RAM cap is kept")
    tiny = rec(10 ** 8, "v5", 25, W)
    passed &= check(tiny.windows == 1 and tiny.bucket_mb == run_budget.MIN_BUCKET_MB,
                    f"100 MB free: 1 window, minimum buckets (got {tiny})")
    grid_ok = True
    last = 0
    for available in range(GB, 40 * GB, GB // 2):
        r = rec(available, "v5", 25, W)
        fits = (r.windows == 1
                or run_budget.run_footprint_bytes("v5", r.windows, W, r.bucket_mb)
                <= 0.5 * available)
        grid_ok &= fits and r.windows >= last and r.bucket_mb <= 1024
        last = r.windows
    passed &= check(grid_ok, "1..40 GB free @25: always fits, windows never shrink with RAM")
    passed &= check(rec(64 * GB, "v5", 25, W, max_windows=1000).windows == 1000,
                    "max_windows caps the recommendation")
    return passed


def main():
    passed = check_v41_unchanged()
    passed &= check_target()
    passed &= check_footprint()
    passed &= check_v5_recommendation()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
