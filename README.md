# PrimeAtlas

A desktop application for generating, browsing, and searching large-scale prime number
and prime-constellation (k-tuple) data -- plus standalone primality/factorization tools
and a constellation-pattern calculator that work independently of anything already
generated. The GUI runs natively on Windows (tkinter); the generation pipeline it drives
runs under WSL, backed by `libprimesieve` and a set of custom C sieve engines (three
interchangeable engine generations, v3/v4/v4.1 -- see "Architecture" below).

## Features

- **Prime numbers** -- an inner notebook of three sub-tabs:
  - **Storage** -- browse generated data floor by floor (a digit-count
    range, floor `N` = `[10^N, 10^(N+1))`) and file by file, with per-floor and
    per-file prime counts, on-disk size, generation time, a paginated preview, and
    direct search for a specific value. A background worker computes floor totals
    (count + disk size) incrementally, so re-checking an already-scanned floor after
    a small change is cheap rather than a full rescan. Only lists floors that
    actually hold prime-window data -- a floor whose only leftover is
    `prime_sieve_v4.py`'s sieving-prime-count cache is hidden here (though the cache
    itself is kept on disk for reuse if the floor is generated later).
  - **primesieve** (calculator) -- four standalone libprimesieve queries (count
    primes in a range, nth prime, next/previous prime) that don't touch anything
    already in storage -- no floor, no generated data involved -- run over WSL via a
    one-shot script (`prime_sieve/primesieve_query.py`).
  - **Primality tests** -- primality testing (Miller-Rabin, Fermat, Solovay-
    Strassen; pure Python, no WSL round trip) and factorization (trial division +
    Pollard's rho by default, or `sympy.factorint()` instead when installed -- see
    Settings below) for any entered number, with the factor list shown in a copyable
    field.
- **Constellations** -- an inner notebook of three sub-tabs:
  - **Storage** -- browse detected k-tuple patterns floor by floor, with hit counts,
    offset/record metadata, a paginated preview that reconstructs each hit's full
    tuple, and a search that reports whether a given number participates in any
    recorded constellation. Only lists floors where the constellation finder has
    actually recorded at least one hit, not every floor that happens to have prime
    data. The finder also checks for patterns straddling a floor boundary (base on
    one floor, tail past `10^(N+1)` into the next) -- not just patterns spanning a
    window boundary within the same floor -- recording any such hit under the
    lower floor. A floor whose neighbor has no data yet at scan time is left
    unresolved (with an informational note, not silent skipping) and self-heals the
    next time it's scanned once that neighbor exists.
  - **Constellation calculator** -- pick a k-tuple pattern from the catalog (k, then
    variant), enter a floor and an offset, and instantly compute every number the
    pattern implies -- pure arithmetic, no file I/O, so it is instant even for a huge
    floor. Its Search button reuses the Storage sub-tab's own search machinery
    against the selected number: it covers both "the prime window isn't generated
    yet" and "the constellation finder never scanned this specific pattern on this
    floor" (proactively, even when the floor already has hits for some *other*
    pattern), offers to generate whichever is missing, and once the number is found,
    jumps the Storage view straight to that exact hit instead of leaving it to be
    located by hand.
  - **Records table** -- a pzktupel.de-style table (exp x pattern-variant) of the
    smallest offset found so far per floor, scanned from *this project's own*
    storage, not pzktupel.de itself; an optional floor-range filter keeps the table
    focused instead of dumping every floor in a large database. Double-clicking a
    cell shows the full list of every individual hit behind it (not just the
    smallest), and double-clicking one of those jumps straight to it in the Storage
    sub-tab. PDF/CSV export covers every individual hit for the currently displayed
    floor range, not just the compact per-cell summary.
