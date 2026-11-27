"""Every action of the real app that reads number fields refuses a red one first
(core/number_field.refuse_problem), with the fields it reads and no others.

Drives the app (temp storage, launches stubbed). For each action below:
  - the action asks refuse_problem about exactly the number fields it reads (a field read
    only in one case, e.g. Exploration's Width with more than one iteration or Verify's
    workers with Threads Auto, only in that case); a refusal stops it before anything else:
    no other dialog, no process, no thread;
  - with the first of those fields holding invalid text, the real refusal shows one error
    naming the reason and nothing else happens;
  - with a red field that the action does not read, the action asks only about its own fields.
Generation: the pipeline form's Run, the direct orchestrator launch, Verify Run, the k-tuple
Run, Auto and n_locations Auto, the constellation Run, Quick-gen's Auto buttons (Floor, Range,
Exploration with one and with three iterations, primesieve and cudasieve From).
Research: the Gaps, Squares, Polynomials, pi(x) and Goldbach Runs, Goldbach Visualize (before
and after its window exists), the Goldbach window's Check, row Previous/Next/Go, old base Go,
decompose and the decomposition list's Go. A refusal changes no page and opens no window.
Irreducibility: every button and Enter that reads number fields (Build, Compare, random pair,
Fit, Draw, Show, take from A/B, Find, the Arithmetic operations, Primality Run and Fit,
Multiplicative Run); Enter asks like its button, a refusal keeps what the view shows, and the
computation the tab runs when it is built asks nothing.
The minimum of each field is the lower bound its action checks: the pipeline form's floor 0
and its other numbers 1; the k-tuple step, window and MR rounds 1 (0 hangs the sieve or
confirms every candidate), its other numbers 0; Gaps and Squares 1, Polynomials 0, pi(x)
from/to 2 and step 1, Goldbach n and window "to" 2, window "from" and decompose 4, every Go 1;
Irreducibility: the numbers A, B and N 0, layout starts 2 and sizes and counts 1 (Comparison
and Ranges), radices from/to 1, comb a/b 2, Ranges n 1, Arithmetic b 1, T 2, e 1, p 2, n 1,
Primality fuel 1, Multiplicative q 2 and g 1.
Windows, real display:
    python unitTests/test_field_refusal_app.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_time_simulation import FAKE_FREE_RAM, check  # noqa: E402


class Launched(Exception):
    """An action got past its refusal and started a process or a thread."""


def _fields_of(items):
    """The NumberFields behind `items` (variables or widgets)."""
    from primeatlas.core import number_field as nf
    found = set()
    for item in items:
        if hasattr(item, "winfo_class"):
            field = getattr(item, "number_field", None)
            if field is not None:
                found.add(field)
            continue
        name = str(item)
        for field in list(nf._FIELDS):
            if name in {field.variable_name, str(getattr(field.entry, "variable", ""))}:
                found.add(field)
    return found


def _set_text(item, text):
    """Writes `text` into a variable or a widget (a disabled one too, left disabled);
    returns the previous text."""
    if hasattr(item, "winfo_class"):
        old = item.get()
        state = str(item.cget("state"))
        item.configure(state="normal")
        item.delete(0, "end")
        item.insert(0, text)
        item.configure(state=state)
        return old
    old = item.get()
    item.set(text)
    return old


class Harness:
    def __init__(self, app, errors, dialogs):
        self.app = app
        self.errors = errors
        self.dialogs = dialogs

    def _guarded(self, action):
        """Runs `action` with processes and threads forbidden; True when it tried one."""
        real_popen, real_start = subprocess.Popen, threading.Thread.start

        def forbid(*_a, **_k):
            raise Launched()
        subprocess.Popen = forbid
        threading.Thread.start = forbid
        try:
            action()
        except Launched:
            return True
        finally:
            subprocess.Popen, threading.Thread.start = real_popen, real_start
        return False

    def asked(self, action):
        """The fields `action` asks refuse_problem about (refusing them), the other dialogs
        shown and whether it launched anything."""
        from primeatlas.core import number_field as nf
        calls = []
        real = nf.refuse_problem

        def record(items, _T, _title):
            calls.append(list(items))
            return True
        nf.refuse_problem = record
        self.errors.clear()
        self.dialogs.clear()
        try:
            launched = self._guarded(action)
        finally:
            nf.refuse_problem = real
        self.app.update()
        return calls, list(self.errors) + list(self.dialogs), launched

    def case(self, name, action, expected, foreign=()):
        """Checks one action against the fields it should ask about."""
        T = self.app.generation_tab_widget.T
        passed = True
        self.app.update()
        calls, shown, launched = self.asked(action)
        got = _fields_of(calls[0]) if calls else set()
        want = _fields_of(expected)
        passed &= check(len(calls) == 1 and got == want and not shown and not launched,
                        f"{name}: asks about its {len(want)} fields first, then stops "
                        f"(calls {len(calls)}, got {len(got)}, missing "
                        f"{sorted(f.purpose for f in want - got)}, extra "
                        f"{sorted(f.purpose for f in got - want)}, shown {shown[:1]}, "
                        f"launched {launched})")
        first = expected[0]
        old = _set_text(first, "abc")
        self.app.update()
        self.errors.clear()
        self.dialogs.clear()
        launched = self._guarded(action)
        self.app.update()
        refusal = T("number_field.fix_field", reason="").split("\n")[0]
        passed &= check(len(self.errors) == 1 and refusal in self.errors[0] and not self.dialogs
                        and not launched,
                        f"{name}: its first field 'abc' is refused, nothing else "
                        f"({self.errors[:2]} {self.dialogs[:1]} launched {launched})")
        _set_text(first, old)
        for item in foreign:
            old = _set_text(item, "abc")
            self.app.update()
            calls, _shown, _launched = self.asked(action)
            got = _fields_of(calls[0]) if calls else set()
            passed &= check(got == want, f"{name}: a red field it does not read is not asked about")
            _set_text(item, old)
        self.app.update()
        return passed


def generation_cases(h, gen):
    from primeatlas.generation import engine_options
    passed = True
    knobs = gen._engine_fields

    def knob_vars():
        return [knobs.knob_vars[key] for key in engine_options.engine_knob_keys(knobs.engine())
                if key not in engine_options.CHECKBOX_KNOBS]

    loop = gen._loop_vars
    loop_keys = ("base_exponent", "run_count", "n_instances", "window_count_per_run",
                 "workers", "batches_per_worker", "window_m")
    for engine in ("v4.1", "v7", "pt1"):
        knobs.engine_var.set(engine)
        h.app.update()
        passed &= h.case(f"pipeline Run ({engine})", gen._on_run_loop,
                         [loop[k] for k in loop_keys] + knob_vars(),
                         foreign=[gen._ktuple_vars["window_m"]])
    knobs.engine_var.set("v7")
    h.app.update()
    passed &= h.case("direct orchestrator launch",
                     lambda: gen._on_run_orchestrator_direct(30, 0, 1),
                     [loop["workers"], loop["batches_per_worker"]] + knob_vars(),
                     foreign=[loop["run_count"]])

    verify = gen._verify_vars
    for threads, extra in (("3", []), ("Auto", [loop["workers"]])):
        verify["threads"].set(threads)
        h.app.update()
        passed &= h.case(f"Verify Run (Threads {threads})", gen._on_run_verify,
                         [verify["base_exponent"], verify["width"], verify["max_windows"],
                          verify["threads"]] + extra,
                         foreign=[gen._ktuple_vars["step"]])
    verify["threads"].set("Auto")

    ktuple = [gen._ktuple_vars[k] for k in (
        "base_exponent", "n_locations", "window_m", "step", "fragment_width", "fragment_start",
        "deep_prime_limit", "mr_rounds", "pass_counter")]
    passed &= h.case("k-tuple Run", lambda: gen._launch_ktuple(auto=False), ktuple,
                     foreign=[loop["window_m"]])
    passed &= h.case("k-tuple Auto", lambda: gen._launch_ktuple(auto=True), ktuple)
    passed &= h.case("k-tuple n_locations Auto", gen._on_ktuple_n_locations_auto_clicked,
                     [gen._ktuple_vars["base_exponent"], gen._ktuple_vars["window_m"]],
                     foreign=[gen._ktuple_vars["step"]])
    passed &= h.case("constellation Run", gen._on_run_constellation,
                     [gen._const_base_exponent_var], foreign=[loop["base_exponent"]])

    passed &= h.case("Quick-gen Floor Auto",
                     lambda: gen._on_quick_auto_width_clicked(
                         gen.quick_floor_width_var, None, floor_var=gen.quick_floor_var),
                     [gen.quick_floor_var] + knob_vars(), foreign=[gen.quick_floor_width_var])
    passed &= h.case("Quick-gen Range Auto",
                     lambda: gen._on_quick_auto_width_clicked(None, None,
                                                              floor_var=gen.quick_from_var),
                     [gen.quick_from_var] + knob_vars(), foreign=[gen.quick_to_var])
    for iterations, extra in (("1", []), ("3", [gen.quick_explore_width_var])):
        gen.quick_iterations_var.set(iterations)
        h.app.update()
        passed &= h.case(
            f"Quick-gen Exploration Auto ({iterations} iterations)",
            lambda: gen._on_quick_auto_width_clicked(
                gen.quick_explore_width_var, None, gen.quick_iterations_var,
                floor_var=gen.quick_explore_floor_var),
            [gen.quick_explore_floor_var, gen.quick_iterations_var] + extra + knob_vars())
    gen.quick_iterations_var.set("1")
    passed &= h.case("Quick-gen primesieve From Auto", gen._on_primesieve_auto_from_clicked,
                     [gen.quick_primesieve_floor_var], foreign=[gen.quick_primesieve_width_var])
    passed &= h.case("Quick-gen cudasieve From Auto", gen._on_cudasieve_auto_from_clicked,
                     [gen.quick_cudasieve_floor_var], foreign=[gen.quick_cudasieve_width_var])
    return passed


def minimum_checks(gen):
    """Each field's minimum: below it red, at it fine."""
    passed = True
    lows = {("loop", "base_exponent"): 0}
    for key in ("run_count", "n_instances", "window_count_per_run", "batches_per_worker",
                "window_m"):
        lows[("loop", key)] = 1
    for key in ("base_exponent", "n_locations", "fragment_width", "fragment_start",
                "deep_prime_limit", "pass_counter"):
        lows[("ktuple", key)] = 0
    for key in ("window_m", "step", "mr_rounds"):
        lows[("ktuple", key)] = 1
    for (section, key), low in lows.items():
        var = (gen._loop_vars if section == "loop" else gen._ktuple_vars)[key]
        fields = _fields_of([var])
        old = var.get()
        var.set(str(low - 1))
        below = all(f.problem == "range" for f in fields)
        var.set(str(low))
        at = all(f.problem is None for f in fields)
        var.set(old)
        passed &= check(fields and below and at, f"{section} {key}: minimum {low}")
    return passed


