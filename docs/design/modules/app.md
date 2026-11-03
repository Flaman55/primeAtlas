# Module: app (entry point and main window)

`prime_atlas_v2.py` starts the application; `primeatlas/app/` holds `PortalBrowserApp`, the main
window, split into one mixin per tab section. It runs once per app session on the GUI thread.

## Files

| Part | Files |
|---|---|
| Entry point | `prime_atlas_v2.py` (sys.path, dependency check, first-run wizard, `main()`); `prime_atlas_v1.py` (shim that runs it) |
| Shared values | `app_const.py` (preview page sizes, update-check delay), `app_dynamic.py` (`APP_SETTINGS`, `PORTAL_FOLDER`, `TRANSLATOR`, `T`, `REPO_DIR`) |
| Window | `app_window.py` (`PortalBrowserApp`: loading screen, notebook, coordinators, close guard), `app_theme.py` (font scale, palette) |
| Tab sections | `primes_section.py`, `constellations_section.py`, `research_section.py`, `visualization_section.py`, `single_tabs_section.py` (Generation, Benchmark, About), `settings_wiring.py` (Settings, `_set_portal_folder`) |
| Helpers | `paging.py` (`render_page`, `update_nav_controls`) |

## Contract

| In | Out |
|---|---|
| user actions; tab callbacks (reload trees, search, "generate missing" offers) | the window; cross-tab jumps; storage-path changes reaching every tab |

Every tab class is built with injected callables (`get_portal_folder`, `status_var`, `translator`,
reload and search hooks) and never imports this package back. `_set_portal_folder` is the one place
that rebinds `app_dynamic.PORTAL_FOLDER`; tabs read it through `lambda: _dyn.PORTAL_FOLDER`.
Importing `prime_atlas_v2` loads no tkinter (`_build_gui()` imports the window).

## Parameters and texts

Main tab names and status texts in `primeatlas/core/locales/strings_*.json` (`tabs.*`, `app.*`).

## Kept data

None of its own; app settings belong to `core` ([data.md](../data.md)).

## Specs and tests

`test_prime_atlas_app_layout` (layout, shared values, mixins, `_set_portal_folder`), `test_app_sandbox`
(`isolate_app()` used before every full-app build), `test_loading_screen`, `test_entry_point_shim`,
`test_startup_dependency_check`, `test_theme_readability`, `test_app_icon`.

## Known gaps

None.
