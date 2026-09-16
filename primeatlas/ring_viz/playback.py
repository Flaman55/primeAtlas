"""
playback.py -- pure playback/timing logic for primeatlas/ring_viz/renderer.py:
tempo clamping, LEFT/RIGHT scrub deltas, the sequential-mode ceiling guards,
buffer-lookahead extension math, the range-mode dynamic step size, the
resonance log's jump-vs-tick update rule, and auto-orbit's cycling. Split out
of renderer.py; see that file's own module docstring for the overall module
breakdown.

Every function here is plain scalar/dict logic with no GL-context
dependency (renderer.py's own `_run_visualization` is the only caller that
wires these into GLFW callbacks and a moderngl main loop) -- ports
StructuralSieveApp's #toggleRunning / #stop / #tick / #setTempo /
#advanceAutoOrbit / #backfillResonanceLog / #logResonance, see each
function's own doc-comment for the exact JS method it corresponds to.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so `from primeatlas.ring_geometry import resonance_log_lines` below
works whether this module is imported after renderer.py has already run its
own bootstrap, or on its own (e.g. directly from a test).
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.ring_geometry import resonance_log_lines

_TEMPO_MS_MIN = 30
_TEMPO_MS_MAX = 2000
_TEMPO_MS_DEFAULT = 120


def clamp_tempo_ms(value):
    """Ports #setTempo's own clamp exactly: [30, 2000] ms/tick, falling back
    to the JS's own default (120) for a missing/non-finite value -- see
    that method's own `Math.min(2000, Math.max(30, ...))` line."""
    if value is None:
        value = _TEMPO_MS_DEFAULT
    return min(_TEMPO_MS_MAX, max(_TEMPO_MS_MIN, int(value)))


_ARROW_SCRUB_STEP = 1
_ARROW_SCRUB_STEP_CTRL = 10


def arrow_scrub_delta(is_right, ctrl_held):
    """The N delta for one LEFT/RIGHT scrub step: +/-1 normally, +/-10 with
    Ctrl held. Deliberately a separate, fixed step size from --n-step
    (which only governs Up/Down/PageUp/PageDown), independent of how
    --n-step happens to be configured for a given run."""
    magnitude = _ARROW_SCRUB_STEP_CTRL if ctrl_held else _ARROW_SCRUB_STEP
    return magnitude if is_right else -magnitude


def can_start_playback(n, range_mode, ceiling):
    """Ports #toggleRunning's own pre-start guard: sequential mode refuses to
    START playback once N has already reached the loaded ceiling (the caller
    should show the JS's own "ss-info-ceiling-reached" message in that case
    instead of silently doing nothing) -- range mode has no ceiling at all
    and can always start (mirrors `this.#model.mode === "sequential" &&
    this.#n >= ceiling` being the ONLY case that blocks a start)."""
    return range_mode or n < ceiling


def clamp_scrub_n(n, range_mode, ceiling):
    """Bounds for the LEFT/RIGHT scrub keys specifically: never negative,
    and in SEQUENTIAL mode never past the loaded ceiling.

    Why this exists: unlike a single Up/Down/PageUp/PageDown press, OS key
    repeat can fire a LEFT/RIGHT scrub's PRESS/REPEAT handler many times per
    second while a key is held down -- especially with Ctrl held (10 per
    step instead of 1) -- so a couple of seconds of holding RIGHT can push N
    far past the ceiling before the key is ever released. Once N is past
    the ceiling, can_start_playback() permanently refuses to (re)start
    sequential playback, since the scrub's own auto-resume-on-release (and
    even a manual Space press afterward) both go through that same guard.
    Clamping the scrub itself to the ceiling caps it at the same "end of
    loaded data" edge real forward playback ticking already stops at on
    its own (tick_next_n) instead of letting it run arbitrarily far past
    that edge.

    Deliberately scoped to the scrub keys ONLY -- Up/Down/PageUp/PageDown's
    own pre-existing, unclamped past-ceiling behavior is left untouched
    here.

    Range mode has no ceiling at all (mirrors tick_next_n/can_start_playback's
    own range_mode bypass)."""
    n = max(0, n)
    if not range_mode:
        n = min(n, ceiling)
    return n


