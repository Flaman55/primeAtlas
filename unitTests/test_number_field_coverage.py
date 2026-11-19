"""Every entry field in primeatlas/ is a number field or says why it is not.

A line creating a ttk.Entry / tk.Entry / ttk.Spinbox passes when the field is made a number field
(number_field.attach on the same line or within the next ATTACH_LINES lines) or when the
line above it is a comment starting with MARKER, naming why the field is not read by
core.number_text (a path, a formula, a list, a fraction, its own parsing). A new field
without either fails here, so no number field misses the shared reader and its hint.
Every number_field.attach call passes the field's purpose (the locale key its hover tip
starts with); a literal key exists, not empty, in English and Polish. A key built at run
time is checked on the live fields by test_number_fields_app.
    python unitTests/test_number_field_coverage.py
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "primeatlas")
ATTACH_LINES = 5          # a constructor call may span several lines
MARKER = "# not a number field:"
ENTRY = re.compile(r"\b(?:ttk|tk)\.(?:Entry|Spinbox)\(")


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _locale(lang):
    path = os.path.join(PACKAGE, "core", "locales", f"strings_{lang}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _purpose(call):
    """The purpose argument of an attach() call (third positional or purpose=), or None."""
    if len(call.args) >= 3:
        return call.args[2]
    return next((k.value for k in call.keywords if k.arg == "purpose"), None)


def purpose_checks():
    passed = True
    locales = {lang: _locale(lang) for lang in ("en", "pl")}
    calls = literal = 0
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "attach"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "number_field"):
                    continue
                calls += 1
                where = f"{os.path.relpath(path, ROOT)}:{node.lineno}"
                purpose = _purpose(node)
                if purpose is None:
                    passed &= check(False, f"{where}: attach without the field's purpose")
                    continue
                if isinstance(purpose, ast.Constant) and isinstance(purpose.value, str):
                    literal += 1
                    for lang, strings in locales.items():
                        passed &= check(str(strings.get(purpose.value, "")).strip(),
                                        f"{where}: {lang} text for {purpose.value}")
    passed &= check(calls >= 80, f"{calls} attach calls checked ({literal} with a literal purpose key)")
    return passed


def main():
    passed = purpose_checks()
    attached = marked = 0
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            for i, line in enumerate(lines):
                if not ENTRY.search(line) or line.lstrip().startswith(("#", "return isinstance")):
                    continue
                where = f"{os.path.relpath(path, ROOT)}:{i + 1}"
                if any("number_field.attach(" in l for l in lines[i:i + 1 + ATTACH_LINES]):
                    attached += 1
                    continue
                above = lines[i - 1].strip() if i else ""
                if above.startswith(MARKER) and len(above) > len(MARKER) + 3:
                    marked += 1
                    continue
                passed &= check(False, f"{where}: neither a number field nor marked "
                                       f"'{MARKER} <why>'")
    passed &= check(attached >= 40, f"number fields attached at {attached} places")
    print(f"{marked} fields marked as not number fields")
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
