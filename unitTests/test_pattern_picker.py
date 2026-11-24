"""
test_pattern_picker.py -- primeatlas/constellations/pattern_picker.py's PatternPicker, the
app's one "k-tuple pattern from the catalog" control (k dropdown -> variant dropdown + the
offsets/record info line), and the three places that use it: Constellations > Calculator,
Generation's k-tuple section and Rings' line mode.

Checks: the k list is the catalog's; select() with a known k/id, an unknown k, an unknown id,
no arguments; a k change picks that k's first variant; the info line for a tracked and an
untracked pattern; on_change fires once per change with the selected pattern; the three users
hold a PatternPicker. Windows, real display:
    python unitTests/test_pattern_picker.py
"""
import os
import sys
import tkinter as tk

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_REPO_ROOT, os.path.join(_REPO_ROOT, "prime_sieve"),
                os.path.join(_REPO_ROOT, "constellation")]

import pattern_catalog_v1  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _source(module):
    path = os.path.join(_REPO_ROOT, *module.split(".")) + ".py"
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    from primeatlas.constellations.pattern_picker import PatternPicker, pattern_info

    T = Translator("en").t
    root = tk.Tk()
    seen = []
    picker = PatternPicker(root, T, "const_calc.field_k", "const_calc.field_variant",
                           on_change=seen.append)
    picker.row.pack()
    picker.info_label.pack()
    root.update()

    # The k list is the catalog's.
    check(list(picker.k_combo["values"]) == [str(k) for k in pattern_catalog_v1.all_k()],
          f"k list = catalog k values (got {picker.k_combo['values']})")
    check(str(picker.k_combo["state"]) == "readonly" and str(picker.variant_combo["state"]) == "readonly",
          "both dropdowns are read-only (no free text)")

    # select() without arguments: the first k, its first variant.
    picker.select()
    first = pattern_catalog_v1.patterns_for_k(pattern_catalog_v1.all_k()[0])[0]
    check(picker.pattern() == first, f"select() -> the first catalog pattern (got {picker.pattern()})")
    check(seen and seen[-1] == first, "on_change gets the selected pattern")

    # A known k and id.
    seen.clear()
    picker.select(k=13, variant_id=3)
    want = pattern_catalog_v1.find_pattern(13, pattern_catalog_v1.patterns_for_k(13)[2]["offsets"])
    check(picker.pattern() == want and want["id"] == 3, f"select(13, 3) -> k=13 id 3 (got {picker.pattern()})")
    check(picker.k_combo.get() == "13", f"the k dropdown shows 13 (got {picker.k_combo.get()!r})")
    check(picker.variant_combo.get() == T("const_calc.variant_label", id=3),
          f"the variant dropdown shows id 3 (got {picker.variant_combo.get()!r})")
    check(list(picker.variant_combo["values"]) ==
          [T("const_calc.variant_label", id=w["id"]) for w in pattern_catalog_v1.patterns_for_k(13)],
          "the variant list holds k=13's variants")
    check(len(seen) == 1, f"one change -> one on_change call (got {len(seen)})")

    # Strings as saved (settings hold text).
    picker.select(k="9", variant_id="4")
    check(picker.pattern()["k"] == 9 and picker.pattern()["id"] == 4, "select('9', '4') takes text")

    # An unknown id -> that k's first variant; an unknown k -> the first k.
    picker.select(k=8, variant_id=99)
    check(picker.pattern() == pattern_catalog_v1.patterns_for_k(8)[0], "unknown id -> first variant of k")
    picker.select(k=1000, variant_id=2)
    check(picker.pattern() == first, "unknown k -> first catalog pattern, no error")
    picker.select(k="abc", variant_id=None)
    check(picker.pattern() == first, "garbage k -> first catalog pattern, no error")

    # A k change in the dropdown picks that k's first variant and refreshes the info line.
    picker.select(k=13, variant_id=3)
    seen.clear()
    picker.k_combo.set("7")
    picker.k_combo.event_generate("<<ComboboxSelected>>")
    root.update()
    check(picker.pattern() == pattern_catalog_v1.patterns_for_k(7)[0], "k -> 7 selects k=7 id 1")
    check("0, 2, 6, 8, 12, 18, 20" in picker.info_var.get(), f"info line follows (got {picker.info_var.get()!r})")
    check(len(seen) == 1 and seen[0]["k"] == 7, "the k change fires on_change once")

    # A variant change in the dropdown.
    seen.clear()
    picker.variant_combo.current(1)
    picker.variant_combo.event_generate("<<ComboboxSelected>>")
    root.update()
    check(picker.pattern()["id"] == 2 and len(seen) == 1 and seen[0]["id"] == 2, "variant -> id 2")

    # Info line: tracked and untracked patterns, same texts the Calculator showed.
    tracked = pattern_catalog_v1.patterns_for_k(7)[0]
    check(pattern_info(T, tracked) == T("const_calc.pattern_info", offsets="0, 2, 6, 8, 12, 18, 20",
                                        record_digits=tracked["record_digits"],
                                        discoverer=tracked["discoverer"], date=tracked["date"]),
          "tracked pattern info = const_calc.pattern_info")
    twins = pattern_catalog_v1.patterns_for_k(2)[0]
    check(pattern_info(T, twins) == T("const_calc.pattern_info_untracked", offsets="0, 2"),
          "untracked pattern info = const_calc.pattern_info_untracked")
    picker.select(k=2)
    check(picker.info_var.get() == pattern_info(T, twins), "the info line shows pattern_info()")

    root.destroy()

    # The three users hold the one control (no copy of the cascade left behind).
    for module in ("primeatlas.constellations.constellations_calc_tab",
                   "primeatlas.generation.ktuple_section",
                   "primeatlas.visualization.rings.pattern_source"):
        src = _source(module)
        check("PatternPicker(" in src, f"{module} builds a PatternPicker")
        check("patterns_for_k(" not in src, f"{module} keeps no own k -> variant cascade")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
