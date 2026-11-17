"""The thread counts of the real app (core/threads_field.py wired into the tabs).

Drives the app (temp storage, the WSL probes faked, launches stubbed). Checks:
  - the app reads WSL's CPU count once at startup, in the background, into cpu_dynamic;
  - the four thread counts are ThreadsFields: the pipeline form's workers, Verify Threads,
    Pseudosquares Threads (every panel copy) and the v5/v6/v7 write threads; there is no
    other Spinbox or Entry bound to their variables;
  - workers: Max (CPU count), no Auto button next to it;
  - Verify Threads: Auto shows the workers it resolves to and follows the workers field,
    Max shows the CPU count;
  - Pseudosquares Threads: Auto bare (the program picks), Max shows the CPU count and a
    count run with Max hands the program that count;
  - write threads: numbers only, the default 8 above the CPU count becomes the count;
  - stored values above the count load as Max (workers 24, Pseudosquares 24), a lower one
    stays (Verify 3);
  - a launch's own probe updates the count every field shows; so does the About tab's read.
Windows, real display:
    python unitTests/test_threads_fields_app.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_time_simulation import check  # noqa: E402

CPUS = 6
WRITE_KNOBS = ("v5_write_threads", "v6_write_threads", "v7_write_threads")


def _widgets(widget, found):
    from tkinter import ttk
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Entry, ttk.Spinbox)) and not isinstance(child, ttk.Combobox):
            found.append(child)
        _widgets(child, found)
    return found


def _bound(app, var):
    """Every entry or spinbox of the app showing `var`: directly or as a ThreadsField."""
    name = str(var)
    return [w for w in _widgets(app, []) if str(w.cget("textvariable")) == name
            or str(getattr(w, "variable", "")) == name]


def _wait(app, condition, ms=5000):
    for _ in range(ms // 50):
        app.update()
        if condition():
            return True
        app.after(50)
    return condition()


def field_checks(app, gen):
    from primeatlas.core import cpu_dynamic
    from primeatlas.core.threads_field import ThreadsField
    T = gen.T
    passed = check(_wait(app, lambda: cpu_dynamic.WSL_CPUS == CPUS),
                   f"startup reads WSL's CPU count ({cpu_dynamic.WSL_CPUS})")
    fields = {
        "workers": gen._loop_vars["workers"],
        "verify": gen._verify_vars["threads"],
        "pseudosquares": gen.quick_pseudosquares_threads_var,
    }
    fields.update({key: gen._engine_fields.knob_vars[key] for key in WRITE_KNOBS})
    shown = {}
    for name, var in fields.items():
        widgets = _bound(app, var)
        passed &= check(widgets and all(isinstance(w, ThreadsField) for w in widgets),
                        f"{name}: every control is a ThreadsField ({len(widgets)}: "
                        f"{sorted({type(w).__name__ for w in widgets})})")
        shown[name] = widgets
    workers = shown["workers"][0]
    passed &= check(workers.get() == f"Max ({CPUS})" and fields["workers"].get() == "Max",
                    f"workers: stored 24 loads as Max, shown Max ({CPUS}) ({workers.get()!r})")
    auto_text = T("quick.auto_button")
    buttons = [w for w in workers.master.winfo_children()
               if w.winfo_class() == "TButton" and str(w.cget("text")) == auto_text]
    passed &= check(not buttons, "workers: no Auto button")

    verify = shown["verify"][0]
    passed &= check(fields["verify"].get() == "3", "Verify: a stored 3 stays")
    fields["verify"].set("Auto")
    app.update()
    passed &= check(verify.get() == f"Auto ({CPUS})",
                    f"Verify: Auto shows the workers' Max ({verify.get()!r})")
    fields["workers"].set("4")
    app.update()
    passed &= check(verify.get() == "Auto (4)", f"Verify: Auto follows workers 4 ({verify.get()!r})")
    passed &= check(f"Max ({CPUS})" in [str(v) for v in verify.cget("values")],
                    "Verify: Max shows the CPU count")

    pseudo = shown["pseudosquares"]
    passed &= check(fields["pseudosquares"].get() == "Max"
                    and all(w.get() == f"Max ({CPUS})" for w in pseudo),
                    "Pseudosquares: stored 24 loads as Max in every copy")
    fields["pseudosquares"].set("Auto")
    app.update()
    passed &= check(all(w.get() == "Auto" for w in pseudo), "Pseudosquares: Auto is bare")
    fields["pseudosquares"].set(str(CPUS + 1))
    app.update()
    passed &= check(fields["pseudosquares"].get() == "Max",
                    "Pseudosquares: above the count becomes Max")

    for key in WRITE_KNOBS:
        var = fields[key]
        passed &= check(var.get() == str(CPUS),
                        f"{key}: the default 8 becomes the count {CPUS} ({var.get()!r})")
        var.set("2")
        app.update()
        passed &= check(var.get() == "2", f"{key}: 2 stays")
    return passed


def launch_checks(app, gen, probe):
    from primeatlas.core import cpu_dynamic
    passed = True
    runs = []
    gen._on_run_pseudosquares = lambda *args: runs.append(args)
    gen.quick_pseudosquares_mode_var.set("count")
    gen.quick_pseudosquares_from_var.set("")
    gen.quick_pseudosquares_floor_var.set("20")
    gen.quick_pseudosquares_width_var.set("1")
    gen.quick_pseudosquares_threads_var.set("Max")
    app.update()
    gen._on_quick_generate_pseudosquares()
    passed &= check(runs and runs[-1][4] == CPUS,
                    f"Pseudosquares with Max hands the program {CPUS} threads ({runs[-1:]})")

    probe["count"] = 3
    gen._loop_vars["workers"].set("Max")
    gen._verify_vars["threads"].set("5")
    app.update()
    settings = gen._collect_loop_settings_from_form()
    app.update()
    passed &= check(settings is not None and settings["workers"] == 3
                    and cpu_dynamic.WSL_CPUS == 3,
                    f"a launch probes again: workers 3, the count 3 ({cpu_dynamic.WSL_CPUS})")
    passed &= check(gen._verify_vars["threads"].get() == "Max",
                    "the new count reaches the other fields: Verify 5 becomes Max")

    from primeatlas.about import system_info
    gib = 1024 ** 3
    system_info.read_system_info = lambda: system_info.SystemInfo(
        system_info.WindowsInfo(os_name="Windows Test", cpu_model="CPU", cores=4, threads=8,
                                ram_total=16 * gib, ram_free=8 * gib),
        system_info.WslInfo(distro="Ubuntu", kernel="k", cpus=7, mem_total=8 * gib,
                            mem_available=7 * gib),
        system_info.WslConfig(None, None, None))
    app.about_tab_widget._read_system()
    passed &= check(_wait(app, lambda: cpu_dynamic.WSL_CPUS == 7),
                    f"the About tab's read updates the count ({cpu_dynamic.WSL_CPUS})")
    return passed


def main():
    from tkinter import messagebox
    errors = []
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showerror = lambda title, text, **k: errors.append(text)
    messagebox.askyesno = lambda *a, **k: True
    messagebox.askokcancel = lambda *a, **k: True
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    from primeatlas.core import cpu_dynamic, ui_state_dynamic
    from primeatlas.generation import wsl_resources
    cpu_dynamic.WSL_CPUS = None
    probe = {"count": CPUS}
    wsl_resources.estimate_wsl_available_cpu_count = lambda timeout=10: probe["count"]
    store = ui_state_dynamic.STORE
    store.set("generation.loop.workers", "24")
    store.set("generation.verify.threads", "3")
    store.set("quick.pseudosquares_threads", "24")
    app = None
    passed = False
    try:
        app = prime_atlas_v2._build_gui()()
        app.update()
        gen = app.generation_tab_widget
        passed = field_checks(app, gen)
        passed &= launch_checks(app, gen, probe)
        passed &= check(not errors, f"no error dialogs ({errors[:1]})")
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:  # noqa: BLE001
                pass
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
