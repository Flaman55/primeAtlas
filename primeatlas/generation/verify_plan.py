"""
verify_plan.py -- the fields of the Generation tab's Section D (verification P -> D) turned
into pt1_verify_store.py's arguments: floor, window width as a power of ten, how many of the
floor's P windows to prove and the thread count. No tkinter here.

The window count is read from the store: the floor's P windows on the width's grid
(storage_kinds.p_windows_on_grid()), so the field starts at "all of them" and a smaller value
proves only the first ones. Threads: Auto takes the pipeline form's workers (the thread count
pt1 sieves with), Max the CPUs WSL reports, or a number.
"""
import storage_kinds

THREADS_AUTO = "Auto"
THREADS_MAX = "Max"
THREADS_CAP = 256
THREAD_CHOICES = [THREADS_AUTO, THREADS_MAX] + [str(n) for n in range(1, THREADS_CAP + 1)]
WIDTH_EXP_MIN = 1
WIDTH_EXP_MAX = 12


def parse_int(text, minimum):
    """A whole number >= minimum typed in a field, None for anything else."""
    text = (text or "").strip()
    if not text.isdigit() or int(text) < minimum:
        return None
    return int(text)


def window_count(portal_folder, base_exponent, width_exp):
    """How many P windows of width 10^width_exp the floor's store holds; 0 when the floor
    or the width is not a valid number."""
    if base_exponent is None or width_exp is None or not portal_folder:
        return 0
    return len(storage_kinds.p_windows_on_grid(portal_folder, base_exponent,
                                               10 ** width_exp))


def max_windows_arg(text, total):
    """pt1_verify_store.py's max_windows from the Windows field: 0 (all) for the total or
    more, the typed count below it, None for an invalid field."""
    count = parse_int(text, 1)
    if count is None:
        return None
    return 0 if count >= total else count


def resolve_threads(text, form_workers, wsl_cpu_count):
    """The thread count of the Threads field: Auto -> form_workers (the pipeline form's
    workers field as typed), Max -> wsl_cpu_count (None when the probe failed), else a
    whole number in [1, THREADS_CAP]. None when it cannot be resolved."""
    text = (text or "").strip()
    if text.lower() == THREADS_AUTO.lower():
        return parse_int(form_workers, 1)
    if text.lower() == THREADS_MAX.lower():
        return min(wsl_cpu_count, THREADS_CAP) if wsl_cpu_count else None
    count = parse_int(text, 1)
    return count if count is not None and count <= THREADS_CAP else None
