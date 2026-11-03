# Data PrimeAtlas keeps

Paths are relative to the storage folder (the "portal": `CONSTELLATION_PORTAL/` next to the app by
default, or the path chosen in Settings, which reaches the WSL engines as `CONSTELLATION_PORTAL_DIR`).
`10p{N}/` is the folder of floor N, the range [10^N, 10^(N+1)). Nothing here is in git. "Validity" is
how a reader decides whether a kept record is still right for the code that reads it; "none" means it is
used as it was written.

## Prime windows

| Data | Where | Owner module | Format (version) | Validity | Who may read it |
|---|---|---|---|---|---|
| Prime window (D, proven) | `10p{N}/source_primes/shard_NNNNN/PRIME_WINDOW_10p{N}_off_{OFFSET}.bin` | `prime_sieve/` engines (`prime_sieve_v5.py` default, `prime_sieve_pt1.py`, `prime_sieve_primesieve.py`, `prime_sieve_cudasieve.py`, `hybrid_sieve.py`) | PGS2: magic `PGS2`, header (base prime, count, generation time), then count-1 LEB128 varint gaps (`prime_sieve_v1.write_prime_window`) | magic bytes; `window_integrity.py` checks payload = exactly count-1 gaps | engines, every GUI reader, `constellation/` |
| Shard layout | `shard_NNNNN/`, 5000 windows each | `prime_sieve/window_sharding.py` (`SHARD_SIZE`) | folder name from the window index | every reader assumes all floors are sharded; `migrate_shard_source_primes.py` converts old floors | engines and GUI alike |
| Probable-prime window (P) | `10p{N}/source_primes_P/shard_NNNNN/PRIME_WINDOW_10p{N}_off_{OFFSET}_P.bin` | `prime_sieve/storage_kinds.py` (pt1 P runs) | PGS2 | proven by D through `dp_verify.py` | Primes tab, Benchmark |
| D-proves-P marks | `10p{N}/DP_PROVEN.txt`, `10p{N}/DP_MISMATCH.txt` | `storage_kinds.py`, `dp_verify.py` | text | written by "Verify P against D" | Primes tab |
| Sieving-prime count cache | `10p{N}/sieving_primes_count_cache.json` | `prime_sieve/sieving_prime_count_v5.py` | JSON | none (diagnostic) | engines, backup manifest |
| Last scan metrics | `last_scan_metrics.json` | engines (`prime_sieve_v5.py`, primesieve, cudasieve) | JSON | overwritten per run | GUI run summary |

## Run history and totals

| Data | Where | Owner module | Format (version) | Validity | Who may read it |
|---|---|---|---|---|---|
| Benchmark log | `benchmark_log.csv` | header: `prime_sieve/benchmark_log_schema.py` (`BENCHMARK_FIELDNAMES`); writers: `orchestrator_v3.py`, `orchestrator_loop_helpers.py`, `prime_sieve_primesieve.py`, `prime_sieve_cudasieve.py`, `hybrid_sieve.py` | CSV, one row per run; new columns only at the end, older rows keep them blank | a writer migrates an old header in place, never guesses old values | Benchmark tab, totals, floor_meta |
| Floor history copy | `10p{N}/floor_meta.json` | `prime_sieve/floor_meta_store.py` | JSON list of the floor's benchmark rows, deduped by `ROW_KEY_FIELDS` | none | `primeatlas/settings/floor_meta.py` imports it into another storage's log |
| Floor totals cache | `.portal_totals_cache.json` | `primeatlas/core/storage.py` | JSON per floor (prime count, generation time) | rebuilt by a floor rescan (Refresh, after a run) | Primes tab, status bar, backup manifest |

## Constellation search (`10p{N}/constellations/`)

