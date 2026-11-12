"""
storage_kinds.py -- the two window stores of a floor: D (deterministic) and P (probable).

D holds proven primes: every sieve engine's output, and pt1's output for windows wholly
below MR_DET_BOUND, where its 13 Miller-Rabin bases are a proof. P holds pt1's BPSW output
for windows that reach the bound: no BPSW counterexample is known, but none is proven
impossible there. The two never share a file:

    D: 10p{N}/source_primes/shard_NNNNN/PRIME_WINDOW_10p{N}_off_{tag}.bin
    P: 10p{N}/source_primes_P/shard_NNNNN/PRIME_WINDOW_10p{N}_off_{tag}_P.bin

Same sharding (window_sharding.py), PGS2 format and window grid. The _P suffix keeps a P
file out of every D reader's filename pattern even when it lands in the wrong folder.

Each engine plans its windows (continue, first gap, trim of a request) only from the store
it writes into (engine_target_idxs()), so a sieve engine and pt1 can cover the same range;
dp_verify.py then lets the D window prove or refute the P one.

A D window that proved its P window equal is a D/P window: the P file is removed and the
D file's tag (its name without .bin) is listed in 10p{N}/DP_PROVEN.txt, so the range is
stored once and still counts as present in the P store. A D/P entry counts only while its
D file exists; an entry without one is ignored.

Pure Python and dependency-free like window_sharding.py: imported by the WSL engines and
by the Windows GUI alike.
"""
import os
import re

import window_sharding

KIND_D = "D"
KIND_P = "P"
KINDS = (KIND_D, KIND_P)

# Sorenson-Webster: a strong probable prime to the 13 bases 2..41 below this is prime.
MR_DET_BOUND = 3_317_044_064_679_887_385_961_981

SOURCE_DIRNAMES = {KIND_D: "source_primes", KIND_P: "source_primes_P"}
_SUFFIX = {KIND_D: ".bin", KIND_P: "_P.bin"}

KIND_DP = "D/P"
PROVEN_FILENAME = "DP_PROVEN.txt"

ENGINE_PT1 = "pt1"
ENGINE_PT1_PSS = "pt1-pss"  # pt1 with the proof in the same pass: writes D only

_OFFSET_RE = re.compile(r"_off_(\d+)(M|k)?(?:_P)?\.bin$")


def source_dir(portal_folder, base_exponent, kind=KIND_D):
    return os.path.join(portal_folder, f"10p{base_exponent}", SOURCE_DIRNAMES[kind])


def window_filename(base_exponent, offset_label, kind=KIND_D):
    """offset_label is the scanners' format_offset(offset)."""
    return f"PRIME_WINDOW_10p{base_exponent}_off_{offset_label}{_SUFFIX[kind]}"


def window_path(portal_folder, base_exponent, offset, window_m, offset_label, kind=KIND_D):
    shard = window_sharding.shard_dir(source_dir(portal_folder, base_exponent, kind),
                                      window_sharding.shard_index_for_offset(offset, window_m))
    return os.path.join(shard, window_filename(base_exponent, offset_label, kind))


def kind_of_name(name):
    return KIND_P if name.endswith(_SUFFIX[KIND_P]) else KIND_D


def is_window_name(name, kind=KIND_D):
    return (name.startswith("PRIME_WINDOW_") and name.endswith(".bin")
            and kind_of_name(name) == kind)


def offset_from_name(name):
    """Offset encoded in a D or P window filename ("_off_{N}[M|k]"), or None."""
    m = _OFFSET_RE.search(name)
    if not m:
        return None
    n = int(m.group(1))
    if m.group(2) == "M":
        n *= 1_000_000
    elif m.group(2) == "k":
        n *= 1_000
    return n


def window_tag(name):
    """A D or P window filename without its suffix: the same tag for both kinds."""
    return name[:-len(_SUFFIX[kind_of_name(name)])]


def proven_path(portal_folder, base_exponent):
    return os.path.join(portal_folder, f"10p{base_exponent}", PROVEN_FILENAME)


