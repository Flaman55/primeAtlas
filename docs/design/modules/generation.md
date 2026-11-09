# Module: generation (Generation tab)

Launches and follows every engine run: the generation pipeline (Section A and the Quick-gen panel,
with orchestrator, primesieve, cudasieve and Hybrid modes), the constellation search (Section B) and
the targeted k-tuple sieve (Section C). Only one engine runs at a time.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/generation/generation_tab.py` (`GenerationTab`, WSL runner factory) |
| Sections (mixins) | `quick_gen_panel.py`, `quick_gen_runs.py`, `loop_section.py`, `constellation_section.py`, `ktuple_section.py`, `run_progress.py`, `run_guard_controls.py`, `hybrid_controls.py`, `engine_fields.py`, `time_simulation_controls.py` |
| Launching | `engine_argv.py` (argv of every script), `wsl_command.py` (wsl.exe command, logs), `logged_runners.py` (`WslLoggedRunner`, `LocalLoggedRunner`), `wsl_blocking.py`, `wsl_resources.py` |
| Planning | `window_planning.py`, `quick_gen_plan.py`, `run_budget.py`, `engine_options.py`, `engine_presets.py`, `quick_number.py` |
| Time simulation | `time_model.py` (run time model calibrated from benchmark_log.csv), `run_ram.py` (predicted RAM of a run, widest run in the RAM budget), `time_simulation_window.py` (`TimeSimulationWindow`) |
| Following and settling | `run_output.py` (log parsing), `run_guard.py` (stop request, active-run marker, recovery), `close_guard.py` |
| Settings | `generation_settings.py` (form defaults and persistence), `generation_console.py` (`GenerationConsole`) |
| Offers | `generation_offer_coordinator.py` ("generate the missing fragment" for other tabs) |

## Contract

| In | Out |
|---|---|
| form values, offers from other tabs | WSL runs ([generation-run](../flows/generation-run.md), [constellation-search](../flows/constellation-search.md), [ktuple-sieve](../flows/ktuple-sieve.md)); consoles, progress bar, totals bumps, tree reloads |

Never imports engine code: names and defaults the engines also use are mirrored and kept equal by
tests (`test_engine_options`). Log lines are parsed by their stable prefixes (`[CONSTELLATIONS v2]`,
`[KTUPLE SIEVE v2]`, `[+] Progress:`). The shared bar fills a run's sieve steps to the progress
line's own percent, not to its job count: v7.1 weights the percent by estimated cost, the other
engines print done / total.

## Knob profiles

`engine_presets.py` names the measured sets of v5's and v6's four sieve knobs (segment,
bucket region, bucket memory, pieces per thread): Old (128 KiB / 1 GiB buckets), New (2 MiB /
8 GiB, long runs), Intermediate (2 MiB / 1 GiB, short runs), Auto and Custom. Each engine
keeps its own profile (`v5_preset`, `v6_preset`, `v7_preset`, default Auto). `engine_options.resolve()`
applies the selected engine's profile with the run's window count: Auto steps the segment and
bucket memory up with the width, per engine (`AUTO_STEPS`; v5: 2 MiB / 1 GiB below 1,500
windows, 2 MiB / 4 GiB below 4,000; v6 and v7: 128 KiB / 1 GiB below 3,000, 2 MiB / 4 GiB below
8,000; then New), New's values when the width is not known yet (the Auto RAM button). The form fills the profile fields when a profile is picked and,
under Auto, whenever the run width is edited (`EngineFields.set_windows()`, fed by Windows /
iteration and the Quick-gen Floor and Exploration Width, the last edited one wins), so the
fields show what the next run gets; it switches
to Custom when one of them is typed in; a RAM-reduced bucket memory only lowers the profile's
value. Windows-at-25 and the RAM budget size the run, so no profile sets them.

## Floor fields

When a run ends, the Primes tree, an open Time simulation window and the Benchmark tab reread the
storage (`reload_benchmark_log`, injected by the app), so the run's row is on the charts at once.

primesieve mode has a Native checkbox (`quick.primesieve_native`, remembered). Off, it runs the
wrapper `prime_sieve_primesieve.py` (Atlas windows into storage; the info tip names the conversion
overhead in its time). On, a print/count list becomes usable and Generate runs
`primesieve_native.py` with that mode; while native primesieve mode is selected the Benchmark
checkbox is disabled and shows checked: a native run measures the program in its own format,
so count and print are both benchmark runs (`benchmark_log_schema.NATIVE_ENGINES`).

Pseudosquares mode (`quick_gen_pseudosquares.py`) is always native: Floor / From / Width,
count or print, and Threads (Auto or a number, usable for count only; print runs on one
thread). `pseudosquares_plan.py` turns the fields into one run without reading the storage:
From (blank = the Floor's start) picks its floor and the window holding it, the range is cut
at the floor's end and at 10^33, and a bad Threads value, a From past 10^33 or no From and no
Floor stop before launch. It launches `pseudosquares_native.py` on the shared runner and
console. One function, `_sync_benchmark_lock`, handles both native modes: the checkbox is disabled and
bound to a fixed Variable that shows it checked, so the shared `write_files` setting of the
Atlas modes is not changed and shows again when an Atlas mode is selected. A missing program is reported by the runner in the console (exit code 2, no row); the
Generation tab does not hold the Settings status.

## Benchmark runs

"Benchmark (no storage writes)" sits next to Generate in every Quick-gen panel copy and applies
to every mode: it is the shared `write_files` setting shown inverted (checked = `write_files`
off, remembered as `generation.loop.write_files`), passed to every engine's argv. A benchmark
run sieves and counts and leaves the storage as it was: no windows, no floor folder, no
`floor_meta.json` row (`floor_meta_store` refuses rows whose `row_purpose()` is benchmark); its
only trace is its `benchmark_log.csv` row with `run_purpose = benchmark`. Every script in
`prime_sieve/` that writes log rows sets `run_purpose` (`run_purpose()` of
`benchmark_log_schema.py`), which `test_floor_meta_store` checks for every such script, so an
engine added later logs it too. The engines' own `last_scan_metrics.json` hand-off is still
written: the frozen scanners write it.

Every Quick-gen Floor field (Floor only, Explore, Hybrid, primesieve, CUDASieve) is a spinbox: its
arrows and the mouse wheel step the floor through 0 to `QUICK_FLOOR_MAX` (35; primesieve and
CUDASieve stop at `UINT64_FLOOR_MAX`, 19), and a typed value or expression is not capped.

## Remembered fields

Every Quick-gen input and every field of the pipeline, constellation and k-tuple forms is remembered
per install (`core/ui_state.py`, keys `quick.*` and `generation.<section>.<field>`): restored at
start, saved on each change, no Run click needed. The forms read their values through
`load_generation_settings()`, which first copies the storage folder's legacy
`.portal_generation_settings.json` once per install; Run still saves the parsed values (the k,
variant and strategy combos in their canonical form). Never remembered: Quick-gen's starting point
(a run consumes it; the Floor it filled is restored as an ordinary value) and the k-tuple reset
checkpoint box (unchecked at every start).

## Time simulation

The Quick-gen "Time simulation" button opens one window with two sliders: the floor (7-35) and
the run width in windows of 10^7 (log scale up to its cap, see RAM below), plus the engine
selector. They are the Quick-gen Floor and Width fields (Explore: its own pair) and the pipeline
form's engine var themselves, so a slider fills the form and a form edit moves the slider; what
Generate runs is what the window shows. The window width `window_m` is not a slider: it is the
storage unit (changing it on a floor with data breaks resume), and speed depends on the run span.

`time_model.py` models one run of span S ending at `top` at floor f as
`prep = k(f) * pi(L)`, `sieve = m(f) * S`, `write = w(f) * S`, with L = isqrt(top) (v4.1, v5, v6) or the
pt1 bound B. prep is the per-run fixed cost F (every sieving prime up to L, about 3x more per floor).
The storage folder's `benchmark_log.csv` is read when the window opens and again when a run
started from the Generation tab ends (`_on_loop_finished()` calls `reload_log()`), so a run
finishing while the window is open recalibrates it; a run started outside the app shows on the
next opening. The log is never written. Its completed rows give, per measured floor:

- two or more widths on the floor: F and m by least squares of the sieve time against the span;
- one width: m from a baseline fit over all the engine's rows (relative-error least squares over
  subsets of run, prime * pi(L), number * S, number * S * ln ln L), F as the rest of the time;
- w: the wall time the floor's file-writing runs took beyond prep and sieving (writing may overlap
  sieving, so the engines' write busy time is not added).

A run's measured time is `total_seconds` without `base_gen_seconds` (the optional pi(L) count).
Rows calibrate per engine version (`time_model.calibration_rows()`): the version of the engine's
last row in the log (`engine_version`, the writing script's `VERSION`, e.g. v5.1) calibrates from
its own rows once it has two, so a faster release is not averaged with the old one; until then, and
for rows logged before the column, every row of the engine does. The window names the version.
Other floors interpolate k, m and w log-linearly and hold the nearest measured floor's values
outside them. The window shows pi(L) (exact at powers of ten, else R(x)), prep, sieving, added
write time, run and per-window time, gross speed (span / run time) and net sieving speed (span /
sieving time) with the unit scaled to the value, the floor's measured runs next to the model's
time for the same runs, and the whole floor's time (9 * 10^f numbers, start to end), plus the rows,
floors and worst error of the fit; outside the measured floors and spans it says the times are
extrapolated, and with fewer than two rows of the engine it shows only pi(L).

RAM: `run_ram.py` predicts the run's peak memory as `run_budget.run_footprint_bytes()` with the
knobs the run launches with (`EngineFields.choice_for_windows()`: an Auto profile picks the bucket
memory by width), unlike the Auto button's `engine_options.recommend()`, which may lower the bucket
memory to fit. The window shows it in GB and as a share of the RAM free in WSL (`MemAvailable`, read
on a background thread when the window opens and when a run ends). The width slider ends at the
widest run that fits the pipeline form's RAM budget (`ram_budget_pct` of the free RAM; binary search,
since the footprint grows with the width), or at the engine's cap when that is smaller, for pt1 (no
run-sized buffer) and while the free RAM is unknown. The window traces the budget, bucket-memory and
profile fields, so an edit there moves the cap at once. A width typed into the Width field above the
budget is kept (the form runs what it holds) and the RAM line flags it; its info tip names the budget
field, the recommended value (the 50 % default) and what a higher budget risks (swapping, the run
killed out of memory, an unresponsive system).

## Parameters and texts

[generation-loop](../parameters/generation-loop.md), [generation-constellation](../parameters/generation-constellation.md),
[generation-ktuple](../parameters/generation-ktuple.md); texts `gen.*`, `quick.*`, `close.*`, `timesim.*`.

## Kept data

Form values in `ui_state.json` (per install; a storage folder's legacy `.portal_generation_settings.json`
is copied in once), `.generation_logs/` (logs, exit codes, `ACTIVE_RUN.json`),
`GENERATION_STOP_REQUEST.txt`, `STOP_REQUEST.txt` ([data.md](../data.md)).

## Specs and tests

`test_generation_launch_planning`, `test_generation_window_arithmetic`, `test_engine_options`,
`test_engine_presets`, `test_engine_gui_wiring`, `test_run_budget`, `test_run_guard`, `test_close_guard`, `test_close_guard_wiring`,
`test_cross_engine_run_lock`, `test_gen_progress_bar_engine_gating`, `test_progress_bar_owner`,
`test_console_controls`, `test_constellation_auto_retry`, `test_storage_fill`, `test_pi_seed_checkbox_exclusivity`,
`test_time_model`, `test_run_ram`, `test_time_simulation`, `test_ui_state_app`.

## Known gaps

- primesieve mode's planning still checks the requested range against the storage ("already
  in storage") also for Native runs, which write nothing there; Pseudosquares mode does not.
- The RAM budget caps only the Time simulation slider: Generate does not refuse a typed width
  above it.
- The run-progress ETA does not use the time model yet; the model is shown only in the Time
  simulation window.
- The time model is linear in the span per floor: a run much shorter than the floor's measured ones
  (process start-up dominates) or one whose buffer outgrows the caches deviates; the worst error
  is shown in the window. Several parallel instances (`n_instances`) are not modelled.
- Rows logged before the `engine_version` column carry no version: v5 rows from before v5.1
  still calibrate v5 until two v5.1 rows exist. Recent rows are not weighted above older rows
  of the same version.