def research_cases(h, app):
    passed = True
    gaps = app.research_gaps_tab_widget
    squares = app.research_squares_tab_widget
    poly = app.research_polynomials_tab_widget
    pi = app.research_pi_approx_tab_widget
    gold = app.research_goldbach_tab_widget
    passed &= h.case("Gaps Run", gaps._on_gaps_run,
                     [gaps.gaps_n_from_entry, gaps.gaps_n_to_entry],
                     foreign=[squares.squares_n_from_entry])
    passed &= h.case("Squares Run", squares._on_squares_run,
                     [squares.squares_required_count_entry, squares.squares_n_from_entry,
                      squares.squares_n_to_entry], foreign=[gaps.gaps_n_to_entry])
    passed &= h.case("Polynomials Run", poly._on_poly_run,
                     [poly.poly_n_from_entry, poly.poly_n_to_entry],
                     foreign=[pi.pi_step_entry])
    passed &= h.case("pi(x) Run", pi._on_pi_run,
                     [pi.pi_x_from_entry, pi.pi_x_to_entry, pi.pi_step_entry],
                     foreign=[poly.poly_n_to_entry])
    passed &= h.case("Goldbach Run", gold._on_goldbach_run, [gold.goldbach_n_entry],
                     foreign=[gaps.gaps_n_from_entry])
    passed &= h.case("Goldbach Visualize (no window yet)", gold._on_goldbach_visualize,
                     [gold.goldbach_n_entry])
    passed &= check(gold._goldbach_viz_win is None,
                    "Goldbach Visualize: a refusal opens no window")

    gold._goldbach_ensure_viz_window()
    h.app.update()
    od, do = gold.goldbach_viz_range_from_entry, gold.goldbach_viz_n_entry
    passed &= h.case("Goldbach Visualize (window open)", gold._on_goldbach_visualize,
                     [gold.goldbach_n_entry, od], foreign=[gold.goldbach_viz_decompose_entry])
    passed &= h.case("Goldbach window Check", gold._on_goldbach_viz_refresh, [do, od],
                     foreign=[gold.goldbach_n_entry])
    gold._goldbach_viz_current_n = 1000
    gold._goldbach_viz_row_page = 1
    passed &= h.case("Goldbach rows Previous", gold._on_goldbach_viz_row_prev, [od],
                     foreign=[do])
    passed &= check(gold._goldbach_viz_row_page == 1,
                    "Goldbach rows Previous: a refusal keeps the page")
    passed &= h.case("Goldbach rows Next", gold._on_goldbach_viz_row_next, [od])
    passed &= check(gold._goldbach_viz_row_page == 1,
                    "Goldbach rows Next: a refusal keeps the page")
    passed &= h.case("Goldbach rows Go", gold._on_goldbach_viz_row_goto,
                     [gold.goldbach_viz_row_goto_entry, od],
                     foreign=[gold.goldbach_viz_chip_goto_entry])
    passed &= h.case("Goldbach old base Go", gold._on_goldbach_viz_chip_goto,
                     [gold.goldbach_viz_chip_goto_entry], foreign=[od])
    gold._goldbach_viz_last_result = {"pmax": 997}
    passed &= h.case("Goldbach decompose", gold._on_goldbach_viz_decompose,
                     [gold.goldbach_viz_decompose_entry], foreign=[od])
    gold._goldbach_viz_last_result = None
    gold._goldbach_viz_current_n = None
    gold._goldbach_viz_row_page = 0

    gold._goldbach_ensure_decompose_window()
    h.app.update()
    gold._goldbach_decompose_current_n = 1012
    gold._goldbach_decompose_current_pmax = 997
    passed &= h.case("Goldbach decomposition list Go", gold._on_goldbach_decompose_goto,
                     [gold.goldbach_decompose_goto_entry], foreign=[od])
    gold._goldbach_decompose_current_n = None
    return passed


