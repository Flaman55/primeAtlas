"""
ring_resonance.py -- the resonance-step scan over a range of n and the text
formatting of the resonance log / surviving-primes panel. Pure numpy and plain
strings, no rendering, no I/O, no tkinter.
"""

import numpy as np

from primeatlas.visualization.shared.bigint import to_prime_array


# ---------------------------------------------------------------------------
# Resonance -- ports SieveModel.resonanceEventsInRange, the bulk "goto catch-up"
# resonance-flash finder used by StructuralSieveApp's resonance log (a goto must not
# skip resonance events strictly before the jumped-to n; see SieveModel.js for the
# algorithm). A marking pass, not O(range * primes) trial division; numpy is used for
# the per-prime multiple marking (see resonance_events_in_range for the vectorization).
# ---------------------------------------------------------------------------

#: Hard ceiling on resonance_events_in_range's O(to_n-from_n) marking-pass array --
#: 20M int64 entries is ~160MB. Beyond this a dense per-n marking pass is not viable
#: regardless of memory (see that function's docstring).
_RESONANCE_SCAN_MAX_SIZE = 20_000_000

#: resonance_events_in_range's marking pass: primes with more multiples than this
#: in the span get their own numpy slice add; the rest are counted together via
#: np.bincount (one numpy call per chunk instead of one per prime).
_RESONANCE_SCAN_DENSE_MULTIPLES = 64

#: Upper bound on how many flat multiple-indices one np.bincount chunk expands
#: (~32 MB per int64 temporary), keeping peak memory near the factor_count array.
_RESONANCE_SCAN_CHUNK = 4_000_000


def resonance_events_in_range(primes, from_n, to_n):
    """Every "resonance" step n in [from_n, to_n] (inclusive): n is a
    resonance step when every prime whose leading primorial product still
    fits under n also divides n (getStepState's own doc-comment has the
    full definition; this is the BULK finder for a whole span at once, not
    a per-n test).

    Returns a list of {"n": int, "factors": [int, ...]} dicts in ascending n
    order, factors listing every dividing prime for that n (same shape as
    the JS version's plain objects).

    The marking pass is O(to_n - from_n) by design. tick_next_n's `range_step` can
    make a single range-mode tick's gap ~10**21 once storage-floor primes are loaded,
    which no dense array can hold. TWO guards below, cheapest first:
      1. A resonance step needs `primorial(smallest active prime) <= to_n` (see
         `thresholds` below) -- if even the SMALLEST active prime's threshold exceeds
         to_n, no resonance is possible anywhere in the span, so this returns without
         allocating anything. A high-floor range (active primes ~10**25, to_n ~10**21)
         hits this on every tick at O(1) cost.
      2. A hard cap on `size` itself, for any other combination that still
         slips past guard 1 (e.g. small-enough primes but an enormous gap
         some other way) -- past this, resonance events genuinely cannot be
         found by this approach at all; returning [] (same contract as the
         to_n<from_n case above) is the correct result, since a marking pass over a
         span this size cannot finish regardless of memory."""
    if to_n < from_n:
        return []
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0 or int(primes_arr[0]) > to_n:
        return []
    size = to_n - from_n + 1
    if size > _RESONANCE_SCAN_MAX_SIZE:
        return []

    # Everything below is vectorized: a per-n Python loop over the whole span
    # (plus one numpy slice call per active prime) takes seconds at N=20M, all
    # of it inside the ring-viz GLFW loop on every scrub jump, where Esc and
    # window-close cannot be processed until it finishes.
    if primes_arr.dtype == object:
        candidates = np.array([int(p) for p in primes_arr if int(p) <= to_n], dtype=np.int64)
    else:
        candidates = primes_arr[primes_arr <= to_n].astype(np.int64)
    first = np.maximum(candidates, from_n)
    first += (-first) % candidates  # round up to the next multiple of p
    in_span = first <= to_n
    candidates, first = candidates[in_span], first[in_span]
    multiples = (to_n - first) // candidates + 1

    # Marking pass: factor_count[i] = number of active primes dividing
    # from_n + i. Primes with many multiples in the span get a slice add each;
    # the (typically far more numerous) primes with only a few multiples are
    # expanded into flat index arrays and counted with np.bincount, in chunks
    # of at most _RESONANCE_SCAN_CHUNK indices to bound peak memory.
    factor_count = np.zeros(size, dtype=np.int64)
    dense = multiples > _RESONANCE_SCAN_DENSE_MULTIPLES
    for p, m in zip(candidates[dense].tolist(), first[dense].tolist()):
        factor_count[m - from_n::p] += 1
    sparse_p, sparse_first, sparse_count = candidates[~dense], first[~dense], multiples[~dense]
    i = 0
    while i < len(sparse_p):
        running = np.cumsum(sparse_count[i:])
        j = i + max(1, int(np.searchsorted(running, _RESONANCE_SCAN_CHUNK, side="right")))
        counts = sparse_count[i:j]
        k = np.arange(int(counts.sum()), dtype=np.int64) - np.repeat(np.cumsum(counts) - counts, counts)
        offsets = np.repeat(sparse_first[i:j] - from_n, counts) + k * np.repeat(sparse_p[i:j], counts)
        factor_count += np.bincount(offsets, minlength=size)
        i = j

    # maxResonance(n) only changes at the handful of n where the running
    # primorial crosses n (Python ints here, not int64, so this stays exact
    # well past where a naive int64 accumulator would silently overflow --
    # a correctness improvement over the JS version's plain float64 numbers,
    # though not one expected to matter at the N scale this module targets).
    # Each crossing bumps max_resonance for the rest of the span.
    max_resonance = np.zeros(size, dtype=np.int8)
    primorial = 1
    for p in primes_arr:
        primorial *= int(p)
        if primorial > to_n:
            break
        max_resonance[max(primorial - from_n, 0):] += 1

    hits = np.nonzero((max_resonance > 0) & (factor_count >= max_resonance))[0]
    events = []
    for offset in hits.tolist():
        n = from_n + offset
        count = int(factor_count[offset])
        factors = []
        for p in primes_arr:
            p_int = int(p)
            if p_int > n or len(factors) >= count:
                break
            if n % p_int == 0:
                factors.append(p_int)
        events.append({"n": n, "factors": factors})
    return events


