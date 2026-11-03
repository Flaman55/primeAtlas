"""
run_output.py -- parsing and formatting of a generation run's live output: the regexes for
the progress lines the engines print (prep, batch progress, totals, constellation and
Hybrid stages, multi-iteration loop sessions) and the short duration format of the ETA.
"""
import re


def format_duration_short(seconds):
    """Renders a duration (seconds, float or int, may be 0 or slightly negative from
    clock jitter) as a short human string -- "5h03m", "12m07s", or "42s" depending on
    magnitude -- for the constellation search's own elapsed-time/ETA display (see
    run_progress.py's own _update_shared_progress_from_generation_chunk()). Picks
    exactly ONE larger unit to pair with the next one down (never seconds AND hours
    together) so the string stays short enough for the shared status bar alongside the
    floor/batch counts already shown there."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


# Parsed out of a generation run's live console output by _drain_output_queue() to drive the
# SHARED bottom status/progress bar (self.status/self.totals_progress -- the same one the
# floor-totals scan and the Primes/Constellations search box already use) while a run is in
# flight, in addition to the raw text already visible in the console/terminal panel itself.
# The engines print these lines themselves; this only parses them. Together they cover the
# WHOLE pipeline, not just the batch-sieve phase -- see
# _update_shared_progress_from_generation_chunk()'s own docstring for how the individual
# lines below map onto one combined step count, so the bar isn't left sitting empty for
# however long the pi(L_final) prep phase happens to take (which can itself run into
# minutes at extreme depth) before the first batch-progress line ever arrives.
#   prime_sieve_v4.py/prime_sieve_v4_1.py (main_batch_scanner, pi(L_final) prep step --
#   EITHER the "used" (computed) or "count ... SKIPPED" wording, depending on the
#   compute_sieving_primes_count flag, both start the same way):
#     "[*] Active sieving primes used (pi(L_final)): 346,065,536,839 (computed in 0.009s -- ...)"
#     "[*] Active sieving primes count (pi(L_final)): SKIPPED (...)"
#   prime_sieve_v4.py/prime_sieve_v4_1.py (main_batch_scanner's own progress print):
#     "[+] Progress: 42.31% (156/369 batches) | time: 12.34s (...) | ETA ~16s"
#   prime_sieve_pt1.py (same line, counted in sieve chunks):
#     "[+] Progress: 21.00% (210/1000 chunks) | time: 1700.00s | ETA ~6395s"
#   prime_sieve_v4.py/prime_sieve_v4_1.py (main_batch_scanner, run-finished line -- printed
#   for BOTH the low-floor and normal-window code paths, only the tail differs):
#     "[*] TOTAL PRIMES FOUND this run: 167,026,529 across 1000 windows"
#   constellation_finder_v2_2.py (process_floor's own per-file print):
#     "[CONSTELLATIONS v2] 12/48: PRIME_WINDOW_10p11_off_50M.bin -- ..."
#   constellation_finder_v2_2.py (process_floor, floor-wide progress -- see
#   _GEN_CONST_FLOOR_PROGRESS_RE's own comment for why this is separate from the
#   per-file line above):
#     "[CONSTELLATIONS v2] FLOOR PROGRESS: batch_size=5000 total_windows=545000 already_done_before_batch=340000"
#   constellation_finder_v2_2.py (process_floor, run-finished line):
#     "[CONSTELLATIONS v2] Done. New hits this run, by pattern:"
#   orchestrator_loop_v2.py (multi-iteration Exploration-mode launches ONLY -- see
#   _LOOP_SESSION_START_RE/_LOOP_ITERATION_START_RE/_LOOP_SESSION_DONE_RE's own comment
#   below: _GEN_SIEVE_DONE_RE above fires once PER ITERATION -- each iteration is its own
#   orchestrator_v3.py subprocess -- and _GEN_SIEVE_PROGRESS_RE's batch count resets every
#   iteration, so these three are what tracks the whole multi-iteration request):
#     "[LOOP] orchestrator_loop_v2 v2 (parallel instances): 10 iteration(s), 1 instance(s)
#     /iteration, 1000 windows/iteration, ..."
#     "[LOOP] iteration 3/10: launching 1 instance(s) concurrently -- target_idx ..."
#     "[LOOP] All iterations complete in 123.4s total." / "[LOOP] Stopped early in ...s total."
_GEN_PREP_DONE_RE = re.compile(r"\[\*\] Active sieving primes (?:used|count) \(pi\(L_final\)\)")
_GEN_SIEVE_PROGRESS_RE = re.compile(
    r"\[\+\] Progress: ([\d.]+)% \((\d+)/(\d+) (?:batches|chunks)\)")
_GEN_SIEVE_DONE_RE = re.compile(r"\[\*\] TOTAL PRIMES FOUND this run:")
_GEN_CONST_PROGRESS_RE = re.compile(r"\[CONSTELLATIONS v2\] (\d+)/(\d+): ")
_GEN_CONST_DONE_RE = re.compile(r"\[CONSTELLATIONS v2\] Done\. New hits this run")
# constellation_finder_v2_2.py's own "FLOOR PROGRESS" line (printed once
# near the start of every process_floor() call, right after the human-readable "N/M
# windows to process" line): unlike _GEN_CONST_PROGRESS_RE above, whose own (done, total)
# pair only ever counts this ONE --max-windows-capped batch (resetting to 1 every time
# constellation_section.py's own _maybe_continue_constellation_batch() chains the next one),
# this line's three counts are relative to the WHOLE floor, letting the GUI show real
# progress across a floor's entire remaining backlog instead of the bar/status
# snapping back to near-zero at every batch boundary. See
# _update_shared_progress_from_generation_chunk()'s own docstring for how the two lines
# combine (already_done_before_batch + this batch's own running "i/N" -> a floor-wide
# done/total pair).
#   "[CONSTELLATIONS v2] FLOOR PROGRESS: batch_size=5000 total_windows=545000 already_done_before_batch=340000"
_GEN_CONST_FLOOR_PROGRESS_RE = re.compile(
    r"\[CONSTELLATIONS v2\] FLOOR PROGRESS: batch_size=(\d+) total_windows=(\d+) "
    r"already_done_before_batch=(\d+)")
_GEN_HYBRID_STAGE_RE = re.compile(r"\[HYBRID\] stage (\d+)/(\d+):")
_GEN_HYBRID_DONE_RE = re.compile(r"\[HYBRID\] done:")
_LOOP_SESSION_START_RE = re.compile(
    r"\[LOOP\] orchestrator_loop_v2 \S+ \(parallel instances\): (\d+) iteration\(s\)")
_LOOP_ITERATION_START_RE = re.compile(r"\[LOOP\] iteration (\d+)/(\d+): launching")
_LOOP_SESSION_DONE_RE = re.compile(
    r"\[LOOP\] (?:All iterations complete|Stopped early) in [\d.]+s total\.")
