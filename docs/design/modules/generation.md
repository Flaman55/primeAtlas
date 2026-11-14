# Module: generation (Generation tab)

Launches and follows every engine run: the generation pipeline (Section A and the Quick-gen panel,
with orchestrator, primesieve, cudasieve and Hybrid modes), the constellation search (Section B) and
the targeted k-tuple sieve (Section C) and the verification P -> D of pt1's stored windows
(Section D, `pt1_verify_store.py` or `v73_verify_store.py`, chosen by its Method field with a rough time of both from `verify_estimate.py`, see [prime-sieve](prime-sieve.md)). Only one engine runs at
a time.

Section D takes a floor and a window width as power-of-ten spinboxes; its Windows field is
recounted from the floor's P store (`storage_kinds.p_windows_on_grid()`, the list the script
proves) whenever the floor or the width changes and after a run, so it starts at "all" and a
smaller value proves only the first windows. Threads: Auto = the pipeline form's workers (what
pt1 sieves with), Max = WSL's CPU count (probed at Run), or a number.

Section D's Method and Pass also serve the pipeline form's pt1 checkbox "Verify P -> D after the
run": one choice, two places. The checkbox's hint (`EngineFields.knob_hint_vars`) names the
method and, for the sieve, the pass, updated on every change in Section D; a ticked pt1 run
(pipeline or Quick-gen) carries them in its env (`engine_options.launch_env(verify=...)`,
`VerifySection._pt1_verify_choice()`), and the orchestrator verifies the run's windows after
the run. A Benchmark run writes no windows to verify: while Benchmark is ticked the checkbox
is greyed out, its value kept, and hovering it says why (`EngineFields.set_knob_lock()`, an
InfoTip anchored on the checkbox).

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/generation/generation_tab.py` (`GenerationTab`, WSL runner factory) |
| Sections (mixins) | `quick_gen_panel.py`, `quick_gen_runs.py`, `loop_section.py`, `constellation_section.py`, `ktuple_section.py`, `verify_section.py`, `run_progress.py`, `run_guard_controls.py`, `hybrid_controls.py`, `engine_fields.py`, `time_simulation_controls.py`, `engine_advice_controls.py`, `pi_count_notice_controls.py` |
| Launching | `engine_argv.py` (argv of every script), `wsl_command.py` (wsl.exe command, logs), `logged_runners.py` (`WslLoggedRunner`, `LocalLoggedRunner`), `wsl_blocking.py`, `wsl_resources.py` |
| Planning | `window_planning.py`, `quick_gen_plan.py`, `run_budget.py`, `engine_options.py`, `engine_presets.py`, `quick_number.py`, `verify_plan.py`, `verify_estimate.py`, `pi_count_notice.py` (whether a run counts pi(L) from zero) |
| Time simulation | `time_model.py` (run time model calibrated from benchmark_log.csv), `run_ram.py` (predicted RAM of a run, widest run in the RAM budget), `time_simulation_window.py` (`TimeSimulationWindow`) |
| Engine proposal | `engine_advisor.py` (options, choice, guest line), `engine_advisor_seeds.py` (seed rows), `engine_advice_text.py` (its texts), `engine_advice_view.py` (`EngineAdviceView`); `tools/engine_advice.py` prints it |
| Following and settling | `run_output.py` (log parsing), `run_eta.py` (a running run's remaining time from the time model), `run_guard.py` (stop request, active-run marker, recovery), `close_guard.py` |
| Settings | `generation_settings.py` (form defaults and persistence), `generation_console.py` (`GenerationConsole`) |
| Offers | `generation_offer_coordinator.py` ("generate the missing fragment" for other tabs) |

## Contract

| In | Out |
|---|---|
| form values, offers from other tabs | WSL runs ([generation-run](../flows/generation-run.md), [constellation-search](../flows/constellation-search.md), [ktuple-sieve](../flows/ktuple-sieve.md)); consoles, progress bar, totals bumps, tree reloads |

Never imports engine code: names and defaults the engines also use are mirrored and kept equal by
tests (`test_engine_options`). Log lines are parsed by their stable prefixes (`[CONSTELLATIONS v2]`,
`[KTUPLE SIEVE v2]`, `[+] Progress:`). The shared bar fills a run's sieve steps to the progress
line's own percent, not to its job count: v7 weights the percent by estimated cost, the other
engines print done / total.

While a pipeline run or a Quick-gen run launched directly (`orchestrator_v3.py`) is running, the
status text ends with its running time and ETA (`| running: 1m05s, ETA: 4m10s`). At launch the
tab models the run with `time_model.estimate()` from the engine's calibration (the same as the
engine proposal's, seed rows included): one run from the run's start for Quick-gen, one run of
the form's windows per iteration for the pipeline, the first where the orchestrator continues the
floor and each next one `n_instances` x windows further. `run_eta.RunEta` advances the model by
the progress lines (a progress line counts its iteration's prep plus the line's percent of its
sieve and write; an iteration's done line counts it whole). Until the reported work reaches 10 % of the model
(`TRUST_SHARE`, arbitrary) the ETA is the model counting down by the clock (or by the progress
when the run is ahead of it); from then on the modelled rest is scaled by the run's measured
pace against the model. The clock refreshes the text about once a second from the output poll,
but only while the status still shows what the run last wrote, so a search or totals message is
not overwritten. Without a calibration (or on floors 0-6) only the running time shows; Hybrid,
primesieve, CUDASieve and Pseudosquares runs show neither, and the constellation search keeps
its own measured ETA.

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
so count and print are both benchmark runs (`benchmark_log_schema.NATIVE_ENGINES`). A native run
writes nothing into the storage, so it is planned like Pseudosquares' (`native_plan.py` with
primesieve's stop, 2^64 - 1) and never compared with the stored windows: a blank From starts at
the Floor's start and stays blank.

Pseudosquares mode (`quick_gen_pseudosquares.py`) is always native: Floor / From / Width,
count or print, and Threads (Auto or a number, usable for count only; print runs on one
thread). `native_plan.py` turns the fields into one run without reading the storage:
From (blank = the Floor's start) picks its floor and the window holding it, the range is cut
at the floor's end and at the program's stop (`MAX_STOP` = int(1.73 * 1e33), in floor 33), and a
bad Threads value, a From past that stop or no From and no
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

## pi(L) notice

Counting pi(L) (the two pi checkboxes of the pipeline form, off by default and remembered) adds
`base_gen_seconds` to a run's total. The engines keep the largest L counted per floor in
`10p{N}/sieving_primes_count_cache.json`, so only a floor's first count is long: a floor without
that file, or a run whose first batch lies below its L (`l_final` = isqrt(top) + 1; the file holds
no prefix for a smaller L), counts from zero. Before such a run `_on_run_loop` /
`_on_run_orchestrator_direct` show the notice (`pi_count_notice_controls.py`, decided by
`pi_count_notice.counts_from_zero`) with the time of that count: li-based primes from 0 (or from the
largest known pi(10^n) with the seed) at `SECONDS_PER_PRIME`, and [Enable] / [Leave disabled].
[Leave disabled] and closing the window untick both boxes. With counting off, or on a floor that
has its cache, nothing shows.

## Pipeline form

Section A's Advanced settings are four framed groups stacked top to bottom: Range (floor, window
width, windows per iteration, iterations), Parallelism (parallel instances, workers per instance
with its Auto button, batches per worker), Counting pi(L_final) (the two checkboxes, their text
wrapped at the form's width) and Sieve engine (`EngineFields`: engine, profile, knobs, then the
BPSW offset). Each group has its own grid of at most two label/field pairs per row, so the form
fits a Full HD screen at 150 % scaling (a 1280 px wide window for the DPI-unaware Tk). A fresh
install starts with one parallel instance, one batch per worker and engine v7.

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

Generate checks the same prediction before a pipeline run and a Quick-gen run launched directly
(`orchestrator_v3.py`): when the run's RAM times its parallel instances (`n_instances`) is over the
budget (`run_ram.over_budget()`), it asks whether to run anyway, naming the predicted GB, the
budget, the free RAM and the budget field; No launches nothing. pt1 and pt1-pss (no run-sized
buffer) and a run without a RAM reading are not asked. The free RAM is read on a background
thread when the Generation tab is built, when the Time simulation window opens and when a run
ends; the engine proposal and this check use the last reading.

## Engine proposal

Atlas proposes the engine of the run the Quick-gen Floor and Width fields describe (Floor and Explore
modes, a line under the panel) and of the Time simulation window's sliders (the same text). The
Quick-gen line times the run from where Generate starts it: Floor mode's typed starting point, else
one past the floor's last window in the selected engine's store (the first gap with "fill gaps
first"); the run's end sets its sieving-prime bound, the Miller-Rabin bound and pt1-pss's proof
bound. The Time simulation window times runs from the floor's start. Every own
engine (`engine_options.ENGINES`) is an option with its `time_model` run time when it fits the floor
(pt1 7..37; pt1-pss while the proof's B stays below 2^32, so up to floor 34), the width (its per-run
cap) and the RAM budget (`run_ram.fits_budget()` with the free WSL RAM read last; unknown: no
limit). An engine with fewer than two logged rows is timed from its seed rows
(`engine_advisor_seeds.py`: v7.2's measured prep on floors 28 and 30, pt1 and pt1-pss speeds on
floors 25-32) and the proposal says it is an estimate; an engine with neither is left out. pt1 is
probabilistic when the run reaches past 3.3e24 (BPSW), every other option is deterministic.

The proposal is the fastest deterministic option, unless pt1 with BPSW is faster by at least the
BPSW offset (`advisor_bpsw_offset`, a float >= 1, default 3, arbitrary; the pipeline form's advanced
field, persisted with the form; `--offset` in `tools/engine_advice.py`) or no deterministic option
fits. With pt1 proposed, the BPSW warning shows: no known counterexample, verified below 2^64, fine for
informal use, not proven, so formal research takes v7, pt1-pss or a later P -> D verification. Use
selects the proposed engine; nothing switches it otherwise.

Guest tools (`engine_advisor.GUEST_ENGINES`: the Pseudosquares program in count mode) are never an
option. One that the log calibrates (two runs measured on this machine), fits its floor range and is
faster than the fastest deterministic option shows a line with its speed-up (both timed without
writing) and the note that it writes no windows into the storage, while its prime count stays in
the Benchmark tab: equal to a pt1 run's count over exactly the same range, it proves that run's P
windows (the sieve to B <= sqrt(lo) and BPSW never reject a prime, so the P windows hold every prime
of the range and an equal count leaves no composite). Without guests every proposal is
the same ([ADR 0009](../../adr/0009-own-engines-guests-optional.md)).

## Parameters and texts

[generation-loop](../parameters/generation-loop.md), [generation-constellation](../parameters/generation-constellation.md),
[generation-ktuple](../parameters/generation-ktuple.md),
[generation-verify](../parameters/generation-verify.md); texts `gen.*`, `quick.*`, `close.*`, `timesim.*`, `advisor.*`.

## Kept data

Form values in `ui_state.json` (per install; a storage folder's legacy `.portal_generation_settings.json`
is copied in once), `.generation_logs/` (logs, exit codes, `ACTIVE_RUN.json`),
`GENERATION_STOP_REQUEST.txt`, `STOP_REQUEST.txt` ([data.md](../data.md)).

## Specs and tests

`test_generation_launch_planning`, `test_generation_window_arithmetic`, `test_engine_options`,
`test_engine_presets`, `test_engine_gui_wiring`, `test_run_budget`, `test_run_guard`, `test_close_guard`, `test_close_guard_wiring`,
`test_cross_engine_run_lock`, `test_verify_plan`, `test_gen_progress_bar_engine_gating`, `test_progress_bar_owner`,
`test_console_controls`, `test_constellation_auto_retry`, `test_storage_fill`, `test_pi_seed_checkbox_exclusivity`,
`test_time_model`, `test_run_ram`, `test_time_simulation`, `test_ui_state_app`, `test_pi_count_notice`,
`test_pi_count_notice_controls`, `test_engine_advisor`, `test_engine_advice_gui`, `test_native_plan`,
`test_primesieve_native_controls`, `test_generation_ram_guard`, `test_run_eta`, `test_pipeline_form_layout`.

## Known gaps

- The Time simulation window times every run from the floor's start (10^floor); only the
  Quick-gen proposal line follows the run's real start.
- Exploration mode's proposal is for the floor in its Floor field; a run that moves on to the
  next floor is proposed for the first one.
- The run ETA models a pipeline iteration's parallel instances as one run; the measured pace
  corrects it once 10 % of the model is reported. The pipeline's start is the selected engine's
  store continuation, which the orchestrator also uses.
- The time model is linear in the span per floor: a run much shorter than the floor's measured ones
  (process start-up dominates) or one whose buffer outgrows the caches deviates; the worst error
  is shown in the window. Several parallel instances (`n_instances`) are not modelled.
- A restore job's regeneration counts pi(L) with the remembered setting without the notice.
- Rows logged before the `engine_version` column carry no version: v5 rows from before v5.1
  still calibrate v5 until two v5.1 rows exist. Recent rows are not weighted above older rows
  of the same version.
