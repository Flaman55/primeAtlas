"""
test_theme_readability.py -- readability settings and the app-wide styles they feed.

A. theme.py: shift_color() blends toward white (+) / black (-); adjusted_palette()
   shifts exactly the background keys by `background` and the text keys by `text`,
   is the identity at 0/0, and clamps out-of-range shifts; hint_fg/disabled_fg reach
   WCAG AA (4.5:1) on bg in both themes; tree_alt_bg differs from tree_bg.
B. AppSettings: per-theme brightness (background/text) defaults to 0/0, is stored per
   theme, survives a reload, is clamped, garbage -> default; font_scale defaults to
   100, survives a reload, is clamped, garbage -> default.
C. StripedTreeview: every second VISIBLE row carries the stripe tag -- after inserts,
   opening/closing a node, deletes; rows whose own tag sets a background are never
   striped; set_stripe_background() recolors live trees and trees built later.
D. RevealFrame: hidden until reveal(True); reveal(True, before=w) keeps the order
   when w is packed, packs at the end when w is hidden.
E. Source scan: no raw ttk.Treeview( outside widgets.py; no hard-coded grey
   foreground on labels (they use the Hint.TLabel style).
F. Real app: Hint.TLabel / Status.TLabel styles come from the adjusted palette, the
   status line is bold, the stripe tag uses tree_alt_bg, Treeview rowheight follows
   the font, a brightness shift reaches ttk.Style, font_scale enlarges every named
   font, and Benchmark gets the adjusted palette.

Usage:
    python unitTests/test_theme_readability.py
"""
import os
import re
import sys
import tempfile
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core import app_settings as app_settings_module  # noqa: E402
from primeatlas.core import theme  # noqa: E402
from primeatlas.core import widgets  # noqa: E402
from primeatlas.core.app_settings import AppSettings  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _test_palette():
    print("\n--- A. theme.adjusted_palette ---")
    check(theme.shift_color("#808080", 0) == "#808080", "shift 0 is the identity")
    check(theme.shift_color("#000000", 50) == "#808080", "+50 blends halfway to white")
    check(theme.shift_color("#ffffff", -50) == "#808080", "-50 blends halfway to black")
    check(theme.shift_color("#2b2b2b", 100) == "#ffffff", "+100 is white")
    for name in ("dark", "light"):
        base = theme.THEMES[name]
        check(theme.adjusted_palette(name, 0, 0) == base, f"{name}: 0/0 is the identity")
        check(base is not theme.adjusted_palette(name, 0, 0), f"{name}: a copy, not THEMES itself")
        shifted = theme.adjusted_palette(name, 20, -30)
        for key in theme.BACKGROUND_KEYS:
            check(shifted[key] == theme.shift_color(base[key], 20), f"{name}: {key} follows background")
        for key in theme.TEXT_KEYS:
            check(shifted[key] == theme.shift_color(base[key], -30), f"{name}: {key} follows text")
        for key in set(base) - set(theme.BACKGROUND_KEYS) - set(theme.TEXT_KEYS):
            check(shifted[key] == base[key], f"{name}: {key} (selection/accent) is untouched")
        clamped = theme.adjusted_palette(name, 999, -999)
        check(clamped == theme.adjusted_palette(name, theme.BRIGHTNESS_MAX, theme.BRIGHTNESS_MIN),
              f"{name}: out-of-range shifts are clamped")
        for key in ("hint_fg", "disabled_fg"):
            ratio = _contrast(base[key], base["bg"])
            check(ratio >= 4.5, f"{name}: {key} on bg reaches 4.5:1 (got {ratio:.2f})")
        check(base["tree_alt_bg"] != base["tree_bg"], f"{name}: stripe color differs from tree_bg")
    check(set(theme.BACKGROUND_KEYS).isdisjoint(theme.TEXT_KEYS), "no key is both bg and text")
    check(theme.clamp_brightness("x") == theme.BRIGHTNESS_DEFAULT == 0, "brightness garbage -> 0")
    check(theme.clamp_font_scale(None) == theme.FONT_SCALE_DEFAULT == 100, "font scale garbage -> 100")
    check(theme.clamp_font_scale(10) == theme.FONT_SCALE_MIN, "font scale clamped to min")
    check(theme.clamp_font_scale(10_000) == theme.FONT_SCALE_MAX, "font scale clamped to max")


