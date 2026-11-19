"""The target-set planner (primeatlas/generation/target_planner.py): which targets one Atlas run
covers and which Pseudosquares checks, with the fewest estimated seconds.

Rules checked:
  - parsing: one target per line, `center` or `center radius` (whitespace, ';' or ','
    between them), expressions as in Quick-gen; blank lines and '#' comments skipped; every
    bad line is reported with its number and a reason (not a number, more than two fields,
    center below 1, radius below 0, below 10^7, above the highest number, too many
    targets); the interval is [center - radius, center + radius];
  - engine: an optional last field names the engine (v4.1, v5, v6, v7, pt1 or pt1.1,
    pt1-pss, pss or pseudosquares, any case), also without a radius (radius 0); an unknown
    name, two engines or an engine before a number is a bad line;
  - lanes: targets with an engine are planned in their own lane (its stored windows, cap
    and costs), never grouped with others, the forced method used even when another is
    faster; a forced group without a time stays in the plan with no seconds; the plan's
    seconds sum all lanes, the comparison totals come from the targets without an engine;
  - windows: an interval maps to the window grid of its floor and is split at a floor
    boundary; overlapping and repeated targets share windows; stored windows are dropped
    and a target with all its windows stored counts as already in the storage;
  - blocks: maximal runs of consecutive needed windows, cut at the cap;
  - choice: groups of consecutive blocks with the fewest total seconds (dynamic
    programming), an Atlas group's span never above the cap, a tie goes to Atlas, a
    missing method leaves the other, a block with neither is unplanned; the comparison
    totals (all separate Atlas runs, all Pseudosquares) and the per-group target counts.
A brute force over every partition of small random block sets checks the optimum.
    python unitTests/test_target_planner.py
"""
import itertools
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

W = 10_000_000
F25 = 10 ** 25
MAX_NUMBER = 10 ** 36 - 1


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def atlas_linear(prep=100.0, per_window=0.1, engine="v7"):
    def cost(floor, idx, windows):
        return prep + per_window * windows, engine
    return cost


def pss_linear(start=1.0, per_window=2.0):
    def cost(floor, idx, windows):
        return start + per_window * windows
    return cost


def none_cost(floor, idx, windows):
    return None


def cap_of(value):
    return lambda floor: value


def no_stored(floor):
    return set()


def parse_checks(tp):
    passed = True
    r = tp.parse_targets("10**25+3\n\n# a comment\n10**25+1000; 50\n", MAX_NUMBER)
    passed &= check(not r.errors and [(t.line, t.lo, t.hi) for t in r.targets]
                    == [(1, F25 + 3, F25 + 3), (4, F25 + 950, F25 + 1050)],
                    f"expressions, ';' radius, blank and comment lines skipped ({r})")
    r = tp.parse_targets("100000000000 5\r\n100000000000,7\r\n100000000000\t9", MAX_NUMBER)
    passed &= check(not r.errors and [t.hi - t.lo for t in r.targets] == [10, 14, 18],
                    "space, comma and tab separators; CRLF line ends")
    r = tp.parse_targets("10**25 0", MAX_NUMBER)
    passed &= check(not r.errors and r.targets[0].lo == r.targets[0].hi == F25,
                    "radius 0: the center alone")
    cases = (("abc", "not_number"), ("10**25 x", "unknown_engine"), ("10**25 1 x", "unknown_engine"),
             ("23 081 664 151", "too_many_fields"), ("0", "center_below_one"),
             ("-5", "center_below_one"), ("10**25 -1", "radius_negative"),
             ("9999999", "below_min"), ("10**7+5 10", "below_min"),
             (str(MAX_NUMBER), None), (str(MAX_NUMBER + 1), "above_max"),
             (f"{MAX_NUMBER} 1", "above_max"), ("10**7", None))
    for text, key in cases:
        r = tp.parse_targets(text, MAX_NUMBER)
        got = r.errors[0].key if r.errors else None
        passed &= check(got == key, f"{text!r}: error {key} (got {got})")
    r = tp.parse_targets("10**25\nabc\n10**25+1\n-1", MAX_NUMBER)
    passed &= check([(e.line, e.key) for e in r.errors] == [(2, "not_number"),
                                                            (4, "center_below_one")]
                    and len(r.targets) == 2,
                    "every bad line reported with its line number, good lines still parsed")
    lines = "\n".join(str(F25 + i) for i in range(tp.MAX_TARGETS + 1))
    r = tp.parse_targets(lines, MAX_NUMBER)
    passed &= check(any(e.key == "too_many" for e in r.errors),
                    f"{tp.MAX_TARGETS + 1} targets: too_many")
    r = tp.parse_targets("\n".join(str(F25 + i) for i in range(tp.MAX_TARGETS)), MAX_NUMBER)
    passed &= check(not r.errors and len(r.targets) == tp.MAX_TARGETS,
                    f"exactly {tp.MAX_TARGETS} targets: accepted")
    r = tp.parse_targets("  \n# only a comment\n", MAX_NUMBER)
    passed &= check(not r.errors and not r.targets, "nothing to plan: no targets, no error")
    return passed


