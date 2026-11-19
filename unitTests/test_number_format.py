"""
test_number_format.py -- core/number_format: every number shown to a person goes through one
formatter whose notation follows the interface language, or the notation picked in
Settings > General.

A. whole(): digit grouping per notation; zero, one digit, four digits (always grouped),
   negatives, 10^30 exact, numpy integers; a float is refused (no silent truncation).
B. decimal(): fixed places per notation, the integer part grouped; 0 places has no decimal
   mark; rounding and negative values as Python rounds them.
C. resolve(): "Follow language" maps pl and en to their notations; an explicit notation
   wins over the language; an unknown choice follows the language; an unknown language
   takes the English notation.
D. The running notation: number_format_dynamic.STYLE starts at the English notation; whole()
   and decimal() without a style use it; apply_saved() sets it from AppSettings.
E. AppSettings.number_format: "Follow language" on a fresh install, a set choice survives a
   reload, an unknown saved or set value reads as "Follow language".
F. sample(): the example each Settings entry shows.
G. Settings > General: a Number format list under the language with "Follow language" plus
   every notation, each label showing its example; it starts at the saved choice; picking
   another saves it and restarts once; picking the current one or an unknown label does
   nothing; locale keys exist in pl and en.
H. Views use the running notation: a HUD line, the Rings tab header, the Quick-gen plan and
   the benchmark table cell show the Polish notation when STYLE is set to it.
I. Guard: no f-string in primeatlas/ formats a number with "," or ".Nf" outside
   number_format itself and the listed machine-format sites (logs, CSV, CLI help, files).
J. The renderer process applies the saved notation at startup.

Usage:
    python unitTests/test_number_format.py
"""
import ast
import inspect
import os
import re
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, _SCRIPT_DIR)

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


NBSP = " "


def _import():
    try:
        from primeatlas.core import number_format, number_format_dynamic
        return number_format, number_format_dynamic
    except ImportError as error:
        check(False, f"core.number_format and core.number_format_dynamic import ({error})")
        return None, None


def _test_whole(nf):
    print("\n--- A. whole() ---")
    expected = {
        nf.SPACE_COMMA: f"1{NBSP}234{NBSP}567",
        nf.COMMA_DOT: "1,234,567",
        nf.DOT_COMMA: "1.234.567",
        nf.APOSTROPHE_DOT: "1'234'567",
        nf.PLAIN_DOT: "1234567",
    }
    check(set(expected) == set(nf.STYLES), "five notations")
    for style, text in expected.items():
        check(nf.whole(1234567, style) == text, f"{style}: 1234567 -> {text!r} "
                                                 f"(got {nf.whole(1234567, style)!r})")
        check(nf.whole(0, style) == "0", f"{style}: zero")
        check(nf.whole(7, style) == "7", f"{style}: one digit")
        check(nf.whole(-1234567, style) == "-" + text, f"{style}: negative")
    check(nf.whole(1234, nf.SPACE_COMMA) == f"1{NBSP}234", "four digits are grouped")
    check(nf.whole(999, nf.SPACE_COMMA) == "999", "three digits stay as they are")
    check(nf.whole(10 ** 30, nf.DOT_COMMA) == "1" + ".000" * 10, "10^30 exact")
    check(nf.whole(10 ** 30 + 1, nf.PLAIN_DOT) == str(10 ** 30 + 1), "10^30+1 exact, no float")
    try:
        import numpy as np
        check(nf.whole(np.int64(1234567), nf.COMMA_DOT) == "1,234,567", "numpy int64")
        check(nf.whole(np.uint64(2 ** 63), nf.COMMA_DOT) == f"{2 ** 63:,}", "numpy uint64")
    except ImportError:
        print("skip: numpy not installed")
    try:
        nf.whole(2.7, nf.COMMA_DOT)
        check(False, "a float is refused")
    except TypeError:
        check(True, "a float is refused")


