"""
test_rings_pattern_source.py -- primeatlas/visualization/rings/pattern_source.py's
PatternSource, line mode's pattern choice in the Rings tab: From the list (a catalog
PatternPicker), Manual (k and p0, with a how-to line and a live preview of the offsets) or
None.

Checks: the first-run default and every saved-settings case (new keys, an older save
without a mode, a k/id no longer in the catalog, an unknown mode); which controls show per
mode; what each mode launches with (valid and invalid manual input); the live preview
(catalog, outside the catalog, empty, invalid, too large to compute while typing); values
kept across mode switches; the saved parameters; the widgets locked while paused.
Windows, real display:
    python unitTests/test_rings_pattern_source.py
"""
import os
import sys
import tkinter as tk

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_REPO_ROOT, os.path.join(_REPO_ROOT, "prime_sieve"),
                os.path.join(_REPO_ROOT, "constellation")]

import pattern_catalog_v1  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

# Preview texts hold an arrow a cp1252 console cannot print.
sys.stdout.reconfigure(errors="replace")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


T = Translator("en").t


def _make(root, saved):
    from primeatlas.visualization.rings.pattern_source import PatternSource
    source = PatternSource(root, T, saved)
    source.frame.pack(fill="x")
    root.update()
    return source


def _type(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


def _shown(source, root):
    root.update()
    return (bool(source.list_frame.winfo_ismapped()), bool(source.manual_frame.winfo_ismapped()))


def main():
    from primeatlas.visualization.rings.pattern_source import PREVIEW_K_MAX, PREVIEW_P0_MAX

    root = tk.Tk()

    # 16: first run -> From the list, k=2 id 1 (twins).
    source = _make(root, {})
    check(source.source_var.get() == "list", f"first run: From the list (got {source.source_var.get()!r})")
    check(source.picker.pattern() == pattern_catalog_v1.patterns_for_k(2)[0], "first run: k=2 id 1")
    check(source.launch_pattern() == {"pattern_seed_k": None, "pattern_seed_start": None,
                                      "pattern_offsets": [0, 2]},
          f"list mode launches the catalog offsets (got {source.launch_pattern()})")

    # 1: only the selected mode's controls show.
    check(_shown(source, root) == (True, False), "list mode: the picker shows, the k/p0 fields do not")
    source.source_var.set("manual")
    check(_shown(source, root) == (False, True), "manual mode: the k/p0 fields show, the picker does not")
    source.source_var.set("none")
    check(_shown(source, root) == (False, False), "none: neither shows")
    source.source_var.set("list")
    check(_shown(source, root) == (True, False), "back to list: the picker shows again")
    radios = [w for w in source.radios]
    check([str(r["value"]) for r in radios] == ["list", "manual", "none"],
          f"three radios in order List / Manual / None (got {[str(r['value']) for r in radios]})")

    # 3: list mode's info line is the picker's.
    source.picker.select(k=7, variant_id=1)
    root.update()
    check("0, 2, 6, 8, 12, 18, 20" in source.picker.info_var.get(), "list mode shows the offsets info line")
    check(source.launch_pattern()["pattern_offsets"] == [0, 2, 6, 8, 12, 18, 20], "list launches k=7 id 1")
    source.frame.pack_forget()

    # 17, 18: saved settings.
    cases = [
        ({"pattern_k": "7", "pattern_p0": "11"}, "manual"),
        ({"pattern_k": "", "pattern_p0": ""}, "list"),
        ({"pattern_k": "7", "pattern_p0": ""}, "manual"),
        ({"pattern_source": "none", "pattern_k": "7", "pattern_p0": "11"}, "none"),
        ({"pattern_source": "list", "pattern_k": "7", "pattern_p0": "11"}, "list"),
        ({"pattern_source": "bogus"}, "list"),
    ]
    for saved, want in cases:
        source = _make(root, saved)
        check(source.source_var.get() == want, f"saved {saved} -> {want} (got {source.source_var.get()!r})")
        check(source.k_entry.get() == saved.get("pattern_k", "")
              and source.p0_entry.get() == saved.get("pattern_p0", ""),
              f"saved {saved}: the manual fields keep their text")
        source.frame.pack_forget()
    source = _make(root, {"pattern_source": "list", "pattern_list_k": "13", "pattern_list_id": "3"})
    check(source.picker.pattern()["k"] == 13 and source.picker.pattern()["id"] == 3, "saved list k=13 id 3")
    source.frame.pack_forget()
    source = _make(root, {"pattern_source": "list", "pattern_list_k": "99", "pattern_list_id": "1"})
    check(source.picker.pattern() == pattern_catalog_v1.patterns_for_k(2)[0],
          "a saved k not in the catalog -> the first pattern, no error")
    source.frame.pack_forget()
    source = _make(root, {"pattern_source": "list", "pattern_list_k": "8", "pattern_list_id": "77"})
    check(source.picker.pattern() == pattern_catalog_v1.patterns_for_k(8)[0],
          "a saved id not in the catalog -> that k's first variant")
    source.frame.pack_forget()

    # 5, 9, 10: manual mode launches the seed; empty or invalid input launches nothing.
    source = _make(root, {"pattern_source": "manual"})
    check(source.hint_var.get() == T("rings.pattern_manual_hint"), "manual mode has its how-to line")
    _type(source.k_entry, "4")
    _type(source.p0_entry, "5")
    check(source.launch_pattern() == {"pattern_seed_k": 4, "pattern_seed_start": 5, "pattern_offsets": None},
          f"manual k=4 p0=5 -> the seed flags (got {source.launch_pattern()})")
    _type(source.p0_entry, "10**12")
    check(source.launch_pattern()["pattern_seed_start"] == 10 ** 12, "p0 takes the app's number forms")
    for k_text, p0_text in (("", ""), ("4", ""), ("", "5"), ("1", "5"), ("4", "2"), ("abc", "5"), ("4", "x")):
        _type(source.k_entry, k_text)
        _type(source.p0_entry, p0_text)
        check(source.launch_pattern() is None, f"manual k={k_text!r} p0={p0_text!r} -> invalid (None)")

    # 11: none launches no pattern.
    source.source_var.set("none")
    check(source.launch_pattern() == {"pattern_seed_k": None, "pattern_seed_start": None,
                                      "pattern_offsets": None}, "none -> no pattern flags")

    # 6: the live preview follows every keystroke.
    source.source_var.set("manual")

    def preview(k_text, p0_text):
        _type(source.k_entry, k_text)
        _type(source.p0_entry, p0_text)
        root.update()
        return source.preview_var.get()

    check(preview("4", "5") == T("rings.pattern_preview_catalog", offsets="0, 2, 6, 8", k=4, id=1),
          f"k=4 p0=5 -> catalog k=4 id 1 (got {source.preview_var.get()!r})")
    check(preview("3", "7") == T("rings.pattern_preview_other", offsets="0, 4, 6"),
          f"k=3 p0=7 (7, 11, 13) -> outside the catalog (got {source.preview_var.get()!r})")
    check(preview("7", "11") == T("rings.pattern_preview_catalog", offsets="0, 2, 6, 8, 12, 18, 20", k=7, id=1),
          "k=7 p0=11 -> catalog k=7 id 1")
    check(preview("", "") == "" and preview("4", "") == "" and preview("1", "5") == ""
          and preview("4", "2") == "" and preview("x", "5") == "",
          "empty or invalid fields -> empty preview, no dialog")
    check(preview("4", str(PREVIEW_P0_MAX)) .startswith("→"), "p0 at the limit still previews")
    check(preview("4", str(PREVIEW_P0_MAX + 1)) == T("rings.pattern_preview_at_start"),
          "p0 past the limit -> 'computed when the window starts'")
    check(preview(str(PREVIEW_K_MAX + 1), "5") == T("rings.pattern_preview_at_start"),
          "k past the limit -> 'computed when the window starts'")
    check(PREVIEW_P0_MAX == 10 ** 9, "the preview limit is 10^9 (criterion 6)")

    # 15: values survive mode switches; saved parameters hold each mode's own values.
    _type(source.k_entry, "5")
    _type(source.p0_entry, "11")
    source.source_var.set("list")
    source.picker.select(k=13, variant_id=3)
    source.source_var.set("manual")
    source.source_var.set("list")
    check(source.k_entry.get() == "5" and source.p0_entry.get() == "11", "manual values survive switching")
    check(source.picker.pattern()["k"] == 13 and source.picker.pattern()["id"] == 3,
          "the list selection survives switching")
    check(source.saved_params() == {"pattern_source": "list", "pattern_k": "5", "pattern_p0": "11",
                                    "pattern_list_k": "13", "pattern_list_id": "3"},
          f"saved parameters (got {source.saved_params()})")

    # 14: the widgets locked while paused.
    entries, buttons, dropdowns = source.lock_widgets()
    check(source.k_entry in entries and source.p0_entry in entries, "the k/p0 fields lock")
    check(all(r in buttons for r in source.radios), "the three radios lock")
    check(source.picker.k_combo in dropdowns and source.picker.variant_combo in dropdowns, "both dropdowns lock")

    root.destroy()
    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
