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
    not a usable value (invalid, ambiguous or out of range), so a run can refuse it;
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
        "help_fraction")


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
    field = nf.attach(entry, T)
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
    field = nf.attach(spin, T, minimum=1, maximum=lambda: cap[0])
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
                    and T("number_field.reason_range", low=1, high=10) in field.tip.text(),
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
    ffield = nf.attach(fentry, T, fraction=True)
    root.update()
    passed &= check(ffield.problem is None and ffield.reading.value == 1.5
                    and T("number_field.help_fraction") in ffield.tip.text(),
                    "a fraction field takes 1,5 and its tip says fractions are fine")
    fentry.destroy()
    wvar = tk.StringVar(root, value="Auto")
    wspin = ttk.Spinbox(root, values=("Auto", "1", "2"), textvariable=wvar)
    wspin.pack()
    wfield = nf.attach(wspin, T, words=("Auto",), minimum=1)
    root.update()
    passed &= check(wfield.problem is None, "a word is fine")
    wvar.set("0")
    root.update()
    passed &= check(wfield.problem == "range", "a number next to the word still has its range")
    wspin.destroy()
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
        late_field = nf.attach(late, T)
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
        passed &= check(not errors, f"no callback errors ({errors[:1]})")
    finally:
        root.destroy()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
