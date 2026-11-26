"""The number field (primeatlas/core/number_field.py): what a field shows while its text is read
by core.number_text.

Rules checked, for a field with a StringVar and for a bare entry:
  - a whole number or an empty field shows nothing and keeps the normal style, at once;
  - red and the popup wait SETTLE_MS after the last change (typing "1,000,000" passes
    through "1,000" and "10^25" through "10^": neither flashes) or show at once when the
    field is left;
  - invalid text turns the field red (INVALID_STYLE) and back when fixed, also when the text
    is set by code (StringVar.set), not typed;
  - ambiguous text opens a "Could be" popup under the field with one button per reading; a
    click writes that number's plain digits into the field and closes the popup; fixing the
    text by hand closes it too; leaving the field closes it and turns the field red (no
    value is taken), the hover tip then lists the readings, and coming back reopens it;
  - the hover tip on the field shows the accepted forms, plus the reason when the text is
    invalid; it waits TIP_DELAY_MS and sits below the field; while the popup is open it
    shows nothing;
  - a bare entry that gets a textvariable after attach (core.ui_state.remember restoring a
    saved value) follows that variable: a restored invalid value is red;
  - a Spinbox number field turns red with its own style (INVALID_SPINBOX_STYLE);
  - a range (minimum, maximum; a callable maximum follows a changing cap): outside it the
    field is red and the tip names the range; a fraction field takes "1,5"; words ("Auto")
    are fine;
  - problem_field(vars) names the first field bound to one of those variables whose text is
    not a usable value (invalid, ambiguous or out of range), so a run can refuse it; it also
    takes the fields' widgets (a bare entry has no variable) and reads the text they show now;
  - the tip starts with what the field is for (attach requires a purpose key), then its
    range in grouped digits in the app's notation (also in the range reason); the notation
    help shows only with no maximum or a maximum of at least 10^6, otherwise one short line of
    the power and scientific forms (a callable maximum is read when the tip shows), the fraction line only on a fraction field;
  - a field destroyed right after it was left (a closed dialog) leaves no error behind; every text exists in English and Polish.
Windows, real display:
    python unitTests/test_number_field.py
"""
import os
import sys
import tkinter as tk
from tkinter import ttk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

SETTLE = 0
KEYS = ("help", "could_be", "reason_not_whole", "reason_syntax", "reason_too_large",
        "reason_min", "reason_max", "reason_range", "reason_ambiguous", "fix_field",
        "help_fraction", "range_both", "range_min", "range_max", "help_short")
PURPOSE = "field_tip.primality_number"


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def type_text(root, entry, text, settle=True):
    entry.delete(0, "end")
    entry.insert(0, text)
    entry.event_generate("<KeyRelease>")
    root.update()
    if settle:
        wait(root, SETTLE + 80)


def wait(root, ms):
    root.after(ms)
    root.update()


