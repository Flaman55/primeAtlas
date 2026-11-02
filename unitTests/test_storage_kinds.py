"""storage_kinds: the D (deterministic) and P (probable prime) window stores.

Checks: the MR bound and folder names; D and P filenames and the offset parsed back from
both; a P filename never matches a D reader's pattern (orchestrator_v3.find_auto_start's
regex, read from source); a window is D only when it lies wholly below MR_DET_BOUND; sieve
engines always write D, pt1 writes D below the bound and P from it on; each engine plans
from the store it writes into only: v5 sees D, pt1 sees P on floor 25 and D below the bound
plus P on floor 24; orchestrator_loop_helpers.find_auto_start and the Generation tab's
continuation / first-gap / trim / highest-floor helpers follow that view. Pure Python, runs
on Windows and WSL:
    python unitTests/test_storage_kinds.py
"""
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

W = 10 ** 7


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _label(n):
    """format_offset() of the scanners for the offsets used here (multiples of 10^6)."""
    return "0" if n == 0 else f"{n // 1_000_000}M"


def _touch(portal, floor, offset, kind):
    import storage_kinds as sk
    path = sk.window_path(portal, floor, offset, W, _label(offset), kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"PGS2\0" + bytes(8))
    return path


def check_names():
    import storage_kinds as sk
    passed = True
    passed &= check(sk.MR_DET_BOUND == 3_317_044_064_679_887_385_961_981, "MR bound value")
    passed &= check(sk.SOURCE_DIRNAMES == {"D": "source_primes", "P": "source_primes_P"},
                    f"store folders {sk.SOURCE_DIRNAMES}")
    d = sk.window_filename(25, "120M", sk.KIND_D)
    p = sk.window_filename(25, "120M", sk.KIND_P)
    passed &= check(d == "PRIME_WINDOW_10p25_off_120M.bin", f"D name {d}")
    passed &= check(p == "PRIME_WINDOW_10p25_off_120M_P.bin", f"P name {p}")
    passed &= check(sk.kind_of_name(d) == "D" and sk.kind_of_name(p) == "P", "kind from name")
    passed &= check(sk.offset_from_name(d) == 120_000_000 and sk.offset_from_name(p) == 120_000_000
                    and sk.offset_from_name("PRIME_WINDOW_10p9_off_5k.bin") == 5000
                    and sk.offset_from_name("PRIME_WINDOW_10p9_off_0_P.bin") == 0
                    and sk.offset_from_name("notes.txt") is None,
                    "offset parsed from D, P, k-suffixed and foreign names")
    passed &= check(sk.is_window_name(d, "D") and not sk.is_window_name(p, "D")
                    and sk.is_window_name(p, "P") and not sk.is_window_name(d, "P"),
                    "is_window_name separates the stores")
    with open(os.path.join(ROOT, "prime_sieve", "orchestrator_v3.py"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r're\.compile\(rf"(\^PRIME_WINDOW_[^"]+)"\)', src)
    if m:
        d_pattern = re.compile(m.group(1).replace("{base_exponent}", "25"))
        passed &= check(d_pattern.match(d) and not d_pattern.match(p),
                        "orchestrator's D filename regex matches D, never P")
    path = sk.window_path("/portal", 25, 120_000_000_000, W, "120000M", sk.KIND_P)
    passed &= check(path.replace("\\", "/")
                    == "/portal/10p25/source_primes_P/shard_00002/PRIME_WINDOW_10p25_off_120000M_P.bin",
                    f"P path uses the same sharding ({path})")
    return passed


def check_kind_rule():
    import storage_kinds as sk
    b = sk.MR_DET_BOUND
    passed = True
    passed &= check(sk.kind_for_window(b - 10, b) == "D", "window ending exactly at the bound is D")
    passed &= check(sk.kind_for_window(b - 10, b + 1) == "P", "window straddling the bound is P")
    passed &= check(sk.kind_for_window(b, b + 10) == "P", "window from the bound on is P")
    passed &= check(sk.kind_for_window(10 ** 19, 10 ** 19 + W) == "D", "floor 19 is D")
    for engine in ("v3", "v4", "v4.1", "v5"):
        passed &= check(sk.written_kind(engine, 10 ** 25, 10 ** 25 + W) == "D",
                        f"{engine} writes D even above the bound")
    passed &= check(sk.written_kind("pt1", 10 ** 22, 10 ** 22 + W) == "D", "pt1 below the bound -> D")
    passed &= check(sk.written_kind("pt1", 10 ** 25, 10 ** 25 + W) == "P", "pt1 at floor 25 -> P")
    return passed


def check_views(tmp):
    import storage_kinds as sk
    import orchestrator_loop_helpers as helpers
    from primeatlas.generation import generation as gen
    passed = True
    # floor 25: D windows 0..2, P windows 0, 5, 6
    for i in (0, 1, 2):
        _touch(tmp, 25, i * W, "D")
    for i in (0, 5, 6):
        _touch(tmp, 25, i * W, "P")
    passed &= check(sk.engine_target_idxs(tmp, 25, W, "v5") == {0, 1, 2}, "v5 sees D only on floor 25")
    passed &= check(sk.engine_target_idxs(tmp, 25, W, "pt1") == {0, 5, 6}, "pt1 sees P only on floor 25")
    passed &= check(helpers.find_auto_start(25, tmp, W, engine="v5") == 3
                    and helpers.find_auto_start(25, tmp, W, engine="pt1") == 7,
                    "find_auto_start continues each engine from its own store")
    passed &= check(gen.find_continuation_target_idx(tmp, 25, W, engine="v5") == 3
                    and gen.find_continuation_target_idx(tmp, 25, W, engine="pt1") == 7,
                    "GUI continuation per engine")
    passed &= check(gen.find_first_gap_target_idx(tmp, 25, W, engine="v5") == 3
                    and gen.find_first_gap_target_idx(tmp, 25, W, engine="pt1") == 1,
                    "GUI first gap per engine")
    passed &= check(gen._trim_existing_from_target_idx_range(tmp, 25, 0, 4, W, engine="pt1") == (1, 3)
                    and gen._trim_existing_from_target_idx_range(tmp, 25, 0, 4, W, engine="v5") == (3, 1),
                    "GUI trim of an existing edge per engine")
    passed &= check(gen.find_continuation_target_idx(tmp, 25, W) == 3,
                    "GUI default engine (v5) sees D")
    # floor 24: the bound sits at offset b - 10^24; D windows below and above it, one P above
    base = 10 ** 24
    below = (sk.MR_DET_BOUND - base) // W - 5
    above = below + 10
    for i in (below, above):
        _touch(tmp, 24, i * W, "D")
    _touch(tmp, 24, (above + 1) * W, "P")
    passed &= check(sk.engine_target_idxs(tmp, 24, W, "v5") == {below, above},
                    "v5 sees every D window on floor 24")
    passed &= check(sk.engine_target_idxs(tmp, 24, W, "pt1") == {below, above + 1},
                    "pt1 on floor 24: D below the bound plus P")
    # floor 26: D windows 0..2, window 1 proven D/P, P window 4, a D/P entry without D (9)
    for i in (0, 1, 2):
        _touch(tmp, 26, i * W, "D")
    _touch(tmp, 26, 4 * W, "P")
    sk.add_proven_tags(tmp, 26, {sk.window_tag(sk.window_filename(26, _label(i * W))) for i in (1, 9)})
    passed &= check(sk.engine_target_idxs(tmp, 26, W, "pt1") == {1, 4},
                    "pt1 sees P plus D/P windows whose D file exists")
    passed &= check(sk.engine_target_idxs(tmp, 26, W, "v5") == {0, 1, 2}, "v5 ignores D/P marks")
    passed &= check(sk.display_kind(sk.window_filename(26, _label(W)), sk.read_proven_tags(tmp, 26)) == "D/P"
                    and sk.display_kind(sk.window_filename(26, "0"), sk.read_proven_tags(tmp, 26)) == "D"
                    and sk.display_kind(sk.window_filename(26, "0", "P"), set()) == "P",
                    "display kind D, P, D/P")
    sk.add_proven_tags(tmp, 26, {sk.window_tag(sk.window_filename(26, "0"))})
    passed &= check(len(sk.read_proven_tags(tmp, 26)) == 3, "add_proven_tags merges (union)")
    # a floor with P only is a populated floor for pt1, not for v5
    _touch(tmp, 27, 0, "P")
    passed &= check(gen.find_highest_populated_floor(tmp, engine="pt1") == 27
                    and gen.find_highest_populated_floor(tmp, engine="v5") == 26,
                    "highest populated floor per engine")
    return passed


def main():
    passed = check_names()
    passed &= check_kind_rule()
    tmp = tempfile.mkdtemp(prefix="storage_kinds_")
    try:
        passed &= check_views(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
