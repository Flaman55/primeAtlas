"""
verify_plan.py -- the fields of the Generation tab's Section D (verification P -> D) turned
into the store verifiers' arguments: the method (the pt1.1 proof, pt1_verify_store.py, or the
v7.3 sieve, v73_verify_store.py), the floor and the thread count. The island and the width of
the verification windows live in verify_width.py. No tkinter here.

Threads: Auto takes the pipeline form's workers (the thread count pt1 sieves with), Max the
CPUs WSL reports, or a number.
"""
import run_verify

from . import wsl_resources
from ..core.number_text import plain_number

THREADS_AUTO = "Auto"
THREADS_MAX = wsl_resources.WORKERS_MAX
THREADS_CAP = 256
METHOD_PROOF = run_verify.METHOD_PROOF
METHOD_SIEVE = run_verify.METHOD_SIEVE
METHODS = run_verify.METHODS


def parse_int(text, minimum):
    """A whole number >= minimum typed in a field (any notation), None for anything else."""
    text = plain_number(text)
    if not text.isdigit() or int(text) < minimum:
        return None
    return int(text)


def resolve_threads(text, form_workers, wsl_cpu_count):
    """The thread count of the Threads field: Auto -> form_workers (the pipeline form's
    workers field, its Max resolved by wsl_cpu_count), Max -> wsl_cpu_count (None when the probe failed), else a
    whole number in [1, THREADS_CAP]. None when it cannot be resolved."""
    text = plain_number(text, words=(THREADS_AUTO, THREADS_MAX))
    if text.lower() == THREADS_AUTO.lower():
        workers = wsl_resources.resolve_workers(form_workers, wsl_cpu_count)
        return min(workers, THREADS_CAP) if workers else None
    if text.lower() == THREADS_MAX.lower():
        return min(wsl_cpu_count, THREADS_CAP) if wsl_cpu_count else None
    count = parse_int(text, 1)
    return count if count is not None and count <= THREADS_CAP else None
