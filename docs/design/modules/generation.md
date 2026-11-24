# Module: generation (Generation tab)

Launches and follows every engine run: the generation pipeline (Section A and the Quick-gen panel,
with orchestrator, primesieve, cudasieve and Hybrid modes), the constellation search (Section B) and
the targeted k-tuple sieve (Section C) and the verification P -> D of pt1's stored windows
(Section D, `pt1_verify_store.py` or `v73_verify_store.py`, chosen by its Method field with a rough time of both from `verify_estimate.py`, see [prime-sieve](prime-sieve.md)). Only one engine runs at
a time.

Section D verifies the floor's first island of P files (`verify_width.py`): the run of P files
from the smallest n, each one file width after the previous; a gap, a D file or a file of
another width ends it, and the next island comes once this one is D. A P file's name holds no
width, so the file width is the smallest gap between the floor's P offsets (10^7 for a single
file). That gap can belong to narrower files further on, so the island's first file is read
(once per path and mtime): a last prime past the guessed width makes it a wider file, of the
smallest multiple of the guess past that prime that divides its offset, verified as an island
of its own; the island's files are the first ones the script takes from the grid
(`storage_kinds.p_windows_on_grid()`). The Width field sets the numbers of one verification
window in whole files, from one file up to the island, for the v7.3 sieve also up to half the
free RAM x 30 (`run_budget.DEFAULT_SAFETY_FRACTION`; the RAM is read by Auto and a v7.3 Run,
10^11 before the first reading); a width outside its range takes the nearest end, one between
rounds down to whole files, on leaving the field, a floor or method change and Run, and it is
shown short and exact (`verify_width.width_text()`: 1e8, 9e7, 2.5e8; never three digits after
the point, which also read as a thousands group: 83.34e9); the arrows and the wheel step to the next
round width (`verify_width.step_width()`: one significant digit, 1e8 -> 2e8, 1e9 -> 9e8 down;
2.5e8 -> 3e8 or 2e8), at least one file and within the range, so a small island steps file by
file. The island text gives the window range (one file up to the island or the v7.3 cap). Auto: one file for the pt1.1 proof (the most windows), the fewest windows
under the cap split evenly for the v7.3 sieve; a blank stored width takes Auto's. The Split
field holds ceil(island / width), the island's numbers and files beside it; a typed split sets
the width to ceil(files / split) files (evenly), its arrows step to the next split that
changes the width. "Verify now" holds every window, recounted on every change, after any
engine's run (it may have written or proved P files) and whenever the main tab holding
Generation is shown (P files removed in the primes tree, another store folder); a smaller
value proves only the first windows. The script gets
the file width as window_m, the files of the chosen windows as max_windows and, for the
sieve, the width as its pass. Without a P file there is nothing to pick: Windows empty and
greyed out, "no P windows on this floor" beside it, Width, Auto and Run greyed out. Run is
also greyed out while any engine runs (`_lock_other_run_buttons()` holds the Run buttons);
P files gone between the recount and a click launch nothing and grey Run out. A pt1 run that
wrote files (`loop_run_info` engine "pt1", write_files on; stopped too) moves the section to
its floor and runs Auto, whatever floor and width it showed. Threads: Auto = the pipeline form's workers (what
pt1 sieves with; its Max probed as below), Max = WSL's CPU count (probed at Run), or a number.

