"""The Benchmark sieve chart measures one of three times (primeatlas/benchmark/sieve_measure.py
and the Filter window's "Sieve measure" choice).

Pure: "phase" is the engine's own sieve_seconds (n/s, s/window) as before; "wall" is
sieve_wall_seconds, the orchestrator's launch-to-sieve-done time (n/s, s/window); "overhead"
is the speed the startup takes: phase n/s minus wall n/s, and that as % of the phase n/s.
Native primesieve count is one process timed with its startup: its sieve_seconds is its point on "phase" and "wall", and it has no
startup/sieve split, so no point on "overhead". A row without the time of a measure has no
point on it. Every label key exists in en and pl.
On a real BenchmarkTab: choosing "overhead" in the Filter window leaves only the rows with
both times on the sieve chart, clears that chart's y pins (other units), names the measure
next to the Filter button and in the PDF's sieve page heading; "phase" restores the lines. A
long filter summary leaves the reference and log-scale toggles on screen.
Windows, real display (the tab part):
    python unitTests/test_benchmark_sieve_measure.py
"""
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import benchmark, sieve_measure  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

N = 10 ** 10


def _row(engine, version, sieve, wall, windows=1000, ts="1", threads="15", write="8"):
    return dict(run_timestamp_utc=ts, base_exponent="19", engine=engine,
                engine_version=version, threads=threads, write_threads=write,
                instance_of_n="1/1", numbers_processed=str(N), windows_written=str(windows),
                sieve_seconds=str(sieve), sieve_wall_seconds=str(wall),
                loop_numbers_per_second="1", write_seconds="1", bytes_written="1000")


ROWS = [
    _row("v6", "v6.0", 2.0, 2.5, ts="a"),
    _row("v5", "v5.1", 3.0, "", ts="b", write="1"),
    _row("primesieve_count", "12.15", 3.125, "", windows=0, ts="c", write=""),
]
V6, V5, COUNT = "v6.0, 15 thr, write 8", "v5.1, 15 thr, write 1", \
    "primesieve count (native) 12.15, 15 thr"


class PureTests(unittest.TestCase):
    def lines(self, metric):
        return benchmark.benchmark_engine_lines(ROWS, metric)

    def test_phase_unchanged(self):
        self.assertEqual(self.lines("sieve"), {V6: [(19, N / 2.0)], V5: [(19, N / 3.0)],
                                               COUNT: [(19, N / 3.125)]})

    def test_wall(self):
        self.assertEqual(self.lines("sieve_wall"), {V6: [(19, N / 2.5)], COUNT: [(19, N / 3.125)]},
                         "native count's whole-process time includes its startup; v5 has no wall")
        self.assertEqual(self.lines("sieve_wall_spw"),
                         {V6: [(19, 2.5 / 1000)], COUNT: [(19, 3.125 / 1000)]})

    def test_overhead(self):
        self.assertEqual(self.lines("sieve_overhead"), {V6: [(19, N / 2.0 - N / 2.5)]},
                         "native count has no startup split; v5 has no wall time")
        self.assertEqual(self.lines("sieve_overhead_pct"), {V6: [(19, 20.0)]})

    def test_specs(self):
        self.assertEqual(sieve_measure.MEASURES, ("phase", "wall", "overhead"))
        self.assertEqual(sieve_measure.DEFAULT, "phase")
        phase = sieve_measure.chart("phase")
        self.assertEqual((phase.metric1, phase.metric2), ("sieve", "sieve_spw"))
        self.assertEqual((phase.label_key1, phase.label_key2),
                         ("bench.axis_sieve_nps", "bench.axis_sieve_spw"))
        self.assertTrue(phase.references and sieve_measure.chart("wall").references)
        self.assertFalse(sieve_measure.chart("overhead").references,
                         "n/s references do not belong on a seconds axis")
        for lang in ("en", "pl"):
            with open(ROOT / "primeatlas" / "core" / "locales" / f"strings_{lang}.json",
                      encoding="utf-8") as f:
                strings = json.load(f)
            keys = [sieve_measure.TIP_KEY, sieve_measure.HEADING_KEY, sieve_measure.NOTE_KEY]
            for m in sieve_measure.MEASURES:
                spec = sieve_measure.chart(m)
                keys += [sieve_measure.LABEL_KEYS[m], spec.label_key1, spec.label_key2]
            for key in keys:
                self.assertIn(key, strings, f"{key} in strings_{lang}.json")

    def test_note(self):
        t = Translator("en").t
        self.assertEqual(sieve_measure.note("phase", t), "")
        self.assertIn(t("bench.measure_overhead"), sieve_measure.note("overhead", t))


class TabTests(unittest.TestCase):
    def test_filter_window_switches_the_sieve_chart(self):
        import tkinter as tk
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        captured = {}
        original_hover = benchmark_tab._bind_chart_hover
        benchmark_tab._bind_chart_hover = (
            lambda canvas, points, *a: captured.__setitem__(str(canvas), list(points)))
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(ROWS[0]))
                writer.writeheader()
                writer.writerows(ROWS)
            root = tk.Tk()
            try:
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack(fill="both", expand=True)
                tab.reload_benchmark_log()
                root.update()

                def tags():
                    return {p[4].split("[", 1)[1].split("]")[0]
                            for p in captured.get(str(tab.benchmark_chart2), [])
                            if "[" in p[4]}

                tab._redraw_charts()
                self.assertEqual(tags(), {V6, V5, COUNT})
                tab._y_pins["sieve"] = {"primary": (1.0, 2.0)}

                window = tab._open_filter_window()
                window.measure_var.set("wall")
                window.apply()
                root.update()
                self.assertEqual(tags(), {V6, COUNT}, "native count stays, as PARI does")

                window.measure_var.set("overhead")
                window.apply()
                root.update()
                self.assertEqual(tags(), {V6})
                self.assertEqual(tab._y_pins["sieve"], {}, "pins of other units are cleared")
                self.assertIn("overhead", tab.filter_summary_var.get().lower())

                with tempfile.TemporaryDirectory() as out:
                    path = os.path.join(out, "r.pdf")
                    tab._render_pdf(path)
                    text = Path(path).read_bytes().decode("latin-1")
                sieve_page = text.split("page 2", 1)[1].split("endstream", 1)[0]
                self.assertIn("Sieve measure: startup overhead alone", sieve_page)
                self.assertIn("startup overhead: n / s lost", sieve_page)
                self.assertIn(V6 + "]", sieve_page)
                self.assertNotIn(V5 + "]", sieve_page,
                                 "the sieve page draws only rows with both times")

                root.geometry("900x700")
                tab.filter_summary_var.set("x" * 400)
                root.update()
                toggles = [w for w in tab.winfo_children()[0].winfo_children()
                           if str(w.cget("text")) == tab.T("bench.show_references")]
                self.assertEqual(len(toggles), 1)
                self.assertTrue(toggles[0].winfo_ismapped() and toggles[0].winfo_width() > 20,
                                "a long filter summary does not push the PARI toggle out")

                window.measure_var.set("phase")
                window.apply()
                root.update()
                self.assertEqual(tags(), {V6, V5, COUNT})
                window.destroy()
            finally:
                root.destroy()
                benchmark_tab._bind_chart_hover = original_hover


if __name__ == "__main__":
    unittest.main()
