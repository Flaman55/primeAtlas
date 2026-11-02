"""
test_window_integrity.py -- window_integrity.is_complete() / read_window_header():
True for every window write_prime_window_offsets() writes (empty, one prime, many,
multi-byte gaps), False for every truncation of such a file, header fields read back.

Pure logic, no tkinter, no WSL.

Usage:
    python unitTests/test_window_integrity.py
"""
import os
import shutil
import sys
import tempfile

import numpy as np

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


def main():
    from pgs2_vector import write_prime_window_offsets
    import window_integrity

    tmp = tempfile.mkdtemp(prefix="primeatlas_window_integrity_test_")
    try:
        lo = 10 ** 25 + 1
        cases = {
            "empty": np.array([], dtype=np.int64),
            "one prime": np.array([6], dtype=np.int64),
            "many primes": np.array([0, 2, 6, 8, 12, 18, 20, 26], dtype=np.int64),
            # gaps >= 128 need two varint bytes, >= 16384 three
            "multi-byte gaps": np.array([0, 300, 20_000, 20_002, 60_000], dtype=np.int64),
        }
        for name, offsets in cases.items():
            path = os.path.join(tmp, f"{name.replace(' ', '_')}.bin")
            write_prime_window_offsets(path, lo, offsets, generated_at=1_700_000_000)
            check(window_integrity.is_complete(path), f"{name}: written window is complete")
            count, generated_at = window_integrity.read_window_header(path)
            check(count == len(offsets) and generated_at == 1_700_000_000,
                  f"{name}: header reads back count={count}, generated_at={generated_at}")

            with open(path, "rb") as f:
                data = f.read()
            cut_ok = True
            for cut in range(len(data)):
                cut_path = os.path.join(tmp, "cut.bin")
                with open(cut_path, "wb") as f:
                    f.write(data[:cut])
                if window_integrity.is_complete(cut_path):
                    cut_ok = False
                    print(f"      {name}: truncation to {cut}/{len(data)} bytes judged complete")
            check(cut_ok, f"{name}: every truncation ({len(data)} lengths) is incomplete")

        bad = os.path.join(tmp, "bad_magic.bin")
        with open(bad, "wb") as f:
            f.write(b"XXXX" + bytes(20))
        check(not window_integrity.is_complete(bad), "bad magic is incomplete")
        check(not window_integrity.is_complete(os.path.join(tmp, "missing.bin")),
              "missing file is incomplete")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
