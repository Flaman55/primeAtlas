"""
test_machine_details.py -- this computer's entry in benchmark_machines.json from the app: the
hardware read at startup, the entry written at a launch, the window for the values Windows
cannot give, and the question after the first finished run.

A. Startup: the app reads the CPU/RAM details once in the background
   (core.hardware_details.read_hardware_details, looked up at call time) into
   core.hardware_dynamic.DETAILS; building the app does not wait for it. A read with nothing
   known keeps known details. About's read (system_info.SystemInfo.details) refreshes them.
B. Launch: generation.wsl_command.build_wsl_logged_command() records this computer in the
   storage's file (machines_file.record) with the known details; no details yet: no file; a
   broken file stays untouched and the command is still built.
C. About -> This computer: a "Fill in details..." button opens the window
   (about.machine_details_window.MachineDetailsWindow), recording the entry first when the
   file has none; a second click while it is open opens no second window.
   The window: a how-to naming Task Manager and CPU-Z, and BIOS/UEFI as optional for advanced
   users; architecture (text), release year (1970..2100), turbo clock MHz (100..10000) and
   CL (1..100) as number fields with a purpose in both languages, XMP/EXPO as a list (blank,
   on, off); the fields show the entry's current values; a JEDEC hint next to XMP when the
   configured speed is above the JEDEC maximum of its type, none otherwise.
   Save stores the fields (machines_file.set_manual, blank = None) and closes; Cancel and the
   window's close button store nothing; a red field refuses Save, stores nothing and keeps
   the window open. A broken file: an error naming the file, a copy kept, no window. No
   entry and no details read yet: a message saying so, no window, no file.
D. The question (about.machine_prompt.MachinePrompt.after_rows(rows)): asked (Yes/No) only
   when the rows hold a row of this computer and its current entry was not asked yet; Yes
   opens the window, both answers mark the entry asked; never asked twice for one entry; a
   new entry after a hardware change asks again; no row of this computer or no entry: no
   question. A broken file: one error per session, one copy.
E. The app: a reload of the Benchmark log with a row of this computer asks (the Benchmark
   tab hands its rows to the app's MachinePrompt).
F. Every machine.* key exists in English and Polish.

Windows, real display:
    python unitTests/test_machine_details.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GB = 1024 ** 3
asked, errors, infos = [], [], []
answers = []


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def fake_details(**changes):
    from primeatlas.core.hardware_details import HardwareDetails
    base = dict(cpu_name="Test CPU 9000", cpu_maker="Test", cpu_family="Family 1", cores=8,
                threads=16, base_mhz=3700, l2_kb=4096, l3_kb=32768, ram_bytes=32 * GB,
                ram_type="DDR4", ram_mts=3600, ram_modules=2)
    base.update(changes)
    return HardwareDetails(**base)


def _wait(app, condition, seconds=5.0):
    end = time.time() + seconds
    while not condition() and time.time() < end:
        app.update()
        time.sleep(0.02)
    app.update()


def _copies(storage):
    from primeatlas.core import machines_file as mf
    return [n for n in os.listdir(storage)
            if n.startswith(mf.FILE_NAME) and n != mf.FILE_NAME and ".tmp" not in n]


def _broken(storage):
    from primeatlas.core import machines_file as mf
    with open(mf.path(storage), "w", encoding="utf-8") as f:
        f.write("{broken")


def startup_checks(app, reads):
    from primeatlas.core import hardware_dynamic
    _wait(app, lambda: hardware_dynamic.DETAILS is not None)
    passed = check(len(reads) == 1 and hardware_dynamic.DETAILS == fake_details(),
                   f"startup reads the details once ({len(reads)} reads)")
    from primeatlas.core.hardware_details import HardwareDetails
    hardware_dynamic.set_details(HardwareDetails())
    hardware_dynamic.set_details(None)
    passed &= check(hardware_dynamic.DETAILS == fake_details(),
                    "a read with nothing known keeps the known details")
    return passed


def launch_checks(storage):
    from primeatlas.core import hardware_dynamic, machines_file as mf, windows_hardware
    from primeatlas.generation import wsl_command
    passed = True
    machine = windows_hardware.this_machine_id()
    log = os.path.join(storage, ".generation_logs", "x.log")

    def build():
        return wsl_command.build_wsl_logged_command(["true"], log, log + ".exit", storage)

    known = hardware_dynamic.DETAILS
    hardware_dynamic.DETAILS = None
    build()
    passed &= check(not os.path.exists(mf.path(storage)), "no details yet: no file")
    hardware_dynamic.DETAILS = known
    command = build()
    entry = mf.current(mf.load(storage), machine)
    passed &= check(command and entry and entry["auto"]["cpu_name"] == "Test CPU 9000",
                    "a launch records this computer")
    os.remove(mf.path(storage))
    _broken(storage)
    command = build()
    with open(mf.path(storage), encoding="utf-8") as f:
        passed &= check(command and f.read() == "{broken",
                        "broken file: untouched, command still built")
    os.remove(mf.path(storage))
    return passed


def _all(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _all(child)


def _texts(widget):
    import tkinter as tk
    out = []
    for w in _all(widget):
        try:
            out.append(str(w.cget("text")))
        except tk.TclError:
            pass
    return "\n".join(out)


def window_checks(app, storage):
    from primeatlas.core import hardware_dynamic, machines_file as mf, windows_hardware
    from primeatlas.about.machine_details_window import MachineDetailsWindow
    passed = True
    about = app.about_tab_widget
    T = about.T
    machine = windows_hardware.this_machine_id()
    button = getattr(about, "machine_button", None)
    passed &= check(button is not None
                    and str(button).startswith(str(about.system_text.master) + "."),
                    "a Fill in details button sits in the This computer frame")
    if button is None:
        return False
    prompt = app.machine_prompt
    button.invoke()
    app.update()
    window = prompt.window
    passed &= check(isinstance(window, MachineDetailsWindow) and window.winfo_exists()
                    and mf.current(mf.load(storage), machine) is not None,
                    "the button records the entry and opens the window")
    button.invoke()
    app.update()
    windows = [w for w in _all(app) if isinstance(w, MachineDetailsWindow)]
    passed &= check(len(windows) == 1, f"a second click opens no second window ({len(windows)})")

    text = _texts(window)
    passed &= check("CPU-Z" in text and T("machine.howto") in text
                    and T("machine.howto_bios") in text and "BIOS" in T("machine.howto_bios"),
                    "the how-to names CPU-Z, and BIOS as optional")
    passed &= check("3200" in str(window.xmp_hint.cget("text")),
                    f"DDR4-3600: the JEDEC hint names 3200 ({window.xmp_hint.cget('text')!r})")
    purposes = {f.number_field.purpose for f in window.number_entries}
    passed &= check(purposes == {"field_tip.machine_year", "field_tip.machine_turbo", "field_tip.machine_cl"},
                    f"three number fields with purposes ({purposes})")
    passed &= check(list(window.xmp_box.cget("values"))
                    == ["", T("machine.xmp_on"), T("machine.xmp_off")],
                    "XMP/EXPO is a list: blank, on, off")

    window.architecture_var.set("Zen 3")
    window.year_var.set("2020")
    window.turbo_var.set("4 800")
    window.cl_var.set("16")
    window.xmp_var.set(T("machine.xmp_on"))
    window.cancel()
    app.update()
    entry = mf.current(mf.load(storage), machine)
    passed &= check(not window.winfo_exists() and entry["manual"]["cl"] is None,
                    "Cancel closes and stores nothing")

    window = prompt.open_details()
    window.year_var.set("abc")
    window.cl_var.set("16")
    window.save()
    app.update()
    entry = mf.current(mf.load(storage), machine)
    passed &= check(window.winfo_exists() and entry["manual"]["cl"] is None and errors,
                    "a red field refuses Save, nothing stored, window stays")
    errors.clear()
    window.year_var.set("2020")
    window.turbo_var.set("4 800")
    window.architecture_var.set(" Zen 3 ")
    window.xmp_var.set(T("machine.xmp_on"))
    window.save()
    app.update()
    entry = mf.current(mf.load(storage), machine)
    passed &= check(not window.winfo_exists() and entry["manual"] == {
        "architecture": "Zen 3", "year": 2020, "turbo_mhz": 4800, "cl": 16, "xmp": True},
        f"Save stores the fields and closes ({entry['manual']})")

    window = prompt.open_details()
    passed &= check(window.architecture_var.get() == "Zen 3" and window.year_var.get() == "2020"
                    and window.cl_var.get() == "16" and window.xmp_var.get() == T("machine.xmp_on"),
                    "the fields show the stored values")
    window.cl_var.set("")
    window.xmp_var.set("")
    window.save()
    app.update()
    entry = mf.current(mf.load(storage), machine)
    passed &= check(entry["manual"]["cl"] is None and entry["manual"]["xmp"] is None,
                    "blank fields store None")
    window = prompt.open_details()
    window.protocol_close()
    app.update()
    passed &= check(not window.winfo_exists(), "the close button closes like Cancel")

    hardware_dynamic.DETAILS = fake_details(ram_type=None)
    os.remove(mf.path(storage))
    window = prompt.open_details()
    passed &= check(window is not None and not str(window.xmp_hint.cget("text")).strip(),
                    "unknown RAM type: no JEDEC hint")
    window.cancel()

    os.remove(mf.path(storage))
    known = hardware_dynamic.DETAILS
    hardware_dynamic.DETAILS = None
    infos.clear()
    passed &= check(prompt.open_details() is None and infos
                    and not os.path.exists(mf.path(storage)),
                    "no entry and no details: a message, no window, no file")
    hardware_dynamic.DETAILS = known

    _broken(storage)
    errors.clear()
    passed &= check(prompt.open_details() is None and errors and mf.FILE_NAME in errors[-1]
                    and len(_copies(storage)) == 1, "broken file: error naming it, copy, no window")
    os.remove(mf.path(storage))
    for name in _copies(storage):
        os.remove(os.path.join(storage, name))
    return passed


def _row(machine):
    return {"run_timestamp_utc": "2026-11-20 10:00:00 UTC", "machine_id": machine,
            "base_exponent": "20"}


def prompt_checks(app, storage):
    from primeatlas.about.machine_details_window import MachineDetailsWindow
    from primeatlas.core import hardware_dynamic, machines_file as mf, windows_hardware
    passed = True
    machine = windows_hardware.this_machine_id()
    prompt = app.machine_prompt
    prompt.after_rows([_row(machine)])
    passed &= check(not asked, "no entry: no question")
    mf.record(storage, machine, hardware_dynamic.DETAILS)
    prompt.after_rows([_row("ffffffffffff"), {"machine_id": ""}])
    passed &= check(not asked, "no row of this computer: no question")
    answers.append(False)
    prompt.after_rows([_row(machine)])
    entry = mf.current(mf.load(storage), machine)
    passed &= check(len(asked) == 1 and entry["asked"] and prompt.window is None,
                    "Later: asked once, marked asked, no window")
    prompt.after_rows([_row(machine)])
    passed &= check(len(asked) == 1, "never asked twice for one entry")
    hardware_dynamic.DETAILS = fake_details(ram_bytes=64 * GB)
    mf.record(storage, machine, hardware_dynamic.DETAILS,
              datetime(2030, 1, 1, tzinfo=timezone.utc))
    answers.append(True)
    prompt.after_rows([_row(machine)])
    app.update()
    entry = mf.current(mf.load(storage), machine)
    passed &= check(len(asked) == 2 and entry["asked"]
                    and isinstance(prompt.window, MachineDetailsWindow),
                    "a new entry asks again; Yes opens the window")
    prompt.window.cancel()
    _broken(storage)
    errors.clear()
    prompt.after_rows([_row(machine)])
    prompt.after_rows([_row(machine)])
    passed &= check(len(errors) == 1 and len(_copies(storage)) == 1 and len(asked) == 2,
                    f"broken file: one error, one copy ({len(errors)}, {_copies(storage)})")
    os.remove(mf.path(storage))
    for name in _copies(storage):
        os.remove(os.path.join(storage, name))
    return passed


def app_checks(app, storage):
    import csv
    from benchmark_log_schema import BENCHMARK_FIELDNAMES
    from primeatlas.core import hardware_dynamic, machines_file as mf, windows_hardware
    machine = windows_hardware.this_machine_id()
    app.machine_prompt._broken_reported = False
    mf.record(storage, machine, hardware_dynamic.DETAILS)
    with open(os.path.join(storage, "benchmark_log.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        writer.writeheader()
        writer.writerow({k: _row(machine).get(k, "") for k in BENCHMARK_FIELDNAMES})
    asked.clear()
    answers.append(False)
    app.benchmark_tab_widget.reload_benchmark_log()
    app.update()
    return check(len(asked) == 1, "a Benchmark reload with a row of this computer asks")


def locale_checks():
    folder = os.path.join(ROOT, "primeatlas", "core", "locales")
    keys = {}
    for lang in ("en", "pl"):
        with open(os.path.join(folder, f"strings_{lang}.json"), encoding="utf-8") as f:
            keys[lang] = {k for k, v in json.load(f).items()
                          if k.startswith("machine.") and str(v).strip()}
    return check(keys["en"] and keys["en"] == keys["pl"] and len(keys["en"]) >= 15,
                 f"machine.* keys in both languages ({len(keys['en'])}, "
                 f"differ: {sorted(keys['en'] ^ keys['pl'])})")


def main():
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda title, text, **k: infos.append(text)
    messagebox.showwarning = lambda title, text, **k: errors.append(text)
    messagebox.showerror = lambda title, text, **k: errors.append(text)

    def ask(title, text, **kwargs):
        asked.append(text)
        return answers.pop(0) if answers else False
    messagebox.askyesno = ask
    from primeatlas.core import windows_hardware
    if windows_hardware.this_machine_id() is None:
        print("SKIPPED (Windows only: needs this computer's id)")
        return 0
    from primeatlas.core import hardware_details
    reads = []

    def fake_read(*_a, **_k):
        reads.append(1)
        return fake_details()
    portal = tempfile.mkdtemp(prefix="primeatlas_machine_details_")
    app = None
    passed = False
    try:
        from app_sandbox import isolate_app
        prime_atlas_v2, _portal = isolate_app(portal)
        hardware_details.read_hardware_details = fake_read
        app = prime_atlas_v2._build_gui()()
        app.update()
        passed = startup_checks(app, reads)
        passed &= launch_checks(portal)
        passed &= window_checks(app, portal)
        passed &= prompt_checks(app, portal)
        passed &= app_checks(app, portal)
        passed &= locale_checks()
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
    sys.exit(main())