| Data | Where | Owner module | Format (version) | Validity | Who may read it |
|---|---|---|---|---|---|
| Hit file | `k{K}/variant{V}/HITS_10p{N}_k{K}_v{V}.bin`, or pages `HITS_..._page{NNNNN}.bin` + `PAGES_META.json` | `constellation/constellation_hits_v2_3.py`, paging `prime_sieve/hit_paging.py` | PGS2 of each hit's first value; pages ~1M entries (`hit_paging.PAGE_SIZE`) | sorted, deduplicated on append/merge | Constellations tab, k-tuple sieve, backups |
| Last stored value cache | `LAST_VALUES.tsv` | `constellation_hits_v2_3.py` | TSV `k`, `variant`, last value | checked against the hit file's header; otherwise the last value is read from the hit file | finder |
| Window index | `WINDOW_INDEX.tsv` | `constellation_windows_v2_3.py` | TSV filename -> base prime | entries for files no longer on disk are dropped; only new files' headers are read | finder |
| Done log | `DONE_WINDOWS.txt` | `constellation_progress_v2_3.py` | one searched window name per line, fsynced appends | seeded from CHECKPOINT.txt when missing | finder |
| Checkpoint | `CHECKPOINT.txt` | `constellation_progress_v2_3.py` | `last_processed_file=` plus gap-aware `done_range=` lines | atomic rewrite | finder, k-tuple frontier, GUI auto-retry (`engine_argv.read_constellation_checkpoint`) |
| Floor boundary mark | `BOUNDARY_CHECKED.txt` | `constellation_progress_v2_3.py` | text note | written once the cross-floor tail is checked | finder, backups |
| Search stop request | `STOP_REQUEST.txt` (storage root) | written by `primeatlas/generation/constellation_section.py`, read by `constellation_progress_v2_3._stop_requested` | empty marker | deleted by the GUI after the run | finder |
| k-tuple checkpoint | `k{K}/variant{V}/KTUPLE_CHECKPOINT_10p{N}_k{K}_v{V}.txt` | `constellation/ktuple_hit_store_v2_2.py` | text: next offset, step, window_m, strategy | next offset alone is authoritative | k-tuple sieve |
| Provisional hits | `k{K}/variant{V}/PROVISIONAL_HITS_10p{N}_k{K}_v{V}.txt` | `ktuple_hit_store_v2_2.py` | one value per line | hits at or beyond the exhaustive frontier; rediscovered by the finder later | k-tuple sieve |

## Generation runs (GUI side)

| Data | Where | Owner module | Format (version) | Validity | Who may read it |
|---|---|---|---|---|---|
| Run log and exit code | `.generation_logs/{run_id}.log`, `.exit` | `primeatlas/generation/wsl_command.py` | text tail, exit code | none | Generation consoles |
| Active-run marker | `.generation_logs/ACTIVE_RUN.json` | `primeatlas/generation/run_guard.py` | JSON of the launched run | settled at the next start (`recover_unfinished_run`) | Generation tab at startup |
| Closed-console log | `.generation_logs/closed_{key}_{stamp}.log` | `primeatlas/generation/close_guard.py` | text | none | the user |
| Generation stop request | `GENERATION_STOP_REQUEST.txt` | `prime_sieve/generation_stop.py` (GUI writes, orchestrators read) | empty marker | deleted by the GUI after the run and before every launch | orchestrators |
| Generation form values | `.portal_generation_settings.json` | `primeatlas/generation/generation_settings.py` | JSON sections `loop`, `constellation`, `ktuple`; merged over the defaults | a missing key takes its default ([parameters](parameters/README.md)) | Generation tab |

## Backups

| Data | Where | Owner module | Format (version) | Validity | Who may read it |
|---|---|---|---|---|---|
| Metadata backup manifest | `_backups/{name}.json` | `primeatlas/settings/manifest.py`, `backup_store.py` | JSON snapshot of floors, constellations, benchmark log (not the prime data) | none | Settings > Backup |
| Restore checkpoint | `_backups/{name}.restore.json` | `primeatlas/settings/restore_job.py` | JSON of the pausable restore plan | resumed or discarded by the user | Settings > Backup |
| Full-data backup | chosen destination, per floor, gzip copies + `full_backup_meta.json` | `primeatlas/settings/full_backup.py` | gzip files + JSON meta | meta lists what was copied | Settings > Backup |

## Defaults, texts and translations (in git)

- Generation form defaults: `primeatlas/generation/generation_settings.py` (`DEFAULT_GENERATION_SETTINGS`)
  and `engine_options.py` (`DEFAULT_ENGINE`, `DEFAULT_KNOBS`, bounds). A saved value in
  `.portal_generation_settings.json` wins over the default.
- Visualization renderer defaults: each mode's `add_arguments` (argparse), listed in
  [parameters/visualization-renderer.md](parameters/visualization-renderer.md).
- Texts: `primeatlas/core/locales/strings_en.json` and `strings_pl.json`, read through `Translator`
  (`primeatlas/core/i18n.py`); a language change applies after a restart.

## App settings (outside the storage folder)

| Data | Where | Owner module | Format | Validity |
|---|---|---|---|---|
| App settings | `primeatlas/core/locales/app_settings.json` (gitignored) | `primeatlas/core/app_settings.py` | JSON: storage path, theme, font scale, viz parameters, update and setup flags | a legacy `.portal_app_settings.json` next to the app is migrated once |
| Language | `primeatlas/core/locales/language_settings.json` | `primeatlas/core/i18n.py` | JSON | read before the window exists |

## Secrets

None. The app holds no keys or tokens; the self-update check reads the public GitHub API.
