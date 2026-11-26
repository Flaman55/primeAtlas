"""open_path.py -- opening a folder or a saved file with the system's default program.

open_path() hands an existing path to the system opener (os.startfile on Windows,
`open` on macOS, `xdg-open` elsewhere) and raises OSError for a missing path or a failed
opener. open_folder() is the "Folder" buttons' action: a missing folder is reported, never
created (a typo in the storage path or an unplugged drive must not get a new empty
folder). SavedDialog is the app's "Saved" message after an export: the saved paths with
OK (the default) and Open, which opens the main file -- the first path -- and closes.
show_saved() opens it and waits until it closes.
"""
import os
import subprocess
import sys

import tkinter as tk
from tkinter import messagebox, ttk

STRING_KEYS = ("common.ok", "common.open", "open.failed", "open.folder_missing",
               "bench.saved_dialog")


def _launch(path):
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def open_path(path):
    """Opens `path` (a file or a folder) in its default program; OSError when it fails."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"no such file or folder: {path}")
    _launch(path)


def _open_or_report(parent, path, T):
    try:
        open_path(path)
    except OSError as exc:
        messagebox.showerror(T("common.open"), T("open.failed", path=path, error=exc),
                             parent=parent)


def open_folder(parent, folder, T):
    """Opens `folder` in the file manager; a missing folder is an info message."""
    if not os.path.isdir(folder):
        messagebox.showinfo(T("common.open"), T("open.folder_missing", path=folder),
                            parent=parent)
        return
    _open_or_report(parent, folder, T)


class SavedDialog(tk.Toplevel):
    """Modal "Saved" message over `parent`: `paths` (the main file first), OK and Open."""

    def __init__(self, parent, title, paths, T):
        super().__init__(parent)
        self._main = paths[0]
        self._T = T
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=T("bench.saved_dialog", path="\n".join(paths)),
                  justify="left", wraplength=560).pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(12, 0))
        self.open_button = ttk.Button(buttons, text=T("common.open"), command=self._open)
        self.open_button.pack(side="left")
        self.ok_button = ttk.Button(buttons, text=T("common.ok"), command=self.destroy,
                                    default="active")
        self.ok_button.pack(side="left", padx=(6, 0))
        self.bind("<Return>", lambda _e: self.destroy())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.ok_button.focus_set()

    def _open(self):
        parent = self.master
        self.destroy()
        _open_or_report(parent, self._main, self._T)


def show_saved(parent, title, paths, T):
    """Shows SavedDialog and returns when it closes."""
    dialog = SavedDialog(parent, title, list(paths), T)
    dialog.wait_window()
