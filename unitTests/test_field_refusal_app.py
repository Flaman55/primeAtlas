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
The minimum of each field is the lower bound its action checks: the pipeline form's floor 0
and its other numbers 1; the k-tuple step, window and MR rounds 1 (0 hangs the sieve or
confirms every candidate), its other numbers 0.
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
    """Writes `text` into a variable or a widget; returns the previous text."""
    if hasattr(item, "winfo_class"):
        old = item.get()
        item.delete(0, "end")
        item.insert(0, text)
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
