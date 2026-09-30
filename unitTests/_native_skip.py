"""
_native_skip.py -- shared by the WSL-only hybrid tests (test_hybrid_native,
test_hybrid_sieve, test_hybrid_reference_primesieve).

They need Linux shared libraries (prime_sieve/hybrid_filter_engine.so, libprimesieve),
which cannot exist on native Windows -- run there they used to end in a RuntimeError
traceback that looked like a regression in every full-suite run. On Windows (os.name ==
"nt") a missing library now means SKIPPED; inside WSL, where these tests are meant to run,
a missing library is still a real failure.
"""
import os


def skip_reason_on_windows(loaders):
    """The first loader's error message if running on native Windows and any loader
    fails, else None (run the test)."""
    if os.name != "nt":
        return None
    for load in loaders:
        try:
            load()
        except (RuntimeError, OSError) as e:
            return str(e).splitlines()[0]
    return None


def exit_if_skipped(loaders):
    reason = skip_reason_on_windows(loaders)
    if reason:
        print(f"SKIPPED (WSL-only test, native library unavailable on Windows): {reason}")
        raise SystemExit(0)
