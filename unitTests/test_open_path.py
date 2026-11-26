"""Opening the storage folder and a saved export (core/open_path.py and its callers).

A. open_path() hands an existing path to the system opener and raises OSError for a
   missing one or when the opener fails.
B. open_folder() opens an existing folder; a missing folder (or a file in its place) gives
   an info message naming it, opens nothing and creates nothing; an opener failure gives
   the "could not open" error with the path and the error, without raising.
C. The saved dialog is modal over its parent and shows the saved paths with OK (the
   default) and Open: OK, Enter, Escape and closing the window open nothing; Open opens the
   main file and closes the dialog; an Open failure gives the "could not open" error and
   closes the dialog without raising.
D. The Benchmark tab: the Folder button stands right after Filter..., is enabled without
   data and with a filter, opens the storage folder and changes no view state. Every export
   ends in the saved dialog with the written paths, Open on the main file (the .csv of the
   CSV pair); a save error or a cancelled file dialog shows no saved dialog.
E. The Constellations Records export ends in the same saved dialog.
    python unitTests/test_open_path.py
"""
import csv
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation"),
                str(ROOT / "unitTests")]

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

from app_sandbox import fresh_ui_store  # noqa: E402
from primeatlas.core import open_path  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

T = Translator("en")


class _Patched:
    """Records the system opener's calls and the message boxes, restores them on exit."""

    def __init__(self, fail=None):
        self.launched, self.shown = [], []
        self._fail = fail

    def __enter__(self):
        self._saved = (open_path._launch, messagebox.showinfo, messagebox.showerror)

        def launch(path):
            if self._fail is not None:
                raise self._fail
            self.launched.append(path)

        open_path._launch = launch
        messagebox.showinfo = lambda title, text, **k: self.shown.append(("info", text))
        messagebox.showerror = lambda title, text, **k: self.shown.append(("error", text))
        return self

    def __exit__(self, *exc):
        open_path._launch, messagebox.showinfo, messagebox.showerror = self._saved


class OpenPathTests(unittest.TestCase):
    def test_existing_file_and_folder_go_to_the_opener(self):
        with tempfile.TemporaryDirectory() as folder, _Patched() as p:
            path = os.path.join(folder, "report.pdf")
            Path(path).write_text("x")
            open_path.open_path(path)
            open_path.open_path(folder)
            self.assertEqual(p.launched, [os.path.abspath(path), os.path.abspath(folder)])

    def test_missing_path_raises_and_opens_nothing(self):
        with tempfile.TemporaryDirectory() as folder, _Patched() as p:
            with self.assertRaises(OSError):
                open_path.open_path(os.path.join(folder, "gone.pdf"))
            self.assertEqual(p.launched, [])

    def test_opener_failure_raises(self):
        with tempfile.TemporaryDirectory() as folder, _Patched(fail=OSError("no app")):
            with self.assertRaises(OSError):
                open_path.open_path(folder)


class OpenFolderTests(unittest.TestCase):
    def test_existing_folder_opens_without_a_message(self):
        with tempfile.TemporaryDirectory() as folder, _Patched() as p:
            open_path.open_folder(None, folder, T)
            self.assertEqual(p.launched, [os.path.abspath(folder)])
            self.assertEqual(p.shown, [])

    def test_missing_folder_says_so_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as parent, _Patched() as p:
            for folder in (os.path.join(parent, "CONSTELLATION_PORTAL"),
                           os.path.join(parent, "a", "b")):
                p.shown.clear()
                open_path.open_folder(None, folder, T)
                self.assertEqual(p.shown, [("info", T("open.folder_missing", path=folder))])
                self.assertFalse(os.path.exists(folder), "the folder is not created")
            self.assertEqual(p.launched, [])

    def test_a_file_in_place_of_the_folder_is_missing(self):
        with tempfile.TemporaryDirectory() as parent, _Patched() as p:
            path = os.path.join(parent, "portal")
            Path(path).write_text("x")
            open_path.open_folder(None, path, T)
            self.assertEqual(p.shown, [("info", T("open.folder_missing", path=path))])
            self.assertEqual(p.launched, [])

    def test_opener_failure_is_a_message(self):
        with tempfile.TemporaryDirectory() as folder, \
                _Patched(fail=PermissionError("denied")) as p:
            open_path.open_folder(None, folder, T)
            self.assertEqual(p.shown, [("error", T("open.failed", path=folder,
                                                   error=PermissionError("denied")))])


class SavedDialogTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.folder = tempfile.TemporaryDirectory()
        self.main = os.path.join(self.folder.name, "report.csv")
        self.second = os.path.join(self.folder.name, "report_computers.csv")
        for path in (self.main, self.second):
            Path(path).write_text("x")

    def tearDown(self):
        self.root.destroy()
        self.folder.cleanup()

    def dialog(self):
        return open_path.SavedDialog(self.root, "Export CSV", [self.main, self.second], T)

    def _texts(self, widget):
        found = []
        for child in widget.winfo_children():
            try:
                found.append(child.cget("text"))
            except tk.TclError:
                pass
            found.extend(self._texts(child))
        return found

    def test_shows_the_paths_ok_and_open(self):
        d = self.dialog()
        self.root.update()
        texts = self._texts(d)
        self.assertIn(T("bench.saved_dialog", path=f"{self.main}\n{self.second}"), texts)
        self.assertEqual(d.ok_button.cget("text"), T("common.ok"))
        self.assertEqual(d.open_button.cget("text"), T("common.open"))
        self.assertEqual(d.title(), "Export CSV")
        self.assertEqual(str(d.grab_current()), str(d), "the dialog is modal")
        self.assertEqual(str(d.transient()), str(self.root))
        self.assertEqual(str(d.focus_lastfor()), str(d.ok_button), "OK is the default")

    def test_ok_enter_escape_and_close_open_nothing(self):
        for close in (lambda d: d.ok_button.invoke(),
                      lambda d: d.event_generate("<Return>"),
                      lambda d: d.event_generate("<Escape>"),
                      lambda d: d.tk.call(d.protocol("WM_DELETE_WINDOW"))):
            with _Patched() as p:
                d = self.dialog()
                self.root.update()
                d.focus_force()
                close(d)
                self.root.update()
                self.assertFalse(d.winfo_exists())
                self.assertEqual((p.launched, p.shown), ([], []))

    def test_open_opens_the_main_file_and_closes(self):
        with _Patched() as p:
            d = self.dialog()
            d.open_button.invoke()
            self.root.update()
            self.assertEqual(p.launched, [os.path.abspath(self.main)])
            self.assertFalse(d.winfo_exists())

    def test_open_failure_is_a_message_and_closes(self):
        for fail, gone in ((OSError("no app"), False), (None, True)):
            with _Patched(fail=fail) as p:
                if gone:
                    os.remove(self.main)
                d = self.dialog()
                d.open_button.invoke()
                self.root.update()
                self.assertEqual([kind for kind, _ in p.shown], ["error"])
                self.assertTrue(p.shown[0][1].startswith(
                    T("open.failed", path=self.main, error="").rstrip()))
                self.assertFalse(d.winfo_exists())
                self.assertEqual(p.launched, [])


RUN = {"timestamp_utc": "2026-11-20T10:00:00Z", "engine": "v5", "engine_version": "5.0",
       "base_exponent": "12", "range_width": "1000000", "sieve_threads": "24",
       "write_threads": "8", "numbers_processed": "1000000", "total_seconds": "2.0",
       "loop_numbers_per_second": "500000", "purpose": "benchmark"}


