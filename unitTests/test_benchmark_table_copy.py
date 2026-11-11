"""Copying Benchmark table rows to the clipboard (primeatlas/benchmark/table_copy.py,
benchmark_table_copy.py).

Pure (table_copy): runs_in_order() gives the runs of the selected floors and the selected
single runs, each once, in table order (floors ascending, runs as the floor lists them).
table_text() writes them in the export columns (floor, run, engine, then the table's): MARKDOWN
as a pipe table with the shown values, columns padded to one width so it reads as plain text
too, a "|" in a value escaped; TSV with the raw values (as the CSV export, so a spreadsheet
reads numbers); in both a column no copied run has a value in is left out, and no run gives "".
floor_mark(): a floor's box is UNMARKED with none of its runs marked, MARKED with all, PARTIAL
with some; toggle_floor() marks them all unless all are marked, then none.
On a real BenchmarkTab: a box column left of the table's columns. A click on a run's box marks
or unmarks that run, a click on a floor's box all its runs the filter keeps (collapsed or open);
the click neither selects nor scrolls; Space toggles the focused row's box; a floor shows
PARTIAL when some of its runs are marked, its open runs their own boxes. Ctrl+C copies the
marked runs of every floor as Markdown, Ctrl+Shift+C as TSV, and unmarks them all. With
nothing marked the selection is copied: a selected floor (collapsed or open) or its stats row
copies every run the filter keeps on it; a floor and one of its runs copy that run once;
nothing selected, or the "no data" row, leaves the clipboard as it was. A filter change
unmarks everything.
Windows, real display:
    python unitTests/test_benchmark_table_copy.py
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation"),
                str(ROOT / "unitTests")]

from primeatlas.benchmark import table_columns, table_copy  # noqa: E402
from primeatlas.benchmark.table_cells import MISSING  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402
import test_benchmark_chart_points as chart_points_tests  # noqa: E402

T = Translator("en")
ROWS = chart_points_tests.ROWS
_row = chart_points_tests._row
SENTINEL = "clipboard before"


def by_floor(rows):
    out = {}
    for row in rows:
        out.setdefault(int(row["base_exponent"]), []).append(row)
    return out


def md_rows(text):
    """The cells of each line of a Markdown table, header first, separator left out."""
    lines = text.splitlines()
    return [[c.strip() for c in line.strip("|").split(" | ")]
            for i, line in enumerate(lines) if i != 1]


class PureTests(unittest.TestCase):

    def test_runs_in_order(self):
        floors = by_floor(ROWS)
        f28, f29 = floors[28], floors[29]
        self.assertEqual(table_copy.runs_in_order(floors, set(), []), [])
        self.assertEqual(table_copy.runs_in_order(floors, {29}, []), f29)
        self.assertEqual(table_copy.runs_in_order(floors, {29}, [f29[1]]), f29,
                         "floor and one of its runs: each run once")
        self.assertEqual(table_copy.runs_in_order(floors, set(), [f29[2], f28[0], f29[0]]),
                         [f28[0], f29[0], f29[2]], "table order, not selection order")
        self.assertEqual(table_copy.runs_in_order(floors, {29, 27}, [f28[1]]),
                         floors[27] + [f28[1]] + f29)
        self.assertEqual(table_copy.runs_in_order(floors, {99}, []), [], "unknown floor")

    def test_markdown(self):
        rows = [ROWS[0], ROWS[3]]
        text = table_copy.table_text(rows, table_copy.MARKDOWN, T)
        lines = text.splitlines()
        self.assertEqual(len(lines), 4, "header, separator, two runs")
        self.assertEqual(len({len(line) for line in lines}), 1, "columns padded to one width")
        self.assertTrue(set(lines[1]) <= set("|- "), lines[1])
        header, *cells = md_rows(text)
        self.assertEqual(header[:3], [T(table_columns.header_key(c))
                                      for c in table_columns.KEY_COLUMNS])
        self.assertEqual([c[:2] for c in cells], [["29", "a"], ["28", "d"]])
        sieve = header.index(T(table_columns.header_key("sieve_nps")))
        self.assertEqual(cells[0][sieve], table_columns.shown(ROWS[0], "sieve_nps", T))
        self.assertIn(",", cells[0][sieve], "shown values: grouped thousands")
        verify = T(table_columns.header_key("verify_seconds"))
        self.assertNotIn(verify, header, "a column no run has a value in is left out")
        kept = [c for c in table_columns.EXPORT_COLUMNS
                if any(table_columns.raw(r, c) for r in rows)]
        self.assertEqual(len(header), len(kept))

    def test_markdown_missing_and_pipe(self):
        rows = [ROWS[0], ROWS[6]]  # the f27 run has no width
        header, first, second = md_rows(table_copy.table_text(rows, table_copy.MARKDOWN, T))
        numbers = header.index(T(table_columns.header_key("numbers")))
        self.assertEqual(second[numbers], MISSING, "a run without the value shows the dash")
        piped = dict(ROWS[0], run_timestamp_utc="x|y")
        text = table_copy.table_text([piped], table_copy.MARKDOWN, T)
        self.assertIn("x\\|y", text)
        self.assertEqual(md_rows(text)[1][1], "x\\|y", "the escaped pipe splits no cell")

    def test_tsv(self):
        rows = [ROWS[0], ROWS[6]]
        lines = table_copy.table_text(rows, table_copy.TSV, T).splitlines()
        header, first, second = (line.split("\t") for line in lines)
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(first), len(header))
        sieve = header.index(T(table_columns.header_key("sieve_nps")))
        self.assertEqual(first[sieve], table_columns.raw(ROWS[0], "sieve_nps"))
        self.assertNotIn(",", first[sieve], "raw values: a spreadsheet reads numbers")
        numbers = header.index(T(table_columns.header_key("numbers")))
        self.assertEqual(second[numbers], "", "a run without the value: empty cell")
        self.assertNotIn(T(table_columns.header_key("verify_seconds")), header)

    def test_floor_marks(self):
        rows = by_floor(ROWS)[29]
        marks = set()
        self.assertEqual(table_copy.floor_mark(rows, marks), table_copy.UNMARKED)
        marks = table_copy.toggle_floor(rows, marks)
        self.assertEqual(marks, {id(r) for r in rows})
        self.assertEqual(table_copy.floor_mark(rows, marks), table_copy.MARKED)
        self.assertEqual(table_copy.toggle_floor(rows, marks), set(), "there and back")
        some = {id(rows[1]), id(ROWS[3])}
        self.assertEqual(table_copy.floor_mark(rows, some), table_copy.PARTIAL)
        self.assertEqual(table_copy.toggle_floor(rows, some),
                         {id(r) for r in rows} | {id(ROWS[3])}, "partial: all, others kept")
        self.assertEqual(table_copy.floor_mark([], set()), "")
        self.assertEqual(table_copy.marked_in_order(by_floor(ROWS), {id(ROWS[1]), id(ROWS[4])}),
                         [ROWS[4], ROWS[1]], "table order")

    def test_nothing(self):
        for fmt in (table_copy.MARKDOWN, table_copy.TSV):
            self.assertEqual(table_copy.table_text([], fmt, T), "")


class TabTests(unittest.TestCase):

    def setUp(self):
        from primeatlas.core import ui_state_dynamic
        from primeatlas.core.ui_state_store import UiStateStore
        self._saved_store = ui_state_dynamic.STORE
        ui_state_dynamic.STORE = UiStateStore(None)

    def tearDown(self):
        from primeatlas.core import ui_state_dynamic
        ui_state_dynamic.STORE = self._saved_store

    @staticmethod
    def floor_node(tab, floor):
        tree = tab.benchmark_tree
        return next(n for n in tree.get_children("")
                    if tree.item(n, "text").startswith(f"10p{floor} "))

    @staticmethod
    def copy(tab, root, items, keys="<Control-c>"):
        """Selects `items`, presses `keys` on the tree, returns the clipboard."""
        tree = tab.benchmark_tree
        root.clipboard_clear()
        root.clipboard_append(SENTINEL)
        tree.selection_set(items)
        root.update()
        tree.focus_force()
        root.update()
        tree.event_generate(keys)
        root.update()
        return root.clipboard_get()

    @staticmethod
    def runs(text):
        return [cells[1] for cells in md_rows(text)[1:]]

    def test_copy_keys(self):
        def body(tab, root, points):
            run = chart_points_tests.TabTests._row_item(tab, 28, "e")
            self.assertEqual(self.runs(self.copy(tab, root, [run])), ["e"], "one run")
            f29 = self.floor_node(tab, 29)
            self.assertFalse(tab.benchmark_tree.item(f29, "open"))
            self.assertEqual(self.runs(self.copy(tab, root, [f29])), ["a", "b", "c"],
                             "a collapsed floor: all its runs")
            self.assertEqual(self.runs(self.copy(tab, root, [f29, run])), ["e", "a", "b", "c"])
            f28 = self.floor_node(tab, 28)
            stat = tab.benchmark_tree.get_children(f28)[0]
            self.assertIn("stat", tab.benchmark_tree.item(stat, "tags"))
            self.assertEqual(self.runs(self.copy(tab, root, [stat, run])), ["d", "e", "f"],
                             "the stats row stands for its floor; its run once")
            text = self.copy(tab, root, [run], "<Control-Shift-C>")
            self.assertIn("\t", text)
            self.assertNotIn("|", text)
            self.assertEqual(text.splitlines()[1].split("\t")[1], "e", "TSV")
            self.assertEqual(self.copy(tab, root, []), SENTINEL, "nothing selected")
        chart_points_tests.TabTests._tab(self, ROWS, body)

    @staticmethod
    def mark(tab, root, item):
        tree = tab.benchmark_tree
        tree.see(item)
        root.update()
        x, y, w, h = tree.bbox(item, table_copy.CHECK_COLUMN)
        tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2)
        tree.event_generate("<ButtonRelease-1>", x=x + w // 2, y=y + h // 2)
        root.update()

    @staticmethod
    def box(tab, item):
        return tab.benchmark_tree.set(item, table_copy.CHECK_COLUMN)

    def press(self, tab, root, keys):
        tree = tab.benchmark_tree
        root.clipboard_clear()
        root.clipboard_append(SENTINEL)
        tree.focus_force()
        root.update()
        tree.event_generate(keys)
        root.update()
        return root.clipboard_get()

    def test_marks(self):
        def body(tab, root, points):
            tree = tab.benchmark_tree
            columns = tuple(tree.cget("displaycolumns"))
            self.assertEqual(columns[0], table_copy.CHECK_COLUMN, "the box column first")
            f28, f29 = self.floor_node(tab, 28), self.floor_node(tab, 29)
            run_e = chart_points_tests.TabTests._row_item(tab, 28, "e")
            tree.item(f28, open=True)
            tree.selection_set(())
            root.update()
            self.assertEqual(self.box(tab, f28), table_copy.UNMARKED)
            self.assertEqual(self.box(tab, run_e), table_copy.UNMARKED)
            stat = tree.get_children(f28)[0]
            self.assertEqual(self.box(tab, stat), "", "the stats row has no box")
            self.mark(tab, root, run_e)
            self.assertEqual(self.box(tab, run_e), table_copy.MARKED)
            self.assertEqual(self.box(tab, f28), table_copy.PARTIAL)
            self.assertEqual(tree.selection(), (), "a box click selects nothing")
            self.mark(tab, root, f29)
            self.assertFalse(tree.item(f29, "open"))
            self.assertEqual(self.box(tab, f29), table_copy.MARKED, "collapsed floor marked")
            self.assertEqual(self.runs(self.press(tab, root, "<Control-c>")),
                             ["e", "a", "b", "c"], "marked runs of both floors")
            for item in (f28, f29, run_e):
                self.assertEqual(self.box(tab, item), table_copy.UNMARKED, "unmarked after copy")
            self.assertEqual(tab._copy_marks, set())
            self.mark(tab, root, f29)
            tree.item(f29, open=True)
            tab._populate_benchmark_floor_node(f29)
            root.update()
            runs29 = [i for i in tree.get_children(f29) if i in tab._tree_item_rows]
            self.assertEqual([self.box(tab, i) for i in runs29], [table_copy.MARKED] * 3,
                             "opened later: its runs show the floor's marks")
            self.mark(tab, root, runs29[0])
            self.assertEqual(self.box(tab, f29), table_copy.PARTIAL)
            self.mark(tab, root, f29)
            self.assertEqual(self.box(tab, f29), table_copy.MARKED, "partial floor: all")
            self.mark(tab, root, f29)
            self.assertEqual([self.box(tab, i) for i in runs29 + [f29]],
                             [table_copy.UNMARKED] * 4, "all marked: none")
            tree.focus(run_e)
            self.press(tab, root, "<space>")
            self.assertEqual(self.box(tab, run_e), table_copy.MARKED, "Space marks")
            text = self.press(tab, root, "<Control-Shift-C>")
            self.assertEqual([line.split("	")[1] for line in text.splitlines()[1:]], ["e"],
                             "TSV of the marks")
            self.assertEqual(self.box(tab, run_e), table_copy.UNMARKED)
            self.mark(tab, root, f28)
            tab._set_filter({"engine": {"v7.1"}})
            root.update()
            self.assertEqual(tab._copy_marks, set(), "a filter change unmarks")
        chart_points_tests.TabTests._tab(self, ROWS, body)

    def test_mark_all_from_the_heading(self):
        def body(tab, root, points):
            tree = tab.benchmark_tree
            col = table_copy.CHECK_COLUMN

            def heading_click():
                tree.tk.call(tree.heading(col, "command"))
                root.update()

            def head():
                return tree.heading(col, "text")

            label = T("bench.copy_column")
            self.assertEqual(head(), f"{table_copy.UNMARKED} {label}")
            floors = list(tree.get_children(""))
            heading_click()
            self.assertEqual(head(), f"{table_copy.MARKED} {label}")
            self.assertEqual([self.box(tab, f) for f in floors], [table_copy.MARKED] * 3,
                             "every floor, collapsed ones too")
            self.assertEqual(len(tab._copy_marks), len(ROWS))
            heading_click()
            self.assertEqual(tab._copy_marks, set(), "all marked: the heading unmarks all")
            self.assertEqual(head(), f"{table_copy.UNMARKED} {label}")
            run_e = chart_points_tests.TabTests._row_item(tab, 28, "e")
            self.mark(tab, root, run_e)
            self.assertEqual(head(), f"{table_copy.PARTIAL} {label}")
            heading_click()
            self.assertEqual(len(tab._copy_marks), len(ROWS), "some marked: all")
            self.assertEqual(self.runs(self.press(tab, root, "<Control-c>")),
                             ["g", "d", "e", "f", "a", "b", "c"], "all runs, table order")
            self.assertEqual(head(), f"{table_copy.UNMARKED} {label}", "cleared after copy")
            tab._set_filter({"floor": {"28"}})
            root.update()
            heading_click()
            self.assertEqual(self.runs(self.press(tab, root, "<Control-c>")), ["d", "e", "f"],
                             "all = what the filter keeps")
            tab._set_filter({"floor": {"nothing"}})
            root.update()
            heading_click()
            self.assertEqual(tab._copy_marks, set(), "no runs: nothing to mark")
            self.assertEqual(head(), label, "no runs: no box in the heading")
        chart_points_tests.TabTests._tab(self, ROWS, body)

    def test_hint_above_the_table(self):
        def body(tab, root, points):
            label, tip = tab.copy_hint_label, tab.copy_info
            self.assertEqual(label.cget("text"), T("bench.copy_hint"))
            self.assertEqual(tip.text(), T("bench.copy_tip"))
            for widget in (label, tip.label):
                self.assertTrue(widget.winfo_ismapped(), widget)
                self.assertEqual(widget.master, tab.benchmark_prev_btn.master,
                                 "in the row above the table")
            for key in ("bench.copy_hint", "bench.copy_tip"):
                for lang in ("en", "pl"):
                    self.assertNotEqual(Translator(lang)(key), key, f"{lang} {key}")
            text = T("bench.copy_tip")
            for words in ("Ctrl+C", "Ctrl+Shift+C", "Markdown", table_copy.UNMARKED):
                self.assertIn(words, text)
        chart_points_tests.TabTests._tab(self, ROWS, body)

    def test_copy_follows_filter(self):
        rows = ROWS + [_row(29, 10 ** 10, 2000.0, version="v7.2", ts="h")]

        def body(tab, root, points):
            tab._set_filter({"engine": {"v7.2"}})
            root.update()
            self.assertEqual(self.runs(self.copy(tab, root, [self.floor_node(tab, 29)])), ["h"])
            tab._set_filter({"floor": {"nothing"}})
            root.update()
            placeholder = tab.benchmark_tree.get_children("")
            self.assertEqual(self.copy(tab, root, placeholder), SENTINEL, "no-data row")
        chart_points_tests.TabTests._tab(self, rows, body)


if __name__ == "__main__":
    unittest.main()
