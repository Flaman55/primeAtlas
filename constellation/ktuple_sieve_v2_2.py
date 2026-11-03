"""
ktuple_sieve_v2_2.py -- targeted k-tuple ("constellation") candidate sieve, complementary
to constellation_finder_v2_3.py.

Same engine as ktuple_sieve_v2.py, split across modules, with the portal folder passed
explicitly: every function that touches disk takes `portal` first, and the command line
resolves it once via constellation_portal_v2_3.default_portal_folder() (unitTests/
test_ktuple_sieve_v2_2.py checks that every function and constant matches v2 once
`portal` is read as v2's PORTAL_FOLDER). It is the version the GUI launches. Module
layout: ktuple_wheel_v2_2.py holds the arithmetic (Miller-Rabin, wheel, candidate
scan, Hardy-Littlewood sizing), ktuple_locations_v2_2.py the location strategies,
ktuple_hit_store_v2_2.py the checkpoint, the exhaustive frontier and the gap-safe hit
recording; this file keeps the scan drivers, the command line and the sys.path setup.

GAP-SAFE HIT RECORDING: this module's location strategies (concentrated, digit_sweep,
manual_step) deliberately jump around a floor rather than crawling it in increasing
order, hunting for a rare deep hit far ahead of wherever constellation_finder_v2_3.py's
exhaustive, window-by-window scan currently is. Both tools append confirmed hits to the
SAME cumulative HITS_10p{N}_k{K}_v{V}.bin file via the shared _append_hits_deduped(),
which decides "already known" purely by comparing a new value against the file's own
LAST stored value -- safe only if every writer discovers hits in strictly increasing
numeric order. If a targeted, out-of-order find were appended directly, the shared
file's own "last value" would jump ahead of it, and every SMALLER, genuinely NEW hit
constellation_finder_v2_3.py finds afterwards, working its way up from below, would be
silently treated as an "already known duplicate" and dropped -- this module's own finds
(sitting near the top of the floor in LAST_VALUES.tsv) poisoning the shared file's dedup
cursor against everything smaller.

Hence: before recording a batch of confirmed hits, check them against
constellation_finder_v2_3's own exhaustive frontier (ktuple_hit_store_v2_2._exhaustive_frontier_value() --
the smallest value NOT yet covered by that module's gap-aware done-range checkpoint,
see resolve_done_names()). Anything BELOW the frontier is safe to append to the shared
file (the exhaustive scan has already read that window; this is always either
a harmless duplicate or a legitimate confirmation). Anything AT OR ABOVE the frontier
goes into this pattern's own PROVISIONAL_HITS_10p{N}_k{K}_v{V}.txt file instead (see
read_provisional_hits()/_append_provisional_hits()) -- a plain, order-independent text
log, not the strict monotonic PGS2 format, since even THIS module's own discovery order
isn't monotonic across a batch (digit_sweep deliberately jumps between magnitude
neighborhoods -- see its own docstring). Nothing is lost: once the exhaustive scan's own
frontier genuinely reaches that range, it rediscovers the same hit deterministically and
appends it to the shared file itself; the provisional entry just becomes a redundant,
already-known early sighting.

WHY THIS EXISTS: constellation_finder_v2_3.py finds k-tuples by pattern-matching against
windows that prime_sieve_v1/prime_sieve_primesieve.py have ALREADY fully sieved (every
prime in the window, via primesieve). That's the right tool when you already want every
prime in a range for other reasons, but it's the wrong tool for hunting a single sparse
pattern deep in a wide floor: a k=15 pattern's singular-series density at floor ~25 is on
the order of 1e-21..1e-22 per integer, so fully sieving a range wide enough to have a
realistic chance of a hit (~1e20-1e21 wide) would take a FULL prime sieve engine
centuries even at this app's own measured floor-25 throughput -- the bottleneck isn't the
per-window sieve cost (that's genuinely cheap, ~0.18s/1e7-window even at floor 25), it's
that there are simply too many windows to visit at all.

This module instead builds a small explicit residue WHEEL (via CRT over a handful of
small primes) for the pattern's own offsets: for each wheel prime p, at least one of the
k members is FORCED divisible by p for most residues of the window's starting position n
mod p (since k=15's offsets already span most residues mod any small p -- see
build_wheel()'s own docstring), so the overwhelming majority of positions can be
DIRECTLY SKIPPED (via striding by the wheel modulus) rather than ever touched. What
survives the wheel is filtered further by incremental trial division (early-exit) against
deeper primes, and only the tiny remainder -- individual integers, not whole windows --
gets real primality-tested (Miller-Rabin; numbers in play here are a few dozen to ~100
bits, trivially cheap to test individually regardless of how many survive).

This is deterministic and exact at every stage before the final Miller-Rabin call: a
position is only ever ELIMINATED because one of its k members is PROVABLY divisible by a
small prime (hence composite, barring the trivial n+d==p edge case, guarded for
explicitly) -- so no true k-tuple is ever silently skipped by the wheel or trial-division
stages. Only the final Miller-Rabin step is probabilistic (standard rounds=40 default,
error probability < 4**-40), same trust level the rest of this app already uses
elsewhere (see primeatlas/primality.py's own miller_rabin_test, which this deliberately
mirrors in miniature -- duplicated rather than imported since this script runs standalone
inside WSL, same self-contained pattern as constellation_finder_v2_3.py/prime_sieve_v1.py,
with no dependency on the primeatlas/ Windows-side package).

Because this mode never needs a pre-existing PRIME_WINDOW_*.bin for the locations it
scans (it works directly off raw integer ranges), it's independent of prime_sieve's own
generation pipeline and CHECKPOINT.txt -- confirmed hits use the SAME per-(k,variant)
hit-file format constellation_finder_v2_3.py uses (hit_file_path()/_append_hits_deduped()),
routed through this module's own frontier check first -- see the gap-safe hit recording
note above -- so the rest of the portal (browsing, search) needs no changes to pick up
whichever ones land in the shared file.

CHECKPOINTING: every strategy except manual_list reduces to the same striding mechanism
(see stride_locations()) -- n_locations windows spaced `step` apart, starting at a
floor-relative offset persisted per (floor, k, variant) in its own
KTUPLE_CHECKPOINT_*.txt file (read_ktuple_checkpoint()/write_ktuple_checkpoint()). A
plain run (auto=False) scans one batch and updates the checkpoint, so the next run
continues rather than re-scanning; run_ktuple_job(auto=True) keeps looping batch after
batch, checkpointing after each, until a confirmed hit turns up, the caller's
should_stop() fires, or the floor is exhausted.

DIGIT SWEEP: a 5th location strategy alongside even/concentrated/manual_step/manual_list
-- see digit_sweep_locations() for the full design note. In one sentence: instead of
crawling the floor linearly, it drills through the floor's own digit positions (coarsest
first) so a single n_locations-sized batch samples the ENTIRE magnitude range of the
floor at once, nesting deeper into one committed digit branch (default: always "...1")
at each successive, finer position (e.g. 10000, 20000, ..., 90000, then 11000, 12000,
..., 19000, then 11100, 11200, ..., 11900, ...). Extra per-position budget beyond one
window per digit value is spent as a CONTIGUOUS block right at that digit's own offset
(denser, not wider, coverage there). Continuation between batches does NOT shift a
floor-relative offset the way the other three strategies do (that would corrupt the
digit alignment -- see run_ktuple_job()'s own docstring) -- instead a pass_counter
increments by 1 each batch, and each position derives ITS OWN committed digit from it (a
different small step per position -- see digit_sweep_locations()'s PATH VARIETY note),
so the explored path looks mixed/scrambled (e.g. "53254553452543") rather than a single
repeated digit, while staying fully deterministic and always starting from a clean,
unshifted anchor.
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)  # sibling ktuple_*_v2_2.py, constellation_*_v2_3.py,
                                 # pattern_catalog_v1.py (same folder)
# prime_sieve_v1, window_sharding and hit_paging live in the sibling folder ../prime_sieve/;
# this script (the entry point) puts it on sys.path for every module it imports.
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "prime_sieve"))
from ktuple_wheel_v2_2 import (  # noqa: E402
    primes_upto, build_wheel, default_wheel_primes, scan_window_for_candidates,
    verify_candidates,
)
from ktuple_locations_v2_2 import (  # noqa: E402
    stride_locations, step_for_even, step_for_concentrated, manual_list_locations,
    digit_sweep_positions, digit_sweep_locations,
)
from ktuple_hit_store_v2_2 import (  # noqa: E402
    read_ktuple_checkpoint, write_ktuple_checkpoint, clear_ktuple_checkpoint,
    _exhaustive_frontier_value, _record_confirmed_hits,
)
from pattern_catalog_v1 import PATTERN_CATALOG  # noqa: E402
from constellation_portal_v2_3 import default_portal_folder  # noqa: E402


# ------------------------------------------------------------------------------------------
# Top-level drivers.
# ------------------------------------------------------------------------------------------

def scan_locations(portal, base_exponent, pattern, locations, window_m,
                    wheel_primes=None, deep_prime_limit=2000, mr_rounds=40,
                    progress_cb=None, should_stop=None):
    """Scans each of `locations` (absolute base positions, each a window_m-wide range)
    for pattern's k-tuple, routing confirmed hits through _record_confirmed_hits() --
    the pattern's own cumulative hit file if constellation_finder_v2_3's own exhaustive
    scan already covers that value, its PROVISIONAL file otherwise (see this module's
    header note). Used directly (no checkpoint) for strategy=manual_list;
    run_ktuple_job() below builds its own
    locations per batch via stride_locations() and calls the same per-window scan-and-
    verify logic inline (needs to inspect per-location hits to decide whether to keep
    auto-looping, which a single boolean return here doesn't expose).

    `progress_cb(index, total, location, candidates_found, confirmed_count)` -- called
    after each location finishes. `should_stop()` -- checked before each location.
    Returns {"locations_done": n, "cancelled": bool, "total_candidates": n,
    "total_confirmed": n}."""
    offsets = pattern["offsets"]
    k = pattern["k"]
    variant_id = pattern["id"]

    if wheel_primes is None:
        wheel_primes = default_wheel_primes(offsets)
    wheel_M, wheel_residues = build_wheel(offsets, wheel_primes)
    deep_primes = [p for p in primes_upto(deep_prime_limit) if p not in wheel_primes]

    total_candidates = 0
    total_confirmed = 0
    locations_done = 0
    cancelled = False
    frontier = _exhaustive_frontier_value(portal, base_exponent)

    for i, base in enumerate(locations):
        if should_stop is not None and should_stop():
            cancelled = True
            break
        candidates = scan_window_for_candidates(
            base, window_m, offsets, wheel_M, wheel_residues, deep_primes)
        confirmed = verify_candidates(candidates, offsets, rounds=mr_rounds)
        if confirmed:
            _record_confirmed_hits(portal, base_exponent, k, variant_id, sorted(confirmed), frontier)
        total_candidates += len(candidates)
        total_confirmed += len(confirmed)
        locations_done += 1
        if progress_cb is not None:
            progress_cb(i, len(locations), base, len(candidates), len(confirmed))

    return {"locations_done": locations_done, "cancelled": cancelled,
            "total_candidates": total_candidates, "total_confirmed": total_confirmed}


def run_ktuple_job(portal, base_exponent, pattern, window_m, strategy, n_locations,
                    step=None, start_offset=None, fragment_width=None,
                    target_expected=1.0, hl_limit=200_000, wheel_primes=None,
                    deep_prime_limit=2000, mr_rounds=40, auto=False,
                    reset_checkpoint=False, pass_counter=0, progress_cb=None, should_stop=None):
    """Checkpointed driver for strategy in ("even", "concentrated", "manual_step",
    "digit_sweep") -- manual_list has no checkpoint concept, see
    manual_list_locations()/scan_locations() above instead.

    `step`, if given, overrides the strategy's own formula for even/concentrated/
    manual_step (manual_step has no formula of its own -- an explicit step is required
    for it; digit_sweep ignores `step` entirely, see digit_sweep_locations() instead).
    `start_offset`, if given, is only used the very FIRST time (no checkpoint exists
    yet, or reset_checkpoint=True) -- every batch after that continues from the
    checkpoint regardless of what was passed in here; digit_sweep ignores it too (see
    `pass_counter` below instead -- a floor-relative offset has no meaning for it).

    `pass_counter` -- digit_sweep only, the STARTING pass (0, 1, 2, ..., default 0)
    used only the very first time (no checkpoint yet, or reset_checkpoint=True); every
    batch after that continues from the checkpoint's own pass_counter regardless of
    what's passed in here. CONTINUATION: a checkpointed anchor_offset that isn't a
    multiple of 10**base_exponent corrupts the digit sweep -- every position's own
    d=0..9 loop assumes committed starts CLEAN at that position, i.e. anchor's own
    digit there is 0, so a nonzero leftover from a "shift the whole pattern by
    10**p_min" scheme would add on TOP of that, overflowing past a single digit and
    producing nonsense offsets. Avoided by NEVER shifting the anchor at all for
    digit_sweep (it stays 0, always clean) -- instead, each batch after the first
    just increments pass_counter by 1, persisted in the checkpoint's own next_offset
    field (repurposed to hold the next pass_counter for this one strategy, since a
    floor offset is meaningless here).

    PATH VARIETY: pass_counter alone driving ONE digit shared by every swept position
    for the whole pass would only ever explore repdigit branches (pass 0 ->
    "111...1", pass 1 -> "222...2", etc.) instead of a genuinely mixed/scrambled
    path. digit_sweep_locations() derives a DIFFERENT digit per position from the
    SAME pass_counter (see its own PATH VARIETY note) -- pass_counter itself still
    just increments by 1 each batch, but the resulting explored path is mixed rather
    than uniform.

    auto=False (default): scans exactly one batch of up to n_locations windows, updates
    the checkpoint, and returns -- the shape a plain "Run" click wants (repeat by
    clicking Run again, each click a fresh continuation).
    auto=True: keeps scanning batch after batch (checkpointing after each) until one
    of -- a confirmed hit appears in some batch (stop_reason="hit_found"),
    should_stop() returns True (stop_reason="cancelled"), or the next batch would have
    zero locations because the floor is exhausted (stop_reason="floor_exhausted" --
    for digit_sweep this can only happen if window_m itself leaves no positions to
    sweep at all, checked up front below; a normal digit_sweep run simply keeps
    incrementing pass_counter forever until a hit or should_stop()).

    Returns {"batches_done", "locations_scanned", "total_candidates",
    "total_confirmed", "stop_reason", "next_offset"}."""
    if strategy not in ("even", "concentrated", "manual_step", "digit_sweep"):
        raise ValueError(f"run_ktuple_job() strategy must be 'even', 'concentrated', "
                          f"'manual_step', or 'digit_sweep' (got {strategy!r}) -- use "
                          f"manual_list_locations()+scan_locations() for strategy='manual_list'")

    offsets = pattern["offsets"]
    k = pattern["k"]
    variant_id = pattern["id"]

    if wheel_primes is None:
        wheel_primes = default_wheel_primes(offsets)
    wheel_M, wheel_residues = build_wheel(offsets, wheel_primes)
    deep_primes = [p for p in primes_upto(deep_prime_limit) if p not in wheel_primes]

    checkpoint = None if reset_checkpoint else read_ktuple_checkpoint(portal, base_exponent, k, variant_id)

    if strategy == "digit_sweep":
        drill_positions = digit_sweep_positions(base_exponent, window_m)
        if not drill_positions:
            raise ValueError("window_m leaves no digit positions to sweep at this floor "
                              "-- window_m is too wide relative to the floor's own width")
        # next_offset here holds the NEXT pass_counter, not a floor offset -- see
        # the docstring's CONTINUATION note above. Falls back to the
        # caller-given pass_counter if the checkpoint is missing/reset/negative.
        current_offset = checkpoint["next_offset"] if checkpoint is not None else pass_counter
        if current_offset < 0:
            current_offset = pass_counter
    else:
        current_offset = checkpoint["next_offset"] if checkpoint is not None else (start_offset or 0)
        if step is None:
            if strategy == "even":
                step = step_for_even(window_m)
            elif strategy == "concentrated":
                step = step_for_concentrated(
                    offsets, k, base_exponent, n_locations, window_m,
                    target_expected=target_expected, hl_limit=hl_limit, fragment_width=fragment_width)
            else:  # manual_step
                raise ValueError("strategy='manual_step' requires an explicit step")

    total_candidates = 0
    total_confirmed = 0
    total_scanned = 0
    batches_done = 0
    stop_reason = "single_batch_done"

    while True:
        if strategy == "digit_sweep":
            locations = digit_sweep_locations(
                base_exponent, n_locations, window_m,
                anchor_offset=0, pass_counter=current_offset)
            next_offset = current_offset + 1  # next pass -- see PATH VARIETY note
        else:
            locations, next_offset = stride_locations(
                base_exponent, n_locations, window_m, current_offset, step)
        if not locations:
            stop_reason = "floor_exhausted"
            break

        # Recomputed once per BATCH (not once per whole auto=True job, and not once per
        # location) -- see _exhaustive_frontier_value()'s own docstring: cheap (served
        # from list_source_windows()'s own WINDOW_INDEX.tsv cache), and a long auto=True
        # job can easily outlive several of constellation_finder_v2_3's own batches, so a
        # frontier computed once at the very start would go stale exactly the way this
        # whole mechanism exists to avoid.
        frontier = _exhaustive_frontier_value(portal, base_exponent)

        batch_confirmed_any = False
        batch_cancelled = False
        for i, base in enumerate(locations):
            if should_stop is not None and should_stop():
                batch_cancelled = True
                break
            candidates = scan_window_for_candidates(
                base, window_m, offsets, wheel_M, wheel_residues, deep_primes)
            confirmed = verify_candidates(candidates, offsets, rounds=mr_rounds)
            if confirmed:
                _record_confirmed_hits(portal, base_exponent, k, variant_id, sorted(confirmed), frontier)
                batch_confirmed_any = True
            total_candidates += len(candidates)
            total_confirmed += len(confirmed)
            total_scanned += 1
            if progress_cb is not None:
                progress_cb(batches_done, i, len(locations), base, len(candidates), len(confirmed))

        batches_done += 1
        # for digit_sweep, `current_offset` just used for this batch is the
        # pass_counter ABOUT to be superseded -- record it as `step` too
        # (informational only, so a status line can show which pass this batch just
        # finished) before overwriting current_offset with the next pass_counter.
        checkpoint_step = current_offset if strategy == "digit_sweep" else step
        current_offset = next_offset
        write_ktuple_checkpoint(portal, base_exponent, k, variant_id, current_offset, checkpoint_step, window_m, strategy)

        if batch_cancelled:
            stop_reason = "cancelled"
            break
        if batch_confirmed_any:
            stop_reason = "hit_found"
            break
        if not auto:
            stop_reason = "single_batch_done"
            break
        # auto=True, no hit this batch, not stopped, floor not exhausted -- loop again

    return {"batches_done": batches_done, "locations_scanned": total_scanned,
            "total_candidates": total_candidates, "total_confirmed": total_confirmed,
            "stop_reason": stop_reason, "next_offset": current_offset}


if __name__ == "__main__":
    portal = default_portal_folder()
    import argparse
    parser = argparse.ArgumentParser(
        description="Targeted k-tuple candidate sieve (wheel + trial division + Miller-Rabin) "
                    "for a single catalog pattern, checkpointed per (floor, k, variant).")
    parser.add_argument("base_exponent", type=int, help="floor N (searches near 10**N)")
    parser.add_argument("k", type=int, help="pattern k (e.g. 15)")
    parser.add_argument("variant_id", type=int, help="pattern variant id within k (see pattern_catalog_v1.py)")
    parser.add_argument("--n-locations", type=int, default=1000)
    parser.add_argument("--window-m", type=int, default=10_000_000)
    parser.add_argument("--strategy",
                         choices=["even", "concentrated", "manual_list", "manual_step", "digit_sweep"],
                         default="concentrated")
    parser.add_argument("--step", type=int, default=None,
                         help="explicit stride override for even/concentrated/manual_step "
                              "(required for manual_step; ignored by digit_sweep)")
    parser.add_argument("--fragment-width", type=int, default=None)
    parser.add_argument("--fragment-start", type=int, default=None,
                         help="initial offset used only when no checkpoint exists yet "
                              "(or --reset-checkpoint) -- default 0")
    parser.add_argument("--manual-offsets", type=int, nargs="*", default=None,
                         help="strategy=manual_list only")
    parser.add_argument("--pass-counter", type=int, default=0,
                         help="strategy=digit_sweep only -- starting pass (0, 1, 2, ...) "
                              "used only when no checkpoint exists yet or --reset-checkpoint "
                              "(default 0 -- matches the original worked example exactly)")
    parser.add_argument("--deep-prime-limit", type=int, default=2000)
    parser.add_argument("--mr-rounds", type=int, default=40)
    parser.add_argument("--auto", action="store_true",
                         help="keep scanning batch after batch until a hit, --stop, or the floor is exhausted")
    parser.add_argument("--reset-checkpoint", action="store_true",
                         help="ignore any existing checkpoint and start from --fragment-start (default 0)")
    args = parser.parse_args()

    pattern = next((w for w in PATTERN_CATALOG if w["k"] == args.k and w["id"] == args.variant_id), None)
    if pattern is None:
        print(f"[!] No pattern k={args.k} id={args.variant_id} in PATTERN_CATALOG.")
        sys.exit(1)

    print(f"[KTUPLE SIEVE v2.2] 10^{args.base_exponent} pattern k={args.k} v={args.variant_id} "
          f"({pattern['discoverer']}, {pattern['date']}) -- strategy={args.strategy}, "
          f"n_locations={args.n_locations}, window_m={args.window_m:,}, auto={args.auto}")

    if args.reset_checkpoint and args.strategy != "manual_list":
        clear_ktuple_checkpoint(portal, args.base_exponent, args.k, args.variant_id)
        print("[KTUPLE SIEVE v2] Checkpoint reset -- starting from "
              f"--fragment-start={args.fragment_start or 0}.")

    if args.strategy == "manual_list":
        locations = manual_list_locations(args.base_exponent, args.manual_offsets)
        print(f"[KTUPLE SIEVE v2] {len(locations)} manual location(s) (one-shot, no checkpoint).")

        def progress_list(i, total, base, n_cand, n_conf):
            extra = f" -- {n_conf} CONFIRMED HIT(S)!" if n_conf else ""
            print(f"[KTUPLE SIEVE v2] {i+1}/{total}: base={base} candidates={n_cand}{extra}")

        result = scan_locations(portal, args.base_exponent, pattern, locations, args.window_m,
                                 deep_prime_limit=args.deep_prime_limit, mr_rounds=args.mr_rounds,
                                 progress_cb=progress_list)
        print(f"\n[KTUPLE SIEVE v2] Done. locations_done={result['locations_done']} "
              f"total_candidates={result['total_candidates']} "
              f"total_confirmed={result['total_confirmed']}")
    else:
        def progress_batch(batch_idx, i, total, base, n_cand, n_conf):
            extra = f" -- {n_conf} CONFIRMED HIT(S)!" if n_conf else ""
            print(f"[KTUPLE SIEVE v2] batch {batch_idx+1}, {i+1}/{total}: base={base} "
                  f"candidates={n_cand}{extra}")

        result = run_ktuple_job(portal,
            args.base_exponent, pattern, args.window_m, args.strategy, args.n_locations,
            step=args.step, start_offset=args.fragment_start,
            fragment_width=args.fragment_width, deep_prime_limit=args.deep_prime_limit,
            mr_rounds=args.mr_rounds, auto=args.auto, reset_checkpoint=args.reset_checkpoint,
            pass_counter=args.pass_counter, progress_cb=progress_batch)
        print(f"\n[KTUPLE SIEVE v2] Done. batches_done={result['batches_done']} "
              f"locations_scanned={result['locations_scanned']} "
              f"total_candidates={result['total_candidates']} "
              f"total_confirmed={result['total_confirmed']} "
              f"stop_reason={result['stop_reason']} next_offset={result['next_offset']}")
