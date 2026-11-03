# Module: installer (Windows installer and startup dependency check)

`installer/` builds `PrimeAtlasSetup.exe`: an offline Inno Setup installer bundling pinned CPython and
MinGit, which clones this repository into `{app}\app` and installs `requirements.txt`.
`startup_dependency_check.py` checks those packages before the app's first `primeatlas` import.

## Files

| Part | Files |
|---|---|
| Installer | `installer/PrimeAtlasSetup.iss`, `build_installer.py` (downloads and SHA-256-verifies the pinned ZIPs), `make_icons.py`, `release_notes.md` |
| CI | `.github/workflows/installer.yml` (a `vX.Y.Z` tag publishes the release) |
| Startup check | `startup_dependency_check.py`, `requirements.txt` |
| Launchers | `Run_PrimeAtlas.bat`, `Run_PrimeAtlas_Hidden.vbs`, `prime_atlas_v1.py` |

## Contract

| In | Out |
|---|---|
| pinned versions in the `.iss`; `APP_VERSION` (`primeatlas/core/version.py`) | installer exe; shortcuts running `pythonw.exe prime_atlas_v2.py` |

The startup check imports nothing from `primeatlas`; only numpy blocks startup.

## Parameters and texts

Pins as `#define` in the `.iss`; texts of the check from the locale JSON files.

## Kept data

None.

## Specs and tests

`test_installer_script`, `test_startup_dependency_check`, `test_entry_point_shim`, `test_app_icon`.

## Known gaps

- Code signing is not set up.
