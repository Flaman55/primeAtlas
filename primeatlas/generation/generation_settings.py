"""
generation_settings.py -- the Generation tab's form values in the remembered-fields store
(primeatlas/core/ui_state.py), one key per field ("generation.<section>.<field>"), merged
over DEFAULT_GENERATION_SETTINGS so a store from an older schema still yields every field.

The form's widgets save each change themselves (remember(..., restore=False)); the Run
handlers also save the values they parsed, which covers the pattern combos (k, variant,
strategy) in their canonical form. The values used to live per storage folder in
.portal_generation_settings.json: load_generation_settings() copies that file of the
storage folder it is given into the store once (MIGRATED_KEY), then never reads it again.
reset_checkpoint is never stored: a checkpoint reset applies to the run it is ticked for.
"""
import json
import os

from . import engine_options, engine_presets


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
        # Sieve engine and v5/v6 perf knobs -- see engine_options.py.
        "engine": engine_options.DEFAULT_ENGINE,
        **{key: str(value) for key, value in engine_options.DEFAULT_KNOBS.items()},
        **{engine_presets.preset_key(e): engine_presets.DEFAULT_PRESET
           for e in engine_presets.PRESET_ENGINES},
        # How many times faster pt1 with BPSW must be to be proposed -- engine_advisor.py.
        engine_options.ADVISOR_OFFSET_KEY: f"{engine_options.DEFAULT_BPSW_OFFSET:g}",
    },
    "constellation": {
        "base_exponent": "",  # blank = auto (every floor with source data -- see
                               # constellation_windows_v2_3.list_floors_with_data())
    },
    "verify": {
        "base_exponent": "",
        "width_exp": "7",     # windows of 10^7 numbers
        "threads": "Auto",    # the pipeline form's workers (verify_plan.resolve_threads)
        "method": "proof",    # verify_plan.METHOD_PROOF (pt1.1) or METHOD_SIEVE (v7.3)
        "pass_exp": "11",     # v7.3 passes of 10^11 numbers (verify_plan.DEFAULT_PASS_EXP)
    },
    "ktuple": {
        "base_exponent": "",
        "k": "",
        "variant_id": "",
        "n_locations": "1000",
        "window_m": "10000000",
        "strategy": "concentrated",  # see ktuple_sieve_v2_2.py's own module docstring for
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
                               # reset -- see ktuple_locations_v2_2.py's digit_sweep_locations()
                               # docstring (PATH VARIETY section)
    },
}


_KTUPLE_STRATEGY_KEYS = ["even", "concentrated", "manual_list", "manual_step", "digit_sweep"]

KEY_PREFIX = "generation"
MIGRATED_KEY = "generation._migrated_portal_settings"
NOT_STORED = {("ktuple", "reset_checkpoint")}


def generation_key(section, field):
    return f"{KEY_PREFIX}.{section}.{field}"


def _load_portal_file(portal_folder):
    """The legacy per-storage-folder file as {section: {field: value}}, or {} when it is
    missing or unreadable."""
    path = os.path.join(portal_folder, GENERATION_SETTINGS_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def migrate_portal_settings(store, portal_folder):
    """Copies the storage folder's .portal_generation_settings.json into `store` once per
    install; later calls, and the file of any other storage folder, are ignored."""
    if store.get(MIGRATED_KEY):
        return
    legacy = _load_portal_file(portal_folder) if portal_folder else {}
    for section, defaults in DEFAULT_GENERATION_SETTINGS.items():
        values = legacy.get(section)
        if not isinstance(values, dict):
            continue
        for field, value in values.items():
            if field in defaults and (section, field) not in NOT_STORED                     and not store.has(generation_key(section, field)):
                store.set(generation_key(section, field), value)
    store.set(MIGRATED_KEY, True)


def load_generation_settings(store, portal_folder=None):
    """{section: {field: value}}: DEFAULT_GENERATION_SETTINGS overlaid with the store's
    values, after migrating `portal_folder`'s legacy file when given. Never raises."""
    if portal_folder is not None:
        migrate_portal_settings(store, portal_folder)
    merged = {section: dict(values) for section, values in DEFAULT_GENERATION_SETTINGS.items()}
    for section, values in merged.items():
        for field in values:
            key = generation_key(section, field)
            if (section, field) not in NOT_STORED and store.has(key):
                values[field] = store.get(key)
    return merged


def save_generation_settings(store, settings):
    """Stores every field of `settings` ({section: {field: value}}) except NOT_STORED."""
    for section, values in settings.items():
        for field, value in values.items():
            if (section, field) not in NOT_STORED:
                store.set(generation_key(section, field), value)


def remember_generation_field(section, field, var, store=None, widget=None, choices=None):
    """Saves later changes of a form widget whose value came from load_generation_settings()."""
    from primeatlas.core.ui_state import remember
    return remember(generation_key(section, field), var, store=store, restore=False,
                    widget=widget, choices=choices)
