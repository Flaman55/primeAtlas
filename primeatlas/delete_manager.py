"""
delete_manager.py -- PortalWiper, deletes an ENTIRE portal storage location: every
10p{N} floor folder (source windows + constellations), and truncates benchmark_log.csv
back to just its header. Deliberately does NOT touch _backups/ -- backups are the whole
point of offering this button safely at all.

Also FloorWiper, for two narrower, per-floor variants of the same idea -- Artur,
2026-08-17, asked for the Settings tab's delete section to offer these alongside the
whole-storage wipe, since sometimes only ONE floor needs clearing (to force a clean
re-generation) or only that floor's constellation hits need clearing (to re-run
constellation_finder_v1.py against an unchanged pattern catalog, or a changed one,
without touching the -- expensive to regenerate -- prime data underneath it):
  - delete_floor(): removes the WHOLE 10p{N} folder (source_primes AND constellations
    together, since they live under the same directory) plus that floor's own rows
    from benchmark_log.csv.
  - delete_constellations(): removes ONLY 10p{N}/constellations/, leaving
    10p{N}/source_primes/ (and that floor's benchmark_log.csv rows, which are about
    prime generation, not constellation-finding) untouched.

The warning/confirmation dialogs themselves live in settings_tab.py (needs tkinter);
this module is the pure logic behind them -- plan() for what a dialog should show,
execute() for what OK actually does. A destructive wipe action is only offered behind
an explicit warning and a recommendation to back up first.
"""
import os
import shutil
import re
import csv

_PIETRO_DIR_RE = re.compile(r"^10p(\d+)$")
_SOURCE_WINDOW_RE = re.compile(r"^PRIME_WINDOW_10p\d+_off_(\d+)(M)?\.bin$")
_CONSTELLATION_K_RE = re.compile(r"^k(\d+)$")
_CONSTELLATION_VARIANT_RE = re.compile(r"^variant(\d+)$")
_HITS_FILE_RE = re.compile(r"^HITS_10p\d+_k\d+_v\d+\.bin$")


class PortalWiper:
    def __init__(self, storage_path):
        self.storage_path = storage_path

    def plan(self):
        """Dry-run: what WOULD be deleted, for the confirmation dialog. Returns
        (pietro_names, benchmark_row_count) without touching anything on disk."""
        pietra = []
        if os.path.isdir(self.storage_path):
            for name in os.listdir(self.storage_path):
                if _PIETRO_DIR_RE.match(name) and os.path.isdir(os.path.join(self.storage_path, name)):
                    pietra.append(name)
        pietra.sort()
        csv_path = os.path.join(self.storage_path, "benchmark_log.csv")
        row_count = 0
        if os.path.exists(csv_path):
            try:
                with open(csv_path, newline="", encoding="utf-8") as f:
                    row_count = sum(1 for _ in csv.DictReader(f))
            except OSError:
                row_count = 0
        return pietra, row_count

    def execute(self):
        """Actually deletes. Returns (deleted_pietra, errors) -- best-effort: a single
        locked/undeletable file shouldn't abort the whole wipe, it just gets reported so
        the caller can show the user what didn't go through."""
        pietra, _ = self.plan()
        deleted = []
        errors = []
        for name in pietra:
            path = os.path.join(self.storage_path, name)
            try:
                shutil.rmtree(path)
                deleted.append(name)
            except OSError as e:
                errors.append(f"{name}: {e}")

        csv_path = os.path.join(self.storage_path, "benchmark_log.csv")
        if os.path.exists(csv_path):
            try:
                with open(csv_path, newline="", encoding="utf-8") as f:
                    header = next(csv.reader(f), None)
                if header is not None:
                    tmp_path = f"{csv_path}.tmp{os.getpid()}"
                    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
                        csv.writer(f).writerow(header)
                    os.replace(tmp_path, csv_path)
            except OSError as e:
                errors.append(f"benchmark_log.csv: {e}")

        return deleted, errors


