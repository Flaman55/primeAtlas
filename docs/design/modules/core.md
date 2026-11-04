# Module: core (shared GUI infrastructure)

`primeatlas/core/` holds what most tabs share: app settings, translations, theme, storage reads, the
app-wide widgets and the background coordinators for floor totals and search. GUI side only.

## Files

| Part | Files |
|---|---|
| Settings and texts | `app_settings.py` (`AppSettings`), `i18n.py` (`Translator`), `locales/strings_en.json`, `locales/strings_pl.json` |
| Look | `theme.py` (palettes), `app_icon.py`, `assets/` |
| Storage reads | `storage.py` (floor listing, totals cache, `LOW_FLOOR_CUTOFF`) |
| Widgets | `widgets.py` (HeightGrip, ScrollPad, ScrollablePage, FlowRow), `info_tip.py` (InfoTip, the "i" marker with a hover text), `base_tab.py` (`BaseTab`) |
| Background work | `totals_search_coordinator.py` (floor totals and prime/constellation search workers), `background.py` |
| Other | `version.py` (version from CHANGELOG.md: release + merge count, commit label), `pdf_writer.py` (dependency-free PDF) |

## Contract

| In | Out |
|---|---|
| storage path, setting changes, search requests | settings persisted, translated strings, floor totals, search results on the GUI thread |

Never launches WSL; never imports engine code (`ADR 0001`). One control per UI role: HeightGrip for
heights, ScrollPad for scrolling pages, InfoTip for a field's explanation.

## Parameters and texts

Theme, language, font scale and ScrollPad width live in `AppSettings`; texts in both locale files.

## Kept data

`app_settings.json`, `language_settings.json`, `.portal_totals_cache.json` ([data.md](../data.md)).

## Specs and tests

`test_ui_settings`, `test_theme_readability`, `test_scroll_pad`, `test_scrollable_page`,
`test_settings_scroll`, `test_storage`, `test_search_worker`, `test_window_centering`, `test_pdf_table`.

## Known gaps

None.
