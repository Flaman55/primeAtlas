"""The Benchmark tab's on-screen chart drawing lives in primeatlas/benchmark/chart_canvas.py.

Checks: chart_canvas defines the six drawing functions; benchmark_tab defines none of them and
keeps no import that only the drawing used; the hover hook a test replaces is
chart_canvas._bind_chart_hover, and every chart the tab draws (the three tab canvases and an
open chart window) goes through it. Windows, real display:
    python unitTests/test_benchmark_chart_canvas.py
"""
import csv
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from app_sandbox import fresh_ui_store  # noqa: E402

from primeatlas.core.i18n import Translator  # noqa: E402

failures = []

CHART_FUNCTIONS = ("_mix", "_legend_tag", "_draw_legend", "_draw_growth_chart",
                   "_legend_series_at", "_bind_pin_menu")
# Names benchmark_tab imported only for the chart drawing.
DRAWING_ONLY_IMPORTS = ("re", "tkfont", "Translator", "DEFAULT_LANGUAGE", "clip_polyline",
                        "in_view", "legend_entries", "marker_state", "plain_series",
                        "point_label", "run_key", "series_xs", "visible_series", "y_scale",
                        "chart_points", "_bind_chart_hover", "_nearest_point")


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _row(floor, engine, nps):
    return dict(base_exponent=str(floor), engine=engine, loop_numbers_per_second=str(nps),
                numbers_processed="100", windows_written="10", sieve_seconds="1",
                bytes_written="2000000", write_seconds="1", max_child_rss_mb=str(10 * floor))


ROWS = [_row(f, e, k * 1e6 * f) for f in range(10, 16) for e, k in (("v5", 1), ("v6", 2))]


def _test_module_split():
    try:
        from primeatlas.benchmark import chart_canvas
    except ImportError as exc:
        check(False, f"primeatlas.benchmark.chart_canvas imports ({exc})")
        return
    from primeatlas.benchmark import benchmark_tab

    for name in CHART_FUNCTIONS:
        check(callable(getattr(chart_canvas, name, None)), f"chart_canvas defines {name}")
        check(not hasattr(benchmark_tab, name), f"benchmark_tab has no {name}")
    left = [name for name in DRAWING_ONLY_IMPORTS if hasattr(benchmark_tab, name)]
    check(not left, f"benchmark_tab keeps no drawing-only import (left: {left})")


def _test_hover_seam_reaches_every_chart():
    import tkinter as tk
    try:
        from primeatlas.benchmark import chart_canvas
    except ImportError as exc:
        check(False, f"the hover seam is chart_canvas._bind_chart_hover ({exc})")
        return
    from primeatlas.benchmark import benchmark_tab
    from primeatlas.core.theme import palette_for

    captured = {}
    original_hover = chart_canvas._bind_chart_hover
    chart_canvas._bind_chart_hover = (
        lambda canvas, points, *a: captured.__setitem__(str(canvas), list(points)))
    with tempfile.TemporaryDirectory() as portal:
        with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(ROWS[0]))
            writer.writeheader()
            writer.writerows(ROWS)
        root = tk.Tk()
        try:
            fresh_ui_store()
            tab = benchmark_tab.BenchmarkTab(
                root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                lambda *a, **k: None, palette_for("light"))
            tab.pack(fill="both", expand=True)
            root.geometry("1000x800")
            tab.reload_benchmark_log()
            root.update()
            canvases = [tab.benchmark_chart, tab.benchmark_chart2, tab.benchmark_chart3]
            for canvas in canvases:
                check(captured.get(str(canvas)), f"{canvas} is drawn through the hover seam")
            captured.clear()
            tab._open_chart_window("run")
            root.update()
            windows = tab._chart_window_canvases("run")
            check(len(windows) == 1 and captured.get(str(windows[0])),
                  "an open chart window is drawn through the hover seam")
        finally:
            chart_canvas._bind_chart_hover = original_hover
            root.destroy()


def main():
    _test_module_split()
    _test_hover_seam_reaches_every_chart()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
