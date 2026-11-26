"""The HTML report's script is split into parts by function (primeatlas/benchmark/report_js/),
which report_html.py joins into one script.

Checks: every .js file of the folder is a listed part and every listed part exists; the old
single report_chart.js is gone; no part is over MAX_PART_LINES; every top-level name is
defined in one part only; the joined script is one function wrapper with one "use strict"
that no part repeats; a missing part fails the export instead of writing a partial script.
Through node (skipped without it): each part parses on its own, and the joined script, run in
an empty context, adds no global besides module.exports, which holds the exported functions.
    python unitTests/test_benchmark_report_js_split.py
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import report_export, report_html  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

NODE = shutil.which("node")
BENCHMARK = ROOT / "primeatlas" / "benchmark"
# A ceiling per part, below the repo's 1000 so the page part cannot regrow into a monolith.
MAX_PART_LINES = 400
EXPORTS = ["YScale", "chartSvg", "clipPolyline", "controlsHtml", "emptyColumns",
           "filterSummary", "formatCompact", "formatNumber", "keptRuns", "mixedFloors", "pan",
           "pick", "placeLabels", "reduce", "selectAll", "shownCharts", "tickFloors",
           "toggleValue", "widthLabel", "xLabel", "zoomStep"]
TOP_LEVEL = re.compile(r"^(?:function (\w+)|var (\w+)|(\w+\.prototype\.\w+) =)", re.M)

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _parts():
    folder = getattr(report_html, "SCRIPT_DIR", None)
    parts = getattr(report_html, "SCRIPT_PARTS", None)
    if folder is None or parts is None:
        return None, None
    return Path(folder), list(parts)


def _test_part_list():
    folder, parts = _parts()
    check(parts is not None, "report_html lists the script's parts (SCRIPT_DIR, SCRIPT_PARTS)")
    if parts is None:
        return
    on_disk = sorted(p.name for p in folder.glob("*.js"))
    check(sorted(parts) == on_disk and len(parts) == len(set(parts)),
          f"the list holds every part once and every .js in {folder.name}/ (list {parts}, "
          f"folder {on_disk})")
    check(not (BENCHMARK / "report_chart.js").exists(), "the single report_chart.js is gone")
    for name in parts:
        path = folder / name
        lines = len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0
        check(lines <= MAX_PART_LINES, f"{name} has at most {MAX_PART_LINES} lines (got {lines})")


def _test_names_once():
    folder, parts = _parts()
    if parts is None:
        return
    where = {}
    for name in parts:
        for match in TOP_LEVEL.finditer((folder / name).read_text(encoding="utf-8")):
            where.setdefault(next(g for g in match.groups() if g), []).append(name)
    twice = {n: files for n, files in where.items() if len(files) > 1}
    check(where and not twice, f"every top-level name is defined in one part (twice: {twice})")


def _test_wrapper():
    folder, parts = _parts()
    if parts is None:
        return
    script = report_html.chart_script()
    check(script.startswith('<script>(function () {\n"use strict";\n')
          and script.endswith("})();\n</script>"),
          "the joined script is one function wrapper with \"use strict\" first")
    check(script.count('"use strict"') == 1, "\"use strict\" appears once in the joined script")
    repeats = [n for n in parts if "use strict" in (folder / n).read_text(encoding="utf-8")]
    check(not repeats, f"no part repeats \"use strict\" (got {repeats})")
    page = report_export.render("html", ["base_exponent", "engine"],
                                [{"base_exponent": "18", "engine": "v6"}],
                                translator=Translator("en"))
    check(page.count("<script>") == 1, "an exported page holds one script element")


def _test_missing_part():
    folder, parts = _parts()
    if parts is None:
        return
    real = report_html.SCRIPT_PARTS
    report_html.SCRIPT_PARTS = tuple(real) + ("no_such_part.js",)
    try:
        report_html.chart_script()
        error = None
    except FileNotFoundError as exc:
        error = exc
    finally:
        report_html.SCRIPT_PARTS = real
    check(error is not None, "a missing part fails the export (FileNotFoundError)")


def _test_node():
    folder, parts = _parts()
    if parts is None:
        return
    if not NODE:
        print("SKIPPED (node not installed): parts parse alone, no globals leak")
        return
    for name in parts:
        done = subprocess.run([NODE, "--check", str(folder / name)], capture_output=True,
                              text=True, encoding="utf-8")
        check(done.returncode == 0, f"{name} parses on its own ({done.stderr.strip()[:200]})")
    driver = ("const vm = require('vm'); const fs = require('fs');"
              "const ctx = vm.createContext({module: {exports: {}}});"
              "vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);"
              "process.stdout.write(JSON.stringify({globals: Object.keys(ctx).sort(),"
              " exports: Object.keys(ctx.module.exports).sort()}));")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "report.js"
        source.write_text(report_html.chart_source(), encoding="utf-8")
        script = Path(tmp) / "driver.js"
        script.write_text(driver, encoding="utf-8")
        done = subprocess.run([NODE, str(script), str(source)], capture_output=True, text=True,
                              encoding="utf-8")
    check(done.returncode == 0, f"the joined script runs in node ({done.stderr.strip()[:300]})")
    if done.returncode:
        return
    got = json.loads(done.stdout)
    check(got["globals"] == ["module"], f"no global besides module (got {got['globals']})")
    check(got["exports"] == sorted(EXPORTS), f"module.exports holds the exported functions "
                                             f"(got {got['exports']})")


def main():
    _test_part_list()
    _test_names_once()
    _test_wrapper()
    _test_missing_part()
    _test_node()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