def field_checks(root, T, nf, with_var):
    passed = True
    name = "StringVar field" if with_var else "bare entry"
    var = tk.StringVar(root) if with_var else None
    entry = ttk.Entry(root, textvariable=var) if with_var else ttk.Entry(root)
    entry.pack()
    field = nf.attach(entry, T, PURPOSE)
    entry.focus_force()
    root.update()
    normal = str(entry.cget("style"))

    type_text(root, entry, "10^25+3")
    passed &= check(str(entry.cget("style")) == normal and field.popup is None,
                    f"{name}: a whole number shows nothing")
    seen = []
    for step in ("1", "1,", "1,0", "1,00", "1,000", "1,000,", "1,000,0", "1,000,00",
                 "1,000,000", "10^", "10^2", "10^25"):
        type_text(root, entry, step, settle=False)
        seen.append((field.popup is not None, str(entry.cget("style")) == nf.INVALID_STYLE))
    wait(root, nf.SETTLE_MS + 80)
    passed &= check(not any(p or r for p, r in seen) and field.popup is None
                    and str(entry.cget("style")) == normal,
                    f"{name}: typing through '1,000' and '10^' flashes nothing ({seen})")
    type_text(root, entry, "1,5", settle=False)
    passed &= check(str(entry.cget("style")) == normal, f"{name}: red waits for a pause")
    wait(root, nf.SETTLE_MS + 80)
    passed &= check(str(entry.cget("style")) == nf.INVALID_STYLE, f"{name}: then shows")
    type_text(root, entry, "15", settle=False)
    passed &= check(str(entry.cget("style")) == normal, f"{name}: a fix clears red at once")
    type_text(root, entry, "1,5")
    passed &= check(str(entry.cget("style")) == nf.INVALID_STYLE and field.popup is None,
                    f"{name}: invalid text turns the field red")
    tip = field.tip.text()
    passed &= check(T("number_field.help") in tip and T("number_field.reason_not_whole") in tip,
                    f"{name}: the hover tip names the forms and the reason")
    type_text(root, entry, "")
    passed &= check(str(entry.cget("style")) == normal, f"{name}: an empty field is normal")
    if with_var:
        var.set("abc")
        wait(root, SETTLE + 80)
        passed &= check(str(entry.cget("style")) == nf.INVALID_STYLE,
                        f"{name}: text set by code is checked too")
        var.set("42")
        root.update()
        passed &= check(str(entry.cget("style")) == normal, f"{name}: and back to normal")

    type_text(root, entry, "3,000")
    popup = field.popup
    buttons = field.candidate_buttons
    passed &= check(popup is not None and str(entry.cget("style")) == normal
                    and sorted(b.cget("text") for b in buttons) == ["3", "3000"]
                    and T("number_field.could_be") in field.popup_title,
                    f"{name}: ambiguous text offers both readings")
    passed &= check(popup is not None
                    and popup.winfo_rooty() >= entry.winfo_rooty() + entry.winfo_height(),
                    f"{name}: the popup sits under the field")
    passed &= check(field.tip.text() == "", f"{name}: no hover tip while the popup is open")
    [b for b in buttons if b.cget("text") == "3"][0].invoke()
    root.update()
    passed &= check(entry.get() == "3" and field.popup is None,
                    f"{name}: a click writes the plain number and closes the popup")
    type_text(root, entry, "1.500e3")
    passed &= check(field.popup is not None, f"{name}: ambiguous again")
    type_text(root, entry, "1500000")
    passed &= check(field.popup is None, f"{name}: fixing the text by hand closes the popup")
    type_text(root, entry, "3.000")
    other = ttk.Entry(root)
    other.pack()
    other.focus_force()
    root.update()
    root.after(nf.FOCUS_OUT_GRACE_MS + 100)
    root.update()
    passed &= check(field.popup is None and str(entry.cget("style")) == nf.INVALID_STYLE,
                    f"{name}: leaving the field closes the popup and leaves it red")
    tip = field.tip.text()
    passed &= check(T("number_field.could_be") in tip and "3000" in tip,
                    f"{name}: the hover tip then lists the readings")
    entry.focus_force()
    root.update()
    passed &= check(field.popup is not None, f"{name}: coming back opens the popup again")
    type_text(root, entry, "1,5", settle=False)
    other.focus_force()
    root.update()
    wait(root, nf.FOCUS_OUT_GRACE_MS + 50)
    passed &= check(str(entry.cget("style")) == nf.INVALID_STYLE,
                    f"{name}: leaving before the pause shows red at once")
    passed &= check(field.tip._below and field.tip._delay_ms == nf.TIP_DELAY_MS,
                    f"{name}: the hover tip waits and sits below the field")
    type_text(root, entry, "3,000", settle=False)
    entry.focus_force()
    root.update()
    other.focus_force()
    root.update()
    entry.destroy()
    wait(root, max(nf.FOCUS_OUT_GRACE_MS, nf.SETTLE_MS) + 100)
    other.destroy()
    if with_var:
        var.set("1,5")
    root.update()
    return passed


def options_checks(root, T, nf):
    passed = True
    var = tk.StringVar(root, value="5")
    spin = ttk.Spinbox(root, from_=1, to=10, textvariable=var)
    spin.pack()
    cap = [10]
    field = nf.attach(spin, T, PURPOSE, minimum=1, maximum=lambda: cap[0])
    root.update()
    normal = str(spin.cget("style"))
    var.set("abc")
    wait(root, SETTLE + 80)
    passed &= check(str(spin.cget("style")) == nf.INVALID_SPINBOX_STYLE,
                    "a Spinbox turns red with its own style")
    var.set("1 0")
    wait(root, SETTLE + 80)
    passed &= check(str(spin.cget("style")) == normal and field.problem is None,
                    "in range (any notation): normal")
    var.set("11")
    wait(root, SETTLE + 80)
    passed &= check(str(spin.cget("style")) == nf.INVALID_SPINBOX_STYLE
                    and field.problem == "range"
                    and T("number_field.reason_range", low="1", high="10") in field.tip.text(),
                    f"above the maximum: red, the tip names the range ({field.problem})")
    cap[0] = 20
    field.refresh()
    wait(root, SETTLE + 80)
    passed &= check(field.problem is None, "a callable maximum follows a changed cap")
    var.set("0")
    wait(root, SETTLE + 80)
    passed &= check(field.problem == "range", "below the minimum: out of range")
    other = tk.StringVar(root, value="")
    passed &= check(nf.problem_field([other]) is None and nf.problem_field([var]) is field,
                    "problem_field names the field of the variable with a problem")
    var.set("3,000")
    root.update()
    passed &= check(nf.problem_field([var]) is field and field.problem == "ambiguous",
                    "problem_field: an ambiguous text is a problem at once (no pause)")
    var.set("")
    root.update()
    passed &= check(nf.problem_field([var]) is None, "an empty field is no problem")
    spin.destroy()

    fvar = tk.StringVar(root, value="1,5")
    fentry = ttk.Entry(root, textvariable=fvar)
    fentry.pack()
    ffield = nf.attach(fentry, T, PURPOSE, fraction=True)
    root.update()
    passed &= check(ffield.problem is None and ffield.reading.value == 1.5
                    and T("number_field.help_fraction") in ffield.tip.text(),
                    "a fraction field takes 1,5 and its tip says fractions are fine")
    fentry.destroy()
    wvar = tk.StringVar(root, value="Auto")
    wspin = ttk.Spinbox(root, values=("Auto", "1", "2"), textvariable=wvar)
    wspin.pack()
    wfield = nf.attach(wspin, T, PURPOSE, words=("Auto",), minimum=1)
    root.update()
    passed &= check(wfield.problem is None, "a word is fine")
    wvar.set("0")
    root.update()
    passed &= check(wfield.problem == "range", "a number next to the word still has its range")
    wspin.destroy()
    return passed


