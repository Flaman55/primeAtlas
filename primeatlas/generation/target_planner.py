"""Target-set planner: given target points (a center and a radius each), which windows one Atlas
run covers and which Pseudosquares checks, with the fewest estimated seconds. No tkinter.

Both methods work on the window grid of a floor (window_m numbers per window), so a target
[center - radius, center + radius] becomes the windows it touches, split at a floor
boundary (a run never leaves its floor). Repeated and overlapping targets share windows;
windows already in the storage are dropped. The needed windows of a floor form blocks
(maximal runs of consecutive windows, cut at the cap).

A group of consecutive blocks is checked either by one Atlas run over its whole span (the
gaps between the blocks included, at most `cap` windows) or by one Pseudosquares run per
block; a single block takes the faster of the two. Dynamic programming over the blocks of
each floor picks the partition with the fewest total seconds; a tie goes to Atlas, whose
run stores its primes. The costs are callables, so the time model stays outside:
atlas_cost(floor, idx, windows) -> (seconds, engine) or None, pss_cost(floor, idx,
windows) -> seconds or None (None: no calibration).
"""
import bisect
import re
from collections import namedtuple

from .quick_number import _eval_quick_number

MAX_TARGETS = 10_000
"""Most targets one plan takes; arbitrary, keeps a pasted list from freezing the view."""

MIN_NUMBER = 10 ** 7
"""Floors 0..6 generate in seconds as one range (Floor mode); the planner starts above them."""

METHOD_ATLAS = "atlas"
METHOD_PSS = "pseudosquares"

Target = namedtuple("Target", "line lo hi")
LineError = namedtuple("LineError", "line key text")
ParseResult = namedtuple("ParseResult", "targets errors")
Group = namedtuple("Group", "floor idx windows method engine seconds blocks targets lo hi")
Plan = namedtuple("Plan", "groups seconds atlas_seconds pss_seconds stored_targets unplanned")

_SEPARATORS = re.compile(r"[\s;,]+")


def _parse_line(text):
    """(center, radius) or an error key."""
    fields = [f for f in _SEPARATORS.split(text) if f]
    if len(fields) > 2:
        return "too_many_fields"
    numbers = [_eval_quick_number(f) for f in fields]
    if any(n is None for n in numbers):
        return "not_number"
    center, radius = numbers[0], numbers[1] if len(numbers) == 2 else 0
    if center < 1:
        return "center_below_one"
    if radius < 0:
        return "radius_negative"
    return center, radius


def parse_targets(text, max_number, max_targets=MAX_TARGETS):
    """ParseResult of the planner's text: one Target per valid line, one LineError per bad
    line (line numbers from 1). Blank lines and '#' comments are skipped."""
    targets, errors = [], []
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _parse_line(line)
        if isinstance(parsed, str):
            errors.append(LineError(number, parsed, line))
            continue
        center, radius = parsed
        lo, hi = max(1, center - radius), center + radius
        if lo < MIN_NUMBER:
            errors.append(LineError(number, "below_min", line))
        elif hi > max_number:
            errors.append(LineError(number, "above_max", line))
        else:
            targets.append(Target(number, lo, hi))
    if len(targets) > max_targets:
        errors.append(LineError(targets[max_targets].line, "too_many", ""))
    return ParseResult(targets, errors)


def _floor(number):
    return len(str(number)) - 1


