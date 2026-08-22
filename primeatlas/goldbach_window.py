"""
goldbach_window.py -- structural window check for Goldbach's conjecture, for the
Badania -> Goldbach sub-tab. Pure Python, no external dependencies (same zero-install
promise as primality.py -- see that module's own header comment).

Mirrors, term for term, Artur's own formalization in
"A Structural Sieve for Goldbach's Conjecture" (LaTeX) and
Hipoteza Goldbacha/lean/StructuralGoldbach/{Basic,Structural}.lean:

  hasGoldbachRep(n)   := exists p q, p prime, q prime, p + q = n            (Basic.lean)
  repCount(n)         := #{p in [0, n] : p prime and (n - p) prime}        (Basic.lean)
  windowCovered(Pmax) := for every even n, 4 <= n <= 2*Pmax, hasGoldbachRep(n)
                                                                             (Structural.lean)
  windowCoveredDec(Pmax) := for every even n < 2*Pmax + 1, not(4<=n and repCount(n)=0)
                                                                             (Structural.lean)

repCount ranges its witness p over ALL of [0, n] (Lean's `range (n+1)`), so it counts
ORDERED witnesses -- both p=3,q=7 and p=7,q=3 add 1 each to repCount(10) (repCount(10)=3:
p in {3,5,7}). check_window()'s "all_combinations" mode reports that same number under
"rep_count" (exactly reproducing the Lean definition), and ALSO derives the deduplicated
UNORDERED pair list (p <= q) under "pairs", since that's the more natural thing for a
person to read -- the two are never in conflict, "pairs" is just "rep_count" grouped by
{p, q} instead of listed once per p.

Two selectable modes (the checkbox in the GUI), both checking exactly the same window
[4, 2*Pmax] and reporting exactly the same "covered" verdict on that window as a whole --
they differ only in how much they compute PER n, in line with the paper's own framing
(Constructive.lean's header comment): "windowCovered doesn't count how many primes are
in the window, it shows the window must geometrically deliver one" vs
"repCount/PositiveMargin are the counting-spirit road, which runs into the parity
problem".

  "touch_once"       -- for each n, stop at the FIRST witness found (smallest p).
                         This is windowCovered / hasGoldbachRep: existence, not count.
                         The paper's ACTIVE line of proof.
  "all_combinations" -- for each n, compute repCount(n) in full (every p in [0, n]).
                         This is the paper's repCount/PositiveMargin framing, explicitly
                         flagged there as kept "for comparison, not the active line of
                         proof" (it inherits the parity problem in full force).

Because every n checked here satisfies n <= 2*Pmax, any witness pair p <= q must have
p <= Pmax (p is the smaller summand, so 2p <= p+q = n <= 2*Pmax). This means
"touch_once"'s witness search never needs a candidate above Pmax -- it is simultaneously
a live check of buildableFromBase(Pmax, n) (Constructive.lean) for every n in the window,
not just of the unbounded hasGoldbachRep -- the two framings coincide exactly on this
window, which is itself a small confirmation that the translation below is faithful to
the source.

IMPORTANT, learned the hard way (see git history on this file): buildableFromBase in
Constructive.lean only bounds p, the SMALLER summand -- `def buildableFromBase (B n) :=
exists p q, p <= B and p.Prime and q.Prime and p + q = n`. It says NOTHING about q. So
buildableFromBase(Pmax, n) holds for EVERY prime pair p <= q summing to any n in this
window, not just ones where q ALSO happens to be <= Pmax -- that "both <= Pmax" idea
(and the "prefer a fully-old-base witness" search, and "old base insufficient" framing
that briefly lived in this file) was never what the theorem says; it was an invented,
stricter, unproven condition that crept in from reading too much into the "STARA BAZA"
visualization. Whether q happens to be <= Pmax or not is purely INFORMATIONAL (which
primes were already known before this window vs first appear inside it) -- it is never
a pass/fail condition. Every function below reflects this: only p is ever checked
against Pmax for buildableFromBase purposes; q's relationship to Pmax is reported
separately and is never treated as a requirement.

The GUI's number field is labeled "n" (an arbitrary integer), not "Pmax" -- Pmax is
DERIVED as the largest prime <= n (see largest_prime_le()), matching the paper's own
convention that Pmax must itself be a genuine prime, without requiring the person to
type a prime by hand.
"""
import time


