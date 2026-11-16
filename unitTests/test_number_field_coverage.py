"""Every entry field in primeatlas/ is a number field or says why it is not.

A line creating a ttk.Entry / tk.Entry passes when the field is made a number field
(number_field.attach on the same line or within the next ATTACH_LINES lines) or when the
line above it is a comment starting with MARKER, naming why the field is not read by
core.number_text (a path, a formula, a list, a fraction, its own parsing). A new field
without either fails here, so no number field misses the shared reader and its hint.
    python unitTests/test_number_field_coverage.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "primeatlas")
ATTACH_LINES = 3
MARKER = "# not a number field:"
ENTRY = re.compile(r"\b(?:ttk|tk)\.Entry\(")


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def main():
    passed = True
    attached = marked = 0
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            for i, line in enumerate(lines):
                if not ENTRY.search(line):
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