# ---------------------------------------------------------------------------
# Resonance log + surviving-primes panel text -- ports
# StructuralSieveApp.js's #resonanceLog formatting and #renderLogPanel's
# text-truncation rules to plain strings for renderer.py's console-pane
# prints (NOT the on-canvas HUD/HUD_STATE path). No new math:
# resonance_log_lines is a thin formatter over resonance_events_in_range above; format_log_panel_text
# is generic and used for both the resonance-log lines and the raw
# surviving-primes list.
# ---------------------------------------------------------------------------

LOG_PANEL_TRUNCATE_THRESHOLD = 50  # mirrors JS's own LOG_PANEL_TRUNCATE_THRESHOLD


def resonance_log_lines(primes, from_n, to_n):
    """Ports #resonanceLog's own entry format exactly (`${e.n} = ${e.factors
    .join(" × ")}`) -- turns resonance_events_in_range's structured events
    for [from_n, to_n] into the same human-readable strings the HTML
    reference's Resonances panel shows, one per resonance step, ascending n
    order (resonance_events_in_range's own order, unchanged)."""
    events = resonance_events_in_range(primes, from_n, to_n)
    return [f"{e['n']} = {' × '.join(str(f) for f in e['factors'])}" for e in events]


def format_log_panel_text(items, threshold=LOG_PANEL_TRUNCATE_THRESHOLD):
    """Ports StructuralSieveApp.js's #renderLogPanel text-formatting rules
    (see that method's own doc-comment for the full rationale) for a plain
    console-pane line rather than a DOM panel with a live collapse/expand
    toggle: the console pane is a scrolling text stream, not an interactive
    widget, so there is nothing to click here -- this always renders the
    COLLAPSED view once a list exceeds `threshold` items (JS's own default
    state for a freshly rendered long panel), which is strictly more useful
    for a scrollback than dumping a potentially huge comma-separated line.

    Returns a (count, text) tuple: `count` is len(items) (for the caller's
    own "(count)" header, matching JS's `els.count.textContent`); `text` is
    "-" for an empty list, the full ", "-joined list at or below
    `threshold` items, or the first `threshold` items joined by ", "
    followed by " (+K more)" above it -- K is the omitted remainder,
    mirroring JS's own "+N more" wording (ss-log-panel-truncated)."""
    count = len(items)
    if count == 0:
        return count, "-"
    if count <= threshold:
        return count, ", ".join(str(x) for x in items)
    shown = items[:threshold]
    remaining = count - threshold
    return count, ", ".join(str(x) for x in shown) + f" (+{remaining} more)"
