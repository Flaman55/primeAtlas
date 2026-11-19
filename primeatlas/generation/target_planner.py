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

A target may name its engine (an optional last field: an Atlas engine, or Pseudosquares).
Targets naming the same engine form a lane planned on its own, with the lane's stored
windows, cap and costs (lane_for(choice) -> Lane), and never share a group with another
lane; the named method is used even where another would be faster, and a block it cannot
time stays in the plan as a group with no seconds. The comparison totals cover the targets
that name no engine.
"""
import bisect
import re
from collections import namedtuple

from . import engine_options
from .quick_number import _eval_quick_number

MAX_TARGETS = 10_000
"""Most targets one plan takes; arbitrary, keeps a pasted list from freezing the view."""

MIN_NUMBER = 10 ** 7
"""Floors 0..6 generate in seconds as one range (Floor mode); the planner starts above them."""

METHOD_ATLAS = "atlas"
METHOD_PSS = "pseudosquares"

ENGINE_NAMES = {name: name for name in engine_options.ENGINES}
ENGINE_NAMES.update({"pt1.1": engine_options.ENGINE_PT1, "pss": METHOD_PSS,
                     "pseudosquares": METHOD_PSS})
"""A target line's engine field (any case) -> its engine id, or METHOD_PSS."""

Target = namedtuple("Target", "line lo hi engine", defaults=(None,))
LineError = namedtuple("LineError", "line key text")
ParseResult = namedtuple("ParseResult", "targets errors")
Group = namedtuple("Group", "floor idx windows method engine seconds blocks targets lo hi forced",
                   defaults=(False,))
Plan = namedtuple("Plan", "groups seconds atlas_seconds pss_seconds stored_targets unplanned "
                          "compared", defaults=(True,))
Lane = namedtuple("Lane", "stored cap_for atlas pss")

_SEPARATORS = re.compile(r"[\s;,]+")


def _parse_line(text):
    """(center, radius, engine) or an error key."""
    fields = [f for f in _SEPARATORS.split(text) if f]
    engines = [i for i, f in enumerate(fields) if f.lower() in ENGINE_NAMES]
    if len(engines) > 1:
        return "too_many_engines"
    engine = None
    if engines:
        if len(fields) == 1:
            return "not_number"
        if engines[0] != len(fields) - 1:
            return "engine_not_last"
        engine = ENGINE_NAMES[fields.pop().lower()]
    numbers = [_eval_quick_number(f) for f in fields]
    if (engine is None and len(numbers) in (2, 3) and numbers[-1] is None
            and None not in numbers[:-1] and any(c.isalpha() for c in fields[-1])):
        return "unknown_engine"
    if len(fields) > 2:
        return "too_many_fields"
    if any(n is None for n in numbers):
        return "not_number"
    center, radius = numbers[0], numbers[1] if len(numbers) == 2 else 0
    if center < 1:
        return "center_below_one"
    if radius < 0:
        return "radius_negative"
    return center, radius, engine


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
        center, radius, engine = parsed
        lo, hi = max(1, center - radius), center + radius
        if lo < MIN_NUMBER:
            errors.append(LineError(number, "below_min", line))
        elif hi > max_number:
            errors.append(LineError(number, "above_max", line))
        else:
            targets.append(Target(number, lo, hi, engine))
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


def plan_targets(targets, window_m, stored, cap_for, atlas_cost, pss_cost, lane_for=None):
    """Plan of the targets. stored(floor): the window indices already in the storage;
    cap_for(floor): the widest Atlas run. A block neither method can time is unplanned and
    the plan's seconds are then None. A target naming an engine is planned in the lane
    lane_for(engine) returns (without lane_for: with the others)."""
    lanes = {}
    for target in targets:
        lanes.setdefault(target.engine if lane_for is not None else None, []).append(target)
    groups, unplanned, stored_targets = [], [], 0
    atlas_total = pss_total = None
    for choice, own in lanes.items():
        if choice is None:
            lane = Lane(stored, cap_for, atlas_cost, pss_cost)
        else:
            lane = lane_for(choice)
            if choice == METHOD_PSS:
                lane = lane._replace(atlas=_no_cost)
            else:
                lane = lane._replace(pss=_no_cost)
        found = _plan_lane(own, window_m, lane, choice)
        groups.extend(found[0])
        stored_targets += found[4]
        if choice is None:
            unplanned, atlas_total, pss_total = found[1], found[2], found[3]
    groups.sort(key=lambda g: (g.lo, g.forced, g.engine or ""))
    known = sum(g.seconds for g in groups if g.seconds is not None)
    return Plan(groups, None if unplanned else known, atlas_total, pss_total, stored_targets,
                unplanned, None in lanes)


def _no_cost(floor, idx, windows):
    return None


def _plan_lane(targets, window_m, lane, choice):
    """(groups, unplanned blocks, separate Atlas total, Pseudosquares total, stored targets)
    of one lane; choice: the engine its targets name (None: the free lane)."""
    stored, cap_for, atlas_cost, pss_cost = lane
    forced = choice is not None
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
        base = 10 ** floor
        for block in blocks:
            atlas = atlas_cost(floor, block[0], block[1])
            pss = pss_cost(floor, block[0], block[1])
            atlas_total = None if atlas is None or atlas_total is None else atlas_total + atlas[0]
            pss_total = None if pss is None or pss_total is None else pss_total + pss
            if atlas is not None or pss is not None:
                plannable.append(block)
            elif forced:
                # The named method cannot time it: the run stays in the plan, with no time.
                method = METHOD_PSS if choice == METHOD_PSS else METHOD_ATLAS
                groups.append(Group(floor, block[0], block[1], method,
                                    None if method == METHOD_PSS else choice, None, (block,), 0,
                                    base + block[0] * window_m,
                                    base + (block[0] + block[1]) * window_m - 1, True))
            else:
                unplanned.append(block)
        if not plannable:
            continue
        for i, j, seconds, method, engine in _plan_floor(floor, plannable, cap, atlas_cost,
                                                          pss_cost):
            idx = plannable[i][0]
            windows = plannable[j][0] + plannable[j][1] - idx
            groups.append(Group(floor, idx, windows, method, engine, seconds,
                                tuple(plannable[i:j + 1]), 0, base + idx * window_m,
                                base + (idx + windows) * window_m - 1, forced))

    # A lane's groups never overlap: sorted by (floor, first window), bisect finds a window's.
    groups.sort(key=lambda g: (g.floor, g.idx))
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
    return groups, unplanned, atlas_total, pss_total, stored_targets
