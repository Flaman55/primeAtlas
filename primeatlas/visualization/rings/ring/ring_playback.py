"""
ring_playback.py -- rings-mode playback state rules: the resonance log's
jump-vs-tick update (update_resonance_log, ports #backfillResonanceLog /
#logResonance) and auto-orbit's cycling (advance_auto_orbit, ports
#advanceAutoOrbit). Plain scalar/dict logic, no GL-context dependency.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so the primeatlas.* imports below work whether this module is imported
after renderer.py has already run its own bootstrap, or on its own (e.g.
directly from a test).
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.rings.ring.ring_geometry import resonance_log_lines


def update_resonance_log(state, active, n_value, range_mode, advancing):
    """Ports StructuralSieveApp.js's own
    #backfillResonanceLog / #logResonance split, mutating `state` in place
    (`state["lines"]`, `state["last_n"]`, `state["last_range_mode"]` --
    caller owns and persists this dict across calls, same convention as
    `flash_state`/`orbit_state` elsewhere in renderer.py).

    A full O(from_n..n_value) recompute via ring_geometry.resonance_log_lines
    only runs on a JUMP: the first call ever (`state["last_n"] is None`), a
    sequential<->range mode switch, or any call that isn't a simple forward
    playback tick -- exactly StructuralSieveApp.js's own #renderFrame
    jump-detection condition (`this.#n !== this.#lastRenderedN ||
    this.#model.mode !== this.#lastRenderedMode`, OR'd with "not a +1
    forward tick"). A full backfill is cheap even here because
    resonance_log_lines' own resonance_events_in_range is a whole-range
    vectorized numpy pass, not a python loop -- same cost argument as
    renderer.py's other jump-time full recomputes (build_vertex_data itself).

    A simple FORWARD tick (`advancing=True`) instead only checks the span
    actually crossed since the LAST call (`state["last_n"] + 1` .. `n_value`)
    for new resonance steps: one call into resonance_log_lines bounded by
    however far this single tick actually moved (cost bound by the active-
    prime count times that span, not by n_value itself), not a full
    [original from_n, n_value] rescan on every single tick. This is exactly
    the performance concern StructuralSieveApp.js's own #logResonance
    doc-comment calls out ("O(1) per tick ... this full-range recompute only
    runs for actual jumps") -- skipping it would make playback at a large N
    rescan the WHOLE history every tick.

    Sequential mode's tick_next_n always advances by exactly +1, so this
    span is always a single value (n_value..n_value) there.
    Range mode's own tick_next_n step can be > 1 (see that function's own
    doc-comment) -- using `state["last_n"] + 1` as the actual from_n here
    (instead of the old hardcoded `n_value` for both ends) is
    what keeps this correct for a multi-step tick: a resonance event that
    fell strictly BETWEEN two consecutive (now farther-apart) ticks would
    otherwise never be scanned at all and silently vanish from the log.

    Returns nothing; mutates `state` in place (mirrors the JS's own
    #resonanceLog being a private instance field mutated by both methods,
    not returned/reassigned by the caller)."""
    is_jump = (
        state["last_n"] is None
        or state["last_range_mode"] != range_mode
        or not advancing
    )
    if is_jump:
        resonance_from_n = 0 if range_mode else 1
        state["lines"] = resonance_log_lines(active, resonance_from_n, n_value)
    else:
        new_lines = resonance_log_lines(active, state["last_n"] + 1, n_value)
        for new_line in new_lines:
            if not state["lines"] or state["lines"][-1] != new_line:
                state["lines"].append(new_line)
    state["last_n"] = n_value
    state["last_range_mode"] = range_mode


def advance_auto_orbit(active_primes, index, counter):
    """One tick's worth of #advanceAutoOrbit -- ports that method's body
    exactly: cycles a "which ring is tracked" index forward through
    `active_primes`, holding each one for a number of ticks proportional to
    the gap to the next active prime (wrapping to a fixed gap of 10 once it
    cycles past the last one back to index 0 -- ports the JS's own
    `nextIndex === 0 ? 10 : ...` line verbatim).

    Returns (new_index, new_counter, chosen_prime_or_None) -- `chosen_prime`
    is only non-None on the tick where the orbit actually ADVANCES to a new
    ring (mirrors the JS only reassigning `this.#trackedPrimes` inside the
    `if (counter >= gap)` branch); the caller is responsible for remembering
    the LAST chosen prime across ticks where this returns None (see run()'s
    own `orbit_state["current_prime"]`, which persists across calls the same
    way the JS's own `this.#trackedPrimes` instance field does).

    `len(active_primes) <= 1` is a no-op (mirrors the JS's own early-return
    guard: nothing to orbit through) -- returns the index/counter unchanged
    and None."""
    n = len(active_primes)
    if n <= 1:
        return index, counter, None
    next_index = (index + 1) % n
    gap = 10 if next_index == 0 else int(active_primes[next_index]) - int(active_primes[index])
    counter += 1
    if counter >= gap:
        return next_index, 0, int(active_primes[next_index])
    return index, counter, None
