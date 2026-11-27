"""
test_research_irreducibility_tab.py -- tests for Research -> Irreducibility
(primeatlas/research/research_irreducibility_tab.py and its seven sub-tab views: Radices and
atoms, Comparison, Comb reading, Ranges, Arithmetic, Primality, Multiplicative counting). The
pure logic is tested in test_irreducibility_core.py and test_irreducibility_blocks.py; this
file exercises the tkinter wiring: what each sub-tab computes on opening, its buttons, input
errors, the numbers A and B shared by Comparison, Ranges, Arithmetic and Primality, the
repository links, remembered fields and both locales.

Builds the real app (same approach as test_research_pi_approx_tab.py), with the storage
folder and remembered fields isolated by app_sandbox.isolate_app().

Usage (Windows, real display):
    python unitTests\\test_research_irreducibility_tab.py
"""
import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

# Texts hold Λ, ⊕, − and thin spaces, which a cp1250 console cannot print.
sys.stdout.reconfigure(errors="backslashreplace")

failures = []
dialogs = []
"""Error dialogs shown (messagebox.showerror is patched in main)."""

REPO_URL = "https://github.com/Flaman55/Irreducibility"
PAPER_URL = REPO_URL + "/blob/main/Latex/irreducibility.pdf"


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _refusals():
    """How many error dialogs appeared since the last call."""
    n = len(dialogs)
    dialogs.clear()
    return n


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _set(entry, value):
    entry.delete(0, "end")
    entry.insert(0, value)


def _locale_keys(language):
    path = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales", f"strings_{language}.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k for k in data if k.startswith("research_irreducibility.")} | (
        {"tabs.research_irreducibility"} & set(data))


def _check_cases(app, v, T, count, name, kind_texts=None, detail_mark="m:"):
    """The test opened v.cases_window: one row per case, all marked ok, 'only errors' leaves
    none, a selected row shows its residues; a second run refreshes the same window; after
    closing it a run opens a new one."""
    w = getattr(v, "cases_window", None)
    check(w is not None and w.winfo_exists() and w.winfo_class() == "Toplevel",
          f"{name}: the test opens a window with its cases")
    if w is None:
        return
    rows = w.tree.get_children()
    check(len(rows) == count, f"{name}: one row per case ({len(rows)} of {count})")
    oks = {w.tree.set(r, "ok") for r in rows}
    check(oks == {"✓"}, f"{name}: every case marked ok ({oks})")
    check(str(count) in w.summary_var.get(), f"{name}: summary names the count")
    if kind_texts:
        kinds = {w.tree.set(r, "kind") for r in rows}
        check(kinds == set(kind_texts), f"{name}: every kind listed by its name ({kinds})")
    w.tree.selection_set(rows[1])
    app.update()
    check(detail_mark in w.detail.text(), f"{name}: a selected row shows its details")
    w.only_errors_var.set(True)
    w.refill()
    check(w.tree.get_children() == (), f"{name}: 'only errors' leaves no row")
    v.test_button.invoke()
    app.update()
    check(v.cases_window is w and len(w.tree.get_children()) == 0 and w.only_errors_var.get(),
          f"{name}: a second run refreshes the same window and keeps the filter")
    w.only_errors_var.set(False)
    w.refill()
    check(len(w.tree.get_children()) == count, f"{name}: filter off shows all again")
    w.destroy()
    app.update()
    v.test_button.invoke()
    app.update()
    check(v.cases_window is not w and v.cases_window.winfo_exists(),
          f"{name}: after closing, a run opens a new window")
    v.cases_window.destroy()