def engine_parse_checks(tp):
    passed = True
    names = (("v4.1", "v4.1"), ("v5", "v5"), ("V6", "v6"), ("v7", "v7"), ("pt1", "pt1"),
             ("pt1.1", "pt1"), ("PT1.1", "pt1"), ("pt1-pss", "pt1-pss"),
             ("pss", tp.METHOD_PSS), ("Pseudosquares", tp.METHOD_PSS))
    for name, engine in names:
        r = tp.parse_targets(f"10**25+3 1000 {name}", MAX_NUMBER)
        passed &= check(not r.errors and r.targets[0].engine == engine
                        and (r.targets[0].lo, r.targets[0].hi) == (F25 - 997, F25 + 1003),
                        f"'{name}' after the radius: engine {engine} ({r})")
    r = tp.parse_targets("10**25+3 pss", MAX_NUMBER)
    passed &= check(not r.errors and r.targets[0].engine == tp.METHOD_PSS
                    and r.targets[0].lo == r.targets[0].hi == F25 + 3,
                    "an engine without a radius: radius 0")
    r = tp.parse_targets("10**25+3;7,v7", MAX_NUMBER)
    passed &= check(not r.errors and r.targets[0].engine == "v7",
                    "';' and ',' separate the engine too")
    r = tp.parse_targets("10**25+3 7", MAX_NUMBER)
    passed &= check(not r.errors and r.targets[0].engine is None, "no engine: None")
    cases = (("10**25 7 v9", "unknown_engine"), ("10**25 primesieve", "unknown_engine"),
             ("10**25 v7 pss", "too_many_engines"), ("10**25 pss 7", "engine_not_last"),
             ("v7 10**25", "engine_not_last"), ("10**25 7 9 v7", "too_many_fields"),
             ("v7", "not_number"), ("10**25 # note", "too_many_fields"))
    for text, key in cases:
        r = tp.parse_targets(text, MAX_NUMBER)
        got = r.errors[0].key if r.errors else None
        passed &= check(got == key and not r.targets, f"{text!r}: error {key} (got {got})")
    return passed