def should_extend_buffer(n, ceiling, margin, range_mode, can_extend_source):
    """Whether N has come close enough to the loaded ceiling
    (within `margin`) that the buffer should be extended further NOW,
    before N actually reaches it -- the whole point of a lookahead margin
    is to finish the (possibly slow, disk-bound) extension load before N's
    own advance ever catches up to a ceiling that would otherwise stop it.

    `range_mode` and a data source that has nothing more to fetch anyway
    (`can_extend_source=False` -- see extend_buffer_if_needed's own
    doc-comment for why only --source magazyn qualifies) both return False
    unconditionally, same as can_start_playback/tick_next_n's own
    range_mode bypass: there is no "ceiling" concept worth extending in
    either case.

    Uses a STRICT `n > ceiling - margin` (not `>=`): the caller
    (extend_buffer_if_needed) sets `ceiling` to exactly `ceiling + margin`
    on a successful extension, so at the moment that happens N still sits
    at (at most) the OLD ceiling -- `n > new_ceiling - margin` reduces to
    `n > old_ceiling`, which is False right after extending (N cannot
    exceed old_ceiling in sequential mode -- tick_next_n/clamp_scrub_n both
    already guarantee that). A non-strict `>=` would immediately re-trigger
    another extension the very next frame purely from floating/landing
    exactly on that boundary, before N has advanced by so much as 1."""
    if range_mode or not can_extend_source or margin <= 0:
        return False
    return n > ceiling - margin


def next_buffer_ceiling(current_ceiling, margin):
    """The new ceiling to request after a successful buffer extension --
    simply one more `margin`'s worth of headroom past the current ceiling,
    so the buffer keeps carrying the SAME lookahead margin it started with
    at launch as N keeps moving forward (the margin stays fixed rather
    than growing over time)."""
    return current_ceiling + margin


#: One full "orbit" (phase 0 back to 0) of the largest currently-active
#: prime takes this many ticks in range mode -- see tick_next_n's own
#: doc-comment for the derivation this feeds. Needed because at
#: magazyn-floor-scale ranges (~10**25), phase = n mod prime advances by an
#: imperceptible fraction of the prime per tick unless the step size scales
#: with the prime's magnitude. Purely a pacing constant -- tempo (ms/tick)
#: is a separate, independent knob; not currently exposed as its own CLI
#: flag.
_RANGE_STEP_ORBIT_TICKS = 10_000


def tick_next_n(n, range_mode, ceiling, range_step=1):
    """One playback tick's worth of N-advance -- ports #tick's own body:
    sequential mode STOPS (does not advance, `should_stop=True`) once N has
    reached the ceiling, and always advances by exactly 1 regardless of
    `range_step` (unchanged from #tick's own hard-coded `this.#n += 1`, NOT
    --n-step, which only applies to the manual Up/Down/PageUp/PageDown keys).

    `range_step` -- the caller's own dynamically-computed step for RANGE
    MODE ONLY (see _run_visualization's own range_step computation,
    `max(1, largest_active_prime // _RANGE_STEP_ORBIT_TICKS)`). A fixed +1
    step is imperceptible at magazyn-floor-scale primes (~10**25) loaded
    via --load-range: phase = n mod prime needs n to advance by a
    meaningful FRACTION of the prime's own value before any angular
    movement is visible at all, so scaling the step with the largest
    active prime is required. The computation naturally settles back down
    to the exact old `1` at low floors, where a full orbit already fit
    inside _RANGE_STEP_ORBIT_TICKS ticks, so nothing changes there.
    Sequential mode's own advance is NEVER affected by this parameter.
    Defaults to 1 (the old, always-correct behavior) so any caller that
    omits it (including every existing test) sees no change. Returns
    (new_n, should_stop)."""
    if not range_mode and n >= ceiling:
        return n, True
    return n + (range_step if range_mode else 1), False


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
    span is always a single value (n_value..n_value) there, same as before.
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
