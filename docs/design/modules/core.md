# Module: core (shared GUI infrastructure)

`primeatlas/core/` holds what most tabs share: app settings, translations, theme, storage reads, the
app-wide widgets and the background coordinators for floor totals and search. GUI side only.

## Files

| Part | Files |
|---|---|
| Settings and texts | `app_settings.py` (`AppSettings`), `i18n.py` (`Translator`), `locales/strings_en.json`, `locales/strings_pl.json` |
| CPU count | `cpu_dynamic.py` (`WSL_CPUS`: the CPU count WSL reports, read once at startup in the background and refreshed by each launch's probe and the About tab's read; a failed probe keeps a known count; `set_wsl_cpus()` tells every ThreadsField) |
| Remembered fields | `ui_state.py` (`remember()`), `ui_state_store.py` (`UiStateStore`, no tkinter), `ui_state_dynamic.py` (the app's store, `STORE`) |
| Theme in use | `theme_dynamic.py` (`THEME`, set by `app_dynamic` at startup, read by `benchmark/line_colors.py`) |
| Look | `theme.py` (palettes), `app_icon.py`, `assets/` |
| Storage reads | `storage.py` (floor listing, totals cache, `LOW_FLOOR_CUTOFF`) |
| Widgets | `widgets.py` (HeightGrip, ScrollPad, ScrollablePage, FlowRow), `wrapped_heading.py` (WrappedHeading, a Treeview heading row whose headings wrap to two lines; `heading_wrap.py` the pure wrapping and width fit), `info_tip.py` (InfoTip, the "i" marker with a hover text kept inside the app window), `number_text.py` (`read_number`, the reader of a whole number in any notation, no tkinter), `number_field.py` (`attach`, the number field: red, "Could be" popup, hover tip of the accepted forms), `wrapped_check.py` (a Checkbutton whose text wraps at its parent's width), `threads_field.py` (ThreadsField, the one thread-count control: a Spinbox over a form variable it does not own, its words shown with their count, "Max (8)", the list 1..WSL's CPU count, a larger number turned into Max or the count; `threads_choice.py` its text rules, no tkinter), `base_tab.py` (`BaseTab`) |
| Background work | `totals_search_coordinator.py` (floor totals and prime/constellation search workers), `background.py` |
| Shared progress bar | `progress_bar_owner.py`: one owner at a time writes the bottom bar (`claim_progress_bar`); the busy animation is its own `.after()` loop (`pump_indeterminate`), and every switch to a real fraction goes through `show_fraction`, which stops that loop first so no animation tick moves the value |
| Other | `version.py` (version from CHANGELOG.md: release + merge count, commit label), `pdf_writer.py` (dependency-free PDF), `windows_hardware.py` (`read_windows_info`, `windows_ram`: Windows OS, CPU, cores, threads, RAM total and free, no admin; `this_machine_id()`: the first 12 hex digits of the SHA-256 of the MachineGuid, so benchmark rows tell computers apart without naming one), `cpu_load.py` (`read_system_counters()`: whole-Windows idle and total CPU ticks from `GetSystemTimes`; `CpuSampler`, started once by the app on a daemon thread, one sample a second, 30 s kept; `busy_before_launch()`: the busy share over the last 5 s) |

## Contract

| In | Out |
|---|---|
| storage path, setting changes, search requests | settings persisted, translated strings, floor totals, search results on the GUI thread |

Never launches WSL; never imports engine code (`ADR 0001`). One control per UI role: HeightGrip for
heights, ScrollPad for scrolling pages, InfoTip for a field's explanation (also, anchored on a greyed-out field, for why it cannot be
changed), `number_field.attach` for a field that takes a whole number. The mouse wheel goes
through one app-wide binding made once (`install_wheel_router()`): for each event `route_wheel()`
walks from the widget under the pointer up to its toplevel and scrolls the ScrollPad's page, or the
innermost ScrollablePage whose content does not fit (a nested page that fits passes the wheel out),
so no <Enter>/<Leave> sequence (a dialog, a rebuild after Run) can leave a page without the wheel;
a Toplevel built with a master inside a page is not part of that page. The router
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
`test_settings_scroll`, `test_ui_state`, `test_ui_state_app`, `test_storage`, `test_search_worker`, `test_window_centering`, `test_pdf_table`,
`test_number_text`, `test_number_field`, `test_number_field_coverage`, `test_number_fields_app`,
`test_info_tip`, `test_system_info` (B), `test_cpu_load` (A-C, F).

## Number fields

`number_text.read_number(text)` reads a whole number written in any common notation, typed or
pasted: grouping by spaces of any kind, apostrophes, underscores, commas or dots (groups of three or
Indian lakh groups), a decimal comma or dot, powers (`^`, `**`, superscripts, LaTeX braces),
scientific `1.5E+25`, times signs `* × · 	imes` and `x` before a power of ten, minus signs `- − –`,
`+ - * / ( )`. Arithmetic is exact (fractions) in a small parser, never `eval`; one power is capped at
10^100000. A comma or dot that appears once before exactly three digits is tried as grouping and as a
decimal mark, and only whole results count: one -> ok, several -> ambiguous with the readings
("3,000": 3000 or 3), none -> invalid with a reason (not whole, syntax, too large).
`generation.quick_number._eval_quick_number` returns the value only when it is ok.

`number_field.attach(entry, T, fraction=, words=, minimum=, maximum=)` makes an Entry or a
Spinbox a number field: a whole number by default, a fraction with `fraction=True`, also one
of `words` ("Auto", "Max"), within an optional range (a callable maximum follows a changing
cap, e.g. the engine's per-run windows). It follows the entry's text (typed, pasted, or set through its
textvariable, also one added later by `remember()`). A whole number or an empty field clears
everything at once; red (`Invalid.TEntry` / `Invalid.TSpinbox`, palette `invalid_bg`, also
out of range) and the ambiguous popup wait
`SETTLE_MS` after the last change, so typing through "1,000" or "10^" flashes nothing, and show at
once when the field is left. The popup ("Could be:" and a button per reading) shows while the
field has focus; a click writes the plain digits. Left ambiguous, the field is red and its hover
tip lists the readings. The hover tip (`InfoTip`, below the field, after `TIP_DELAY_MS`) shows the
accepted forms and, when invalid, the reason.

Code that reads plain integers keeps its own checks and messages: it reads the text through
`number_text.plain_number()` (the plain digits of an ok reading, else the stripped text);
`number_value()` / `fraction_value()` return the value or None. `number_field.refuse_problem
(variables, T, title)` shows the reason and puts the cursor in the first red field bound to
those variables; Quick-gen Generate calls it for the selected mode's fields
(`_QUICK_MODE_NUMBER_VARS`), so a red field never becomes a default width.

`unitTests/test_number_field_coverage.py` requires every `ttk.Entry` and `ttk.Spinbox` in
`primeatlas/` to be a number field or marked `# not a number field: <why>` (folder paths,
formulas in n, lists of offsets, factors, primes or colours).

## Known gaps

None.