def widget_checks(root, T, nf):
    """problem_field / refuse_problem take the fields' widgets too (a bare entry has no
    variable) and read the text the widget shows now, also text set by code without an event."""
    from tkinter import messagebox
    passed = True
    bare = ttk.Entry(root)
    bare.pack()
    field = nf.attach(bare, T, PURPOSE, minimum=1)
    var = tk.StringVar(root, value="5")
    other = ttk.Entry(root, textvariable=var)
    other.pack()
    other_field = nf.attach(other, T, PURPOSE, minimum=1)
    root.update()
    bare.insert(0, "0")  # no event: the field has not refreshed yet
    passed &= check(nf.problem_field([bare]) is field and field.problem == "range",
                    "a widget: its current text below the minimum is a problem")
    passed &= check(nf.problem_field([other]) is None and nf.problem_field([var]) is None,
                    "another field's problem does not count (widget or variable)")
    passed &= check(nf.problem_field([var, bare]) is field,
                    "variables and widgets mix in one list")
    bare.delete(0, "end")
    bare.insert(0, "abc")
    passed &= check(nf.problem_field([bare]) is field and field.problem not in (None, "range"),
                    "a widget: invalid text set by code is a problem")
    bare.delete(0, "end")
    passed &= check(nf.problem_field([bare]) is None, "a widget: an empty field is no problem")
    bare.insert(0, "1")
    passed &= check(nf.problem_field([bare]) is None, "a widget: the minimum itself is fine")
    var.set("0")
    root.update()
    passed &= check(nf.problem_field([other]) is other_field,
                    "a widget with a variable: the variable's value is read")
    shown = []
    real = messagebox.showerror
    messagebox.showerror = lambda *a, **k: shown.append(a)
    try:
        refused = nf.refuse_problem([bare, other], T, "Title")
        passed &= check(refused and len(shown) == 1 and shown[0][0] == "Title"
                        and shown[0][1] == T("number_field.fix_field",
                                             reason=other_field.problem_text()),
                        f"refuse_problem with widgets: one error naming the reason ({shown})")
        var.set("2")
        root.update()
        del shown[:]
        passed &= check(not nf.refuse_problem([bare, other], T, "Title") and not shown,
                        "refuse_problem with usable widgets: no error, False")
        passed &= check(not nf.refuse_problem([ttk.Entry(root)], T, "Title") and not shown,
                        "a widget that is no number field is no problem")
    finally:
        messagebox.showerror = real
    bare.destroy()
    other.destroy()
    return passed


def _tip_of(root, nf, T, **options):
    entry = ttk.Entry(root)
    entry.pack()
    field = nf.attach(entry, T, PURPOSE, **options)
    root.update()
    text = field.tip.text()
    return entry, field, text


