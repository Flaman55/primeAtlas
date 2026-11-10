"""Sieve engine choice and perf knobs of the Generation tab: parsing, run sizing, launch env.

The engine (v4.1, v5, v6, v7 or pt1) and its knobs are form fields persisted in the Generation
settings' "loop" section. They reach the WSL side as environment variables in front of the
launched command (see generation.build_wsl_logged_command()): orchestrator_v3.py reads
PRIMEATLAS_SCANNER_VERSION, prime_sieve_v5_2.py the PRIMEATLAS_V5_* knobs through
work_plan_v5.py, prime_sieve_v6_1.py the PRIMEATLAS_V6_* knobs through work_plan_v6.py,
prime_sieve_v7_2.py the PRIMEATLAS_V7_* knobs through work_plan_v7_2.py, prime_sieve_pt1.py
the PRIMEATLAS_PT1_* knobs through pt1_plan.py. v5, v6 and v7 have separate knob sets: their best values differ. The same variables are the command-line interface for
runs started by hand. The RAM budget knob (percent of the RAM free in WSL that a run may
use) only sizes the run on this side (recommend()); no engine reads it, so it has no
environment variable. ENGINE_VERSIONS is the code version each engine name runs (shown next
to the selector); the names stay what benchmark_log.csv and the storage folder record.

Names and defaults mirror orchestrator_v3.py, work_plan_v5/_v6/_v7_2.py, pt1_plan.py
and run_budget.py instead of importing the engine modules: this module runs in the native
Windows GUI, which must not pull in the WSL-only engine imports.
unitTests/test_engine_options.py keeps them equal.
"""
from collections import namedtuple

from . import engine_presets, run_budget

ENGINE_V41 = run_budget.ENGINE_V41
ENGINE_V5 = run_budget.ENGINE_V5
ENGINE_V6 = run_budget.ENGINE_V6
ENGINE_V7 = run_budget.ENGINE_V7
ENGINE_PT1 = run_budget.ENGINE_PT1
ENGINES = (ENGINE_V41, ENGINE_V5, ENGINE_V6, ENGINE_V7, ENGINE_PT1)
DEFAULT_ENGINE = ENGINE_V6
BUCKETED_ENGINES = run_budget.BUCKETED_ENGINES
ENGINE_VERSIONS = {ENGINE_V41: "v4.1", ENGINE_V5: "v5.2", ENGINE_V6: "v6.1", ENGINE_V7: "v7.2",
                   ENGINE_PT1: "pt1"}

SCANNER_VERSION_ENV = "PRIMEATLAS_SCANNER_VERSION"
PT1_B_ENV = "PRIMEATLAS_PT1_B"
PT1_CHUNK_KB_ENV = "PRIMEATLAS_PT1_CHUNK_KB"

RAM_BUDGET_KNOB = "ram_budget_pct"


# v5.2, v6 and v7 write their windows with a thread pool (parallel_window_writer.py).
_DEFAULT_WRITE_THREADS = 8


def _bucketed_knobs(engine):
    return (f"{engine}_segment_kb", f"{engine}_region_kb", f"{engine}_bucket_mb",
            f"{engine}_windows_at_25", f"{engine}_pieces_per_thread",
            f"{engine}_write_threads")


# v7's jump gear (work_plan_v7_2.py): threshold in percent of the cost model (0 = off), the
# model's block and landing costs, block length factor (percent), gear span in percent of the
# model's optimum (0 = the buffer span).
_V7_JUMP_KNOBS = ("v7_jump_model_pct", "v7_jump_block_cost", "v7_jump_landing_cost_pct",
                  "v7_jump_block_pct", "v7_gear_span_pct")