def test_radices(app, v, T):
    from primeatlas.research import irreducibility_residues as res
    check((v.from_entry.get(), v.to_entry.get()) == ("2", "60"), "range starts at 2..60")
    check(len(v.chips) == 59 and sum(r > 1 for _, r in v.chips) == 25,
          f"2..60: 59 moduli, 25 with radix > 1 (got {len(v.chips)})")
    check(len(v.canvas.find_withtag("chip")) == 59 and len(v.canvas.find_withtag("gold")) == 25,
          "the canvas shows 59 chips, 25 of them marked")
    check(dict(v.chips)[8] == 2 and dict(v.chips)[6] == 1 and dict(v.chips)[7] == 7,
          "radix of 8 is 2, of 6 is 1, of 7 is 7")
    s = v.summary_var.get()
    check("25" in s and "59" in s, f"summary names 25 of 59 ({s!r})")
    check(v.atoms_below == [] and [k for k, _, _ in v.atoms_inside] == res.interval_atoms(2, 60),
          "2..60: no atoms below 2, the atoms inside are intervalAtoms(2, 60)")

    _set(v.from_entry, "50")
    _set(v.to_entry, "200")
    v.run()
    atoms = res.interval_atoms(50, 200)
    check([k for k, _, _ in v.atoms_below] == [k for k in atoms if k < 50]
          and [k for k, _, _ in v.atoms_inside] == [k for k in atoms if k >= 50],
          "50..200: atoms split into below 50 and inside")
    check(all(a % k == 0 and b - a == k and 50 <= a and b <= 200
              for k, a, b in v.atoms_below + v.atoms_inside),
          "every atom k is read from a, b = a + k in the interval with k | a")
    check(len(v.below_canvas.find_withtag("atom")) + len(v.inside_canvas.find_withtag("atom"))
          == len(atoms), "atoms are drawn as chips")

    _set(v.from_entry, "2")
    _set(v.to_entry, "5000")
    v.run()
    check(v.to_entry.get() == "1001" and len(v.chips) == 1000
          and T("research_irreducibility.limit_note", max=1000) in v.summary_var.get(),
          "more than 1000 moduli: the range is cut to 1000 and the summary says so")
    _set(v.from_entry, "30")
    _set(v.to_entry, "10")
    v.run()
    check(v.to_entry.get() == "30" and len(v.chips) == 1, "to below from: one modulus")
    for bad in (("abc", "60"), ("2", ""), ("-5", "60")):
        _set(v.from_entry, bad[0])
        _set(v.to_entry, bad[1])
        v.run()
        check(v.message_var.get() != "" and v.chips == [] and not v.canvas.find_withtag("chip"),
              f"range {bad!r}: message, nothing drawn")
    _set(v.from_entry, "2")
    _set(v.to_entry, "60")
    v.run()
    check(v.message_var.get() == "" and len(v.chips) == 59, "a valid range clears the message")


def test_compare(app, tab, T):
    v = tab.compare_view
    check(tab.numbers.number_var("A").get() == "12345678"
          and tab.numbers.number_var("B").get() == "12345679", "A, B start at 12345678, 12345679")
    check(v.verdict_var.get() == "A < B" and v.oracle_ok is True,
          f"opening compares: A < B, the check agrees ({v.verdict_var.get()!r})")
    rows = [v.digits_tree.item(i) for i in v.digits_tree.get_children()]
    check(len(rows) == 11 and sum("decides" in r["tags"] for r in rows) == 1,
          "11 common moduli listed from the top, one row marks the deciding digit")
    check(len(v.sides["A"].dials.find_withtag("dial")) == 6
          and len(v.sides["B"].dials.find_withtag("dial")) == 5,
          "one dial per block modulus: A 3 + 3, B 2 + 3")

    _set(v.sides["A"].number_entry, "100000000000000000000")
    v.sides["A"].fit_button.invoke()
    app.update()
    lay = tab.numbers.layout("A")
    from primeatlas.research import irreducibility_layout as layout
    check(layout.capacity(*lay) > 10 ** 20, "Fit to number gives a layout whose W exceeds A")
    _set(v.sides["B"].number_entry, "99999999999999999999")
    v.sides["B"].fit_button.invoke()
    v.run_compare()
    check(v.verdict_var.get() == "A > B" and v.oracle_ok is True, "10^20 > 10^20 - 1")

    _set(v.sides["A"].number_entry, "abc")
    v.run_compare()
    check(v.message_var.get() != "" and v.verdict_var.get() == "", "A not a number: message")
    _set(v.sides["A"].number_entry, "10" + "0" * 40)
    v.run_compare()
    check(v.message_var.get() != "" and v.verdict_var.get() == "",
          "A above the capacity: message")
    _set(v.sides["A"].layout_entries["dz"], "0")
    v.run_compare()
    check(v.message_var.get() != "", "block size 0: message")
    _set(v.sides["A"].layout_entries["dz"], "3")
    _set(v.sides["A"].number_entry, "12345678")
    v.sides["A"].fit_button.invoke()

    v.random_button.invoke()
    app.update()
    a, b = int(v.sides["A"].number_entry.get()), int(v.sides["B"].number_entry.get())
    expected = "A = B" if a == b else "A < B"
    check(b - a in (0, 1) and v.verdict_var.get() == expected and v.oracle_ok is True,
          f"Random neighbours: B = A or A + 1, verdict {expected}")
    v.test_button.invoke()
    app.update()
    check("1000" in v.verdict_var.get() and v.oracle_ok is True, "Test 1000 pairs: 0 errors")
    _check_cases(app, v, T, 1000, "Comparison test")


