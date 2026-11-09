"""engine_options turns the Generation tab's engine choice and v5/v6 perf knobs into a run plan.

Checks: the engine names, knob defaults and environment variable names mirror
orchestrator_v3.py / work_plan_v5.py / work_plan_v6.py and run_budget.py; v5 and v6 have
their own knob sets with their own defaults; the default engine is v6 in both the GUI and
orchestrator_v3.py run without PRIMEATLAS_SCANNER_VERSION; an unknown engine falls
back to the default; knob parsing accepts blanks (default) and positive integers and names the first bad
field; the RAM budget knob is a percentage 1..100 (default from run_budget.py) read by
v4.1 and v5, never by pt1, and reaches run_budget as safety_fraction; resolve() never fails (Restore has no form to report errors in); the per-run window
cap is 1000 for v4.1 and higher for v5; recommend() passes the engine, floor and knobs on to
run_budget and respects the cap; launch_env() always names the engine and adds the
engine's own four knobs (segment, region, buckets, pieces per thread) for v5 and v6, plus v6's
write threads, with a bucket override (which only lowers the buckets); every knob and the engine selector have an info text in both locales; build_wsl_logged_command() puts that env in front
of the command, quoted, and rejects malformed names; the persisted Generation settings carry
the engine and knob defaults. Pure Python, runs on Windows and WSL:
    python unitTests/test_engine_options.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

from primeatlas.generation import engine_options as eo  # noqa: E402
from primeatlas.generation import generation_settings, run_budget, wsl_command, wsl_resources  # noqa: E402
import pt1_plan  # noqa: E402
import work_plan_v5  # noqa: E402
import work_plan_v6  # noqa: E402
import work_plan_v7_1  # noqa: E402

GB = 10 ** 9
W = 10_000_000


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def check_mirrors():
    passed = True
    passed &= check(eo.ENGINES == ("v4.1", "v5", "v6", "v7", "pt1"), f"engines offered: {eo.ENGINES}")
    passed &= check(eo.DEFAULT_ENGINE == "v6", f"default engine {eo.DEFAULT_ENGINE}")
    # orchestrator_v3.py imports WSL-only engine modules, so its default is read from source.
    with open(os.path.join(ROOT, "prime_sieve", "orchestrator_v3.py"), encoding="utf-8") as f:
        src = f.read()
    match = re.search(r'^SCANNER_VERSION = os\.environ\.get\("PRIMEATLAS_SCANNER_VERSION"\)'
                      r' or "([^"]+)"$', src, re.MULTILINE)
    passed &= check(match is not None and match.group(1) == eo.DEFAULT_ENGINE,
                    f"orchestrator_v3.py default engine "
                    f"{match.group(1) if match else None} matches the GUI default")
    passed &= check(eo.SCANNER_VERSION_ENV == "PRIMEATLAS_SCANNER_VERSION",
                    "engine env name matches orchestrator_v3.py")
    d = eo.DEFAULT_KNOBS
    for engine, plan in (("v5", work_plan_v5), ("v6", work_plan_v6), ("v7", work_plan_v7_1)):
        jump_envs = ({"v7_jump_model_pct": plan.JUMP_MODEL_PCT_ENV,
                      "v7_jump_block_cost": plan.JUMP_BLOCK_COST_ENV,
                      "v7_jump_landing_cost_pct": plan.JUMP_LANDING_COST_PCT_ENV,
                      "v7_jump_block_pct": plan.JUMP_BLOCK_PCT_ENV} if engine == "v7" else {})
        passed &= check(eo.KNOB_ENVS[engine] == {
            f"{engine}_segment_kb": plan.SEGMENT_KB_ENV,
            f"{engine}_region_kb": plan.REGION_KB_ENV,
            f"{engine}_bucket_mb": plan.BUCKET_MB_ENV,
            f"{engine}_pieces_per_thread": plan.PIECES_PER_THREAD_ENV,
            f"{engine}_write_threads": plan.WRITE_THREADS_ENV, **jump_envs},
            f"{engine} knob env names match {plan.__name__}.py")
        passed &= check((d[f"{engine}_segment_kb"], d[f"{engine}_region_kb"],
                         d[f"{engine}_bucket_mb"], d[f"{engine}_pieces_per_thread"])
                        == (plan.DEFAULT_SEGMENT_KB, plan.DEFAULT_REGION_KB,
                            plan.DEFAULT_BUCKET_MB, plan.DEFAULT_PIECES_PER_THREAD),
                        f"{engine} knob defaults match {plan.__name__}.py")
        passed &= check(d[f"{engine}_windows_at_25"]
                        == run_budget.DEFAULT_TARGET_WINDOWS_AT_25[engine],
                        f"{engine} windows-at-25 default matches run_budget.py")
    passed &= check((d["v7_jump_model_pct"], d["v7_jump_block_cost"],
                     d["v7_jump_landing_cost_pct"], d["v7_jump_block_pct"], d["v7_write_threads"])
                    == (work_plan_v7_1.DEFAULT_JUMP_MODEL_PCT,
                        work_plan_v7_1.DEFAULT_JUMP_BLOCK_COST,
                        work_plan_v7_1.DEFAULT_JUMP_LANDING_COST_PCT,
                        work_plan_v7_1.DEFAULT_JUMP_BLOCK_PCT,
                        work_plan_v7_1.DEFAULT_WRITE_THREADS),
                    "v7 jump and write-threads defaults match work_plan_v7_1.py")
    passed &= check("v7_jump_pct" not in eo.KNOB_KEYS,
                    "v7.0's threshold factor is no knob of v7.1 (its meaning changed)")
    passed &= check(d["v6_write_threads"] == work_plan_v6.DEFAULT_WRITE_THREADS
                    and d["v5_write_threads"] == work_plan_v5.DEFAULT_WRITE_THREADS,
                    "v5/v6 write-threads defaults match the work plans")
    passed &= check((d["v5_segment_kb"], d["v5_region_kb"], d["v5_bucket_mb"])
                    == (2048, 1024, 8192),
                    "v5.1 defaults: 2 MiB segments, 1 MiB regions, 8 GiB buckets (measured)")
    passed &= check(eo.ENGINE_VERSIONS == {"v4.1": "v4.1", "v5": "v5.2", "v6": "v6.1",
                                           "v7": "v7.1", "pt1": "pt1"},
                    f"engine versions shown in the GUI ({eo.ENGINE_VERSIONS})")
    passed &= check(set(d) == set(eo.KNOB_KEYS), "DEFAULT_KNOBS covers exactly KNOB_KEYS")
    for engine in ("pt1", "v7"):
        passed &= check(re.search(rf'^elif SCANNER_VERSION == "{engine}":$', src, re.MULTILINE)
                        is not None, f"orchestrator_v3.py has a {engine} branch")
    passed &= check(re.search(r'^    import prime_sieve_v7_1 as prime_sieve_module', src,
                              re.MULTILINE) is not None, "orchestrator_v3.py: v7 runs v7.1")
    import generation_stop
    passed &= check(generation_stop.scanner_script("v7") == "prime_sieve_v7_1.py",
                    "the save-point stop knows v7's scanner script")
    passed &= check((eo.PT1_B_ENV, eo.PT1_CHUNK_KB_ENV) == (pt1_plan.B_ENV, pt1_plan.CHUNK_KB_ENV),
                    "pt1 env names match pt1_plan.py")
    passed &= check(d["pt1_b"] == 0 and d["pt1_chunk_kb"] == pt1_plan.DEFAULT_CHUNK_KB,
                    f"pt1 defaults: B auto (0), chunk {pt1_plan.DEFAULT_CHUNK_KB} KiB")
    passed &= check(eo.engine_knob_keys("pt1") == ("pt1_b", "pt1_chunk_kb")
                    and eo.engine_knob_keys("v5") == ("v5_segment_kb", "v5_region_kb",
                                                      "v5_bucket_mb", "v5_windows_at_25",
                                                      "v5_pieces_per_thread", "v5_write_threads",
                                                      "ram_budget_pct")
                    and eo.engine_knob_keys("v6") == ("v6_segment_kb", "v6_region_kb",
                                                      "v6_bucket_mb", "v6_windows_at_25",
                                                      "v6_pieces_per_thread", "v6_write_threads",
                                                      "ram_budget_pct")
                    and eo.engine_knob_keys("v7") == ("v7_segment_kb", "v7_region_kb",
                                                      "v7_bucket_mb", "v7_windows_at_25",
                                                      "v7_pieces_per_thread", "v7_write_threads",
                                                      "v7_jump_model_pct",
                                                      "v7_jump_block_cost",
                                                      "v7_jump_landing_cost_pct",
                                                      "v7_jump_block_pct",
                                                      "ram_budget_pct")
                    and eo.engine_knob_keys("v4.1") == ("ram_budget_pct",),
                    "knobs per engine")
    passed &= check(eo.KNOB_KEYS[-1] == "ram_budget_pct"
                    and len(set(eo.KNOB_KEYS)) == len(eo.KNOB_KEYS),
                    f"KNOB_KEYS lists each knob once, RAM budget last ({eo.KNOB_KEYS})")
    passed &= check(d["ram_budget_pct"] == round(run_budget.DEFAULT_SAFETY_FRACTION * 100) == 50,
                    f"RAM budget default {d['ram_budget_pct']} % matches run_budget.py")
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
    passed &= check(bad is None and knobs == dict(eo.DEFAULT_KNOBS, v5_segment_kb=256,
                                                  v5_bucket_mb=512, v5_windows_at_25=2000),
                    f"strings, ints and blanks parse ({knobs})")
    for raw, want in (("", 0), ("0", 0), (" 5000 ", 5000)):
        knobs, bad = eo.parse_knobs({"pt1_b": raw})
        passed &= check(bad is None and knobs["pt1_b"] == want, f"pt1 B {raw!r} -> {want}")
    for raw, want in (("1", 1), (" 80 ", 80), ("100", 100), ("", 50)):
        knobs, bad = eo.parse_knobs({"ram_budget_pct": raw})
        passed &= check(bad is None and knobs["ram_budget_pct"] == want,
                        f"RAM budget {raw!r} -> {want}")
    for raw in ("0", "101", "-5", "50.5", "half"):
        knobs, bad = eo.parse_knobs({"ram_budget_pct": raw})
        passed &= check(knobs is None and bad == "ram_budget_pct", f"RAM budget {raw!r} rejected")
    for key, raw, want in (("v7_jump_model_pct", "", 100), ("v7_jump_model_pct", "0", 0),
                           ("v7_jump_model_pct", " 250 ", 250),
                           ("v7_jump_landing_cost_pct", "0", 0),
                           ("v7_jump_landing_cost_pct", "", 10),
                           ("v7_jump_block_cost", "", 300), ("v7_jump_block_cost", "1", 1)):
        knobs, bad = eo.parse_knobs({key: raw})
        passed &= check(bad is None and knobs[key] == want,
                        f"{key} {raw!r} -> {want} (model 0 % = gear off)")
    for key, raw in (("v7_jump_model_pct", "-1"), ("v7_jump_model_pct", "1.5"),
                     ("v7_jump_block_cost", "0"), ("v7_jump_landing_cost_pct", "-2"),
                     ("v7_jump_block_pct", "0"),
                     ("v7_jump_block_pct", "-3"), ("v7_jump_block_pct", "x")):
        knobs, bad = eo.parse_knobs({key: raw})
        passed &= check(knobs is None and bad == key, f"{key} {raw!r} rejected")
    knobs, bad = eo.parse_knobs({"pt1_b": "-1"})
    passed &= check(bad == "pt1_b", "negative B rejected")
    for raw in ("0", "-5", "abc", "1.5"):
        knobs, bad = eo.parse_knobs({"v5_region_kb": raw, "v5_bucket_mb": "x"})
        passed &= check(knobs is None and bad == "v5_region_kb",
                        f"region {raw!r} rejected, first bad field named ({bad})")
    choice = eo.resolve({"engine": "v5", "v5_preset": "custom", "v5_bucket_mb": "nonsense", "v5_segment_kb": "64"})
    passed &= check(choice.engine == "v5" and choice.knobs["v5_bucket_mb"] == 8192
                    and choice.knobs["v5_segment_kb"] == 64,
                    f"resolve keeps valid knobs and defaults the bad one ({choice})")
    passed &= check(eo.resolve({}) == eo.EngineChoice(eo.DEFAULT_ENGINE, eo.DEFAULT_KNOBS),
                    "resolve of empty settings -> default engine and knobs")
    return passed


def check_caps_and_recommend():
    passed = True
    passed &= check(eo.max_windows_per_run("v4.1") == 1000, "v4.1 cap is 1000 windows")
    for engine in ("v5", "v6"):
        passed &= check(eo.max_windows_per_run(engine) == 100_000,
                        f"{engine} cap {eo.max_windows_per_run(engine)}")
    v6 = eo.resolve({"engine": "v6"})
    rec = eo.recommend(64 * GB, v6, 25, W)
    passed &= check(rec == run_budget.recommend_run(
        64 * GB, "v6", 25, W, bucket_mb=8192,
        target_at_25=run_budget.DEFAULT_TARGET_WINDOWS_AT_25["v6"], max_windows=100_000),
        f"v6 @25 reads its own knobs ({rec})")
    tuned = eo.resolve({"engine": "v6", "v6_preset": "custom", "v6_bucket_mb": "256", "v6_windows_at_25": "2000",
                        "v5_windows_at_25": "9"})
    rec = eo.recommend(64 * GB, tuned, 25, W)
    passed &= check(rec.windows == 2000 and rec.bucket_mb == 256,
                    f"v6 knobs reach run_budget, v5's do not ({rec})")
    passed &= check(eo.max_windows_per_run("bogus") == eo.max_windows_per_run(eo.DEFAULT_ENGINE),
                    "unknown engine -> default engine's cap")
    v5 = eo.resolve({"engine": "v5"})
    rec = eo.recommend(64 * GB, v5, 25, W)
    passed &= check(rec == run_budget.recommend_run(64 * GB, "v5", 25, W,
                                                    max_windows=100_000),
                    f"v5 @25, 64 GB: same as run_budget ({rec})")
    tuned = eo.resolve({"engine": "v5", "v5_preset": "custom", "v5_bucket_mb": "256", "v5_windows_at_25": "2000"})
    rec = eo.recommend(64 * GB, tuned, 25, W)
    passed &= check(rec.windows == 2000 and rec.bucket_mb == 256,
                    f"knobs reach run_budget ({rec})")
    rec = eo.recommend(10 ** 13, eo.resolve({"engine": "v5", "v5_windows_at_25": "10000000"}),
                       25, W)
    passed &= check(rec.windows == eo.max_windows_per_run("v5"),
                    f"recommendation never exceeds the cap ({rec.windows})")
    v41 = eo.resolve({"engine": "v4.1"})
    passed &= check(eo.recommend(64 * GB, v41, 25, W).windows
                    == wsl_resources.recommended_max_windows(64 * GB),
                    "v4.1 recommendation matches the old Auto button")
    passed &= check(eo.recommend(None, v5, 25, W) is None, "no RAM reading -> None")
    pt1 = eo.resolve({"engine": "pt1"})
    cap = eo.max_windows_per_run("pt1")
    passed &= check(cap == 100_000, f"pt1 cap {cap}")
    passed &= check(eo.recommend(64 * GB, pt1, 29, W).windows == cap
                    and eo.recommend(GB // 2, pt1, 29, W).windows == cap,
                    "pt1 recommendation is not RAM-capped")
    passed &= check(eo.recommend(64 * GB, v5, None, W).windows == run_budget.BASE_WINDOWS,
                    "unknown floor -> base target")
    for engine, floor in (("v5", 25), ("v5", 27), ("v6", 27), ("v4.1", 25)):
        choice = eo.resolve({"engine": engine, "ram_budget_pct": "80"})
        for ram in (8 * GB, 64 * GB):
            rec = eo.recommend(ram, choice, floor, W)
            want = run_budget.recommend_run(
                ram, engine, floor, W, safety_fraction=0.8,
                max_windows=eo.max_windows_per_run(engine))
            passed &= check(rec == want, f"{engine} @{floor}, {ram // GB} GB, 80 %: "
                                         f"budget follows the knob ({rec} == {want})")
    small = eo.recommend(8 * GB, eo.resolve({"engine": "v4.1", "ram_budget_pct": "10"}), 25, W)
    large = eo.recommend(8 * GB, eo.resolve({"engine": "v4.1", "ram_budget_pct": "90"}), 25, W)
    passed &= check(small.windows < large.windows,
                    f"v4.1, 8 GB: 10 % fits fewer windows than 90 % ({small.windows} < "
                    f"{large.windows})")
    rec = eo.recommend(GB // 2, eo.resolve({"engine": "pt1", "ram_budget_pct": "1"}), 29, W)
    passed &= check(rec.windows == cap, "pt1 ignores the RAM budget")
    return passed


def check_env():
    passed = True
    v41 = eo.launch_env(eo.resolve({"engine": "v4.1", "v5_bucket_mb": "64"}))
    passed &= check(v41 == [("PRIMEATLAS_SCANNER_VERSION", "v4.1")],
                    f"v4.1 env names only the engine ({v41})")
    v5 = eo.resolve({"engine": "v5", "v5_preset": "custom", "v5_segment_kb": "256", "ram_budget_pct": "80"})
    env = eo.launch_env(v5)
    passed &= check(env == [("PRIMEATLAS_SCANNER_VERSION", "v5"),
                            ("PRIMEATLAS_V5_SEGMENT_KB", "256"),
                            ("PRIMEATLAS_V5_REGION_KB", "1024"),
                            ("PRIMEATLAS_V5_BUCKET_MB", "8192"),
                            ("PRIMEATLAS_V5_PIECES_PER_THREAD", "16"),
                            ("PRIMEATLAS_V5_WRITE_THREADS", "8")],
                    f"v5 env carries its five knobs ({env})")
    v6 = eo.resolve({"engine": "v6", "v6_preset": "custom", "v6_segment_kb": "1024", "v5_segment_kb": "64"})
    env6 = eo.launch_env(v6, bucket_mb=300)
    passed &= check(env6 == [("PRIMEATLAS_SCANNER_VERSION", "v6"),
                             ("PRIMEATLAS_V6_SEGMENT_KB", "1024"),
                             ("PRIMEATLAS_V6_REGION_KB", "1024"),
                             ("PRIMEATLAS_V6_BUCKET_MB", "300"),
                             ("PRIMEATLAS_V6_PIECES_PER_THREAD", "16"),
                             ("PRIMEATLAS_V6_WRITE_THREADS", "8")],
                    f"v6 env carries its own five knobs, bucket override wins ({env6})")
    passed &= check(work_plan_v6.segment_kb_from_env(dict(env6)) == 1024
                    and work_plan_v6.pieces_per_thread_from_env(dict(env6)) == 16
                    and work_plan_v6.write_threads_from_env(dict(env6)) == 8,
                    "work_plan_v6 reads the env back")
    v7 = eo.resolve({"engine": "v7", "v7_preset": "custom", "v7_jump_model_pct": "0",
                     "v7_jump_pct": "300", "v6_segment_kb": "64"})
    env7 = eo.launch_env(v7)
    passed &= check(env7 == [("PRIMEATLAS_SCANNER_VERSION", "v7"),
                             ("PRIMEATLAS_V7_SEGMENT_KB", "2048"),
                             ("PRIMEATLAS_V7_REGION_KB", "1024"),
                             ("PRIMEATLAS_V7_BUCKET_MB", "8192"),
                             ("PRIMEATLAS_V7_PIECES_PER_THREAD", "16"),
                             ("PRIMEATLAS_V7_WRITE_THREADS", "8"),
                             ("PRIMEATLAS_V7_JUMP_MODEL_PCT", "0"),
                             ("PRIMEATLAS_V7_JUMP_BLOCK_COST", "300"),
                             ("PRIMEATLAS_V7_JUMP_LANDING_COST_PCT", "10"),
                             ("PRIMEATLAS_V7_JUMP_BLOCK_PCT", "50")],
                    f"v7 env carries its own nine knobs, never v6's nor v7.0's threshold "
                    f"({env7})")
    passed &= check(work_plan_v7_1.jump_model_pct_from_env(dict(env7)) == 0
                    and work_plan_v7_1.jump_block_cost_from_env(dict(env7)) == 300
                    and work_plan_v7_1.jump_landing_cost_pct_from_env(dict(env7)) == 10
                    and work_plan_v7_1.jump_block_pct_from_env(dict(env7)) == 50
                    and work_plan_v7_1.segment_kb_from_env(dict(env7)) == 2048,
                    "work_plan_v7_1 reads the env back (model 0 % = gear off)")
    env = dict(eo.launch_env(v5, bucket_mb=417))
    passed &= check(env["PRIMEATLAS_V5_BUCKET_MB"] == "417", "bucket override wins")
    env = eo.launch_env(eo.resolve({"engine": "pt1", "pt1_b": "7000", "v5_bucket_mb": "64"}))
    passed &= check(env == [("PRIMEATLAS_SCANNER_VERSION", "pt1"), ("PRIMEATLAS_PT1_B", "7000"),
                            ("PRIMEATLAS_PT1_CHUNK_KB", "4096")],
                    f"pt1 env carries B and chunk only ({env})")
    passed &= check(pt1_plan.b_from_env(dict(env)) == 7000
                    and pt1_plan.chunk_kb_from_env(dict(env)) == 4096
                    and pt1_plan.b_from_env({}) == 0,
                    "pt1_plan reads the env back (missing B -> auto)")
    env = dict(eo.launch_env(v5))
    passed &= check(work_plan_v5.segment_kb_from_env(env) == 256
                    and work_plan_v5.bucket_mb_from_env(env) == 8192
                    and work_plan_v5.pieces_per_thread_from_env(env) == 16,
                    "work_plan_v5 reads the env back")
    return passed


def check_wsl_command():
    passed = True
    base = wsl_command.build_wsl_logged_command(["python3", "x.py"], "C:\\l.log", "C:\\e.txt",
                                               "C:\\portal")
    passed &= check(base == wsl_command.build_wsl_logged_command(
        ["python3", "x.py"], "C:\\l.log", "C:\\e.txt", "C:\\portal", extra_env=()),
        "no extra env -> command unchanged")
    cmd = wsl_command.build_wsl_logged_command(
        ["python3", "x.py"], "C:\\l.log", "C:\\e.txt", "C:\\portal",
        extra_env=[("PRIMEATLAS_SCANNER_VERSION", "v5"), ("PRIMEATLAS_V5_BUCKET_MB", "a b")])
    bash = cmd[-1]
    passed &= check("PRIMEATLAS_SCANNER_VERSION=v5 " in bash
                    and "PRIMEATLAS_V5_BUCKET_MB='a b' " in bash
                    and bash.index("PRIMEATLAS_SCANNER_VERSION") < bash.index("python3"),
                    f"env goes before the argv, quoted ({bash[:120]}...)")
    try:
        wsl_command.build_wsl_logged_command(["python3"], "C:\\l", "C:\\e", "C:\\p",
                                            extra_env=[("BAD; rm", "1")])
        passed &= check(False, "malformed env name rejected")
    except ValueError:
        passed &= check(True, "malformed env name rejected")
    loop = generation_settings.DEFAULT_GENERATION_SETTINGS["loop"]
    passed &= check(loop.get("engine") == eo.DEFAULT_ENGINE
                    and all(loop.get(k) == str(v) for k, v in eo.DEFAULT_KNOBS.items()),
                    "persisted loop settings carry the engine and knob defaults")
    return passed


def check_info_texts():
    import json
    passed = True
    for lang in ("en", "pl"):
        path = os.path.join(ROOT, "primeatlas", "core", "locales", f"strings_{lang}.json")
        with open(path, encoding="utf-8") as f:
            strings = json.load(f)
        missing = [k for k in eo.KNOB_KEYS + ("engine",)
                   if not strings.get(f"gen.info_{k}", "").strip()]
        passed &= check(not missing, f"{lang}: every knob and the engine selector have an "
                                     f"info text (missing {missing})")
    return passed


def main():
    passed = check_mirrors()
    passed &= check_info_texts()
    passed &= check_parsing()
    passed &= check_caps_and_recommend()
    passed &= check_env()
    passed &= check_wsl_command()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
