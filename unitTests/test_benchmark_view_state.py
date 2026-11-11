"""The Benchmark tab's view kept across restarts and the one-click axis toggles
(primeatlas/benchmark/view_store.py, benchmark_view_state.py).

Pure (view_store): save() then load() gives back the filter (per dimension, values as sets),
the sieve measure, the x axis, the point choice per chart and the hidden lines per chart; a
chart on SELECTED is saved as its choice from before the selection (LAST when none), since the
selected run is not kept. load() of an empty store gives the defaults; of junk (a wrong type
anywhere, an unknown dimension, measure, x axis, chart or choice, a malformed line key) the
defaults for exactly the parts that are junk. prune(): the filter keeps only values the log
holds; a dimension left with none is at All again.
On a real BenchmarkTab: a chart's right-click menu has "Hide/Show left-axis lines (circles)"
and "Hide/Show right-axis lines (squares)": Hide hides every line drawn on that axis of that
chart (the other charts keep theirs), and then reads Show; Show brings them all back; with some
of them hidden, Hide hides the rest; there and back lands on the same lines; an axis without
lines has the entry disabled. A hidden axis stays hidden for a line that appears later (a
new run, a wider filter); a marker click on it shows that line alone. A second tab built on the same store opens with the filter, the
measure, the x axis, the point choices and the hidden lines of the first; a filter value the
log no longer holds is dropped at reload.
Windows, real display:
    python unitTests/test_benchmark_view_state.py
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation"),
                str(ROOT / "unitTests")]

from primeatlas.benchmark import chart_points as cp, chart_series, sieve_measure, view_store  # noqa: E402
from primeatlas.core.ui_state_store import UiStateStore  # noqa: E402
import test_benchmark_chart_points as chart_points_tests  # noqa: E402

ROWS = chart_points_tests.ROWS
# A second engine build, so each axis of a chart has two lines.
TWO_LINES = ROWS + [chart_points_tests._row(29, 10 ** 10, 2000.0, version="v7.2", ts="h")]
DEFAULTS = {"selection": {}, "measure": sieve_measure.DEFAULT, "x_mode": cp.X_FLOOR,
            "choices": {"run": cp.LAST, "sieve": cp.LAST, "ram": cp.LAST},
            "hidden": {"run": set(), "sieve": set(), "ram": set()}}


class StoreTests(unittest.TestCase):

    def test_round_trip(self):
        store = UiStateStore(None)
        view_store.save(store, {"engine": {"v7.1", "v7.2"}, "floor": {"29"}},
                        sieve_measure.WALL, cp.X_WIDTH,
                        {"run": cp.MAX, "sieve": cp.ALL, "ram": cp.MIN}, {},
                        {"run": {("secondary", "v7.1, 24 thr")}, "sieve": {("primary", "*")},
                         "ram": set()})
        self.assertEqual(view_store.load(store), {
            "selection": {"engine": {"v7.1", "v7.2"}, "floor": {"29"}},
            "measure": sieve_measure.WALL, "x_mode": cp.X_WIDTH,
            "choices": {"run": cp.MAX, "sieve": cp.ALL, "ram": cp.MIN},
            "hidden": {"run": {("secondary", "v7.1, 24 thr")}, "sieve": {("primary", "*")},
                       "ram": set()}})

    def test_selected_saved_as_before(self):
        store = UiStateStore(None)
        view_store.save(store, {}, sieve_measure.DEFAULT, cp.X_FLOOR,
                        {"run": cp.SELECTED, "sieve": cp.SELECTED, "ram": cp.ALL},
                        {"run": cp.MAX}, DEFAULTS["hidden"])
        self.assertEqual(view_store.load(store)["choices"],
                         {"run": cp.MAX, "sieve": cp.LAST, "ram": cp.ALL})

    def test_empty_and_junk(self):
        self.assertEqual(view_store.load(UiStateStore(None)), DEFAULTS, "empty store")
        for junk in (None, 7, "x", [], {"selection": 3}, {"measure": 5, "x_mode": []},
                     {"choices": {"run": "nope", "pie": cp.MAX}, "hidden": {"run": [[1]]}},
                     {"selection": {"nope": ["a"], "engine": "v7"}, "hidden": "x"},
                     {"choices": {"sieve": cp.SELECTED}}):
            store = UiStateStore(None)
            store.set(view_store.KEY, junk)
            self.assertEqual(view_store.load(store), DEFAULTS, f"junk {junk!r}")
        store = UiStateStore(None)
        store.set(view_store.KEY, {"selection": {"engine": ["v7.1"], "nope": ["a"]},
                                   "measure": "nope", "choices": {"run": cp.MAX},
                                   "hidden": {"sieve": [["primary", "a"], ["sideways", "b"]]}})
        loaded = view_store.load(store)
        self.assertEqual(loaded["selection"], {"engine": {"v7.1"}}, "only the junk part dropped")
        self.assertEqual(loaded["measure"], sieve_measure.DEFAULT)
        self.assertEqual(loaded["choices"]["run"], cp.MAX)
        self.assertEqual(loaded["hidden"]["sieve"], {("primary", "a")})

    def test_prune(self):
        selection = {"engine": {"v7.1", "gone"}, "floor": {"99"}}
        self.assertEqual(view_store.prune(selection, ROWS), {"engine": {"v7.1"}})
        self.assertEqual(view_store.prune({}, ROWS), {})
        self.assertEqual(view_store.prune({"floor": {"28"}}, []), {}, "no log: All")


class TabTests(unittest.TestCase):

    def setUp(self):
        from primeatlas.core import ui_state_dynamic
        self._saved_store = ui_state_dynamic.STORE
        ui_state_dynamic.STORE = UiStateStore(None)

    def tearDown(self):
        from primeatlas.core import ui_state_dynamic
        ui_state_dynamic.STORE = self._saved_store

    @staticmethod
    def entries(tab, chart):
        return {e[0]: (e[1], e[2]) for e in tab._pin_menu_entries(chart, None) if e}

    @staticmethod
    def axis_label(tab, action, axis):
        return tab.T(f"bench.axis_lines_{action}_{axis}")

    @staticmethod
    def drawn(tab, axis):
        canvas = tab.benchmark_chart2
        return {s.name for tag, s in canvas.legend_series.items()
                if tag.startswith(f"legend:{axis}:")}

    def test_axis_toggle(self):
        def body(tab, root, points):
            hide2 = self.axis_label(tab, "hide", "secondary")
            show2 = self.axis_label(tab, "show", "secondary")
            entries = self.entries(tab, "sieve")
            self.assertTrue(entries[hide2][1], "an axis with lines: enabled")
            self.assertIn(self.axis_label(tab, "hide", "primary"), entries)
            names = self.drawn(tab, "secondary")
            self.assertEqual(len(names), 2, names)
            for _round in range(2):  # there and back, twice
                self.entries(tab, "sieve")[hide2][0]()
                root.update()
                self.assertEqual(tab._hidden_lines["sieve"], {chart_series.axis_key("secondary")},
                                 "the right axis hidden whole")
                self.assertEqual(tab._hidden_lines["run"], set(), "other charts keep theirs")
                self.assertIn(show2, self.entries(tab, "sieve"), "now reads Show")
                self.entries(tab, "sieve")[show2][0]()
                root.update()
                self.assertEqual(tab._hidden_lines["sieve"], set(), "all back")
            one = sorted(names)[0]
            tab._toggle_lines("sieve", [("secondary", one)])
            self.assertIn(hide2, self.entries(tab, "sieve"), "some hidden: still Hide")
            self.entries(tab, "sieve")[hide2][0]()
            self.assertTrue(all(chart_series.is_hidden(tab._hidden_lines["sieve"], "secondary", n)
                                for n in names), "every square hidden")
            tab._set_filter({"floor": {"nothing"}})
            root.update()
            entries = self.entries(tab, "sieve")
            label = next(k for k in entries if k in (hide2, show2))
            self.assertFalse(entries[label][1], "no lines: disabled")
        chart_points_tests.TabTests._tab(self, TWO_LINES, body)

    def test_hidden_axis_covers_a_new_line(self):
        def shown(tab, axis):
            return {n for n in self.drawn(tab, axis)
                    if not chart_series.is_hidden(tab._hidden_lines["sieve"], axis, n)}

        def body(tab, root, points):
            hide2 = self.axis_label(tab, "hide", "secondary")
            show2 = self.axis_label(tab, "show", "secondary")
            tab._set_filter({"engine": {"v7.1"}})
            root.update()
            self.assertEqual(len(self.drawn(tab, "secondary")), 1)
            self.entries(tab, "sieve")[hide2][0]()
            root.update()
            tab._set_filter({})  # the v7.2 line comes back, as a new run would add one
            root.update()
            names = self.drawn(tab, "secondary")
            self.assertEqual(len(names), 2, names)
            self.assertEqual(shown(tab, "secondary"), set(), "the new line stays hidden")
            self.assertEqual(len(shown(tab, "primary")), 2, "the left axis keeps its lines")
            self.assertIn(show2, self.entries(tab, "sieve"), "still reads Show")
            one = sorted(names)[0]
            tab._toggle_lines("sieve", [("secondary", one)])
            root.update()
            self.assertEqual(shown(tab, "secondary"), {one}, "a marker click shows that line")
            self.entries(tab, "sieve")[hide2][0]()
            self.entries(tab, "sieve")[show2][0]()
            root.update()
            self.assertEqual(shown(tab, "secondary"), names, "Show brings all back")
            self.assertEqual(tab._hidden_lines["sieve"], set())
        chart_points_tests.TabTests._tab(self, TWO_LINES, body)

    def test_kept_across_tabs(self):
        state = {}

        def first(tab, root, points):
            tab._set_filter({"engine": {"v7.1"}, "floor": {"28", "29"}}, sieve_measure.WALL)
            tab._set_points(cp.X_WIDTH, {"sieve": cp.MAX, "ram": cp.ALL})
            tree = tab.benchmark_tree
            tree.selection_set(chart_points_tests.TabTests._row_item(tab, 28, "d"))
            root.update()
            self.entries(tab, "run")[self.axis_label(tab, "hide", "secondary")][0]()
            root.update()
            state["hidden"] = {c: set(v) for c, v in tab._hidden_lines.items()}
            self.assertTrue(state["hidden"]["run"])

        def second(tab, root, points):
            self.assertEqual(tab._filter_selection, {"engine": {"v7.1"}, "floor": {"28", "29"}})
            self.assertEqual(tab._sieve_measure, sieve_measure.WALL)
            self.assertEqual(tab._x_mode, cp.X_WIDTH)
            self.assertEqual(tab._point_choice, {"run": cp.LAST, "sieve": cp.MAX,
                                                 "ram": cp.ALL}, "SELECTED kept as before")
            self.assertIsNone(tab._selected_run)
            self.assertEqual(tab._hidden_lines, state["hidden"])
            self.assertEqual(tab.filter_summary_var.get(), tab._filter_summary())
            self.assertIn("v7.1", tab.filter_summary_var.get())

        chart_points_tests.TabTests._tab(self, ROWS, first)
        chart_points_tests.TabTests._tab(self, ROWS, second)

    def test_stale_value_dropped(self):
        from primeatlas.core import ui_state_dynamic
        view_store.save(ui_state_dynamic.STORE, {"engine": {"gone"}, "floor": {"29"}},
                        sieve_measure.DEFAULT, cp.X_FLOOR, DEFAULTS["choices"], {},
                        DEFAULTS["hidden"])

        def body(tab, root, points):
            self.assertEqual(tab._filter_selection, {"floor": {"29"}})
            self.assertTrue(points(tab.benchmark_chart2), "charts not emptied by it")
        chart_points_tests.TabTests._tab(self, ROWS, body)


if __name__ == "__main__":
    unittest.main()
