"""engine_presets names the knob profiles of the bucketed engines (v5, v6) and turns a chosen
profile into knob values.

Checks: the profiles are auto, old, new, mid and custom, auto by default (also for an unknown
or missing value); old, new and mid each give the four profile knobs (segment, region,
buckets, pieces per thread) of v5 and v6, matching the measured sets (old = 128 KiB segments
with 1 GiB buckets, new = 2 MiB with 8 GiB, mid = 2 MiB with 1 GiB); new equals the engines'
built-in defaults (work_plan_v5.py, work_plan_v6.py); auto steps the segment and bucket memory
up with the run's window count, per engine (AUTO_STEPS; v5: 2 MiB with 1 GiB below 1500
windows, 2 MiB with 4 GiB below 4000; v6: 128 KiB with 1 GiB below 3000, 2 MiB with 4 GiB
below 8000), then new's set, also for an unknown window count; custom keeps
the fields; applying a profile touches only that engine's four profile knobs, never the
windows-at-25, RAM budget, pt1 or the other engine's knobs; engines without profiles (v4.1,
pt1) are left alone; engine_options.resolve() applies the persisted profile for the run's
window count; launch_env() lets a RAM override only lower the profile's buckets; every
profile has a label and an info text in both locales. Pure Python:
    python unitTests/test_engine_presets.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

from primeatlas.generation import engine_options as eo  # noqa: E402
from primeatlas.generation import engine_presets as ep  # noqa: E402
import work_plan_v5  # noqa: E402
import work_plan_v6  # noqa: E402

PROFILE_KNOBS = ("segment_kb", "region_kb", "bucket_mb", "pieces_per_thread")


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def check_names():
    passed = check(ep.PRESETS == ("auto", "old", "new", "mid", "custom"),
                   f"profiles offered: {ep.PRESETS}")
    passed &= check(ep.DEFAULT_PRESET == "auto", "auto is the default profile")
    for raw in (None, "", "fast", 3):
        passed &= check(ep.normalize_preset(raw) == "auto", f"{raw!r} -> auto")
    passed &= check(ep.normalize_preset(" mid ") == "mid", "names are trimmed")
    passed &= check(ep.preset_key("v5") == "v5_preset" and ep.preset_key("v6") == "v6_preset",
                    "persisted under <engine>_preset")
    passed &= check(ep.PRESET_ENGINES == ("v5", "v6", "v7"), "only v5, v6 and v7 have profiles")
    return passed


def check_values():
    passed = True
    expected = {"old": (128, 1024, 1024, 16), "new": (2048, 1024, 8192, 16),
                "mid": (2048, 1024, 1024, 16)}
    for engine in ep.PRESET_ENGINES:
        for name, values in expected.items():
            got = ep.preset_values(engine, name)
            want = {f"{engine}_{k}": v for k, v in zip(PROFILE_KNOBS, values)}
            passed &= check(got == want, f"{engine} {name}: {got}")
    v5_new, v6_new = ep.preset_values("v5", "new"), ep.preset_values("v6", "new")
    passed &= check(
        (v5_new["v5_segment_kb"], v5_new["v5_region_kb"], v5_new["v5_bucket_mb"],
         v5_new["v5_pieces_per_thread"])
        == (work_plan_v5.DEFAULT_SEGMENT_KB, work_plan_v5.DEFAULT_REGION_KB,
            work_plan_v5.DEFAULT_BUCKET_MB, work_plan_v5.DEFAULT_PIECES_PER_THREAD),
        "v5 new = work_plan_v5 defaults")
    passed &= check(
        (v6_new["v6_segment_kb"], v6_new["v6_region_kb"], v6_new["v6_bucket_mb"],
         v6_new["v6_pieces_per_thread"])
        == (work_plan_v6.DEFAULT_SEGMENT_KB, work_plan_v6.DEFAULT_REGION_KB,
            work_plan_v6.DEFAULT_BUCKET_MB, work_plan_v6.DEFAULT_PIECES_PER_THREAD),
        "v6 new = work_plan_v6 defaults")
    passed &= check(all(v5_new[k] == eo.DEFAULT_KNOBS[k] for k in v5_new),
                    "v5 new = the form's defaults")
    return passed


def check_auto():
    passed = True
    expected = {
        "v5": [(1, 2048, 1024), (1499, 2048, 1024), (1500, 2048, 4096), (3999, 2048, 4096),
               (4000, 2048, 8192), (10 ** 6, 2048, 8192), (None, 2048, 8192)],
        "v6": [(1, 128, 1024), (2999, 128, 1024), (3000, 2048, 4096), (7999, 2048, 4096),
               (8000, 2048, 8192), (10 ** 6, 2048, 8192), (None, 2048, 8192)],
    }
    expected["v7"] = expected["v6"]   # v7 runs on v6's buffer: v6's measured steps
    for engine in ep.PRESET_ENGINES:
        for windows, segment, bucket in expected[engine]:
            got = ep.preset_knobs(engine, "auto", windows)
            passed &= check(got[f"{engine}_bucket_mb"] == bucket
                            and got[f"{engine}_segment_kb"] == segment
                            and got[f"{engine}_region_kb"] == 1024
                            and got[f"{engine}_pieces_per_thread"] == 16,
                            f"{engine} auto at {windows} windows -> {segment} KiB / {bucket} MiB")
        passed &= check(ep.preset_knobs(engine, "auto", None) == ep.preset_values(engine, "new"),
                        f"{engine} auto with unknown width = new")
    passed &= check(ep.preset_knobs("v5", "custom", 10) is None, "custom -> no profile")
    passed &= check(ep.preset_knobs("v5", "old", 10 ** 6) == ep.preset_values("v5", "old"),
                    "named profile ignores width")
    return passed


def check_apply():
    passed = True
    knobs = dict(eo.DEFAULT_KNOBS)
    knobs.update({"v5_segment_kb": 64, "v5_bucket_mb": 333, "v5_windows_at_25": 777,
                  "v6_segment_kb": 99, "pt1_b": 5, eo.RAM_BUDGET_KNOB: 42})
    out = ep.apply_preset("v5", "old", None, knobs)
    passed &= check(out["v5_segment_kb"] == 128 and out["v5_bucket_mb"] == 1024,
                    "old sets the v5 profile knobs")
    passed &= check(out["v5_windows_at_25"] == 777 and out[eo.RAM_BUDGET_KNOB] == 42
                    and out["pt1_b"] == 5 and out["v6_segment_kb"] == 99,
                    "other knobs untouched")
    passed &= check(knobs["v5_segment_kb"] == 64, "input dict not mutated")
    passed &= check(ep.apply_preset("v5", "custom", None, knobs) == knobs, "custom keeps fields")
    passed &= check(ep.apply_preset("v4.1", "old", None, knobs) == knobs, "v4.1 untouched")
    passed &= check(ep.apply_preset("pt1", "new", None, knobs) == knobs, "pt1 untouched")
    short = ep.apply_preset("v6", "auto", 1000, knobs)
    passed &= check(short["v6_bucket_mb"] == 1024 and short["v6_segment_kb"] == 128,
                    "v6 auto at 1000 windows -> its short-run set")
    return passed


def check_engine_options():
    passed = True
    base = {"engine": "v5", "v5_segment_kb": "64", "v5_bucket_mb": "333"}
    passed &= check(eo.resolve(base).knobs["v5_bucket_mb"] == 8192,
                    "no persisted profile -> auto, unknown width -> new")
    passed &= check(eo.resolve(base, windows=1000).knobs["v5_bucket_mb"] == 1024,
                    "auto with a short run -> mid")
    custom = dict(base, v5_preset="custom")
    passed &= check(eo.resolve(custom, windows=1000).knobs["v5_segment_kb"] == 64,
                    "custom keeps the fields")
    old = dict(base, v5_preset="old")
    passed &= check(eo.resolve(old).knobs["v5_segment_kb"] == 128, "old applied")
    choice = eo.resolve(dict(base, v5_preset="mid"))
    env = dict(eo.launch_env(choice, bucket_mb=6000))
    passed &= check(env["PRIMEATLAS_V5_BUCKET_MB"] == "1024",
                    "RAM override never raises the profile's buckets")
    env = dict(eo.launch_env(eo.resolve(dict(base, v5_preset="new")), bucket_mb=6000))
    passed &= check(env["PRIMEATLAS_V5_BUCKET_MB"] == "6000", "RAM override lowers buckets")
    passed &= check(all(ep.preset_key(e) in eo.PERSISTED_KEYS for e in ep.PRESET_ENGINES),
                    "profile keys are persisted with the knobs")
    return passed


def check_locales():
    passed = True
    for lang in ("en", "pl"):
        path = os.path.join(ROOT, "primeatlas", "core", "locales", f"strings_{lang}.json")
        with open(path, encoding="utf-8") as f:
            strings = json.load(f)
        keys = ["gen.field_preset", "gen.info_preset"] + [
            f"gen.preset_{name}" for name in ep.PRESETS]
        missing = [k for k in keys if not strings.get(k, "").strip()]
        passed &= check(not missing, f"{lang}: profile label and info texts (missing {missing})")
    return passed


def main():
    passed = check_names()
    passed &= check_values()
    passed &= check_auto()
    passed &= check_apply()
    passed &= check_engine_options()
    passed &= check_locales()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
