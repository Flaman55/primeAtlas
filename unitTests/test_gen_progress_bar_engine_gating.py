"""
test_gen_progress_bar_engine_gating.py -- regression test for the 2026-08-27 fix
disabling the shared bottom progress bar for engines that don't print granular
progress to stdout (primesieve/cudasieve mode).

Background: primesieve mode (prime_sieve_primesieve.py) and cudasieve mode
(prime_sieve_cudasieve.py) both do ONE blocking call with no per-batch reporting --
confirmed by reading their actual print() statements -- so the only line of theirs
that ever matches anything in _update_shared_progress_from_generation_chunk() is the
final "[*] TOTAL PRIMES FOUND..." line. Before this fix, that line unconditionally
snapped totals_progress to "100% done", which combined with the earlier "stuck full
after generation" bug (see test_search_worker.py's own regression block) made the bar
look like it was tracking progress when it was really just jumping from whatever it
already showed straight to full at the very end -- Artur's own observation ("widzę
dwa stany pasek pusty i pasek pełny brak wartości pomiędzy"). Artur's explicit
decision (2026-08-27): leave totals_progress alone entirely for those two engines
(self._gen_progress_bar_active=False) rather than fake a step count; the status TEXT
still updates normally either way. The old batched engine (orchestrator_v3.py /
orchestrator_loop_v2.py) keeps its existing live bar behavior
(self._gen_progress_bar_active=True) since it genuinely does print granular
"[+] Progress: ..." lines.

This test drives the REAL GenerationTab method
(_update_shared_progress_from_generation_chunk) with real console-chunk strings
(copy-pasted from the actual print() format strings in prime_sieve_v1/v3/v4/v4_1.py
and prime_sieve_primesieve.py/prime_sieve_cudasieve.py), never a mock -- catching a
future accidental regex/format drift the same way a mock never would.

Usage (Windows, real display):
    python unitTests\\test_gen_progress_bar_engine_gating.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tmp_tk/usr/lib/python3.10:/tmp/tmp_tk/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tmp_tk/usr/lib/x86_64-linux-gnu:/tmp/tmp_tk/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_gen_progress_bar_engine_gating.py
"""
import os
import shutil
import sys
import tempfile
import tkinter.messagebox

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None

    sys.argv = ["prime_atlas_v1.py"]
    import prime_atlas_v1

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_gen_progress_gating_test_")
    try:
        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        app.update()
        gen = app.generation_tab_widget
        bar = gen.totals_progress

        # =====================================================================
        # primesieve/cudasieve mode (flag OFF): the DONE line -- the only line these
        # two engines' real stdout ever emits that matches anything here -- must NOT
        # touch the bar at all, whatever state it was already in.
        # =====================================================================
        bar.configure(mode="determinate", maximum=7, value=7)
        gen._gen_progress_bar_active = False
        gen._update_shared_progress_from_generation_chunk(
            "\n[*] TOTAL PRIMES FOUND this run: 654,321 across 3 window(s)")
        check(int(bar["maximum"]) == 7 and int(bar["value"]) == 7,
              f"primesieve/cudasieve mode's own DONE line must leave totals_progress "
              f"completely untouched (got maximum={bar['maximum']!r}, "
              f"value={bar['value']!r})")
        check(gen.status.get() == gen.T("gen.status_progress_done"),
              f"the status TEXT still updates normally even with the bar disabled "
              f"(got {gen.status.get()!r})")

        # A real primesieve/cudasieve run's header lines (never matched by any regex
        # here anyway) must also not crash or move the bar.
        gen._update_shared_progress_from_generation_chunk(
            "[*] PRIME SIEVE -- v1.0 (primesieve mode: calls libprimesieve's own "
            "public C API directly)")
        check(int(bar["maximum"]) == 7 and int(bar["value"]) == 7,
              "an unmatched header line must not move the bar either "
              f"(got maximum={bar['maximum']!r}, value={bar['value']!r})")

        # =====================================================================
        # Old batched engine (flag ON): prep -> sieve-progress -> done must move the
        # bar exactly as before this fix (real print() format strings from
        # prime_sieve_v1/v3/v4/v4_1.py -- see this file's own module docstring).
        # =====================================================================
        gen._gen_progress_bar_active = True
        bar.configure(mode="determinate", maximum=1, value=0)
        gen._gen_step_total = None

        gen._update_shared_progress_from_generation_chunk(
            "[*] Active sieving primes used (pi(L_final)): 5,761,455")
        check(int(bar["maximum"]) == 2 and int(bar["value"]) == 1,
              f"batched-engine prep-done line must show the provisional 1-of-2 state "
              f"(got maximum={bar['maximum']!r}, value={bar['value']!r})")

        gen._update_shared_progress_from_generation_chunk(
            "[+] Progress: 25.00% (1/4 batches) | elapsed 12.3s")
        check(int(bar["maximum"]) == 5 and int(bar["value"]) == 2,
              f"batched-engine first sieve-progress line must set the real total "
              f"(4 batches + 1 prep step = 5) and value=done+1=2 "
              f"(got maximum={bar['maximum']!r}, value={bar['value']!r})")

        gen._update_shared_progress_from_generation_chunk(
            "\n[*] TOTAL PRIMES FOUND this run: 12,345 across 4 window(s)")
        check(int(bar["maximum"]) == int(bar["value"]) == 5,
              f"batched-engine DONE line snaps the bar to fully complete "
              f"(got maximum={bar['maximum']!r}, value={bar['value']!r})")

        # =====================================================================
        # Launcher wiring: each _on_run_*() sets the flag to match its own engine.
        # Stubs WslLoggedRunner to avoid any real subprocess/WSL dependency.
        # =====================================================================
        import primeatlas.generation_tab as generation_tab_mod

        class _FakeRunner:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def is_running(self):
                return False

        orig_runner_cls = generation_tab_mod.WslLoggedRunner
        generation_tab_mod.WslLoggedRunner = _FakeRunner
        try:
            gen.settings_tab_ref = None  # not used by these launchers directly
            gen._gen_progress_bar_active = True
            gen._on_run_primesieve(10, 0, 1)
            check(gen._gen_progress_bar_active is False,
                  "_on_run_primesieve() must set _gen_progress_bar_active=False")

            gen._gen_progress_bar_active = True
            gen._on_run_cudasieve(41, 0, 1)
            check(gen._gen_progress_bar_active is False,
                  "_on_run_cudasieve() must set _gen_progress_bar_active=False")

            gen._gen_progress_bar_active = False
            gen._on_run_orchestrator_direct(10, 0, 1)
            check(gen._gen_progress_bar_active is True,
                  "_on_run_orchestrator_direct() must re-enable "
                  "_gen_progress_bar_active=True (it DOES print granular progress)")
        finally:
            generation_tab_mod.WslLoggedRunner = orig_runner_cls

        app.destroy()
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