- **Generation** -- two ways to launch the sieve/orchestrator pipeline and the
  constellation finder over WSL, both with live streamed output (stackable across
  runs, detachable into its own window) and a stop control:
  - **Quick generation** -- six simple modes (Floor only, Range from/to,
    Exploration, primesieve, cudasieve, Hybrid) that translate a plain request into the
    right low-level parameters, check what is already on disk first, and report "already in
    storage" instead of launching a redundant run. An "Auto" button estimates a safe window
    count from the WSL environment's available RAM (see "Window count, throughput, and RAM"
    below). See "The primesieve mode", "The cudasieve mode", and "The Hybrid mode" below for
    how the fourth, fifth, and sixth modes differ from the first three -- cudasieve is an
    optional, opt-in GPU engine, hidden behind its own installer (Settings > Aktualizacje)
    and requiring an Nvidia GPU; Hybrid is a deliberately narrow, single-window
    experimental engine, not a general-purpose replacement for the other five.
    Exploration mode's own Floor field auto-continues from whichever
    floor currently holds the deepest generated data (leave it blank, or use its
    dedicated Auto button) instead of requiring a manually-typed floor every time, and
    rolls forward into floor 7+ once the fixed floors-0-6 batch is complete, rather
    than reporting "already in storage" and getting stuck there. Its shared progress
    bar reflects the WHOLE multi-iteration run (iterations x windows), not just
    whichever single iteration currently happens to be in flight. "Windows in
    storage" figures shown throughout Quick generation are the real, on-disk file
    count, not a continuation-position number -- the two only coincide on a
    gap-free floor, and can diverge once a floor has interior gaps (see below).
    Floor mode also accepts an explicit starting point, dispatched directly
    (ceiling-aware: primesieve mode when the requested range fits under
    libprimesieve's own uint64 limit, the orchestrator otherwise) rather than always
    continuing from the end of what already exists -- Width acts as a hard cap on
    how many windows that single launch can cover, never rounded upward past it. An
    off-by-default "Wypelnij luki najpierw" checkbox, shared by Floor and
    Exploration mode, fills a floor's first interior gap (if one exists) instead of
    continuing from its highest file -- checked on every floor Exploration mode
    rolls forward past, not just the one it starts on, so a floor nobody has
    personally visited yet (e.g. one a search or the Goldbach tab's "generate
    missing range" offer wrote into directly) doesn't get silently skipped over
    while still holding a real gap.
  - **Low-level form** -- exposes every CLI parameter of the orchestrator and
    constellation finder directly (workers, batch size, window count, window width,
    write-files toggle, sieving-prime count diagnostic) for full manual control. The
    "workers" field has its own Auto button, the CPU-count counterpart to Quick
    generation's RAM-based Auto button above: it probes the CPU count INSIDE WSL
    (`nproc`, not the native Windows host's own count, since WSL2 can be configured
    with fewer visible CPUs than the host) and fills the field with that count --
    requesting more workers than available CPUs adds scheduling overhead without any
    real parallelism gain. The field stays freely editable afterward, same as every
    other field in this form.
  - **Targeted k-tuple sieve** -- a third launcher, complementary to the
    constellation finder above rather than a replacement for it: instead of pattern-
    matching against windows `prime_sieve` has already fully sieved (every prime in
    the window, via libprimesieve), this builds a small explicit residue wheel (CRT
    over a handful of small primes) for a chosen pattern's own offsets, strides
    directly to the positions that survive it -- skipping the overwhelming majority
    without ever touching them -- filters further via incremental trial division,
    and only primality-tests the tiny remainder (Miller-Rabin). This makes hunting a
    single sparse pattern (e.g. a 15-tuple, whose singular-series density is on the
    order of `1e-21` per integer at floor 25) across scattered window locations deep
    in a wide floor tractable, where fully sieving a wide enough span for the
    ordinary constellation finder to find the same thing would take centuries even
    at this project's own measured floor-25 sieve throughput -- the bottleneck there
    isn't the per-window sieve cost (genuinely cheap on its own), it's that there
    are simply too many windows to visit at all. The pattern picker reuses the same
    k-then-variant catalog cascade as the Constellation calculator. Five location
    strategies choose the (by default 1000) window locations one batch scans. Three
    of them -- even, concentrated, manual (step) -- share one linear checkpointed
    mechanism (n windows, `step` apart, starting from wherever the LAST batch for
    this exact floor+pattern left off, persisted in its own `KTUPLE_CHECKPOINT_*.txt`
    file next to that pattern's hit file), differing only in how `step` itself is
    picked: even uses the window width (dense, contiguous), concentrated auto-sizes
    it from the pattern's own Hardy-Littlewood density so the batch's expected hit
    count is roughly 1 (editable, or an explicit fragment width/step can be given
    instead), and manual (step) takes a caller-given step directly. Digit sweep is a
    fourth, also checkpointed, strategy but with its own mechanism instead of linear
    striding: it drills through the floor's own digit positions, coarsest (the
    floor's own leading digit) first, so a single batch already samples every
    magnitude neighborhood of the floor at once rather than crawling linearly
    through one -- at each position it nests into ONE committed digit branch
    (pass 0's default: "1") before drilling into the next, finer position, mirroring a manual
    worked example (10000, 20000, ..., 90000, then 11000, 12000, ..., 19000, then
    11100, 11200, ..., within the "1"/"11" branches); any window budget left over
    after one sample per digit value at a position is spent as a contiguous block
    right at that digit's own offset, densifying rather than widening coverage
    there. Its anchor never shifts by a raw offset the way the other three do (that
    corrupted the digit alignment -- a leftover nonzero digit at a swept position
    would add on top of that position's own 0..9 sweep and overflow past a single
    digit); instead, between batches (Auto, or repeated Run clicks) a pass counter
    increments by one each time, and every drilled position derives its OWN
    committed digit from it via a distinct small-prime step per position, so
    different positions advance at different rates and the explored path looks
    scrambled/varied (e.g. "53254553452543") rather than a single repeated digit --
    pass 0 still reproduces the manual worked example exactly (every position
    commits to "1"). Each batch still drills a genuinely different, previously only
    shallowly-sampled path all the way down from a permanently clean starting point,
    spanning the floor's full magnitude range every single batch. The starting pass
    (default 0) is only used the first time, before any checkpoint exists -- an
    Advanced field lets it be overridden for a fresh start. Because n_locations is
    shared across all five strategies, the default (1000) leaves each individual digit branch only a
    few windows deep for digit_sweep specifically -- an Auto button next to the
    field computes a floor-and-window_m-aware recommendation (enough windows for
    every branch at every position to get roughly 40 windows of depth) without
    disturbing the field's default for the other four strategies. The fifth
    strategy, manual (list), is a one-off explicit offset list with
    no checkpoint, for precisely-chosen positions a fixed step can't express. A
    plain Run scans exactly one batch and updates the
    checkpoint, so clicking Run again continues rather than re-scanning; the Auto
    button instead keeps the same WSL process scanning batch after batch,
    checkpointing after each, until a confirmed hit, Stop, or the floor is exhausted
    -- a "Resetuj checkpoint" checkbox restarts from the Fragment-start field instead
    of continuing. Confirmed hits are written into the exact same per-`(k, variant)`
    hit file the constellation finder itself writes to, so the Constellations tab
    needs no changes at all to pick them up, and this mode never touches the
    constellation finder's own `CHECKPOINT.txt` -- its own checkpoint is a completely
    separate file, since these locations are not tied to any pre-existing prime
    window at all (see `ktuple_sieve_v1.py`'s own module docstring).
- **Ring visualization** -- a seventh top-level tab (between Generation and Benchmark)
  that opens an interactive, GPU-rendered view of prime rings around a chosen `n`, fed
  from whatever is already in storage. See "Ring visualization" below for what it shows
  and how it's launched.
- **Benchmark** -- a throughput chart (numbers generated per second vs. floor depth,
  derived from the actual count of integers swept per floor rather than a window-count
  approximation, so a mode like Hybrid whose swept range is normally far smaller than
  one full window still plots accurately), plus a second chart (sieve speed and write
  speed per floor) whenever the active engine reports that level of phase timing (see
  `prime_sieve_v4_1.py` under "Architecture" below), a full benchmark log table, and
  one-click PDF export covering both charts. The progress bar shown during a generation
  run models the whole pipeline as a sequence of steps (prep, then each sieve batch,
  then done) rather than only moving during the sieve phase and sitting empty through prep.
- **Research (Badania)** -- an inner notebook of five sub-tabs, grouped by shared
  question shape rather than by conjecture name; one is implemented so far, the other
  four are structural placeholders reserved for later phases:
  - **Goldbach** -- checks the strong-Goldbach window property for a chosen `n`:
    whether every even number in `[4, Pmax+2]` (`Pmax` = largest prime `<= n`)
    decomposes into two primes both `<= Pmax` -- exactly the window the project's own
    Lean formalization (`additiveSelfContained_of_hasGoldbachRep`, linked directly
    from this tab) proves unconditionally. "Sprawdz okno" runs a fresh, from-scratch
    check (touch-once: stop at the first witness per `n`, with a full pair drill-down
    in all-combinations mode); "Wizualizacja" instead opens a persistent diagram
    window that reads primes from the already-generated magazyn rather than
    re-sieving, with an `od`/`do` range to scan only part of a large window (`do`
    doubles as the window-defining `n`), a live progress bar (both in the main window
    and inside the Wizualizacja window itself, for fullscreen use), an offer to
    generate any missing storage range on the spot, and a "Rozloz liczbe" exhaustive
    decomposition checker for one specific number against the shown window's base.
  - Square intervals (Legendre/Oppermann/Brocard), prime-generating polynomials
    (Landau/Euler/Bunyakovsky), gaps (Andrica/Firoozbakht/Cramer), and pi(x)
    approximations (li(x)/R(x) accuracy) are tab placeholders -- no computational
    logic behind them yet.
- **Settings** -- laid out as three vertically-scrollable sub-tabs (backup + restore +
  delete together run taller than a non-maximized window, so each sub-tab scrolls
  independently):
  - **Ogolne** -- language switch, light/dark theme switch, and storage-location
    configuration. Saving a language or theme change automatically relaunches the app
    (`primeatlas/app_restart.py`, `os.execv()` in-place process replacement -- exactly
    one PrimeAtlas process exists at any instant, never a manual close-and-reopen) --
    unless a background job (a Generation-tab pipeline/constellation-finder/k-tuple run,
    or this tab's own restore/full-backup/storage-merge job) is currently running, in
    which case it warns instead of restarting, so the change is not silently lost the
    next time the app happens to close.
  - **Backup** -- backup create/list/delete, restore (manifest-based drift detection
    against what is actually on disk, then a checkpointed, pausable/resumable/
    cancellable regeneration job -- see "Restore" below for ordering and engine
    choice; manifests also cover the totals/sieving caches, see "Backup manifest
    contents"), an incomplete-restores list with its own resume/delete, per-floor delete
    (clears one chosen floor's primes and constellations together, or only that
    floor's constellations while leaving its primes untouched -- for a clean
    constellation-finder re-run without regenerating prime data), and the existing
    whole-database delete. Two further sections cover moving real data (not just a
    manifest) between locations -- see "Full-data backup" and "Integrating an
    external storage" below.
  - **Aktualizacje** -- an optional-library installer (currently `sympy`, used by the
    Primality tests sub-tab's factorization when present) that runs natively on
    Windows via `pip`, not through WSL -- checks whether it is already importable and
    installs it on request, with the install's own live output shown in place. Also
    hosts PrimeAtlas's own self-update (`primeatlas/app_update.py`): since the app runs
    directly out of its own git checkout rather than a packaged install, "check for
    update" resolves `origin`'s branch HEAD via the GitHub REST API first (no local git
    or network fetch needed for the check itself), falling back to a real `git fetch` +
    local-HEAD-vs-`origin/main` comparison only when the remote isn't a recognizable
    `github.com` remote or the API call fails; "download" fetches and fast-forwards
    (`git merge --ff-only`) -- refused outright (no files touched) if the working tree
    has uncommitted changes or local history has genuinely diverged from `origin`, so an
    in-progress edit is never silently clobbered. A leftover git lock file from an
    interrupted process (or a momentary hold by another concurrent git invocation) is
    told apart from a real divergence by attempting an OS-verified release (a rename
    that only succeeds if nothing still has the lock file open) and retried
    automatically for close to 30 seconds before surfacing an error, rather than
    leaving the user stuck with a raw git error they have no way to resolve themselves.
    Two checkboxes control the feature overall: auto-check on startup (on by default --
    a background, non-blocking probe a few seconds after launch) and auto-download
    without asking (off by default, since unlike the read-only check this one changes
    files on disk). A manual "Sprawdz teraz" button works independently of the
    auto-check toggle. When a downloaded update needs a restart to take effect, the
    same job-running guard used by the theme/language auto-restart above applies.

## Search

Searching for a specific number -- from either Storage sub-tab (Prime numbers or
Constellations), or from the Constellation calculator -- distinguishes three outcomes
instead of one generic "not found":

- The window the number would fall in genuinely is not on disk yet -- offers to
  generate just that one window (via a direct, ceiling-aware dispatch -- primesieve
  mode's targeted single-window path when the window falls under libprimesieve's own
  uint64 limit, the orchestrator launched directly at that exact window otherwise --
  never a from-scratch backfill from window 0), then automatically re-runs the same
  search once generation finishes.
- The number is a confirmed prime, but its floor has no recorded constellation hits at
  all -- offers to run the constellation finder for that floor, then re-checks
  participation. The Constellation calculator's own Search additionally checks the
  *specific* pattern it just calculated (not merely "does this floor have any hits for
  anything"), so the offer still appears correctly even on a floor that already has
  hits for some other pattern.
- The window is already on disk and the number still is not found in it -- a
  definitive "this number is composite" message, distinct from the ambiguous
  missing-data case above.

Numeric fields throughout the app (offsets, floor numbers, search boxes) also accept
thousands-grouped input -- spaces or commas, e.g. `23 081 664 151` or
`23,081,664,151` -- as well as plain integers or simple expressions like `10**5+3`,
making it easy to paste a number copied from another source.

## Floor semantics

A "floor" is a digit-count range: floor `N` covers `[10^N, 10^(N+1))`. Generation works
in fixed-width windows (10,000,000 numbers by default); how a floor relates to that
window width falls into two regimes:

- **Floors 0-6** are each narrower than one window (floor 6 is only 9,000,000 numbers
  wide), and together span exactly `[1, 10,000,000)` -- one window's worth. Requesting
  any floor in this range generates and completes, in a single pass, every one of
  floors 0-6 that is not already on disk, each written to its own `10p{N}/` folder. A
  floor only partially covered by wherever the batch happens to end is left out
  entirely rather than written half-finished.
- **Floors 7 and up** are each an exact multiple of the window width (floor 7 = 9
  windows, floor 8 = 90 windows, and so on), so a window never straddles a floor
  boundary at this depth. Floor-only and Range requests are capped at the requested
  floor's own last window -- anything beyond that boundary is dropped, not silently
  written under the wrong floor's folder. Exploration mode is the one intentional
  exception: it is meant to march forward indefinitely across many windows without
  that cap, since deep, open-ended continuation is its whole purpose.

## The primesieve mode

Every other engine (Floor only, Range, Exploration -- all three ultimately run
`orchestrator_loop_v2.py` / `prime_sieve_v3.py` or `v4.py`) links a small custom C wrapper
around libprimesieve's *internal* segment-sieving functions, wrapped in this project's own
parallel batching/orchestration machinery (workers, batches, a shared mmap buffer -- see
"Window count, throughput, and RAM" below). **primesieve mode** is different: it calls
libprimesieve's own top-level public C API function, `primesieve_generate_primes()`,
directly -- no custom engine, no batching, no orchestrator in between (see
`prime_sieve/prime_sieve_primesieve.py`). It maps the result onto exactly the same on-disk
format and folder layout as every other engine, so a floor generated through this mode is
indistinguishable, from the rest of the application's point of view, from one generated any
other way.

The trade is libprimesieve's own domain limit: it operates on the `uint64_t` range, so
nothing above `primesieve_get_max_stop()` (currently `2**64 - 1` =
18,446,744,073,709,551,615, which falls in the middle of floor 19, not at a floor boundary)
can be generated this way. A request that would cross that ceiling is truncated to it --
the run still launches for whatever part of the request is reachable, and both the Quick
generation panel (before launching) and the console output (while running) explain the
truncation and point at Floor/Range/Exploration mode for anything past it, since those three
have no such ceiling (at the cost of being slower). A request entirely past the ceiling is
rejected outright before anything launches.

primesieve mode's Quick generation fields differ from the other three: instead of a From/To
range, it takes a Floor + From (starting point) + Width (window-count multiplier) -- the same
floor-relative navigation Floor-only mode uses, rather than Range mode's absolute pair. Its
own Auto button fills From with wherever that floor's storage currently ends (not a
RAM-based suggestion, since this mode has no RAM-driven reason to keep window count small --
see "Window count, throughput, and RAM" below), making it easy to see where a floor's
generated data currently stops and extend it without hand-computing the continuation point.
Because this mode never allocates the combined shared buffer the other three depend on, its
Width field is not capped at their RAM-driven limit of 1,000 -- it can request as many
windows in one run as libprimesieve's own `uint64_t` range allows.

libprimesieve is an independent, third-party, open-source project by Kim Walisch
(https://github.com/kimwalisch/primesieve, BSD 2-Clause License) -- see `NOTICE.md` for the
full attribution. The Quick generation panel shows this attribution directly whenever
primesieve mode is selected, not just in source comments.

## The cudasieve mode (optional GPU engine)

A fifth engine, `prime_sieve/prime_sieve_cudasieve.py`, shells out to CUDASieve, an
independent, third-party, GPU-accelerated sieve of Eratosthenes by Curtis Seizert
(https://github.com/curtisseizert/CUDASieve, **GNU GPLv3** -- a different, copyleft license,
NOT the same as primesieve's BSD or this project's own). Like primesieve mode, it maps its
output onto this project's own PGS2 window format and the same sharded `source_primes/`
folder layout, so a floor it generates is fully interchangeable with one from any other
engine. UNLIKE primesieve mode, it never links a library into this process at all -- see
that file's own module header, "PROCESS BOUNDARY, NOT LINKING", for why that distinction
specifically matters for a GPLv3 dependency: it is invoked purely as a separate OS
subprocess, never vendored into this repository.

Installing it is entirely optional and opt-in, from Settings > Aktualizacje
(`primeatlas/settings_tab.py`): the installer clones/builds it fresh from its own GitHub
repository into your WSL home folder and shows you its ACTUAL, just-fetched `License` file
text, requiring explicit acceptance before the build step ever runs -- not a copy of the
license kept in this project. Requires an Nvidia GPU and the CUDA Toolkit (`nvcc`) inside
WSL; `cmd_build()` autodetects `CUDA_DIR` and the GPU's compute-capability architecture
flags (via `nvidia-smi`) instead of trusting CUDASieve's own makefile default (Maxwell-era,
circa 2014), and patches in `-rdc=true`, which modern `nvcc` versions require for
CUDASieve's own template code to link -- confirmed on real hardware (RTX 5070 + WSL2 +
CUDA 13.3).

cudasieve mode's Quick generation fields are identical in shape to primesieve mode's own
(Floor + From + Width, same floor-relative navigation, same uint64-range Width field with
no RAM-driven cap), with two engine-specific differences: the uint64 ceiling check uses
CUDASieve's own limit (`2**64 - 1`, same domain as libprimesieve's), and there is an
additional lower bound -- CUDASieve's own CLI documents that printing individual primes is
ignored below `2**40` (~1.0995e12). A request entirely below that value is rejected with a
clear error rather than silently returning an incomplete result; its own Auto button clamps
a too-low continuation point up to `2**40` instead of handing back a value the engine would
just reject anyway. Use primesieve, Floor, Range, or Exploration mode for anything below
that floor. CUDASieve's own README also documents a roughly 1-in-20,000 chance of an
off-by-one count under concurrent GPU load -- worth keeping in mind for anything where exact
counts matter; `generate_primes_in_range()` does a strictly-increasing sanity check on the
returned primes as a (partial) defense against a badly parsed or truncated stdout stream.

## The Hybrid mode

Hybrid is a sixth Quick generation mode, deliberately narrower in scope than the other
five: a single-window experimental engine built around one MAIN prime cap and a small
filter-prime tuple, rather than sieving a whole range the way libprimesieve or this
project's own orchestrator do. Every candidate up to a limit `N = b*d - 1` (`b` the
prime just above MAIN, `d` the prime just above the filter tuple's own top member) is
guaranteed eliminated either by MAIN's ordinary sieve or by the filter tuple's own
residue check -- the two visible parameters are "MAIN <=" (the prime cap) and "Filter
primes / stage" (how many filter primes to use), and a debounced (350ms) background
reach preview shows the resulting range live as either is edited, without blocking typing.

Rather than an explicit From/To range, Hybrid is driven by a "Cel" (intent) picker: a
concrete number, "continue this floor" (from wherever that floor's storage currently
ends), "fill this floor's first gap", or an explicit floor + window index -- each
resolves to exactly one standard PGS2 window before anything launches, so Hybrid's
output is ordinary window data, indistinguishable from any other engine's, and never
overwrites or disturbs windows already on disk. Before actually launching, the chosen
MAIN and filter-count values are auto-minimized (smallest MAIN, then the smallest
sufficient filter count for the resolved window) via the same policy function the reach
preview itself uses -- if the values typed in weren't already minimal, the console
reports what was adjusted and why.

A single MAIN+filter combination can only reach up to `10**11` (inclusive; also capped
at 1,000,000 filter primes) -- a target past that limit cannot be reached by Hybrid at
all, so rather than failing outright it offers to switch to primesieve mode instead,
with that mode's own Floor/From/Width fields pre-filled from the request. A native C
backend (reusing the same segment-sieving primitive `prime_sieve_v4.py`'s own engine
uses for MAIN) does the actual work when built; a pure-Python reference implementation
is used automatically as a fallback otherwise, at a real cost to speed but not
correctness -- both produce byte-identical output.

## Window count, throughput, and RAM

This section is about Floor only, Range, and Exploration mode -- the three engines that run
through this project's own batching/orchestration pipeline. primesieve mode (see above) has
no such relationship: it makes one direct call into libprimesieve's own bulk-generation
function per run, with no batches, workers, or shared buffer of this project's own involved.
Hybrid (see above) also sits outside this pipeline -- it sieves a single, small,
explicitly-resolved window rather than a batch of windows sharing one buffer.

The Quick generation panel's window-count fields (and the low-level form's own) have a
direct, mechanical relationship to both how fast a run goes and how much RAM it needs.
Both effects trace back to the same design choice: one invocation of the sieve engine
processes a whole batch of adjacent windows as a single *combined range*, sieved into
one shared output buffer, rather than one window at a time.

**Why more windows per run means better throughput.** Splitting the combined range
across parallel workers is not done window-by-window -- it is split into a small,
*fixed* number of equal-cost batches (24 parallel processes x 2 batches each by
default = 48 batches, regardless of how many windows are being generated). Each batch
pays a real, measurable one-time setup cost inside the C engine (positioning
`libprimesieve`'s iterator to that batch's own starting point -- a "bootstrap" call).
That fixed overhead is paid exactly the same number of times whether the run covers 10
windows or 1,000: the more windows batched into one invocation, the more actual sieved
output that same fixed setup cost gets amortized over, so numbers-per-second throughput
improves as window count grows -- up to the point where something else becomes the
bottleneck.

**Why more windows per run means more RAM.** The combined range is sieved into one
single, shared, bit-packed buffer (one bit per candidate number -- prime or not),
allocated once before any worker process starts, so every worker writes directly into
the same physical memory instead of returning its own private copy. That buffer's size
is `window_count * window_width / 8` bytes, growing *linearly* with window count. This
is deliberately much cheaper than it used to be (earlier engine revisions gave every
worker its own private buffer, multiplying peak RAM by the worker count), but it is
still the hard ceiling: however much window count helps throughput, the whole combined
buffer for one run has to fit in RAM at once. The Quick-gen panel's "Auto" button reads
WSL's currently available memory and suggests a window count against exactly this
formula (using half the available RAM as a safety margin, since the buffer is not the
only thing using memory during a run) -- pushing window count past that estimate risks
an out-of-memory failure rather than a graceful slowdown.

In short: within whatever RAM is available, a larger window count is close to strictly
better for throughput; RAM is the only reason not to simply set it as high as possible.

## Backup manifest contents

A backup is a lightweight JSON snapshot ("what SHOULD exist"), not a copy of the actual
prime/constellation data -- a single floor can be hundreds of GB. Per floor it records:
which `PRIME_WINDOW_*.bin` filenames exist, which constellation `k{K}/variant{V}` hit
files exist plus that floor's `CHECKPOINT.txt` text, a copy of `benchmark_log.csv`, and
(added 2026-08-18) each floor's `.portal_totals_cache.json` entry and
`sieving_primes_count_cache.json` -- the two on-disk caches that exist purely to speed up
prime-count display, not to hold data. Restoring these two costs nothing to skip (they
just get recomputed the next time that floor is visited), but restoring them from the
backup avoids that recompute -- for a heavily-populated floor, rescanning every window
header from scratch has been measured at roughly 78 seconds for one 15,101-file floor.

### Moving floor data between storages (magazyny)

A floor's `10p{N}/` directory is self-contained enough to be physically copied from one
storage location into another (e.g. building a fresh, empty storage but bringing some
already-generated floors along from an older one) -- no backup/restore cycle is required
for this to work correctly. Each floor also carries its own `floor_meta.json`, a full copy
of that floor's `benchmark_log.csv` rows, updated every time a generation run logs a new
one. Since `benchmark_log.csv` itself lives at the storage root (shared across all floors,
not per-floor), a raw directory copy would otherwise leave that floor's generation history
behind in the old location. The app's totals-cache background worker (the same one that
scans a floor's file headers the first time it is visited in the Prime numbers tab) checks
every floor's `floor_meta.json` on each visit and imports any rows not already present in
the local `benchmark_log.csv`, so a moved-in floor's Benchmark tab entry appears exactly as
if it had been generated in that storage -- nothing is lost, and this needs no explicit
action from the user. A floor's own `CHECKPOINT.txt`/`BOUNDARY_CHECKED.txt`
(constellation-scan progress markers) have no merge logic of their own -- if a floor is
merged in from a storage that had independently scanned some of the same windows, or a
checkpoint simply names a window no longer present, some windows may get rescanned. That's
harmless: rescanning a window whose hits are already recorded used to crash on the
duplicate append (a strict-increase assertion in the on-disk hit format); it now silently
skips the already-known values instead.

Physically copying a WHOLE external storage's root (not just one floor's directory) this
way, however, is NOT recommended -- see "Integrating an external storage" below for why,
and for the dedicated feature that does this correctly.

### Full-data backup

The metadata-only backup above never copies actual bytes -- restoring it always means
regenerating (re-sieving) whatever is missing. Settings tab -> Backup also offers a
second, independent backup mode: a real, gzip-compressed, per-file copy of a chosen
floor's data (window and constellation-hit files) at a location OUTSIDE the storage,
picked per floor (Backup lists every floor currently in storage, pre-selecting/marking
whichever ones' MEASURED total generation time -- summed from `benchmark_log.csv`, real
runs only -- exceeds one hour, since regeneration cost depends on how much of a floor
is actually populated, not just its floor number). Restoring from this copies bytes
back directly instead of re-sieving -- far faster for a floor that was genuinely
expensive to generate the first time, at the cost of needing that much extra disk space
somewhere else.

Each floor gets ONE persistent entry at the destination (not a growing pile of
timestamped snapshots): re-running the backup for a floor that has grown since only
copies what's new. Updating a backup only ever ADDS files, never removes any -- even if
something disappeared from the live side (e.g. an accidental floor delete) -- since a
backup that silently followed a live mistake would defeat its own purpose. The one
exception is the constellation-scan progress markers (`CHECKPOINT.txt`/
`BOUNDARY_CHECKED.txt`), which are always re-synced to whatever the live floor
currently says (they're scalar "how far did we get" pointers, not data); restoring them
back never regresses a live floor's own, possibly further-along, progress. The
destination is validated to be neither inside the storage nor wrapping it -- a backup
living inside the very thing it protects isn't a backup.

### Integrating an external storage

Growing a local storage by folding in someone else's -- data downloaded from GitHub, or
copied from another machine -- the way GIMPS grows from many contributors' partial
results. Copying a whole external storage's root with a generic file-copy tool forces
resolving conflicts on files that were never meant to be merged that way: blindly
overwriting `benchmark_log.csv` silently discards whichever side's rows aren't picked
(there's no way to file-level "merge" two CSVs), and `.portal_totals_cache.json`/
`.portal_generation_settings.json` are just self-healing/local-install convenience
files with no real merge semantics either way.

Settings tab -> Backup -> "Integruj zewnetrzny magazyn" does this correctly: point it at
an external storage folder, click Podglad (preview) to see, PER FLOOR, whether it's a
brand-new floor or one that merely gains some missing files, plus a total size estimate
-- nothing is copied until Integruj is confirmed. Only floor directories are ever
touched; the three root-level files above are never read or written by this feature at
all. A floor's generation history (`floor_meta.json`) is imported additively, and then
flows into the local `benchmark_log.csv` automatically the next time that floor is
visited in the app (see "Moving floor data between storages" above) -- so the person
never has to resolve those conflicts themselves.

## Restore

Restoring from a backup (Settings tab) regenerates whatever a saved manifest says should
exist but currently does not, as a checkpointed job that can be paused, resumed, or
cancelled and resumed again in a later session. The cheap caches described above (totals,
sieving, `floor_meta.json`) are restored first, before any window regeneration begins.

A restore run is ordered in two strict phases across every floor named in the diff, rather
than finishing one floor end-to-end before starting the next: every floor's missing prime
windows are restored first, in ascending floor order, before any floor's constellation hits
are touched. This ordering matters because the constellation finder reads a floor's own
`source_primes` files -- running it against a floor whose windows are not fully back yet
would either fail outright or silently record an incomplete hit set.

Floors 0-6 restore as a single combined pass, mirroring Quick generation's own low-floor
completion (see "Floor semantics" above): requesting any one of them fills every other
floor in 0-6 that is not already on disk in that same run, instead of launching once per
floor.

For a floor whose range fits entirely under libprimesieve's own ceiling (see "The
primesieve mode" above), restore uses primesieve mode -- the whole missing range in one
run, with no RAM-driven window-count chunking needed. Floors above that ceiling fall back
to the orchestrator pipeline, using a RAM-based automatic window count per run -- the same
formula behind Quick generation's own "Auto" button, re-evaluated fresh for each floor
rather than a fixed default.

## Ring visualization

Opens an interactive, GPU-driven visualization of prime rings around a chosen `n`, fed
primes from whatever is currently in storage. Unlike every other tab, it does not build
its own tkinter widgets for the visualization itself: `rings_tab.py` launches
`ring_viz/renderer.py` (moderngl + GLFW) as a separate native Windows subprocess, since a
GL render loop does not compose with Tkinter's own `mainloop()`. Closing the render
window (Esc, or its own close control) doesn't kill the process outright -- it hides and
idles in the background, preserving playback position, tempo, and audio state, so
clicking Start / Resume again continues exactly where it left off rather than
relaunching from scratch; an explicit Reset is needed to actually start over. An
always-visible HUD panel in the main tkinter window mirrors the renderer's own live
status (current N, ring count, rebuild time, running/paused state) even while the render
window itself is hidden.

Configurable before launch: point size and a separate hit-ring point size (the axis
rings), HUD font size, and three independent audio channels (rings `<= 7`, rings `> 7`,
and the LCM ring) each assignable to one of seven instruments (sine/triangle/square/
sawtooth/bell/choir/mute) -- audio requires the optional `sounddevice` package and is
otherwise silently unavailable with a clear console message, never a crash. Window
highlight checkboxes for the Bertrand, Legendre, and General Law windows (the same three
families the standalone Structural Sieve HTML tool defines) can be enabled together,
with the General Law family's own theta and sliding/stepped mode fields; these, like
point size and audio, are launch-time-only -- fixed for the life of one running
subprocess and only editable again after Reset. Every one of these launch-time fields
remembers its last-used value across app restarts (`AppSettings.ring_viz_params`) --
only a fresh install falls back to hardcoded defaults -- and Reset unlocks them for
editing without resetting their contents, so a relaunch always starts from wherever the
previous run left off unless a field is actually retyped. A Track P field (plus an Auto orbit
toggle) follows specific primes' LCM/resonance state live in the HUD; Load Range
auto-tracks every prime in a chosen range at once instead of naming them individually.
Playback controls (Space to start/stop, `[`/`]` and `-`/`=` to adjust speed, R to reset)
drive automatic advancement through N; a resonance log and a surviving-primes list panel
are both collapsible, with their own counts shown in the header. F11 toggles fullscreen,
restoring the window's prior geometry on exit (and releasing the fullscreen monitor
before the process is allowed to pause, so a paused, hidden process never leaves a
monitor stuck in exclusive-fullscreen mode).

## Architecture

```
prime_atlas_v1.py           thin composition root (tkinter); builds the main window and
                              its seven top-level tabs (three of which -- Prime numbers,
                              Constellations, Research -- are themselves inner
                              notebooks of sub-tabs, see "Features" above; a further one,
                              Ring visualization, launches a separate GPU-rendered
                              subprocess rather than building tkinter widgets of its own
                              -- see "Ring visualization" above), owns the handful of
                              genuinely CROSS-tab pieces (module globals
                              PORTAL_FOLDER/TRANSLATOR/T/APP_SETTINGS; the totals-cache
                              and search PersistentWorkers, shared by more than one
                              tab; the Prime-numbers/Constellations background tree
                              scans; the three "generate missing data, then retry"
                              methods), and otherwise just instantiates and wires each
                              tab class below
primeatlas/                 backend + GUI-tab package, one file (or pure-logic/UI pair
                              of files) per feature
  GUI tab classes (ttk.Frame subclasses, one file each unless noted):
  primes_tab.py               PrimesTab -- Prime numbers -> Storage sub-tab
  primesieve_calc_tab.py      PrimesieveCalcTab -- Prime numbers -> primesieve
                              calculator sub-tab (also holds
                              build_primesieve_query_argv/run_primesieve_query_wsl,
                              its only callers)
  primality_tab.py            PrimalityTab -- Prime numbers -> Primality tests sub-tab
                              (UI only; primality.py below is the pure-logic backend)
  constellations_hits_tab.py  ConstellationsHitsTab -- Constellations -> Storage
  constellations_calc_tab.py  ConstellationsCalcTab -- Constellations -> Constellation
                              calculator
  constellations_records_tab.py ConstellationsRecordsTab -- Constellations -> Records
                              table
  research_goldbach_tab.py    ResearchGoldbachTab -- Research -> Goldbach sub-tab (UI;
                              research_goldbach.py below is the pure-logic backend)
  generation_tab.py           GenerationTab -- the Generation tab (largest one: Quick-
                              gen panel -- Floor only/Range/Exploration/primesieve/
                              cudasieve/Hybrid modes -- plus the loop/orchestrator-
                              direct/primesieve/k-tuple-sieve launch forms;
                              generation.py below is the pure-logic backend;
                              hybrid_controls.py holds the Hybrid mode's own debounced
                              reach-preview/auto-fit UI logic, kept in its own file
                              since it runs its preview calculation off the Tk main
                              thread)
  rings_tab.py                RingsTab -- the Ring visualization tab: launches
                              ring_viz/renderer.py (moderngl/GLFW) as a separate native
                              Windows subprocess, and exchanges state with it over
                              stdin/stdout (HUD JSON, pause/resume commands) rather than
                              building any of the visualization itself as tkinter
                              widgets; see "Ring visualization" above
  benchmark_tab.py            BenchmarkTab -- the Benchmark tab (charts + PDF export;
                              benchmark.py below is the pure-logic backend)
  settings_tab.py             SettingsTab -- the Settings tab (Ogolne/Backup/
                              Aktualizacje sub-tabs, each independently scrollable),
                              incl. the optional-library (sympy) installer

  pure-logic backends (no tkinter) for the larger tabs above:
  generation.py                window/floor arithmetic, generation-settings
                              persistence, argv builders for every launch engine,
                              WslLoggedRunner/LocalLoggedRunner, WSL RAM/CPU probing
  benchmark.py                 reading/normalizing benchmark_log.csv rows
  constellations.py            constellation (k-tuple) hit storage: listing, search,
                              PDF/CSV export
  research_goldbach.py         storage-bridging layer between goldbach_window.py's
                              pure arithmetic and ResearchGoldbachTab's UI
  goldbach_window.py           Goldbach strong-window check/visualization core
                              arithmetic (see "Features" above) -- reads primes from
                              the on-disk magazyn via the same source_primes format
                              the Prime numbers tab browses
  primality.py                 Miller-Rabin/Fermat/Solovay-Strassen primality tests
                              plus factorization (trial division + Pollard's rho, or
                              sympy.factorint() if installed) -- pure Python, no WSL
  ring_geometry.py              ring/drum placement math, plus Bertrand/Legendre/
                              General Law highlight-window membership and blended
                              colors -- ported from the standalone Structural Sieve
                              HTML tool's own SieveModel.js; pure functions, no OpenGL
                              or subprocess code (that lives in ring_viz/, below)
  storage.py                    the core prime-window storage layer (listing floors/
                              files, totals caches, format_duration/format_bytes)
                              shared by several tabs above, not specific to any one

  Settings-tab-only backend pieces (originally the whole point of this package, before
  it grew into every other tab too -- see this package's own __init__.py docstring):
  app_settings.py, manifest.py, backup_store.py, restore_job.py, floor_meta.py,
  full_backup.py, storage_integrate.py, delete_manager.py -- see "Backup manifest
  contents" / "Moving floor data between storages" / "Full-data backup" /
  "Integrating an external storage" below for what each backs
  app_restart.py                execv()-based in-place relaunch, used by the
                              theme/language auto-restart and the self-update
                              restart-after-download prompt (Settings > Ogolne /
                              Aktualizacje)
  app_update.py                 GitHub-API/git-fetch based self-update check + fetch-
                              and-fast-forward download, with OS-verified git-lock
                              recovery (Settings > Aktualizacje) -- pure Python, no
                              tkinter

  ring_viz/                      the GPU renderer subprocess launched by rings_tab.py --
                              kept in its own subpackage since it's a separate OS
                              process, not additional widgets in the main Tk process;
                              see "Ring visualization" above
    renderer.py                  moderngl/GLFW render loop -- camera, HUD (on-canvas GL
                              bitmap-font text, no native window-chrome dependency),
                              audio wiring, CLI entrypoint (invoked via rings_tab.py's
                              build_renderer_argv())
    audio.py                     standalone tone-synthesis module (sine/triangle/
                              square/sawtooth/bell/choir/mute) for the three
                              independently assignable audio channels (low/prime/lcm)
    window_mode.py                shared General Law theta/mode CLI parsing, used by
                              both build_renderer_argv() and renderer.py itself so the
                              two never drift out of sync

  shared infrastructure (used across many tabs, not feature-specific):
  background.py                run_in_background()/PersistentWorker -- shared
                              background-job helpers used by any tab that launches a
                              one-shot call or a queue of same-kind jobs off the Tk
                              main thread
  pdf_writer.py                 a minimal, dependency-free PDF writer (text, lines,
                              filled rects, basic pagination) shared by the Benchmark
                              tab's export and the Constellations Records table's export
  generation_console.py        stacked/detachable live-output console used by the
                              Generation tab's loop/constellation/k-tuple sections
  widgets.py                    small generic tkinter helpers (e.g. FlowRow) with no
                              application-specific state
  theme.py                      light/dark palette DATA only -- the actual
                              ttk.Style()/option_add() application lives in
                              PortalBrowserApp._apply_theme(), which needs a live Tk
                              root this module deliberately never touches
  i18n.py                       Translator: loads one of two static locale files
  locales/                      strings_en.json, strings_pl.json, app_settings.json
prime_sieve/                 sieve and orchestration pipeline (invoked via WSL)
  prime_sieve_v1.py          PGS1 output format, process-pool orchestration
  prime_sieve_v3.py          PGS2 output format, shared-memory mmap orchestration;
                              also implements low-floor completion (floors 0-6) and
                              the per-floor sieving-prime-count cache
  prime_sieve_v4.py          same as v3, plus an inlined fast-path modulo in the C
                              engine for the per-sieving-prime phase computation
  prime_sieve_v4_1.py        same as v4, plus base-gen/sieve/write phase timing and
                              bytes-written tracking, feeding the Benchmark tab's
                              second (sieve-speed/write-speed) chart
  prime_sieve_primesieve.py  "primesieve mode" -- calls libprimesieve's own public C API
                              (primesieve_generate_primes()) directly via ctypes, no custom
                              engine or batching pipeline; see "The primesieve mode" above
  prime_sieve_cudasieve.py   "cudasieve mode" (optional, opt-in) -- shells out to the
                              third-party CUDASieve GPU CLI as a separate OS process
                              (never linked, GPLv3 process boundary); see "The cudasieve
                              mode" above
  hybrid_policy.py           Hybrid mode's parameter minimization (MAIN cap + filter
                              count -> reachable limit), shared by the reach preview and
                              the actual launch-time auto-fit; MAX_TARGET=10**11,
                              MAX_FILTER=1_000_000 are its hard caps
  hybrid_planner.py          pure extension-planning invariants (MAIN<=a, filter tuple
                              over [b,c], N=b*d-1 correctness contract) -- no I/O
  hybrid_reference.py        pure-Python reference tuple-filter sieve, PGS2-output-
                              compatible -- the fallback used when the native backend
                              below isn't built
  hybrid_native.py           ctypes binding to hybrid_filter_engine.c's native tuple-
                              filter backend (reuses v4's own segment-sieving primitive
                              for the MAIN sieve)
  hybrid_filter_engine.c     C tuple-filter sieve core for hybrid_native.py (ctypes)
  hybrid_sieve.py            Hybrid mode's own launch/orchestration entrypoint --
                              resolves the selected intent (a concrete n, "continue this
                              floor", "fill this floor's first gap", or an explicit
                              floor+window index) to exactly one canonical PGS2 window,
                              then runs MAIN+filter over it; see "The Hybrid mode" above
  primesieve_query.py        one-shot standalone libprimesieve queries (count/nth/
                              next/prev primes) behind the Prime numbers tab's
                              primesieve calculator sub-tab -- independent of
                              anything already in storage
  prime_sieve_engine_v1.c    C sieve core for prime_sieve_v1.py (ctypes)
  prime_sieve_engine_v3.c    C sieve core for prime_sieve_v3.py (ctypes)
  prime_sieve_engine_v4.c    C sieve core for prime_sieve_v4.py/v4_1.py (ctypes)
  orchestrator_v3.py         single-run driver; a single SCANNER_VERSION flag near
                              the top selects the active engine ("v3", "v4", or
                              "v4.1" -- currently v4.1) instead of separate settings
                              that could drift out of sync with each other
  orchestrator_loop_v2.py    continuous-run driver
  orchestrator_loop_helpers.py
constellation/
  constellation_finder_v1.py  k-tuple pattern search over generated prime data
  ktuple_sieve_v1.py          targeted k-tuple candidate sieve (wheel + trial
                              division + Miller-Rabin) over scattered window
                              locations -- see "Targeted k-tuple sieve" above
  pattern_catalog_v1.py       catalog of supported k-tuple patterns, shared by the
                              constellation finder, ktuple_sieve_v1.py, and the
                              Constellation calculator / Records table sub-tabs
Run_PrimeAtlas.bat           launches the GUI, visible console (errors surfaced directly)
Run_PrimeAtlas_Hidden.vbs    launches the GUI with no console window
```

Generated data is stored under a folder named `CONSTELLATION_PORTAL` (the name predates
and is independent of the application's own name). By default this folder is created
next to `prime_atlas_v1.py`, so the application is self-contained regardless of where
its directory is placed on disk. The location can be overridden either through the
Settings tab or by setting the `CONSTELLATION_PORTAL_DIR` environment variable, which
the sieve, orchestrator, and constellation-finder scripts also read directly when
launched by the GUI. A small `.portal_totals_cache.json` file lives alongside the
generated data, caching each floor's prime count and on-disk size so the Prime numbers
tab does not have to re-read every file's header on every visit.

## Requirements

GUI:
- Windows
- Python 3 with the standard library (`tkinter` included)
- Optional: `sympy`, for faster factorization in the Primality tests sub-tab. Not
  required -- without it, factorization falls back to a pure-Python trial-division +
  Pollard's rho implementation. Installable from inside the app itself (Settings tab's
  optional-library installer, runs `pip install --user sympy` natively on Windows, no
  WSL involved).
- For Ring visualization: `numpy`, `moderngl`, and `glfw`, installed into the same native
  Windows Python that runs `prime_atlas_v1.py` (the renderer is launched as a plain
  subprocess of that same interpreter, not through WSL). Optional: `sounddevice`, for the
  tab's live audio -- without it, audio is silently unavailable with a clear message in
  the console, never a crash.

Generation pipeline (only needed to generate new data; browsing existing data needs
only the GUI requirements above):
- WSL with a Linux distribution
- `gcc`, `libprimesieve` (headers and library) for building the C sieve engines
- Python 3 with `numpy` inside WSL
- For primesieve mode specifically: the libprimesieve *shared library* installed where
  `ctypes.util.find_library("primesieve")` (or a plain `libprimesieve.so` on the linker
  search path) can find it at runtime -- the same library the `-lprimesieve` build step
  below links against, just also needed as a runtime `.so`, not only at build time.

## Building the sieve engines

From WSL, inside `prime_sieve/`:

```
gcc -O3 -shared -fPIC prime_sieve_engine_v1.c -o prime_sieve_engine_v1.so -lprimesieve -lstdc++ -lm
gcc -O3 -shared -fPIC prime_sieve_engine_v3.c -o prime_sieve_engine_v3.so -lprimesieve -lstdc++ -lm
gcc -O3 -shared -fPIC prime_sieve_engine_v4.c -o prime_sieve_engine_v4.so -lprimesieve -lstdc++ -lm
```

Prebuilt `.so` files are included; rebuild if the WSL environment's glibc/architecture
differs from the one they were built on.

## Running

Double-click `Run_PrimeAtlas.bat` (visible console, useful for diagnosing startup
errors) or `Run_PrimeAtlas_Hidden.vbs` (no console window). Equivalently:

```
python prime_atlas_v1.py
```

Language (English/Polish, English by default) and theme (light/dark, dark by default) are both set from
the Settings tab; saving either automatically restarts the app so the change takes
effect immediately (see "Settings" above), unless a background job is running, in which
case a restart is required manually once it finishes.

## License

Distributed under the license at the repository root (`License`, PolyForm Noncommercial
1.0.0). See `NOTICE.md` for attribution requirements.
