"""
ktuple_hit_store_v2_1.py -- the on-disk state of ktuple_sieve_v2_1.py, all under the
pattern's own folder in the portal: the KTUPLE_CHECKPOINT_* file, the exhaustive
frontier read from constellation_finder_v2_1's done ranges, and the gap-safe split
of confirmed hits between the shared HITS_*.bin file and the PROVISIONAL_HITS_* log.
"""
import datetime
import os

import constellation_finder_v2_1 as _cf2  # module reference, not a copied PORTAL_FOLDER
                                           # binding, so this file always sees whatever
                                           # _cf2.PORTAL_FOLDER currently is (tests
                                           # monkeypatch it after import)
from constellation_finder_v2_1 import _append_hits_deduped  # a function reference is
                                                            # never reassigned


# ------------------------------------------------------------------------------------------
# Checkpoint -- one file per (floor, k, variant), living alongside that pattern's own
# hit file (_cf2.hit_file_path's own folder), storing only where the
# NEXT batch should start plus enough context to show in a status line. Never blocks on
# a strategy/window_m/step mismatch against a previous run (same "informational, not a
# hard stop" philosophy as _cf2.check_floor_boundary's own
# unresolved-boundary note) -- next_offset alone is authoritative; the rest is just
# provenance for whoever's watching the log.
# ------------------------------------------------------------------------------------------

def _ktuple_checkpoint_path(base_exponent, k, variant_id):
    return os.path.join(
        _cf2.PORTAL_FOLDER, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"KTUPLE_CHECKPOINT_10p{base_exponent}_k{k}_v{variant_id}.txt")


def read_ktuple_checkpoint(base_exponent, k, variant_id):
    """Returns {"next_offset", "step", "window_m", "strategy"} (ints/str) or None if no
    checkpoint exists yet, or if the file is missing/corrupt -- treated as "start
    fresh" either way, never raises."""
    path = _ktuple_checkpoint_path(base_exponent, k, variant_id)
    if not os.path.exists(path):
        return None
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "=" not in line:
                    continue
                key, _, val = line.strip().partition("=")
                values[key] = val
        return {"next_offset": int(values["next_offset"]), "step": int(values["step"]),
                "window_m": int(values["window_m"]), "strategy": values.get("strategy", "")}
    except (OSError, KeyError, ValueError):
        return None


