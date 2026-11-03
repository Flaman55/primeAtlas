# 0001. Engines run under WSL, the GUI is native Windows and never imports them

Date: 2026-11-03 (recorded; in force since the first GUI). Status: accepted.

## Context
The sieve engines are C shared libraries loaded through ctypes (`prime_sieve_engine_v5.so` and
siblings) plus Linux-only libraries (libprimesieve, libprimecount, CUDASieve). The application is used
on Windows and must start with a plain Windows Python: tkinter, numpy, and for the visualizations
moderngl/glfw/Pillow.

## Decision
The engines and orchestrators run as scripts under WSL, launched by the GUI through `wsl.exe` with
argv and environment variables (`CONSTELLATION_PORTAL_DIR`, `PRIMEATLAS_*`); the GUI follows them
through log files and talks back through stop-request files. The GUI never imports engine modules.
Constants both sides need are either in standard-library-only helpers in `prime_sieve/` that both
import (`window_sharding`, `benchmark_log_schema`, `floor_meta_store`, `generation_stop`) or mirrored
in the GUI and kept equal by tests (`engine_options.py`, `test_engine_options`).

## Options rejected
- Importing the engine modules into the GUI, even just to read a constant: `orchestrator_loop_v2` reaches
  a ctypes-loaded Linux `.so` a few imports down, which the native Windows app must never need
  (`generation_settings.py`, `engine_options.py`).

## Consequences
Every run is a subprocess with a log file; a run the GUI never saw finish is settled at the next start
(`run_guard.recover_unfinished_run`), and every engine can be run by hand. The mirrored constants need
a test each. Paths cross the boundary as `/mnt/...` paths.
