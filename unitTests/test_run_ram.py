"""primeatlas/generation/run_ram.py: the predicted RAM of one run and the widest run that
fits the RAM budget, which cap the time simulation's width slider.

Checks: the prediction is run_budget.run_footprint_bytes() with the knobs the run launches
with (an auto profile's bucket memory follows the width); pt1 has no prediction; the
budget is ram_budget_pct percent of the free RAM; the widest fitting run fits and one more
window does not; a budget too small for the buckets alone gives 0; the engine's cap bounds
the result; pt1 and an unknown RAM reading give None. Pure Python:
    python unitTests/test_run_ram.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

W = 10_000_000
GB = 10 ** 9


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _choice_for(engine, preset="custom", **knobs):
    from primeatlas.generation import engine_options
    settings = {"engine": engine, f"{engine}_preset": preset, **knobs}
    return lambda windows: engine_options.resolve(settings, windows)


def check_prediction():
    from primeatlas.generation import engine_options, run_budget, run_ram
    passed = True
    choice = _choice_for("v5", v5_bucket_mb="1024")(5000)
    passed &= check(run_ram.run_ram_bytes(choice, 5000, W)
                    == run_budget.run_footprint_bytes("v5", 5000, W, 1024),
                    "v5 prediction is the footprint with the bucket knob")
    choice = _choice_for("v6", v6_bucket_mb="2048")(40_000)
    passed &= check(run_ram.run_ram_bytes(choice, 40_000, W)
                    == run_budget.run_footprint_bytes("v6", 40_000, W, 2048),
                    "v6 prediction is the footprint with the bucket knob")
    choice = _choice_for("v4.1")(1000)
    passed &= check(run_ram.run_ram_bytes(choice, 1000, W) == 1000 * (W // 8),
                    "v4.1 prediction is the bit buffer")
    passed &= check(run_ram.run_ram_bytes(_choice_for("pt1")(1000), 1000, W) is None,
                    "pt1 has no prediction")
    passed &= check(run_ram.run_ram_bytes(_choice_for("pt1-pss")(1000), 1000, W) is None,
                    "pt1-pss has no prediction")
    auto = _choice_for("v6", preset="auto")
    small, large = auto(100), auto(90_000)
    passed &= check(small.knobs["v6_bucket_mb"] < large.knobs["v6_bucket_mb"]
                    and run_ram.run_ram_bytes(small, 100, W) == run_budget.run_footprint_bytes(
                        "v6", 100, W, small.knobs["v6_bucket_mb"]),
                    "an auto profile's bucket memory follows the width")
    choice = _choice_for("v5", ram_budget_pct="40")(1)
    passed &= check(run_ram.budget_bytes(choice, 100 * GB) == 40 * GB,
                    "budget is ram_budget_pct percent of the free RAM")
    passed &= check(engine_options.RAM_BUDGET_KNOB == "ram_budget_pct", "budget knob name")
    return passed


def check_max_windows():
    from primeatlas.generation import run_ram
    passed = True
    for engine, extra in (("v5", {"v5_bucket_mb": "1024"}), ("v6", {"v6_bucket_mb": "1024"}),
                          ("v4.1", {})):
        choice_for = _choice_for(engine, ram_budget_pct="50", **extra)
        fit = run_ram.max_windows_in_budget(choice_for, 32 * GB, 100_000, W)
        budget = run_ram.budget_bytes(choice_for(1), 32 * GB)
        passed &= check(fit is not None and 0 < fit < 100_000
                        and run_ram.run_ram_bytes(choice_for(fit), fit, W) <= budget
                        and run_ram.run_ram_bytes(choice_for(fit + 1), fit + 1, W) > budget,
                        f"{engine}: the widest run fits, one more window does not ({fit})")
    auto = _choice_for("v6", preset="auto", ram_budget_pct="50")
    fit = run_ram.max_windows_in_budget(auto, 64 * GB, 100_000, W)
    budget = run_ram.budget_bytes(auto(1), 64 * GB)
    passed &= check(run_ram.run_ram_bytes(auto(fit), fit, W) <= budget
                    and (fit == 100_000 or run_ram.run_ram_bytes(auto(fit + 1), fit + 1, W) > budget),
                    f"auto profile: the widest run fits with its own buckets ({fit})")
    tiny = _choice_for("v5", v5_bucket_mb="8192", ram_budget_pct="10")
    passed &= check(run_ram.max_windows_in_budget(tiny, 16 * GB, 100_000, W) == 0,
                    "buckets alone above the budget -> 0 windows")
    roomy = _choice_for("v6", v6_bucket_mb="64", ram_budget_pct="100")
    passed &= check(run_ram.max_windows_in_budget(roomy, 10 ** 15, 100_000, W) == 100_000,
                    "the engine's cap bounds the result")
    passed &= check(run_ram.max_windows_in_budget(_choice_for("pt1"), 32 * GB, 100_000, W) is None,
                    "pt1 -> None (no RAM limit)")
    passed &= check(run_ram.max_windows_in_budget(_choice_for("pt1-pss"), 32 * GB, 100_000, W)
                    is None, "pt1-pss -> None (no RAM limit)")
    passed &= check(run_ram.max_windows_in_budget(_choice_for("v5"), None, 100_000, W) is None,
                    "unknown RAM -> None")
    return passed


def main():
    passed = check_prediction()
    passed &= check_max_windows()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