def test_comb(app, v, T):
    check((v.a_entry.get(), v.b_entry.get(), v.scale_entry.get()) == ("17", "5", "8"),
          "comb fields start at a=17, b=5, scale 8")
    check("17 mod 5 = 2" in v.result_var.get(), f"17 on 5 reads 2 ({v.result_var.get()!r})")
    c = v.canvas
    check(all(c.find_withtag(t) for t in ("comb_a", "comb_b", "window", "a_mark")),
          "both combs, the window from the last peak of C_b to a, and the mark at a are drawn")
    _set(v.a_entry, "3")
    _set(v.b_entry, "7")
    v.draw()
    check("3 mod 7 = 3" in v.result_var.get(), "a < b reads a")
    _set(v.a_entry, "200")
    _set(v.b_entry, "13")
    _set(v.scale_entry, "2")
    v.draw()
    check(v.scale_entry.get() == "3" and T("research_irreducibility.comb_scale_raised")
          == v.message_var.get() and "200 mod 13 = 5" in v.result_var.get(),
          "scale below 3 is raised to 3 with a note")
    for a, b, s in (("1", "5", "8"), ("201", "5", "8"), ("17", "x", "8"), ("17", "5", "nan")):
        _set(v.a_entry, a)
        _set(v.b_entry, b)
        _set(v.scale_entry, s)
        v.draw()
        check(v.result_var.get() == "" and v.message_var.get() != ""
              and not c.find_withtag("comb_a"), f"comb input {(a, b, s)!r}: message, no plot")
    _set(v.a_entry, "17")
    _set(v.b_entry, "5")
    _set(v.scale_entry, "8")
    v.draw()


def test_ranges(app, tab, T):
    v = tab.ranges_view
    check(len(v.sweep_cells) == 6 * 7, "sweep grid: 6 parameters x 7 steps on opening")
    check("2,520" in v.ranges_var.get(), f"W(D) of blocks 2..10 is 2,520 ({v.ranges_var.get()!r})")
    _set(tab.compare_view.sides["B"].layout_entries["dc"], "2")
    _set(tab.compare_view.sides["B"].layout_entries["dz"], "4")
    v.from_b_button.invoke()
    check(all(v.param_entries[k].get() == tab.numbers.layout_var("B", k).get()
              for k in v.param_entries) and v.param_entries["dz"].get() == "4"
          and v.param_entries["dc"].get() == "2", "Take from B copies B's layout")
    _set(v.param_entries["dc"], "x")
    v.show()
    check(v.message_var.get() != "", "invalid parameter: message")
    _set(v.param_entries["dc"], "3")
    v.show()
    check(v.message_var.get() == "", "valid parameters clear the message")

    check(v.n_entry.get() == "1" + "0" * 24 and len(v.fit_tree.get_children()) == 5,
          "settings for 10^24: one row per block size 1..5")
    rows = v.fit_tree.get_children()
    v.fit_tree.selection_set(rows[2])
    v.use_b_button.invoke()
    app.update()
    from primeatlas.research import irreducibility_layout as layout
    check(tab.numbers.number_var("B").get() == "1" + "0" * 24
          and layout.capacity(*tab.numbers.layout("B")) > 10 ** 24
          and tab.compare_view.sides["B"].layout_entries["dz"].get() == "3",
          "Use for B sets B = n and the block size 3 layout")
    check(tab.sub_notebook.index("current") == 1, "Use for B shows the Comparison sub-tab")
    _set(v.n_entry, "-4")
    v.find()
    check(v.message_var.get() != "" and not v.fit_tree.get_children(), "n <= 0: message")
    _set(v.n_entry, "1" + "0" * 24)
    v.find()


