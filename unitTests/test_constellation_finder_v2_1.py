"""
test_constellation_finder_v2_1.py -- constellation_finder_v2_1.py runs the same code as
constellation_finder_v2.py: their syntax trees match once docstrings and the start banner
are set aside (comments are not part of the tree). The v2 test files therefore cover v2_1.

A mutated copy of v2 (one changed constant) must be reported as different, so the check
cannot pass by comparing nothing.

Run (no WSL needed):
    python unitTests\\test_constellation_finder_v2_1.py
"""
import ast
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CONSTELLATION_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "constellation")
V2 = os.path.join(_CONSTELLATION_DIR, "constellation_finder_v2.py")
V2_1 = os.path.join(_CONSTELLATION_DIR, "constellation_finder_v2_1.py")
BANNER_PREFIX = "[*] CONSTELLATION FINDER -- v2"

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def normalized_tree(source):
    """ast.dump of `source` without docstrings and with the start banner text blanked."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.startswith(BANNER_PREFIX)):
            node.value = BANNER_PREFIX
    return ast.dump(tree, include_attributes=False)


def main():
    with open(V2, encoding="utf-8") as f:
        v2_source = f.read()
    with open(V2_1, encoding="utf-8") as f:
        v2_1_source = f.read()

    check(v2_source != v2_1_source, "v2_1 is a separate file (its comments differ from v2)")
    check(normalized_tree(v2_source) == normalized_tree(v2_1_source),
          "constellation_finder_v2_1.py has the same code as constellation_finder_v2.py")
    check("CONSTELLATION FINDER -- v2.1 " in v2_1_source,
          "v2_1's start banner names version 2.1")

    mutated = v2_source.replace("DONE_LOG_FILENAME = ", "DONE_LOG_FILENAME = 'x' + ", 1)
    check(mutated != v2_source and normalized_tree(mutated) != normalized_tree(v2_source),
          "a one-constant change to the code is detected")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