def research_minimum_checks(app):
    """Each Research field's minimum: below it red, at it fine."""
    gaps = app.research_gaps_tab_widget
    squares = app.research_squares_tab_widget
    poly = app.research_polynomials_tab_widget
    pi = app.research_pi_approx_tab_widget
    gold = app.research_goldbach_tab_widget
    lows = [("gaps from", gaps.gaps_n_from_entry, 1), ("gaps to", gaps.gaps_n_to_entry, 1),
            ("squares required", squares.squares_required_count_entry, 1),
            ("squares from", squares.squares_n_from_entry, 1),
            ("squares to", squares.squares_n_to_entry, 1),
            ("polynomials from", poly.poly_n_from_entry, 0),
            ("polynomials to", poly.poly_n_to_entry, 0),
            ("pi from", pi.pi_x_from_entry, 2), ("pi to", pi.pi_x_to_entry, 2),
            ("pi step", pi.pi_step_entry, 1), ("Goldbach n", gold.goldbach_n_entry, 2),
            ("Goldbach window from", gold.goldbach_viz_range_from_entry, 4),
            ("Goldbach window to", gold.goldbach_viz_n_entry, 2),
            ("Goldbach decompose", gold.goldbach_viz_decompose_entry, 4),
            ("Goldbach rows Go", gold.goldbach_viz_row_goto_entry, 1),
            ("Goldbach old base Go", gold.goldbach_viz_chip_goto_entry, 1),
            ("Goldbach decomposition list Go", gold.goldbach_decompose_goto_entry, 1)]
    def problem(entry, text):
        _set_text(entry, text)
        entry.number_field.refresh(at_once=True)
        return entry.number_field.problem

    passed = True
    for label, entry, low in lows:
        old = entry.get()
        below = problem(entry, str(low - 1)) == "range"
        at = problem(entry, str(low)) is None
        problem(entry, old)
        passed &= check(below and at, f"{label}: minimum {low}")
    return passed


