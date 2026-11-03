"""
test_design_parameters.py -- docs/design/parameters/ is current with the code:

  A. tools/gen_design_parameters.py --check reports no stale page (every Generation form
     default and every visualization renderer argument is documented as the code holds it);
  B. every Generation form field has a label mapping, and every mapped label exists in
     strings_en.json, so no row falls back to "(no form label)";
  C. a changed default is reported as stale (the check compares something).

Run:
    python unitTests\test_design_parameters.py
"""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "tools"))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import gen_design_parameters as gen  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def main():
    print("\n--- A. pages current ---")
    check(gen.main(["--check"]) == 0, "docs/design/parameters/ matches the code's defaults")

    print("\n--- B. labels ---")
    from primeatlas.generation.generation_settings import DEFAULT_GENERATION_SETTINGS
    with open(gen.LOCALE_EN, encoding="utf-8") as f:
        labels = json.load(f)
    for section, values in DEFAULT_GENERATION_SETTINGS.items():
        unmapped = [k for k in values if k not in gen.FORM_LABELS.get(section, {})]
        check(not unmapped, f"every {section} field has a label mapping (missing {unmapped})")
        missing = [v for v in gen.FORM_LABELS.get(section, {}).values() if v not in labels]
        check(not missing, f"every {section} label key exists in strings_en.json (missing {missing})")

    print("\n--- C. a changed default is stale ---")
    loop = DEFAULT_GENERATION_SETTINGS["loop"]
    saved = loop["workers"]
    loop["workers"] = "999"
    try:
        pages = gen.build_pages()
        current = open(os.path.join(gen.OUT_DIR, "generation-loop.md"), encoding="utf-8").read()
        check(pages["generation-loop.md"] != current, "a changed default changes the page")
    finally:
        loop["workers"] = saved

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
