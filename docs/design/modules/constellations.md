# Module: constellations (Constellations tab)

The Constellations tab: the Storage sub-tab (hit files per floor, k and variant, with each hit's full
tuple), the Constellation calculator (where a number sits in a pattern) and the Records table (scan,
drill-down and PDF/CSV export) and the Density sub-tab (hits against the Hardy-Littlewood
prediction over the finder's scanned spans).

## Files

| Part | Files |
|---|---|
| Storage sub-tab | `primeatlas/constellations/constellations_hits_tab.py`, `constellations_tree_coordinator.py` |
| Calculator | `constellations_calc_tab.py`; the pattern control `pattern_picker.py` (`PatternPicker`: k dropdown, variant dropdown, offsets/record line; also used by Generation's k-tuple section and Rings' line mode) |
| Records table | `constellations_records_tab.py` (a PDF/CSV export ends in `core/open_path.show_saved`: OK and Open) |
| Density | `constellations_density_tab.py` (UI, background scan with Stop), `density_scan.py` (covered spans, hits inside them, rows), `hl_density.py` (constant and integral), `density_chart.py` (chart) |
| Backend | `constellations.py` (hit listing, paged reads, participation search, export) |

## Contract

| In | Out |
|---|---|
| storage path, a number, a pattern | hit tree, tuple previews, participation results, exports |

Reads hit files and `PAGES_META.json` written by `constellation/` and `prime_sieve/hit_paging.py`;
never writes them.

Storage sub-tab layout: the tree pane keeps a third of the width (`core/widgets.keep_sash_share`)
across window resizes, the detail pane never narrower than its page navs' widest group (a nav's page jump group goes under its buttons while the row is too narrow, `core/widgets.add_page_nav_row`); a sash drag sets the
share, so a window made narrow and wide again shows the same split.

Density: a floor's covered spans come from its done windows (`DONE_WINDOWS.txt` /
`CHECKPOINT.txt`). A done window spans from its first prime to the next window's first prime
when it reaches that window, else to its last prime + 1. Window widths are not stored, so a
window with at least `DECODE_BELOW` primes is judged by its prime count against li over the
span (`ADJACENCY_SIGMAS`); any other window is decoded, and a last prime within (ln x)^2 of
the next window still reaches it. Hits count only when their base lies in a span; a paged
pattern adds a whole page from its header count and decodes only pages crossing a span edge.
The prediction is `C * integral dt / (ln t)^k` over the same spans, C from
`ktuple_wheel_v2_2.singular_series_constant()` with primes up to `SERIES_LIMIT`. A floor cut
off by Stop is left out whole. Constellations whose tail lies past a scanned window with no
window after it cannot be found by the finder but are in the prediction; the difference is
at most one pattern diameter per span. Cross-sub-tab jumps go through `primeatlas/app/constellations_section.py`.

## Refused fields

Each action first refuses a red number field it reads (`number_field.refuse_problem`), after its
"already running" guard and before any other check, with exactly the fields it reads: Records
Scan and Density Scan the floor from/to, Records PDF and CSV export the export pages from/to,
the calculator's Compute the exponent and offset, Storage Search (button and Enter) the search
number. An empty field behaves as before (no floor bound, offset 0, the "enter an integer"
search error). The minima are the lower bounds the actions check: the calculator's exponent and
offset 0, the search number 0, the export pages 1; the floors have none. The calculator's
exponent stops at 99 999 (`EXP_MAX`: 10^e has `number_text.MAX_DIGITS` digits) and its offset at
9·10^e − 1, so 10^e + offset stays on floor e; the offset's maximum follows the exponent field
(the exponent's top while that field holds no usable value).

## Parameters and texts

Pattern catalog: `constellation/pattern_catalog_v1.py`; texts `const.*`, `const_calc.*`, `const_records.*`, `const_density.*`, `search.*`.
Density constants (arbitrary): `hl_density.SERIES_LIMIT` 200 000, `hl_density.SEGMENT_RATIO` 1.1,
`density_scan.ADJACENCY_SIGMAS` 3, `density_scan.DECODE_BELOW` 100 000, `density_chart.Y_CAP` 5.
Remembered fields: `constellations.density.k`, `.floor_from`, `.floor_to`.

## Kept data

None of its own.

## Specs and tests

`test_constellations_tab`, `test_constellations_paging`, `test_const_records_worker`,
`test_constellation_auto_retry`, `test_constellations_density`, `test_constellations_density_tab`,
`test_pattern_picker`, `test_field_refusal_tools_app` (refused fields and minima).

## Known gaps

None.