def _test_decimal(nf):
    print("\n--- B. decimal() ---")
    expected = {
        nf.SPACE_COMMA: f"1{NBSP}234{NBSP}567,89",
        nf.COMMA_DOT: "1,234,567.89",
        nf.DOT_COMMA: "1.234.567,89",
        nf.APOSTROPHE_DOT: "1'234'567.89",
        nf.PLAIN_DOT: "1234567.89",
    }
    for style, text in expected.items():
        got = nf.decimal(1234567.891, 2, style)
        check(got == text, f"{style}: 1234567.891, 2 places -> {text!r} (got {got!r})")
    check(nf.decimal(0.5, 1, nf.SPACE_COMMA) == "0,5", "0.5 -> 0,5")
    check(nf.decimal(1.5, 0, nf.SPACE_COMMA) == "2", "0 places: rounded, no decimal mark")
    check(nf.decimal(12345.4, 0, nf.SPACE_COMMA) == f"12{NBSP}345", "0 places still grouped")
    check(nf.decimal(-1234.25, 1, nf.DOT_COMMA) == "-1.234,2", "negative, rounded as Python")
    check(nf.decimal(7, 2, nf.SPACE_COMMA) == "7,00", "an int with places")
    check(nf.decimal(1e15, 2, nf.COMMA_DOT) == "1,000,000,000,000,000.00", "1e15")
    check(nf.signed(1234.5, 1, nf.SPACE_COMMA) == f"+1{NBSP}234,5", "signed: + before a positive")
    check(nf.signed(-0.25, 2, nf.SPACE_COMMA) == "-0,25", "signed: a negative keeps its -")
    check(nf.signed(0, 2, nf.COMMA_DOT) == "+0.00", "signed: zero takes +")


def _test_resolve(nf):
    print("\n--- C. resolve() ---")
    check(nf.resolve(nf.FOLLOW_LANGUAGE, "pl") == nf.SPACE_COMMA, "follow + pl -> 1 234,5")
    check(nf.resolve(nf.FOLLOW_LANGUAGE, "en") == nf.COMMA_DOT, "follow + en -> 1,234.5")
    check(nf.resolve(nf.DOT_COMMA, "en") == nf.DOT_COMMA, "an explicit notation wins")
    check(nf.resolve(nf.PLAIN_DOT, "pl") == nf.PLAIN_DOT, "an explicit notation wins (pl)")
    check(nf.resolve("garbage", "pl") == nf.SPACE_COMMA, "unknown choice follows the language")
    check(nf.resolve(None, "en") == nf.COMMA_DOT, "missing choice follows the language")
    check(nf.resolve(nf.FOLLOW_LANGUAGE, "xx") == nf.COMMA_DOT, "unknown language -> English")
    check(nf.CHOICES[0] == nf.FOLLOW_LANGUAGE and set(nf.CHOICES[1:]) == set(nf.STYLES),
          "choices: Follow language first, then every notation")


def _test_running_style(nf, dyn):
    print("\n--- D. running notation ---")
    check(dyn.STYLE == nf.COMMA_DOT, f"STYLE starts at 1,234.5 (got {dyn.STYLE!r})")
    saved = dyn.STYLE
    try:
        dyn.STYLE = nf.SPACE_COMMA
        check(nf.whole(12345) == f"12{NBSP}345", "whole() uses STYLE")
        check(nf.decimal(2.25, 1) == "2,2", "decimal() uses STYLE")
        from primeatlas.core import app_settings as app_settings_module
        from primeatlas.core.app_settings import AppSettings
        orig = app_settings_module.LOCALES_DIR
        app_settings_module.LOCALES_DIR = tempfile.mkdtemp(prefix="number_format_test_")
        try:
            settings = AppSettings(_REPO_ROOT)
            settings.set_number_format(nf.APOSTROPHE_DOT)
            check(nf.apply_saved(settings) == nf.APOSTROPHE_DOT and dyn.STYLE == nf.APOSTROPHE_DOT,
                  "apply_saved() sets STYLE from the saved choice")
            settings.set_number_format(nf.FOLLOW_LANGUAGE)
            nf.apply_saved(settings)
            check(dyn.STYLE == nf.resolve(nf.FOLLOW_LANGUAGE, settings.language),
                  "apply_saved() with Follow language takes the language's notation")
        finally:
            app_settings_module.LOCALES_DIR = orig
    finally:
        dyn.STYLE = saved


