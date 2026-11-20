"""
test_machines_backup.py -- benchmark_machines.json (core/machines_file.py) survives backups,
restores and storage integration: nothing is lost, a broken file is never overwritten.

A. machines_file.merge_file_into(target_dir, source_dir, now, replace_broken_target=False):
   merges the source folder's file into the target folder's: "merged" when the target
   changed, "unchanged" when it already held every entry or the source has no file;
   a broken source file: "broken", nothing changes; a broken target file: "broken", a copy of
   it is kept (preserve_corrupt) and the target is left as it is, unless
   replace_broken_target, which writes the source's entries over it after the copy.
B. Metadata backup (settings/manifest.py, backup_store.py): BackupManifest.build_from_disk()
   keeps the storage's machines (machines); to_dict()/from_dict() keep them; a broken or
   missing storage file gives machines None and the backup is still made; a manifest from
   before the field reads as None. BackupStore.restore_machines(manifest) merges them into
   the storage file ("merged"/"unchanged"); None leaves the file untouched ("unchanged"); a
   broken storage file: "broken", untouched, a copy kept.
C. Full backup (settings/full_backup.py): copy_floor_increment() merges the live file into
   benchmark_machines.json at the backup root and names the outcome in its result
   ("machines"); a later backup never drops an entry the live file lost; a broken backup copy
   is kept aside and rewritten from the live file ("broken"). restore_floor_from_full_backup()
   merges the backup's file into the live one ("machines" in its result); a broken backup
   file imports nothing; a broken live file stays untouched ("broken").
D. storage_integrate.integrate_floor() merges the external storage's file into the
   destination's; a repeated integration changes nothing; the external file is untouched; an
   external storage without the file, or with a broken one, changes nothing and raises
   nothing.

Usage:
    python unitTests/test_machines_backup.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

from primeatlas.core import machines_file as mf  # noqa: E402
from primeatlas.settings import full_backup, storage_integrate  # noqa: E402
from primeatlas.settings.backup_store import BackupStore  # noqa: E402
from primeatlas.settings.manifest import BackupManifest  # noqa: E402

_dirs = []
T1 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _tmp(prefix):
    path = tempfile.mkdtemp(prefix=f"machines_{prefix}_")
    _dirs.append(path)
    return path


def entry(since, cl=None, ram=3600):
    stamp = since.strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"since": stamp, "edited_at": stamp, "asked": True, "auto": {"ram_mts": ram},
            "manual": {f: None for f in mf.MANUAL_FIELDS} | {"cl": cl}}


A = {"aaaaaaaaaaaa": [entry(T1, 16)]}
B = {"bbbbbbbbbbbb": [entry(T1, 18)], "aaaaaaaaaaaa": [entry(T2, ram=3200)]}


def _text(folder):
    with open(mf.path(folder), encoding="utf-8") as f:
        return f.read()


def _broken(folder):
    with open(mf.path(folder), "w", encoding="utf-8") as f:
        f.write("{broken")


def _copies(folder):
    return [n for n in os.listdir(folder)
            if n.startswith(mf.FILE_NAME) and n != mf.FILE_NAME and ".tmp" not in n]


def _floor(storage, floor=20):
    os.makedirs(os.path.join(storage, f"10p{floor}", "source_primes"), exist_ok=True)


def merge_file_checks():
    passed = True
    target, source = _tmp("target"), _tmp("source")
    mf.save(target, A)
    passed &= check(mf.merge_file_into(target, source, T2) == "unchanged"
                    and mf.load(target) == A, "no source file: unchanged")
    mf.save(source, B)
    passed &= check(mf.merge_file_into(target, source, T2) == "merged"
                    and mf.load(target) == mf.merge(A, B), "source entries merged in")
    passed &= check(mf.merge_file_into(target, source, T2) == "unchanged", "again: unchanged")
    _broken(source)
    before = _text(target)
    passed &= check(mf.merge_file_into(target, source, T2) == "broken"
                    and _text(target) == before, "broken source: nothing changes")
    mf.save(source, B)
    _broken(target)
    passed &= check(mf.merge_file_into(target, source, T2) == "broken"
                    and _text(target) == "{broken" and len(_copies(target)) == 1,
                    "broken target: copy kept, target untouched")
    other = _tmp("target2")
    _broken(other)
    passed &= check(mf.merge_file_into(other, source, T2, replace_broken_target=True) == "broken"
                    and mf.load(other) == B and len(_copies(other)) == 1,
                    "replace_broken_target: copy kept, rewritten from the source")
    return passed


def manifest_checks():
    passed = True
    storage = _tmp("manifest")
    mf.save(storage, A)
    manifest = BackupManifest.build_from_disk(storage)
    passed &= check(manifest.machines == A, "the manifest keeps the machines")
    again = BackupManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
    passed &= check(again.machines == A, "to_dict/from_dict keep them")
    old = manifest.to_dict()
    old.pop("machines", None)
    passed &= check(BackupManifest.from_dict(old).machines is None,
                    "a manifest from before the field: None")
    _broken(storage)
    passed &= check(BackupManifest.build_from_disk(storage).machines is None,
                    "broken storage file: None, backup still made")
    empty = _tmp("manifest_empty")
    passed &= check(BackupManifest.build_from_disk(empty).machines is None, "no file: None")

    live = _tmp("restore")
    mf.save(live, B)
    store = BackupStore(live)
    passed &= check(store.restore_machines(again) == "merged"
                    and mf.load(live) == mf.merge(B, A), "restore merges, nothing lost")
    passed &= check(store.restore_machines(again) == "unchanged", "again: unchanged")
    before = _text(live)
    passed &= check(store.restore_machines(BackupManifest.from_dict(old)) == "unchanged"
                    and _text(live) == before, "old manifest: file untouched")
    _broken(live)
    passed &= check(store.restore_machines(again) == "broken" and _text(live) == "{broken"
                    and len(_copies(live)) == 1, "broken live file: untouched, copy kept")
    return passed


def full_backup_checks():
    passed = True
    storage, dest = _tmp("fb_live"), _tmp("fb_dest")
    _floor(storage)
    mf.save(storage, A)
    result = full_backup.copy_floor_increment(storage, dest, 20)
    passed &= check(result.get("machines") == "merged" and mf.load(dest) == A,
                    f"backup writes the file at the backup root ({result.get('machines')})")
    mf.save(storage, B)
    full_backup.copy_floor_increment(storage, dest, 20)
    passed &= check(mf.load(dest) == mf.merge(A, B),
                    "a later backup keeps the entry the live file lost")
    _broken(dest)
    result = full_backup.copy_floor_increment(storage, dest, 20)
    passed &= check(result.get("machines") == "broken" and mf.load(dest) == B
                    and len(_copies(dest)) == 1, "broken backup copy: kept aside, rewritten")

    mf.save(dest, mf.merge(A, B))
    target = _tmp("fb_target")
    _floor(target)
    result = full_backup.restore_floor_from_full_backup(target, dest, 20)
    passed &= check(result.get("machines") == "merged" and mf.load(target) == mf.merge(A, B),
                    "restore merges the backup's file into the live one")
    _broken(target)
    result = full_backup.restore_floor_from_full_backup(target, dest, 20)
    passed &= check(result.get("machines") == "broken" and _text(target) == "{broken",
                    "broken live file: untouched")
    other = _tmp("fb_other")
    _floor(other)
    _broken(dest)
    try:
        result = full_backup.restore_floor_from_full_backup(other, dest, 20)
        passed &= check(result.get("machines") == "broken"
                        and not os.path.exists(mf.path(other)),
                        "broken backup file: nothing imported")
    except Exception as error:  # noqa: BLE001
        passed &= check(False, f"broken backup file raised {error!r}")
    return passed


def integrate_checks():
    passed = True
    ext, dest = _tmp("ext"), _tmp("dest")
    _floor(ext)
    mf.save(ext, B)
    mf.save(dest, A)
    ext_before = _text(ext)
    storage_integrate.integrate_floor(dest, ext, 20)
    passed &= check(mf.load(dest) == mf.merge(A, B), "integration merges the external file")
    before = _text(dest)
    storage_integrate.integrate_floor(dest, ext, 20)
    passed &= check(_text(dest) == before and _text(ext) == ext_before,
                    "repeated: nothing changes; external untouched")
    for kind in ("none", "broken"):
        bare = _tmp(f"ext_{kind}")
        _floor(bare)
        if kind == "broken":
            _broken(bare)
        try:
            storage_integrate.integrate_floor(dest, bare, 20)
            passed &= check(_text(dest) == before, f"external {kind}: nothing changes")
        except Exception as error:  # noqa: BLE001
            passed &= check(False, f"external {kind} raised {error!r}")
    return passed


def main():
    try:
        passed = merge_file_checks()
        passed &= manifest_checks()
        passed &= full_backup_checks()
        passed &= integrate_checks()
    finally:
        for path in _dirs:
            shutil.rmtree(path, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
