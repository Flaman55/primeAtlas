"""The threads field (primeatlas/core/threads_field.py, threads_choice.py, cpu_dynamic.py): one
control for every thread count of the app.

Rules checked:
  - cpu_dynamic holds the CPU count WSL reports; set_wsl_cpus() tells every listener on a
    change, a failed probe (None) keeps a known count, a destroyed field is no listener;
  - the list holds the field's words and the numbers 1..CPU count (1..CAP while the count is
    unknown), a later count rebuilds it;
  - a word shows what it stands for, "Max (8)", "Auto (6)"; the variable every reader and
    the remembered-fields store use holds the word alone; a word that stands for no number
    ("Auto" of a program that picks its own count) shows bare; picking a label from the list
    puts the word into the variable;
  - a number above the CPU count cannot be set: typed, picked or set by code it becomes the
    field's `over` word (Max), or the CPU count itself for a field without words; the count
    itself stays; with the count unknown nothing is changed;
  - a value already in the variable (a stored one) above the count becomes Max when the field
    is built, or when the count becomes known later; a lower one stays;
  - text that is no number and no word, or below 1, turns the field red; a label "Max (8)" is
    no problem;
  - two fields on one variable (copies of one panel) show the same value;
  - every field follows a later CPU count (the probe at a launch).
Windows, real display:
    python unitTests/test_threads_field.py
"""
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def type_text(root, field, text):
    field.delete(0, "end")
    field.insert(0, text)
    field.event_generate("<KeyRelease>")
    root.update()


def values(field):
    return [str(v) for v in field.cget("values")]


def choice_checks():
    from primeatlas.core import threads_choice as tc
    passed = True
    print("--- threads_choice ---")
    passed &= check(tc.label("Max", 8) == "Max (8)" and tc.label("Auto", None) == "Auto",
                    "a label names the count, or is the bare word when there is none")
    passed &= check(tc.word_of("Max (8)") == "Max" and tc.word_of(" Auto (12) ") == "Auto"
                    and tc.word_of("12") == "12" and tc.word_of("") == "",
                    "word_of() strips the count of a label and nothing else")
    passed &= check(tc.fit("9", 8, "Max") == "Max" and tc.fit("8", 8, "Max") == "8"
                    and tc.fit("9", 8, None) == "8" and tc.fit("1 000", 8, "Max") == "Max",
                    "fit(): above the count -> over (or the count), the count itself stays, "
                    "any notation")
    passed &= check(tc.fit("500", None, "Max") == "500" and tc.fit("Max", 8, "Max") == "Max"
                    and tc.fit("abc", 8, "Max") == "abc" and tc.fit("", 8, "Max") == "",
                    "fit(): unknown count, a word, text and empty stay as they are")
    passed &= check(tc.choices(["Max"], 4, lambda w: 4) == ["Max (4)", "1", "2", "3", "4"],
                    "choices(): labels then 1..count")
    unknown = tc.choices(["Auto", "Max"], None, lambda w: None)
    passed &= check(unknown[:3] == ["Auto", "Max", "1"] and unknown[-1] == str(tc.CAP)
                    and len(unknown) == 2 + tc.CAP, "choices() with the count unknown: 1..CAP")
    return passed


def dynamic_checks():
    from primeatlas.core import cpu_dynamic
    passed = True
    print("--- cpu_dynamic ---")
    seen = []
    cpu_dynamic.WSL_CPUS = None
    cpu_dynamic.add_listener(seen.append)
    cpu_dynamic.set_wsl_cpus(8)
    passed &= check(cpu_dynamic.WSL_CPUS == 8 and seen == [8], "a count reaches listeners")
    cpu_dynamic.set_wsl_cpus(8)
    passed &= check(seen == [8], "the same count again tells nobody")
    cpu_dynamic.set_wsl_cpus(None)
    passed &= check(cpu_dynamic.WSL_CPUS == 8 and seen == [8],
                    "a failed probe keeps the known count")
    cpu_dynamic.set_wsl_cpus(4)
    passed &= check(seen == [8, 4], "a new count reaches listeners")
    cpu_dynamic.remove_listener(seen.append)
    cpu_dynamic.set_wsl_cpus(6)
    passed &= check(seen == [8, 4], "a removed listener hears nothing")
    return passed


