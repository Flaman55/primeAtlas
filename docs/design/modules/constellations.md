# Module: constellations (Constellations tab)

The Constellations tab: the Storage sub-tab (hit files per floor, k and variant, with each hit's full
tuple), the Constellation calculator (where a number sits in a pattern) and the Records table (scan,
drill-down and PDF/CSV export).

## Files

| Part | Files |
|---|---|
| Storage sub-tab | `primeatlas/constellations/constellations_hits_tab.py`, `constellations_tree_coordinator.py` |
| Calculator | `constellations_calc_tab.py` |
| Records table | `constellations_records_tab.py` |
| Backend | `constellations.py` (hit listing, paged reads, participation search, export) |

## Contract

| In | Out |
|---|---|
| storage path, a number, a pattern | hit tree, tuple previews, participation results, exports |

Reads hit files and `PAGES_META.json` written by `constellation/` and `prime_sieve/hit_paging.py`;
never writes them. Cross-sub-tab jumps go through `primeatlas/app/constellations_section.py`.

## Parameters and texts

Pattern catalog: `constellation/pattern_catalog_v1.py`; texts `const.*`, `const_calc.*`, `const_records.*`, `search.*`.

## Kept data

None of its own.

## Specs and tests

`test_constellations_tab`, `test_constellations_paging`, `test_const_records_worker`,
`test_constellation_auto_retry`.

## Known gaps

None.
