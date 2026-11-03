"""
test_constellation_finder_v2_2.py -- constellation_finder_v2_2.py and its sibling modules
(constellation_const/_dynamic/_diag/_windows/_progress/_hits/_match_v2_2.py) run the same
code as the single-file constellation_finder_v2.py:

  - every top-level function, constant and the __main__ block of v2 is defined in exactly
    one v2_2 module with the same syntax tree, once docstrings are set aside, the
    `_const.NAME` / `_dyn.NAME` module references are read as the bare NAME, and the start
    banner's version is mapped back; no v2_2 module defines anything v2 does not;
  - shared values live only in constellation_const_v2_2.py (fixed) and
    constellation_dynamic_v2_2.py (computed at import): no other v2_2 module assigns a
    module-level value;
  - a mutated copy of v2 (one changed constant) is reported as different, so the check
    cannot pass by comparing nothing;
  - every v2_2 file stays under the 1000-line ceiling;
  - the GUI launches and stops constellation_finder_v2_2.py;
  - the same two runs (a --max-windows batch, then the rest) over the same two-floor
    portal, run as a script through v2 and v2_2, print the same lines and write the same
    files (write timestamps, timings and the portal path set aside).

Run (no WSL needed):
    python unitTests\\test_constellation_finder_v2_2.py
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_CONSTELLATION_DIR = os.path.join(_REPO_ROOT, "constellation")
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
V2 = os.path.join(_CONSTELLATION_DIR, "constellation_finder_v2.py")
V2_2_FILES = [os.path.join(_CONSTELLATION_DIR, f"constellation_{name}_v2_2.py") for name in (
    "finder", "const", "dynamic", "diag", "windows", "progress", "hits", "match")]
SHARED_VALUE_MODULES = ("constellation_const_v2_2.py", "constellation_dynamic_v2_2.py")
SHARED_MODULE_ALIASES = ("_const", "_dyn")
MAX_LINES = 1000
BANNER_PREFIX = "[*] CONSTELLATION FINDER -- v2"

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class _Unqualify(ast.NodeTransformer):
    """Reads `_const.NAME` / `_dyn.NAME` as the bare NAME v2 uses."""

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id in SHARED_MODULE_ALIASES:
            return ast.Name(id=node.attr, ctx=node.ctx)
        return node


def _normalize(node):
    """Drops docstrings, unqualifies shared values and blanks the start banner's version."""
    node = _Unqualify().visit(node)
    for sub in ast.walk(node):
        body = getattr(sub, "body", None)
        if (isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            sub.body = body[1:] or [ast.Pass()]
        if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                and sub.value.startswith(BANNER_PREFIX)):
            sub.value = BANNER_PREFIX
    return ast.dump(node, include_attributes=False)


def _is_main_block(node):
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")


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
        elif _is_main_block(node):
            units["__main__"] = _normalize(node)
    return units


def compare_units(v2_source, v2_2_sources):
    """Returns the list of mismatch descriptions between v2 and the v2_2 modules."""
    v2_units = top_level_units(v2_source)
    problems = []
    found = {}
    for path, source in v2_2_sources.items():
        for name, dump in top_level_units(source).items():
            if name in found:
                problems.append(f"{name} is defined in both {found[name][0]} and {path}")
            found[name] = (path, dump)
    for name, dump in v2_units.items():
        if name not in found:
            problems.append(f"{name} is missing from v2_2")
        elif found[name][1] != dump:
            problems.append(f"{name} differs ({os.path.basename(found[name][0])})")
    for name in found:
        if name not in v2_units:
            problems.append(f"{name} is new in v2_2")
    return problems


def module_level_assignments(source):
    """Names assigned at module level, `_SCRIPT_DIR` and try/except import fallbacks aside."""
    names = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names += [t.id for t in targets if isinstance(t, ast.Name) and t.id != "_SCRIPT_DIR"]
    return names


def _build_portal(portal):
    """Two floors of real PGS2 source windows: 10^2 in three windows reaching the floor
    boundary, 10^3 in one window, so batching, the boundary check and its NOTE all run."""
    import prime_sieve_v1
    import window_sharding

    def primes_between(lo, hi):
        return [n for n in range(max(lo, 2), hi)
                if all(n % d for d in range(2, int(n ** 0.5) + 1))]

    layout = {2: [("PRIME_WINDOW_A.bin", 100, 400), ("PRIME_WINDOW_B.bin", 400, 700),
                  ("PRIME_WINDOW_C.bin", 700, 1000)],
              3: [("PRIME_WINDOW_A.bin", 1000, 1300)]}
    for floor, windows in layout.items():
        shard = window_sharding.shard_dir(os.path.join(portal, f"10p{floor}", "source_primes"), 0)
        os.makedirs(shard, exist_ok=True)
        for name, lo, hi in windows:
            prime_sieve_v1.write_prime_window(os.path.join(shard, name), primes_between(lo, hi))


_VOLATILE_LINE = re.compile(r"^(updated_at|checked_at)=.*$", re.MULTILINE)