def field_checks(root, T):
    from primeatlas.core import cpu_dynamic, number_field
    from primeatlas.core.threads_field import ThreadsField
    passed = True
    print("--- ThreadsField ---")
    cpu_dynamic.WSL_CPUS = None
    var = tk.StringVar(root, value="Max")
    field = ThreadsField(root, T, var, words=("Max",), over="Max")
    field.pack()
    root.update()
    passed &= check(field.get() == "Max" and values(field)[:2] == ["Max", "1"]
                    and len(values(field)) == 1 + 256,
                    "count unknown: bare word, list 1..256")
    type_text(root, field, "200")
    passed &= check(var.get() == "200", "count unknown: a large number is not changed")

    cpu_dynamic.set_wsl_cpus(8)
    root.update()
    passed &= check(var.get() == "Max" and field.get() == "Max (8)",
                    "the count arrives: a number above it becomes Max, shown as Max (8)")
    passed &= check(values(field) == ["Max (8)"] + [str(n) for n in range(1, 9)],
                    "the list is Max (8), 1..8")
    type_text(root, field, "8")
    passed &= check(var.get() == "8" and field.get() == "8", "the count itself can be set")
    type_text(root, field, "9")
    passed &= check(var.get() == "Max" and field.get() == "Max (8)",
                    "typing one above the count gives Max")
    var.set("12")
    root.update()
    passed &= check(var.get() == "Max" and field.get() == "Max (8)",
                    "set by code above the count: Max")
    field.set("5")
    field.event_generate("<<Increment>>")
    root.update()
    passed &= check(var.get() == "6", "an arrow click reaches the variable")
    field.set("Max (8)")
    field.event_generate("<<Increment>>")
    root.update()
    passed &= check(var.get() == "1", "the arrow from the label goes on to 1")
    type_text(root, field, "Max (8)")
    passed &= check(var.get() == "Max" and str(field.cget("style")) != number_field.
                    INVALID_SPINBOX_STYLE, "the label itself: variable Max, not red")
    for bad in ("abc", "0", "1,5"):
        type_text(root, field, bad)
        field.number_field.refresh(at_once=True)
        root.update()
        passed &= check(str(field.cget("style")) == number_field.INVALID_SPINBOX_STYLE,
                        f"{bad!r} turns the field red")
    type_text(root, field, "4")
    field.number_field.refresh(at_once=True)
    root.update()
    passed &= check(str(field.cget("style")) != number_field.INVALID_SPINBOX_STYLE,
                    "a valid number clears the red")

    twin = ThreadsField(root, T, var, words=("Max",), over="Max")
    twin.pack()
    root.update()
    type_text(root, twin, "Max")
    passed &= check(field.get() == "Max (8)" and twin.get() == "Max (8)",
                    "two fields on one variable show the same")

    stored_high = tk.StringVar(root, value="24")
    stored_low = tk.StringVar(root, value="3")
    high = ThreadsField(root, T, stored_high, words=("Max",), over="Max")
    low = ThreadsField(root, T, stored_low, words=("Max",), over="Max")
    root.update()
    passed &= check(stored_high.get() == "Max" and stored_low.get() == "3",
                    "a stored value above the count loads as Max, a lower one stays")

    plain_var = tk.StringVar(root, value="8")
    plain = ThreadsField(root, T, plain_var)
    root.update()
    passed &= check(plain_var.get() == "8" and values(plain) == [str(n) for n in range(1, 9)],
                    "no words: the list is 1..count")
    type_text(root, plain, "20")
    passed &= check(plain_var.get() == "8", "no words: above the count gives the count")
    type_text(root, plain, "Max")
    plain.number_field.refresh(at_once=True)
    root.update()
    passed &= check(str(plain.cget("style")) == number_field.INVALID_SPINBOX_STYLE,
                    "no words: a word is red")

    workers = {"value": 6}
    auto_var = tk.StringVar(root, value="Auto")
    auto = ThreadsField(root, T, auto_var, words=("Auto", "Max"), over="Max",
                        resolve=lambda word: workers["value"] if word == "Auto" else None)
    root.update()
    passed &= check(auto.get() == "Auto (6)" and values(auto)[:2] == ["Auto (6)", "Max (8)"],
                    "resolve() names Auto's count; Max is the CPU count by default")
    workers["value"] = 3
    auto.refresh()
    root.update()
    passed &= check(auto.get() == "Auto (3)" and auto_var.get() == "Auto",
                    "refresh() follows a changed Auto")
    bare_var = tk.StringVar(root, value="Auto")
    bare = ThreadsField(root, T, bare_var, words=("Auto", "Max"), over="Max",
                        resolve=lambda word: None if word == "Auto" else cpu_dynamic.WSL_CPUS)
    root.update()
    passed &= check(bare.get() == "Auto" and values(bare)[:2] == ["Auto", "Max (8)"],
                    "a word that stands for no number shows bare")

    var.set("6")
    stored_low.set("4")
    plain_var.set("8")
    root.update()
    cpu_dynamic.set_wsl_cpus(4)
    root.update()
    passed &= check(var.get() == "Max" and field.get() == "Max (4)" and twin.get() == "Max (4)"
                    and stored_low.get() == "4" and plain_var.get() == "4"
                    and values(plain)[-1] == "4" and high.get() == "Max (4)",
                    "a later, lower count: every field follows (6 -> Max, 4 stays, 8 -> 4)")
    field.destroy()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc)
    cpu_dynamic.set_wsl_cpus(2)
    root.update()
    passed &= check(not errors and twin.get() == "Max (2)",
                    "a destroyed field is no listener; the others still follow")
    for widget in (twin, high, low, plain, auto, bare):
        widget.destroy()
    return passed


def main():
    from tkinter import ttk
    from primeatlas.core.i18n import Translator
    passed = choice_checks()
    passed &= dynamic_checks()
    root = tk.Tk()
    ttk.Style(root).theme_use("clam")
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(exc)
    try:
        passed &= field_checks(root, Translator("en"))
        passed &= check(not errors, f"no callback errors ({errors[:1]})")
    finally:
        root.destroy()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
