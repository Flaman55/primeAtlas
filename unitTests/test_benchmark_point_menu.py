"""The Benchmark charts' point choice from the right-click menu, and clearing the run selected in
the table with a right-click (benchmark_points.py, benchmark_tab._pin_menu_entries()).

Chart menu (on a point or off every point): first the five point choices of that chart (Last,
Min, Max, Selected, All); the chart's current choice is ticked and disabled, Selected is
disabled while no run is selected; choosing one sets that chart's choice alone, redraws it, and
the filter summary and an open Filter window follow. Then, after a separator, the two axis
toggles (test_benchmark_view_state), the pin entries of a point (none off a point), and the
three resets, each group after a separator.
Table: selecting a run switches every chart not on All to Selected and remembers each chart's
choice from before; selecting another run keeps what was remembered. A right-click anywhere in
the table clears the selection: no selected run, no ring on any chart, and every chart still on
Selected goes back to its remembered choice; a chart whose choice was changed meanwhile (menu or
window) keeps it. A right-click with nothing selected changes nothing. There and back: select,
clear, select, clear lands on the first choices each time.
Windows, real display:
    python unitTests/test_benchmark_point_menu.py
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation"),
                str(ROOT / "unitTests")]

from primeatlas.benchmark import chart_points as cp  # noqa: E402
import test_benchmark_chart_points as chart_points_tests  # noqa: E402

ROWS, NPS = chart_points_tests.ROWS, chart_points_tests.NPS
CHOICES = (cp.LAST, cp.MIN, cp.MAX, cp.SELECTED, cp.ALL)


def rings(canvas):
    return len(canvas.find_withtag("selected_mark"))


def labels(tab):
    return {choice: tab.T("bench.point_menu", choice=tab.T(cp.CHOICE_LABEL_KEYS[choice]))
            for choice in CHOICES}


class PointMenuTests(unittest.TestCase):

    def setUp(self):
        from app_sandbox import fresh_ui_store
        fresh_ui_store()

    def _tab(self, body):
        chart_points_tests.TabTests._tab(self, ROWS, body)

    def menu(self, tab, chart, target=None):
        return tab._pin_menu_entries(chart, target)

    def choice_entries(self, tab, chart):
        entries = self.menu(tab, chart)
        names = labels(tab)
        found = {}
        for entry in entries:
            if entry is None:
                continue
            label, command, enabled = entry
            for choice, name in names.items():
                if label in (name, "✓ " + name):
                    found[choice] = (label.startswith("✓ "), command, enabled)
        return entries, found

    def test_menu_layout(self):
        def body(tab, root, points):
            entries, found = self.choice_entries(tab, "sieve")
            self.assertEqual(list(found), list(CHOICES), "five choices, in order, first")
            self.assertEqual(entries.index(None), len(CHOICES), "separator after them")
            self.assertEqual({c for c, v in found.items() if v[0]}, {cp.LAST}, "Last ticked")
            self.assertFalse(found[cp.LAST][2], "the current choice is disabled")
            self.assertFalse(found[cp.SELECTED][2], "Selected needs a selected run")
            self.assertTrue(all(found[c][2] for c in (cp.MIN, cp.MAX, cp.ALL)))
            resets = [e[0] for e in entries[-3:]]
            self.assertEqual(resets, [tab.T("bench.pin_reset_primary"),
                                      tab.T("bench.pin_reset_secondary"),
                                      tab.T("bench.pin_reset_chart")], "resets last")
            self.assertIsNone(entries[-4], "separator before the resets")
            axes = entries[len(CHOICES) + 1:len(CHOICES) + 3]
            self.assertEqual([e[0] for e in axes],
                             [tab.T("bench.axis_lines_hide_primary"),
                              tab.T("bench.axis_lines_hide_secondary")], "then the axes")
            self.assertIsNone(entries[len(CHOICES) + 3])
            self.assertEqual(len(entries), len(CHOICES) + 7, "off a point: no pins")
            on_point = self.menu(tab, "sieve", ("primary", 1.0, "1"))
            pins = on_point[len(CHOICES) + 4:-4]
            self.assertEqual(len(pins), 2, "a point adds its max/min pins between")
            self.assertIsNone(on_point[-4])
        self._tab(body)

    def test_menu_sets_one_chart(self):
        def body(tab, root, points):
            window = tab._open_filter_window()
            _entries, found = self.choice_entries(tab, "sieve")
            found[cp.MAX][1]()
            root.update()
            self.assertEqual(tab._point_choice, {"run": cp.LAST, "sieve": cp.MAX,
                                                 "ram": cp.LAST}, "that chart only")
            self.assertIn((28, NPS["e"]), points(tab.benchmark_chart2), "f28: the max run")
            self.assertIn("Max", tab.filter_summary_var.get())
            self.assertEqual(window.choice_vars["sieve"].get(), cp.MAX, "window follows")
            _entries, found = self.choice_entries(tab, "sieve")
            self.assertEqual({c for c, v in found.items() if v[0]}, {cp.MAX}, "Max ticked")
            found[cp.LAST][1]()
            root.update()
            self.assertIn((28, NPS["f"]), points(tab.benchmark_chart2), "back: the last run")
            window.destroy()
        self._tab(body)

    def test_right_click_clears_selection(self):
        def body(tab, root, points):
            tree = tab.benchmark_tree
            self.choice_entries(tab, "ram")[1][cp.ALL][1]()
            self.choice_entries(tab, "sieve")[1][cp.MAX][1]()
            root.update()
            before = dict(tab._point_choice)
            self.assertEqual(before, {"run": cp.LAST, "sieve": cp.MAX, "ram": cp.ALL})
            tree.event_generate("<Button-3>", x=5, y=5)
            root.update()
            self.assertEqual(tab._point_choice, before, "nothing selected: nothing changes")
            for _round in range(2):  # there and back, twice
                tree.selection_set(chart_points_tests.TabTests._row_item(tab, 28, "d"))
                root.update()
                self.assertEqual(tab._point_choice, {"run": cp.SELECTED, "sieve": cp.SELECTED,
                                                     "ram": cp.ALL})
                tree.selection_set(chart_points_tests.TabTests._row_item(tab, 29, "b"))
                root.update()
                self.assertEqual(tab._selected_run["run_timestamp_utc"], "b")
                _entries, found = self.choice_entries(tab, "sieve")
                self.assertTrue(found[cp.SELECTED][0], "Selected ticked")
                tree.event_generate("<Button-3>", x=5, y=5)
                root.update()
                self.assertEqual(tree.selection(), ())
                self.assertIsNone(tab._selected_run)
                self.assertEqual(tab._point_choice, before, "back to the remembered choices")
                for canvas in (tab.benchmark_chart, tab.benchmark_chart2,
                               tab.benchmark_chart3):
                    self.assertEqual(rings(canvas), 0, "no ring left")
                self.assertIn((28, NPS["e"]), points(tab.benchmark_chart2), "max again")
        self._tab(body)

    def test_changed_meanwhile_is_kept(self):
        def body(tab, root, points):
            tree = tab.benchmark_tree
            window = tab._open_filter_window()
            tree.selection_set(chart_points_tests.TabTests._row_item(tab, 28, "d"))
            root.update()
            self.choice_entries(tab, "sieve")[1][cp.MIN][1]()
            window.choice_vars["ram"].set(cp.MAX)
            window.apply_points()
            root.update()
            tree.event_generate("<Button-3>", x=5, y=5)
            root.update()
            self.assertEqual(tab._point_choice, {"run": cp.LAST, "sieve": cp.MIN,
                                                 "ram": cp.MAX})
            self.assertEqual({c: v.get() for c, v in window.choice_vars.items()},
                             tab._point_choice, "the open window shows it")
            window.destroy()
        self._tab(body)


if __name__ == "__main__":
    unittest.main()
