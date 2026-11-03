# Flow: app startup (double-click to a usable window)

Entry points: `python prime_atlas_v2.py`, `Run_PrimeAtlas.bat`, `Run_PrimeAtlas_Hidden.vbs`, the installer's
shortcuts (`pythonw.exe prime_atlas_v2.py`), `prime_atlas_v1.py` (compatibility shim), the in-app restart
(`primeatlas/settings/app_restart.py`).

```
 prime_atlas_v2.py: sys.path (prime_sieve/, constellation/) ─> startup_dependency_check.ensure_dependencies
   ─> app_dynamic (AppSettings, PORTAL_FOLDER, Translator) ─> main()
   ─> set_app_user_model_id ─> env_setup_wizard.maybe_run_first_run_wizard
   ─> PortalBrowserApp(): theme, loading screen, tabs built one by one, coordinators
   ─> benchmark log read, both tree scans in the background ─> loading screen removed
   ─> close guard, previous run settled, update auto-check after 5 s
```

## Steps

| Step (module) | Runs when | Reads | Writes / does |
|---|---|---|---|
| Dependency check (`startup_dependency_check.py`) | run as the app, never on import | `requirements.txt` | offers `pip install`; numpy missing blocks startup |
| Shared startup values (`primeatlas/app/app_dynamic.py`) | import | `app_settings.json`, `language_settings.json` | `APP_SETTINGS`, `PORTAL_FOLDER`, `TRANSLATOR` |
| First-run wizard (`primeatlas/settings/env_setup_wizard.py`) | `setup_completed` not set | WSL, Ubuntu, apt packages (`env_setup.py`) | installs after confirmation; may need a reboot |
| Window (`primeatlas/app/app_window.py`) | always | theme, font scale | eight main tabs, each built by its section mixin under a loading caption |
| Tree scans (`primes_tree_coordinator.py`, `constellations_tree_coordinator.py`) | background | storage folder | floor lists; the totals scan per floor (`totals_search_coordinator.py`) |
| Previous run (`run_guard_controls.recover_previous_run`) | `ACTIVE_RUN.json` left | WSL process list | settles the run ([generation-run](generation-run.md)) |
| Update check (`settings/app_update.py`) | `auto_update_check` on, 5 s after start | GitHub API or `git fetch` | status in Settings > Updates |

## What leaves and what is kept

- What the user gets: the main window with every tab, the status bar with totals.
- What is stored: nothing new unless the wizard or the dependency installer runs.

## Known gaps

- None known.