def lane_checks(tp):
    """Targets with an engine are planned in their own lane, never grouped with others."""
    passed = True
    asked = []

    def lane_for(choice):
        asked.append(choice)
        if choice == tp.METHOD_PSS:
            return tp.Lane(no_stored, cap_of(1000), none_cost, pss_linear())
        if choice == "pt1":
            return tp.Lane(no_stored, cap_of(1000), atlas_linear(prep=1.0, engine="pt1"),
                           none_cost)
        return tp.Lane(no_stored, cap_of(1000), none_cost, none_cost)

    # Free lane: Atlas over 200 windows. The same windows forced to PSS and to pt1.
    targets = [tp.Target(1, F25, F25 + 200 * W - 1),
               tp.Target(2, F25, F25 + 200 * W - 1, tp.METHOD_PSS),
               tp.Target(3, F25 + 5, F25 + 5, "pt1"), tp.Target(4, F25 + 9, F25 + 9, "pt1")]
    p = tp.plan_targets(targets, W, no_stored, cap_of(1000), atlas_linear(), pss_linear(),
                        lane_for=lane_for)
    shape = sorted((g.method, g.engine, g.windows, g.targets, g.forced) for g in p.groups)
    passed &= check(shape == sorted([(tp.METHOD_ATLAS, "v7", 200, 1, False),
                                     (tp.METHOD_PSS, None, 200, 1, True),
                                     (tp.METHOD_ATLAS, "pt1", 1, 2, True)]),
                    f"three lanes, each its own groups; pt1 targets share a window ({shape})")
    passed &= check(sorted(asked) == sorted(["pt1", tp.METHOD_PSS]),
                    f"a lane is asked once per forced choice ({asked})")
    passed &= check(abs(p.seconds - (120.0 + 401.0 + 1.1)) < 1e-9,
                    f"the plan's seconds sum every lane ({p.seconds})")
    passed &= check(p.compared and abs(p.atlas_seconds - 120.0) < 1e-9
                    and abs(p.pss_seconds - 401.0) < 1e-9,
                    "the comparison totals come from the free lane only")
    # pt1 forced on a far pair: pt1 is cheap, but PSS would be cheaper still; forced wins.
    pair = [tp.Target(1, F25, F25, "pt1"), tp.Target(2, F25 + 50 * W, F25 + 50 * W, "pt1")]
    p = tp.plan_targets(pair, W, no_stored, cap_of(1000), atlas_linear(), pss_linear(0, 0.01),
                        lane_for=lane_for)
    passed &= check(all(g.method == tp.METHOD_ATLAS and g.engine == "pt1" for g in p.groups)
                    and not p.compared,
                    f"a forced engine is used even when another is faster; no free lane, no "
                    f"comparison ({p.groups})")
    # v5 forced, no calibration: the rows stay, with no time.
    p = tp.plan_targets([tp.Target(1, F25, F25, "v5"), tp.Target(2, F25 + 9 * W, F25 + 9 * W,
                                                                  "v5")],
                        W, no_stored, cap_of(1000), atlas_linear(), pss_linear(),
                        lane_for=lane_for)
    passed &= check([(g.method, g.engine, g.seconds, g.forced) for g in p.groups]
                    == [(tp.METHOD_ATLAS, "v5", None, True)] * 2 and not p.unplanned
                    and p.seconds == 0,
                    f"a forced engine without measurements: its rows stay, time None ({p})")
    # Cap of the forced lane holds.
    p = tp.plan_targets([tp.Target(1, F25, F25 + 25 * W - 1, "pt1")], W, no_stored,
                        cap_of(1000), atlas_linear(), pss_linear(),
                        lane_for=lambda c: tp.Lane(no_stored, cap_of(10),
                                                   atlas_linear(engine="pt1"), none_cost))
    passed &= check(all(g.windows <= 10 for g in p.groups)
                    and sum(g.windows for g in p.groups) == 25,
                    "the forced lane's own cap cuts its runs")
    # Stored windows come from the lane.
    p = tp.plan_targets([tp.Target(1, F25, F25 + 2 * W - 1, "pt1")], W, no_stored,
                        cap_of(1000), atlas_linear(), pss_linear(),
                        lane_for=lambda c: tp.Lane(lambda f: {0}, cap_of(10),
                                                   atlas_linear(engine="pt1"), none_cost))
    passed &= check([(g.idx, g.windows) for g in p.groups] == [(1, 1)],
                    "the forced lane's own stored windows are dropped")
    # Groups come sorted by floor and first number.
    p = tp.plan_targets([tp.Target(1, F25 + 9 * W, F25 + 9 * W, tp.METHOD_PSS),
                         tp.Target(2, F25, F25)], W, no_stored, cap_of(1000),
                        atlas_linear(), pss_linear(), lane_for=lane_for)
    passed &= check([g.lo for g in p.groups] == sorted(g.lo for g in p.groups),
                    "rows sorted by their first number")
    # Without lane_for every target is free (the plan of earlier callers is unchanged).
    p = tp.plan_targets([tp.Target(1, F25, F25)], W, no_stored, cap_of(10), atlas_linear(),
                        pss_linear())
    passed &= check(p.compared and not p.groups[0].forced, "no engine: a free group")
    return passed


