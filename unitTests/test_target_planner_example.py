"""The target planner's example (primeatlas/generation/target_planner_example.py and its text
file target_planner_example.txt).

Rules checked:
  - the example parses with no bad line, has at least four targets, one forced to
    Pseudosquares, one to pt1.1, at least one with no engine, and its comments on their own
    lines;
  - planned with any costs it gives groups in every lane and nothing unplanned;
  - ensure_copy(storage) writes the example into the storage folder when it is missing and
    returns its path; an existing copy (edited by the person) is never overwritten; a
    storage path that cannot take the file returns None without raising;
  - the copy, read back, is the example text.
    python unitTests/test_target_planner_example.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

W = 10_000_000


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def text_checks(tp, example):
    from primeatlas.generation.target_planner_section import MAX_NUMBER
    passed = True
    text = example.example_text()
    parsed = tp.parse_targets(text, MAX_NUMBER)
    engines = [t.engine for t in parsed.targets]
    passed &= check(not parsed.errors and len(parsed.targets) >= 4,
                    f"the example parses: {len(parsed.targets)} targets, errors "
                    f"{parsed.errors}")
    passed &= check(tp.METHOD_PSS in engines and "pt1" in engines and None in engines,
                    f"one target forced to Pseudosquares, one to pt1.1, one free ({engines})")
    passed &= check("pt1.1" in text, "pt1.1 is written as the person sees the version")
    inline = [line for line in text.splitlines()
              if "#" in line and not line.lstrip().startswith("#")]
    passed &= check(not inline, f"comments on their own lines ({inline})")

    def atlas(floor, idx, windows, engine="v7"):
        return 100.0 + 0.1 * windows, engine

    def pss(floor, idx, windows):
        return 1.0 + 2.0 * windows

    def lane_for(choice):
        if choice == tp.METHOD_PSS:
            return tp.Lane(lambda f: set(), lambda f: 1000, lambda *a: None, pss)
        return tp.Lane(lambda f: set(), lambda f: 1000,
                       lambda f, i, w: atlas(f, i, w, choice), lambda *a: None)

    plan = tp.plan_targets(parsed.targets, W, lambda f: set(), lambda f: 1000, atlas, pss,
                           lane_for=lane_for)
    lanes = {(g.forced, g.engine if g.method == tp.METHOD_ATLAS else g.method)
             for g in plan.groups}
    passed &= check(plan.groups and not plan.unplanned and (True, "pt1") in lanes
                    and (True, tp.METHOD_PSS) in lanes
                    and any(not forced for forced, _ in lanes),
                    f"planned: groups in every lane, nothing unplanned ({lanes})")
    return passed


def copy_checks(example):
    passed = True
    storage = tempfile.mkdtemp(prefix="primeatlas_planner_example_")
    try:
        path = example.ensure_copy(storage)
        passed &= check(path == os.path.join(storage, example.EXAMPLE_FILE_NAME)
                        and os.path.isfile(path), f"missing: the copy is written ({path})")
        with open(path, encoding="utf-8") as f:
            passed &= check(f.read().rstrip("\n") == example.example_text().rstrip("\n"),
                            "the copy holds the example text")
        with open(path, "w", encoding="utf-8") as f:
            f.write("10**20 5\n")
        again = example.ensure_copy(storage)
        with open(path, encoding="utf-8") as f:
            kept = f.read()
        passed &= check(again == path and kept == "10**20 5\n",
                        "an edited copy is never overwritten")
        blocked = os.path.join(storage, "a_file")
        with open(blocked, "w") as f:
            f.write("x")
        try:
            result = example.ensure_copy(blocked)
            passed &= check(result is None, f"a storage path that is a file: None ({result})")
        except Exception as error:  # noqa: BLE001
            passed &= check(False, f"a storage path that is a file raised {error!r}")
    finally:
        shutil.rmtree(storage, ignore_errors=True)
    return passed


def main():
    from primeatlas.generation import target_planner as tp
    from primeatlas.generation import target_planner_example as example
    passed = text_checks(tp, example)
    passed &= copy_checks(example)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
