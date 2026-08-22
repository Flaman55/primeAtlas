"""
manifest.py -- pure-logic, tkinter-free models for the Settings tab's backup/restore
feature.

A "backup" here is NOT a copy of the actual prime/constellation data -- a single floor can
be hundreds of GB, so copying that wholesale is not realistic. A backup is a MANIFEST: a lightweight JSON
snapshot of what SHOULD exist on disk (which floors, which source-window filenames each,
which constellation k/variant hit files, what each floor's constellation CHECKPOINT.txt
said) plus a copy of benchmark_log.csv's text. Restoring a backup means comparing this
manifest against the CURRENT disk state and, if anything is missing, optionally
regenerating it via the existing orchestrator_loop_v2.py / constellation_finder_v1.py
pipelines -- see restore_job.py for the checkpointed/pausable job that drives that.

Also snapshotted per floor (added 2026-08-18, at Artur's request): the two on-disk caches
that exist purely to speed up prime-count display (.portal_totals_cache.json at the
storage root, 10p{N}/sieving_primes_count_cache.json per floor) and floor_meta.json's
benchmark-row history (see floor_meta.py) -- none of these are DATA (nothing is lost if
they're missing, they just get recomputed/rescanned), but restoring them saves that
recompute cost and, for floor_meta.json specifically, restores generation-history rows
that might otherwise only exist in this exact backup. See backup_store.py's
restore_floor_metadata() for the write-back side.
"""
import os
import re
import json
import datetime

from . import floor_meta

_PIETRO_DIR_RE = re.compile(r"^10p(\d+)$")
_SOURCE_WINDOW_RE = re.compile(r"^PRIME_WINDOW_10p\d+_off_(\d+)(M)?\.bin$")
_CONSTELLATION_K_RE = re.compile(r"^k(\d+)$")
_CONSTELLATION_VARIANT_RE = re.compile(r"^variant(\d+)$")
_HITS_FILE_RE = re.compile(r"^HITS_10p\d+_k\d+_v\d+\.bin$")

TOTALS_CACHE_FILENAME = ".portal_totals_cache.json"
SIEVING_CACHE_FILENAME = "sieving_primes_count_cache.json"


