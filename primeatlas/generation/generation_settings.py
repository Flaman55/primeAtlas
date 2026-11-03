"""
generation_settings.py -- persistence of the Generation tab's form values
(.portal_generation_settings.json in the storage folder), merged over
DEFAULT_GENERATION_SETTINGS so a file from an older schema still yields every key.
"""
import json
import os

from . import engine_options


GENERATION_SETTINGS_FILENAME = ".portal_generation_settings.json"

# Mirrors orchestrator_loop_v2.py's own module-level defaults (WINDOW_COUNT_PER_RUN=1000,
# WORKERS=24, BATCHES_PER_WORKER=2). Duplicated here (not imported) rather than importing
# orchestrator_loop_v2 directly, because that module requires WSL/ctypes to actually RUN
# (prime_sieve_v3.py, three hops down its import chain, ctypes-loads a Linux .so) -- this
# native-Windows tkinter app must never gain that dependency just to read a constant. If
# those scripts' defaults ever change, update both places.
DEFAULT_GENERATION_SETTINGS = {
    "loop": {
        "base_exponent": "20",
        "run_count": "1",
        "n_instances": "2",
        "write_files": True,
        "compute_sieving_primes_count": False,
        "use_known_pi_seed": False,
        "window_count_per_run": "1000",
        "workers": "24",
        "batches_per_worker": "2",
        "window_m": "10000000",  # mirrors orchestrator_loop_helpers.py's own
                                  # WINDOW_M -- see build_loop_argv()'s docstring for the
                                  # cross-floor-consistency caveat before changing this.
        # Sieve engine and v5 perf knobs -- see engine_options.py.
        "engine": engine_options.DEFAULT_ENGINE,
        **{key: str(value) for key, value in engine_options.DEFAULT_KNOBS.items()},
    },
    "constellation": {
        "base_exponent": "",  # blank = auto (every floor with source data -- see
                               # constellation_finder_v2_1.list_floors_with_data())
    },
    "ktuple": {
        "base_exponent": "",
        "k": "",
        "variant_id": "",
        "n_locations": "1000",
        "window_m": "10000000",
        "strategy": "concentrated",  # see ktuple_sieve_v2.py's own module docstring for
                                      # what each strategy means
        "step": "",  # blank = auto-computed per strategy (required for manual_step)
        "fragment_width": "",  # blank = auto-sized from Hardy-Littlewood density
        "fragment_start": "0",  # only used the first time (no checkpoint yet) or after
                                 # a reset -- every run after that continues from the
                                 # checkpoint regardless of this field
        "manual_offsets": "",  # space/comma-separated ints, strategy=manual_list only
        "deep_prime_limit": "2000",
        "mr_rounds": "40",
        "reset_checkpoint": False,
        "pass_counter": "0",  # strategy=digit_sweep only -- starting pass (0, 1, 2, ...)
                               # used only when no checkpoint exists yet or after a
                               # reset -- see ktuple_sieve_v2.py's digit_sweep_locations()
                               # docstring (PATH VARIETY section)
    },
}


_KTUPLE_STRATEGY_KEYS = ["even", "concentrated", "manual_list", "manual_step", "digit_sweep"]


def _generation_settings_path(portal_folder):
    return os.path.join(portal_folder, GENERATION_SETTINGS_FILENAME)


def load_generation_settings(portal_folder):
    """Returns the persisted Generation-tab form values, merged over
    DEFAULT_GENERATION_SETTINGS so a settings file saved before some field existed (schema
    grew since) or a missing/corrupt file still yields a complete dict with every key
    present -- same defensive shape as load_totals_cache(). Never raises."""
    merged = {section: dict(values) for section, values in DEFAULT_GENERATION_SETTINGS.items()}
    path = _generation_settings_path(portal_folder)
    if not os.path.exists(path):
        return merged
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return merged
    if not isinstance(data, dict):
        return merged
    for section, values in merged.items():
        loaded = data.get(section)
        if isinstance(loaded, dict):
            values.update(loaded)
    return merged


def save_generation_settings(portal_folder, settings):
    """Atomic write (temp file + os.replace()), same pattern as save_totals_cache()."""
    path = _generation_settings_path(portal_folder)
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(portal_folder, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError:
        pass  # best-effort -- a failed settings save just means the next launch reuses
              # whatever was last persisted (or the defaults, if nothing ever saved)
