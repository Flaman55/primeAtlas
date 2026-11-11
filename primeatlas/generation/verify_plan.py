"""
verify_plan.py -- the fields of the Generation tab's Section D (verification P -> D) turned
into the store verifiers' arguments: the method (the pt1.1 proof, pt1_verify_store.py, or the
v7.3 sieve, v73_verify_store.py), floor, window width as a power of ten, how many of the
floor's P windows to prove, the thread count and the v7.3 sieve's pass width as a power of
ten. No tkinter here.

The window count is read from the store: the floor's P windows on the width's grid
(storage_kinds.p_windows_on_grid()), so the field starts at "all of them" and a smaller value
proves only the first ones. Threads: Auto takes the pipeline form's workers (the thread count
pt1 sieves with), Max the CPUs WSL reports, or a number. The v7.3 passes are counted the way
the script cuts them (store_verify.passes()), for the time estimate (verify_estimate.py).
The method and the pass width also serve the verification after a pt1 run (run_verify.py,
pass_exp()).
"""
import run_verify
import storage_kinds
import store_verify

THREADS_AUTO = "Auto"
THREADS_MAX = "Max"
THREADS_CAP = 256
THREAD_CHOICES = [THREADS_AUTO, THREADS_MAX] + [str(n) for n in range(1, THREADS_CAP + 1)]
WIDTH_EXP_MIN = 1
WIDTH_EXP_MAX = 12
METHOD_PROOF = run_verify.METHOD_PROOF
METHOD_SIEVE = run_verify.METHOD_SIEVE
METHODS = run_verify.METHODS
# 10^11 numbers per pass: a ~3.3 GB wheel buffer (run_verify.DEFAULT_PASS_NUMBERS).
DEFAULT_PASS_EXP = 11


def parse_int(text, minimum):
    """A whole number >= minimum typed in a field, None for anything else."""
    text = (text or "").strip()
    if not text.isdigit() or int(text) < minimum:
        return None
    return int(text)


def pass_exp(text):
    """The v7.3 pass exponent of the Pass field: n in [WIDTH_EXP_MIN, WIDTH_EXP_MAX],
    DEFAULT_PASS_EXP for anything else."""
    exp = parse_int(text, WIDTH_EXP_MIN)
    return exp if exp is not None and exp <= WIDTH_EXP_MAX else DEFAULT_PASS_EXP


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


def pass_widths(offsets, window_m, pass_numbers):
    """The numbers of each v7.3 pass over the windows at `offsets` (ascending)."""
    window_list = [(offset, None) for offset in offsets]
    return [len(items) * window_m
            for items in store_verify.passes(window_list, window_m, pass_numbers)]


def store_passes(portal_folder, base_exponent, width_exp, max_windows, pass_exp):
    """pass_widths() of the floor's P windows at width 10^width_exp, the first max_windows of
    them (0: all); [] when a field is not a valid number."""
    if None in (base_exponent, width_exp, pass_exp) or not portal_folder:
        return []
    window_m = 10 ** width_exp
    window_list = store_verify.windows(portal_folder, base_exponent, window_m, max_windows)
    return pass_widths([offset for offset, _p in window_list], window_m, 10 ** pass_exp)
