"""The Rings tab's renderer argv lives in primeatlas/visualization/rings/rings_argv.py and
its form is built section by section.

Checks: rings_argv defines build_renderer_argv and RENDERER_SCRIPT; rings_tab defines
neither and keeps no import that only the argv used; the script a test replaces is
rings_argv.RENDERER_SCRIPT, and Start launches exactly that script; _build_ui builds the
four sections (Position & mode, Windows & tracking, Appearance, Audio) through their own
methods, in that order. Windows, real display:
    python unitTests/test_rings_tab_split.py
"""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from app_sandbox import fresh_ui_store  # noqa: E402

from primeatlas.core.i18n import Translator  # noqa: E402

failures = []

SECTIONS = ("_build_position_section", "_build_windows_section", "_build_appearance_section",
            "_build_audio_section")
# Names rings_tab defined or imported only for the argv.
ARGV_ONLY_NAMES = ("build_renderer_argv", "RENDERER_SCRIPT", "_THIS_DIR", "sys")


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_module_split():
    try:
        from primeatlas.visualization.rings import rings_argv
    except ImportError as exc:
        check(False, f"primeatlas.visualization.rings.rings_argv imports ({exc})")
        return
    from primeatlas.visualization.rings import rings_tab

    check(callable(getattr(rings_argv, "build_renderer_argv", None)),
          "rings_argv defines build_renderer_argv")
    script = getattr(rings_argv, "RENDERER_SCRIPT", "")
    check(script.replace("\\", "/").endswith("visualization/shared/renderer.py"),
          f"rings_argv.RENDERER_SCRIPT is the shared renderer (got {script!r})")
    left = [name for name in ARGV_ONLY_NAMES if hasattr(rings_tab, name)]
    check(not left, f"rings_tab keeps no argv-only name (left: {left})")


class _FakeRunner:
    """Records the argv and exits at once, so no process is started."""
    launched = []

    def __init__(self, cmd, q, pipe_stdin=False):
        _FakeRunner.launched.append(list(cmd))
        self.q = q

    def start(self):
        self.q.put(("__exit__", 0))

    def is_running(self):
        return False

    def stop(self):
        pass


def _build_tab(root, rings_tab, portal):
    import tkinter as tk
    tab = rings_tab.RingsTab(root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                             None)
    tab.pack(fill="both", expand=True)
    root.update()
    return tab


def _labelframe_texts(widget):
    """Texts of every labelled frame under `widget`, in creation order."""
    texts = []
    for child in widget.winfo_children():
        if child.winfo_class() == "TLabelframe":
            texts.append(str(child.cget("text")))
        texts += _labelframe_texts(child)
    return texts


def _test_script_seam_reaches_start():
    import tkinter as tk
    import tkinter.messagebox
    try:
        from primeatlas.visualization.rings import rings_argv
    except ImportError as exc:
        check(False, f"the renderer script seam is rings_argv.RENDERER_SCRIPT ({exc})")
        return
    from primeatlas.visualization.rings import rings_tab

    shown = []
    real = (rings_argv.RENDERER_SCRIPT, rings_tab.LocalLoggedRunner,
            rings_tab.find_highest_populated_floor, tkinter.messagebox.showerror)
    rings_argv.RENDERER_SCRIPT = "FAKE_RENDERER_SCRIPT"
    rings_tab.LocalLoggedRunner = _FakeRunner
    rings_tab.find_highest_populated_floor = lambda portal: 0
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(a)
    root = tk.Tk()
    try:
        fresh_ui_store()
        with tempfile.TemporaryDirectory() as portal:
            tab = _build_tab(root, rings_tab, portal)
            _FakeRunner.launched.clear()
            tab._on_open()
            root.update()
            launched = _FakeRunner.launched
            check(not shown, f"Start shows no error (got {shown})")
            check(len(launched) == 1 and launched[0][1:2] == ["FAKE_RENDERER_SCRIPT"],
                  f"Start launches rings_argv.RENDERER_SCRIPT (got {launched[0][:2] if launched else None})")
    finally:
        (rings_argv.RENDERER_SCRIPT, rings_tab.LocalLoggedRunner,
         rings_tab.find_highest_populated_floor, tkinter.messagebox.showerror) = real
        root.destroy()


def _test_sections_built_in_order():
    import tkinter as tk
    from primeatlas.visualization.rings import rings_tab

    cls = rings_tab.RingsTab
    missing = [name for name in SECTIONS if not callable(getattr(cls, name, None))]
    check(not missing, f"RingsTab has a method per section (missing: {missing})")
    if missing:
        return
    calls = []
    originals = {name: getattr(cls, name) for name in SECTIONS}

    def spy(name):
        def wrapper(self, *args, **kwargs):
            calls.append(name)
            return originals[name](self, *args, **kwargs)
        return wrapper

    for name in SECTIONS:
        setattr(cls, name, spy(name))
    root = tk.Tk()
    try:
        fresh_ui_store()
        tab = _build_tab(root, rings_tab, os.getcwd())
        check(calls == list(SECTIONS), f"_build_ui builds the four sections in order (got {calls})")
        expected = [tab.T(f"rings.section_{key}")
                    for key in ("position", "windows", "appearance", "audio")]
        sections = [text for text in _labelframe_texts(tab) if text in expected]
        check(sections == expected, f"the four section frames come in that order (got {sections})")
    finally:
        for name, method in originals.items():
            setattr(cls, name, method)
        root.destroy()


def main():
    _test_module_split()
    _test_script_seam_reaches_start()
    _test_sections_built_in_order()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
