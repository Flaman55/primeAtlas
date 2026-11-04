"""
test_ui_state.py -- core/ui_state.py: the per-install store of remembered form fields and
remember(), which binds one tk Variable or input widget to one store key.

Checks: a missing or corrupt file gives an empty store; set() writes the file only after
the debounce delay (one write for a burst of changes), flush() writes at once, an
unchanged value does not mark the store dirty, a store without a path never writes;
remember() restores a saved value and saves later changes; restore=False only tracks;
a read-only Combobox restores only a value it lists; choices= stores an id for a
translated label (a list parallel to a Combobox's values, or an {id: label} dict) and
survives a language change; an Entry or Combobox without a
textvariable gets one and keeps its text when nothing is saved; a saved value of the wrong
type for a BooleanVar is ignored.

Usage:
    python unitTests/test_ui_state.py
"""
import json
import os
import shutil
import sys
import tempfile
import tkinter as tk
from tkinter import ttk

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core import ui_state  # noqa: E402
from primeatlas.core.ui_state import UiStateStore, remember  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_store(folder):
    path = os.path.join(folder, "ui_state.json")
    store = UiStateStore(path)
    check(store.get("a") is None and store.get("a", 5) == 5, "missing file -> empty store")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    check(UiStateStore(path).get("a") is None, "corrupt file -> empty store")
    with open(path, "w", encoding="utf-8") as f:
        f.write("[1, 2]")
    check(UiStateStore(path).get("a") is None, "non-dict file -> empty store")
    os.remove(path)

    root = tk.Tk()
    root.withdraw()
    try:
        store = UiStateStore(path)
        store.attach(root)
        writes = []
        real_write = store._write
        store._write = lambda: (writes.append(1), real_write())
        store.set("x", "1")
        store.set("x", "2")
        store.set("y", True)
        check(not os.path.exists(path), "set() does not write at once")
        root.after(ui_state.SAVE_DELAY_MS + 200, root.quit)
        root.mainloop()
        check(len(writes) == 1 and _read(path) == {"x": "2", "y": True},
              f"one debounced write for a burst of changes ({len(writes)} writes)")
        store.set("y", True)
        check(not store.dirty, "an unchanged value does not mark the store dirty")
        store.set("x", "3")
        store.flush()
        check(_read(path)["x"] == "3" and not store.dirty, "flush() writes at once")
        check(UiStateStore(path).get("x") == "3", "a new store reads the saved values")
        leftovers = [n for n in os.listdir(folder) if n.startswith("ui_state.json.")]
        check(not leftovers, f"atomic write leaves no temp file ({leftovers})")
    finally:
        root.destroy()

    memory = UiStateStore(None)
    memory.set("x", "1")
    memory.flush()
    check(memory.get("x") == "1" and os.listdir(folder) == ["ui_state.json"],
          "a store without a path keeps values in memory and never writes")


def check_remember():
    root = tk.Tk()
    root.withdraw()
    try:
        store = UiStateStore(None)
        store.set("f.saved", "27")
        var = tk.StringVar(value="1")
        returned = remember("f.saved", var, store=store)
        check(returned is var and var.get() == "27", "remember() restores a saved value")
        var.set("28")
        check(store.get("f.saved") == "28", "a later change is saved")

        fresh = tk.StringVar(value="default")
        remember("f.fresh", fresh, store=store)
        check(fresh.get() == "default" and store.get("f.fresh") is None,
              "nothing saved -> the default stays and nothing is written yet")

        store.set("f.track", "old")
        tracked = tk.StringVar(value="new")
        remember("f.track", tracked, store=store, restore=False)
        check(tracked.get() == "new", "restore=False keeps the variable's value")
        tracked.set("newer")
        check(store.get("f.track") == "newer", "restore=False still saves changes")

        flag = tk.BooleanVar(value=False)
        store.set("f.flag", "yes")
        remember("f.flag", flag, store=store)
        check(flag.get() is False, "a non-bool saved for a BooleanVar is ignored")
        flag.set(True)
        check(store.get("f.flag") is True, "a BooleanVar saves a bool")

        engine = tk.StringVar(value="v6")
        combo = ttk.Combobox(root, state="readonly", values=("v4.1", "v5", "v6"),
                             textvariable=engine)
        store.set("f.engine", "v9")
        remember("f.engine", engine, store=store, widget=combo)
        check(engine.get() == "v6", "a read-only Combobox ignores a value it does not list")
        store.set("f.engine2", "v5")
        engine2 = tk.StringVar(value="v6")
        combo2 = ttk.Combobox(root, state="readonly", values=("v4.1", "v5", "v6"),
                              textvariable=engine2)
        remember("f.engine2", engine2, store=store, widget=combo2)
        check(engine2.get() == "v5", "a read-only Combobox restores a listed value")

        ids = ["even", "concentrated", "manual"]
        labels_en = ["Even", "Concentrated", "Manual"]
        strategy = ttk.Combobox(root, state="readonly", values=labels_en)
        strategy.current(1)
        remember("f.strategy", strategy, store=store, choices=ids)
        strategy.current(2)
        check(store.get("f.strategy") == "manual", "choices= stores the id, not the label")
        labels_pl = ["Równo", "Skupione", "Ręcznie"]
        strategy_pl = ttk.Combobox(root, state="readonly", values=labels_pl)
        strategy_pl.current(1)
        remember("f.strategy", strategy_pl, store=store, choices=ids)
        check(strategy_pl.get() == "Ręcznie", "the id restores under another language's labels")

        target = tk.StringVar(value="Continue")
        labels = {"n": "n", "continue": "Continue", "fill": "Fill a gap"}
        remember("f.target", target, store=store, choices=labels)
        target.set("Fill a gap")
        check(store.get("f.target") == "fill", "dict choices= stores the id of a Variable's label")
        target_pl = tk.StringVar(value="Kontynuuj")
        remember("f.target", target_pl, store=store,
                 choices={"n": "n", "continue": "Kontynuuj", "fill": "Uzupełnij lukę"})
        check(target_pl.get() == "Uzupełnij lukę", "... and restores that id's label in another language")
        target_pl.set("free text")
        check(store.get("f.target") == "fill", "a value outside the choices is not stored")

        entry = ttk.Entry(root)
        entry.insert(0, "100")
        entry_var = remember("f.entry", entry, store=store)
        check(entry.get() == "100" and str(entry.cget("textvariable")) == str(entry_var),
              "an Entry gets a textvariable and keeps its text when nothing is saved")
        entry.delete(0, "end")
        entry.insert(0, "250")
        check(store.get("f.entry") == "250", "typing into the Entry is saved")
        store.set("f.entry2", "n**2 + 1")
        entry2 = ttk.Entry(root)
        entry2.insert(0, "n**2")
        remember("f.entry2", entry2, store=store)
        check(entry2.get() == "n**2 + 1", "a saved value replaces the Entry's default text")
    finally:
        root.destroy()


def main():
    folder = tempfile.mkdtemp(prefix="primeatlas_ui_state_test_")
    try:
        check_store(folder)
        check_remember()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
