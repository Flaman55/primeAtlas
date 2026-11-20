"""
machines_file.py -- benchmark_machines.json at the storage root: the computers the benchmark
rows name by machine_id (windows_hardware.machine_id()), so a row can be read with the CPU
and RAM it ran on.

{"format": 1, "machines": {machine_id: [entry, ...]}}, each history in `since` order. An
entry:
- since: when this hardware was first recorded ("YYYY-MM-DD HH:MM:SS UTC", the format of the
  log's run_timestamp_utc, so the two compare as text);
- auto: the details Windows gave (hardware_details.HardwareDetails, known fields only);
- manual: MANUAL_FIELDS, typed by the person (None = not typed);
- edited_at: the last change of manual (since when never typed);
- asked: the app already asked to type the manual values for this entry.
A known auto value that changes (RAM swapped) starts a new entry, so older rows keep the
hardware they ran on (entry_for()); the manual values carry over and the app asks again.

Every write is atomic (temp file + os.replace()). A file that is not this shape raises
MachinesFileCorrupt and is never overwritten here; preserve_corrupt() keeps a copy of it.
Pure logic, no tkinter.
"""
import copy
import json
import os
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

FILE_NAME = "benchmark_machines.json"
FORMAT_VERSION = 1
MANUAL_FIELDS = ("architecture", "year", "turbo_mhz", "cl", "xmp")
_WHOLE_FIELDS = ("year", "turbo_mhz", "cl")


class MachinesFileCorrupt(Exception):
    """The file exists but is not benchmark_machines.json's shape."""


def path(storage):
    return os.path.join(storage, FILE_NAME)