def test_arith(app, tab, T):
    v = tab.arith_view
    nums = tab.numbers
    nums.number_var("A").set("12345678")
    nums.number_var("B").set("12345679")
    for side, (dz, dc, ks) in (("A", ("3", "3", "11")), ("B", ("4", "2", "13"))):
        nums.layout_var(side, "ds").set("2")
        nums.layout_var(side, "dz").set(dz)
        nums.layout_var(side, "dc").set(dc)
        nums.layout_var(side, "ks").set(ks)
        nums.layout_var(side, "kz").set("3")
        nums.layout_var(side, "kc").set("3")
    app.update()
    check(v.number_entries["A"].get() == "12345678"
          and tab.compare_view.sides["A"].number_entry.get() == "12345678",
          "A in Arithmetic and in Comparison is one field")
    ok_text = T("research_irreducibility.check_ok_text")
    for name, run in (("add", lambda: v.add_button.invoke()), ("sub", lambda: v.sub_button.invoke()),
                      ("mul", lambda: v.mul_button.invoke()), ("div", lambda: v.div_button.invoke()),
                      ("address", lambda: v.address_button.invoke()),
                      ("pow", lambda: v.pow_button.invoke())):
        run()
        app.update()
        text = v.output_text()
        check(ok_text in text and v.last_check is True, f"{name}: residues agree with the integer result")
    _set(v.t_entry, "37")
    v.address_button.invoke()
    check(v.last_check is None and T("research_irreducibility.address_needs_divisor").split("{")[0]
          in v.output_text(), "T not dividing W: message")
    _set(v.t_entry, "30")
    v.chapters_button.invoke()
    text = v.output_text()
    check("5^1" in text or "5^" in text, "chapters list the powers of p")
    v.test_button.invoke()
    app.update()
    check("450" in v.output_text() and v.last_check is True, "Test 450 operations: 0 errors")
    from primeatlas.research.irreducibility_selftest import OP_KINDS
    _check_cases(app, v, T, 450, "Arithmetic test",
                 [T(f"research_irreducibility.op_{k}") for k in OP_KINDS])
    nums.number_var("A").set("abc")
    before = v.output_text()
    v.add_button.invoke()
    check(_refusals() == 1 and v.output_text() == before,
          "A not a number: refused, the output kept")
    nums.number_var("A").set("12345678")


def _set_layout(nums, values):
    for key, value in zip(("ds", "dz", "dc", "ks", "kz", "kc"), values):
        nums.layout_var("A", key).set(str(value))


def _run_to_end(app, v, seconds=20):
    v.run_button.invoke()
    deadline = time.time() + seconds
    while v.is_running() and time.time() < deadline:
        app.update()
        time.sleep(0.005)


