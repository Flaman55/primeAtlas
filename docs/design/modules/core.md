# Module: core (shared GUI infrastructure)

`primeatlas/core/` holds what most tabs share: app settings, translations, theme, storage reads, the
app-wide widgets and the background coordinators for floor totals and search. GUI side only.

## Files

| Part | Files |
|---|---|
| Settings and texts | `app_settings.py` (`AppSettings`), `i18n.py` (`Translator`), `locales/strings_en.json`, `locales/strings_pl.json` |
| Remembered fields | `ui_state.py` (`remember()`), `ui_state_store.py` (`UiStateStore`, no tkinter), `ui_state_dynamic.py` (the app's store, `STORE`) |
| Theme in use | `theme_dynamic.py` (`THEME`, set by `app_dynamic` at startup, read by `benchmark/line_colors.py`) |
| Look | `theme.py` (palettes), `app_icon.py`, `assets/` |
| Storage reads | `storage.py` (floor listing, totals cache, `LOW_FLOOR_CUTOFF`) |
| Widgets | `widgets.py` (HeightGrip, ScrollPad, ScrollablePage, FlowRow), `wrapped_heading.py` (WrappedHeading, a Treeview heading row whose headings wrap to two lines; `heading_wrap.py` the pure wrapping and width fit), `info_tip.py` (InfoTip, the "i" marker with a hover text kept inside the app window), `base_tab.py` (`BaseTab`) |
| Background work | `totals_search_coordinator.py` (floor totals and prime/constellation search workers), `background.py` |
| Other | `version.py` (version from CHANGELOG.md: release + merge count, commit label), `pdf_writer.py` (dependency-free PDF) |

## Contract

| In | Out |
|---|---|
| storage path, setting changes, search requests | settings persisted, translated strings, floor totals, search results on the GUI thread |

Never launches WSL; never imports engine code (`ADR 0001`). One control per UI role: HeightGrip for
heights, ScrollPad for scrolling pages, InfoTip for a field's explanation (also, anchored on a greyed-out field, for why it cannot be
changed). A page's wheel handler
leaves the wheel to widgets that use it themselves (`event_over_own_scroller()`: Text, Listbox,
Treeview, and an enabled ttk.Spinbox or ttk.Combobox, whose Tk class binding steps its value), so the page and
the widget never move together. The wheel never switches notebook tabs: Tk 9 binds it on the
TNotebook class to cycle the tabs, and `disable_notebook_wheel()` (called when the app window is
built) removes those bindings, so the wheel over a tab strip scrolls the page under it.

Remembered fields: a tab binds each input to a key with `remember(key, var_or_widget)`; the value is
restored when the tab is built and saved on every change (debounced, `SAVE_DELAY_MS`), with no Save or
Run click. An Entry or Combobox without a textvariable gets one. A read-only Combobox restores only a
value it lists; `choices=` stores a translated drop-down's id, so the value survives a language change.
Not remembered: one-shot fields (Quick-gen starting point, k-tuple reset checkpoint), status and result
labels, page and go-to fields, search boxes, the Constellation records export page range. Settings
(Save buttons) and the visualization tabs (parameters saved at launch, `AppSettings`) keep their own.

## Parameters and texts

Theme, language, font scale and ScrollPad width live in `AppSettings`; texts in both locale files.

## Kept data

`app_settings.json`, `language_settings.json`, `ui_state.json`, `.portal_totals_cache.json` ([data.md](../data.md)).

## Specs and tests

`test_ui_settings`, `test_theme_readability`, `test_scroll_pad`, `test_scrollable_page`, `test_tree_scroll_to_top`,
`test_settings_scroll`, `test_ui_state`, `test_ui_state_app`, `test_storage`, `test_search_worker`, `test_window_centering`, `test_pdf_table`.

## Known gaps

None.