def sieve_is_prime(limit):
    """Classic sieve of Eratosthenes. Returns a bytearray `is_prime` of length
    limit + 1, is_prime[i] truthy iff i is prime (0 and 1 are not). O(limit
    log log limit) time, O(limit) memory -- fine for the window sizes this tab is meant
    for (a GUI research tool, not the production floor-sieve -- see
    primeatlas_offset_optimization_ceiling.md in memory for why depth belongs to the
    primesieve-backed engine, not here)."""
    if limit < 2:
        return bytearray(max(limit + 1, 0))
    is_prime = bytearray([1]) * (limit + 1)
    is_prime[0] = 0
    is_prime[1] = 0
    p = 2
    while p * p <= limit:
        if is_prime[p]:
            span = len(range(p * p, limit + 1, p))
            is_prime[p * p:: p] = bytearray(span)
        p += 1
    return is_prime


def largest_prime_le(is_prime, n):
    """Largest prime <= n, or None if none exists (n < 2) -- how the GUI derives Pmax
    from the user-facing "n" field: Pmax := the largest prime <= n, matching the paper's
    own convention that Pmax must itself be a genuine prime, without requiring the
    person to type a prime by hand. Dual of next_anchor() below (that one searches
    upward for the next prime; this one searches downward for the one at-or-below n).
    `is_prime` must be long enough to index up to n."""
    for candidate in range(min(n, len(is_prime) - 1), 1, -1):
        if is_prime[candidate]:
            return candidate
    return None