def purpose_checks(root, nf, translators):
    """The tip names what the field is for, its range (grouped digits, in the app's
    notation) and the notation help only where large numbers belong."""
    from primeatlas.core import number_format, number_format_dynamic
    passed = True
    try:
        nf.attach(ttk.Entry(root), translators["en"])
        passed &= check(False, "attach without a purpose is refused")
    except TypeError:
        passed &= check(True, "attach without a purpose is refused")
    saved_style = number_format_dynamic.STYLE
    try:
        for lang, style, big in (("en", number_format.COMMA_DOT, "100,000"),
                                 ("pl", number_format.SPACE_COMMA, "100\u00a0000")):
            T = translators[lang]
            number_format_dynamic.STYLE = style
            entry, field, tip = _tip_of(root, nf, T, minimum=1, maximum=100000)
            lines = tip.split("\n")
            passed &= check(lines[0] == T(PURPOSE), f"{lang}: the tip starts with the purpose")
            passed &= check(T("number_field.range_both", low="1", high=big) in tip,
                            f"{lang}: the range line groups digits ({lines[1:2]})")
            passed &= check(T("number_field.help") not in tip
                            and T("number_field.help_short") in tip,
                            f"{lang}: a maximum below 10^6: the short notation line only")
            entry.insert(0, "200000")
            field.refresh(at_once=True)
            passed &= check(T("number_field.reason_range", low="1", high=big)
                            in field.tip.text(), f"{lang}: the range reason groups digits")
            entry.destroy()
        T = translators["en"]
        number_format_dynamic.STYLE = number_format.COMMA_DOT
        cases = (
            ({}, None, True, "no range"),
            ({"minimum": 1}, T("number_field.range_min", low="1"), True, "a minimum only"),
            ({"maximum": 999999}, T("number_field.range_max", high="999,999"), False,
             "a maximum just below 10^6"),
            ({"minimum": 0, "maximum": 10 ** 6}, T("number_field.range_both", low="0",
                                                   high="1,000,000"), True, "a maximum of 10^6"),
            ({"minimum": 0.5, "maximum": 2.5, "fraction": True},
             T("number_field.range_both", low="0.5", high="2.5"), False, "fraction bounds"),
        )
        starts = tuple(T(f"number_field.{key}", low="\0", high="\0").split("\0")[0]
                       for key in ("range_both", "range_min", "range_max"))
        for options, line, help_shown, what in cases:
            entry, field, tip = _tip_of(root, nf, T, **options)
            ranges = [l for l in tip.split("\n") if l.startswith(starts)]
            passed &= check(ranges == ([line] if line else []),
                            f"{what}: range line {line!r} ({ranges})")
            passed &= check((T("number_field.help") in tip) == help_shown,
                            f"{what}: notation help {'shown' if help_shown else 'left out'}")
            passed &= check((T("number_field.help_short") in tip) != help_shown,
                            f"{what}: the short notation line only without the full help")
            passed &= check((T("number_field.help_fraction") in tip) == bool(
                options.get("fraction")), f"{what}: fraction line only on a fraction field")
            entry.destroy()
        cap = [500]
        entry, field, tip = _tip_of(root, nf, T, minimum=1, maximum=lambda: cap[0])
        cap[0] = 2 * 10 ** 6
        tip2 = field.tip.text()
        passed &= check(T("number_field.range_both", low="1", high="500") in tip
                        and T("number_field.help") not in tip
                        and T("number_field.range_both", low="1", high="2,000,000") in tip2
                        and T("number_field.help") in tip2,
                        "a callable maximum: the tip follows the changed cap")
        entry.destroy()
    finally:
        number_format_dynamic.STYLE = saved_style
    return passed


def main():
    global SETTLE
    from primeatlas.core import number_field as nf
    from primeatlas.core.i18n import Translator
    SETTLE = nf.SETTLE_MS
    passed = True
    for lang in ("en", "pl"):
        T = Translator(lang)
        for key in KEYS:
            text = T(f"number_field.{key}")
            passed &= check(text and not text.startswith("number_field."),
                            f"{lang}: text for {key}")
    root = tk.Tk()
    root.geometry("400x300+100+100")
    ttk.Style(root).theme_use("clam")
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc)
    try:
        T = Translator("en")
        passed &= field_checks(root, T, nf, with_var=True)
        passed &= field_checks(root, T, nf, with_var=False)
        late = ttk.Entry(root)
        late.pack()
        late_field = nf.attach(late, T, PURPOSE)
        late_var = tk.StringVar(root, value="1,5")
        late.configure(textvariable=late_var)
        root.update()
        passed &= check(str(late.cget("style")) == nf.INVALID_STYLE,
                        "a textvariable added after attach: its restored value is checked")
        late_var.set("12")
        root.update()
        passed &= check(str(late.cget("style")) != nf.INVALID_STYLE
                        and late_field.reading.value == 12, "and its later values too")
        late.destroy()
        passed &= options_checks(root, T, nf)
        passed &= widget_checks(root, T, nf)
        passed &= purpose_checks(root, nf, {"en": T, "pl": Translator("pl")})
        passed &= check(not errors, f"no callback errors ({errors[:1]})")
    finally:
        root.destroy()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
