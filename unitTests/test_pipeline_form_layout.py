"""
test_pipeline_form_layout.py -- the Generation tab's pipeline form (Advanced settings) on a
small screen, and its defaults.

A. Defaults (a fresh install, nothing remembered):
   - one parallel instance, one batch per worker, engine v7, workers Max;
   - orchestrator_v3.py's own default engine is the GUI's, and its header names code
     version 3.1 with what changed from 3.0.
B. Layout (isolated app, default text size, window 1280 x 720: a Full HD screen at Windows'
   150 % scaling, as a DPI-unaware Tk app sees it):
   - the form is split into four groups, in order: range, parallelism, pi(L_final), engine;
     each field sits in its group (floor/width/windows/iterations; instances/workers/
     batches; the two pi(L_final) checkboxes; engine, its knobs and the BPSW offset);
   - with the form shown, no field, label, button or checkbox ends past the right edge of
     the window, and none is squeezed below its requested width;
   - the pi(L_final) checkboxes wrap their text: each is narrower than the window;
   - the same holds after switching to every engine (the knob rows change);
   - the workers Auto button sits next to the workers field.
C. Workers "Max" = the CPU count read inside WSL (nproc), resolved at launch:
   - wsl_resources.resolve_workers: Max in any case and spacing -> the CPU count (capped
     at 256), unknown CPU count -> None; a positive whole number as typed; 0, blank,
     negative, a fraction or text -> None;
   - the verification's Threads Auto follows a workers field set to Max;
   - a pipeline run with workers Max launches with the probed count and keeps "Max" in
     the remembered settings; a failed probe stops the run with a message;
   - a typed number is launched as typed, without a probe;
   - a Quick-gen run launched directly takes the probed count for Max, 1 when the probe
     fails (it never blocks on this field).

Usage (Windows, real display):
    python unitTests/test_pipeline_form_layout.py
"""
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, _SCRIPT_DIR)

failures = []

