"""
test_machines_file.py -- the computers of the benchmark rows (primeatlas/core/machines_file.py):
benchmark_machines.json at the storage root, one history of entries per machine_id.

A. record(storage, machine_id, details, now):
   - no file: writes one entry (since = now, auto = the known details, manual empty, not
     asked); "added";
   - the same details again: "unchanged", the file is not rewritten;
   - a field unknown before and known now fills the current entry ("updated", no new entry);
     a field unknown now keeps its known value;
   - a known field with another value (RAM swapped): a new entry since now with the new
     details, the manual values carried over, not asked; the old entry stays as it was;
   - no machine_id, or details with nothing known: "skipped", no file;
   - two computers keep two histories side by side.
B. The file: written atomically (no temporary file left), UTF-8 JSON with a format version;
   load() of an absent file is {}; a broken file (bad JSON, wrong shape) raises
   MachinesFileCorrupt and record()/set_manual() never overwrite it; preserve_corrupt()
   copies it next to itself under a new name and returns that path, the original untouched.
C. set_manual(storage, machine_id, manual, now): stores the manual fields (architecture, year,
   turbo_mhz, cl, xmp) on the current entry, empty ones as None, sets edited_at = now and
   asked; unknown fields are dropped; a machine with no entry raises KeyError.
   mark_asked() sets asked only. needs_asking(entry) is not asked.
D. entry_for(machines, machine_id, run_timestamp): the newest entry whose since is not after
   the run; a run older than every entry gets the first one; an unknown machine_id or a blank
   one gives None. current() is the newest entry.
E. merge(current, other): every entry of both (union by machine_id and since), each history
   in since order; the same machine and since in both: the later edited_at wins, a tie keeps
   current; merge with {} changes nothing. merge_into_storage(storage, other) writes the
   merged file only when it differs, returns "merged" / "unchanged", None other leaves the
   storage file untouched ("unchanged"), a broken storage file raises MachinesFileCorrupt and
   stays as it is.

Usage:
    python unitTests/test_machines_file.py
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


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


GB = 1024 ** 3
T1 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)
ID = "a1b2c3d4e5f6"


def details(**changes):
    from primeatlas.core.hardware_details import HardwareDetails
    base = dict(cpu_name="AMD Ryzen 9 5900X 12-Core Processor", cpu_maker="AuthenticAMD",
                cpu_family="AMD64 Family 25 Model 33 Stepping 2", cores=12, threads=24,
                base_mhz=3701, l2_kb=6144, l3_kb=65536, ram_bytes=64 * GB, ram_type="DDR4",
                ram_mts=3600, ram_modules=4)
    base.update(changes)
    return HardwareDetails(**base)


def stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def record_checks(mf, storage):
    passed = True
    path = mf.path(storage)
    passed &= check(mf.load(storage) == {}, "no file: load() is {}")
    passed &= check(mf.record(storage, ID, details(), T1) == "added" and os.path.isfile(path),
                    "first record: added, file written")
    entry = mf.load(storage)[ID][0]
    passed &= check(entry["since"] == stamp(T1) and entry["auto"]["ram_mts"] == 3600
                    and entry["auto"]["cpu_name"].startswith("AMD Ryzen")
                    and all(v is None for v in entry["manual"].values())
                    and set(entry["manual"]) == set(mf.MANUAL_FIELDS)
                    and not entry["asked"], f"entry: since, auto, empty manual ({entry})")
    before = open(path, "rb").read()
    mtime = os.stat(path).st_mtime_ns
    passed &= check(mf.record(storage, ID, details(), T2) == "unchanged"
                    and open(path, "rb").read() == before and os.stat(path).st_mtime_ns == mtime,
                    "same details: unchanged, file not rewritten")

    shutil.rmtree(storage)
    os.makedirs(storage)
    mf.record(storage, ID, details(l3_kb=None, ram_type=None), T1)
    passed &= check(mf.record(storage, ID, details(), T2) == "updated"
                    and len(mf.load(storage)[ID]) == 1
                    and mf.load(storage)[ID][0]["auto"]["l3_kb"] == 65536,
                    "a field known only now fills the current entry")
    passed &= check(mf.record(storage, ID, details(ram_mts=None), T2) == "unchanged"
                    and mf.load(storage)[ID][0]["auto"]["ram_mts"] == 3600,
                    "a field unknown now keeps its value")

    mf.set_manual(storage, ID, {"architecture": "Zen 3", "cl": 16}, T2)
    passed &= check(mf.record(storage, ID, details(ram_bytes=128 * GB, ram_mts=3200), T3)
                    == "added", "RAM swapped: a new entry")
    history = mf.load(storage)[ID]
    passed &= check(len(history) == 2 and history[0]["auto"]["ram_bytes"] == 64 * GB
                    and history[0]["since"] == stamp(T1)
                    and history[1]["since"] == stamp(T3)
                    and history[1]["auto"]["ram_bytes"] == 128 * GB
                    and history[1]["manual"]["architecture"] == "Zen 3"
                    and history[1]["manual"]["cl"] == 16 and not history[1]["asked"]
                    and history[0]["asked"],
                    "old entry kept; new one carries the manual values and asks again")

    passed &= check(mf.record(storage, "ffff00001111", details(cpu_name="Intel i5-8250U"), T1)
                    == "added" and set(mf.load(storage)) == {ID, "ffff00001111"},
                    "two computers side by side")
    other = tempfile.mkdtemp(prefix="primeatlas_machines_skip_")
    try:
        from primeatlas.core.hardware_details import HardwareDetails
        passed &= check(mf.record(other, None, details(), T1) == "skipped"
                        and mf.record(other, "", details(), T1) == "skipped"
                        and mf.record(other, ID, HardwareDetails(), T1) == "skipped"
                        and mf.record(other, ID, None, T1) == "skipped"
                        and not os.path.exists(mf.path(other)),
                        "no id or nothing known: skipped, no file")
    finally:
        shutil.rmtree(other, ignore_errors=True)
    return passed


def file_checks(mf, storage):
    passed = True
    path = mf.path(storage)
    passed &= check(os.path.basename(path) == "benchmark_machines.json"
                    and os.path.dirname(path) == storage, f"file at the storage root ({path})")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    passed &= check(data.get("format") == mf.FORMAT_VERSION and ID in data.get("machines", {}),
                    "JSON with a format version and the machines")
    passed &= check(not [n for n in os.listdir(storage) if ".tmp" in n],
                    "no temporary file left")

    for broken in ("{not json", json.dumps([1, 2]), json.dumps({"machines": {ID: "x"}}),
                   json.dumps({"machines": {ID: [{"auto": {}}]}})):
        with open(path, "w", encoding="utf-8") as f:
            f.write(broken)
        raised = []
        for action in (lambda: mf.load(storage),
                       lambda: mf.record(storage, ID, details(), T1),
                       lambda: mf.set_manual(storage, ID, {"cl": 14}, T1)):
            try:
                action()
                raised.append(False)
            except mf.MachinesFileCorrupt:
                raised.append(True)
        with open(path, encoding="utf-8") as f:
            kept = f.read()
        passed &= check(all(raised) and kept == broken,
                        f"broken {broken[:30]!r}: raises, never overwritten ({raised})")
    copy = mf.preserve_corrupt(storage, T1)
    with open(copy, encoding="utf-8") as f:
        copied = f.read()
    with open(path, encoding="utf-8") as f:
        original = f.read()
    passed &= check(copy != path and os.path.dirname(copy) == storage and copied == original,
                    f"preserve_corrupt copies it next to itself ({os.path.basename(copy)})")
    os.remove(path)
    return passed


def manual_checks(mf, storage):
    passed = True
    mf.record(storage, ID, details(), T1)
    entry = mf.current(mf.load(storage), ID)
    passed &= check(mf.needs_asking(entry), "a new entry needs asking")
    mf.mark_asked(storage, ID)
    entry = mf.current(mf.load(storage), ID)
    passed &= check(not mf.needs_asking(entry) and entry["manual"]["cl"] is None,
                    "mark_asked: asked, manual untouched")
    mf.set_manual(storage, ID, {"architecture": " Zen 3 ", "year": 2020, "turbo_mhz": 4800,
                                "cl": 16, "xmp": True, "colour": "red"}, T2)
    entry = mf.current(mf.load(storage), ID)
    passed &= check(entry["manual"] == {"architecture": "Zen 3", "year": 2020, "turbo_mhz": 4800,
                                        "cl": 16, "xmp": True}
                    and entry["edited_at"] == stamp(T2) and entry["asked"],
                    f"set_manual stores the five fields, drops others ({entry['manual']})")
    mf.set_manual(storage, ID, {"architecture": "", "year": None, "xmp": None}, T3)
    entry = mf.current(mf.load(storage), ID)
    passed &= check(entry["manual"]["architecture"] is None and entry["manual"]["year"] is None
                    and entry["manual"]["xmp"] is None and entry["manual"]["cl"] is None,
                    "emptied fields are None")
    try:
        mf.set_manual(storage, "000000000000", {"cl": 14}, T3)
        passed &= check(False, "set_manual of an unknown machine raised nothing")
    except KeyError:
        passed &= check(True, "set_manual of an unknown machine: KeyError")
    os.remove(mf.path(storage))
    return passed


def entry_for_checks(mf):
    first = {"since": stamp(T1), "edited_at": stamp(T1), "asked": True, "auto": {"ram_mts": 3600},
             "manual": {}}
    second = dict(first, since=stamp(T3), auto={"ram_mts": 3200})
    machines = {ID: [first, second]}
    passed = True
    for run, expected in ((stamp(T1), first), (stamp(T2), first), (stamp(T3), second),
                          ("2027-01-01 00:00:00 UTC", second),
                          ("2026-01-01 00:00:00 UTC", first)):
        passed &= check(mf.entry_for(machines, ID, run) is expected,
                        f"run {run}: entry since {expected['since']}")
    passed &= check(mf.entry_for(machines, "unknown", stamp(T2)) is None
                    and mf.entry_for(machines, "", stamp(T2)) is None
                    and mf.entry_for(machines, None, stamp(T2)) is None,
                    "unknown or blank machine: None")
    passed &= check(mf.current(machines, ID) is second and mf.current(machines, "x") is None,
                    "current() is the newest entry")
    return passed


def merge_checks(mf, storage):
    passed = True

    def entry(since, edited, cl):
        return {"since": stamp(since), "edited_at": stamp(edited), "asked": True,
                "auto": {"ram_mts": 3600}, "manual": {"cl": cl}}

    current = {ID: [entry(T1, T1, 16), entry(T3, T3, 18)]}
    other = {ID: [entry(T1, T2, 14), entry(T2, T2, 15)], "ffff00001111": [entry(T1, T1, 22)]}
    merged = mf.merge(current, other)
    passed &= check([e["since"] for e in merged[ID]] == [stamp(T1), stamp(T2), stamp(T3)]
                    and merged[ID][0]["manual"]["cl"] == 14 and merged[ID][2]["manual"]["cl"] == 18
                    and merged["ffff00001111"][0]["manual"]["cl"] == 22,
                    "union in since order; same since: later edited_at wins")
    tie = mf.merge({ID: [entry(T1, T2, 16)]}, {ID: [entry(T1, T2, 99)]})
    passed &= check(tie[ID][0]["manual"]["cl"] == 16, "tie keeps current")
    passed &= check(mf.merge(current, {}) == current, "merge with {} changes nothing")

    mf.save(storage, current)
    path = mf.path(storage)
    before = open(path, "rb").read()
    passed &= check(mf.merge_into_storage(storage, None) == "unchanged"
                    and open(path, "rb").read() == before, "None other: untouched")
    passed &= check(mf.merge_into_storage(storage, {ID: [entry(T1, T1, 16)]}) == "unchanged"
                    and open(path, "rb").read() == before, "nothing new: untouched")
    passed &= check(mf.merge_into_storage(storage, other) == "merged"
                    and mf.load(storage) == merged, "new entries: merged and written")
    os.remove(path)
    passed &= check(mf.merge_into_storage(storage, other) == "merged"
                    and mf.load(storage) == mf.merge({}, other), "no storage file: written")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{broken")
    try:
        mf.merge_into_storage(storage, other)
        passed &= check(False, "broken storage file: no error")
    except mf.MachinesFileCorrupt:
        with open(path, encoding="utf-8") as f:
            passed &= check(f.read() == "{broken", "broken storage file: raises, untouched")
    os.remove(path)
    return passed


def main():
    from primeatlas.core import machines_file as mf
    storage = tempfile.mkdtemp(prefix="primeatlas_machines_")
    try:
        passed = record_checks(mf, storage)
        passed &= file_checks(mf, storage)
        passed &= manual_checks(mf, storage)
        passed &= entry_for_checks(mf)
        passed &= merge_checks(mf, storage)
    finally:
        shutil.rmtree(storage, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