def run_twice(script, portal):
    """A --max-windows 2 batch, then an uncapped run; returns (exit codes, lines, files)."""
    import prime_sieve_v1

    _build_portal(portal)
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    codes, out_lines = [], []
    for args in (["--max-windows", "2"], []):
        result = subprocess.run([sys.executable, script] + args, capture_output=True,
                                text=True, env=env, timeout=120)
        if result.returncode != 0:
            print(result.stderr)
        codes.append(result.returncode)
        for line in result.stdout.splitlines():
            if line.startswith(("Start time:", "[*] Portal:", BANNER_PREFIX)):
                continue
            out_lines.append(re.sub(r"\(\d+\.\d+s\)", "(t)", line.replace(portal, "<portal>")))
    files = {}
    for root, _dirs, names in os.walk(portal):
        for name in names:
            path = os.path.join(root, name)
            with open(path, "rb") as f:
                data = f.read()
            if name.endswith(".txt"):
                data = _VOLATILE_LINE.sub("", data.decode("utf-8")).encode("utf-8")
            elif name.endswith(".bin"):
                # The PGS2 header carries the write time; compare base_prime, count and
                # the decoded values instead.
                header = prime_sieve_v1.read_prime_window_header(path)
                data = (header["base_prime"], header["count"],
                        tuple(prime_sieve_v1.read_prime_window(path)))
            files[os.path.relpath(path, portal)] = data
    return codes, out_lines, files


def main():
    with open(V2, encoding="utf-8") as f:
        v2_source = f.read()
    v2_2_sources = {}
    for path in V2_2_FILES:
        check(os.path.exists(path), f"{os.path.basename(path)} exists")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                v2_2_sources[path] = f.read()

    if len(v2_2_sources) == len(V2_2_FILES):
        problems = compare_units(v2_source, v2_2_sources)
        for problem in problems:
            print(f"      {problem}")
        check(not problems, "every function, constant and the __main__ block of "
                            "constellation_finder_v2.py is in exactly one v2_2 module, unchanged")
        check(len(top_level_units(v2_source)) > 40,
              "the comparison covers v2's top-level definitions (sanity)")

        stray = {os.path.basename(path): module_level_assignments(source)
                 for path, source in v2_2_sources.items()
                 if os.path.basename(path) not in SHARED_VALUE_MODULES}
        stray = {name: values for name, values in stray.items() if values}
        check(not stray, f"only constellation_const/_dynamic_v2_2.py assign module-level "
                         f"values (others: {stray})")

        mutated = v2_source.replace('DONE_LOG_FILENAME = "DONE_WINDOWS.txt"',
                                    'DONE_LOG_FILENAME = "DONE_WINDOWS_X.txt"')
        check(mutated != v2_source and compare_units(mutated, v2_2_sources),
              "a mutated copy of v2 is reported as different")

        for path, source in v2_2_sources.items():
            n = source.count("\n")
            check(n <= MAX_LINES, f"{os.path.basename(path)} has {n} lines (<= {MAX_LINES})")

    gui_sources = {}
    for rel in (("generation", "engine_argv.py"), ("generation", "constellation_section.py"),
                ("settings", "restore_section.py")):
        with open(os.path.join(_REPO_ROOT, "primeatlas", *rel), encoding="utf-8") as f:
            gui_sources[rel[1]] = f.read()
    check('os.path.join(_SCRIPT_DIR, "constellation", "constellation_finder_v2_2.py")'
          in gui_sources["engine_argv.py"],
          "the GUI launches constellation_finder_v2_2.py (engine_argv)")
    for name in ("constellation_section.py", "restore_section.py"):
        check('kill_pattern="constellation_finder_v2_2.py"' in gui_sources[name],
              f"{name} stops constellation_finder_v2_2.py, the script the GUI launches")

    portal_v2 = tempfile.mkdtemp(prefix="primeatlas_cf_v2_cli_")
    portal_v2_2 = tempfile.mkdtemp(prefix="primeatlas_cf_v2_2_cli_")
    try:
        codes_a, out_a, files_a = run_twice(V2, portal_v2)
        codes_b, out_b, files_b = run_twice(V2_2_FILES[0], portal_v2_2)
        check(codes_a == [0, 0] and codes_b == [0, 0],
              f"both scripts exit 0 on both runs (v2={codes_a}, v2_2={codes_b})")
        if out_a != out_b:
            for a, b in zip(out_a, out_b):
                if a != b:
                    print(f"      v2:   {a}\n      v2_2: {b}")
                    break
        check(out_a == out_b and any("BATCH DONE" in line for line in out_a),
              "v2 and v2_2 print the same lines for the same batched runs")
        check(files_a == files_b and any("HITS_" in name for name in files_a),
              f"v2 and v2_2 write the same files with the same bytes "
              f"({len(files_a)} vs {len(files_b)} files)")
    finally:
        shutil.rmtree(portal_v2, ignore_errors=True)
        shutil.rmtree(portal_v2_2, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
