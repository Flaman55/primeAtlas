"""
test_window_sharding.py -- unit tests for prime_sieve/window_sharding.py, the shared
sharding scheme introduced for task #405 (constellation_finder_v1.py's WSL process dying
silently mid-scan on floor 25's 542,001-file flat source_primes/ directory).

Pure logic, no tkinter, no real prime data needed -- exercises the module's own functions
directly against a real (but tiny) temp-directory tree, plus a couple of integration
checks against prime_sieve_v1.write_prime_window()/primeatlas.storage.list_source_files()
to confirm the write-then-read round trip actually works end to end, not just that the
pure functions individually do the right arithmetic.

Usage (Windows, real Python -- pure Python + numpy, no Tk/display dependency at all):
    python unitTests\\test_window_sharding.py

Usage (this sandbox, headless):
    python3 unitTests/test_window_sharding.py
"""
import os
import shutil
import sys
import tempfile

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
    import window_sharding as ws
    import prime_sieve_v1

    # === Pure arithmetic: shard_name / shard_index_for_offset ==========================
    check(ws.shard_name(0) == "shard_00000", f"window_index=0 -> shard_00000 (got {ws.shard_name(0)!r})")
    check(ws.shard_name(4999) == "shard_00000",
          f"window_index=4999 (last of first shard) -> shard_00000 (got {ws.shard_name(4999)!r})")
    check(ws.shard_name(5000) == "shard_00001",
          f"window_index=5000 (first of second shard) -> shard_00001 (got {ws.shard_name(5000)!r})")
    check(ws.shard_name(542000) == f"shard_{542000 // 5000:05d}",
          f"window_index=542000 (floor 25's real historical scale) doesn't crash/misformat "
          f"(got {ws.shard_name(542000)!r})")
    try:
        ws.shard_name(-1)
        check(False, "shard_name(-1) should raise ValueError, not silently misplace a file")
    except ValueError:
        check(True, "shard_name(-1) raises ValueError")

    check(ws.shard_index_for_offset(0, 10_000_000) == 0,
          "offset=0 -> window_index 0 regardless of window_m")
    check(ws.shard_index_for_offset(10_000_000, 10_000_000) == 1,
          "offset=window_m -> window_index 1 (second window written)")
    check(ws.shard_index_for_offset(49_990_000_000, 10_000_000) == 4999,
          "offset just under 5000*window_m -> window_index 4999 (last slot of shard_00000)")

    # === shard_dir / iter_shard_dirs / list_sharded_files (real temp directory) =========
    tmp = tempfile.mkdtemp(prefix="primeatlas_window_sharding_test_")
    try:
        parent = os.path.join(tmp, "source_primes")

        check(list(ws.iter_shard_dirs(parent)) == [],
              "iter_shard_dirs on a nonexistent parent returns nothing (not an error)")
        check(ws.list_sharded_files(parent) == [],
              "list_sharded_files on a nonexistent parent returns [] (not an error)")
        check(ws.count_sharded_files(parent) == 0,
              "count_sharded_files on a nonexistent parent returns 0")

        # Three windows spread across two shards (index 0 and 1), plus a stray
        # non-matching file and a stray non-shard subfolder -- both should be ignored.
        shard0 = ws.shard_dir(parent, 0)
        shard1 = ws.shard_dir(parent, 5000)
        os.makedirs(shard0, exist_ok=True)
        os.makedirs(shard1, exist_ok=True)
        os.makedirs(os.path.join(parent, "not_a_shard"), exist_ok=True)
        open(os.path.join(parent, "not_a_shard", "PRIME_WINDOW_stray.bin"), "wb").close()

        prime_sieve_v1.write_prime_window(os.path.join(shard0, "PRIME_WINDOW_a.bin"), [2, 3, 5])
        prime_sieve_v1.write_prime_window(os.path.join(shard0, "PRIME_WINDOW_b.bin"), [7, 11])
        prime_sieve_v1.write_prime_window(os.path.join(shard1, "PRIME_WINDOW_c.bin"), [13])
        open(os.path.join(shard1, "not_a_window.txt"), "w").close()

        shard_names = [name for name, _path in ws.iter_shard_dirs(parent)]
        check(shard_names == ["shard_00000", "shard_00001"],
              f"iter_shard_dirs finds both real shards, in order, ignores 'not_a_shard' "
              f"(got {shard_names!r})")

        all_files = ws.list_sharded_files(parent)
        all_names = sorted(name for name, _path in all_files)
        check(all_names == ["PRIME_WINDOW_a.bin", "PRIME_WINDOW_b.bin", "PRIME_WINDOW_c.bin",
                             "not_a_window.txt"],
              f"list_sharded_files (no predicate) finds every file in every real shard, "
              f"ignores the stray non-shard subfolder entirely (got {all_names!r})")

        predicate = lambda n: n.startswith("PRIME_WINDOW_") and n.endswith(".bin")
        window_files = ws.list_sharded_files(parent, predicate=predicate)
        window_names = sorted(name for name, _path in window_files)
        check(window_names == ["PRIME_WINDOW_a.bin", "PRIME_WINDOW_b.bin", "PRIME_WINDOW_c.bin"],
              f"list_sharded_files with a predicate filters out not_a_window.txt "
              f"(got {window_names!r})")
        check(ws.count_sharded_files(parent, predicate=predicate) == 3,
              "count_sharded_files with the same predicate agrees with list_sharded_files's length")

        # === shard_dir_for_restored_offset (backup-restore / cross-storage merge path) ==
        check(ws.shard_dir_for_restored_offset(parent, None) == ws.shard_dir(parent, 0),
              "shard_dir_for_restored_offset(offset=None) falls back to shard index 0 "
              "instead of raising")
        check(ws.shard_dir_for_restored_offset(parent, 50_000_000_000) ==
              ws.shard_dir(parent, 5000),
              "shard_dir_for_restored_offset buckets by the default 10,000,000 window_m")

        # === Round-trip: storage.list_source_files finds files across BOTH shards =======
        # storage.py lives in the primeatlas/ package (imported elsewhere in this repo as
        # primeatlas.storage / "from .storage import ..."), not a bare top-level module --
        # add repo root (already on sys.path above) is enough since it's a real package
        # (primeatlas/__init__.py exists).
        from primeatlas import storage as storage_module

        # list_source_files/list_source_filenames expect a portal-folder layout
        # ("<portal>/10p{N}/source_primes/..."), not a bare source_primes/ dir -- reuse
        # the same tmp/source_primes tree by nesting it one level deeper under a fake
        # portal + floor.
        portal_dir = os.path.join(tmp, "portal")
        floor_source_dir = os.path.join(portal_dir, "10p7", "source_primes")
        floor_shard = ws.shard_dir(floor_source_dir, 0)
        floor_shard2 = ws.shard_dir(floor_source_dir, 5000)
        os.makedirs(floor_shard, exist_ok=True)
        os.makedirs(floor_shard2, exist_ok=True)
        prime_sieve_v1.write_prime_window(os.path.join(floor_shard, "PRIME_WINDOW_x.bin"), [17, 19])
        prime_sieve_v1.write_prime_window(os.path.join(floor_shard2, "PRIME_WINDOW_y.bin"), [23])

        found = storage_module.list_source_files(portal_dir, 7)
        found_names = sorted(name for name, _path, _header in found)
        check(found_names == ["PRIME_WINDOW_x.bin", "PRIME_WINDOW_y.bin"],
              f"storage.list_source_files() finds windows across BOTH shard_00000 and "
              f"shard_00001 (got {found_names!r}) -- this is the exact read path "
              f"the Prime numbers tab's floor-file listing depends on")
        check(all(header is not None for _n, _p, header in found),
              "storage.list_source_files() successfully read a real header for every "
              "sharded window (not silently falling back to header=None)")

        found_names2 = sorted(name for name, _path in storage_module.list_source_filenames(portal_dir, 7))
        check(found_names2 == ["PRIME_WINDOW_x.bin", "PRIME_WINDOW_y.bin"],
              f"storage.list_source_filenames() (the cheap no-I/O listing used by "
              f"constellation_finder_v1.py and manifest.py) also finds windows across "
              f"BOTH shards (got {found_names2!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