def _load_json_best_effort(path):
    """Returns the parsed JSON dict at `path`, or None if it doesn't exist or is corrupt --
    never raises, same best-effort philosophy as load_totals_cache() in prime_atlas_v1.py
    (deliberately NOT imported from here -- that module imports tkinter transitively, and
    this one must stay importable without it, see this file's own docstring)."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _save_json_atomic(path, data):
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except OSError:
        return False


def _pietra_on_disk(storage_path):
    """Every base_exponent with a 10p{N} folder actually present on disk right now --
    shared by build_from_disk() (what to snapshot) and diff_against_disk() (which also
    needs this to notice a floor that exists on disk but was never in the backup at
    all -- see that method's docstring)."""
    found = set()
    if os.path.isdir(storage_path):
        for name in os.listdir(storage_path):
            m = _PIETRO_DIR_RE.match(name)
            if m and os.path.isdir(os.path.join(storage_path, name)):
                found.add(int(m.group(1)))
    return found


class PietroSnapshot:
    """What one floor (10p{N}/source_primes/) looked like on disk at backup time: just
    filenames, not contents -- the filename alone encodes the offset (see
    _SOURCE_WINDOW_RE), and reading every window's header just to build a backup would be
    exactly the expensive per-file I/O the totals-cache background worker already exists to
    avoid (measured at ~78s for one 15,101-file floor). A backup only needs to
    know WHICH files exist -- restoring means regenerating missing ones from scratch, not
    restoring bytes.

    meta_rows/totals_cache_entry/sieving_cache (added 2026-08-18) are the exception to
    "just filenames, not contents": these three are small, cheap-to-embed JSON blobs (a
    floor's benchmark-row history, its totals-cache sub-object, its sieving-prime-count
    cache) that exist purely to avoid recomputation, not to describe what needs
    regenerating -- see this module's own docstring and floor_meta.py."""

    def __init__(self, base_exponent, filenames, meta_rows=None, totals_cache_entry=None,
                 sieving_cache=None):
        self.base_exponent = base_exponent
        self.filenames = sorted(filenames)
        self.meta_rows = list(meta_rows) if meta_rows else []
        self.totals_cache_entry = totals_cache_entry  # dict or None
        self.sieving_cache = sieving_cache  # dict or None

    @property
    def file_count(self):
        return len(self.filenames)

    def to_dict(self):
        return {
            "base_exponent": self.base_exponent,
            "filenames": self.filenames,
            "meta_rows": self.meta_rows,
            "totals_cache_entry": self.totals_cache_entry,
            "sieving_cache": self.sieving_cache,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(int(data["base_exponent"]), list(data.get("filenames", [])),
                    data.get("meta_rows", []), data.get("totals_cache_entry"),
                    data.get("sieving_cache"))

    @classmethod
    def scan(cls, storage_path, base_exponent, totals_cache=None):
        """`totals_cache` is the ALREADY-LOADED root .portal_totals_cache.json dict (see
        BackupManifest.build_from_disk, which loads it once for every floor rather than
        re-reading the same root file per floor) -- optional so this can still be called
        standalone (e.g. from tests) with totals_cache=None, in which case
        totals_cache_entry is simply left None."""
        source_dir = os.path.join(storage_path, f"10p{base_exponent}", "source_primes")
        names = []
        if os.path.isdir(source_dir):
            names = [n for n in os.listdir(source_dir) if _SOURCE_WINDOW_RE.match(n)]

        meta = floor_meta.load_floor_meta(storage_path, base_exponent)
        meta_rows = meta["benchmark_rows"] if meta else []

        totals_cache_entry = None
        if totals_cache:
            totals_cache_entry = totals_cache.get(f"10p{base_exponent}")

        sieving_cache_path = os.path.join(
            storage_path, f"10p{base_exponent}", SIEVING_CACHE_FILENAME)
        sieving_cache = _load_json_best_effort(sieving_cache_path)

        return cls(base_exponent, names, meta_rows, totals_cache_entry, sieving_cache)

    def missing_from(self, other):
        """Filenames present in self (the backup) but absent from `other` (current disk)."""
        return sorted(set(self.filenames) - set(other.filenames))


class ConstellationSnapshot:
    """What one floor's constellations/ folder looked like: which (k, variant) hit files
    exist (as "k{K}/variant{V}/HITS_....bin" relative paths), plus the floor-level
    CHECKPOINT.txt text (constellation_finder_v1.py writes ONE checkpoint per floor, not
    per k/variant -- see that file's own module docstring)."""

    def __init__(self, base_exponent, hit_files, checkpoint_text):
        self.base_exponent = base_exponent
        self.hit_files = sorted(hit_files)
        self.checkpoint_text = checkpoint_text  # None if no checkpoint existed at scan time

    def to_dict(self):
        return {
            "base_exponent": self.base_exponent,
            "hit_files": self.hit_files,
            "checkpoint_text": self.checkpoint_text,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(int(data["base_exponent"]), list(data.get("hit_files", [])),
                    data.get("checkpoint_text"))

    @classmethod
    def scan(cls, storage_path, base_exponent):
        const_dir = os.path.join(storage_path, f"10p{base_exponent}", "constellations")
        hit_files = []
        if os.path.isdir(const_dir):
            for k_name in os.listdir(const_dir):
                k_path = os.path.join(const_dir, k_name)
                if not _CONSTELLATION_K_RE.match(k_name) or not os.path.isdir(k_path):
                    continue
                for variant_name in os.listdir(k_path):
                    variant_path = os.path.join(k_path, variant_name)
                    if not _CONSTELLATION_VARIANT_RE.match(variant_name) or not os.path.isdir(variant_path):
                        continue
                    for fname in os.listdir(variant_path):
                        if _HITS_FILE_RE.match(fname):
                            hit_files.append(f"{k_name}/{variant_name}/{fname}")
        checkpoint_path = os.path.join(const_dir, "CHECKPOINT.txt")
        checkpoint_text = None
        if os.path.exists(checkpoint_path):
            try:
                with open(checkpoint_path, encoding="utf-8") as f:
                    checkpoint_text = f.read()
            except OSError:
                checkpoint_text = None
        return cls(base_exponent, hit_files, checkpoint_text)

    def missing_from(self, other):
        return sorted(set(self.hit_files) - set(other.hit_files))


class BackupManifest:
    """Full snapshot: every floor's PietroSnapshot + ConstellationSnapshot, plus a copy of
    benchmark_log.csv's raw text (small -- a few hundred rows even after months of use --
    safe to embed directly in the manifest JSON rather than as a separate file to keep
    track of)."""

    def __init__(self, timestamp_utc, storage_path, pietra, constellations, benchmark_csv_text):
        self.timestamp_utc = timestamp_utc
        self.storage_path = storage_path
        self.pietra = {p.base_exponent: p for p in pietra}
        self.constellations = {c.base_exponent: c for c in constellations}
        self.benchmark_csv_text = benchmark_csv_text

    @property
    def name(self):
        return f"backup_{self.timestamp_utc}"

    def to_dict(self):
        return {
            "timestamp_utc": self.timestamp_utc,
            "storage_path": self.storage_path,
            "pietra": [p.to_dict() for p in self.pietra.values()],
            "constellations": [c.to_dict() for c in self.constellations.values()],
            "benchmark_csv_text": self.benchmark_csv_text,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data["timestamp_utc"], data.get("storage_path", ""),
            [PietroSnapshot.from_dict(p) for p in data.get("pietra", [])],
            [ConstellationSnapshot.from_dict(c) for c in data.get("constellations", [])],
            data.get("benchmark_csv_text", ""),
        )

    @classmethod
    def build_from_disk(cls, storage_path):
        """Scans storage_path RIGHT NOW and builds a fresh manifest -- this is what
        "Backup" actually does (see backup_store.py.BackupStore.create()). Cheap: only
        os.listdir() calls, no per-file header reads (unlike the app's totals-cache worker,
        which needs actual prime counts -- a backup only needs to know WHICH files
        exist)."""
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Loaded ONCE here rather than per-floor inside PietroSnapshot.scan() -- it's one
        # root-level file shared by every floor, so re-reading it per floor would be pure
        # waste (same reasoning update_pietro_totals_cache's caller only loads it once per
        # app session, see prime_atlas_v1.py's _reload_totals_caches()).
        totals_cache = _load_json_best_effort(
            os.path.join(storage_path, TOTALS_CACHE_FILENAME)) or {}
        pietra = []
        constellations = []
        for base_exponent in sorted(_pietra_on_disk(storage_path)):
            pietra.append(PietroSnapshot.scan(storage_path, base_exponent, totals_cache))
            constellations.append(ConstellationSnapshot.scan(storage_path, base_exponent))
        csv_path = os.path.join(storage_path, "benchmark_log.csv")
        csv_text = ""
        if os.path.exists(csv_path):
            try:
                with open(csv_path, encoding="utf-8") as f:
                    csv_text = f.read()
            except OSError:
                csv_text = ""
        return cls(timestamp, storage_path, pietra, constellations, csv_text)

    def restore_floor_metadata(self, storage_path):
        """Writes back floor_meta.json rows (merged, not overwritten -- see
        floor_meta.merge_rows_into_floor_meta()'s own docstring for why), merges each
        floor's totals_cache_entry into the root .portal_totals_cache.json, and restores
        sieving_primes_count_cache.json, for every floor in this manifest. Called once at
        the START of a restore, right alongside BackupStore.restore_csv() (see
        settings_tab.py's _on_start_restore()).

        These three are pure speed-of-display caches, not data -- a totals_cache_entry
        that's briefly stale relative to files not yet regenerated self-heals the next
        time that floor is visited (update_pietro_totals_cache re-validates every
        filename's mtime against current disk state regardless of what this wrote), so
        this is safe to run BEFORE window regeneration rather than needing to wait for it.
        Best-effort per floor: one floor's write failing doesn't stop the others.

        Returns the number of floors whose metadata was actually written."""
        root_totals_cache = _load_json_best_effort(
            os.path.join(storage_path, TOTALS_CACHE_FILENAME)) or {}
        touched = 0
        for base_exponent, snap in self.pietra.items():
            wrote_any = False
            if snap.meta_rows:
                if floor_meta.merge_rows_into_floor_meta(
                        storage_path, base_exponent, snap.meta_rows):
                    wrote_any = True
            if snap.totals_cache_entry is not None:
                root_totals_cache[f"10p{base_exponent}"] = snap.totals_cache_entry
                wrote_any = True
            if snap.sieving_cache is not None:
                sieving_path = os.path.join(
                    storage_path, f"10p{base_exponent}", SIEVING_CACHE_FILENAME)
                if _save_json_atomic(sieving_path, snap.sieving_cache):
                    wrote_any = True
            if wrote_any:
                touched += 1
        _save_json_atomic(os.path.join(storage_path, TOTALS_CACHE_FILENAME), root_totals_cache)
        return touched

    def diff_against_disk(self, storage_path):
        """Compares this manifest against storage_path's CURRENT state. Returns
        {base_exponent: {"missing_windows": [...], "missing_hits": [...],
        "extra_windows": [...], "extra_hits": [...]}} for every floor that differs in
        EITHER direction -- an empty dict means the backup and the disk match exactly.
        Floors with nothing missing AND nothing extra are simply absent from the result,
        same reasoning as the benchmark aggregation elsewhere in this project: only
        including floors that actually have data.

        The comparison unions self.pietra's keys with EVERY floor folder actually on
        disk right now (_pietra_on_disk()), and computes BOTH directions for each:
        missing_from() (the backup has it, disk doesn't -- restore_job.py's
        regenerate-it path) and its mirror, current.missing_from(snap) (disk has it,
        backup doesn't -- the extra_windows/extra_hits fields, which the caller can
        offer to delete, always with an explicit confirm/cancel prompt -- see
        restore_job.py's delete_extra_files() and settings_tab.py's
        _on_start_restore()). This also covers a floor entirely absent from the
        backup (e.g. one added to the storage after the backup was taken, with no
        entry in self.pietra at all): its snapshot is treated as empty, so ALL of its
        files come back as extra_windows/extra_hits rather than being silently
        invisible to the diff."""
        result = {}
        all_base_exponents = set(self.pietra.keys()) | _pietra_on_disk(storage_path)
        for base_exponent in all_base_exponents:
            snap = self.pietra.get(base_exponent)
            current = PietroSnapshot.scan(storage_path, base_exponent)
            if snap is not None:
                missing_windows = snap.missing_from(current)
                extra_windows = current.missing_from(snap)
            else:
                missing_windows = []
                extra_windows = list(current.filenames)

            const_snap = self.constellations.get(base_exponent)
            current_const = ConstellationSnapshot.scan(storage_path, base_exponent)
            if const_snap is not None:
                missing_hits = const_snap.missing_from(current_const)
                extra_hits = current_const.missing_from(const_snap)
            else:
                missing_hits = []
                extra_hits = list(current_const.hit_files)

            if missing_windows or missing_hits or extra_windows or extra_hits:
                result[base_exponent] = {
                    "missing_windows": missing_windows,
                    "missing_hits": missing_hits,
                    "extra_windows": extra_windows,
                    "extra_hits": extra_hits,
                }
        return result