def _enter(entry):
    """Enter in `entry`, with every notebook page holding it shown (a hidden page gets no
    key events)."""
    def press():
        w = entry
        while w.master is not None:
            if w.master.winfo_class() == "TNotebook":
                w.master.select(w)
            w = w.master
        entry.update()
        entry.focus_force()
        entry.event_generate("<Return>")
    return press


def irreducibility_cases(h, app):
    """Every button and Enter of the Irreducibility sub-tabs that reads number fields; the
    computation the tab runs when it is built asks nothing."""
    tab = app.research_irreducibility_tab_widget
    rad, cmp_, comb = tab.radices_view, tab.compare_view, tab.comb_view
    rng, ar, pr, mul = tab.ranges_view, tab.arith_view, tab.primality_view, tab.mul_view
    sides = cmp_.sides
    keys = ("ds", "dz", "dc", "ks", "kz", "kc")
    layouts = [sides[s].layout_entries[k] for s in ("A", "B") for k in keys]
    numbers = [sides["A"].number_entry, sides["B"].number_entry]
    params = [rng.param_entries[k] for k in keys]
    nums = [ar.number_entries["A"], ar.number_entries["B"]]
    a_only = [ar.number_entries["A"]]
    passed = True
    actions = [
        ("Radices Build", rad.build_button.invoke, [rad.from_entry, rad.to_entry],
         [comb.a_entry]),
        ("Compare", cmp_.compare_button.invoke, numbers + layouts, [rng.param_entries["ds"]]),
        ("Compare random pair", cmp_.random_button.invoke, layouts, [rng.n_entry]),
        ("Compare Fit A", sides["A"].fit_button.invoke,
         [sides["A"].number_entry, sides["A"].layout_entries["dz"],
          sides["A"].layout_entries["kz"]], [sides["B"].number_entry]),
        ("Compare Fit B", sides["B"].fit_button.invoke,
         [sides["B"].number_entry, sides["B"].layout_entries["dz"],
          sides["B"].layout_entries["kz"]], [sides["A"].layout_entries["dz"]]),
        ("Comb Draw", comb.draw_button.invoke, [comb.a_entry, comb.b_entry, comb.scale_entry],
         [rad.from_entry]),
        ("Ranges Show", rng.show_button.invoke, params, [sides["A"].layout_entries["ds"]]),
        ("Ranges Find", rng.find_button.invoke, [rng.n_entry], [rng.param_entries["ds"]]),
        ("Arithmetic A+B", ar.add_button.invoke, nums, [ar.b_entry]),
        ("Arithmetic A-B", ar.sub_button.invoke, nums, [ar.t_entry]),
        ("Arithmetic A*B", ar.mul_button.invoke, nums, [ar.e_entry]),
        ("Arithmetic A/b", ar.div_button.invoke, a_only + [ar.b_entry],
         [ar.number_entries["B"], ar.t_entry]),
        ("Arithmetic address", ar.address_button.invoke, a_only + [ar.t_entry], [ar.b_entry]),
        ("Arithmetic power", ar.pow_button.invoke, a_only + [ar.e_entry], [ar.p_entry]),
        ("Arithmetic chapters", ar.chapters_button.invoke, a_only + [ar.p_entry, ar.n_entry],
         [ar.e_entry]),
        ("Arithmetic Fit A", ar.fit_buttons["A"].invoke, a_only, [ar.number_entries["B"]]),
        ("Arithmetic Fit B", ar.fit_buttons["B"].invoke, [ar.number_entries["B"]], [ar.b_entry]),
        ("Primality Run", pr.run_button.invoke, [pr.number_entry, pr.fuel_entry], [ar.b_entry]),
        ("Primality Fit", pr.fit_button.invoke, [pr.number_entry], [pr.fuel_entry]),
        ("Multiplicative Run", mul.run_button.invoke, [mul.q_entry, mul.g_entry, mul.n_entry],
         [comb.a_entry]),
    ]
    for name, action, fields, foreign in actions:
        passed &= h.case(name, action, fields, foreign=foreign)

    for side, button in (("A", rng.from_a_button), ("B", rng.from_b_button)):
        calls, shown, _launched = h.asked(button.invoke)
        got = _fields_of(calls[0]) if calls else set()
        passed &= check(len(calls) == 1 and got == _fields_of(params) and not shown,
                        f"Ranges take from {side}: asks about the copied fields")
        source = sides[side].layout_entries["kc"]
        old = _set_text(source, "abc")
        h.app.update()
        before = rng.ranges_var.get()
        h.errors.clear()
        button.invoke()
        h.app.update()
        passed &= check(len(h.errors) == 1 and rng.ranges_var.get() == before,
                        f"Ranges take from {side}: a red {side} field copied over is refused")
        _set_text(source, old)
        h.app.update()
        rng.show_button.invoke()

    enters = [("Radices", e, [rad.from_entry, rad.to_entry]) for e in (rad.from_entry,
                                                                        rad.to_entry)]
    enters += [("Compare", e, numbers + layouts) for e in numbers + layouts]
    enters += [("Comb", e, [comb.a_entry, comb.b_entry, comb.scale_entry])
               for e in (comb.a_entry, comb.b_entry, comb.scale_entry)]
    enters += [("Ranges Show", e, params) for e in params]
    enters += [("Ranges Find", rng.n_entry, [rng.n_entry])]
    enters += [("Primality", e, [pr.number_entry, pr.fuel_entry])
               for e in (pr.number_entry, pr.fuel_entry)]
    enters += [("Multiplicative", e, [mul.q_entry, mul.g_entry, mul.n_entry])
               for e in (mul.q_entry, mul.g_entry, mul.n_entry)]
    for name, e, fields in enters:
        calls, shown, launched = h.asked(_enter(e))
        got = _fields_of(calls[0]) if calls else set()
        passed &= check(len(calls) == 1 and got == _fields_of(fields) and not shown,
                        f"{name}: Enter in {e.number_field.purpose} asks like its button "
                        f"(calls {len(calls)}, got {len(got)} of {len(fields)})")

    for name, compute in (("Radices", rad.run), ("Compare", cmp_.run_compare),
                          ("Comb", comb.draw), ("Ranges Show", rng.show),
                          ("Ranges Find", rng.find), ("Multiplicative", mul.run)):
        calls, shown, _launched = h.asked(compute)
        passed &= check(not calls and not shown,
                        f"{name}: the computation run when the tab is built asks nothing")

    outputs = [("Radices Build", rad.build_button.invoke, rad.from_entry,
                lambda: (rad.summary_var.get(), rad.message_var.get())),
               ("Compare", cmp_.compare_button.invoke, sides["A"].layout_entries["dc"],
                lambda: (cmp_.verdict_var.get(), cmp_.message_var.get(),
                         len(cmp_.digits_tree.get_children()))),
               ("Comb Draw", comb.draw_button.invoke, comb.b_entry,
                lambda: (comb.result_var.get(), comb.message_var.get())),
               ("Ranges Show", rng.show_button.invoke, rng.param_entries["kc"],
                lambda: (rng.ranges_var.get(), rng.message_var.get(), len(rng.sweep_cells))),
               ("Ranges Find", rng.find_button.invoke, rng.n_entry,
                lambda: (rng.fit_note_var.get(), len(rng.fit_tree.get_children()))),
               ("Arithmetic power", ar.pow_button.invoke, ar.e_entry, ar.out.text),
               ("Primality Run", pr.run_button.invoke, pr.fuel_entry,
                lambda: (pr.message_var.get(), pr.verdict_var.get(), pr.is_running())),
               ("Multiplicative Run", mul.run_button.invoke, mul.q_entry,
                lambda: (mul.verdict_var.get(), mul.message_var.get()))]
    for name, action, field, state in outputs:
        old = _set_text(field, "abc")
        h.app.update()
        before = state()
        h.errors.clear()
        action()
        h.app.update()
        passed &= check(len(h.errors) == 1 and state() == before,
                        f"{name}: a refusal keeps what the view shows")
        _set_text(field, old)
    h.errors.clear()
    h.app.update()
    return passed