def test_primality(app, tab, T):
    import math
    from primeatlas.research import irreducibility_layout as layout
    from primeatlas.research.irreducibility_primality import HEAD_ROWS, TAIL_ROWS
    v = tab.primality_view
    nums = tab.numbers
    check(tab.sub_notebook.tab(tab.sub_notebook.tabs()[-2], "text")
          == T("research_irreducibility.tab_primality"), "Primality is the sixth sub-tab")
    check(v.verdict_var.get() == "" and not v.is_running(),
          "nothing runs on opening: the run waits for its button")
    nums.number_var("A").set("12345678")
    _set_layout(nums, (2, 3, 3, 11, 3, 3))
    app.update()
    check(v.number_entry.get() == "12345678"
          and tab.compare_view.sides["A"].number_entry.get() == "12345678",
          "A in Primality and in Comparison is one field")
    _set(v.fuel_entry, "1000000")
    _run_to_end(app, v)
    rows = v.steps_tree.get_children()
    check(v.answer is False and v.reason == "divisor" and v.steps == 1 and len(rows) == 1
          and v.steps_tree.item(rows[0], "values")[1] == "2",
          f"12345678: composite, 2 divides it, one step ({v.verdict_var.get()!r})")
    check("2" in v.verdict_var.get() and v.last_check is True,
          "the verdict names the divisor; the integer check agrees")

    p = 1000003
    nums.number_var("A").set(str(p))
    v.fit_button.invoke()
    app.update()
    w = layout.capacity(*nums.layout("A"))
    check(w > (math.isqrt(p) + 1) ** 2, f"Fit for primality: W > (isqrt(n) + 1)^2 (W = {w})")
    check(v.square_note_var.get() == "", "W large enough: no square-test note")
    _run_to_end(app, v)
    rows = v.steps_tree.get_children()
    vals = [v.steps_tree.item(r, "values") for r in rows]
    check(v.answer is True and v.reason == "square" and v.steps == math.isqrt(p)
          and v.last_check is True,
          f"1000003: prime, the square test stops at m = isqrt(n) + 1 ({v.steps} steps)")
    check(len(rows) == HEAD_ROWS + 1 + TAIL_ROWS and vals[0][1] == "2"
          and vals[HEAD_ROWS][0] == "…" and vals[-1][1] == str(math.isqrt(p) + 1)
          and vals[-1][3] == ">",
          f"table: first {HEAD_ROWS} steps, a gap row, last {TAIL_ROWS} steps ending m^2 > n")
    check(str(v.steps) in v.result_var.get(), "the step count is shown")

    for n, answer, reason in (("0", False, "below"), ("1", False, "below"), ("2", True, "equal"),
                              ("3", True, "square")):
        nums.number_var("A").set(n)
        _run_to_end(app, v)
        check(v.answer is answer and v.reason == reason and v.steps == 1
              and v.last_check is True, f"n = {n}: {reason}, one step, check agrees")

    nums.number_var("A").set("97")
    _set_layout(nums, (2, 1, 1, 49, 1, 1))
    app.update()
    check(layout.capacity(*nums.layout("A")) == 98 and v.square_note_var.get() != "",
          "W = 98 for 97: the square-test note is shown")
    _run_to_end(app, v)
    check(v.answer is True and v.last_check is True, "97 on W = 98: still prime, check agrees")

    nums.number_var("A").set(str(p))
    v.fit_button.invoke()
    _set(v.fuel_entry, "3")
    _run_to_end(app, v)
    check(v.answer is None and v.reason == "fuel" and v.steps == 3 and v.last_check is None
          and v.verdict_var.get() != "", "fuel 3: no answer after 3 steps, no agreement claimed")
    check(T("research_irreducibility.primality_check_prime").split("{")[0]
          in v.oracle_var.get(), "with no answer the integer result is still shown")

    big = 10 ** 12 + 39
    nums.number_var("A").set(str(big))
    v.fit_button.invoke()
    _set(v.fuel_entry, "1000000")
    v.run_button.invoke()
    _pump(app, 0.3)
    check(v.is_running() and v.progress_var.get() != "" and v.button_state() == "running",
          "a long run goes on in slices, with progress, Stop enabled")
    v.stop_button.invoke()
    app.update()
    done = v.steps
    _pump(app, 0.2)
    check(not v.is_running() and v.reason == "stopped" and 0 < done < 10 ** 6
          and v.steps == done and v.answer is None and v.button_state() == "idle",
          f"Stop ends the run: no answer, steps kept ({done}), nothing advances afterwards")

    v.run_button.invoke()
    _pump(app, 0.1)
    nums.number_var("A").set("12345678")
    v.run_button.invoke()
    _pump(app, 0.3)
    check(v.answer is False and v.steps == 1 and not v.is_running(),
          "Run during a run starts over on the new number; the old run does not continue")

    _refusals()
    # A red field of Primality is refused (one dialog, the view kept); a layout of A, read
    # from the Comparison tab, and values the field accepts get the view's message.
    for number, lay, fuel, name, refused in (
            ("abc", None, "100", "A not a number", True),
            ("12", (2, 1, 1, 0, 1, 1), "100", "invalid layout", False),
            ("12", None, "0", "fuel 0", True),
            ("12", None, "abc", "fuel not a number", True),
            ("12", None, str(10 ** 10), "fuel above the maximum", False),
            (str(10 ** 30), None, "100", "A >= W", False),
            ("1", (2, 1, 1, 2, 1, 1), "100", "W = 2", False)):
        nums.number_var("A").set(number)
        _set_layout(nums, lay or (2, 3, 3, 11, 3, 3))
        _set(v.fuel_entry, fuel)
        before = (v.message_var.get(), v.verdict_var.get(), v.steps_tree.get_children())
        v.run_button.invoke()
        app.update()
        if refused:
            after = (v.message_var.get(), v.verdict_var.get(), v.steps_tree.get_children())
            check(_refusals() == 1 and after == before and not v.is_running(),
                  f"{name}: refused, the view kept, no run")
            continue
        check(_refusals() == 0 and v.message_var.get() != "" and v.verdict_var.get() == ""
              and not v.is_running() and not v.steps_tree.get_children(),
              f"{name}: message, no run")
    _set_layout(nums, (2, 3, 3, 11, 3, 3))
    nums.number_var("A").set("12345678")
    _set(v.fuel_entry, "1000000")

    from primeatlas.research.irreducibility_primality_view import PRIMALITY_TEST_COUNT
    v.test_button.invoke()
    app.update()
    check(v.last_check is True and str(PRIMALITY_TEST_COUNT) in v.verdict_var.get(),
          f"Test {PRIMALITY_TEST_COUNT} numbers: 0 errors")
    _check_cases(app, v, T, PRIMALITY_TEST_COUNT, "Primality test")

    errors = []
    real_report = app.report_callback_exception
    app.report_callback_exception = lambda *a: errors.append(a)
    try:
        from primeatlas.research.irreducibility_primality_view import PrimalityView
        other = PrimalityView(tab.sub_notebook, app_translator(), v.palette, nums)
        nums.number_var("A").set(str(big))
        other.fit()
        other.run_button.invoke()
        _pump(app, 0.1)
        other.destroy()
        _pump(app, 0.3)
    finally:
        app.report_callback_exception = real_report
    check(errors == [], f"closing the view during a run raises nothing ({errors[:1]})")
    nums.number_var("A").set("12345678")
    _set_layout(nums, (2, 3, 3, 11, 3, 3))


