# Flow: constellation search (prime windows to k-tuple hit files)

Entry points: Generation tab, Section B "Run" (`primeatlas/generation/constellation_section.py`
`_on_run_constellation`); the Constellations tab's "generate the missing constellation" offer; a restore
job; by hand: `python3 constellation/constellation_finder_v2_3.py [floor] [--max-windows N]` under WSL.

```
 _on_run_constellation ─> engine_argv.build_constellation_finder_argv ─> WslLoggedRunner
   └─> constellation_finder_v2_3.py: portal = default_portal_folder()
         for each floor: process_floor(portal, floor, max_windows)
           list_source_windows ─> skip done (DONE_WINDOWS.txt) ─> match_patterns_vectorized per window
           ─> append / defer hits ─> flush deferred hits once per batch ─> done log, CHECKPOINT.txt
           ─> check_floor_boundary (tail of floor N against the start of N+1)
 GUI: progress from "[CONSTELLATIONS v2] i/n:" lines; BATCH DONE ─> next batch (auto-retry)
```

## Steps

| Step (module) | Runs when | Reads | Writes / does |
|---|---|---|---|
| Window list (`constellation_windows_v2_3.py`) | each floor | shard folders, `WINDOW_INDEX.tsv` | index of new files' base primes |
| Resume point (`constellation_progress_v2_3.py`) | each floor | `DONE_WINDOWS.txt` (seeded from `CHECKPOINT.txt`) | which windows remain |
| Match (`constellation_match_v2_3.py`) | each window | the window's primes plus a peek into its successor (and its predecessor's tail at the start of a run) | hits per (k, variant) of `pattern_catalog_v1.py` |
| Store (`constellation_hits_v2_3.py`) | each window | `LAST_VALUES.tsv`, hit file header | appends above the last stored value; values at or below it are deferred and merged sorted once per batch (`hit_paging.insert_hits_paged` for paged files) |
| Progress (`constellation_progress_v2_3.py`) | after the merge | | `DONE_WINDOWS.txt`, `CHECKPOINT.txt` done ranges; a batch's windows count as done only after its merge |
| Stop (`_stop_requested`) | between windows | `STOP_REQUEST.txt` at the storage root | ends the batch cleanly |
| Boundary (`constellation_finder_v2_3.check_floor_boundary`) | floor finished | last window of N, first windows of N+1 | hits crossing the floor edge; `BOUNDARY_CHECKED.txt` |
| Batching (`constellation_section.py`) | `--max-windows` set | "BATCH DONE -- N window(s) remain" | relaunches until none remain; checkpoint-verified auto-retry after a crash |

## What leaves and what is kept

- What the caller gets: per-window progress lines and a per-pattern summary of new hits.
- What is stored ([data.md](../data.md), `10p{N}/constellations/`): hit files or pages, `LAST_VALUES.tsv`,
  `WINDOW_INDEX.tsv`, `DONE_WINDOWS.txt`, `CHECKPOINT.txt`, `BOUNDARY_CHECKED.txt`.

## Known gaps

- None known.
