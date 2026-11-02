"""Settings operations over a floor with D and P windows (storage_kinds.py).

Checks: the delete-floor dry run counts D and P windows and the delete removes both stores;
a full backup copies P windows next to D ones and a restore brings each back into its own
store (source_primes_P/ for _P files), and both carry the floor's D/P list
(DP_PROVEN.txt) as a union; integrating an external storage adopts its P
windows into the P store, leaves the D total untouched by them, adds the D ones and
merges the two D/P lists; the
metadata manifest lists D windows only (restoring it regenerates windows with a sieve
engine, which never writes P). Pure Python, runs on Windows and WSL:
    python unitTests/test_dp_settings.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import prime_sieve_v1  # noqa: E402
import storage_kinds as sk  # noqa: E402

W = 10 ** 7
FLOOR = 25


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _seed(root, windows):
    """windows: [(idx, kind)] -> {(idx, kind): path}"""
    paths = {}
    for idx, kind in windows:
        offset = idx * W
        path = sk.window_path(root, FLOOR, offset, W, f"{offset // 10 ** 6}M" if offset else "0", kind)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        prime_sieve_v1.write_prime_window(path, [10 ** FLOOR + offset + 1 + 2 * idx])
        paths[(idx, kind)] = path
    return paths


def _names(root, kind):
    return sorted(name for name, _p in sk.list_window_files(root, FLOOR, kind))


def check_delete(tmp):
    from primeatlas.settings.delete_manager import FloorWiper
    root = os.path.join(tmp, "delete")
    _seed(root, [(0, "D"), (0, "P"), (1, "P")])
    wiper = FloorWiper(root)
    windows, _hits = wiper.plan_floor(FLOOR)
    passed = check(windows == 3, f"delete dry run counts D and P windows ({windows})")
    ok, _err = wiper.execute_delete_floor(FLOOR)
    passed &= check(ok and not os.path.exists(os.path.join(root, f"10p{FLOOR}")),
                    "delete removes the floor with both stores")
    return passed


def check_full_backup(tmp):
    from primeatlas.settings import full_backup
    live = os.path.join(tmp, "live")
    dest = os.path.join(tmp, "backup")
    _seed(live, [(0, "D"), (0, "P"), (1, "P")])
    sk.add_proven_tags(live, FLOOR, {"PRIME_WINDOW_10p25_off_0"})
    result = full_backup.copy_floor_increment(live, dest, FLOOR)
    passed = check(result["copied_windows"] == 3, f"full backup copies D and P windows ({result})")
    shutil.rmtree(os.path.join(live, f"10p{FLOOR}"))
    result = full_backup.restore_floor_from_full_backup(live, dest, FLOOR)
    passed &= check(result["restored_windows"] == 3, f"restore brings all three back ({result})")
    passed &= check(sk.read_proven_tags(dest, FLOOR) == {"PRIME_WINDOW_10p25_off_0"}
                    and sk.read_proven_tags(live, FLOOR) == {"PRIME_WINDOW_10p25_off_0"},
                    "D/P list backed up and restored")
    passed &= check(_names(live, "D") == ["PRIME_WINDOW_10p25_off_0.bin"]
                    and _names(live, "P") == ["PRIME_WINDOW_10p25_off_0_P.bin",
                                              "PRIME_WINDOW_10p25_off_10M_P.bin"],
                    f"each window restored into its own store (D {_names(live, 'D')}, "
                    f"P {_names(live, 'P')})")
    again = full_backup.copy_floor_increment(live, dest, FLOOR)
    passed &= check(again["copied_windows"] == 0, "a second backup finds nothing new")
    return passed


def check_integrate(tmp):
    from primeatlas.core import storage
    from primeatlas.settings import storage_integrate
    dest = os.path.join(tmp, "int_dest")
    ext = os.path.join(tmp, "int_ext")
    _seed(dest, [(0, "D")])
    _seed(ext, [(0, "D"), (1, "D"), (1, "P"), (2, "P")])
    sk.add_proven_tags(dest, FLOOR, {"PRIME_WINDOW_10p25_off_0"})
    sk.add_proven_tags(ext, FLOOR, {"PRIME_WINDOW_10p25_off_30M"})
    ext_cache = {}
    storage.update_floor_totals_cache(ext, FLOOR, ext_cache)
    storage.update_floor_totals_cache(ext, FLOOR, ext_cache, kind="P")
    storage.save_totals_cache(ext, ext_cache)
    plan = storage_integrate.plan_integration(dest, ext)
    missing = plan[0]["missing_windows"] if plan else []
    passed = check(sorted(missing) == ["PRIME_WINDOW_10p25_off_10M.bin",
                                       "PRIME_WINDOW_10p25_off_10M_P.bin",
                                       "PRIME_WINDOW_10p25_off_20M_P.bin"],
                   f"integration plan lists the missing D and P windows ({missing})")
    result = storage_integrate.integrate_floor(dest, ext, FLOOR)
    passed &= check(result["copied_windows"] == 3, f"integration copies them ({result})")
    passed &= check(_names(dest, "P") == ["PRIME_WINDOW_10p25_off_10M_P.bin",
                                          "PRIME_WINDOW_10p25_off_20M_P.bin"]
                    and len(_names(dest, "D")) == 2,
                    "P windows land in the P store, D in D")
    passed &= check(sk.read_proven_tags(dest, FLOOR) == {"PRIME_WINDOW_10p25_off_0",
                                                          "PRIME_WINDOW_10p25_off_30M"},
                    "integration merges the D/P lists")
    entry = storage.load_totals_cache(dest).get(f"10p{FLOOR}", {})
    passed &= check(entry.get("file_count") == 1 and entry.get("total") == 1,
                    f"D total bumped by the one D window only ({entry.get('total')}, "
                    f"{entry.get('file_count')} files)")
    return passed


def check_manifest(tmp):
    from primeatlas.settings.manifest import FloorSnapshot
    root = os.path.join(tmp, "manifest")
    _seed(root, [(0, "D"), (0, "P")])
    snap = FloorSnapshot.scan(root, FLOOR)
    return check(snap.filenames == ["PRIME_WINDOW_10p25_off_0.bin"],
                 f"metadata manifest lists D only ({snap.filenames})")


def main():
    tmp = tempfile.mkdtemp(prefix="dp_settings_")
    try:
        passed = check_delete(tmp)
        passed &= check_full_backup(tmp)
        passed &= check_integrate(tmp)
        passed &= check_manifest(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