def window_checks(tp):
    passed = True
    t = tp.Target(1, F25 + 5, F25 + 5)
    passed &= check(tp.target_parts(t, W) == [(25, 0, 0)], "a point -> its window")
    t = tp.Target(1, F25 + W - 1, F25 + W)
    passed &= check(tp.target_parts(t, W) == [(25, 0, 1)], "an interval over a window edge")
    t = tp.Target(1, F25 - 3, F25 + 3)
    last = (9 * 10 ** 24) // W - 1
    passed &= check(tp.target_parts(t, W) == [(24, last, last), (25, 0, 0)],
                    f"split at the floor boundary ({tp.target_parts(t, W)})")
    t = tp.Target(1, 10 ** 26 - 1, 10 ** 26 - 1)
    passed &= check(tp.target_parts(t, W) == [(25, 9 * 10 ** 25 // W - 1,
                                                9 * 10 ** 25 // W - 1)],
                    "a floor's last number -> its last window")
    passed &= check(tp.make_blocks([3, 4, 5, 9, 10, 20], 100) == [(3, 3), (9, 2), (20, 1)],
                    "blocks: maximal runs of consecutive windows")
    passed &= check(tp.make_blocks(list(range(10)), 4) == [(0, 4), (4, 4), (8, 2)],
                    "a block wider than the cap is cut at the cap")
    passed &= check(tp.make_blocks([], 4) == [], "no windows: no blocks")
    return passed


def plan_checks(tp):
    passed = True
    targets = [tp.Target(1, F25 + 5, F25 + 5), tp.Target(2, F25 + 7, F25 + 9),
               tp.Target(3, F25 + 5, F25 + 5)]
    p = tp.plan_targets(targets, W, no_stored, cap_of(1000), atlas_linear(), pss_linear())
    passed &= check(len(p.groups) == 1 and p.groups[0].windows == 1
                    and p.groups[0].targets == 3,
                    "repeated and overlapping targets share one window")
    passed &= check(p.groups[0].method == tp.METHOD_PSS and p.seconds == 3.0,
                    f"one window: Pseudosquares 3 s beats Atlas 100.1 s ({p.groups})")
    passed &= check(p.groups[0].lo == F25 and p.groups[0].hi == F25 + W - 1,
                    "a group's number range: its windows")
    # 200 consecutive windows: PSS 401 s, Atlas 120 s.
    dense = [tp.Target(1, F25, F25 + 200 * W - 1)]
    p = tp.plan_targets(dense, W, no_stored, cap_of(1000), atlas_linear(), pss_linear())
    passed &= check([(g.method, g.idx, g.windows, g.engine) for g in p.groups]
                    == [(tp.METHOD_ATLAS, 0, 200, "v7")] and p.seconds == 120.0,
                    "a dense range: one Atlas run with its engine")
    # Two single windows 50 apart: Atlas over both 105.1 s vs 2 PSS 6 s; 100 windows each
    # at 0 and 150: Atlas over 0..249 = 125 s vs separate Atlas 220 s vs PSS 402 s.
    far = [tp.Target(1, F25, F25), tp.Target(2, F25 + 50 * W, F25 + 50 * W)]
    p = tp.plan_targets(far, W, no_stored, cap_of(1000), atlas_linear(), pss_linear())
    passed &= check([g.method for g in p.groups] == [tp.METHOD_PSS] * 2 and p.seconds == 6.0,
                    "isolated targets: Pseudosquares each")
    two = [tp.Target(1, F25, F25 + 100 * W - 1),
           tp.Target(2, F25 + 150 * W, F25 + 250 * W - 1)]
    p = tp.plan_targets(two, W, no_stored, cap_of(1000), atlas_linear(), pss_linear())
    passed &= check([(g.method, g.idx, g.windows, g.targets) for g in p.groups]
                    == [(tp.METHOD_ATLAS, 0, 250, 2)] and abs(p.seconds - 125.0) < 1e-9,
                    "two dense ranges with a gap: one Atlas run over the gap")
    passed &= check(abs(p.atlas_seconds - 220.0) < 1e-9 and abs(p.pss_seconds - 402.0) < 1e-9,
                    f"comparison: separate Atlas 220 s, all Pseudosquares 402 s ({p})")
    p = tp.plan_targets(two, W, no_stored, cap_of(200), atlas_linear(), pss_linear())
    passed &= check([(g.method, g.windows) for g in p.groups]
                    == [(tp.METHOD_ATLAS, 100), (tp.METHOD_ATLAS, 100)]
                    and all(g.windows <= 200 for g in p.groups),
                    "a cap of 200: the 250-window run is not allowed, two runs instead")
    # Tie: Atlas 100 + 1 = 101 vs PSS 99 + 2 = 101.
    p = tp.plan_targets([tp.Target(1, F25, F25)], W, no_stored, cap_of(10),
                        atlas_linear(per_window=1.0), pss_linear(start=99.0, per_window=2.0))
    passed &= check(p.groups[0].method == tp.METHOD_ATLAS, "a tie goes to Atlas")
    p = tp.plan_targets(far, W, no_stored, cap_of(1000), atlas_linear(), none_cost)
    passed &= check(all(g.method == tp.METHOD_ATLAS for g in p.groups)
                    and p.pss_seconds is None and len(p.groups) == 1,
                    "no Pseudosquares calibration: Atlas only, still grouped")
    p = tp.plan_targets(dense, W, no_stored, cap_of(1000), none_cost, pss_linear())
    passed &= check([g.method for g in p.groups] == [tp.METHOD_PSS]
                    and p.atlas_seconds is None, "no Atlas calibration: Pseudosquares only")
    p = tp.plan_targets(far, W, no_stored, cap_of(1000), none_cost, none_cost)
    passed &= check(not p.groups and len(p.unplanned) == 2 and p.seconds is None,
                    "no method at all: every block unplanned")
    stored = lambda floor: {0, 1, 2} if floor == 25 else set()
    p = tp.plan_targets([tp.Target(1, F25, F25 + 3 * W - 1), tp.Target(2, F25 + 2 * W,
                                                                         F25 + 5 * W - 1)],
                        W, stored, cap_of(1000), atlas_linear(), pss_linear())
    passed &= check(p.stored_targets == 1 and sum(g.windows for g in p.groups) == 2
                    and p.groups[0].idx == 3,
                    f"stored windows dropped, a fully stored target counted ({p})")
    p = tp.plan_targets([tp.Target(1, F25, F25)], W, lambda f: {0}, cap_of(10),
                        atlas_linear(), pss_linear())
    passed &= check(not p.groups and p.stored_targets == 1 and p.seconds == 0,
                    "everything already in the storage: no groups, 0 s")
    p = tp.plan_targets([tp.Target(1, F25 - 3, F25 + 3)], W, no_stored, cap_of(10),
                        atlas_linear(), pss_linear())
    passed &= check(sorted(g.floor for g in p.groups) == [24, 25],
                    "a target over the floor boundary: a group on each floor")
    big = [tp.Target(1, F25, F25 + 25 * W - 1)]
    p = tp.plan_targets(big, W, no_stored, cap_of(10), atlas_linear(), pss_linear())
    passed &= check(all(g.windows <= 10 for g in p.groups)
                    and sum(g.windows for g in p.groups) == 25,
                    "a radius wider than the cap: cut into runs at most the cap")
    return passed


def brute_force(tp, blocks, cap, atlas, pss):
    best = None
    n = len(blocks)
    for cuts in itertools.product((False, True), repeat=n - 1):
        total, start = 0.0, 0
        for i in range(n):
            if i == n - 1 or cuts[i]:
                group = blocks[start:i + 1]
                span = group[-1][0] + group[-1][1] - group[0][0]
                options = [sum(pss(25, b[0], b[1]) for b in group)]
                if span <= cap:
                    options.append(atlas(25, group[0][0], span)[0])
                total += min(options)
                start = i + 1
        best = total if best is None else min(best, total)
    return best


def optimum_checks(tp):
    passed = True
    rng = random.Random(7)
    worst = 0.0
    for trial in range(300):
        n = rng.randint(1, 8)
        idxs = sorted(rng.sample(range(400), n))
        targets = [tp.Target(i, F25 + x * W, F25 + x * W) for i, x in enumerate(idxs)]
        atlas = atlas_linear(prep=rng.uniform(1, 60), per_window=rng.uniform(0.01, 1))
        pss = pss_linear(start=rng.uniform(0.1, 5), per_window=rng.uniform(0.5, 5))
        cap = rng.randint(1, 400)
        p = tp.plan_targets(targets, W, no_stored, cap_of(cap), atlas, pss)
        blocks = tp.make_blocks(idxs, cap)
        best = brute_force(tp, blocks, cap, atlas, pss)
        worst = max(worst, abs(p.seconds - best))
        if any(g.method == tp.METHOD_ATLAS and g.windows > cap for g in p.groups):
            worst = float("inf")
    passed &= check(worst < 1e-9, f"300 random sets: the plan equals the brute-force optimum "
                                  f"and no Atlas group passes the cap (worst gap {worst})")
    return passed


def speed_checks(tp):
    passed = True
    rng = random.Random(3)
    for name, spread in (("spread over the floor", 9 * 10 ** 25),
                         ("dense within a cap", 40_000 * W)):
        targets = [tp.Target(i, F25 + x, F25 + x)
                   for i, x in enumerate(rng.randrange(spread) for _ in range(1000))]
        t0 = time.perf_counter()
        tp.plan_targets(targets, W, no_stored, cap_of(40_000), atlas_linear(), pss_linear())
        seconds = time.perf_counter() - t0
        passed &= check(seconds < 1.0, f"1000 targets {name}: planned in {seconds:.2f} s < 1 s")
    return passed


def main():
    from primeatlas.generation import target_planner as tp
    passed = True
    for checks in (parse_checks, engine_parse_checks, window_checks, plan_checks, lane_checks,
                   optimum_checks, speed_checks):
        passed &= checks(tp)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