def timestamp(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")


def _check_shape(data):
    machines = data.get("machines") if isinstance(data, dict) else None
    if not isinstance(machines, dict):
        raise MachinesFileCorrupt("no machines")
    for history in machines.values():
        if not isinstance(history, list):
            raise MachinesFileCorrupt("a history is not a list")
        for entry in history:
            if (not isinstance(entry, dict) or not isinstance(entry.get("since"), str)
                    or not isinstance(entry.get("auto", {}), dict)
                    or not isinstance(entry.get("manual", {}), dict)):
                raise MachinesFileCorrupt("an entry is not one")
    return machines


def load(storage):
    """{machine_id: [entry, ...]}; {} without a file; MachinesFileCorrupt for a broken one."""
    try:
        with open(path(storage), encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
    except ValueError as error:
        raise MachinesFileCorrupt(str(error)) from error
    return _check_shape(data)


def save(storage, machines):
    target = path(storage)
    tmp_path = f"{target}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"format": FORMAT_VERSION, "machines": machines}, f, indent=2,
                      ensure_ascii=False)
        os.replace(tmp_path, target)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def preserve_corrupt(storage, now=None):
    """Copies the broken file next to itself under a new name; returns the copy's path."""
    stem = f"{path(storage)}.broken_{(now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%S')}"
    target, n = stem, 1
    while os.path.exists(target):
        n += 1
        target = f"{stem}_{n}"
    shutil.copyfile(path(storage), target)
    return target


def _known(details):
    if details is None:
        return {}
    values = asdict(details) if is_dataclass(details) else dict(details)
    return {k: v for k, v in values.items() if v is not None}


def _empty_manual():
    return {field: None for field in MANUAL_FIELDS}


def current(machines, machine_id):
    """The newest entry of `machine_id`, None when it has none."""
    history = machines.get(machine_id) if machine_id else None
    return history[-1] if history else None


def entry_for(machines, machine_id, run_timestamp):
    """The entry a run at `run_timestamp` ran with: the newest one recorded by then, or the
    first one for a run older than every entry; None for an unknown or blank machine_id."""
    history = machines.get(machine_id) if machine_id else None
    if not history:
        return None
    found = history[0]
    for entry in history:
        if entry["since"] <= str(run_timestamp or ""):
            found = entry
    return found


def record(storage, machine_id, details, now=None):
    """Records this computer's details: "added" (first entry, or a new one after a known
    value changed), "updated" (a value known only now), "unchanged" (no write) or "skipped"
    (no id or nothing known, no write)."""
    known = _known(details)
    if not machine_id or not known:
        return "skipped"
    machines = load(storage)
    history = machines.setdefault(machine_id, [])
    latest = history[-1] if history else None
    stamp = timestamp(now)
    if latest is None:
        history.append({"since": stamp, "edited_at": stamp, "asked": False, "auto": known,
                        "manual": _empty_manual()})
        status = "added"
    else:
        auto = latest.setdefault("auto", {})
        if any(k in auto and auto[k] != v for k, v in known.items()):
            history.append({"since": stamp, "edited_at": latest.get("edited_at", stamp),
                            "asked": False, "auto": {**auto, **known},
                            "manual": {**_empty_manual(), **latest.get("manual", {})}})
            status = "added"
        elif any(k not in auto for k in known):
            auto.update(known)
            status = "updated"
        else:
            return "unchanged"
    save(storage, machines)
    return status


def _manual_value(field, value):
    if value is None or value == "":
        return None
    if field == "architecture":
        return str(value).strip() or None
    if field == "xmp":
        return bool(value)
    return int(value)


def set_manual(storage, machine_id, manual, now=None):
    """Stores the typed values (MANUAL_FIELDS; a missing or blank one is None, others are
    dropped) on the current entry of `machine_id` and marks it asked. KeyError when the
    machine has no entry."""
    machines = load(storage)
    entry = current(machines, machine_id)
    if entry is None:
        raise KeyError(machine_id)
    entry["manual"] = {f: _manual_value(f, manual.get(f)) for f in MANUAL_FIELDS}
    entry["edited_at"] = timestamp(now)
    entry["asked"] = True
    save(storage, machines)


def mark_asked(storage, machine_id):
    machines = load(storage)
    entry = current(machines, machine_id)
    if entry is not None and not entry.get("asked"):
        entry["asked"] = True
        save(storage, machines)


def needs_asking(entry):
    return entry is not None and not entry.get("asked")


def merge(current_machines, other):
    """Every entry of both, each history in since order; the same machine and since in both:
    the later edited_at wins, a tie keeps current_machines'."""
    merged = copy.deepcopy(current_machines)
    for machine_id, history in (other or {}).items():
        mine = {e["since"]: e for e in merged.get(machine_id, [])}
        for entry in history:
            kept = mine.get(entry["since"])
            if kept is None or str(entry.get("edited_at", "")) > str(kept.get("edited_at", "")):
                mine[entry["since"]] = copy.deepcopy(entry)
        merged[machine_id] = [mine[since] for since in sorted(mine)]
    return merged


def merge_into_storage(storage, other):
    """Merges `other` ({machine_id: [entry]}, None = nothing) into the storage file: "merged"
    when it changed, "unchanged" otherwise; MachinesFileCorrupt for a broken storage file."""
    if not other:
        return "unchanged"
    machines = load(storage)
    merged = merge(machines, other)
    if merged == machines:
        return "unchanged"
    save(storage, merged)
    return "merged"


def merge_file_into(target_dir, source_dir, now=None, replace_broken_target=False):
    """Merges source_dir's file into target_dir's: "merged", "unchanged" (nothing new, or no
    source file) or "broken". A broken source changes nothing; a broken target is copied
    aside (preserve_corrupt()) and left as it is, or with replace_broken_target rewritten
    from the source."""
    if not os.path.exists(path(source_dir)):
        return "unchanged"
    try:
        source = load(source_dir)
    except MachinesFileCorrupt:
        return "broken"
    try:
        return merge_into_storage(target_dir, source)
    except MachinesFileCorrupt:
        preserve_corrupt(target_dir, now)
        if replace_broken_target:
            save(target_dir, merge({}, source))
        return "broken"
