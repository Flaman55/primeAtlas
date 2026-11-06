"""WSL test: prime_sieve_v5_2.py (parallel window writer) produces exactly what the frozen
prime_sieve_v5.py (v5.1) produces.

Same comparison as test_engine_v5_identity.py (every output file byte for byte except the
PGS2 generation timestamp, and the handoff's result fields), over the same cases, run once
with one write thread and once with eight, so a thread count never changes the output.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v5_2_identity.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_engine_v5_identity as base  # noqa: E402

PAIR = ("prime_sieve_v5.py", "prime_sieve_v5_2.py")
THREAD_ENVS = ({"PRIMEATLAS_V5_WRITE_THREADS": "1"}, {"PRIMEATLAS_V5_WRITE_THREADS": "8"})


def main():
    passed = True
    tmp = tempfile.mkdtemp(prefix="engine_v5_2_identity_")
    try:
        for env in THREAD_ENVS:
            for label, *case in base.CASES:
                passed &= base.compare_case(tmp, f"{label} threads {env['PRIMEATLAS_V5_WRITE_THREADS']}",
                                            *case, extra_env=env, scripts=PAIR)
            for label, *case in base.SMALL_SEGMENT_CASES:
                passed &= base.compare_case(tmp, f"{label} threads {env['PRIMEATLAS_V5_WRITE_THREADS']}",
                                            *case, extra_env={**base.SMALL_SEGMENT_ENV, **env},
                                            scripts=PAIR)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.path.insert(0, base.SIEVE_DIR)
    import prime_sieve_v4_1
    from _native_skip import exit_if_skipped
    exit_if_skipped([prime_sieve_v4_1._load_lib])
    raise SystemExit(main())
