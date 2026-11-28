"""Settings > General refuses a red number field only when an action uses it
(core/number_field.refuse_problem), and never changes the text the user typed.

Drives the real app (temp storage, saves and restarts stubbed) with test_field_refusal_app's
Harness:
  - Apply asks about the background brightness, text brightness and font size fields; a red
    one shows the error, saves nothing, restarts nothing and keeps every field's text;
  - Enter in the scroll-area width field and its spin command ask about that field only; a
    red width shows the error, saves nothing, leaves every ScrollPad as it was and keeps the
    text;
  - leaving a red width field (FocusOut) shows nothing, saves nothing and keeps the text;
    leaving a valid one applies it as before;
  - an empty field behaves as before: the width field and the Apply fields go back to the
    saved values, nothing is saved;
  - Reset never refuses: it saves the defaults over red fields and restarts;
  - a red field of the other group does not block an action;
  - the minima and maxima stay the ranges the setters clamp to.
Windows, real display:
    python unitTests/test_field_refusal_settings_app.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_field_refusal_app import Harness, _enter  # noqa: E402
from test_time_simulation import FAKE_FREE_RAM, check  # noqa: E402


def _wait_loaded(app, seconds=60):
    """Waits until the loading screen gives way to the tabs (Enter needs a shown field)."""
    import time
    end = time.monotonic() + seconds
    while not app.main_notebook.winfo_manager() and time.monotonic() < end:
        app.update()
        time.sleep(0.02)
    return check(bool(app.main_notebook.winfo_manager()), "the tabs are shown after loading")


def _leave(entry):
    """FocusOut of `entry`, with every notebook page holding it shown."""
    w = entry
    while w.master is not None:
        if w.master.winfo_class() == "TNotebook":
            w.master.select(w)
        w = w.master
    entry.update()
    entry.event_generate("<FocusOut>")
    entry.update()


class Settings:
    """The General section of the Settings tab, with saving and restarting recorded."""

    def __init__(self, app, errors, dialogs):
        from primeatlas.core import widgets
        self.app = app
        self.tab = app.settings_tab
        self.widgets = widgets
        self.errors = errors
        self.dialogs = dialogs
        self.saves = []
        self.restarts = []
        self.tab.app_settings.save = lambda: self.saves.append(1)
        self.tab._restart_now_or_warn = lambda notice_translator: self.restarts.append(1)
        self.readability = (self.tab.background_brightness_var, self.tab.text_brightness_var,
                            self.tab.font_scale_var)

    def reset_log(self):
        """Clears the logs, after any field still holding focus has been left (its FocusOut
        applies a valid width)."""
        self.app.focus_force()
        self.app.update()
        self.errors.clear()
        self.dialogs.clear()
        self.saves.clear()
        self.restarts.clear()

    def state(self):
        """What a refused action must leave unchanged."""
        s = self.tab.app_settings
        return (s.scroll_pad_width, self.widgets.SCROLL_PAD_WIDTH,
                s.theme_brightness(s.theme), s.font_scale)

    def texts(self):
        return (self.tab.scroll_pad_width_var.get(),) + tuple(v.get() for v in self.readability)

    def set_valid(self, width="40", background="0", text="0", font="100"):
        self.tab.scroll_pad_width_var.set(width)
        for var, value in zip(self.readability, (background, text, font)):
            var.set(value)
        self.app.update()


def harness_cases(h, s):
    tab = s.tab
    width = [tab.scroll_pad_width_var]
    readability = list(s.readability)
    passed = True
    for name, action, fields, foreign in (
            ("Apply", tab._on_readability_apply, readability, width),
            ("width Enter", _enter(tab.scroll_pad_width_spin), width, readability),
            ("width spin command", tab._on_scroll_pad_width_changed, width, readability)):
        s.set_valid()
        passed &= h.case(name, action, fields, foreign)
    return passed


def refusal_cases(s):
    tab = s.tab
    T = tab.T
    refusal = T("number_field.fix_field", reason="").split("\n")[0]
    passed = True

    def refused(label, action, texts):
        s.reset_log()
        before = s.state()
        action()
        s.app.update()
        ok = (len(s.errors) == 1 and refusal in s.errors[0] and not s.dialogs
              and not s.saves and not s.restarts and s.state() == before
              and s.texts() == texts)
        return check(ok, f"{label}: one error, nothing saved, nothing restarted, the text "
                         f"kept ({s.errors[:2]} {s.dialogs[:1]} saves {len(s.saves)} "
                         f"restarts {len(s.restarts)} texts {s.texts()} want {texts})")

    for value in ("5", "161", "abc"):
        s.set_valid(width=value)
        passed &= refused(f"width {value!r} + Enter", _enter(tab.scroll_pad_width_spin),
                          s.texts())
        s.set_valid(width=value)
        passed &= refused(f"width {value!r} + spin command", tab._on_scroll_pad_width_changed,
                          s.texts())
    for index, value in ((0, "999"), (1, "-999"), (2, "5"), (2, "huge")):
        values = ["0", "0", "100"]
        values[index] = value
        s.set_valid("40", *values)
        passed &= refused(f"Apply with {value!r} in field {index + 1}", tab._on_readability_apply,
                          s.texts())

    for value in ("5", "abc"):
        s.set_valid(width=value)
        s.reset_log()
        before = s.state()
        _leave(tab.scroll_pad_width_spin)
        passed &= check(not s.errors and not s.dialogs and not s.saves
                        and s.state() == before and tab.scroll_pad_width_var.get() == value,
                        f"leaving the width field with {value!r}: no dialog, nothing saved, "
                        f"the text kept ({s.errors[:1]} saves {len(s.saves)} "
                        f"text {tab.scroll_pad_width_var.get()!r})")

    s.set_valid(width="72")
    s.reset_log()
    _leave(tab.scroll_pad_width_spin)
    passed &= check(not s.errors and s.saves and tab.app_settings.scroll_pad_width == 72
                    and s.widgets.SCROLL_PAD_WIDTH == 72,
                    "leaving the width field with 72 applies it as before")
    s.set_valid(width="64")
    s.reset_log()
    _enter(tab.scroll_pad_width_spin)()
    s.app.update()
    passed &= check(not s.errors and tab.app_settings.scroll_pad_width == 64
                    and s.widgets.SCROLL_PAD_WIDTH == 64,
                    "Enter with 64 applies it as before")
    s.set_valid(width="64")
    s.reset_log()
    tab.scroll_pad_width_spin.event_generate("<<Increment>>")
    s.app.update()
    passed &= check(not s.errors and tab.app_settings.scroll_pad_width == 68
                    and tab.scroll_pad_width_var.get() == "68",
                    f"the up arrow from 64 applies 68 "
                    f"(saved {tab.scroll_pad_width_var.get()!r})")

    for label, action in (("Enter", _enter(tab.scroll_pad_width_spin)),
                          ("leaving", lambda: _leave(tab.scroll_pad_width_spin))):
        s.reset_log()
        s.set_valid(width="")
        saved = tab.app_settings.scroll_pad_width
        action()
        s.app.update()
        passed &= check(not s.errors and not s.dialogs and not s.saves
                        and tab.scroll_pad_width_var.get() == str(saved),
                        f"an empty width field + {label} goes back to the saved {saved} "
                        f"(text {tab.scroll_pad_width_var.get()!r})")

    s.set_valid("40", "10", "-10", "120")
    tab._on_readability_apply()
    s.set_valid("40", "", "-10", "130")
    s.reset_log()
    tab._on_readability_apply()
    passed &= check(not s.errors and not s.saves and not s.restarts
                    and s.texts()[1:] == ("10", "-10", "120"),
                    f"Apply with an empty field puts the saved values back, saves nothing "
                    f"({s.texts()[1:]})")

    s.set_valid("40", "999", "abc", "5")
    s.reset_log()
    tab._on_readability_reset()
    settings = tab.app_settings
    passed &= check(not s.errors and settings.theme_brightness(settings.theme) == (0, 0)
                    and settings.font_scale == 100 and s.restarts == [1]
                    and s.texts()[1:] == ("0", "0", "100"),
                    f"Reset over red fields saves the defaults and restarts "
                    f"({s.errors[:1]} restarts {len(s.restarts)} {s.texts()[1:]})")

    s.set_valid("5", "20", "0", "100")
    s.reset_log()
    tab._on_readability_apply()
    passed &= check(not s.errors and settings.theme_brightness(settings.theme) == (20, 0)
                    and tab.scroll_pad_width_var.get() == "5",
                    "a red width field does not block Apply")
    s.set_valid("80", "999", "0", "100")
    s.reset_log()
    _enter(tab.scroll_pad_width_spin)()
    s.app.update()
    passed &= check(not s.errors and settings.scroll_pad_width == 80,
                    "a red Apply field does not block the width")
    s.set_valid()
    return passed


def range_checks(s):
    from primeatlas.core.app_settings import SCROLL_PAD_WIDTH_MAX, SCROLL_PAD_WIDTH_MIN
    from primeatlas.core.theme import BRIGHTNESS_MAX, BRIGHTNESS_MIN, FONT_SCALE_MAX, FONT_SCALE_MIN
    tab = s.tab
    passed = True
    for label, entry, low, high in (
            ("width", tab.scroll_pad_width_spin, SCROLL_PAD_WIDTH_MIN, SCROLL_PAD_WIDTH_MAX),
            ("background brightness", tab.readability_spins[0], BRIGHTNESS_MIN, BRIGHTNESS_MAX),
            ("text brightness", tab.readability_spins[1], BRIGHTNESS_MIN, BRIGHTNESS_MAX),
            ("font size", tab.readability_spins[2], FONT_SCALE_MIN, FONT_SCALE_MAX)):
        field = entry.number_field

        def problem(text):
            entry.delete(0, "end")
            entry.insert(0, text)
            field.refresh(at_once=True)
            return field.problem
        old = entry.get()
        ok = (problem(str(low - 1)) == "range" and problem(str(low)) is None
              and problem(str(high)) is None and problem(str(high + 1)) == "range")
        problem(old)
        passed &= check(ok, f"{label}: range {low}..{high}")
    return passed


def main():
    import prime_atlas_v2
    from tkinter import messagebox
    errors, dialogs = [], []
    messagebox.showinfo = lambda title, text="", **k: dialogs.append(text)
    messagebox.showwarning = lambda title, text="", **k: dialogs.append(text)
    messagebox.showerror = lambda title, text="", **k: errors.append(text)
    messagebox.askyesno = lambda *a, **k: dialogs.append("askyesno") or False
    messagebox.askokcancel = lambda *a, **k: dialogs.append("askokcancel") or False
    portal = tempfile.mkdtemp(prefix="primeatlas_field_refusal_settings_")
    app = None
    passed = False
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        from primeatlas.generation import time_simulation_controls
        time_simulation_controls.estimate_free_ram_bytes = lambda **_k: FAKE_FREE_RAM
        app = prime_atlas_v2._build_gui()()
        app.update()
        passed = _wait_loaded(app)
        s = Settings(app, errors, dialogs)
        passed &= harness_cases(Harness(app, errors, dialogs), s)
        passed &= refusal_cases(s)
        passed &= range_checks(s)
    finally:
        if app is not None:
            try:
                from primeatlas.core.app_settings import SCROLL_PAD_WIDTH_DEFAULT
                from primeatlas.core.widgets import set_scroll_pad_width
                set_scroll_pad_width(SCROLL_PAD_WIDTH_DEFAULT)
                app.destroy()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(portal, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
