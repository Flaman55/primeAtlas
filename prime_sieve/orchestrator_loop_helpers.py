"""
orchestrator_loop_helpers.py -- the 4 symbols orchestrator_loop_v2.py actually uses
(find_auto_start, WINDOW_M, _parse_bool_arg, ensure_benchmark_log_schema), extracted into
their own tiny, dependency-free module.

This self-contained app copy of the pipeline doesn't need to import a full orchestrator
module (with its own scanning/CLI logic and ctypes sieve-engine dependency) just to reach
four small helper functions, so they live here instead as a standalone extraction.
ensure_benchmark_log_schema (and BENCHMARK_FIELDNAMES) are re-exported from
benchmark_log_schema.py, shared with every engine.

If a bug is ever found in find_auto_start or _parse_bool_arg, the equivalent logic in the
full orchestrator module(s) elsewhere in the project likely needs the same fix.
"""
import os

import storage_kinds
from benchmark_log_schema import BENCHMARK_FIELDNAMES, ensure_benchmark_log_schema  # noqa: F401


def _parse_bool_arg(value):
    """Parses a CLI flag as a boolean. Primary form: 0/1 -- quicker to type on the WSL
    command line than true/false. Also accepts true/false/yes/no/on/off (case-insensitive)
    if you'd rather spell it out. Raises ValueError on anything else, so a typo in the WSL
    invocation fails loudly instead of silently picking the wrong mode."""
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected 0/1 (or true/false, yes/no, on/off) for auto mode, got: {value!r}")


def find_auto_start(base_exponent, portal_folder, window_m, engine=None):
    """The target_idx right AFTER the highest window `engine` already counts as done on
    this floor (storage_kinds.engine_target_idxs(): the store that engine writes into), or
    None if there is none (caller should then use the fallback). engine defaults to
    PRIMEATLAS_SCANNER_VERSION, as orchestrator_v3.py's SCANNER_VERSION does."""
    if engine is None:
        engine = os.environ.get("PRIMEATLAS_SCANNER_VERSION") or "v5"
    idxs = storage_kinds.engine_target_idxs(portal_folder, base_exponent, window_m, engine)
    return max(idxs) + 1 if idxs else None


WINDOW_M = 10 ** 7
