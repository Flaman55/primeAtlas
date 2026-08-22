"""
backup_store.py -- BackupStore, persists/lists BackupManifest snapshots under
<storage_path>/_backups/backup_<timestamp>.json. One plain-JSON file per backup,
human-inspectable, no external dependencies. Lives INSIDE the storage path (unlike
AppSettings, which deliberately lives outside it -- see app_settings.py's docstring) since
a backup is naturally tied to (and should travel with, if the whole portal folder is ever
moved/copied) the data it describes.
"""
import os
import json

from .manifest import BackupManifest

BACKUPS_SUBDIR = "_backups"


class BackupStore:
    """Pure Python, no tkinter dependency -- see manifest.py's own docstring for why this
    whole feature is built this way (exercised directly by unit tests, wired into the GUI
    by settings_tab.py)."""

    def __init__(self, storage_path):
        self.storage_path = storage_path

    @property
    def backups_dir(self):
        return os.path.join(self.storage_path, BACKUPS_SUBDIR)

    def create(self):
        """Builds a fresh manifest from the CURRENT disk state and saves it. Returns the
        saved BackupManifest (its .name is the filename-safe identifier used everywhere
        else, e.g. restore_job.py's checkpoint naming)."""
        manifest = BackupManifest.build_from_disk(self.storage_path)
        self.save(manifest)
        return manifest

    def save(self, manifest):
        """Atomic write (temp file + os.replace()), the same pattern used throughout this
        project's checkpoint files."""
        os.makedirs(self.backups_dir, exist_ok=True)
        path = os.path.join(self.backups_dir, f"{manifest.name}.json")
        tmp_path = f"{path}.tmp{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return path

    def list_backups(self):
        """Returns [(name, path)] sorted NEWEST first -- cheap, just filenames (the
        timestamp is already IN the filename via BackupManifest.name), no need to load
        every manifest just to list them.

        restore_job.py's checkpoint file for a given backup is named
        "{backup_name}.restore.json" (see its restore_checkpoint_path()), and it lives
        in this SAME _backups/ folder. That name also starts with "backup_" and ends
        with ".json", so a naive filter would match it too -- it would show up in the
        GUI's backup list as if it were its own backup, and selecting it would crash
        with KeyError: 'timestamp_utc' inside BackupManifest.from_dict(), since a
        restore checkpoint's JSON shape (backup_name/status/steps) has nothing to do with
        a manifest's (timestamp_utc/storage_path/pietra/...). Excluding ".restore.json"
        specifically (rather than tightening to a strict backup_<timestamp>.json regex)
        keeps this simple and matches restore_checkpoint_path()'s own naming exactly."""
        if not os.path.isdir(self.backups_dir):
            return []
        out = []
        for fname in os.listdir(self.backups_dir):
            if (fname.startswith("backup_") and fname.endswith(".json")
                    and not fname.endswith(".restore.json")):
                name = fname[:-len(".json")]
                out.append((name, os.path.join(self.backups_dir, fname)))
        out.sort(key=lambda t: t[0], reverse=True)
        return out

    def load(self, name):
        path = os.path.join(self.backups_dir, f"{name}.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return BackupManifest.from_dict(data)

    def delete(self, name):
        """Removes one backup's manifest file. Does NOT touch any in-progress restore
        checkpoint for this backup (settings_tab.py's incomplete-restores list has its own
        separate delete button for that -- a backup and a restore-in-progress against it
        are deliberately independent lifecycles, e.g. the user may want to keep resuming a
        restore after pruning the backup list). Silently no-ops if the file is already
        gone (matches this project's general best-effort delete philosophy, see
        delete_manager.py)."""
        path = os.path.join(self.backups_dir, f"{name}.json")
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def restore_csv(self, manifest):
        """Overwrites the CURRENT benchmark_log.csv with the backup's copy -- a separate,
        explicit step (NOT called automatically by anything else here) since restoring the
        CSV history is a real, visible side effect the caller should decide about
        deliberately, same reasoning as this whole feature never touching prime/
        constellation data without being asked."""
        csv_path = os.path.join(self.storage_path, "benchmark_log.csv")
        tmp_path = f"{csv_path}.tmp{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(manifest.benchmark_csv_text)
        os.replace(tmp_path, csv_path)

    def restore_floor_metadata(self, manifest):
        """Thin wrapper around BackupManifest.restore_floor_metadata() -- see that
        method's own docstring for what it actually restores (floor_meta.json rows,
        totals-cache entries, sieving-prime-count caches) and why it's safe to run before
        window regeneration. Kept as its own BackupStore method, called right alongside
        restore_csv() (see settings_tab.py's _on_start_restore()), so both cache-scope
        restores read the same way at the call site."""
        return manifest.restore_floor_metadata(self.storage_path)
