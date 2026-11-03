"""
test_ktuple_sieve_v2_1.py -- ktuple_sieve_v2_1.py and its three sibling modules
(ktuple_wheel_v2_1.py, ktuple_locations_v2_1.py, ktuple_hit_store_v2_1.py) run the same
code as the single-file ktuple_sieve_v2.py:

  - every top-level function, constant and the __main__ block of v2 is defined in exactly
    one v2_1 module with the same syntax tree, once docstrings are set aside and the
    start banner's "[KTUPLE SIEVE v2.1]" and "constellation_finder_v2_1" wording are mapped
    back to their v2 spelling; no v2_1 module defines anything v2 does not;
  - a mutated copy of v2 (one changed constant) is reported as different, so the check
    cannot pass by comparing nothing;
  - every v2_1 file stays under the 1000-line ceiling;
  - the same manual_list job, run as a script through v2 and v2_1 against two fresh
    portals, prints the same lines (v2_1 spellings mapped back) and writes the same files.

The gap-safe hit recording of v2_1 itself is covered by
test_ktuple_sieve_v2_provisional.py, which runs its scenario against both versions.

Run (no WSL needed):
    python unitTests\\test_ktuple_sieve_v2_1.py
"""
import ast
import os
import shutil
import subprocess
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CONSTELLATION_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "constellation")
V2 = os.path.join(_CONSTELLATION_DIR, "ktuple_sieve_v2.py")
V2_1_FILES = [os.path.join(_CONSTELLATION_DIR, name) for name in (
    "ktuple_sieve_v2_1.py", "ktuple_wheel_v2_1.py",
    "ktuple_locations_v2_1.py", "ktuple_hit_store_v2_1.py")]
MAX_LINES = 1000
_STRING_MAP = (("[KTUPLE SIEVE v2.1]", "[KTUPLE SIEVE v2]"),
               ("constellation_finder_v2_1", "constellation_finder_v2"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _normalize(node):
    """Drops docstrings and maps the v2_1 spellings in string constants back to v2."""
    for sub in ast.walk(node):
        body = getattr(sub, "body", None)
        if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            sub.body = body[1:] or [ast.Pass()]
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            for new, old in _STRING_MAP:
                sub.value = sub.value.replace(new, old)
    return ast.dump(node, include_attributes=False)


def top_level_units(source):
    """{name: normalized dump} for every def, simple assignment and the __main__ block."""
    units = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            units[node.name] = _normalize(node)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id != "_SCRIPT_DIR"):
            units[node.targets[0].id] = _normalize(node)
        elif (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
              and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"):
            units["__main__"] = _normalize(node)
    return units


def compare_units(v2_source, v2_1_sources):
    """Returns the list of mismatch descriptions between v2 and the v2_1 modules."""
    v2_units = top_level_units(v2_source)
    problems = []
    found = {}
    for path, source in v2_1_sources.items():
        for name, dump in top_level_units(source).items():
            if name in found:
                problems.append(f"{name} is defined in both {found[name][0]} and {path}")
            found[name] = (path, dump)
    for name, dump in v2_units.items():
        if name not in found:
            problems.append(f"{name} is missing from v2_1")
        elif found[name][1] != dump:
            problems.append(f"{name} differs ({os.path.basename(found[name][0])})")
    for name in found:
        if name not in v2_units:
            problems.append(f"{name} is new in v2_1")
    return problems


def run_manual_list(script, portal):
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    result = subprocess.run(
        [sys.executable, script, "2", "2", "1", "--strategy", "manual_list",
         "--manual-offsets", "0", "300", "--window-m", "100"],
        capture_output=True, text=True, env=env, timeout=120)
    lines = result.stdout.splitlines()
    for new, old in _STRING_MAP:
        lines = [line.replace(new, old) for line in lines]
    files = {}
    for root, _dirs, names in os.walk(portal):
        for name in names:
            path = os.path.join(root, name)
            with open(path, "rb") as f:
                files[os.path.relpath(path, portal)] = f.read()
    return result.returncode, lines, files, result.stderr


def main():
    with open(V2, encoding="utf-8") as f:
        v2_source = f.read()
    v2_1_sources = {}
    for path in V2_1_FILES:
        check(os.path.exists(path), f"{os.path.basename(path)} exists")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                v2_1_sources[path] = f.read()

    if len(v2_1_sources) == len(V2_1_FILES):
        problems = compare_units(v2_source, v2_1_sources)
        for problem in problems:
            print(f"      {problem}")
        check(not problems, "every function, constant and the __main__ block of "
                            "ktuple_sieve_v2.py is in exactly one v2_1 module, unchanged")
        check(len(top_level_units(v2_source)) > 30,
              "the comparison covers v2's top-level definitions (sanity)")

        mutated = v2_source.replace("FLOOR_WIDTH_MULTIPLIER = 9", "FLOOR_WIDTH_MULTIPLIER = 8")
        check(mutated != v2_source and compare_units(mutated, v2_1_sources),
              "a mutated copy of v2 is reported as different")

        for path, source in v2_1_sources.items():
            n = source.count("\n")
            check(n <= MAX_LINES, f"{os.path.basename(path)} has {n} lines (<= {MAX_LINES})")

    portal_v2 = tempfile.mkdtemp(prefix="primeatlas_ktuple_v2_cli_")
    portal_v2_1 = tempfile.mkdtemp(prefix="primeatlas_ktuple_v2_1_cli_")
    try:
        rc_a, out_a, files_a, err_a = run_manual_list(V2, portal_v2)
        rc_b, out_b, files_b, err_b = run_manual_list(V2_1_FILES[0], portal_v2_1)
        if rc_b != 0:
            print(err_b)
        check(rc_a == 0 and rc_b == 0, f"both scripts exit 0 (v2={rc_a}, v2_1={rc_b})")
        check(out_a == out_b and len(out_a) > 2,
              "v2 and v2_1 print the same lines for the same manual_list job")
        check(files_a == files_b and files_a,
              f"v2 and v2_1 write the same files with the same bytes "
              f"({sorted(files_a)} vs {sorted(files_b)})")
    finally:
        shutil.rmtree(portal_v2, ignore_errors=True)
        shutil.rmtree(portal_v2_1, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
