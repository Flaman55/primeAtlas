"""Knob profiles of the bucketed engines (v5, v6): named sets of the four knobs that decide
the sieve's speed (segment, bucket region, bucket memory, pieces per thread).

The best bucket memory grows with the run's width: large buckets cut the rounds of a long run
(10,000 windows of 10^7 numbers: 8 GiB sieves 2.5x faster than 1 GiB at floors 16-20, -31 %
at floor 25) but cost a short run their allocation (1,000 windows at floors 19-20: 8 GiB
about 10 % slower than 1 GiB; 2,000 windows: 4 GiB 8-13 % faster than both). v6's buffer is
almost half of v5's, so its short runs sieve fastest with 128 KiB segments (1,000-2,000
windows at floors 19-20: 5-10 % faster than 2 MiB). The profiles name the measured sets so a
run is switched by one choice:
  - old:    128 KiB segments, 1 GiB buckets (the engines' settings before the 2 MiB segments)
  - new:    2 MiB segments, 8 GiB buckets (long runs; the engines' built-in defaults)
  - mid:    2 MiB segments, 1 GiB buckets (short runs)
  - auto:   the segment and bucket memory of AUTO_STEPS for the run's window count, per
            engine; new when the window count is not known yet
  - custom: the knob fields as typed.
The windows-at-25 and RAM-budget knobs size the run rather than the sieve, so no profile
sets them. The values are measurements on one machine (Ryzen 9 5900X, 64 GB), not limits.
"""

PRESET_AUTO = "auto"
PRESET_OLD = "old"
PRESET_NEW = "new"
PRESET_MID = "mid"
PRESET_CUSTOM = "custom"
PRESETS = (PRESET_AUTO, PRESET_OLD, PRESET_NEW, PRESET_MID, PRESET_CUSTOM)
DEFAULT_PRESET = PRESET_AUTO
PRESET_ENGINES = ("v5", "v6")

# Per engine: ((below this many windows per run, segment KiB, bucket MiB), ...); from the
# last bound on, auto takes new's set. Bounds lie between the measured widths 1000 / 2000 /
# 5000 / 10000 at floors 16-20.
AUTO_STEPS = {"v5": ((1500, 2048, 1024), (4000, 2048, 4096)),
              "v6": ((3000, 128, 1024), (8000, 2048, 4096))}

_PROFILE_KNOBS = ("segment_kb", "region_kb", "bucket_mb", "pieces_per_thread")
_VALUES = {
    PRESET_OLD: (128, 1024, 1024, 16),
    PRESET_NEW: (2048, 1024, 8192, 16),
    PRESET_MID: (2048, 1024, 1024, 16),
}


def preset_key(engine):
    """The persisted settings key of `engine`'s profile."""
    return f"{engine}_preset"


def normalize_preset(value):
    """The profile name, or DEFAULT_PRESET for anything not in PRESETS."""
    text = value.strip() if isinstance(value, str) else ""
    return text if text in PRESETS else DEFAULT_PRESET


def profile_knob_keys(engine):
    """The knob keys a profile of `engine` sets."""
    return tuple(f"{engine}_{knob}" for knob in _PROFILE_KNOBS)


def preset_values(engine, name):
    """{knob key: value} of the concrete profile `name` (old, new, mid) for `engine`."""
    return dict(zip(profile_knob_keys(engine), _VALUES[name]))


def preset_knobs(engine, preset, windows):
    """{knob key: value} that `preset` sets for `engine` at `windows` windows per run (None =
    not known yet), or None for custom."""
    preset = normalize_preset(preset)
    if preset == PRESET_CUSTOM:
        return None
    if preset != PRESET_AUTO:
        return preset_values(engine, preset)
    values = preset_values(engine, PRESET_NEW)
    if windows is not None:
        for below, segment_kb, bucket_mb in AUTO_STEPS[engine]:
            if windows < below:
                values[f"{engine}_segment_kb"] = segment_kb
                values[f"{engine}_bucket_mb"] = bucket_mb
                break
    return values


def apply_preset(engine, preset, windows, knobs):
    """A copy of `knobs` with `engine`'s profile knobs set by `preset` at `windows` windows
    per run; unchanged for custom and for engines without profiles."""
    out = dict(knobs)
    if engine not in PRESET_ENGINES:
        return out
    values = preset_knobs(engine, preset, windows)
    if values is not None:
        out.update(values)
    return out