def _prune_benchmark_csv_rows(storage_path, base_exponent):
    """Removes every benchmark_log.csv row whose own base_exponent column matches the
    just-deleted floor, keeping every other floor's history intact -- the "row_count"
    PortalWiper.plan() reports for a FULL wipe is the whole file's row count because the
    whole file gets truncated to just its header; a single-floor delete needs the
    narrower, filtered version instead, so a floor's stale benchmark history doesn't
    keep showing up in the Benchmark tab after its data is gone. No-op (returns 0) if
    the CSV doesn't exist or doesn't have a "base_exponent" column at all -- an older or
    hand-edited CSV shouldn't raise here, just leave rows exactly as they were."""
    csv_path = os.path.join(storage_path, "benchmark_log.csv")
    if not os.path.exists(csv_path):
        return 0
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if not fieldnames or "base_exponent" not in fieldnames:
                return 0
            kept_rows = []
            removed = 0
            for row in reader:
                if row.get("base_exponent") == str(base_exponent):
                    removed += 1
                else:
                    kept_rows.append(row)
        if removed:
            tmp_path = f"{csv_path}.tmp{os.getpid()}"
            with open(tmp_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(kept_rows)
            os.replace(tmp_path, csv_path)
        return removed
    except OSError:
        return 0


class FloorWiper:
    """Two narrower, per-floor counterparts to PortalWiper -- see this module's own
    docstring for the delete_floor()/delete_constellations() distinction. Both share
    the same plan()-then-execute() shape (dry-run counts for the confirmation dialog,
    then the actual delete), same reasoning as PortalWiper."""

    def __init__(self, storage_path):
        self.storage_path = storage_path

    def list_floors(self):
        """Every base_exponent with a 10p{N} folder present right now, sorted ascending
        -- feeds the floor-picker in the Settings tab's delete section."""
        found = []
        if os.path.isdir(self.storage_path):
            for name in os.listdir(self.storage_path):
                m = _PIETRO_DIR_RE.match(name)
                if m and os.path.isdir(os.path.join(self.storage_path, name)):
                    found.append(int(m.group(1)))
        return sorted(found)

    def plan_floor(self, base_exponent):
        """Dry-run for delete_floor(): (window_count, hit_count) currently under
        10p{base_exponent}, without touching anything on disk."""
        floor_dir = os.path.join(self.storage_path, f"10p{base_exponent}")
        source_dir = os.path.join(floor_dir, "source_primes")
        window_count = 0
        if os.path.isdir(source_dir):
            window_count = sum(
                1 for n in os.listdir(source_dir) if _SOURCE_WINDOW_RE.match(n))
        hit_count = self._count_hits(floor_dir)
        return window_count, hit_count

    def execute_delete_floor(self, base_exponent):
        """Deletes 10p{base_exponent} entirely (source_primes AND constellations
        together -- they share that one directory) plus that floor's own
        benchmark_log.csv rows. Returns (ok, error) -- ok=False with error=None means
        "nothing there to delete" (not itself an error, just a no-op); error is set
        only for an actual OSError during the rmtree."""
        floor_dir = os.path.join(self.storage_path, f"10p{base_exponent}")
        if not os.path.isdir(floor_dir):
            return False, None
        try:
            shutil.rmtree(floor_dir)
        except OSError as e:
            return False, str(e)
        _prune_benchmark_csv_rows(self.storage_path, base_exponent)
        return True, None

    def plan_constellations(self, base_exponent):
        """Dry-run for delete_constellations(): hit_count currently under
        10p{base_exponent}/constellations/, without touching anything on disk."""
        floor_dir = os.path.join(self.storage_path, f"10p{base_exponent}")
        return self._count_hits(floor_dir)

    def execute_delete_constellations(self, base_exponent):
        """Deletes ONLY 10p{base_exponent}/constellations/ -- source_primes/ (and that
        floor's benchmark_log.csv rows, which describe prime generation, not
        constellation-finding) are left untouched. Returns (ok, error), same contract
        as execute_delete_floor()."""
        const_dir = os.path.join(
            self.storage_path, f"10p{base_exponent}", "constellations")
        if not os.path.isdir(const_dir):
            return False, None
        try:
            shutil.rmtree(const_dir)
        except OSError as e:
            return False, str(e)
        return True, None

    @staticmethod
    def _count_hits(floor_dir):
        const_dir = os.path.join(floor_dir, "constellations")
        count = 0
        if not os.path.isdir(const_dir):
            return count
        for k_name in os.listdir(const_dir):
            k_path = os.path.join(const_dir, k_name)
            if not _CONSTELLATION_K_RE.match(k_name) or not os.path.isdir(k_path):
                continue
            for variant_name in os.listdir(k_path):
                variant_path = os.path.join(k_path, variant_name)
                if (not _CONSTELLATION_VARIANT_RE.match(variant_name)
                        or not os.path.isdir(variant_path)):
                    continue
                count += sum(
                    1 for fname in os.listdir(variant_path) if _HITS_FILE_RE.match(fname))
        return count