def write_ktuple_checkpoint(base_exponent, k, variant_id, next_offset, step, window_m, strategy):
    path = _ktuple_checkpoint_path(base_exponent, k, variant_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"next_offset={next_offset}\n")
        f.write(f"step={step}\n")
        f.write(f"window_m={window_m}\n")
        f.write(f"strategy={strategy}\n")
        f.write(f"updated_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    os.replace(tmp_path, path)


def clear_ktuple_checkpoint(base_exponent, k, variant_id):
    """Explicit reset -- also reachable via run_ktuple_job(reset_checkpoint=True),
    which ignores rather than deletes an existing checkpoint (deleting only matters if
    something else wants to observe "no checkpoint" afterward, e.g. a UI's own status
    line -- run_ktuple_job's own in-process ignore-and-overwrite is enough for its own
    correctness either way)."""
    try:
        os.remove(_ktuple_checkpoint_path(base_exponent, k, variant_id))
    except OSError:
        pass


# ------------------------------------------------------------------------------------------
# Gap-safe hit recording -- see ktuple_sieve_v2_1.py's GAP-SAFE HIT RECORDING header
# note.
# ------------------------------------------------------------------------------------------

def _exhaustive_frontier_value(base_exponent):
    """Returns the smallest value NOT YET covered by constellation_finder_v2_1's own
    exhaustive, window-by-window scan for this floor -- i.e. every value strictly BELOW
    this has already been read by that scan (via its own gap-aware done-range
    checkpoint, see resolve_done_names()), so a hit down there is guaranteed to already
    be recorded in the shared hit file, or about to be, deterministically, the moment
    that scan reaches it. Anything at or above this value has NOT been exhaustively
    confirmed yet -- writing it into the shared file here would poison that file's own
    "last known value" against every smaller, genuinely new hit the exhaustive scan
    finds afterwards (see ktuple_sieve_v2_1.py's GAP-SAFE HIT RECORDING header note).

    Deliberately conservative: only the UNBROKEN prefix of done windows starting from
    the floor's very first window counts, even if constellation_finder_v2_1's own
    done-range set has a later range past a gap -- there's no reason to trust anything
    past the first gap for THIS purpose, and walking the window list in order is cheap.

    Returns -1 if not even the floor's first window is done yet (nothing is safe), or
    float('inf') if the whole floor is already exhaustively covered (everything is
    safe) -- both chosen so a plain `value < frontier` is always the right test."""
    windows = _cf2.list_source_windows(base_exponent)
    if not windows:
        return -1
    names = [w[0] for w in windows]
    done = _cf2.resolve_done_names(base_exponent, names)
    for i, (name, _path, base_prime) in enumerate(windows):
        if name not in done:
            return -1 if i == 0 else base_prime
    return float("inf")


def _provisional_hits_path(base_exponent, k, variant_id):
    return os.path.join(
        _cf2.PORTAL_FOLDER, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"PROVISIONAL_HITS_10p{base_exponent}_k{k}_v{variant_id}.txt")


def read_provisional_hits(base_exponent, k, variant_id):
    """Returns the set of confirmed hit values found AT OR AFTER constellation_finder_v2_1's
    own exhaustive frontier at the time they were found (see _record_confirmed_hits()
    below) -- plain text, one value per line, no ordering invariant of its own (unlike
    the shared HITS_*.bin format): even THIS module's own discovery order isn't
    monotonic across a batch for strategy=digit_sweep (see its own docstring), so a
    strict-increase format would be the wrong fit here. Empty set if the file doesn't
    exist yet."""
    path = _provisional_hits_path(base_exponent, k, variant_id)
    if not os.path.exists(path):
        return set()
    values = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                values.add(int(line))
    return values


def _append_provisional_hits(base_exponent, k, variant_id, values):
    """Appends only genuinely NEW values (deduped against what's already on disk) --
    returns how many were actually added. A plain append, not the atomic tmp-then-
    replace pattern CHECKPOINT.txt/write_done_ranges() use: this file is an
    informational log only, never read back by anything that needs it to survive a
    crash mid-write intact (unlike CHECKPOINT.txt, where a truncated file would throw
    away a whole floor's worth of progress) -- worst case here is losing one line."""
    existing = read_provisional_hits(base_exponent, k, variant_id)
    new_values = sorted(v for v in set(values) if v not in existing)
    if not new_values:
        return 0
    path = _provisional_hits_path(base_exponent, k, variant_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for v in new_values:
            f.write(f"{v}\n")
    return len(new_values)


def _record_confirmed_hits(base_exponent, k, variant_id, confirmed_values, frontier):
    """Splits confirmed_values against `frontier` (see _exhaustive_frontier_value())
    and routes each half to where it's safe: anything already covered by
    constellation_finder_v2_1's own exhaustive scan goes into the normal SHARED hit file,
    via _append_hits_deduped() (safe -- the exhaustive
    scan already found the same value deterministically, so this is always either a
    harmless duplicate or a legitimate confirmation); anything at or beyond the
    frontier goes into this pattern's own PROVISIONAL file instead of the shared one.
    Returns (appended_to_shared, appended_to_provisional)."""
    safe = [v for v in confirmed_values if v < frontier]
    ahead = [v for v in confirmed_values if v >= frontier]
    if safe:
        _append_hits_deduped(base_exponent, k, variant_id, safe)
    added_provisional = 0
    if ahead:
        added_provisional = _append_provisional_hits(base_exponent, k, variant_id, ahead)
        if added_provisional:
            print(f"[KTUPLE SIEVE v2] {added_provisional} confirmed hit(s) for k={k} "
                  f"variant={variant_id} are AT OR BEYOND constellation_finder_v2_1's own "
                  f"exhaustive frontier ({frontier}) -- written to this pattern's "
                  f"PROVISIONAL file instead of the shared one; will be rediscovered "
                  f"(and normally recorded) once the exhaustive scan reaches this range.")
    return len(safe), added_provisional