def _test_app_settings(nf):
    print("\n--- E. AppSettings.number_format ---")
    from primeatlas.core import app_settings as app_settings_module
    from primeatlas.core.app_settings import AppSettings
    orig = app_settings_module.LOCALES_DIR
    app_settings_module.LOCALES_DIR = tempfile.mkdtemp(prefix="number_format_test_")
    try:
        settings = AppSettings(_REPO_ROOT)
        check(settings.number_format == nf.FOLLOW_LANGUAGE, "fresh install -> Follow language")
        settings.set_number_format(nf.DOT_COMMA)
        check(AppSettings(_REPO_ROOT).number_format == nf.DOT_COMMA, "a choice survives a reload")
        settings._data["number_format"] = "garbage"
        check(settings.number_format == nf.FOLLOW_LANGUAGE, "unknown saved -> Follow language")
        settings.set_number_format("garbage")
        check(AppSettings(_REPO_ROOT).number_format == nf.FOLLOW_LANGUAGE,
              "unknown set -> Follow language")
    finally:
        app_settings_module.LOCALES_DIR = orig


def _test_sample(nf):
    print("\n--- F. sample() ---")
    check(nf.sample(nf.SPACE_COMMA) == f"1{NBSP}234{NBSP}567,89", "1 234 567,89")
    check(nf.sample(nf.PLAIN_DOT) == "1234567.89", "1234567.89")


def _test_settings_tab(nf):
    print("\n--- G. Settings > General > Number format ---")
    import json
    for language in ("pl", "en"):
        path = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales", f"strings_{language}.json")
        with open(path, encoding="utf-8") as f:
            strings = json.load(f)
        for key in ("settings.number_format_label", "settings.number_format_follow",
                    "settings.number_format_restart_note"):
            check(key in strings, f"{language} locale has {key}")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    try:
        app.update()
        tab = app.settings_tab
        tab.app_settings.save = lambda: None
        var = getattr(tab, "number_format_var", None)
        check(var is not None, "General has a Number format list")
        if var is None:
            return
        labels = tab._number_format_labels_by_code
        check(list(labels) == list(nf.CHOICES), "the list holds Follow language + every notation")
        check(all(nf.sample(code) in labels[code] for code in nf.STYLES),
              "each notation label shows its example")
        check(var.get() == labels[tab.app_settings.number_format], "starts at the saved choice")
        restarts = []
        tab._restart_now_or_warn = lambda notice_translator: restarts.append(1)
        tab.app_settings.set_number_format(nf.FOLLOW_LANGUAGE)
        var.set(labels[nf.DOT_COMMA])
        tab._on_number_format_selected()
        check(tab.app_settings.number_format == nf.DOT_COMMA, "picking a notation saves it")
        check(restarts == [1], "picking a notation restarts once")
        tab._on_number_format_selected()
        check(restarts == [1], "picking the current notation does nothing")
        var.set("not a label")
        tab._on_number_format_selected()
        check(tab.app_settings.number_format == nf.DOT_COMMA and restarts == [1],
              "an unknown label does nothing")
    finally:
        app.destroy()


def _test_views(nf, dyn):
    print("\n--- H. views use the running notation ---")
    saved = dyn.STYLE
    dyn.STYLE = nf.SPACE_COMMA
    try:
        from primeatlas.visualization.sphere import sphere_hud
        source = inspect.getsource(sphere_hud)
        check("number_format" in source and ":,}" not in source, "sphere HUD uses number_format")
        from primeatlas.visualization.shared.hud_text import compose_hud_canvas_lines
        header = compose_hud_canvas_lines(1234567, 1234, [], False, 100)[0]
        check(f"1{NBSP}234{NBSP}567" in header and f"1{NBSP}234" in header,
              f"HUD header in the running notation (got {header!r})")
        from primeatlas.benchmark import table_columns
        check(table_columns._number_text(1234567.0, 0) == f"1{NBSP}234{NBSP}567",
              "benchmark table cell in the running notation")
        check(table_columns._number_text(0.25, 2) == "0,25", "benchmark decimal cell")
        check(table_columns._number_text(None, 2) == "", "an empty cell stays empty")
        from primeatlas.visualization.tree.tree_hud import count_text
        check(count_text(1234567) == f"1{NBSP}234{NBSP}567", "tree HUD count")
    finally:
        dyn.STYLE = saved