WINDOW_W, WINDOW_H = 1280, 720


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def part_a():
    from primeatlas.generation import engine_options
    from primeatlas.generation.generation_settings import DEFAULT_GENERATION_SETTINGS
    loop = DEFAULT_GENERATION_SETTINGS["loop"]
    check(loop["n_instances"] == "1", f"default parallel instances 1 ({loop['n_instances']})")
    check(loop["batches_per_worker"] == "1",
          f"default batches per worker 1 ({loop['batches_per_worker']})")
    check(engine_options.DEFAULT_ENGINE == "v7" and loop["engine"] == "v7",
          f"default engine v7 ({engine_options.DEFAULT_ENGINE}, {loop['engine']})")
    check(loop["workers"] == "Max", f"default workers Max ({loop['workers']})")
    with open(os.path.join(_REPO_ROOT, "prime_sieve", "orchestrator_v3.py"),
              encoding="utf-8") as f:
        src = f.read()
    match = re.search(r'^SCANNER_VERSION = os\.environ\.get\("PRIMEATLAS_SCANNER_VERSION"\)'
                      r' or "([^"]+)"$', src, re.MULTILINE)
    check(match is not None and match.group(1) == "v7", "orchestrator_v3.py defaults to v7")
    head = src[:src.find("import ")]
    check("3.1" in head and "3.0" in head,
          "orchestrator_v3.py's header names code version 3.1 and the change from 3.0")


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _inside(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.master
    return False


def _fits(app, gen, label):
    app.update()
    right = app.winfo_rootx() + app.winfo_width()
    content = gen._loop_advanced_content
    bad = []
    for w in _descendants(content):
        if not w.winfo_ismapped() or w.winfo_class() in ("TFrame", "Frame", "TLabelframe"):
            continue
        end = w.winfo_rootx() + w.winfo_width()
        if end > right or w.winfo_width() + 1 < w.winfo_reqwidth():
            bad.append(f"{w.winfo_class()} {w.cget('text') if 'text' in w.keys() else ''!r}"
                       f" ends {end} > {right} or {w.winfo_width()} < {w.winfo_reqwidth()}")
    check(not bad, f"{label}: every widget within the window, none squeezed {bad[:3]}")


def part_b():
    import tkinter.messagebox
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    from primeatlas.generation import engine_options
    app = prime_atlas_v2._build_gui()()
    try:
        app.geometry(f"{WINDOW_W}x{WINDOW_H}+0+0")
        gen = app.generation_tab_widget
        page = gen
        while page.master is not app.main_notebook:
            page = page.master
        app.main_notebook.select(page)
        if not gen._loop_advanced_visible:
            gen._on_toggle_loop_advanced()
        app.update()

        groups = getattr(gen, "_loop_groups", None)
        check(isinstance(groups, dict)
              and list(groups) == ["range", "parallel", "pi_count", "engine"],
              f"four groups in order range, parallel, pi_count, engine ({groups and list(groups)})")
        if isinstance(groups, dict):
            def entry_of(var_name):
                var = gen._loop_vars[var_name]
                for w in _descendants(gen._loop_advanced_content):
                    if w.winfo_class() == "TEntry" and str(w.cget("textvariable")) == str(var):
                        return w
                return None
            for group, keys in (("range", ("base_exponent", "window_m",
                                           "window_count_per_run", "run_count")),
                                ("parallel", ("n_instances", "workers", "batches_per_worker"))):
                for key in keys:
                    e = entry_of(key)
                    check(e is not None and _inside(e, groups[group]), f"{key} in group {group}")
            checks = [w for w in _descendants(groups["pi_count"])
                      if w.winfo_class() == "TCheckbutton"]
            check(len(checks) == 2, f"both pi(L_final) checkboxes in their group ({len(checks)})")
            check(all(w.winfo_width() < WINDOW_W - 100 for w in checks),
                  f"pi(L_final) checkboxes wrap ({[w.winfo_width() for w in checks]})")
            engine_box = [w for w in _descendants(gen._loop_advanced_content)
                          if w.winfo_class() == "TCombobox"
                          and str(w.cget("textvariable")) == str(gen._engine_fields.engine_var)]
            check(len(engine_box) == 1 and _inside(engine_box[0], groups["engine"]),
                  "engine selector in group engine")
            offset = [w for w in _descendants(groups["engine"]) if w.winfo_class() == "TEntry"
                      and str(w.cget("textvariable")) == str(gen._advice_offset_var)]
            check(len(offset) == 1, "BPSW offset field in group engine")
            workers = entry_of("workers")
            auto = [w for w in _descendants(groups["parallel"]) if w.winfo_class() == "TButton"]
            check(workers is not None and len(auto) == 1
                  and workers.master is auto[0].master,
                  "the workers Auto button sits next to the workers field")

        _fits(app, gen, "default engine")
        for engine in engine_options.ENGINES:
            gen._engine_fields.engine_var.set(engine)
            _fits(app, gen, f"engine {engine}")
    finally:
        app.destroy()


def part_c_pure():
    from primeatlas.generation import verify_plan, wsl_resources
    rw = wsl_resources.resolve_workers
    check(rw("Max", 16) == 16 and rw(" max ", 16) == 16 and rw("MAX", 16) == 16,
          "Max in any case and spacing -> the CPU count")
    check(rw("Max", 1000) == 256, "Max is capped at 256")
    check(rw("Max", None) is None and rw("Max", 0) is None, "Max with no CPU count -> None")
    check(rw("8", None) == 8 and rw(" 12 ", 4) == 12, "a whole number as typed, no probe needed")
    check(all(rw(t, 16) is None for t in ("0", "", "-3", "abc", "8.5", None)),
          "0, blank, negative, fraction, text -> None")
    check(verify_plan.resolve_threads("Auto", "Max", 12) == 12,
          "verification Threads Auto follows workers Max")
    check(verify_plan.resolve_threads("Auto", "Max", None) is None,
          "Threads Auto with workers Max and no CPU count -> None")
    check(verify_plan.resolve_threads("Auto", "6", None) == 6, "Threads Auto, workers 6 -> 6")


def part_c_gui():
    import tkinter.messagebox
    errors = []
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: errors.append(a)
    tkinter.messagebox.askyesno = lambda *a, **k: True
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    from primeatlas.generation import (generation_tab, loop_section, quick_gen_runs,
                                       wsl_resources)

    class _Runner:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def is_running(self):
            return True

        def stop(self):
            pass

    generation_tab.WslLoggedRunner = _Runner
    probes = []
    cpu = {"count": 12}

    def _probe(*_a, **_k):
        probes.append(1)
        return cpu["count"]

    wsl_resources.estimate_wsl_available_cpu_count = _probe
    loop_argv, direct_argv = [], []
    real_loop, real_direct = loop_section.build_loop_argv, quick_gen_runs.build_orchestrator_direct_argv
    loop_section.build_loop_argv = lambda *a, **k: loop_argv.append(a) or real_loop(*a, **k)
    quick_gen_runs.build_orchestrator_direct_argv = (
        lambda *a, **k: direct_argv.append(a) or real_direct(*a, **k))
    app = prime_atlas_v2._build_gui()()
    try:
        gen = app.generation_tab_widget
        gen._loop_runner_factory = _Runner
        check(gen._loop_vars["workers"].get() == "Max", "the form shows workers Max")
        gen._loop_vars["base_exponent"].set("12")
        gen._loop_vars["window_count_per_run"].set("10")

        def run_loop():
            gen._loop_runner = None
            gen._on_run_loop()
            gen._on_loop_finished(0)

        run_loop()
        check(loop_argv and loop_argv[-1][6] == 12,
              f"pipeline run with Max launches the probed 12 workers "
              f"({loop_argv[-1][6] if loop_argv else None})")
        check(gen._generation_settings["loop"]["workers"] == "Max",
              "Max stays remembered as Max, not the probed number")
        cpu["count"] = None
        n_runs, n_err = len(loop_argv), len(errors)
        run_loop()
        check(len(loop_argv) == n_runs and len(errors) == n_err + 1,
              "a failed probe stops the pipeline run with a message")
        gen._loop_vars["workers"].set("5")
        n_probes = len(probes)
        run_loop()
        check(loop_argv[-1][6] == 5 and len(probes) == n_probes,
              "a typed number launches as typed, without a probe")

        gen._loop_vars["workers"].set("Max")
        cpu["count"] = 20
        gen._loop_runner = None
        gen._on_run_orchestrator_direct(12, 0, 10)
        gen._on_loop_finished(0)
        check(direct_argv and direct_argv[-1][6] == 20,
              f"Quick-gen direct run takes the probed count for Max "
              f"({direct_argv[-1][6] if direct_argv else None})")
        cpu["count"] = None
        gen._loop_runner = None
        gen._on_run_orchestrator_direct(12, 0, 10)
        gen._on_loop_finished(0)
        check(direct_argv[-1][6] == 1, "Quick-gen direct run: a failed probe -> 1 worker")
    finally:
        app.destroy()


def main():
    part_a()
    part_b()
    part_c_pure()
    part_c_gui()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
