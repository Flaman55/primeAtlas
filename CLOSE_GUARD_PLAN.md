# Close guard: closing Atlas while a job runs

## Goal

Closing the main window while a Generation-tab job runs (generation, constellation
finder, k-tuple sieve) asks first. On "Yes" the app takes a save point, stops the job and
only then closes. The next start detects a generation run that never reported back and
adds its missing totals.

## Measured facts the design rests on

- A WSL job survives the GUI process exiting: `wsl.exe` is not killed with its parent,
  the Linux process finishes, its `run.log` / `run.exit` stay in `.generation_logs/`, and
  the totals cache is never bumped (`_bump_totals_from_finished_run` runs only in a live
  GUI).
- `WslLoggedRunner.stop()` (terminate `wsl.exe` + `pkill -f <orchestrator>`) kills the
  whole Linux process tree, the scanner child included.
- Scanners write windows with a plain `open(path, "wb")`: a kill during a write leaves a
  truncated PGS2 file.
- `run_orchestrator` writes a benchmark row only for completed batches; the GUI launches
  one batch per run, so a stopped run logs nothing although its windows are on disk.
- pt1 writes the windows of each slab right after sieving it; v5 sieves the whole span in
  RAM and writes every window at the end.

## Behaviour

### 1. Close dialog

- `WM_DELETE_WINDOW` on the main window goes through `close_guard.request_close(app)`.
- No job running: the app closes at once, as today.
- A job running: a Yes/No dialog, default No (Enter and Escape answer No), one line per
  running job: `Generation is running (stage: sieving 42.10%).` and the question
  `Close anyway?`. Windows already written are kept; the window being computed is lost.
  For v5 in the sieve stage the dialog also says that nothing of this batch is written
  yet.
- No: nothing changes, the job keeps running.

### 2. Stage

`run_guard.job_stage(tail_lines)` maps the last lines of a job's output to a stage label:

| last matching line                                   | stage                       |
|------------------------------------------------------|-----------------------------|
| `[+] Progress: X% (...)`                             | sieving X%                  |
| `[*] Counting the primes of the written windows ...` | counting written windows    |
| `[*] D proves P ...`                                 | verifying P against D       |
| `... Launching batch ...`                            | starting batch              |
| constellation / k-tuple progress lines               | searching (last line)       |
| anything else                                        | the last non-empty line, cut to 80 characters |

`WslLoggedRunner` keeps the last 50 output lines (`tail_lines`) so the stage needs no
tkinter.

### 3. Save point and stop ("Yes")

The same graceful stop serves the close dialog and the Generation tab's Stop button for
orchestrator runs (one stop pattern app-wide).

1. The GUI writes `GENERATION_STOP_REQUEST.txt` in the storage folder and kills only the
   scanner processes (`pkill -f <scanner script>` of the chosen engine, e.g.
   `prime_sieve_pt1.py`); the orchestrator survives.
2. `orchestrator_v3.run_orchestrator`: a failed batch with the stop request present is a
   stop, not an error. It
   - validates every window of the batch whose header `generated_at` is at most 60 s
     older than the stop request (a kill can only cut those) and deletes truncated ones
     (`window_integrity.is_complete`: the payload holds exactly `count - 1` varint
     terminators and ends on one; a header that does not parse is truncated);
   - writes the benchmark row over the batch as usual (counts and bytes from the headers
     of the windows that exist), with the new column `run_status = stopped`
     (completed rows: `completed`; old rows stay blank = completed);
   - prints `[!] STOPPED ON REQUEST ...` and exits with code 0.
   A stop with no window written writes no row (v5 in the sieve stage).
3. `orchestrator_loop_v2`: starts no new iteration while the stop request exists.
4. Constellation finder: its existing graceful stop (`STOP_REQUEST.txt`, checkpoint).
   k-tuple sieve: its existing stop (checkpoint after every batch).
   Primesieve / hybrid / CUDASieve generation: their existing hard stop; the next start
   repairs their floor (section 5).
5. A "Stopping..." window shows each job with its live stage (e.g. counting written
   windows) until every runner has exited and its finish callback ran (totals bumped,
   trees reloaded). It has one button, `Close now`: hard stop of what is left, the next
   start repairs it.
6. The console text of every stopped job is saved to
   `.generation_logs/closed_<job>_<UTC timestamp>.log`; then the app closes.
7. The GUI deletes the stop request after the run exits and before every launch, so a
   leftover file never stops the next run.

### 4. Unbuffered orchestrators

`orchestrator_v3.py` and `orchestrator_loop_v2.py` set `sys.stdout.reconfigure(
line_buffering=True)` in `__main__`, so the stage (counting written windows in
particular) reaches the GUI log file when it is printed.

### 5. Unfinished run detected on the next start

- Every generation launch writes `.generation_logs/ACTIVE_RUN.json`: floor, engine,
  kill pattern, scanner pattern, benchmark row count before the run, first target_idx,
  log and exit paths, start time. `_on_loop_finished` deletes it.