# Per bucketed engine: knob -> environment variable (work_plan_v5/_v6/_v7_2.py). The
# windows-at-25 knob only sizes the run on this side, so it has none.
KNOB_ENVS = {
    engine: {f"{engine}_{knob}": f"PRIMEATLAS_{engine.upper()}_{knob.upper()}"
             for knob in ("segment_kb", "region_kb", "bucket_mb", "pieces_per_thread",
                          "write_threads")
             + (tuple(k[len("v7_"):] for k in _V7_JUMP_KNOBS) if engine == ENGINE_V7 else ())}
    for engine in BUCKETED_ENGINES
}
_PT1_KNOBS = ("pt1_b", "pt1_chunk_kb")
# pt1's footprint does not grow with the window count, so the RAM budget never limits it.
_ENGINE_KNOBS = {
    ENGINE_V41: (RAM_BUDGET_KNOB,),
    ENGINE_V5: _bucketed_knobs(ENGINE_V5) + (RAM_BUDGET_KNOB,),
    ENGINE_V6: _bucketed_knobs(ENGINE_V6) + (RAM_BUDGET_KNOB,),
    ENGINE_V7: _bucketed_knobs(ENGINE_V7) + _V7_JUMP_KNOBS + (RAM_BUDGET_KNOB,),
    ENGINE_PT1: _PT1_KNOBS,
}
KNOB_KEYS = (_bucketed_knobs(ENGINE_V5) + _bucketed_knobs(ENGINE_V6)
             + _bucketed_knobs(ENGINE_V7) + _V7_JUMP_KNOBS + _PT1_KNOBS
             + (RAM_BUDGET_KNOB,))
# Settings keys the form persists next to the engine: the knobs and each bucketed engine's
# knob profile (engine_presets.py).
PERSISTED_KEYS = KNOB_KEYS + tuple(engine_presets.preset_key(e)
                                   for e in engine_presets.PRESET_ENGINES)
DEFAULT_KNOBS = {
    **{key: value for engine in BUCKETED_ENGINES
       for key, value in zip(_bucketed_knobs(engine),
                             (2048, 1024, run_budget.DEFAULT_BUCKET_MB,
                              run_budget.DEFAULT_TARGET_WINDOWS_AT_25[engine], 16,
                              _DEFAULT_WRITE_THREADS))},
    "pt1_b": 0,             # 0 = floor(N^(1/4)) of the run's top
    "pt1_chunk_kb": 4096,
    "v7_jump_model_pct": 100,        # p* = the cost model's; 0 = gear off
    "v7_jump_block_cost": 300,       # a: one block setup, in classic primes
    "v7_jump_landing_cost_pct": 10,  # b = 0.10: one landing, in classic primes
    "v7_jump_block_pct": 50,
    "v7_gear_span_pct": 100,         # gear span = the model's optimum V*; 0 = buffer span
    RAM_BUDGET_KNOB: round(run_budget.DEFAULT_SAFETY_FRACTION * 100),
}
_ZERO_ALLOWED = {"pt1_b", "v7_jump_model_pct", "v7_jump_landing_cost_pct",
                 "v7_gear_span_pct"}
PT1_MAX_B = 2 ** 32 - 1
_MAX_VALUES = {"pt1_b": PT1_MAX_B, RAM_BUDGET_KNOB: 100}

# Input ceiling of one run's window count. v4.1 gains nothing from longer tapes; for v5 and
# v6 the RAM budget is the real limit (1e12 numbers take 62.5 GB in v5, 33 GB in v6); pt1
# has no fixed cost to amortize and no run-sized buffer, the cap only bounds one run's
# duration.
MAX_WINDOWS_PER_RUN = {ENGINE_V41: 1000, ENGINE_V5: 100_000, ENGINE_V6: 100_000,
                       ENGINE_V7: 100_000,
                       ENGINE_PT1: 100_000}

EngineChoice = namedtuple("EngineChoice", "engine knobs")


def normalize_engine(value):
    """The engine name, or DEFAULT_ENGINE for anything not in ENGINES."""
    value = str(value).strip() if value is not None else ""
    return value if value in ENGINES else DEFAULT_ENGINE


def engine_knob_keys(engine):
    """The KNOB_KEYS `engine` reads."""
    return _ENGINE_KNOBS[normalize_engine(engine)]