def irreducibility_minimum_checks(app):
    """Each Irreducibility field's minimum: below it red, at it fine."""
    tab = app.research_irreducibility_tab_widget
    rad, cmp_, comb = tab.radices_view, tab.compare_view, tab.comb_view
    rng, ar, pr, mul = tab.ranges_view, tab.arith_view, tab.primality_view, tab.mul_view
    layout_lows = {"ds": 2, "dz": 1, "dc": 1, "ks": 2, "kz": 1, "kc": 1}
    lows = [("radices from", rad.from_entry, 1), ("radices to", rad.to_entry, 1),
            ("comb a", comb.a_entry, 2), ("comb b", comb.b_entry, 2),
            ("ranges n", rng.n_entry, 1), ("arithmetic b", ar.b_entry, 1),
            ("arithmetic T", ar.t_entry, 2), ("arithmetic e", ar.e_entry, 1),
            ("arithmetic p", ar.p_entry, 2), ("arithmetic n", ar.n_entry, 1),
            ("primality number", pr.number_entry, 0), ("primality fuel", pr.fuel_entry, 1),
            ("multiplicative q", mul.q_entry, 2), ("multiplicative g", mul.g_entry, 1),
            ("multiplicative N", mul.n_entry, 0)]
    for side in ("A", "B"):
        lows.append((f"compare {side} number", cmp_.sides[side].number_entry, 0))
        lows.append((f"arithmetic {side} number", ar.number_entries[side], 0))
        lows += [(f"compare {side} {k}", cmp_.sides[side].layout_entries[k], low)
                 for k, low in layout_lows.items()]
    lows += [(f"ranges {k}", rng.param_entries[k], low) for k, low in layout_lows.items()]

    def problem(entry, text):
        _set_text(entry, text)
        entry.number_field.refresh(at_once=True)
        return entry.number_field.problem

    passed = True
    for label, entry, low in lows:
        old = entry.get()
        below = problem(entry, str(low - 1)) == "range"
        at = problem(entry, str(low)) is None
        problem(entry, old)
        passed &= check(below and at, f"{label}: minimum {low}")
    app.update()
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
    portal = tempfile.mkdtemp(prefix="primeatlas_field_refusal_")
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
        gen = app.generation_tab_widget
        h = Harness(app, errors, dialogs)
        passed = generation_cases(h, gen)
        passed &= minimum_checks(gen)
        passed &= research_cases(h, app)
        passed &= research_minimum_checks(app)
        passed &= irreducibility_cases(h, app)
        passed &= irreducibility_minimum_checks(app)
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(portal, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