def _mul(app, v, q, g, n):
    _set(v.q_entry, str(q))
    _set(v.g_entry, str(g))
    _set(v.n_entry, str(n))
    v.run_button.invoke()
    app.update()


def test_multiplicative(app, tab, T):
    from primeatlas.research import irreducibility_multiplicative as mult
    v = tab.mul_view
    check(tab.sub_notebook.tab(tab.sub_notebook.tabs()[-1], "text")
          == T("research_irreducibility.tab_multiplicative"),
          "Multiplicative counting is the last sub-tab")
    check(v.result is not None and v.verdict_var.get() != "",
          "the sub-tab computes its fields on opening")

    _mul(app, v, 23, "auto", 10)
    rows = [v.table.item(r, "values") for r in v.table.get_children()]
    check(v.g_used == 5 and v.auto_used and v.result["primitive"],
          "Auto on q = 23: g = 5, order 22 = q - 1")
    check("5" in v.generator_var.get() and "22" in v.generator_var.get(),
          "the generator line names g and its order")
    check(len(rows) == 23 and rows[0][:3] == ("0", "1", "0") and rows[1][:3] == ("1", "5", "1")
          and rows[22][:3] == ("22", "1", "0"),
          "table: t, g^t mod q, t mod (q - 1) for t = 0..22, back to 1 and 0 at t = 22")
    t = v.result["step"]
    check(rows[t][3] != "" and rows[0][3] != "" and rows[2][3] == "",
          "the mark column marks the returns to 1 and the step reaching N mod q")
    check(v.result["square"] is False and str(t) in v.verdict_var.get()
          and v.last_check is True,
          f"10 mod 23 is not a square: odd step {t}, Euler agrees")
    check(v.pairs_var.get() == T("research_irreducibility.mul_pairs_equal"),
          "a primitive root: equal at the same pairs of steps")
    check(v.canvas.find_withtag("comb") and len(v.canvas.find_withtag("returns")) == 3
          and v.canvas.find_withtag("step_mark"),
          "the comb of modulus 22 is drawn with the 3 returns to 1 over 0..44 and the step")
    check(T("research_irreducibility.mul_comb_same") in v.comb_var.get(),
          "comb peaks and returns to 1 at the same steps")

    _mul(app, v, 23, "auto", 13)
    check(v.result["square"] is True and v.last_check is True, "13 = 6^2 mod 23: a square")

    _mul(app, v, 23, 2, 13)
    check(v.result["order"] == 11 and v.result["square"] is None and v.last_check is None
          and str(v.result["pairs_break"][1]) in v.pairs_var.get(),
          "g = 2 (order 11): pairs break at step 11, no square claim, no agreement claimed")
    check(T("research_irreducibility.mul_comb_differ") in v.comb_var.get(),
          "g = 2: the returns to 1 are not the comb peaks")

    _mul(app, v, 21, "auto", 4)
    check(v.result["primitive"] is False and v.result["square"] is None
          and v.message_var.get() != "" and v.last_check is None,
          "q = 21 (not prime): Auto finds no g of order 20, a note, no square claim")
    _mul(app, v, 23, "auto", 46)
    check(v.result["r"] == 0 and v.result["square"] is None
          and v.verdict_var.get() == T("research_irreducibility.mul_verdict_divides", q=23, n=46),
          "q | N: N mod q = 0, no step")
    _mul(app, v, 2, "auto", 7)
    check(v.g_used == 1 and v.verdict_var.get() == T("research_irreducibility.mul_verdict_q2"),
          "q = 2: g = 1, no square question")
    _mul(app, v, 10, 2, 3)
    check(v.result["order"] is None and v.result["square"] is None,
          "g sharing a factor with q: no order, no claim")

    q = 1009
    _mul(app, v, q, "auto", 123456789)
    rows = [v.table.item(r, "values") for r in v.table.get_children()]
    gaps = sum(r[0] == "…" for r in rows)
    check(len(rows) < 40 and gaps >= 1 and rows[-1][:2] == (str(q - 1), "1"),
          f"q = {q}: head, the step and the tail rows with gap rows ({len(rows)} rows)")
    check(not v.canvas.find_withtag("comb") and not v.canvas.winfo_ismapped()
          and str(mult.COMB_MAX_Q) in v.comb_var.get(),
          f"q above {mult.COMB_MAX_Q}: no comb, its area hidden, a note says up to which q")
    _mul(app, v, mult.MAX_Q, "auto", 7)
    check(v.result is not None and v.message_var.get() != "",
          "q = MAX_Q (composite): computed, with the note")

    _refusals()
    # Below a field's minimum or not a number: refused, the view kept; values the field
    # accepts but the view does not: its message.
    for q, g, n, name, refused in (
            ("1", "auto", "5", "q = 1", True), ("abc", "auto", "5", "q not a number", True),
            (str(mult.MAX_Q + 1), "auto", "5", "q above MAX_Q", False),
            ("23", "0", "5", "g = 0", True), ("23", "23", "5", "g = q", False),
            ("23", "x", "5", "g not a number", True), ("23", "auto", "-1", "N < 0", True),
            ("23", "auto", "", "N empty", False)):
        before = (v.message_var.get(), v.verdict_var.get(), v.table.get_children())
        _mul(app, v, q, g, n)
        if refused:
            after = (v.message_var.get(), v.verdict_var.get(), v.table.get_children())
            check(_refusals() == 1 and after == before, f"{name}: refused, the view kept")
            continue
        check(_refusals() == 0 and v.message_var.get() != "" and v.result is None
              and v.verdict_var.get() == "" and not v.table.get_children()
              and not v.canvas.find_withtag("comb"), f"{name}: message, nothing computed")
    _mul(app, v, 23, "AUTO", 10)
    check(v.auto_used and v.g_used == 5, "auto in any case")

    from primeatlas.research.irreducibility_multiplicative_view import MUL_TEST_COUNT
    v.test_button.invoke()
    app.update()
    check(v.last_check is True and str(MUL_TEST_COUNT) in v.verdict_var.get(),
          f"Test {MUL_TEST_COUNT} cases: 0 errors")
    _check_cases(app, v, T, MUL_TEST_COUNT, "Multiplicative test", detail_mark="t:")
    _mul(app, v, 23, "auto", 10)


