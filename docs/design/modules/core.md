# Module: core (shared GUI infrastructure)

`primeatlas/core/` holds what most tabs share: app settings, translations, theme, storage reads, the
app-wide widgets and the background coordinators for floor totals and search. GUI side only.

## Files

| Part | Files |
|---|---|
| Settings and texts | `app_settings.py` (`AppSettings`), `i18n.py` (`Translator`), `locales/strings_en.json`, `locales/strings_pl.json` |
| Computers | `hardware_details.py` (`read_hardware_details()`: one hidden PowerShell `Get-CimInstance` call, no admin: CPU model, maker, family text, cores, threads, base clock, L2/L3; RAM installed size, module count, type from SMBIOSMemoryType, the slowest configured speed; never serial or part numbers; `xmp_hint()`: the JEDEC maximum of the type when the configured speed is above it), `hardware_dynamic.py` (`DETAILS`, read once at startup in the background, refreshed by the About tab's read; a read with nothing known keeps known details), `machines_file.py` (`benchmark_machines.json`, see below) |
| CPU count | `cpu_dynamic.py` (`WSL_CPUS`: the CPU count WSL reports, read once at startup in the background and refreshed by each launch's probe and the About tab's read; a failed probe keeps a known count; `set_wsl_cpus()` tells every ThreadsField) |
| Remembered fields | `ui_state.py` (`remember()`), `ui_state_store.py` (`UiStateStore`, no tkinter; `remove`, `remove_prefix`), `ui_state_dynamic.py` (the app's store, `STORE`) |
| Remembered layout | `layout_const.py`: the defaults, `GRIPS` (place → default, min, max in lines, or pixels for a chart), `SASH_SHARES`, the main window (`WINDOW_STATE` maximized, `WINDOW_SIZE` when normal). `layout_memory.py`: the layout in the remembered-fields store under `layout.` keys: a grip's height (`layout.grip.<place>`, saved on release), a terminal shown or hidden (`layout.console.<place>`, saved on the person's toggle only), a sash share (`layout.sash.<place>`, saved on release), the window (`layout.window.state`, `layout.window.geometry`, saved from its own `<Configure>`; a size larger than the screen is clamped, a position off every screen dropped). A value equal to its default is never stored; a stored value out of range or of another type gives the default. `reset_layout()` (Settings > General > Default layout) removes every `layout.` key and puts every live grip, terminal, sash and the window back at once. No timer |
| Number format | `number_format.py` (`whole`, `decimal`, `compact`: a chart's short form from a million up, three significant digits and an SI prefix; numbers shown to a person in the notation of the UI language or the one picked in Settings > General; `resolve`, `apply_saved`), `number_format_dynamic.py` (`STYLE`, set by `app_dynamic` and the renderer at startup) |
| Theme in use | `theme_dynamic.py` (`THEME`, set by `app_dynamic` at startup, read by `benchmark/line_colors.py`) |
| Look | `theme.py` (palettes), `app_icon.py`, `assets/` |
| Storage reads | `storage.py` (floor listing, totals cache, `LOW_FLOOR_CUTOFF`) |
| Font scale | `font_scale.py`: `apply(root, percent)` (called by `app/app_theme.py` before any widget is built) multiplies `tk scaling` (pixels per point) by percent/100, so every point-sized font grows by that factor. Tk sets `tk scaling` back to the system's value on WM_DISPLAYCHANGE (a monitor woken up, a resolution change) without any event the app can bind, so `check(root)` runs when the app does something: at the start of each layout pass (`responsive.py`), on a window's `<Activate>`, and on a key or mouse press, which comes before any window the press builds. A check that finds a value other than the one set last takes it as the new base (a real DPI change gives a new one), sets base × percent again, re-resolves the named fonts and re-applies the ttk theme, so widgets measured in between get their sizes back. No timer: an idle app does nothing; at 100 % nothing is set up |
| Layout | `responsive.py`: the layout coordinator, one per Tk root (`coordinator(widget)`). An element is registered with `add(widget, layout, width=None, key=None)`; a pass lays requested elements out in rounds, outer before inner, each at most once, and only when its width or `key()` (content sizes) changed since its last layout. A request made during a round joins the next round, which takes only elements deeper than the shallowest of the round before; past `MAX_ROUNDS`, or for a refused request, the coordinator logs the widget and stops, and the app keeps running. A width change of an element's widget, or of a box it watches (`Item.watch(widget)`) while the widget's own width changes too, waits `DEBOUNCE_MS`; being shown (`<Map>`), the first width of an element never laid out, a watched box settling while the widget keeps the width of its last layout, or `Item.request()` runs at the next idle turn; a hidden element waits until shown. An element without `width()` on a ScrollablePage is laid out for its width up to the page's right edge as it is with the scrollbar shown (`steady_width()`), so showing or hiding the scrollbar never changes a layout. `width_class()` names the window width band (`WIDE_MIN` 1600, `MEDIUM_MIN` 1280, arbitrary). `apply_min_width()` (called by `app/app_window.py`) keeps the app window at least `MIN_WINDOW_WIDTH` wide (the screen's width when narrower): 800 px, the narrowest width of the layout map, at which `test_small_screen_layout` finds nothing cut |
| Wrapping text | `wrap_label.py`: `WrapLabel`, the one static text that wraps to its width (every tab's descriptions, hints and status lines; separate dialogs of a fixed size keep a fixed wrap). `RoomFollower` registers it on its reference -- the scrollable page's canvas, a pane or the window -- and measures its room in its box: the nearest ancestor its parent stretches to a width (pack fill x top/bottom or with expand, grid sticky east-west in a column of weight, a notebook tab, a pane); frames that only fit their content are passed by, so a label and its parent never shrink each other. The room runs to the box's right edge less its inner border, every right padding on the way and the widgets packed beside the label, and is measured as with the page's scrollbar shown (`ScrollablePage.steady_width()`), so showing the scrollbar never changes the wrap (two stable states otherwise); it never runs past the reference's right edge, even while a box is wider for a moment. The box is watched, so a width it takes after the layout lays the label out again; the wrap is always narrower than the box, so this settles. `MIN_WRAP_PX` 120 and `INITIAL_WRAP_PX` 760 are arbitrary. `wrapped_check.py` wraps a Checkbutton by the same rule |
| Widgets | `widgets.py` (HeightGrip from `height_grip.py`, ScrollPad, ScrollablePage, FlowRow: a row whose items wrap whole, an item starting a line at the left edge, laid out by `responsive.py` for its frame's width or a given `width()`, the app's one row of fields and buttons; `flow_group`, a frame holding a label with its field as one item; `add_page_nav_row`, a page navigation whose jump group stands flush right, or under the buttons while the row is too narrow, `min_width()` its wider group; `sash_gap`, the width a panedwindow's sashes take; `status_flow_row`, a status text that wraps to the row followed by buttons; FitLabel, a FlowRow label that wraps to the row; `keep_sash_share`, a two-pane panedwindow whose first pane keeps its share of the width across resizes, set by a sash drag), `wrapped_heading.py` (WrappedHeading, a Treeview heading row whose headings wrap to two lines; `heading_wrap.py` the pure wrapping and width fit), `info_tip.py` (InfoTip, the "i" marker with a hover text kept inside the app window), `number_text.py` (`read_number`, the reader of a whole number in any notation, no tkinter), `number_field.py` (`attach`, the number field: red, "Could be" popup, hover tip of its purpose, range and accepted forms), `wrapped_check.py` (a Checkbutton whose text wraps to its width), `elided_choice.py` (ElidedRadiobutton, a FlowRow radio shortened with "…" and an "i" marker with the full name when wider than the row), `threads_field.py` (ThreadsField, the one thread-count control: a Spinbox over a form variable it does not own, its words shown with their count, "Max (8)", the list 1..WSL's CPU count, a larger number turned into Max or the count; `threads_choice.py` its text rules, no tkinter), `base_tab.py` (`BaseTab`) |
| Opening paths | `open_path.py`: `open_path` (a file or folder in its default program: `os.startfile` on Windows, `open`/`xdg-open` elsewhere; OSError for a missing path or a failed opener), `open_folder` (the Folder buttons: a missing folder is an info message and is never created, so a mistyped storage path or an unplugged drive gets no empty folder), `SavedDialog`/`show_saved` (the one "Saved" message after an export: the saved paths, OK the default, Open on the main file, the first path; an open failure is an error message) |
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
A ScrollablePage that shows its scrollbar again at the page size it hid it at, and then finds
the content back at the height it hid it with, keeps the scrollbar (a show/hide loop from a
layout that follows the width a moment late); any other height hides it;
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
`test_info_tip`, `test_font_scale`, `test_layout_memory`, `test_layout_app`, `test_responsive`, `test_wrap_label`, `test_elided_choice`, `test_small_screen_layout`, `test_system_info` (B), `test_cpu_load` (A-C, F), `test_hardware_details`, `test_machines_file`, `test_open_path`.

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

`number_field.attach(entry, T, purpose, fraction=, words=, minimum=, maximum=)` makes an Entry or a
Spinbox a number field (`purpose` is the locale key, `field_tip.*`, that says what the field is for): a whole number by default, a fraction with `fraction=True`, also one
of `words` ("Auto", "Max"), within an optional range (a callable maximum follows a changing
cap, e.g. the engine's per-run windows). It follows the entry's text (typed, pasted, or set through its
textvariable, also one added later by `remember()`). A whole number or an empty field clears
everything at once; red (`Invalid.TEntry` / `Invalid.TSpinbox`, palette `invalid_bg`, also
out of range) and the ambiguous popup wait
`SETTLE_MS` after the last change, so typing through "1,000" or "10^" flashes nothing, and show at
once when the field is left. The popup ("Could be:" and a button per reading) shows while the
field has focus; a click writes the plain digits. Left ambiguous, the field is red and its hover
tip lists the readings. The hover tip (`InfoTip`, below the field, after `TIP_DELAY_MS`) shows the
purpose, the range (bounds in grouped digits in the app's notation, `number_format`; a callable
maximum is read when the tip shows), the accepted forms only where large numbers belong (no
maximum, or one of at least `HELP_FROM` = 10^6; elsewhere one line of the power and scientific
forms), the fraction line on a fraction field and, when
invalid, the reason (a range reason groups its digits too).

Code that reads plain integers keeps its own checks and messages: it reads the text through
`number_text.plain_number()` (the plain digits of an ok reading, else the stripped text);
`number_value()` / `fraction_value()` return the value or None. `number_field.refuse_problem
(variables, T, title)` shows the reason and puts the cursor in the first red field among
`variables`: Tk variables, or the fields' widgets (a bare entry has no variable; its text is read
again first, since text set by code reaches it through no event). An action calls it first, after
its "already running" guard, with exactly the fields it reads, so a red field never becomes a
default and a red field of another action never blocks it: Quick-gen Generate (the selected
mode's fields, `_QUICK_MODE_NUMBER_VARS`), every action of the Generation tab (see
[generation](generation.md#refused-fields)) and every action of the Research tab except
Irreducibility (see [research](research.md#refused-fields)).

`unitTests/test_number_field_coverage.py` requires every `ttk.Entry` and `ttk.Spinbox` in
`primeatlas/` to be a number field or marked `# not a number field: <why>` (folder paths,
formulas in n, lists of offsets, factors, primes or colours), and every `number_field.attach`
call to pass a purpose whose literal key has English and Polish text; `test_number_fields_app`
checks the keys built at run time (one per engine knob, per visualization parameter) on the
live fields.

## Known gaps

- The actions of the Irreducibility sub-tab and of the Visualization, Constellations, Primality,
  Primes and Benchmark tabs do not call `refuse_problem` yet: there a red field is only shown, and the action reads the
  text with its own checks.
- Separate dialogs and windows of a fixed size (machine details, chart windows, consent and
  confirmation dialogs) keep texts of a fixed wrap width; they are not resized with the app.
- Separate windows (a detached terminal, chart windows, the Goldbach and Irreducibility
  cases windows, the environment wizard) have no height grips and their size and position
  are not remembered; table column widths are not remembered either.

## Computers of the benchmark rows

`machines_file.py` keeps `benchmark_machines.json` at the storage root: per `machine_id` a history
of entries. An entry has `since` (in the log's `run_timestamp_utc` format, so the two compare as
text), `auto` (the known `HardwareDetails`), `manual` (architecture, year, turbo_mhz, cl, xmp,
typed by the person, None when not typed), `edited_at` and `asked`. Every GUI launch
(`wsl_command.build_wsl_logged_command()`) records this computer: the first entry, a known value
known only now fills the current one, a known value that changed (RAM swapped) starts a new entry
carrying the typed values and asking again. `entry_for()` gives a run the entry recorded by its
time (a run older than every entry gets the first). Writes are atomic; a file that is not this
shape raises `MachinesFileCorrupt`, is never overwritten, and `preserve_corrupt()` keeps a copy
next to it. `merge()` is the union of two files (the same machine and `since`: the later
`edited_at` wins); backups, restores and storage integration use it, so no entry is lost.