def _parse_positive(raw, zero_allowed=False):
    lowest = 0 if zero_allowed else 1
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw if raw >= lowest else None
    text = str(raw).strip()
    return int(text) if text.isdigit() and int(text) >= lowest else None


def parse_knobs(raw):
    """(knobs, None) with every KNOB_KEYS value as a positive int (pt1_b: 0 or more, at
    most PT1_MAX_B; ram_budget_pct: at most 100; blank or missing -> default), or
    (None, key) naming the first invalid value."""
    knobs = {}
    for key in KNOB_KEYS:
        value = raw.get(key)
        if value is None or str(value).strip() == "":
            knobs[key] = DEFAULT_KNOBS[key]
            continue
        parsed = _parse_positive(value, key in _ZERO_ALLOWED)
        if parsed is not None and parsed > _MAX_VALUES.get(key, parsed):
            parsed = None
        if parsed is None:
            return None, key
        knobs[key] = parsed
    return knobs, None


def resolve(loop_settings, windows=None):
    """EngineChoice from persisted settings; never fails: a bad knob gets its default. The
    selected engine's knob profile (engine_presets.py, auto when unset) replaces its profile
    knobs; auto picks by `windows` per run (None = not known yet)."""
    knobs = {}
    for key in KNOB_KEYS:
        parsed, bad = parse_knobs({key: loop_settings.get(key)})
        knobs[key] = parsed[key] if bad is None else DEFAULT_KNOBS[key]
    engine = normalize_engine(loop_settings.get("engine"))
    preset = loop_settings.get(engine_presets.preset_key(engine))
    return EngineChoice(engine, engine_presets.apply_preset(engine, preset, windows, knobs))


def max_windows_per_run(engine):
    return MAX_WINDOWS_PER_RUN[normalize_engine(engine)]


def recommend(available_ram_bytes, choice, base_exponent, window_m):
    """run_budget.RunBudget for one run with this engine and knobs, capped at
    max_windows_per_run() and fitted into ram_budget_pct percent of available_ram_bytes;
    None without a RAM reading. An unknown floor (None) sizes the run like a shallow
    floor."""
    floor = base_exponent if base_exponent is not None else 0
    own = choice.engine if choice.engine in BUCKETED_ENGINES else ENGINE_V5
    return run_budget.recommend_run(
        available_ram_bytes, choice.engine, floor, window_m,
        bucket_mb=choice.knobs[f"{own}_bucket_mb"],
        target_at_25=choice.knobs[f"{own}_windows_at_25"],
        safety_fraction=choice.knobs[RAM_BUDGET_KNOB] / 100,
        max_windows=max_windows_per_run(choice.engine))


def bucket_knob(engine):
    """The bucket-memory knob of a bucketed engine (v5, v6, v7), None for the others."""
    return f"{engine}_bucket_mb" if engine in BUCKETED_ENGINES else None


def launch_env(choice, bucket_mb=None):
    """[(name, value)] to set in front of an orchestrator launch: always the engine, plus
    the engine's own segment, region, bucket, pieces-per-thread and write-thread knobs for
    v5, v6 and v7 (v7 also its jump gear's four), or B and the chunk size for pt1. bucket_mb lowers the bucket knob (a RAM-reduced
    recommendation); it never raises it above the knob's value."""
    env = [(SCANNER_VERSION_ENV, choice.engine)]
    if choice.engine == ENGINE_PT1:
        env += [(PT1_B_ENV, str(choice.knobs["pt1_b"])),
                (PT1_CHUNK_KB_ENV, str(choice.knobs["pt1_chunk_kb"]))]
    if choice.engine in BUCKETED_ENGINES:
        values = dict(choice.knobs)
        if bucket_mb is not None:
            key = bucket_knob(choice.engine)
            values[key] = min(bucket_mb, values[key])
        env += [(name, str(values[key])) for key, name in KNOB_ENVS[choice.engine].items()]
    return env