Section D's Method and v7.3 RAM cap also serve the pipeline form's pt1 checkbox "Verify P -> D
after the run": one choice, two places. The checkbox's hint (`EngineFields.knob_hint_vars`)
names the method and, for the sieve, the passes up to the cap, updated on every change in
Section D; a ticked pt1 run
(pipeline or Quick-gen) carries them in its env (`engine_options.launch_env(verify=...)`,
`VerifySection._pt1_verify_choice()`), and the orchestrator verifies the run's windows after
the run. A Benchmark run writes no windows to verify: while Benchmark is ticked the checkbox
is greyed out, its value kept, and hovering it says why (`EngineFields.set_knob_lock()`, an
InfoTip anchored on the checkbox).

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/generation/generation_tab.py` (`GenerationTab`, WSL runner factory) |
| Sections (mixins) | `quick_gen_panel.py`, `quick_gen_runs.py`, `loop_section.py`, `constellation_section.py`, `ktuple_section.py`, `verify_section.py`, `run_progress.py`, `run_guard_controls.py`, `hybrid_controls.py`, `engine_fields.py`, `time_simulation_controls.py`, `engine_advice_controls.py`, `pi_count_notice_controls.py`, `target_planner_section.py` |
| Launching | `engine_argv.py` (argv of every script), `wsl_command.py` (wsl.exe command, logs; every launch names the machine id, the CPU load over the 5 s before it and the run's `.load` file for `prime_sieve/run_load.py`), `logged_runners.py` (`WslLoggedRunner`, `LocalLoggedRunner`; the WSL runner keeps the run's `.load` file of Windows CPU counters, written before the process starts and once a second), `wsl_blocking.py`, `wsl_resources.py` |
| Planning | `window_planning.py`, `quick_gen_plan.py`, `run_budget.py`, `engine_options.py`, `engine_presets.py`, `quick_number.py`, `verify_plan.py`, `verify_width.py`, `verify_estimate.py`, `pi_count_notice.py` (whether a run counts pi(L) from zero) |
| Time simulation | `time_model.py` (run time model calibrated from benchmark_log.csv), `run_ram.py` (predicted RAM of a run, widest run in the RAM budget), `time_simulation_window.py` (`TimeSimulationWindow`) |
| Engine proposal | `engine_advisor.py` (options, choice, guest line), `engine_advisor_seeds.py` (seed rows), `engine_advice_text.py` (its texts), `engine_advice_view.py` (`EngineAdviceView`); `tools/engine_advice.py` prints it |
| Width proposal | `width_advisor.py` (rules), `width_advice_text.py` (its texts), `width_advice_view.py` (`WidthAdviceView`) |
| Target planner | `target_planner.py` (parsing, windows, lanes, choice), `target_plan_costs.py` (costs from the time model), `target_plan_text.py` (its texts), `target_planner_view.py` (`TargetPlannerView`), `target_planner_example.py` + `target_planner_example.txt` (the example list) |
| Following and settling | `run_output.py` (log parsing), `run_eta.py` (a running run's remaining time from the time model), `run_guard.py` (stop request, active-run marker, recovery), `close_guard.py` |
| Settings | `generation_settings.py` (form defaults and persistence), `generation_console.py` (`GenerationConsole`) |
| Offers | `generation_offer_coordinator.py` ("generate the missing fragment" for other tabs) |

The Quick-gen mode radios are a `FlowRow` of `ElidedRadiobutton`s (`core/`): they wrap whole
onto further lines on a narrow window, and a name wider than the whole row is shortened with
"…" and an "i" marker holding the full name; the embedded and the detached panel share the mode.
Each mode's fields and the k-tuple form (primary and Advanced) are `FlowRow`s of
groups (`core/widgets.flow_group`): a label with its field and its Auto button moves whole to the
next line in a narrow window; the mode frames are stretched to the panel's width so their rows can
wrap. Descriptions and hints are `WrapLabel`s (`core/wrap_label.py`).

## Contract

| In | Out |
|---|---|
| form values, offers from other tabs | WSL runs ([generation-run](../flows/generation-run.md), [close-guard](../flows/close-guard.md), [constellation-search](../flows/constellation-search.md), [ktuple-sieve](../flows/ktuple-sieve.md)); consoles, progress bar, totals bumps, tree reloads |

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
count or print, and Threads (Auto, Max or a number, usable for count only; print runs on one
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

A literal range (Range mode, Floor mode with a starting point, primesieve and CUDASieve From, the
search and Goldbach "generate the missing range" offers) is planned by
`_quick_gen_plan_literal_range()` from its own windows only, in the store the selected engine
writes into (`window_planning.stored_target_idxs()`): windows elsewhere on the floor say nothing
about its gaps. A range with every window stored reports "already in storage" with the range's
count; otherwise one run goes from its first missing window to its last, rewriting stored windows
between two gaps. Without a starting point, Floor and Explore continue past the floor's last
window, or with "Fill gaps first" start at its first gap, so repeated clicks fill every gap in
order before continuing. A floor stored up to its last window but with gaps says so and points to
that option. Every window count a Quick-gen message shows is the selected engine's store
(`count_existing_windows(engine=...)`): pt1's P store from floor 24 on, D for the sieves.

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
width, windows per iteration, iterations), Parallelism (parallel instances, workers per instance,
batches per worker), Counting pi(L_final) (the two checkboxes, their text
wrapped at the form's width) and Sieve engine (`EngineFields`: engine, profile, knobs, then the
BPSW offset). Each group has its own grid of at most two label/field pairs per row, so the form
fits a Full HD screen at 150 % scaling (a 1280 px wide window for the DPI-unaware Tk). A fresh
install starts with one parallel instance, one batch per worker and engine v7. Workers takes a
number or Max (the default): every CPU WSL reports (`nproc`), probed at each launch
(`wsl_resources.resolve_workers()`, capped at 256) and remembered as Max, so the form follows the
machine it runs on. A pipeline run whose probe fails stops with a message; a Quick-gen run and a
Restore fall back to one worker.

Every thread count is a `core.threads_field.ThreadsField`: workers (Max or a number), Section D's
Threads (Auto, Max or a number), Pseudosquares' Threads (Auto, the program's own pick, shown bare;
Max; or a number) and the v5/v6/v7 write threads (a number). The list holds the words and 1..the
CPU count WSL reports (`core.cpu_dynamic.WSL_CPUS`), Max is shown with that count, "Max (8)", and
Auto of Section D with the workers it stands for. A larger number, typed or stored, becomes Max
(write threads: the count itself). The app reads the count once at startup in the background;
each launch's probe (`wsl_resources.read_wsl_cpus()`) and the About tab's read refresh it.

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
Only this computer's rows calibrate: `time_model.read_samples()` leaves out a row whose
`machine_id` names another computer and keeps rows without one (logged before the column or
started outside the GUI); without an id of its own (`windows_hardware.this_machine_id()` None)
every row counts. Every reader of the log (time simulation, engine and width proposals, target
planner, `tools/engine_advice.py`) goes through it.
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
memory to fit. The window shows it in GB and as a share of the free RAM
(`wsl_resources.estimate_free_ram_bytes()`: the lower of WSL's `MemAvailable` and the RAM free
in Windows, read on a background thread when the window opens and when a run ends). WSL2 takes
host RAM only as it touches it, so a WSL limit above what Windows has left must not size a run;
pages WSL already holds in its file cache count in `MemAvailable` but not in Windows' free RAM,
so the reading errs low. An unreadable Windows value leaves the WSL value; an unreadable WSL
value gives no reading. The Quick-gen Auto buttons and Settings → Restore size runs from the
same reading. The width slider ends at the
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
cap) and the RAM budget (`run_ram.fits_budget()` with the free RAM read last; unknown: no
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

In Explore with more than one iteration the engine line marks its time as one iteration's.

## Width proposal

A run's prep cost (every sieving prime up to the square root of its end) does not depend on its
width, so a wider run spreads it over more numbers. A second line under the engine proposal,
with its own Use button, proposes a width for the selected engine (`width_advisor.py`):

| Quick-gen state | Proposal |
|---|---|
| Benchmark ticked, Floor or Explore | `BENCHMARK_WINDOWS` = 10,000 windows (10^11 numbers, arbitrary), lowered to the cap; the modelled speed now and then, and the note that one run's prep time stays the same; iterations unchanged |
| Explore writing into the storage, iterations > 1 | `plan_split()` under the cap, by priority: exactly the same total range (`split_total()`: the smallest divisor of the total at least ceil(total / cap)), else the fewest runs ceil(total / cap) with the width rounded up and the extra windows named, else none; the modelled total time now and then; none when the iteration count stays or the model times it no faster |
| Floor writing into the storage, one Explore iteration, other modes | none |

The cap is the engine's widest run (`engine_options.widest_run()`: the per-run ceiling, for v7
lowered to its `v7_auto_max_windows` knob, default 10,000 windows = 10^11 numbers, picked from
benchmark runs where wider v7 runs stop gaining noticeable speed) lowered to the widest run in
the RAM budget (`run_ram.max_windows_in_budget()`; pt1 or no RAM reading: the
ceiling). A typed width at or above the target gives no proposal (never narrower). Without a
calibration of the engine the line leaves out the speeds and times. Use writes the width, in
Explore also the iteration count; nothing changes the fields otherwise.

The Quick-gen Auto buttons size a run with `engine_options.recommend()`, capped at the same
widest run. Floor only and Explore with one iteration fill the width with it. Explore with more
iterations re-splits iterations x width with `plan_split()` under that width and the iteration
field's ceiling (100), by priority: the exact total when it lowers the iterations (or brings a
too-wide width under the widest run); else the fewest runs at the widest window, a few windows
more (fewer than the new iteration count); else the fields as typed. The dialog says which.
Range only reports the width. A width typed by hand may still
go up to the per-run ceiling.

## Target planner

A collapsible section above the pipeline section. The person lists targets, one per line:
`center [radius] [engine]` (whitespace, `;` or `,` between them, Quick-gen expressions);
blank lines and `#` comments are skipped. The engine, when given, is the last field: an Atlas
engine as the form names it (`v4.1`, `v5`, `v6`, `v7`, `pt1` or `pt1.1`, `pt1-pss`) or `pss` /
`pseudosquares`, any case. Any bad line blocks the plan and is listed with its number (not a
number, more than two numbers, an unknown engine, two engines, an engine before a number,
center below 1, negative radius, below 10^7, above 10^36 - 1, more than `MAX_TARGETS` = 10,000
targets, arbitrary).