def app_translator():
    from primeatlas.app import app_dynamic as _dyn
    return _dyn.TRANSLATOR


def test_links(app, tab):
    import webbrowser
    opened = []
    real_open = webbrowser.open
    webbrowser.open = lambda url, *a, **k: opened.append(url)
    try:
        tab.repo_button.invoke()
        tab.paper_button.invoke()
    finally:
        webbrowser.open = real_open
    check(opened == [REPO_URL, PAPER_URL], f"the buttons open the repository and the paper "
                                           f"(got {opened!r})")


def test_remembered(app, tab, translator):
    from primeatlas.core import ui_state_dynamic
    from primeatlas.research.research_irreducibility_tab import ResearchIrreducibilityTab
    _set(tab.radices_view.to_entry, "90")
    _set(tab.comb_view.a_entry, "23")
    _set(tab.primality_view.fuel_entry, "4321")
    _set(tab.mul_view.q_entry, "31")
    _set(tab.mul_view.g_entry, "3")
    _set(tab.mul_view.n_entry, "77")
    tab.numbers.number_var("B").set("777")
    store = ui_state_dynamic.STORE
    check(store.get("research.irreducibility.range_to") == "90"
          and store.get("research.irreducibility.comb_a") == "23"
          and store.get("research.irreducibility.number_b") == "777"
          and store.get("research.irreducibility.primality_fuel") == "4321"
          and store.get("research.irreducibility.mul_q") == "31"
          and store.get("research.irreducibility.mul_g") == "3"
          and store.get("research.irreducibility.mul_n") == "77",
          "fields are remembered")
    second = ResearchIrreducibilityTab(app, translator=translator)
    app.update()
    check(second.radices_view.to_entry.get() == "90" and len(second.radices_view.chips) == 89
          and second.comb_view.a_entry.get() == "23"
          and second.numbers.number_var("B").get() == "777"
          and second.primality_view.fuel_entry.get() == "4321"
          and second.mul_view.q_entry.get() == "31" and second.mul_view.g_used == 3
          and second.mul_view.result["r"] == 77 % 31,
          "a new tab restores the fields and computes them")
    store.set("research.irreducibility.number_a", "abc")
    third = ResearchIrreducibilityTab(app, translator=translator)
    app.update()
    check(third.compare_view.message_var.get() != "", "a restored invalid A opens with a message")
    second.destroy()
    third.destroy()