def _test_app_settings():
    print("\n--- B. AppSettings brightness / font scale ---")
    orig = app_settings_module.LOCALES_DIR
    app_settings_module.LOCALES_DIR = tempfile.mkdtemp(prefix="readability_test_")
    try:
        settings = AppSettings(_REPO_ROOT)
        check(settings.theme_brightness("dark") == (0, 0), "fresh install -> dark 0/0")
        check(settings.font_scale == 100, "fresh install -> font scale 100")
        settings.set_theme_brightness("dark", 15, -10)
        check(settings.theme_brightness("dark") == (15, -10), "dark brightness stored")
        check(settings.theme_brightness("light") == (0, 0), "light keeps its own values")
        settings.set_font_scale(130)
        reloaded = AppSettings(_REPO_ROOT)
        check(reloaded.theme_brightness("dark") == (15, -10), "brightness survives a reload")
        check(reloaded.font_scale == 130, "font scale survives a reload")
        settings.set_theme_brightness("light", 500, -500)
        check(settings.theme_brightness("light") == (theme.BRIGHTNESS_MAX, theme.BRIGHTNESS_MIN),
              "brightness is clamped")
        settings._data["theme_brightness"] = {"dark": "garbage"}
        check(settings.theme_brightness("dark") == (0, 0), "garbage brightness -> 0/0")
        settings._data["font_scale"] = "big"
        check(settings.font_scale == 100, "garbage font scale -> 100")
    finally:
        app_settings_module.LOCALES_DIR = orig


def _striped(tree):
    return [iid for iid in _visible(tree) if widgets.STRIPE_TAG in tree.item(iid, "tags")]


def _visible(tree, parent=""):
    rows = []
    for iid in tree.get_children(parent):
        rows.append(iid)
        if tree.item(iid, "open"):
            rows.extend(_visible(tree, iid))
    return rows


def _expected(tree):
    return _visible(tree)[1::2]


def _test_striped_tree(root):
    print("\n--- C. StripedTreeview ---")
    widgets.set_stripe_background("#123456")
    tree = widgets.StripedTreeview(root, columns=("a",))
    tree.tag_configure("own", background="#654321")
    parents = [tree.insert("", "end", text=f"p{i}") for i in range(5)]
    for p in parents:
        for j in range(3):
            tree.insert(p, "end", text=f"c{j}")
    root.update()
    check(_striped(tree) == _expected(tree) and len(_striped(tree)) == 2,
          f"every second top-level row is striped ({len(_striped(tree))})")
    tree.item(parents[1], open=True)
    root.update()
    check(_striped(tree) == _expected(tree), "opening a node restripes the visible rows")
    tree.item(parents[1], open=False)
    root.update()
    check(_striped(tree) == _expected(tree), "closing a node restripes the visible rows")
    tree.delete(parents[0])
    root.update()
    check(_striped(tree) == _expected(tree), "deleting a row restripes")
    special = tree.insert("", 1, text="own", tags=("own",))
    root.update()
    check(widgets.STRIPE_TAG not in tree.item(special, "tags"),
          "a row whose own tag sets a background is never striped")
    check("own" in tree.item(special, "tags"), "the row keeps its own tag")
    check(str(tree.tag_configure(widgets.STRIPE_TAG, "background")) == "#123456",
          "stripe tag uses the configured color")
    widgets.set_stripe_background("#abcdef")
    later = widgets.StripedTreeview(root)
    check(str(tree.tag_configure(widgets.STRIPE_TAG, "background")) == "#abcdef",
          "set_stripe_background() recolors a live tree")
    check(str(later.tag_configure(widgets.STRIPE_TAG, "background")) == "#abcdef",
          "a tree built afterwards gets the new color")


def _test_reveal_frame(root):
    print("\n--- D. RevealFrame ---")
    host = ttk.Frame(root)
    host.pack()
    first = widgets.RevealFrame(host, fill="x")
    second = widgets.RevealFrame(host, fill="both", expand=True)
    root.update()
    check(first.winfo_manager() == "" and second.winfo_manager() == "", "hidden until revealed")
    second.reveal(True)
    first.reveal(True, before=second)
    check(host.pack_slaves() == [first, second], "before= keeps the order when packed")
    check(first.pack_info()["fill"] == "x" and str(second.pack_info()["expand"]) in ("1", "True"),
          "pack options are the ones given at construction")
    first.reveal(False)
    second.reveal(False)
    first.reveal(True, before=second)
    second.reveal(True)
    check(host.pack_slaves() == [first, second], "before= a hidden widget packs at the end")
    first.reveal(True)
    check(host.pack_slaves().count(first) == 1, "revealing twice does not duplicate")
    check(first.visible and second.visible, "visible reflects the state")


def _sources():
    for base in ("primeatlas", ):
        for dirpath, _dirs, files in os.walk(os.path.join(_REPO_ROOT, base)):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as f:
                        yield path, f.read()
    path = os.path.join(_REPO_ROOT, "prime_atlas_v2.py")
    with open(path, encoding="utf-8") as f:
        yield path, f.read()


