"""
restore_job.py -- RestoreJob, turns a BackupManifest's diff-against-disk (see
manifest.py's BackupManifest.diff_against_disk()) into an ordered, checkpointed,
pausable/resumable/cancellable job.

Deliberately does NOT know how to actually launch orchestrator_loop_v2.py /
constellation_finder_v1.py itself -- that stays in the UI layer (settings_tab.py), which
already has the WslLoggedRunner subprocess-streaming machinery from the Generation tab.
This class only tracks WHAT needs doing and WHAT's been done, one floor at a time, and
persists that to its own small checkpoint file so an interrupted restore resumes from the
next pending floor instead of starting over.
"""
import os
import json

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"


class RestoreStep:
    """One unit of restore work: regenerate a floor's missing source windows and/or
    missing constellation hits. A step is only COMPLETED once the caller (settings_tab.py,
    after its subprocess run(s) for that floor finish) explicitly calls
    RestoreJob.mark_step_done() -- this class never marks itself done."""

    def __init__(self, base_exponent, missing_windows, missing_hits, status=STATUS_PENDING,
                 extra_windows=None, extra_hits=None):
        self.base_exponent = base_exponent
        self.missing_windows = missing_windows
        self.missing_hits = missing_hits
        self.status = status
        # Surplus on disk relative to the backup (e.g. a floor added AFTER the backup
        # was taken) -- see manifest.py's diff_against_disk() docstring. Deleting these
        # is a pure local file op (delete_extra_files() below), driven from
        # settings_tab.py only after an explicit confirm/cancel prompt.
        self.extra_windows = extra_windows or []
        self.extra_hits = extra_hits or []

    @property
    def needs_windows(self):
        return bool(self.missing_windows)

    @property
    def needs_hits(self):
        return bool(self.missing_hits)

    @property
    def has_extra(self):
        return bool(self.extra_windows or self.extra_hits)

    def to_dict(self):
        return {
            "base_exponent": self.base_exponent,
            "missing_windows": self.missing_windows,
            "missing_hits": self.missing_hits,
            "extra_windows": self.extra_windows,
            "extra_hits": self.extra_hits,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(data["base_exponent"], data.get("missing_windows", []),
                    data.get("missing_hits", []), data.get("status", STATUS_PENDING),
                    data.get("extra_windows", []), data.get("extra_hits", []))


class RestoreJob:
    def __init__(self, backup_name, steps, status=STATUS_PENDING, checkpoint_path=None):
        self.backup_name = backup_name
        self.steps = steps  # list[RestoreStep], fixed order (ascending base_exponent --
                             # smallest floor first: cheapest, fastest feedback that the
                             # pipeline actually works before committing to the big ones)
        self.status = status
        self.checkpoint_path = checkpoint_path

    @classmethod
    def from_diff(cls, backup_name, diff, checkpoint_path=None):
        """diff: {base_exponent: {"missing_windows":[...], "missing_hits":[...],
        "extra_windows":[...], "extra_hits":[...]}} -- see BackupManifest.diff_against_disk().
        An empty diff produces a job with zero steps, already STATUS_COMPLETED (nothing to
        do -- the backup and disk already match, in both directions)."""
        steps = [
            RestoreStep(base_exponent, d["missing_windows"], d["missing_hits"],
                        extra_windows=d.get("extra_windows", []),
                        extra_hits=d.get("extra_hits", []))
            for base_exponent, d in sorted(diff.items())
        ]
        status = STATUS_COMPLETED if not steps else STATUS_PENDING
        return cls(backup_name, steps, status, checkpoint_path)

    @property
    def has_any_extra(self):
        """True if ANY step has surplus files -- settings_tab.py uses this to decide
        whether _on_start_restore() needs the extra deletion-warning dialog."""
        return any(s.has_extra for s in self.steps)

    @property
    def pending_steps(self):
        return [s for s in self.steps if s.status == STATUS_PENDING]

    @property
    def done_steps(self):
        return [s for s in self.steps if s.status == STATUS_COMPLETED]

    @property
    def progress(self):
        """(done_count, total_count) -- for a progress bar."""
        return len(self.done_steps), len(self.steps)

    def next_step(self):
        """The next PENDING step in order, or None if everything's done -- the caller
        should stop dispatching new work once this returns None OR self.status is no
        longer STATUS_RUNNING (paused/cancelled)."""
        pending = self.pending_steps
        return pending[0] if pending else None

    def start(self):
        if self.status == STATUS_PENDING:
            self.status = STATUS_RUNNING
            self.save()

    def mark_step_done(self, base_exponent):
        for s in self.steps:
            if s.base_exponent == base_exponent:
                s.status = STATUS_COMPLETED
        if not self.pending_steps and self.status == STATUS_RUNNING:
            self.status = STATUS_COMPLETED
        self.save()

    def pause(self):
        if self.status == STATUS_RUNNING:
            self.status = STATUS_PAUSED
            self.save()

    def resume(self):
        if self.status in (STATUS_PAUSED, STATUS_PENDING) and self.pending_steps:
            self.status = STATUS_RUNNING
            self.save()

    def cancel(self):
        self.status = STATUS_CANCELLED
        self.save()

    def to_dict(self):
        return {
            "backup_name": self.backup_name,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data, checkpoint_path=None):
        steps = [RestoreStep.from_dict(s) for s in data.get("steps", [])]
        return cls(data["backup_name"], steps, data.get("status", STATUS_PENDING), checkpoint_path)

    def save(self):
        """No-op if checkpoint_path wasn't given -- lets tests build/drive a RestoreJob in
        memory only, without touching disk, same as the rest of this feature's pure-logic
        pieces."""
        if not self.checkpoint_path:
            return
        tmp_path = f"{self.checkpoint_path}.tmp{os.getpid()}"
        os.makedirs(os.path.dirname(self.checkpoint_path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.checkpoint_path)

    @classmethod
    def load(cls, checkpoint_path):
        if not os.path.exists(checkpoint_path):
            return None
        with open(checkpoint_path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data, checkpoint_path)


def restore_checkpoint_path(storage_path, backup_name):
    return os.path.join(storage_path, "_backups", f"{backup_name}.restore.json")


def _prune_if_empty(path):
    """Removes `path` if it exists and is now an empty directory. Best-effort (same
    philosophy as the rest of this function's caller) -- returns True if it actually
    removed something, False if the dir doesn't exist, still has content, or removal
    failed for some other reason (never raises)."""
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
            return True
    except OSError:
        pass
    return False


def delete_extra_files(storage_path, base_exponent, extra_windows, extra_hits):
    """Deletes surplus files (present on disk, absent from the backup manifest) for one
    floor. Best-effort, same philosophy as PortalWiper.execute() in delete_manager.py: a
    single locked/undeletable file shouldn't abort the whole operation, so errors are
    collected and returned rather than raised. Pure local file removal (os.remove against
    paths under storage_path) -- unlike regenerating missing files, this needs no WSL
    subprocess, so settings_tab.py can run it synchronously as one restore step.

    Caller (settings_tab.py) is responsible for the confirm/cancel prompt BEFORE calling
    this -- this function itself does not ask, it just deletes what it's told to (the
    warning/confirmation lives in the UI layer, not here).

    Deleting files can empty out source_primes/, a constellations/k{K}/variant{V}/ leaf,
    its parent k{K} dir, constellations/ itself, and ultimately the whole
    10p{base_exponent} folder -- this matters in particular for a floor that was
    entirely absent from the backup, where ALL of its files come back as
    extra_windows/extra_hits (see manifest.py's diff_against_disk() docstring). So after
    removing the listed files, this function also prunes each of those, deepest first,
    but ONLY if actually empty (a floor that still has some backed-up content left over
    is untouched).

    Returns (deleted_count, pruned_count, errors) where errors is a list of
    "filename: OSError" strings."""
    deleted = 0
    errors = []
    pietro_dir = os.path.join(storage_path, f"10p{base_exponent}")
    source_dir = os.path.join(pietro_dir, "source_primes")
    for fname in extra_windows:
        path = os.path.join(source_dir, fname)
        try:
            os.remove(path)
            deleted += 1
        except OSError as e:
            errors.append(f"{fname}: {e}")
    const_dir = os.path.join(pietro_dir, "constellations")
    touched_variant_dirs = set()
    for rel_path in extra_hits:
        path = os.path.join(const_dir, rel_path)
        try:
            os.remove(path)
            deleted += 1
            touched_variant_dirs.add(os.path.dirname(path))
        except OSError as e:
            errors.append(f"{rel_path}: {e}")

    pruned = 0
    for variant_dir in touched_variant_dirs:
        if _prune_if_empty(variant_dir):
            pruned += 1
            if _prune_if_empty(os.path.dirname(variant_dir)):  # k{K} dir, now also empty
                pruned += 1
    if _prune_if_empty(const_dir):
        pruned += 1
    if _prune_if_empty(source_dir):
        pruned += 1
    if _prune_if_empty(pietro_dir):
        pruned += 1
    return deleted, pruned, errors


def prune_empty_pietro_dirs(storage_path):
    """Full bottom-up sweep over every 10p{N} folder directly under storage_path, removing
    any directory that has become empty -- source_primes/, constellations/k{K}/variant{V}/,
    the k{K} dir, constellations/ itself, and finally the 10p{N} floor dir.

    delete_extra_files() above already prunes the specific directories IT touches while
    deleting files for one step, but only those: a floor can end up with OTHER already-
    empty leftover directories it never touched (e.g. a constellations/k{K}/variant{V}/
    leaf that was created at some point but never received a hit file, or was emptied by
    an earlier, unrelated operation) -- those sit there with nothing in them, but because
    delete_extra_files() never lists their parent, a non-empty os.listdir() at a level
    above (constellations/ itself, or the floor dir) blocks its own prune-if-empty check
    even though the ONLY thing left in it is that other empty directory. Meant to run once,
    as the very last step of a restore job (after every step's delete_extra_files() has
    already run), so any such leftover is cleaned up regardless of which specific delete
    last touched (or never touched) it. Best-effort and idempotent, like the rest of this
    module -- never raises, safe to call even if storage_path doesn't exist or nothing
    needs pruning. Only ever touches 10p{N} folders, never storage_path itself or unrelated
    folders like _backups/. Returns the count of directories actually removed."""
    if not os.path.isdir(storage_path):
        return 0
    removed = 0
    for name in os.listdir(storage_path):
        if not (name.startswith("10p") and name[3:].isdigit()):
            continue
        pietro_dir = os.path.join(storage_path, name)
        if not os.path.isdir(pietro_dir):
            continue
        for dirpath, _dirnames, _filenames in os.walk(pietro_dir, topdown=False):
            if _prune_if_empty(dirpath):
                removed += 1
    return removed
