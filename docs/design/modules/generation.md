# Module: generation (Generation tab)

Launches and follows every engine run: the generation pipeline (Section A and the Quick-gen panel,
with orchestrator, primesieve, cudasieve and Hybrid modes), the constellation search (Section B) and
the targeted k-tuple sieve (Section C). Only one engine runs at a time.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/generation/generation_tab.py` (`GenerationTab`, WSL runner factory) |
| Sections (mixins) | `quick_gen_panel.py`, `quick_gen_runs.py`, `loop_section.py`, `constellation_section.py`, `ktuple_section.py`, `run_progress.py`, `run_guard_controls.py`, `hybrid_controls.py`, `engine_fields.py` |
| Launching | `engine_argv.py` (argv of every script), `wsl_command.py` (wsl.exe command, logs), `logged_runners.py` (`WslLoggedRunner`, `LocalLoggedRunner`), `wsl_blocking.py`, `wsl_resources.py` |
| Planning | `window_planning.py`, `quick_gen_plan.py`, `run_budget.py`, `engine_options.py`, `quick_number.py` |
| Following and settling | `run_output.py` (log parsing), `run_guard.py` (stop request, active-run marker, recovery), `close_guard.py` |
| Settings | `generation_settings.py` (form defaults and persistence), `generation_console.py` (`GenerationConsole`) |
| Offers | `generation_offer_coordinator.py` ("generate the missing fragment" for other tabs) |

## Contract

| In | Out |
|---|---|
| form values, offers from other tabs | WSL runs ([generation-run](../flows/generation-run.md), [constellation-search](../flows/constellation-search.md), [ktuple-sieve](../flows/ktuple-sieve.md)); consoles, progress bar, totals bumps, tree reloads |

Never imports engine code: names and defaults the engines also use are mirrored and kept equal by
tests (`test_engine_options`). Log lines are parsed by their stable prefixes (`[CONSTELLATIONS v2]`,
`[KTUPLE SIEVE v2]`, `[+] Progress:`).

## Parameters and texts

[generation-loop](../parameters/generation-loop.md), [generation-constellation](../parameters/generation-constellation.md),
[generation-ktuple](../parameters/generation-ktuple.md); texts `gen.*`, `quick.*`, `close.*`.

## Kept data

`.portal_generation_settings.json`, `.generation_logs/` (logs, exit codes, `ACTIVE_RUN.json`),
`GENERATION_STOP_REQUEST.txt`, `STOP_REQUEST.txt` ([data.md](../data.md)).

## Specs and tests

`test_generation_launch_planning`, `test_generation_window_arithmetic`, `test_engine_options`,
`test_engine_gui_wiring`, `test_run_budget`, `test_run_guard`, `test_close_guard`, `test_close_guard_wiring`,
`test_cross_engine_run_lock`, `test_gen_progress_bar_engine_gating`, `test_progress_bar_owner`,
`test_console_controls`, `test_constellation_auto_retry`, `test_storage_fill`, `test_pi_seed_checkbox_exclusivity`.

## Known gaps

- Prep cost (sieving primes up to sqrt(N)) is not yet an ETA unit.
