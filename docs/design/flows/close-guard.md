# Flow: close guard (closing Atlas while a job runs, and the next start)

Entry points: the main window's close button (`WM_DELETE_WINDOW` → `close_guard.request_close(app)`,
`primeatlas/generation/close_guard.py`); the Generation tab's Stop button for orchestrator runs
(the same save-point stop); the start-up check of an unfinished run (`run_guard.recover_unfinished_run`).

```
 close ─> no job: the app closes
       └> a job: Yes/No dialog with each job's stage (run_guard.job_stage, default No)
            └> Yes: GENERATION_STOP_REQUEST.txt + kill the scanner ─> orchestrator keeps the written
               windows, deletes truncated ones, logs a "stopped" row ─> Stopping window ─> consoles
               saved to .generation_logs/closed_<job>_<UTC>.log ─> the app closes
 next start ─> ACTIVE_RUN.json left ─> process alive? keep the marker : add the missing totals, clear
```

## Facts the design rests on

- A WSL job survives the GUI process exiting: `wsl.exe` is not killed with its parent, the Linux
  process finishes and its `run.log` / `run.exit` stay in `.generation_logs/`, but the totals cache
  is bumped only by a live GUI.
- `WslLoggedRunner.stop()` (terminate `wsl.exe` + `pkill -f <orchestrator>`) kills the whole Linux
  process tree, the scanner included.
- Scanners write windows with a plain `open(path, "wb")`: a kill during a write leaves a truncated
  PGS2 file. The frozen engines and pt1 have no stop hook, so the scanner is killed and the window
  it cut is deleted.
- pt1 writes the windows of each slab right after sieving it; v5 sieves the whole span in RAM and
  writes every window at the end.

## Steps

| Step (module) | Runs when | Reads | Writes / does |
|---|---|---|---|
| Close dialog (`close_guard.py`) | close with a job running | each runner's last 50 output lines (`WslLoggedRunner.TAIL_LINES`) | Yes/No dialog, default No (Enter and Escape answer No), one line per job with its stage; for v5 in the sieve stage a note that nothing of the batch is written yet; No changes nothing |
| Stage (`run_guard.job_stage`) | dialog and Stopping window | output tail | the last stage-bearing line: sieving X%, counting written windows, checking, verifying P against D, starting batch, searching (constellation / k-tuple progress line); else the last non-empty line, cut to `STAGE_LINE_MAX` (80) characters |
| Stop request (`run_guard.write_stop_request`, `generation_stop.py`) | Yes, or Stop | | `GENERATION_STOP_REQUEST.txt` in the storage folder; `pkill -f` of the chosen engine's scanner script only, the orchestrator survives. Storage unreachable → hard stop |
| Save point (`orchestrator_v3.run_orchestrator`) | a batch fails with the stop request present, or the request is found before a batch | windows of the batch written at most 60 s before the request | truncated windows deleted (`window_integrity.is_complete`: the payload holds exactly `count - 1` varint terminators and ends on one); the batch's benchmark row with `run_status = stopped` (no window written → no row); `[!] STOPPED ON REQUEST`, exit code 0. Without the request a failed batch stays an error (rc 1, no row) |
| Loop (`orchestrator_loop_v2.py`) | stop request present | | starts no new iteration; each instance hit by the scanner `pkill` writes its own stopped row |
| Other jobs | Yes | | constellation finder: `STOP_REQUEST.txt` and its checkpoint; k-tuple sieve: checkpoint after every batch; primesieve / Hybrid / CUDASieve: hard stop, repaired on the next start |
| Stopping window (`close_guard.py`) | after Yes | live stages | each job until its runner exits and its finish callback ran (totals bumped, trees reloaded); `Close now` hard-stops what is left; a close request while stopping is ignored |
| Console logs (`close_guard.py`) | every job stopped | console text | `.generation_logs/closed_<job>_<UTC timestamp>.log`, then the app closes |
| Leftover request (`run_guard.clear_stop_request`) | after a run exits and before every launch | | the request file deleted, so it never stops the next run |
| Active-run marker (`run_guard.write_active_run`) | every generation launch | | `.generation_logs/ACTIVE_RUN.json`: floor, engine, kill and scanner patterns, benchmark row count before the run, first target_idx, log and exit paths, start time; `_on_loop_finished` deletes it |
| Recovery (`run_guard.recover_unfinished_run`) | app start, marker left | marker, `pgrep -f <kill pattern>` | process alive (or WSL unreachable): the console says so, the marker stays. Process gone: totals bumped from the rows written since the marker's row count (`compute_totals_bumps_from_new_rows`); with no new row, the floor's windows written after the start time and at most 60 s before the newest of them are checked (`window_integrity.repair_recent`), truncated ones deleted, the floor's D and P totals rescanned; leftover log / exit / stop-request files and the marker deleted; the console reports what was added |

The orchestrators set `sys.stdout.reconfigure(line_buffering=True)` in `__main__`, so a stage
reaches the GUI log file when it is printed. A second Stop press, or a Stop when the request cannot
be written, is a hard stop. A Storage fill queue ends at a save-point Stop and reports it as failed.
Several jobs at once share one dialog and one Stopping window.

## What leaves and what is kept

- Kept: every complete window written before the stop, a benchmark row with `run_status = stopped`
  (read by the Benchmark charts and Storage times like a completed row), the bumped totals, the
  console logs `closed_*.log`.
- Lost: the window being computed when the scanner was killed.
- `run_status` is part of the one benchmark header (`prime_sieve/benchmark_log_schema.py`); a log
  without the column gains it with old rows left blank (= completed).

## Known gaps

- Re-attaching the console to a WSL job that outlived the previous session.
- Graceful stop for primesieve / Hybrid / CUDASieve generation (hard stop + repair on the next start).
- A WSL process from the previous session still running when a new run starts on the same floor.