def target_parts(target, window_m):
    """[(floor, first window, last window)] the target touches, one entry per floor."""
    parts = []
    lo = target.lo
    while lo <= target.hi:
        floor = _floor(lo)
        base = 10 ** floor
        hi = min(target.hi, 10 ** (floor + 1) - 1)
        parts.append((floor, (lo - base) // window_m, (hi - base) // window_m))
        lo = hi + 1
    return parts


def make_blocks(idxs, cap):
    """[(first window, windows)]: maximal runs of consecutive sorted window indices, each cut
    into pieces of at most `cap` windows."""
    blocks = []
    for idx in idxs:
        if blocks and blocks[-1][0] + blocks[-1][1] == idx and blocks[-1][1] < cap:
            blocks[-1] = (blocks[-1][0], blocks[-1][1] + 1)
        else:
            blocks.append((idx, 1))
    return blocks


def _single(atlas_cost, pss_cost, floor, block):
    """(seconds, method, engine) of the faster method for one block, or None."""
    atlas = atlas_cost(floor, block[0], block[1])
    pss = pss_cost(floor, block[0], block[1])
    if atlas is not None and (pss is None or atlas[0] <= pss):
        return atlas[0], METHOD_ATLAS, atlas[1]
    if pss is not None:
        return pss, METHOD_PSS, None
    return None


def _plan_floor(floor, blocks, cap, atlas_cost, pss_cost):
    """[(first block, last block, seconds, method, engine)] of the fewest total seconds."""
    best = [0.0] + [None] * len(blocks)
    choice = [None] * len(blocks)
    for j, last in enumerate(blocks):
        end = last[0] + last[1]
        single = _single(atlas_cost, pss_cost, floor, last)
        if single is not None:
            best[j + 1] = best[j] + single[0]
            choice[j] = (j, single)
        for i in range(j - 1, -1, -1):
            span = end - blocks[i][0]
            if span > cap:
                break
            atlas = atlas_cost(floor, blocks[i][0], span)
            if atlas is None:
                break
            total = best[i] + atlas[0]
            if best[j + 1] is None or total < best[j + 1]:
                best[j + 1] = total
                choice[j] = (i, (atlas[0], METHOD_ATLAS, atlas[1]))
    groups = []
    j = len(blocks) - 1
    while j >= 0:
        i, (seconds, method, engine) = choice[j]
        groups.append((i, j, seconds, method, engine))
        j = i - 1
    return groups[::-1]


def plan_targets(targets, window_m, stored, cap_for, atlas_cost, pss_cost):
    """Plan of the targets. stored(floor): the window indices already in the storage;
    cap_for(floor): the widest Atlas run. A block neither method can time is unplanned and
    the plan's seconds are then None."""
    needed = {}            # floor -> set of window indices
    target_windows = []    # per target: [(floor, idx)] it still needs
    stored_targets = 0
    stored_cache = {}
    for target in targets:
        own = []
        for floor, first, last in target_parts(target, window_m):
            if floor not in stored_cache:
                stored_cache[floor] = set(stored(floor))
            own.extend((floor, idx) for idx in range(first, last + 1)
                       if idx not in stored_cache[floor])
        if not own:
            stored_targets += 1
        target_windows.append(own)
        for floor, idx in own:
            needed.setdefault(floor, set()).add(idx)

    groups, unplanned = [], []
    atlas_total = pss_total = 0.0
    for floor in sorted(needed):
        cap = max(1, cap_for(floor))
        blocks = make_blocks(sorted(needed[floor]), cap)
        plannable = []
        for block in blocks:
            atlas = atlas_cost(floor, block[0], block[1])
            pss = pss_cost(floor, block[0], block[1])
            atlas_total = None if atlas is None or atlas_total is None else atlas_total + atlas[0]
            pss_total = None if pss is None or pss_total is None else pss_total + pss
            (plannable if atlas is not None or pss is not None else unplanned).append(block)
        if not plannable:
            continue
        base = 10 ** floor
        for i, j, seconds, method, engine in _plan_floor(floor, plannable, cap, atlas_cost,
                                                          pss_cost):
            idx = plannable[i][0]
            windows = plannable[j][0] + plannable[j][1] - idx
            groups.append(Group(floor, idx, windows, method, engine, seconds,
                                tuple(plannable[i:j + 1]), 0, base + idx * window_m,
                                base + (idx + windows) * window_m - 1))

    # Groups are sorted by (floor, first window) and never overlap: bisect finds a window's.
    keys = [(g.floor, g.idx) for g in groups]
    counts = [0] * len(groups)
    for own in target_windows:
        hit = set()
        for floor, idx in own:
            k = bisect.bisect_right(keys, (floor, idx)) - 1
            if k >= 0 and groups[k].floor == floor and idx < groups[k].idx + groups[k].windows:
                hit.add(k)
        for k in hit:
            counts[k] += 1
    groups = [g._replace(targets=c) for g, c in zip(groups, counts)]
    seconds = None if unplanned else sum(g.seconds for g in groups)
    return Plan(groups, seconds, atlas_total, pss_total, stored_targets, unplanned)