Each target [center - radius, center + radius] becomes the windows it touches on the 10^7 grid
of its floor, split at a floor boundary. Repeated and overlapping targets share windows; the
windows the selected engine's store already holds (`storage_kinds.engine_target_idxs()`) are
dropped, and a target with none left counts as already stored. The remaining windows of a floor
form blocks (maximal runs of consecutive windows, cut at the cap).

| Choice | Cost |
|---|---|
| One Atlas run over a group of consecutive blocks (gaps included) | `time_model.estimate()` of the selected engine, writing, from the group's first window; only while the span is at most the cap |
| One Pseudosquares print run per block | its print calibration, else its count calibration (noted) |

Dynamic programming over each floor's blocks picks the partition with the fewest total
seconds; a tie goes to Atlas (its primes stay in the storage). The cap is the engine's per-run
ceiling lowered to the RAM budget (as the width proposal); when not one window fits, Atlas is
left out and the blocks stay uncut. The prep of a run depends only on its end, so the costs
take one estimate per end and scale the rest linearly with the span (`time_model.prime_count`
is cached). A block neither method can time is unplanned; when nothing is plannable the
section says to run a benchmark first.

Targets naming an engine are a lane of their own, planned the same way with that engine's
store, RAM-budget cap and costs (Pseudosquares: the selected engine's store) and only that
method, even where the other would be faster; lanes never share a run, so a window named in
two lanes is planned in both. A block the named method cannot time (no measurements, or
beyond the engine) stays in the table with no time, and the summary counts those runs. The
comparison totals cover the targets that name no engine and are left out when there are none.

The table lists each run (floor, from, to, windows, targets, method, time); the summary gives
the plan's total, the totals of separate Atlas runs per block and of Pseudosquares alone, the
targets left out as stored, and notes (seed-estimated engine, Pseudosquares timed from count,
Pseudosquares writes nothing into the storage). Use writes the selected run into Quick-gen:
Atlas into Floor mode (Start = the run's first number, which sets the Floor; Width; storage
writing on; a run of a named Atlas engine first selects that engine in the form),
Pseudosquares into its mode with print (Floor, From, Width). Nothing starts a run. "How does it
work?" reveals a plain-language explanation and the file form.

Insert example puts the text of `target_planner_example.txt` (next to the module, read by
`target_planner_example.py`) into the field: at once into an empty field, nothing when the
field already holds it, after a Yes/No question (No by default) over other text; it plans
nothing. Load file opens in the storage folder, where `ensure_copy()` first writes the example
as `target_planner_example.txt` when it is missing; an existing copy is never overwritten.

## Parameters and texts

[generation-loop](../parameters/generation-loop.md), [generation-constellation](../parameters/generation-constellation.md),
[generation-ktuple](../parameters/generation-ktuple.md),
[generation-verify](../parameters/generation-verify.md); texts `gen.*`, `quick.*`, `close.*`, `timesim.*`, `advisor.*`, `width_advice.*`, `target_planner.*`.

## Kept data

Form values in `ui_state.json` (per install; a storage folder's legacy `.portal_generation_settings.json`
is copied in once), `.generation_logs/` (logs, exit codes, `ACTIVE_RUN.json`),
`GENERATION_STOP_REQUEST.txt`, `STOP_REQUEST.txt` ([data.md](../data.md)).

## Specs and tests

`test_generation_launch_planning`, `test_generation_window_arithmetic`, `test_engine_options`,
`test_engine_presets`, `test_engine_gui_wiring`, `test_run_budget`, `test_run_guard`, `test_close_guard`, `test_close_guard_wiring`,
`test_cross_engine_run_lock`, `test_verify_plan`, `test_verify_width`, `test_verify_windows_field`, `test_gen_progress_bar_engine_gating`, `test_progress_bar_owner`,
`test_console_controls`, `test_constellation_auto_retry`, `test_storage_fill`, `test_pi_seed_checkbox_exclusivity`,
`test_time_model`, `test_run_ram`, `test_free_ram`, `test_time_simulation`, `test_ui_state_app`, `test_pi_count_notice`,
`test_pi_count_notice_controls`, `test_engine_advisor`, `test_engine_advice_gui`, `test_native_plan`,
`test_primesieve_native_controls`, `test_generation_ram_guard`, `test_run_eta`, `test_pipeline_form_layout`,
`test_width_advisor`, `test_width_advice_gui`, `test_quick_auto_split`, `test_target_planner`, `test_target_plan_costs`,
`test_target_plan_text`, `test_target_planner_gui`, `test_target_planner_example`, `test_quick_number`, `test_cpu_load` (D, E).

## Known gaps

- The target planner checks targets on the window grid: a target narrower than a window still
  costs a whole window with either method. Pseudosquares results are not stored, so their
  targets come back in the next plan. Use fills one run at a time; running the whole plan is
  not built.
- The width proposal rests on the linear time model, which always times the widest run that fits
  as the fastest; a measured optimum width per floor (where the per-number cost turns up) is not
  modelled. The benchmark target is a fixed 10^11 numbers.
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
