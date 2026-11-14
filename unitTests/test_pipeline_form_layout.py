"""
test_pipeline_form_layout.py -- the Generation tab's pipeline form (Advanced settings) on a
small screen, and its defaults.

A. Defaults (a fresh install, nothing remembered):
   - one parallel instance, one batch per worker, engine v7;
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


def main():
    part_a()
    part_b()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
