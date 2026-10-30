"""engine_options turns the Generation tab's engine choice and v5 perf knobs into a run plan.

Checks: the engine names, knob defaults and environment variable names mirror
orchestrator_v3.py / work_plan_v5.py and run_budget.py; an unknown engine falls back to the
default; knob parsing accepts blanks (default) and positive integers and names the first bad
field; resolve() never fails (Restore has no form to report errors in); the per-run window
cap is 1000 for v4.1 and higher for v5; recommend() passes the engine, floor and knobs on to
run_budget and respects the cap; launch_env() always names the engine and adds the three v5
knobs only for v5, with a bucket override; build_wsl_logged_command() puts that env in front
of the command, quoted, and rejects malformed names; the persisted Generation settings carry
the engine and knob defaults. Pure Python, runs on Windows and WSL:
    python unitTests/test_engine_options.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

from primeatlas.generation import engine_options as eo  # noqa: E402
from primeatlas.generation import generation, run_budget  # noqa: E402
import work_plan_v5  # noqa: E402

GB = 10 ** 9
W = 10_000_000


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def check_mirrors():
    passed = True
    passed &= check(eo.ENGINES == ("v4.1", "v5"), f"engines offered: {eo.ENGINES}")
    passed &= check(eo.DEFAULT_ENGINE in eo.ENGINES, f"default engine {eo.DEFAULT_ENGINE}")
    passed &= check(eo.SCANNER_VERSION_ENV == "PRIMEATLAS_SCANNER_VERSION",
                    "engine env name matches orchestrator_v3.py")
    passed &= check((eo.SEGMENT_KB_ENV, eo.REGION_KB_ENV, eo.BUCKET_MB_ENV)
                    == (work_plan_v5.SEGMENT_KB_ENV, work_plan_v5.REGION_KB_ENV,
                        work_plan_v5.BUCKET_MB_ENV),
                    "knob env names match work_plan_v5.py")
    d = eo.DEFAULT_KNOBS
    passed &= check((d["v5_segment_kb"], d["v5_region_kb"], d["v5_bucket_mb"])
                    == (work_plan_v5.DEFAULT_SEGMENT_KB, work_plan_v5.DEFAULT_REGION_KB,
                        work_plan_v5.DEFAULT_BUCKET_MB),
                    f"knob defaults match work_plan_v5.py ({d})")
    passed &= check(d["v5_windows_at_25"] == run_budget.DEFAULT_TARGET_WINDOWS_AT_25,
                    "windows-at-25 default matches run_budget.py")
    passed &= check(set(d) == set(eo.KNOB_KEYS), "DEFAULT_KNOBS covers exactly KNOB_KEYS")
    return passed


def check_parsing():
    passed = True
    passed &= check(eo.normalize_engine("v5") == "v5", "v5 stays v5")
    passed &= check(eo.normalize_engine("v3") == eo.DEFAULT_ENGINE
                    and eo.normalize_engine(None) == eo.DEFAULT_ENGINE
                    and eo.normalize_engine(" v5 ") == "v5",
                    "unknown/missing engine -> default; whitespace is stripped")
    knobs, bad = eo.parse_knobs({})
    passed &= check(bad is None and knobs == eo.DEFAULT_KNOBS, "empty mapping -> defaults")
    knobs, bad = eo.parse_knobs({"v5_segment_kb": " 256 ", "v5_region_kb": "",
                                 "v5_bucket_mb": 512, "v5_windows_at_25": "2000"})
    passed &= check(bad is None and knobs == {"v5_segment_kb": 256, "v5_region_kb": 1024,
                                              "v5_bucket_mb": 512, "v5_windows_at_25": 2000},
                    f"strings, ints and blanks parse ({knobs})")
    for raw in ("0", "-5", "abc", "1.5"):
        knobs, bad = eo.parse_knobs({"v5_region_kb": raw, "v5_bucket_mb": "x"})
        passed &= check(knobs is None and bad == "v5_region_kb",
                        f"region {raw!r} rejected, first bad field named ({bad})")
    choice = eo.resolve({"engine": "v5", "v5_bucket_mb": "nonsense", "v5_segment_kb": "64"})
    passed &= check(choice.engine == "v5" and choice.knobs["v5_bucket_mb"] == 1024
                    and choice.knobs["v5_segment_kb"] == 64,
                    f"resolve keeps valid knobs and defaults the bad one ({choice})")
    passed &= check(eo.resolve({}) == eo.EngineChoice(eo.DEFAULT_ENGINE, eo.DEFAULT_KNOBS),
                    "resolve of empty settings -> default engine and knobs")
    return passed


def check_caps_and_recommend():
    passed = True
    passed &= check(eo.max_windows_per_run("v4.1") == 1000, "v4.1 cap is 1000 windows")
    passed &= check(eo.max_windows_per_run("v5") >= run_budget.target_windows("v5", 27, W),
                    f"v5 cap {eo.max_windows_per_run('v5')} holds the floor-27 target")
    passed &= check(eo.max_windows_per_run("bogus") == 1000, "unknown engine -> default cap")
    v5 = eo.resolve({"engine": "v5"})
    rec = eo.recommend(64 * GB, v5, 25, W)
    passed &= check(rec == run_budget.recommend_run(64 * GB, "v5", 25, W),
                    f"v5 @25, 64 GB: same as run_budget ({rec})")
    tuned = eo.resolve({"engine": "v5", "v5_bucket_mb": "256", "v5_windows_at_25": "2000"})
    rec = eo.recommend(64 * GB, tuned, 25, W)
    passed &= check(rec.windows == 2000 and rec.bucket_mb == 256,
                    f"knobs reach run_budget ({rec})")
    rec = eo.recommend(10 ** 13, eo.resolve({"engine": "v5", "v5_windows_at_25": "10000000"}),
                       25, W)
    passed &= check(rec.windows == eo.max_windows_per_run("v5"),
                    f"recommendation never exceeds the cap ({rec.windows})")
    v41 = eo.resolve({"engine": "v4.1"})
    passed &= check(eo.recommend(64 * GB, v41, 25, W).windows
                    == generation.recommended_max_windows(64 * GB),
                    "v4.1 recommendation matches the old Auto button")
    passed &= check(eo.recommend(None, v5, 25, W) is None, "no RAM reading -> None")
    passed &= check(eo.recommend(64 * GB, v5, None, W).windows == run_budget.BASE_WINDOWS,
                    "unknown floor -> base target")
    return passed


def check_env():
    passed = True
    v41 = eo.launch_env(eo.resolve({"engine": "v4.1", "v5_bucket_mb": "64"}))
    passed &= check(v41 == [("PRIMEATLAS_SCANNER_VERSION", "v4.1")],
                    f"v4.1 env names only the engine ({v41})")
    v5 = eo.resolve({"engine": "v5", "v5_segment_kb": "256"})
    env = eo.launch_env(v5)
    passed &= check(env == [("PRIMEATLAS_SCANNER_VERSION", "v5"),
                            ("PRIMEATLAS_V5_SEGMENT_KB", "256"),
                            ("PRIMEATLAS_V5_REGION_KB", "1024"),
                            ("PRIMEATLAS_V5_BUCKET_MB", "1024")],
                    f"v5 env carries the three knobs ({env})")
    env = dict(eo.launch_env(v5, bucket_mb=417))
    passed &= check(env["PRIMEATLAS_V5_BUCKET_MB"] == "417", "bucket override wins")
    env = dict(eo.launch_env(v5))
    passed &= check(work_plan_v5.segment_kb_from_env(env) == 256
                    and work_plan_v5.bucket_mb_from_env(env) == 1024,
                    "work_plan_v5 reads the env back")
    return passed


def check_wsl_command():
    passed = True
    base = generation.build_wsl_logged_command(["python3", "x.py"], "C:\\l.log", "C:\\e.txt",
                                               "C:\\portal")
    passed &= check(base == generation.build_wsl_logged_command(
        ["python3", "x.py"], "C:\\l.log", "C:\\e.txt", "C:\\portal", extra_env=()),
        "no extra env -> command unchanged")
    cmd = generation.build_wsl_logged_command(
        ["python3", "x.py"], "C:\\l.log", "C:\\e.txt", "C:\\portal",
        extra_env=[("PRIMEATLAS_SCANNER_VERSION", "v5"), ("PRIMEATLAS_V5_BUCKET_MB", "a b")])
    bash = cmd[-1]
    passed &= check("PRIMEATLAS_SCANNER_VERSION=v5 " in bash
                    and "PRIMEATLAS_V5_BUCKET_MB='a b' " in bash
                    and bash.index("PRIMEATLAS_SCANNER_VERSION") < bash.index("python3"),
                    f"env goes before the argv, quoted ({bash[:120]}...)")
    try:
        generation.build_wsl_logged_command(["python3"], "C:\\l", "C:\\e", "C:\\p",
                                            extra_env=[("BAD; rm", "1")])
        passed &= check(False, "malformed env name rejected")
    except ValueError:
        passed &= check(True, "malformed env name rejected")
    loop = generation.DEFAULT_GENERATION_SETTINGS["loop"]
    passed &= check(loop.get("engine") == eo.DEFAULT_ENGINE
                    and all(loop.get(k) == str(v) for k, v in eo.DEFAULT_KNOBS.items()),
                    "persisted loop settings carry the engine and knob defaults")
    return passed


def main():
    passed = check_mirrors()
    passed &= check_parsing()
    passed &= check_caps_and_recommend()
    passed &= check_env()
    passed &= check_wsl_command()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
