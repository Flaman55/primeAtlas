# Flow: backup and restore (storage folder to snapshot and back)

Entry points: Settings > Backup (`primeatlas/settings/settings_tab.py` and its sections:
`restore_section.py`, `full_backup_section.py`, `storage_integrate_section.py`, `delete_section.py`).

```
 metadata backup:  BackupManifest.build_from_disk ─> BackupStore.save ─> _backups/{name}.json
 restore:          diff manifest vs disk ─> RestoreJob plan ─> generation / constellation runs ─> _backups/{name}.restore.json
 full backup:      full_backup.py ─> gzip copies + full_backup_meta.json per floor at a destination
 integrate:        storage_integrate.py ─> preview, then copy another storage's floors in
```

## Steps

| Step (module) | Runs when | Reads | Writes / does |
|---|---|---|---|
| Snapshot (`manifest.py`, `backup_store.py`) | "Save backup" | floors, constellation checkpoints and hit counts, benchmark log, totals cache | `_backups/{name}.json` (metadata only, not the prime data) |
| Diff (`restore_section.py`) | a backup is selected | manifest, disk | what is missing on disk now |
| Restore plan (`restore_job.py`) | "Restore" | diff | `_backups/{name}.restore.json`: checkpointed, pausable, resumable, cancellable steps |
| Regenerate (`restore_section._drive_windows_phase`, constellation phase) | each step | RAM estimate, `PRIMESIEVE_MAX_STOP` | primesieve mode where the floor fits uint64, else the orchestrator; then `constellation_finder_v2_3.py` |
| Floor history (`floor_meta.py`) | restore / integrate | `10p{N}/floor_meta.json` | rows merged into `benchmark_log.csv` |
| Benchmark log (`backup_store.restore_csv`) | "Restore" starts | backup's log text, current log | the backup's log, then the current benchmark-purpose rows it lacks (storage rows it lacks go with their files) |
| Full backup (`full_backup.py`) | "Full backup" | window and hit files, the floor's benchmark-purpose log rows | gzip copies, `full_backup_meta.json` and `benchmark_rows.json` at the destination; restore copies them back and appends the missing rows to the log |
| Integrate (`storage_integrate.py`) | "Integrate storage" | another storage folder, its `benchmark_log.csv` | preview, then copy floors and their metadata; the floor's benchmark-purpose rows appended to the local log |
| Delete (`delete_manager.PortalWiper`) | full or per-floor delete, after confirmation | | removes the data; trees reload |
| Delete benchmarks (`delete_manager.clear_benchmark_log`) | after confirmation | | benchmark_log.csv keeps its header only; the Benchmark tab reloads |

## What leaves and what is kept

- What the user gets: a backup list, a diff against disk, a restore that can pause and resume.
- What is stored ([data.md](../data.md)): manifests, restore checkpoints, full-backup copies.

## Known gaps

- A metadata backup cannot restore data that no engine can regenerate the same way (it replays the
  generation); the full-data backup covers that.
- Benchmark-purpose rows live in the storage folder only (`benchmark_log.csv`, and the metadata
  backups in `_backups/` inside it); losing the whole folder loses the ones no full-data backup
  holds. There is no mirror of the log outside the storage.