# Machine-format sites: log lines, CSV/file text, PDF/SVG drawing operators, CLI help and
# engine command lines keep Python's own notation. Path (relative to primeatlas/) -> number
# of number format specs in that file.
MACHINE_FORMAT = {
    "benchmark/chart_svg.py": 15,                   # SVG coordinates and attributes
    "benchmark/proof_rows.py": 4,                   # CSV row fields read back with float()
    "core/pdf_writer.py": 33,                       # PDF content-stream operators
    "generation/run_guard.py": 1,                   # stop-request file content
    "research/research_pi_approx_tab.py": 4,        # CSV export
    "visualization/rings/line/line_mode.py": 7,     # print() lines, the tab console log
    "visualization/rings/ring/ring_mode.py": 3,     # print() lines
    "visualization/shared/renderer_launch.py": 14,  # print() lines
    "visualization/shared/session.py": 7,           # print() lines and messages printed
    "visualization/shared/shaders.py": 1,           # GLSL source
    "visualization/shared/viz_tab_base.py": 1,      # the launch line of the tab console log
    "visualization/sphere/sphere_mode.py": 1,       # argparse --help text
    "visualization/tree/tree_mode.py": 5,           # print() lines
}

_SPEC = re.compile(r"(?:,|\.\d+f)")
_TEMPLATE = re.compile(r"\{[^{}]*:[^{}]*(?:,|\.\d+f)[^{}]*\}")


def _format_specs(path):
    """Number format specs in a source file: f-string fields formatted with "," or ".Nf" and
    str.format() templates such as "{:,.0f}" (docstrings excluded)."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr)                     and isinstance(node.body[0].value, ast.Constant):
                docstrings.add(id(node.body[0].value))
    count = 0
    in_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in ast.walk(node):
                in_fstring.add(id(part))
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(v.value for v in node.format_spec.values
                           if isinstance(v, ast.Constant))
            count += bool(_SPEC.search(spec))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str)                 and id(node) not in in_fstring and id(node) not in docstrings:
            count += len(_TEMPLATE.findall(node.value))
    return count


def _test_guard():
    print("\n--- I. guard: no number formatting outside number_format ---")
    package = os.path.join(_REPO_ROOT, "primeatlas")
    offenders = []
    for folder, _dirs, files in os.walk(package):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            relative = os.path.relpath(path, package).replace(os.sep, "/")
            if relative == "core/number_format.py":
                continue
            found = _format_specs(path)
            if found != MACHINE_FORMAT.get(relative, 0):
                offenders.append(f"{relative}: {found} (allowed {MACHINE_FORMAT.get(relative, 0)})")
    check(not offenders, "every number shown to a person goes through number_format"
          + ("" if not offenders else "\n      " + "\n      ".join(offenders)))
    import json
    for language in ("pl", "en"):
        path = os.path.join(package, "core", "locales", f"strings_{language}.json")
        with open(path, encoding="utf-8") as f:
            strings = json.load(f)
        keys = sorted(k for k, v in strings.items() if _TEMPLATE.search(v))
        check(not keys, f"{language} locale formats no number itself" + (f": {keys}" if keys else ""))


def _test_renderer():
    print("\n--- J. renderer applies the saved notation ---")
    from primeatlas.visualization.shared import renderer
    source = inspect.getsource(renderer.main)
    check("apply_saved" in source, "renderer.main() applies the saved notation")


def main():
    nf, dyn = _import()
    if nf is not None:
        _test_whole(nf)
        _test_decimal(nf)
        _test_resolve(nf)
        _test_running_style(nf, dyn)
        _test_app_settings(nf)
        _test_sample(nf)
        _test_settings_tab(nf)
        _test_views(nf, dyn)
        _test_renderer()
    _test_guard()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for message in failures:
            print(f"  - {message}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
