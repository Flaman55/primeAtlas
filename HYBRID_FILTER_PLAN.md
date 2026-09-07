# Hybrid filter engine -- phased integration plan

Branch: `hybrid-filter-integration` (from `main`, created 2026-09-07).

## Goal

Add a **Hybryda** mode to Generation.  It generates independently of the
magazyn: MAIN \(P_{\le a}\) and the filter \([b,c]\) are constructed by the
backend, while the magazyn is only the ordinary PGS2 output/cache.  Existing
windows are excluded from the requested work; gaps are filled and existing
files are never overwritten.  Output remains ordinary PGS2 prime-window data,
indistinguishable to the rest of PrimeAtlas from data made by the current
engines.

The correctness contract for a planned extension is:

\[
  b=\operatorname{nextprime}(a),\quad
  d=\operatorname{nextprime}(c),\quad
  N=b d-1.
\]

For every candidate \(n\le N\), it is composite iff it is eliminated either
by a MAIN prime \(p\le a\), or by a required tuple product of filter primes
in \([b,c]\).  Every tuple order permitted by \(b^r\le N\) must be covered.

## Working rules

- No change to pre-existing PGS2 windows.  Empty, partial and gapped storage
  are all valid output states; only missing planned windows are generated.
- `prime_sieve_v4` remains untouched as a correctness and performance control.
  Hybrid has separate files until evidence supports a later consolidation.
- `k_adv` is a visible Quick-generation parameter named **filter-prime count
  per stage**, not an Advanced-settings-only value.
- In Quick mode, **Floor** chooses the owner/range of output windows and
  **Width** chooses their count.  Iterations repeat that fixed-width block so
  one built MAIN/filter base can be amortised.  A floor never owns values from
  another floor merely because a broad run began there.
- A phase is complete only after its listed tests pass and its commit exists.
- After each phase, update the checkbox, test evidence and commit hash in this
  file before starting the next phase.
- Tests are the repository's existing or newly added executable test scripts,
  not informal re-checks recreated in chat.  If this agent's environment lacks
  access to WSL, hardware, a library or another required dependency, it will
  state that limitation explicitly, provide the exact script command for Artur
  to run, and mark the phase **awaiting test evidence**.  It will not repeat
  blocked attempts or treat an unavailable test as passed.

## Phase checklist

### [x] Phase 1 — Hybrid Quick-mode contract and UI

Add the `hybrid` mode beside Floor, Range, Exploration, primesieve and
cudasieve.  Its continuation/iteration behavior follows Exploration, while
its visible parameters include the filter-prime count per stage (`k_adv`).
Add independent Tk variables, PL/EN locale strings, validation and a
`build_hybrid_argv()` command contract; do not overload another mode's state.

**Acceptance tests**

- Extend `unitTests/test_generation_launch_planning.py` with a launch recorder
  for hybrid mode.
- Extend `unitTests/test_generation_window_arithmetic.py` for hybrid parameter
  validation and window-boundary planning.
- Run the existing Quick-generation regressions relevant to the touched code.

**Commit:** `feat(generation): add hybrid quick-mode UI`

**Evidence / commit:** static checks passed (`git diff --check`, both locale
files parsed as JSON); Artur confirmed both executable scripts passed:

```powershell
cd H:\PrimeAtlas_gpt\primeAtlas
python unitTests\test_generation_window_arithmetic.py
python unitTests\test_generation_launch_planning.py
```

Commit: `5bdad36 feat(generation): add hybrid quick-mode UI`.

### [x] Phase 2 — Pure hybrid extension planner

Create a GUI-free planner that validates a continuous base, determines
\(a,b,c,d,N\), the bootstrap interval and the maximum tuple order.  It must
refuse a gapped/insufficient base or a requested range for which its selected
tuple capability is incomplete.

**Acceptance tests**

- New pure-Python planner test: pairs, triples, quadruples and each exact
  threshold \(b^r\).
- Tests for no-gap continuation, invalid input and deterministic plans.

**Commit:** `feat(hybrid): add extension planner and invariants`

**Evidence / commit:** static `git diff --check` passed; Artur confirmed the
following executable test passed:

```powershell
cd H:\PrimeAtlas_gpt\primeAtlas
python unitTests\test_hybrid_planner.py
```

Commit: `1979742 feat(hybrid): add extension planner and invariants`.

### [x] Phase 3 — Reference hybrid backend and PGS2 compatibility

Implement a correctness-first WSL runner.  It uses a conventional bootstrap
for \([b,c]\), marks MAIN factors in the extension, applies all planned tuple
orders, and writes only new standard PGS2 windows.  This is the reference for
the native backend, not the final throughput target.

**Acceptance tests**

- Small end-to-end ranges agree exactly with `primesieve` counts and values.
- Existing PGS2 files are unchanged; newly written windows follow the normal
  naming, sharding and header conventions.
- Interrupted/invalid work cannot leave a partial window presented as complete.

**Commit:** `feat(hybrid): add verified reference extension backend`

**Evidence / commit:** static `git diff --check` passed; Artur confirmed both
repository test scripts passed:

```powershell
cd H:\PrimeAtlas_gpt\primeAtlas
python unitTests\test_hybrid_reference.py
```

```bash
cd /mnt/h/PrimeAtlas_gpt/primeAtlas
python3 unitTests/test_hybrid_reference_primesieve.py
```

Commit: `078bd87 feat(hybrid): add verified reference extension backend`.

### [x] Phase 4 — End-to-end Generation integration

Connect the Quick-mode command to the reference runner.  Add console output,
stop behavior, real iteration progress, PGS2-compatible benchmark rows and
documentation.  Storage and Constellations must consume hybrid windows without
any special-case code.

**Acceptance tests**

- Command construction and runner-launch tests with subprocess recorders.
- Console/progress parser test using real hybrid-runner output samples.
- Existing Generation launch and progress-bar regressions.

**Commit:** `feat(generation): launch hybrid extension runs`

**Evidence / commit:** Artur confirmed the Windows Generation/reference checks
and the WSL runner/reference-`primesieve` checks passed after the segment-boundary,
path-type and immutable-per-stage-MAIN regressions were corrected.

```powershell
cd H:\PrimeAtlas_gpt\primeAtlas
python unitTests\test_generation_window_arithmetic.py
python unitTests\test_generation_launch_planning.py
python unitTests\test_hybrid_reference.py
python unitTests\test_hybrid_progress_protocol.py
```

```bash
cd /mnt/h/PrimeAtlas_gpt/primeAtlas
python3 unitTests/test_hybrid_sieve.py
python3 unitTests/test_hybrid_reference_primesieve.py
```

Commit: `e977ef1 feat(generation): launch hybrid extension runs`.

### [x] Phase 5 — Native C tuple-filter backend

Add a separate C backend using the established shared-mmap/atomic-OR model:
MAIN marking for \(P_{\le a}\), plus tuple filtering for \([b,c]\).  Keep
per-phase timings for bootstrap, MAIN, tuple filter and writing.  Do not change
`prime_sieve_engine_v4.c` in this phase.

**Acceptance tests**

- Native output matches Phase 3's reference backend and `primesieve`.
- Regression cases across tuple-order thresholds and window boundaries.
- Count-only benchmark records all component timings and total wall time.

**Commit:** `perf(hybrid): add native tuple-filter backend`

**Evidence / commit:** Artur built the separate WSL library and confirmed both
native-vs-reference/`primesieve` and full-runner tests passed.  When the local
library is present, the runner selects it automatically and reports bootstrap,
MAIN, filter and writing times per stage.  `prime_sieve_engine_v4.c` remains
unchanged.

```bash
cd /mnt/h/PrimeAtlas_gpt/primeAtlas/prime_sieve
gcc -O3 -shared -fPIC hybrid_filter_engine.c -o hybrid_filter_engine.so
cd /mnt/h/PrimeAtlas_gpt/primeAtlas
python3 unitTests/test_hybrid_native.py
python3 unitTests/test_hybrid_sieve.py
```

Commit: `02f7228 perf(hybrid): add native tuple-filter backend`.

### [x] Phase 5b — Output-planning correction

Replace the temporary storage-as-MAIN reference runner with independent hybrid
generation.  Add hybrid Width and fixed-base iteration semantics.  Plan missing
windows by the selected floor's standard window indexes, preserve floor
boundaries, skip already-existing files (including gapped layouts), and never
infer mathematical MAIN completeness from storage.  MAIN/bootstrap selection is
an explicit backend concern, not a PGS2 precondition.

**Acceptance tests**

- Empty storage generates the requested first missing windows.
- Partial and gapped storage produces exactly the missing selected windows.
- A broad request crossing a digit boundary files each output window under its
  actual floor, never under the originally selected floor.
- Repeated fixed-width iterations reuse one planned MAIN/filter base whenever
  its proved bound covers the next block.

**Commit:** `fix(hybrid): decouple generation from storage state`

**Evidence / commit:** Artur confirmed the expanded WSL output-state test passed:
empty storage generated normal floor-routed PGS2 output, a rerun skipped the
existing files byte-for-byte, and a deliberate gap regenerated only its missing
window.  Existing UI/argument regressions were also confirmed green after the
Width contract change.

```bash
cd /mnt/h/PrimeAtlas_gpt/primeAtlas
python3 unitTests/test_hybrid_sieve.py
```

Commit: pending in this working step.

### [~] Phase 6 — Measured tuning and release decision

Benchmark the complete operation, not the filter alone, across `k_adv`, MAIN
boundary, tuple order, workers, instances and window size.  Compare the same
new PGS2 range with v4/primesieve.  Decide from evidence whether Hybryda is an
experimental selectable engine or a default for a defined range of workloads.

**Acceptance tests**

- Reproducible benchmark matrix and count agreement for every reported run.
- No performance claim without full wall-clock measurement including bootstrap,
  MAIN, filter and writing.

**Commit:** `perf(hybrid): record tuned defaults and benchmark evidence`

**Evidence / commit:** whole-pipeline native benchmark script is implemented;
awaiting reproducible WSL measurements before defaults or performance claims.
