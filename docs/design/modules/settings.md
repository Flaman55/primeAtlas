# Module: settings (Settings and About tabs)

Settings: language, theme and storage path (General), metadata and full-data backups, restore, storage
integration and deletes (Backup), optional-library installers and self-update (Updates), and the
first-run WSL setup. About: version (release + merges since it), links, This computer (Windows and
WSL hardware, the WSL RAM limit and a row that changes it), the CHANGELOG.md entries since the last release in the UI
language, and NOTICE.md.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/settings/settings_tab.py` and its mixins `general_section.py`, `restore_section.py`, `delete_section.py`, `full_backup_section.py`, `storage_integrate_section.py`, `updates_section.py`, `pseudosquares_section.py` |
| Backups | `manifest.py`, `backup_store.py`, `restore_job.py`, `full_backup.py`, `floor_meta.py`, `storage_integrate.py`, `delete_manager.py` |
| Updates and restart | `app_update.py`, `app_restart.py` |
| First-run setup | `env_setup.py`, `env_setup_wizard.py` |
| Component versions | `prime_sieve/env_versions.py` (WSL-side probe), `env_versions_view.py` (report text and warnings) |
| About | `primeatlas/about/about_tab.py`, `system_info.py` (hardware probe), `system_info_text.py` (its lines), `wslconfig_edit.py` (changes `.wslconfig` memory=), `wsl_limit_row.py` (its row) |

## Contract

| In | Out |
|---|---|
| user choices; `wsl_helpers` from `primeatlas/app/settings_wiring.py` (launch machinery, reload hooks) | settings saved, backups and restores ([backup-restore](../flows/backup-restore.md)), app updated and restarted |

SettingsTab launches WSL jobs only through the injected `wsl_helpers`; it never imports the app.

Component versions: the "Component versions" button in the WSL environment section runs
`prime_sieve/env_versions.py` in WSL (`wsl_blocking.run_env_versions_wsl_blocking`, on a background
thread, only on a click). The probe reports the distro, Python, numpy and gcc, and for libprimesieve
and libprimecount the version from the library's own `*_version()` call, the file the Python process
maps, the file every built `prime_sieve_engine_*.so` resolves (`ldd`) and every distinct file behind
the linker cache's entries (`ldconfig -p`, symlinks collapsed). `env_versions_view.format_report`
turns it into the text and a warning line: a library with more than one copy (an apt package next to
a build under `/usr/local`: the cache order picks one, so installing or removing either changes what
the engines run on), and an engine that resolves another copy than Python. It also names the
Pseudosquares Prime Sieve program (path, version, build commit) and warns when that build is not
the pinned commit.

This computer (About): `system_info.read_system_info()` reads Windows in this process
(`core/windows_hardware.py`: OS, CPU model, physical cores, threads, RAM total and free, and the
computer's id that its benchmark rows carry as `machine_id`), WSL with one
`wsl.exe` call (distro, kernel, `nproc`, MemTotal, MemAvailable of the default distro) and the
`[wsl2]` `memory=` and `processors=` of `%UserProfile%\.wslconfig`. It runs on a background thread the
first time the About page is selected (reading starts WSL, so the app launch never does) and again
on the Refresh glyph; the copy glyph copies the shown lines. The WSL RAM limit is WSL's MemTotal as a
share of Windows RAM, with its source: `memory=` when set, else the WSL default (half the Windows RAM).
A value that cannot be read shows as "unknown"; WSL that does not answer shows as not reachable.

Changing the WSL RAM limit (About → This computer, `wsl_limit_row.WslLimitRow` over
`wslconfig_edit.py`): a whole-GB field (from WSL's own default, half the Windows RAM, up to the
whole RAM) shows `memory=` when set, else the proposal, Windows RAM minus max(3 GiB, 25 %) rounded
to whole GiB (an arbitrary default: it only fills the field). Save is disabled until the Windows
RAM is known and while a WSL restart runs; with the file's own limit (in any unit, the last
`memory=` of `[wsl2]` when there are several) it does nothing at all. A limit above the proposal first gets a warning (Yes/No, No by
default): Windows short of RAM can freeze or switch itself off and lose unsaved work; No keeps
everything as it was. Save then asks with the file's path and the changed lines, then writes: the
old file is copied next to it as `.wslconfig.bak_<date>_<time>`, the new text replaces it in one
rename, only `[wsl2]` `memory=` changes (other keys, sections, comments, line ends and a BOM stay;
a missing line or section is added), and a file edited while the question was open is not
overwritten. The limit applies when WSL starts again: while a Generation job runs
(`close_guard.running_jobs`) WSL is not restarted and a note says so; otherwise Atlas asks to run
`wsl --shutdown`, which stops every WSL program, then reads the hardware again. No admin rights:
the file belongs to the user.

Deletes (Backup sub-tab, `delete_section.py` over `delete_manager.py`): one floor (or only its
constellations), the benchmarks (`count_benchmark_rows` / `clear_benchmark_log`: benchmark_log.csv
keeps its header line as written, floors and caches stay, the Benchmark tab reloads through
`wsl_helpers["reload_benchmark_log"]`), and the whole database (every floor, the totals cache and
the log rows through the same `clear_benchmark_log`). Each asks first; a backup keeps a copy of the
log.

Pseudosquares Prime Sieve (`pseudosquares_section.py`, in Updates): Check status runs
`pseudosquares_install.py --status`; Install / Rebuild probes, installs missing build tools as root
(`wsl_blocking.run_pseudosquares_tools_install_wsl_blocking`, `wsl.exe -u root`), then runs
`--build` on `WslLoggedRunner` with its log in the section's console, then probes again. One button
for install, rebuild and a move to the pin. No consent step: the BSD 2-Clause License asks for the
notice to be kept (NOTICE.md), not for acceptance. The setup wizard has an optional checkbox (off by
default) that adds the same tools and build to its elevated script (`run_install(pseudosquares=True)`,
build as the distro's default user); checked, it enables Install even when everything required is
present.

## Parameters and texts

`AppSettings` properties; texts `settings.*`, `wizard.*`, `about.*`.

## Kept data

`_backups/` manifests and restore checkpoints, full-backup copies, `app_settings.json` flags
([data.md](../data.md)).

## Specs and tests

`test_app_update`, `test_app_update_locks`, `test_app_restart`, `test_env_setup`, `test_delete_manager`,
`test_delete_benchmarks`,
`test_full_backup_hit_paging`, `test_storage_integrate`, `test_benchmark_rows_safety`, `test_dp_settings`,
`test_primecount_settings_integration`, `test_env_versions`, `test_pseudosquares_settings`,
`test_about_tab`, `test_system_info`, `test_wslconfig_edit`.

## Known gaps

- Installer code signing is not set up.
- The WSL restart check sees only the Generation tab's jobs; WSL programs started elsewhere (other
  tabs, a terminal) are named in the restart question, not detected.
