"""run_budget picks how many windows one sieve run takes, from the floor and the RAM free in WSL.

Checks: the v4.1 recommendation (and wsl_resources.recommended_max_windows, which delegates
here) is exactly the formula the Generation tab's Auto button used
so far (half the free RAM over window_m // 8 bytes, clamped to [1, 1000]); the v5 and v6
targets grow with the floor (1000 windows at shallow floors, the engine's knob value at
floor 25, more above), scale with the window width and follow the knob; the v5 footprint is
the odd-only buffer plus bucket memory plus a fixed overhead and stays within the measured
peak PSS, the v6 footprint the wheel-30 buffer (one byte per 30 numbers) plus the same; in
the same RAM v6 fits about 1.875 times v5's windows; a v5/v6 recommendation never exceeds
the RAM budget, shrinks bucket memory before windows on a small machine and never raises it
above the knob; no RAM reading gives no recommendation. Pure
Python, runs on Windows and WSL:
    python unitTests/test_run_budget.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

from primeatlas.generation import run_budget, wsl_resources  # noqa: E402

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
            if wsl_resources.recommended_max_windows(available, window_m) !=                     old_recommendation(available, window_m):
                mismatches.append(("generation", available, window_m))
    passed &= check(not mismatches, f"v4.1 matches the old Auto formula everywhere "
                                    f"(mismatches: {mismatches[:3]})")
    passed &= check(wsl_resources.recommended_max_windows(None) is None,
                    "wsl_resources.recommended_max_windows: no RAM reading -> None")
    passed &= check(run_budget.recommend_run(None, "v4.1", 25, W) is None,
                    "v4.1: no RAM reading -> no recommendation")
    passed &= check(run_budget.recommend_run(0, "v5", 25, W) is None,
                    "v5: zero RAM reading -> no recommendation")
    return passed


def check_target():
    passed = True
    t = run_budget.target_windows
    passed &= check(t("v4.1", 25, W) == 1000, "v4.1 target stays 1000 at floor 25")
    defaults = run_budget.DEFAULT_TARGET_WINDOWS_AT_25
    passed &= check(defaults == {"v5": 20_000, "v6": 40_000, "v7": 40_000},
                    f"floor-25 target defaults per engine ({defaults})")
    passed &= check(t("v5", 25, W) == 20_000 and t("v6", 25, W) == 40_000,
                    f"targets at floor 25 are the engines' defaults "
                    f"(v5 {t('v5', 25, W)}, v6 {t('v6', 25, W)})")
    passed &= check(t("v6", 25, W, target_at_25=2000) == 2000, "v6 target follows the knob")
    passed &= check(all(t("v6", f, W) == 1000 for f in range(0, 22)),
                    "v6 target is 1000 windows at floors 0..21")
    passed &= check(all(t("v5", f, W) == 1000 for f in range(0, 23)),
                    "v5 target is 1000 windows at floors 0..22")
    series = [t("v5", f, W) for f in range(0, 31)]
    passed &= check(all(a <= b for a, b in zip(series, series[1:])),
                    f"v5 target never shrinks with the floor ({series[22:28]})")
    passed &= check(1000 < t("v5", 24, W) < 20_000 < t("v5", 26, W),
                    f"v5 target between floors: 24 -> {t('v5', 24, W)}, 26 -> {t('v5', 26, W)}")
    passed &= check(t("v5", 25, W // 10) == 200_000,
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
    passed &= check(fp("v6", 1000, W, 1024) == -(-1000 * W // 30) + 1024 * MIB
                    + run_budget.V5_OVERHEAD_BYTES,
                    "v6 footprint = wheel-30 buffer + buckets + overhead")
    passed &= check(all(fp("v7", w, W, mb) == fp("v6", w, W, mb)
                        for w, mb in ((1, 64), (1000, 1024), (37500, 8192))),
                    "v7 footprint = v6's (same buffer; the gear adds 512 KiB per thread)")
    # Peak RSS measured on floor 25 (night 2026-11-04): (engine, windows, bucket MiB, MB).
    measured = [("v6", 20000, 8192, 14945196 / 1024), ("v6", 37500, 8192, 20676044 / 1024),
                ("v6", 37500, 4096, 16481568 / 1024), ("v5", 20000, 8192, 20673032 / 1024)]
    covered = [fp(e, w, W, mb) / MIB >= rss for e, w, mb, rss in measured]
    passed &= check(all(covered), f"v5/v6 footprints cover the measured peak RSS ({covered})")
    return passed


def check_v5_recommendation():
    passed = True
    rec = run_budget.recommend_run
    big = rec(64 * GB, "v5", 25, W)
    cap_mb = int(32 * GB / run_budget.BUCKET_BUDGET_SHARE) // MIB
    passed &= check(run_budget.DEFAULT_BUCKET_MB == 8192
                    and big.windows == 20_000 and big.bucket_mb == min(8192, cap_mb),
                    f"64 GB free @25: 20000 windows, buckets capped at a quarter of the "
                    f"budget (got {big})")
    for ram in (16 * GB, 30 * GB, 53 * GB):
        r5, r6 = rec(ram, "v5", 27, W), rec(ram, "v6", 27, W)
        passed &= check(r6.bucket_mb == r5.bucket_mb and 1.8 <= r6.windows / r5.windows <= 1.9,
                        f"{ram // GB} GB free @27: v6 fits ~1.875x v5's windows "
                        f"({r6.windows} vs {r5.windows})")
    passed &= check(rec(64 * GB, "v5", 19, W).windows == 1000,
                    "64 GB free @19: target 1000 windows")
    small = rec(3_500_000_000, "v5", 25, W)   # 8 GB host: WSL keeps about half
    used = run_budget.run_footprint_bytes("v5", small.windows, W, small.bucket_mb)
    passed &= check(used <= 0.5 * 3_500_000_000,
                    f"3.5 GB free @25: footprint {used / GB:.2f} GB within half the free RAM")
    passed &= check(small.bucket_mb < run_budget.DEFAULT_BUCKET_MB and small.windows > 1000,
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
        grid_ok &= fits and r.windows >= last and r.bucket_mb <= run_budget.DEFAULT_BUCKET_MB
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