def read_proven_tags(portal_folder, base_exponent):
    """Tags of the floor's D/P windows (empty when DP_PROVEN.txt is missing)."""
    path = proven_path(portal_folder, base_exponent)
    try:
        with open(path, encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()


def _write_proven_tags(portal_folder, base_exponent, tags):
    path = proven_path(portal_folder, base_exponent)
    if not tags:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(tags)) + "\n")
    os.replace(tmp, path)


def add_proven_tags(portal_folder, base_exponent, tags):
    """Adds tags to DP_PROVEN.txt (a union: backup, restore and integration merge the
    lists of two storages with it)."""
    current = read_proven_tags(portal_folder, base_exponent)
    merged = current | set(tags)
    if merged != current:
        _write_proven_tags(portal_folder, base_exponent, merged)


def discard_proven_tag(portal_folder, base_exponent, tag):
    update_proven_tags(portal_folder, base_exponent, discard={tag})


def update_proven_tags(portal_folder, base_exponent, add=(), discard=()):
    """Adds `add` and drops `discard` from DP_PROVEN.txt in one read and at most one write
    (a batch of comparisons updates the list once, not once per window)."""
    current = read_proven_tags(portal_folder, base_exponent)
    updated = (current | set(add)) - set(discard)
    if updated != current:
        _write_proven_tags(portal_folder, base_exponent, updated)


def display_kind(name, proven_tags):
    """"D", "P" or "D/P" for a window file listed in the Storage tab."""
    kind = kind_of_name(name)
    if kind == KIND_D and window_tag(name) in proven_tags:
        return KIND_DP
    return kind


def kind_for_window(lo, hi):
    """D when every number of [lo, hi) lies below MR_DET_BOUND, else P: a window straddling
    the bound is P as a whole."""
    return KIND_D if hi <= MR_DET_BOUND else KIND_P


def written_kind(engine, lo, hi):
    """The store `engine` writes the window [lo, hi) into: sieve engines always prove."""
    return kind_for_window(lo, hi) if engine == ENGINE_PT1 else KIND_D


def list_window_files(portal_folder, base_exponent, kind=KIND_D):
    """[(name, path), ...] of one store of a floor, in shard then name order."""
    return window_sharding.list_sharded_files(
        source_dir(portal_folder, base_exponent, kind),
        predicate=lambda name: is_window_name(name, kind))


def p_windows_on_grid(portal_folder, base_exponent, window_m):
    """[(offset, path), ...] of the floor's P windows on the window_m grid, offset ascending:
    the windows the verification P -> D takes, and how many of them."""
    found = []
    for name, path in list_window_files(portal_folder, base_exponent, KIND_P):
        offset = offset_from_name(name)
        if offset is not None and offset % window_m == 0:
            found.append((offset, path))
    found.sort()
    return found


def store_dir_for_name(portal_folder, base_exponent, name):
    """The store folder (not the shard) a window file named `name` belongs to."""
    return source_dir(portal_folder, base_exponent, kind_of_name(name))


def list_all_window_files(portal_folder, base_exponent):
    """[(name, path), ...] of both stores of a floor (names never collide: _P suffix)."""
    return [entry for kind in KINDS
            for entry in list_window_files(portal_folder, base_exponent, kind)]


def engine_target_idxs(portal_folder, base_exponent, window_m, engine):
    """target_idx (offset // window_m) of every window `engine` counts as done on this
    floor: the windows of the store it would write each of them into. A sieve engine sees
    D; pt1 sees P and the D/P windows, plus the D windows wholly below MR_DET_BOUND (on
    floor 24 both)."""
    base = 10 ** base_exponent
    idxs = set()
    is_pt1 = engine == ENGINE_PT1
    proven = read_proven_tags(portal_folder, base_exponent) if is_pt1 else set()
    for kind in (KINDS if is_pt1 else (KIND_D,)):
        for name, _path in list_window_files(portal_folder, base_exponent, kind):
            offset = offset_from_name(name)
            if offset is None:
                continue
            lo = base + offset
            if (written_kind(engine, lo, lo + window_m) == kind
                    or (kind == KIND_D and window_tag(name) in proven)):
                idxs.add(offset // window_m)
    return idxs