def _test_sources():
    print("\n--- E. source scan ---")
    raw_trees, grey_labels = [], []
    grey = re.compile(r'foreground="#(?:5{3}|5{6}|7{3}|7{6}|8{6})"')
    for path, text in _sources():
        rel = os.path.relpath(path, _REPO_ROOT)
        if "ttk.Treeview(" in text and not rel.endswith(os.path.join("core", "widgets.py")):
            raw_trees.append(rel)
        if grey.search(text):
            grey_labels.append(rel)
    check(not raw_trees, f"every table is a StripedTreeview (raw ttk.Treeview in {raw_trees})")
    check(not grey_labels, f"no hard-coded grey label text (found in {grey_labels})")


def _build_app(font_scale=100, brightness=(0, 0)):
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    import prime_atlas_v2
    sys.argv = ["prime_atlas_v2.py"]
    settings = prime_atlas_v2.APP_SETTINGS
    settings.save = lambda: None
    settings.set_font_scale(font_scale)
    settings.set_theme_brightness(settings.theme, *brightness)
    return prime_atlas_v2._build_gui()(), settings


def _test_app():
    print("\n--- F. real app ---")
    app, settings = _build_app()
    try:
        app.update()
        style = ttk.Style(app)
        p = theme.adjusted_palette(settings.theme, 0, 0)
        check(str(style.lookup("Hint.TLabel", "foreground")) == p["hint_fg"],
              "Hint.TLabel uses the palette's hint_fg")
        status_font = tkfont.Font(root=app, font=style.lookup("Status.TLabel", "font"))
        check(status_font.actual("weight") == "bold", "the status line is bold")
        status_labels = [w for w in app._status_frame.winfo_children()
                         if isinstance(w, ttk.Label) and str(w.cget("style")) == "Status.TLabel"]
        check(len(status_labels) == 1, "the status label uses Status.TLabel")
        check(widgets.STRIPE_BACKGROUND == p["tree_alt_bg"], "stripes use tree_alt_bg")
        linespace = tkfont.nametofont("TkDefaultFont", root=app).metrics("linespace")
        check(int(style.lookup("Treeview", "rowheight")) == linespace + 2,
              "Treeview rowheight follows the font")
        tab_map = [(tuple(str(s) for s in spec[:-1]), str(spec[-1]))
                   for spec in style.map("TNotebook.Tab", "background")]
        button_hover = [c for states, c in
                        [(tuple(str(s) for s in spec[:-1]), str(spec[-1]))
                         for spec in style.map("TButton", "background")] if states == ("active",)]
        check((("active",), p["select_bg"]) in tab_map and button_hover == [p["select_bg"]],
              f"a hovered tab is highlighted like a hovered button ({tab_map})")
        states_order = [states for states, _c in tab_map]
        check(("selected",) in states_order and ("active",) in states_order
              and states_order.index(("selected",)) < states_order.index(("active",)),
              "the selected tab keeps its own color while hovered")
        check(app.benchmark_tab_widget._theme_palette == app._palette,
              "Benchmark gets the adjusted palette")
        base_space = linespace
    finally:
        app.destroy()

    app, settings = _build_app(font_scale=150, brightness=(20, -20))
    try:
        app.update()
        style = ttk.Style(app)
        p = theme.adjusted_palette(settings.theme, 20, -20)
        check(str(style.lookup(".", "background")) == p["bg"], "a background shift reaches ttk")
        check(str(style.lookup(".", "foreground")) == p["fg"], "a text shift reaches ttk")
        big = tkfont.nametofont("TkDefaultFont", root=app).metrics("linespace")
        check(big >= base_space * 1.35, f"font scale 150 enlarges the default font ({base_space} -> {big})")
        mono = tkfont.Font(root=app, family="Consolas", size=9).metrics("linespace")
        check(mono > 15, f"explicit point-size fonts scale too (Consolas 9 -> {mono}px)")
        check(int(style.lookup("Treeview", "rowheight")) == big + 2, "rowheight follows the scaled font")
    finally:
        settings.set_font_scale(100)
        settings.set_theme_brightness(settings.theme, 0, 0)
        app.destroy()


def main():
    _test_palette()
    _test_app_settings()
    root = tk.Tk()
    root.withdraw()
    try:
        _test_striped_tree(root)
        _test_reveal_frame(root)
    finally:
        root.destroy()
    _test_sources()
    _test_app()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a missing API must show up as FAIL, not only a traceback
        import traceback
        traceback.print_exc()
        failures.append(f"crashed: {exc!r}")
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