def test_wiring_and_locales(app):
    from primeatlas.app import app_dynamic as _dyn
    from primeatlas.core.i18n import Translator
    sub = app.research_sub_notebook
    texts = [sub.tab(t, "text") for t in sub.tabs()]
    check(texts[-1] == _dyn.T("tabs.research_irreducibility"),
          f"Irreducibility is the last Research sub-tab (got {texts!r})")
    tab = app.research_irreducibility_tab_widget
    inner = [tab.sub_notebook.tab(t, "text") for t in tab.sub_notebook.tabs()]
    check(len(inner) == 7, f"seven sub-tabs ({inner!r})")
    en, pl = _locale_keys("en"), _locale_keys("pl")
    check(en == pl and "tabs.research_irreducibility" in en and len(en) > 40,
          f"en and pl hold the same Irreducibility keys (only en: {sorted(en - pl)}, "
          f"only pl: {sorted(pl - en)})")
    for lang in ("en", "pl"):
        tr = Translator(lang)
        missing = [k for k in en if tr(k) == k]
        check(not missing, f"{lang}: every key translates ({missing})")


def main():
    import tkinter.messagebox
    tkinter.messagebox.showerror = lambda *a, **k: dialogs.append(a)

    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    app.update()
    try:
        from primeatlas.app import app_dynamic as _dyn
        T = _dyn.T
        tab = app.research_irreducibility_tab_widget
        test_radices(app, tab.radices_view, T)
        test_compare(app, tab, T)
        test_comb(app, tab.comb_view, T)
        test_ranges(app, tab, T)
        test_arith(app, tab, T)
        test_primality(app, tab, T)
        test_multiplicative(app, tab, T)
        test_links(app, tab)
        test_remembered(app, tab, _dyn.TRANSLATOR)
        test_wiring_and_locales(app)
        check(dialogs == [], f"no error dialog besides the refusals checked (got {dialogs!r})")
    finally:
        app.destroy()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