- On start, a background check reads the marker:
  - process still alive in WSL (`pgrep -f <kill pattern>`): the Generation console says
    so; the marker stays and the check repeats on the next start. Re-attaching the
    console to a running job is not built (Known gaps).
  - process gone: totals are bumped from the benchmark rows written since the marker's
    row count (`compute_totals_bumps_from_new_rows`); with no new row, the windows of the
    marker's floor written after its start time and at most 60 s before the newest of
    them are checked by `window_integrity` (a kill cuts only the windows being written,
    which are the newest; truncated ones are deleted and generated again by the next run)
    and the floor totals are rescanned
    (`update_floor_totals_cache` for D and P). Leftover log / exit / stop-request files
    are deleted, then the marker. The console reports what was added.

## Acceptance criteria

1. Close with no job: the window closes, no dialog.
2. Close with a job: the dialog lists each job with its stage; default No; No keeps the
   job running and the app open.
3. `job_stage` returns the labels of the table above for each pattern, including a
   tail with mixed lines (the last matching line wins).
4. Yes on a pt1 run: windows written before the stop stay, no truncated window remains,
   one benchmark row with `run_status = stopped` and the counts of the kept windows,
   totals bumped by that row, console log file written, then the app closes.
5. Yes on v5 in the sieve stage: no window written, no row, the app closes.
6. Orchestrator stop path: a batch failing with the stop request present gives rc 0,
   a `stopped` row; without the request it stays an error (rc 1, no row), as today.
7. `window_integrity.is_complete` is True for every window `write_prime_window_offsets`
   writes (empty, one prime, many) and False for every truncation of such a file.
8. A leftover stop request is deleted before a launch; a launch with it does not stop.
9. Next start with a marker and no live process: missing totals added (from the row, or
   by rescan when there is none), truncated windows of the run written at most 60 s
   before its newest window deleted (older windows are not read), leftover files and
   marker removed. With a live process: marker kept, message shown.
10. Benchmark schema migration adds `run_status` to an existing log without changing
    old rows; every writer (orchestrator_v3, orchestrator_loop_helpers, primesieve,
    cudasieve, hybrid) shares one header and logs completed rows with
    `run_status = completed`; Benchmark charts and Storage times read stopped rows like
    completed ones.

## Edge cases

- Several jobs at once (generation + constellation): one dialog, one Stopping window.
- Stop pressed twice: the second press is a hard stop. Close during Stopping: ignored
  while stopping.
- Storage fill queue: a save-point Stop (orchestrator exit 0) ends the queue and reports
  it as failed, so the queue never continues after a Stop.
- `pkill` of the scanner reaches every instance of an orchestrator_loop_v2 run; each
  instance writes its own stopped row.
- Storage folder unreachable when writing the stop request: fall back to the hard stop.
- Marker written by an older run of a different storage folder: the marker lives in the
  storage folder it belongs to, so only the current folder is checked.
- A WSL process from the previous session still running when the user launches a new
  run on the same floor: out of scope (Known gaps).

## Decisions taken without asking (disclosed)

- The scanner is killed, not asked to finish the current window: v5 and v4.1 are frozen
  and pt1 has no stop hook. The window cut by the kill is deleted, so the outcome
  "no truncated files" holds; the cost is that one window.
- The Generation tab's Stop button for orchestrator runs uses the same save point
  (one stop pattern app-wide).
- Logic lives in new modules (`primeatlas/generation/run_guard.py`,
  `primeatlas/generation/close_guard.py`, `prime_sieve/window_integrity.py`);
  `prime_atlas_v2.py` (over 1000 lines) and `generation_tab.py` (over 1000 lines) get
  only the wiring calls.

## Decisions taken during implementation

- A second Stop press (or Stop when the stop request cannot be written) is a hard stop:
  the save-point stop never leaves the user without a way to kill at once.
- The orchestrator also checks the stop request before every batch: a Stop that lands
  before the scanner exists finds nothing to kill.
- `run_status` is added to every copy of `BENCHMARK_FIELDNAMES` (orchestrator_v3,
  orchestrator_loop_helpers, hybrid_sieve, prime_sieve_primesieve, prime_sieve_cudasieve):
  a copy without it would stop migrating the log and append short rows. Merging the
  copies into one module is its own branch.
- A completed run without a scanner handoff now logs `bytes_written` from the window
  sizes (one `fstat` on the header read) instead of leaving it blank.
- On recovery without a benchmark row, the windows written within a minute of the newest
  one get the full check (the kill time is unknown).
- An unreachable WSL during the start-up check counts as "still running": the marker
  waits for the next start rather than settling a run that may still be going.
- Launches go through one method (`RunGuardControls._start_loop_runner`); the runner class
  is still looked up in `generation_tab` at call time, the seam the GUI tests use.

## Known gaps

- Re-attaching the console to a WSL job that outlived the previous session.
- Graceful stop for primesieve / hybrid / CUDASieve generation (hard stop + repair on
  next start).
