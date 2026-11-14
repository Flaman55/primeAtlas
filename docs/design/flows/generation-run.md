# Flow: generation run (Generation form to prime windows on disk)

Entry points: Generation tab, Section A "Run" (`primeatlas/generation/loop_section.py` `_on_run_loop`);
the Quick-gen panel's "Generate" (`quick_gen_runs.py`: orchestrator, primesieve, cudasieve and Hybrid
modes); "generate the missing fragment" offers from the Primes, Constellations, Research and
Visualization tabs (`generation_offer_coordinator.py`); a restore job (Settings > Backup).

```
 _on_run_loop ─> engine_argv.build_loop_argv ─> wsl_command.build_wsl_logged_command
   └─> WslLoggedRunner (wsl.exe) ─> orchestrator_loop_v2.py ─> orchestrator_v3.py ─> engine (prime_sieve_v7_4.py by default)
 GUI: _poll_loop_output tails .generation_logs/{run_id}.log ─> progress bar, console
 exit ─> _on_loop_finished ─> totals bump, reload_primes_tree
```

## Steps

| Step (module) | Runs when | Reads | Writes / does |
|---|---|---|---|
| Form parse and save (`loop_section.py`) | Run clicked, no other engine running | form fields | parsed values into `ui_state.json` (each field also saves its own changes) |
| Run sizing (`engine_options.py`, `run_budget.py`) | v6 / v5 / v4.1 | free WSL RAM (`wsl_resources.py`), RAM budget knob | window count per run |
| Command (`engine_argv.py`, `wsl_command.py`) | always | storage path, engine, knobs | `wsl.exe` command with `CONSTELLATION_PORTAL_DIR` and `PRIMEATLAS_*` env; log/exit paths |
| Active-run marker (`run_guard.py`) | every launch | | `.generation_logs/ACTIVE_RUN.json` |
| Orchestration (`prime_sieve/orchestrator_loop_v2.py`, `orchestrator_v3.py`) | WSL | `GENERATION_STOP_REQUEST.txt` before each iteration | runs the scanner per batch |
| Sieve (`prime_sieve_v6_1.py`, or the engine chosen) | WSL | sieving primes | PGS2 windows in `10p{N}/source_primes/shard_*/`; `benchmark_log.csv` row, `10p{N}/floor_meta.json` |
| Follow (`run_progress.py`, `run_output.py`) | while running | log tail | consoles, shared progress bar, status |
| Stop (`run_guard.py`, `generation_stop.py`) | Stop clicked | | stop request file; scanner processes killed, orchestrator logs what was written |
| Finish (`loop_section._on_loop_finished`) | exit file appears | new benchmark rows | totals bump (`.portal_totals_cache.json`), Primes tree reload, marker cleared |
| Recovery (`run_guard.recover_unfinished_run`) | next app start, marker left | `ACTIVE_RUN.json`, WSL process list | rescans the floor's totals, clears the marker |

Only one engine runs at a time: starting one locks every other Run/Generate button
(`_lock_other_run_buttons`). Closing the app during a run asks first (`close_guard.py`).

## What leaves and what is kept

- What the caller gets: the console log, a progress bar, updated floor totals and tree.
- What is stored ([data.md](../data.md)): prime windows, benchmark row, floor_meta copy, totals cache,
  run log and exit code. A benchmark run (Benchmark checkbox) stores only its benchmark row
  (`run_purpose = benchmark`) and the run log.

## Known gaps

- The prep cost of a run (sieving primes up to sqrt(N)) is not yet an ETA unit; its measurement exists
  (`base_gen_seconds`).
