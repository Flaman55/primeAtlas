# Module: constellation (k-tuple search and targeted sieve, WSL)

`constellation/` finds k-tuple constellations (k = 2..21, the patterns of `pattern_catalog_v1.py`) in
the stored prime windows, exhaustively and in batches (`constellation_finder_v2_3.py`), and hunts for
rare deep hits at chosen locations (`ktuple_sieve_v2_2.py`). Both run under WSL as scripts.

## Files

| Part | Files |
|---|---|
| Exhaustive search (current) | `constellation_finder_v2_3.py` (CLI, `process_floor`, floor boundary), `constellation_const_v2_3.py`, `constellation_portal_v2_3.py`, `constellation_diag_v2_3.py`, `constellation_windows_v2_3.py`, `constellation_progress_v2_3.py`, `constellation_hits_v2_3.py`, `constellation_match_v2_3.py` |
| Targeted sieve (current) | `ktuple_sieve_v2_2.py`, `ktuple_wheel_v2_2.py`, `ktuple_locations_v2_2.py`, `ktuple_hit_store_v2_2.py` |
| Catalog | `pattern_catalog_v1.py` |
| Frozen versions | `constellation_finder_v1.py`, `constellation_finder_v2.py` (reference of every equivalence test), `constellation_finder_v2_1.py`, `constellation_*_v2_2.py`; `ktuple_sieve_v1.py`, `ktuple_sieve_v2.py`, `ktuple_*_v2_1.py` |
| Diagnostics | `debug_single_window.py` |

## Contract

| In | Out |
|---|---|
| argv; `CONSTELLATION_PORTAL_DIR` | hit files, checkpoints and logs under `10p{N}/constellations/` ([constellation-search](../flows/constellation-search.md), [ktuple-sieve](../flows/ktuple-sieve.md)) |

The storage folder is passed explicitly as `portal` to every function that touches disk; only the entry
scripts set sys.path ([ADR 0004](../../adr/0004-shared-values-and-explicit-portal.md)). Log prefixes
`[CONSTELLATIONS v2]` / `[KTUPLE SIEVE v2]` stay fixed because the GUI parses them.

## Parameters and texts

[generation-constellation](../parameters/generation-constellation.md), [generation-ktuple](../parameters/generation-ktuple.md).

## Kept data

`10p{N}/constellations/` ([data.md](../data.md)).

## Specs and tests

`test_constellation_finder_v2_3`, `test_ktuple_sieve_v2_2`, `test_ktuple_sieve_v2_provisional`,
`test_constellation_matching`, `test_constellation_finder_engine`, `test_constellation_finder_v2_checkpoint`,
`test_constellation_finder_v2_automigration`, `test_hit_insert_out_of_order`; equivalence of the frozen
steps: `test_constellation_finder_v2_1`, `test_constellation_finder_v2_2`, `test_ktuple_sieve_v2_1`.

## Known gaps

None.