class BenchmarkTabTests(unittest.TestCase):
    def setUp(self):
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for
        self.portal = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        fresh_ui_store()
        self.tab = benchmark_tab.BenchmarkTab(
            self.root, lambda: self.portal.name, tk.StringVar(master=self.root), T,
            lambda *a, **k: None, palette_for("light"))
        self.tab.pack()
        self.saved = []
        self._show_saved = open_path.show_saved
        open_path.show_saved = lambda parent, title, paths, T: self.saved.append(list(paths))
        self._ask = filedialog.asksaveasfilename

    def tearDown(self):
        open_path.show_saved = self._show_saved
        filedialog.asksaveasfilename = self._ask
        self.root.destroy()
        self.portal.cleanup()

    def write_log(self):
        with open(os.path.join(self.portal.name, "benchmark_log.csv"), "w", newline="",
                  encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(RUN))
            writer.writeheader()
            writer.writerow(RUN)
        self.tab.reload_benchmark_log()

    def folder_button(self):
        filter_text, folder_text = T("bench.filter_button"), T("bench.folder_button")
        for frame in self._frames(self.tab):
            children = frame.winfo_children()
            texts = [c.cget("text") if isinstance(c, ttk.Button) else None for c in children]
            if filter_text in texts:
                at = texts.index(filter_text)
                self.assertEqual(texts[at + 1], folder_text, "Folder follows Filter...")
                return children[at + 1]
        self.fail("no Filter... button")

    def _frames(self, widget):
        yield widget
        for child in widget.winfo_children():
            yield from self._frames(child)

    def test_folder_button_opens_the_storage_folder(self):
        button = self.folder_button()
        for state in ("no data", "data", "filter"):
            if state == "data":
                self.write_log()
            if state == "filter":
                self.tab._filter_selection = {"engine": {"v5 5.0"}}
            view = (dict(self.tab._filter_selection or {}),
                    {k: set(v) for k, v in self.tab._hidden_lines.items()})
            self.assertNotIn("disabled", button.state(), state)
            with _Patched() as p:
                button.invoke()
            self.assertEqual(p.launched, [os.path.abspath(self.portal.name)], state)
            self.assertEqual(p.shown, [], state)
            self.assertEqual(view, (dict(self.tab._filter_selection or {}),
                                    {k: set(v) for k, v in self.tab._hidden_lines.items()}))

    def test_folder_button_with_the_folder_gone(self):
        button = self.folder_button()
        self.portal.cleanup()
        with _Patched() as p:
            button.invoke()
        self.assertEqual(p.shown, [("info", T("open.folder_missing", path=self.portal.name))])
        self.assertFalse(os.path.exists(self.portal.name))

    def test_every_export_ends_in_the_saved_dialog(self):
        self.write_log()
        for kind, ext in (("pdf", ".pdf"), ("csv", ".csv"), ("svg", ".svg"),
                          ("html", ".html"), ("snippet", ".html")):
            path = os.path.join(self.portal.name, f"out_{kind}{ext}")
            filedialog.asksaveasfilename = lambda **k: path
            self.saved.clear()
            with _Patched() as p:
                if kind == "pdf":
                    self.tab._export_benchmark_pdf()
                else:
                    self.tab._export_report(kind)
            self.assertEqual(p.shown, [], kind)
            self.assertEqual(len(self.saved), 1, kind)
            self.assertEqual(self.saved[0][0], path, f"{kind}: Open takes the main file")
            self.assertTrue(all(os.path.exists(s) for s in self.saved[0]), kind)
            if kind == "csv":
                self.assertEqual(len(self.saved[0]), 2)

    def test_error_or_cancel_shows_no_saved_dialog(self):
        self.write_log()
        filedialog.asksaveasfilename = lambda **k: ""
        with _Patched() as p:
            self.tab._export_report("csv")
            self.tab._export_benchmark_pdf()
        self.assertEqual((self.saved, p.shown), ([], []))
        filedialog.asksaveasfilename = lambda **k: os.path.join(self.portal.name, "no", "x.pdf")
        with _Patched() as p:
            self.tab._export_benchmark_pdf()
            self.tab._export_report("html")
        self.assertEqual(self.saved, [])
        self.assertEqual([kind for kind, _ in p.shown], ["error", "error"])


class RecordsTabTests(unittest.TestCase):
    def test_records_export_ends_in_the_saved_dialog(self):
        from primeatlas.constellations.constellations_records_tab import \
            ConstellationsRecordsTab
        saved, status = [], []
        stub = types.SimpleNamespace(
            T=T, _busy=True, scan_button=types.SimpleNamespace(configure=lambda **k: None),
            _stop_busy_progress=lambda: None, _refresh_export_buttons_state=lambda: None,
            status=types.SimpleNamespace(set=status.append))
        original = open_path.show_saved
        open_path.show_saved = lambda parent, title, paths, T: saved.append((title,
                                                                             list(paths)))
        try:
            with _Patched() as p:
                for mode in ("export_pdf", "export_csv"):
                    ConstellationsRecordsTab._on_worker_result(
                        stub, (mode, 4, True, f"C:/out/{mode}.x"), None)
        finally:
            open_path.show_saved = original
        self.assertEqual(saved, [(T("const_records.export_pdf_button"), ["C:/out/export_pdf.x"]),
                                 (T("const_records.export_csv_button"),
                                  ["C:/out/export_csv.x"])])
        self.assertEqual(p.shown, [])
        self.assertEqual(status[-1], T("bench.status_saved", path="C:/out/export_csv.x"))


class StringTests(unittest.TestCase):
    def test_both_languages(self):
        for lang in ("en", "pl"):
            t = Translator(lang)
            for key in ("common.ok", "common.open", "open.failed", "open.folder_missing",
                        "bench.folder_button"):
                self.assertNotEqual(t(key), key, f"{lang}: {key}")
        self.assertEqual(Translator("pl")("bench.folder_button"), "Katalog")
        self.assertEqual(T("bench.folder_button"), "Folder")


def main():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