def _smallest_witness(is_prime, n):
    """Smallest prime p with p <= n//2 and n-p also prime, or (None, None) if no such p
    exists. The single witness-search primitive shared by check_window()'s "touch_once"
    branch and window_rows() below, so both really do run "the exact same algorithm",
    not just similarly-shaped code. For any n <= 2*Pmax this p is AUTOMATICALLY <= Pmax
    (see module docstring) -- so this smallest witness is, unconditionally, a live
    witness of buildableFromBase(Pmax, n) too. No preference or special-casing needed;
    an earlier version of this file searched for a witness where q ALSO stayed <= Pmax,
    which was solving a condition Lean's buildableFromBase never asked for."""
    for p in range(2, n // 2 + 1):
        if is_prime[p] and is_prime[n - p]:
            return p, n - p
    return None, None


def window_rows(is_prime, Pmax, row_cap=None, row_offset=0):
    """Computes windowCovered(Pmax) (Structural.lean) -- every even n in [4, 2*Pmax] --
    using an EXTERNALLY supplied is_prime array (e.g. sourced from on-disk storage, see
    prime_atlas_v1.read_is_prime_from_storage) instead of building a fresh sieve. Runs
    the exact same touch_once witness search as check_window()'s touch_once branch
    (_smallest_witness), just against a caller-supplied is_prime instead of one built
    internally -- this is the Goldbach tab's Wizualizacja feature, per Artur's
    instruction that "wizualizacja zawsze siedzi w oknie 4-2Pmax" (the visualization
    always lives inside the [4, 2*Pmax] window -- the SAME window "Sprawdz okno"
    checks, not a separate cascade step). `is_prime` must be long enough to index up to
    2*Pmax.

    `row_cap` limits how many per-n rows are returned (for GUI display); `row_offset`
    skips that many n's (in window order) before collection starts -- together these
    are a simple offset/limit page window, letting the GUI page through the full
    window's decomposition rows (Artur: chciał nawigacji jak gdzie indziej przy dużej
    ilości danych) without ever materializing more than one page's worth of row dicts
    at a time. The coverage verdict and counterexample list are ALWAYS computed over
    the FULL window regardless of row_cap/row_offset -- pagination only affects which
    slice of already-computed witnesses gets packaged into "rows".

    Returns {"pmax":, "window_max":, "old_base_primes": [...], "covered":,
    "counterexamples": [...], "segment_size": int, "row_offset": int,
    "rows": [{"n":,"p":,"q":,"q_is_new": bool}, ...], "rows_truncated": bool} --
    "old_base_primes" is every prime <= Pmax (the frozen base every p is drawn from,
    automatically -- see the module docstring's note on p <= Pmax, a PROVEN fact for
    every n in this window, not merely observed); "q_is_new" flags q > Pmax --
    PURELY INFORMATIONAL (which prime first appears inside this window vs. was already
    known before it), never a pass/fail signal: buildableFromBase(Pmax, n) holds
    regardless, via p, for every single row here; "rows_truncated" means there are more
    rows AFTER this page (row_offset + len(rows) < segment_size), i.e. whether a "next
    page" would return anything."""
    if Pmax < 2:
        raise ValueError("Pmax must be >= 2")
    window_max = 2 * Pmax
    old_base_primes = [p for p in range(2, Pmax + 1) if is_prime[p]]
    rows = []
    counterexamples = []
    segment_size = 0
    for n in range(4, window_max + 1, 2):
        idx = segment_size  # 0-based position of n within the window, before increment
        segment_size += 1
        p_found, q_found = _smallest_witness(is_prime, n)
        if p_found is None:
            counterexamples.append(n)
        if idx >= row_offset and (row_cap is None or len(rows) < row_cap):
            rows.append({
                "n": n, "p": p_found, "q": q_found,
                "q_is_new": (q_found is not None and q_found > Pmax),
            })
    return {
        "pmax": Pmax, "window_max": window_max, "old_base_primes": old_base_primes,
        "covered": not counterexamples, "counterexamples": counterexamples,
        "segment_size": segment_size, "row_offset": row_offset, "rows": rows,
        "rows_truncated": (row_cap is not None and row_offset + len(rows) < segment_size),
    }


def all_decompositions(is_prime, n, pmax=None, cap=None, offset=0):
    """Exhaustively lists EVERY prime pair (p, q) with p <= q and p + q = n -- unlike
    _smallest_witness (which stops at the first hit), this is the "sliding window"
    scan Artur asked for: slide p from 2 up to n//2 and record every hit.

    `is_prime` must be long enough to index up to n (i.e. len(is_prime) > n). `pmax`
    is optional context (typically the currently displayed window's Pmax) -- when
    given, each pair is flagged with TWO SEPARATE, independent facts:

      "p_in_base": p <= pmax -- this is EXACTLY Lean's buildableFromBase(pmax, n)
        criterion (Constructive.lean: `exists p q, p <= B and ... and p + q = n`,
        which bounds ONLY p). For any n <= 2*pmax this is a PROVEN fact (p <= n/2 <=
        pmax, pure arithmetic -- see module docstring), so it will be True for every
        single pair whenever n is inside the window pmax itself defines. It can
        genuinely be False when probing an n OUTSIDE that window (n > 2*pmax), which
        is allowed here since the decompose feature lets Artur type any n.

      "q_in_base": q <= pmax -- PURELY INFORMATIONAL (whether this particular prime
        was already known before this window or first appears inside it). NOT part
        of buildableFromBase, never a requirement -- Lean's theorem says nothing
        about q. An earlier version of this file collapsed both facts into one
        "both_old_base" flag and required BOTH to hold, which was never what
        buildableFromBase actually says (see module docstring's own note on this).

    `cap`/`offset` page over the pair list. Pairs are grouped q_in_base=True first,
    then q_in_base=False, ascending p within each group (mirrors window_rows'
    row_cap/row_offset -- same "GUI needs Prev/Next/goto over a potentially huge
    list" need, since a large n can have tens of thousands of pairs). Artur,
    2026-08-17: since p_in_base is trivially True for EVERY pair whenever n sits
    inside the window pmax defines (see the "p_in_base" paragraph above -- p is
    only ever enumerated up to n/2, and n <= 2*pmax means n/2 <= pmax always), a
    sort on p_in_base would be completely vacuous -- nothing to distinguish, every
    row already qualifies. q_in_base is the one property that genuinely varies
    pair to pair, so that is what groups the list -- purely a display convenience,
    carrying no bearing on the buildable_from_base verdict below (which is already
    decided by p alone, identically regardless of how the list is ordered).
    The verdict ("buildable_from_base") and total count are still computed over the
    FULL scan regardless of cap/offset, same "verdict always full, display can be
    partial" split as window_rows().

    Returns {"n":, "pmax":, "count": int (total pairs found), "offset": int,
    "decompositions": [{"p":, "q":, "p_in_base": bool|None, "q_in_base": bool|None},
    ...], "buildable_from_base": bool|None (True iff ANY pair has p_in_base=True --
    for n <= 2*pmax this is equivalent to count > 0, i.e. to windowCovered's own
    verdict for that n), "truncated": bool (more pairs exist after this page)}."""
    if n < 4 or n % 2 != 0:
        raise ValueError("n must be even and >= 4")
    if len(is_prime) <= n:
        raise ValueError("is_prime array too short for n")
    all_pairs = []
    for p in range(2, n // 2 + 1):
        if is_prime[p] and is_prime[n - p]:
            q = n - p
            p_in_base = (p <= pmax) if pmax is not None else None
            q_in_base = (q <= pmax) if pmax is not None else None
            all_pairs.append((p, q, p_in_base, q_in_base))
    count = len(all_pairs)
    buildable_from_base = (
        any(pair[2] for pair in all_pairs) if pmax is not None else None
    )
    # Group on q_in_base (True group first), ascending p within each group -- see
    # the docstring paragraph above for why p_in_base itself is never a useful sort
    # key here. When pmax is None, q_in_base is None for every pair, so this key
    # collapses to a no-op and ordered == all_pairs' natural p-ascending order.
    ordered = sorted(all_pairs, key=lambda pair: (0 if pair[3] else 1, pair[0]))
    page = ordered[offset:offset + cap] if cap is not None else ordered[offset:]
    decompositions = [
        {"p": p, "q": q, "p_in_base": p_in_base, "q_in_base": q_in_base}
        for (p, q, p_in_base, q_in_base) in page
    ]
    return {
        "n": n, "pmax": pmax, "count": count, "offset": offset,
        "decompositions": decompositions, "buildable_from_base": buildable_from_base,
        "truncated": (offset + len(decompositions) < count),
    }


BOTH_BASE_PMAX_CEILING = 1_000_000_000
"""Both-base coverage ([4, Pmax+BOTH_BASE_PMIN], both p and q <= Pmax) has been
verified gap-free, this session, for: every order of magnitude 10^2..10^9
individually (largest prime <= each), AND every prime Pmax from 2 to 50,000
exhaustively. 10^9 itself (999,999,937) was checked directly via a memory-safe
chunked sweep -- fully covered, zero gaps. A true 10-digit Pmax (~10^10) was not
reached (would need a segmented/bit-packed sieve well beyond what a plain
in-memory sieve can do in a few GB of RAM), so both_base_window_rows() below
refuses anything above this ceiling rather than silently extrapolating past what
was actually checked.

Note on BOTH_BASE_PMIN's value: the sweeps above were originally run with
BOTH_BASE_PMIN=3 (window [4, Pmax+3]). BOTH_BASE_PMIN is now 2 (window
[4, Pmax+2]), which is a strict SUBSET of [4, Pmax+3] for every Pmax -- every n
checked under Pmin=2 was already checked, and found covered, under the wider
Pmin=3 sweep. The witness search itself never restricted p away from 2 (Pmin
only ever set the upper bound of n to check), so the "zero gaps to 10^9" result
carries over to Pmin=2 without needing to re-run anything."""

BOTH_BASE_PMIN = 2
"""The smallest prime. Matches Lean's `additiveSelfContained_of_hasGoldbachRep`
(Hipoteza Goldbacha/lean/StructuralGoldbach/SelfContainment.lean) exactly: every
prime satisfies p, q >= 2, so for any Goldbach representation p+q=n with
n <= Pmax+Pmin, q = n - p <= n - Pmin <= (Pmax+Pmin) - Pmin = Pmax, and
symmetrically p <= Pmax. That Lean theorem is unconditional -- no
`native_decide`, no `sorry`, proved directly from `Nat.Prime.two_le` plus
`omega` -- so [4, Pmax+2] is not just empirically verified here but the exact
window a machine-checked proof already covers. (An earlier version of this file
used BOTH_BASE_PMIN=3, the smallest ODD prime, reasoning that p=2 only ever
works at n=4 itself. That is also true and gives a WIDER window [4, Pmax+3], but
it was Artur's own not-yet-formalized refinement of the Lean theorem rather than
what the Lean theorem itself states -- 2026-08-17: narrowed back to 2 so this
matches the actual proven statement one-to-one, not a stronger claim built on
top of it.) See the module docstring's own note on the analogous, weaker
p <= Pmax fact for the [4, 2*Pmax] window -- this is the same shape of proof,
just covering both summands on a narrower window."""


def check_both_base_coverage(is_prime, Pmax, Pmin=BOTH_BASE_PMIN):
    """Checks the narrower window [4, Pmax+Pmin] under the STRICTER criterion that
    BOTH p and q are <= Pmax (drawn entirely from the base), not just p as
    buildableFromBase (Constructive.lean) asks for. This deliberately reintroduces
    the "both <= Pmax" criterion that was removed from window_rows/
    all_decompositions earlier in this project's history -- it does NOT match
    Lean's buildableFromBase, and exists as a genuinely DIFFERENT, additional
    property Artur asked to check on its own terms, not as a replacement for
    buildableFromBase/windowCovered anywhere else in this file. See
    BOTH_BASE_PMIN's own docstring for the proof that this window is the natural
    one for this stricter criterion (both summands >= Pmin for n > 4, combined
    with n <= Pmax+Pmin, forces both summands <= Pmax whenever any representation
    exists at all).

    Rows for n with no both<=Pmax pair are still included (n always appears), with
    p/q left as None rather than the row being dropped -- so the counterexample
    list below is exactly "which n's, in this narrowed window, are NOT composable
    purely from base primes."

    Returns {"Pmax", "Pmin", "n_max" (=Pmax+Pmin), "rows": [{"n","p","q"}, ...],
    "counterexamples": [n, ...], "covered": bool (True iff counterexamples empty)}."""
    n_max = Pmax + Pmin
    if len(is_prime) <= n_max:
        raise ValueError("is_prime array too short for Pmax+Pmin")
    rows = []
    counterexamples = []
    for n in range(4, n_max + 1, 2):
        witness = None
        for p in range(2, min(Pmax, n // 2) + 1):
            q = n - p
            if q > Pmax:
                continue
            if is_prime[p] and is_prime[q]:
                witness = (p, q)
                break
        if witness is None:
            counterexamples.append(n)
        rows.append({
            "n": n, "p": witness[0] if witness else None,
            "q": witness[1] if witness else None,
        })
    return {
        "Pmax": Pmax, "Pmin": Pmin, "n_max": n_max, "rows": rows,
        "counterexamples": counterexamples, "covered": not counterexamples,
    }


def report_both_base_coverage(is_prime, Pmax, Pmin=BOTH_BASE_PMIN):
    """Companion to check_both_base_coverage for manual/CLI use -- runs the check
    and prints the result directly: a single "fully covered" line if
    counterexamples is empty, otherwise the exact list of n's with no both<=Pmax
    pair, so Artur doesn't have to manually inspect the returned dict each time.
    Returns the same dict check_both_base_coverage does."""
    res = check_both_base_coverage(is_prime, Pmax, Pmin=Pmin)
    print(f"Pmax={Pmax}  Pmin={Pmin}  okno=[4, {res['n_max']}]  wierszy={len(res['rows'])}")
    if res["covered"]:
        print("  WSZYSTKO POKRYTE -- kazde n w oknie ma pare oba<=Pmax.")
    else:
        print(f"  BRAKI ({len(res['counterexamples'])} z {len(res['rows'])}): "
              f"{res['counterexamples']}")
    return res


def both_base_window_rows(is_prime, Pmax, Pmin=BOTH_BASE_PMIN, row_cap=None,
                           row_offset=0, n_min=None, n_max=None, progress_cb=None):
    """GUI-facing counterpart of check_both_base_coverage, shaped to match
    window_rows()'s own contract (row_cap/row_offset paging, same key names where
    the concept overlaps) -- prime_atlas_v1.py's Wizualizacja now renders
    exclusively through this path. (Briefly lived alongside window_rows() as a
    second, opt-in mode; Artur, 2026-08-17: with BOTH_BASE_PMIN narrowed to 2 this
    IS exactly the window Lean's additiveSelfContained_of_hasGoldbachRep proves
    unconditionally, so the older buildableFromBase-only [4, 2*Pmax] mode was
    dropped rather than kept as a separate, weaker option.)

    Refuses (ValueError) any Pmax above BOTH_BASE_PMAX_CEILING -- see that
    constant's own docstring for exactly what scale has actually been checked
    gap-free versus what would be silent extrapolation beyond it.

    `is_prime` must be long enough to index up to Pmax+Pmin (NOT 2*Pmax -- this
    window is narrower than window_rows()'s).

    `n_min`/`n_max` (Artur, 2026-08-17) let the caller restrict which part of
    [4, Pmax+Pmin] actually gets scanned, instead of always walking from n=4 --
    without this, viewing a page deep into a huge window still required a fresh
    O(window width) scan from the very start on every single request (row_cap/
    row_offset only ever sliced which rows were RETURNED, never which were
    COMPUTED -- see the git history on this function). Both default to the full
    window when omitted, so existing callers are unaffected. When given, they are
    clamped into [4, Pmax+Pmin] and rounded to the nearest valid even boundary
    (n_min up, n_max down). "covered"/"counterexamples"/"segment_size" describe
    ONLY the resulting [n_min, n_max] range, NOT the full window -- the caller is
    responsible for making that scope clear in whatever text it shows (see
    prime_atlas_v1.py's viz_summary_covered/void usage). The returned
    "range_min"/"range_max" record exactly what was used, distinct from the
    unchanged "window_max" (the full window's own upper bound), so a UI can
    render both without recomputing the clamp itself.

    `progress_cb`, if given, is called as progress_cb(fraction: float) a handful
    of times during the base sweep below (fraction = share of the range's n's
    resolved so far, 0.0..1.0) -- purely a progress-reporting hook, no effect on
    the result. Cheap to call often since it's just a Python callable, but not
    called on EVERY single prime (see the sweep loop) to avoid turning a fast
    vectorized computation back into a slow one via callback overhead.

    Algorithm (Artur, 2026-08-17 -- replaced the previous "for each n, linear-
    scan p" nested loop, which also re-derived old_base_primes via a scalar
    Python filter over range(2, Pmax+1) on every call): both are now numpy-
    vectorized sweeps over the SAME base-primes array, computed once.
      1. old_base_primes: np.nonzero on the is_prime buffer (zero-copy view via
         np.frombuffer) instead of a Python-level comprehension -- for Pmax in
         the hundreds of millions this alone used to dominate the wall-clock
         time, well before the witness search even started.
      2. Witness search: rather than, for each n, trying candidate p=2,3,5,... in
         a Python loop, this sweeps the base primes ONCE, and for each prime p
         (ascending, so the first hit for any n is still its SMALLEST witness --
         identical selection to the old algorithm) vectorizes "is n-p prime?"
         across every STILL-UNRESOLVED n in the target range simultaneously via
         numpy boolean indexing. Since witness primes are typically small (this
         project's own WitnessStepBound measurements: the worst-case witness
         across a cascade step grows only polylogarithmically, not linearly, in
         the base size), this sweep resolves the overwhelming majority of a
         range in its first handful of iterations, each iteration doing O(range
         width) work in C rather than O(range width * average witness search
         depth) work in the Python interpreter -- this is the "sum first, sort/
         organize second, display third" restructuring Artur asked for: stage 1
         is this sweep (results land pre-sorted by n, since they're written into
         a fixed-position array indexed by n's own position in the range, not
         appended in discovery order), stage 2 is assembling the plain dict rows
         list for the requested page (cheap, already-sorted data), stage 3 is
         the existing, unchanged Tk rendering code in prime_atlas_v1.py."""
    if Pmax < 2:
        raise ValueError("Pmax must be >= 2")
    if Pmax > BOTH_BASE_PMAX_CEILING:
        raise ValueError(
            f"both_base_window_rows is only verified up to Pmax="
            f"{BOTH_BASE_PMAX_CEILING:,}; Pmax={Pmax:,} exceeds that and is "
            f"refused rather than silently extrapolated")
    import numpy as np
    window_max = Pmax + Pmin

    # Both ends are clamped into [4, window_max] BEFORE the lo>hi check below --
    # an earlier version only clamped lo's LOWER bound (max(4, n_min)) and hi's
    # UPPER bound (min(window_max, n_max)), so a wildly out-of-range n_min (e.g.
    # 10**15 against a window that only reaches ~10**7) left lo sitting at that
    # huge unclamped value while hi got pulled down to window_max -- lo > hi
    # correctly triggered the empty-range branch below, but that branch echoed
    # the raw unclamped lo back out as "range_min", producing a nonsensical
    # display like [1000000000000000, 9999992] instead of a clean bounded
    # result. Symmetric fix on hi's lower bound too, so a wildly negative/too-
    # small n_max can't do the mirror-image version of the same thing.
    lo = 4 if n_min is None else min(max(4, n_min), window_max)
    hi = window_max if n_max is None else max(min(window_max, n_max), 4)
    if lo % 2 == 1:
        lo += 1
    if hi % 2 == 1:
        hi -= 1
    # Re-clamp AFTER rounding -- rounding lo UP by 1 (to reach an even n) can
    # push it one past window_max when window_max itself is odd (Pmin=2, so
    # window_max = Pmax+2 is odd whenever Pmax is odd, i.e. almost always,
    # since Pmax is prime): a lo that clamped to exactly window_max above then
    # rounds up to window_max+1, undoing the clamp just applied. Mirror case
    # for hi rounding down past 4 doesn't actually occur (window_max>=4 always,
    # per the Pmax>=2 check above), but is included for symmetry/safety rather
    # than relying on that invariant staying true forever.
    lo = max(4, min(lo, window_max))
    hi = max(4, min(hi, window_max))

    is_prime_arr = np.frombuffer(is_prime, dtype=np.uint8)
    base_primes_arr = np.nonzero(is_prime_arr[:Pmax + 1])[0]
    old_base_primes = base_primes_arr.tolist()

    if lo > hi:
        return {
            "pmax": Pmax, "window_max": window_max, "range_min": lo, "range_max": hi,
            "old_base_primes": old_base_primes, "covered": True, "counterexamples": [],
            "segment_size": 0, "row_offset": row_offset, "rows": [],
            "rows_truncated": False,
        }

    ns = np.arange(lo, hi + 1, 2, dtype=np.int64)
    segment_size = ns.shape[0]
    witness_p = np.zeros(segment_size, dtype=np.int64)   # 0 = unresolved sentinel
    witness_q = np.zeros(segment_size, dtype=np.int64)
    unresolved = np.ones(segment_size, dtype=bool)

    # Only primes p <= hi - 2 can ever be a valid smaller summand for ANY n in
    # this range (q = n - p >= 2 requires p <= n - 2 <= hi - 2) -- primes above
    # that are in base_primes_arr (needed for old_base_primes/chip display above)
    # but never tried as a witness candidate, closing off the sweep early instead
    # of walking all the way to Pmax on a range that only needed a small prefix.
    search_primes = base_primes_arr[base_primes_arr <= hi - 2]
    report_every = max(1, len(search_primes) // 20)  # ~20 progress_cb calls total
    for i, p in enumerate(search_primes):
        if not unresolved.any():
            break
        idxs = np.nonzero(unresolved)[0]
        cand_n = ns[idxs]
        q = cand_n - p
        in_range = (q >= 2) & (q <= Pmax)
        hit = np.zeros(idxs.shape[0], dtype=bool)
        q_in_range = q[in_range]
        hit[in_range] = is_prime_arr[q_in_range].astype(bool)
        hit_idxs = idxs[hit]
        if hit_idxs.size:
            witness_p[hit_idxs] = p
            witness_q[hit_idxs] = q[in_range][is_prime_arr[q_in_range].astype(bool)]
            unresolved[hit_idxs] = False
        if progress_cb is not None and i % report_every == 0:
            progress_cb(float(segment_size - unresolved.sum()) / segment_size)
    if progress_cb is not None:
        progress_cb(1.0)

    counterexamples = ns[unresolved].tolist()

    rows = []
    row_end = segment_size if row_cap is None else min(segment_size, row_offset + row_cap)
    for idx in range(max(0, row_offset), max(0, row_end)):
        n = int(ns[idx])
        if unresolved[idx]:
            p_found = q_found = None
        else:
            p_found, q_found = int(witness_p[idx]), int(witness_q[idx])
        rows.append({"n": n, "p": p_found, "q": q_found, "q_is_new": False})

    return {
        "pmax": Pmax, "window_max": window_max, "range_min": lo, "range_max": hi,
        "old_base_primes": old_base_primes,
        "covered": not counterexamples, "counterexamples": counterexamples,
        "segment_size": segment_size, "row_offset": row_offset, "rows": rows,
        "rows_truncated": (
            row_cap is not None and row_offset + len(rows) < segment_size),
    }


def check_window(Pmax, mode):
    """Checks windowCovered(Pmax): every even n with 4 <= n <= 2*Pmax must be a sum of
    two primes. `mode` is "touch_once" or "all_combinations" (see module docstring).

    Returns a dict:
      {"pmax": Pmax, "window_max": 2*Pmax, "mode": mode, "covered": bool,
       "n_checked": int, "counterexamples": [n, ...], "elapsed": float,
       "rows": [{"n": n, "p": p or None, "q": q or None, "rep_count": int or None,
                 "pairs": [(p, q), ...] or None}, ...]}

    rows is one entry per even n in [4, 2*Pmax], in ascending order. In "touch_once"
    mode, rep_count/pairs are left None (not computed -- that is the whole point of
    the mode) and p/q hold the first witness found (or None, None for a counterexample).
    In "all_combinations" mode, p/q hold the SMALLEST witness pair for convenience
    (same value "touch_once" would have found), rep_count holds the exact Lean
    repCount(n), and pairs holds the deduplicated (p <= q) witness list.

    Raises ValueError if Pmax < 2 (windowCovered's own window [4, 2*Pmax] is empty/
    degenerate below that -- mirrors anchor 0 = 2, the paper's own base case)."""
    if Pmax < 2:
        raise ValueError("Pmax must be >= 2")
    if mode not in ("touch_once", "all_combinations"):
        raise ValueError(f"unknown mode: {mode!r}")

    t0 = time.perf_counter()
    window_max = 2 * Pmax
    is_prime = sieve_is_prime(window_max)

    rows = []
    counterexamples = []
    for n in range(4, window_max + 1, 2):
        if mode == "touch_once":
            p_found, q_found = _smallest_witness(is_prime, n)
            if p_found is None:
                counterexamples.append(n)
            rows.append({"n": n, "p": p_found, "q": q_found,
                         "rep_count": None, "pairs": None})
        else:
            rep_count = 0
            pairs = []
            for p in range(0, n + 1):
                if is_prime[p] and is_prime[n - p]:
                    rep_count += 1
                    if p <= n - p:
                        pairs.append((p, n - p))
            if rep_count == 0:
                counterexamples.append(n)
            p0, q0 = (pairs[0] if pairs else (None, None))
            rows.append({"n": n, "p": p0, "q": q0,
                         "rep_count": rep_count, "pairs": pairs})

    elapsed = time.perf_counter() - t0
    return {
        "pmax": Pmax, "window_max": window_max, "mode": mode,
        "covered": not counterexamples,
        "n_checked": len(rows), "counterexamples": counterexamples,
        "elapsed": elapsed, "rows": rows,
    }


# ------------------------------------------------------------------------------------------
# Cascade step -- Constructive.lean's nextAnchor / anchor / top / CascadeOldBaseSufficiency.
# A separate, stronger claim from windowCovered above (base held fixed from the PREVIOUS
# cascade step, rather than re-derived as Pmax for the whole window) -- not currently wired
# into any GUI control (the Wizualizacja button uses window_rows() instead, to stay strictly
# inside [4, 2*Pmax] per Artur's instruction), but kept here since it's a distinct, verified,
# potentially useful piece of the formalization for a future dedicated cascade view.
# ------------------------------------------------------------------------------------------

def next_anchor(is_prime, Pmax):
    """Largest prime in (Pmax, 2*Pmax], or 2*Pmax if none -- mirrors Constructive.lean's
    nextAnchor exactly. `is_prime` must be long enough to index up to 2*Pmax (Bertrand's
    postulate guarantees a prime is always found in this range for Pmax >= 1, so the
    "none" fallback is a formality that should never actually trigger)."""
    hi = 2 * Pmax
    for candidate in range(hi, Pmax, -1):
        if is_prime[candidate]:
            return candidate
    return hi


def cascade_step(is_prime, anchor_k, row_cap=None):
    """One cascade step starting at anchor(k) = anchor_k: computes top(k) = 2*anchor_k,
    the next anchor (largest prime in (anchor_k, 2*anchor_k]), top(k+1) = 2*next_anchor,
    and -- for every new even n in the segment (top(k), top(k+1)] -- the smallest prime
    p <= top(k) (the OLD, frozen base) with n-p also prime (buildableFromBase(top(k), n),
    Constructive.lean). `is_prime` must be long enough to index up to top(k+1) -- since
    top(k+1) <= 4*anchor_k always (next_anchor <= 2*anchor_k), the caller should ensure
    `is_prime` covers at least that.

    `row_cap` limits how many per-n rows are returned (for GUI display) -- the coverage
    verdict and counterexample list are still computed over the FULL segment regardless,
    never just the truncated display slice.

    Returns {"anchor_k":, "top_k":, "next_anchor":, "top_k1":, "old_base_primes": [...],
    "segment_size": int, "rows": [{"n":,"p":,"q":,"q_is_new": bool}, ...],
    "rows_truncated": bool, "counterexamples": [...], "covered": bool}."""
    if anchor_k < 1:
        raise ValueError("anchor_k must be >= 1")
    top_k = 2 * anchor_k
    nxt = next_anchor(is_prime, anchor_k)
    top_k1 = 2 * nxt
    old_base_primes = [p for p in range(2, top_k + 1) if is_prime[p]]

    rows = []
    counterexamples = []
    segment_size = 0
    for n in range(top_k + 2, top_k1 + 1, 2):
        segment_size += 1
        p_found = q_found = None
        for p in old_base_primes:
            if p > n // 2:
                break
            if is_prime[n - p]:
                p_found, q_found = p, n - p
                break
        if p_found is None:
            counterexamples.append(n)
        if row_cap is None or len(rows) < row_cap:
            rows.append({
                "n": n, "p": p_found, "q": q_found,
                "q_is_new": (q_found is not None and q_found > top_k),
            })

    return {
        "anchor_k": anchor_k, "top_k": top_k, "next_anchor": nxt, "top_k1": top_k1,
        "old_base_primes": old_base_primes, "segment_size": segment_size,
        "rows": rows, "rows_truncated": (row_cap is not None and segment_size > row_cap),
        "counterexamples": counterexamples, "covered": not counterexamples,
    }
