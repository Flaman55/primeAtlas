"""Sieve engine choice and perf knobs of the Generation tab: parsing, run sizing, launch env.

The engine (v4.1, v5 or pt1) and its knobs are form fields persisted in the Generation
settings' "loop" section. They reach the WSL side as environment variables in front of the
launched command (see generation.build_wsl_logged_command()): orchestrator_v3.py reads
PRIMEATLAS_SCANNER_VERSION, prime_sieve_v5.py reads the PRIMEATLAS_V5_* knobs through
work_plan_v5.py, prime_sieve_pt1.py the PRIMEATLAS_PT1_* knobs through pt1_plan.py. The
same variables are the command-line interface for runs started by hand. The RAM budget
knob (percent of the RAM free in WSL that a run may use) only sizes the run on this side
(recommend()); no engine reads it, so it has no environment variable.

Names and defaults mirror orchestrator_v3.py, work_plan_v5.py, pt1_plan.py and run_budget.py instead of
importing the engine modules: this module runs in the native Windows GUI, which must not
pull in the WSL-only engine imports. unitTests/test_engine_options.py keeps them equal.
"""
from collections import namedtuple

from . import run_budget

ENGINE_V41 = run_budget.ENGINE_V41
ENGINE_V5 = run_budget.ENGINE_V5
ENGINE_PT1 = run_budget.ENGINE_PT1
ENGINES = (ENGINE_V41, ENGINE_V5, ENGINE_PT1)
DEFAULT_ENGINE = ENGINE_V5

SCANNER_VERSION_ENV = "PRIMEATLAS_SCANNER_VERSION"
SEGMENT_KB_ENV = "PRIMEATLAS_V5_SEGMENT_KB"
REGION_KB_ENV = "PRIMEATLAS_V5_REGION_KB"
BUCKET_MB_ENV = "PRIMEATLAS_V5_BUCKET_MB"
PT1_B_ENV = "PRIMEATLAS_PT1_B"
PT1_CHUNK_KB_ENV = "PRIMEATLAS_PT1_CHUNK_KB"

RAM_BUDGET_KNOB = "ram_budget_pct"
_V5_OWN_KNOBS = ("v5_segment_kb", "v5_region_kb", "v5_bucket_mb", "v5_windows_at_25")
_PT1_KNOBS = ("pt1_b", "pt1_chunk_kb")
# pt1's footprint does not grow with the window count, so the RAM budget never limits it.
_ENGINE_KNOBS = {
    ENGINE_V41: (RAM_BUDGET_KNOB,),
    ENGINE_V5: _V5_OWN_KNOBS + (RAM_BUDGET_KNOB,),
    ENGINE_PT1: _PT1_KNOBS,
}
KNOB_KEYS = _V5_OWN_KNOBS + _PT1_KNOBS + (RAM_BUDGET_KNOB,)
DEFAULT_KNOBS = {
    "v5_segment_kb": 128,
    "v5_region_kb": 1024,
    "v5_bucket_mb": run_budget.DEFAULT_BUCKET_MB,
    "v5_windows_at_25": run_budget.DEFAULT_TARGET_WINDOWS_AT_25,
    "pt1_b": 0,             # 0 = floor(N^(1/4)) of the run's top
    "pt1_chunk_kb": 4096,
    RAM_BUDGET_KNOB: round(run_budget.DEFAULT_SAFETY_FRACTION * 100),
}
_ZERO_ALLOWED = {"pt1_b"}
PT1_MAX_B = 2 ** 32 - 1
_MAX_VALUES = {"pt1_b": PT1_MAX_B, RAM_BUDGET_KNOB: 100}

# Input ceiling of one run's window count. v4.1 gains nothing from longer tapes; v5's cap
# leaves room above the floor-27 target (about 46,000 windows of 10^7); pt1 has no fixed
# cost to amortize and no run-sized buffer, the cap only bounds one run's duration.
MAX_WINDOWS_PER_RUN = {ENGINE_V41: 1000, ENGINE_V5: 100_000, ENGINE_PT1: 100_000}

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


def resolve(loop_settings):
    """EngineChoice from persisted settings; never fails: a bad knob gets its default."""
    knobs = {}
    for key in KNOB_KEYS:
        parsed, bad = parse_knobs({key: loop_settings.get(key)})
        knobs[key] = parsed[key] if bad is None else DEFAULT_KNOBS[key]
    return EngineChoice(normalize_engine(loop_settings.get("engine")), knobs)


def max_windows_per_run(engine):
    return MAX_WINDOWS_PER_RUN[normalize_engine(engine)]


def recommend(available_ram_bytes, choice, base_exponent, window_m):
    """run_budget.RunBudget for one run with this engine and knobs, capped at
    max_windows_per_run() and fitted into ram_budget_pct percent of available_ram_bytes;
    None without a RAM reading. An unknown floor (None) sizes the run like a shallow
    floor."""
    floor = base_exponent if base_exponent is not None else 0
    return run_budget.recommend_run(
        available_ram_bytes, choice.engine, floor, window_m,
        bucket_mb=choice.knobs["v5_bucket_mb"],
        target_at_25=choice.knobs["v5_windows_at_25"],
        safety_fraction=choice.knobs[RAM_BUDGET_KNOB] / 100,
        max_windows=max_windows_per_run(choice.engine))


def launch_env(choice, bucket_mb=None):
    """[(name, value)] to set in front of an orchestrator launch: always the engine, plus
    the three v5 knobs for v5 or B and the chunk size for pt1. bucket_mb overrides the v5
    knob (a RAM-reduced recommendation)."""
    env = [(SCANNER_VERSION_ENV, choice.engine)]
    if choice.engine == ENGINE_PT1:
        env += [(PT1_B_ENV, str(choice.knobs["pt1_b"])),
                (PT1_CHUNK_KB_ENV, str(choice.knobs["pt1_chunk_kb"]))]
    if choice.engine == ENGINE_V5:
        bucket = bucket_mb if bucket_mb is not None else choice.knobs["v5_bucket_mb"]
        env += [(SEGMENT_KB_ENV, str(choice.knobs["v5_segment_kb"])),
                (REGION_KB_ENV, str(choice.knobs["v5_region_kb"])),
                (BUCKET_MB_ENV, str(bucket))]
    return env
