# Module: settings (Settings and About tabs)

Settings: language, theme and storage path (General), metadata and full-data backups, restore, storage
integration and deletes (Backup), optional-library installers and self-update (Updates), and the
first-run WSL setup. About: version, links and NOTICE.md.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/settings/settings_tab.py` and its mixins `general_section.py`, `restore_section.py`, `delete_section.py`, `full_backup_section.py`, `storage_integrate_section.py`, `updates_section.py` |
| Backups | `manifest.py`, `backup_store.py`, `restore_job.py`, `full_backup.py`, `floor_meta.py`, `storage_integrate.py`, `delete_manager.py` |
| Updates and restart | `app_update.py`, `app_restart.py` |
| First-run setup | `env_setup.py`, `env_setup_wizard.py` |
| About | `primeatlas/about/about_tab.py` |

## Contract

| In | Out |
|---|---|
| user choices; `wsl_helpers` from `primeatlas/app/settings_wiring.py` (launch machinery, reload hooks) | settings saved, backups and restores ([backup-restore](../flows/backup-restore.md)), app updated and restarted |

SettingsTab launches WSL jobs only through the injected `wsl_helpers`; it never imports the app.

## Parameters and texts

`AppSettings` properties; texts `settings.*`, `wizard.*`, `about.*`.

## Kept data

`_backups/` manifests and restore checkpoints, full-backup copies, `app_settings.json` flags
([data.md](../data.md)).

## Specs and tests

`test_app_update`, `test_app_update_locks`, `test_app_restart`, `test_env_setup`, `test_delete_manager`,
`test_full_backup_hit_paging`, `test_storage_integrate`, `test_dp_settings`,
`test_primecount_settings_integration`, `test_about_tab`.

## Known gaps

- Installer code signing is not set up.
