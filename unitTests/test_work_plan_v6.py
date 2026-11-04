"""work_plan_v6 plans one v6 run on the wheel-30 buffer.

Checks: the four knobs read their own PRIMEATLAS_V6_* variables (not v5's), default to the
measured v6.0 values and reject bad values; a segment of seg_bits wheel bits covers
seg_bits / 8 * 30 numbers; the segmented primes end at half a segment's numbers, never above
L_final and never below 7; slices and pieces are v5's planners (one implementation, not a
copy) and follow the pieces-per-thread knob. Pure Python, runs on Windows and WSL:
    python unitTests/test_work_plan_v6.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import work_plan_v5  # noqa: E402
import work_plan_v6  # noqa: E402


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def check_knobs():
    passed = True
    knobs = (("SEGMENT_KB_ENV", work_plan_v6.segment_kb_from_env, 2048),
             ("REGION_KB_ENV", work_plan_v6.region_kb_from_env, 1024),
             ("BUCKET_MB_ENV", work_plan_v6.bucket_mb_from_env, 8192),
             ("PIECES_PER_THREAD_ENV", work_plan_v6.pieces_per_thread_from_env, 16))
    passed &= check(work_plan_v6.WRITE_THREADS_ENV == "PRIMEATLAS_V6_WRITE_THREADS"
                    and work_plan_v6.write_threads_from_env({}) == 8
                    and work_plan_v6.write_threads_from_env(
                        {"PRIMEATLAS_V6_WRITE_THREADS": "3"}) == 3,
                    "write threads: PRIMEATLAS_V6_WRITE_THREADS, default 8")
    for attr, read, default in knobs:
        name = getattr(work_plan_v6, attr)
        passed &= check(name.startswith("PRIMEATLAS_V6_") and name != getattr(work_plan_v5, attr),
                        f"{attr} is v6's own variable ({name})")
        passed &= check(read({}) == default, f"{name} unset -> {default}")
        passed &= check(read({name: "3"}) == 3, f"{name}=3 -> 3")
        passed &= check(read({getattr(work_plan_v5, attr): "3"}) == default,
                        f"{name}: v5's variable is ignored")
        for bad in ("0", "-2", "1.5", "x"):
            try:
                read({name: bad})
                raised = False
            except ValueError:
                raised = True
            passed &= check(raised, f"{name}={bad!r} raises ValueError")
    passed &= check((work_plan_v6.DEFAULT_SEGMENT_KB, work_plan_v6.DEFAULT_REGION_KB,
                     work_plan_v6.DEFAULT_BUCKET_MB, work_plan_v6.DEFAULT_PIECES_PER_THREAD)
                    == (2048, 1024, 8192, 16), "v6.0 defaults")
    return passed


def check_plan():
    passed = True
    seg = work_plan_v6.segment_bits(2048)
    passed &= check(work_plan_v6.segment_numbers(seg) == 2048 * 1024 * 30,
                    "a 2 MiB segment covers 2 MiB * 30 numbers")
    passed &= check(work_plan_v6.small_prime_stop(seg, 10 ** 12) == 2048 * 1024 * 15,
                    "segmented primes end at half a segment's numbers")
    passed &= check(work_plan_v6.small_prime_stop(seg, 1000) == 1000
                    and work_plan_v6.small_prime_stop(8, 5) == 7,
                    "never above L_final, never below 7")
    passed &= check(work_plan_v6.plan_slices is work_plan_v5.plan_slices
                    and work_plan_v6.plan_pieces is work_plan_v5.plan_pieces,
                    "slices and pieces use v5's planners")
    pieces = work_plan_v6.plan_pieces(3_162_277_660_169, 5 * 10 ** 10, 31_457_280, 24,
                                      pieces_per_thread=2)
    passed &= check(len(pieces) == 48 and pieces[0][0] == 31_457_280,
                    f"pieces follow pieces_per_thread ({len(pieces)})")
    return passed


def main():
    passed = check_knobs()
    passed &= check_plan()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
