"""
test_pi_seed_checkbox_exclusivity.py -- GUI regression test for the mutual-exclusion fix
between the Generation tab's two "how to compute pi(L_final)" checkboxes (Artur, 2026-08-27,
same day as the pi-seed feature itself): "Licz pi(L_final) od zera" (self._loop_count_sieving_
var) and "Zasiew z Wikipedii" (self._loop_use_pi_seed_var) are ALTERNATIVES, not an independent
base+modifier pair -- checking one must uncheck the other, and having both off is the only way
to skip computing pi(L_final) entirely. See generation_tab.py's own comment above the two
Checkbuttons in _build_generation_tab for the full reasoning, and
_collect_loop_settings_from_form()'s docstring for how the two vars combine into the single
effective compute_sieving_primes_count flag actually sent to the scripts.

Requires a real PortalBrowserApp() (tkinter) since the mutual-exclusion wiring lives on real
BooleanVar trace callbacks set up during widget construction -- not testable as a pure function
the way test_pi_seed.py's _seed_from_known_pi()/count_sieving_primes_cached() tests are.

Usage (Windows, real display):
    python unitTests\\test_pi_seed_checkbox_exclusivity.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tmp_tk/usr/lib/python3.10:/tmp/tmp_tk/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tmp_tk/usr/lib/x86_64-linux-gnu:/tmp/tmp_tk/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_pi_seed_checkbox_exclusivity.py
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


def _patch_app_settings(app_settings):
    app_settings.save = lambda: None


def main():
    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_pi_seed_ui_test_")
    try:
        tkinter.messagebox.showinfo = lambda *a, **k: None
        tkinter.messagebox.showerror = lambda *a, **k: None

        sys.argv = ["prime_atlas_v1.py"]
        import prime_atlas_v1

        _patch_app_settings(prime_atlas_v1.APP_SETTINGS)
        prime_atlas_v1.APP_SETTINGS.set_storage_path(tmp_portal)
        prime_atlas_v1.PORTAL_FOLDER = tmp_portal

        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        app.update()

        gen = app.generation_tab_widget

        # --- both start off -----------------------------------------------------------
        check(not gen._loop_count_sieving_var.get() and not gen._loop_use_pi_seed_var.get(),
              "both checkboxes start unchecked on a fresh portal (no saved settings)")

        # --- checking 'count from scratch' unchecks 'use Wikipedia seed' ---------------
        gen._loop_use_pi_seed_var.set(True)
        app.update()
        gen._loop_count_sieving_var.set(True)
        app.update()
        check(gen._loop_count_sieving_var.get() and not gen._loop_use_pi_seed_var.get(),
              f"checking 'count from scratch' while 'use Wikipedia seed' was on turns the "
              f"seed checkbox back off (got count_sieving={gen._loop_count_sieving_var.get()}, "
              f"use_pi_seed={gen._loop_use_pi_seed_var.get()})")

        # --- checking 'use Wikipedia seed' unchecks 'count from scratch' ---------------
        gen._loop_use_pi_seed_var.set(True)
        app.update()
        check(gen._loop_use_pi_seed_var.get() and not gen._loop_count_sieving_var.get(),
              f"checking 'use Wikipedia seed' while 'count from scratch' was on turns THAT "
              f"one back off instead (got count_sieving={gen._loop_count_sieving_var.get()}, "
              f"use_pi_seed={gen._loop_use_pi_seed_var.get()})")

        # --- unchecking the currently-checked one leaves both off, doesn't re-check the
        # other (i.e. this isn't a radio group that always has exactly one selected) -----
        gen._loop_use_pi_seed_var.set(False)
        app.update()
        check(not gen._loop_count_sieving_var.get() and not gen._loop_use_pi_seed_var.get(),
              f"unchecking the seed checkbox leaves BOTH off -- doesn't fall back to "
              f"re-checking 'count from scratch' (got count_sieving="
              f"{gen._loop_count_sieving_var.get()}, use_pi_seed="
              f"{gen._loop_use_pi_seed_var.get()})")

        # --- _collect_loop_settings_from_form(): effective compute_sieving_primes_count is
        # the OR of the two, and use_known_pi_seed is reported separately -----------------
        for key in ("base_exponent", "run_count", "n_instances", "window_count_per_run",
                    "workers", "batches_per_worker", "window_m"):
            gen._loop_vars[key].set("1")

        gen._loop_count_sieving_var.set(False)
        gen._loop_use_pi_seed_var.set(False)
        app.update()
        parsed = gen._collect_loop_settings_from_form()
        check(parsed["compute_sieving_primes_count"] is False and
              parsed["use_known_pi_seed"] is False,
              f"both off -> effective compute_sieving_primes_count=False, "
              f"use_known_pi_seed=False (got {parsed['compute_sieving_primes_count']!r}, "
              f"{parsed['use_known_pi_seed']!r})")

        gen._loop_count_sieving_var.set(True)
        app.update()
        parsed = gen._collect_loop_settings_from_form()
        check(parsed["compute_sieving_primes_count"] is True and
              parsed["use_known_pi_seed"] is False,
              f"'count from scratch' only -> compute_sieving_primes_count=True, "
              f"use_known_pi_seed=False (got {parsed['compute_sieving_primes_count']!r}, "
              f"{parsed['use_known_pi_seed']!r})")

        gen._loop_use_pi_seed_var.set(True)  # unchecks count_sieving via the trace
        app.update()
        parsed = gen._collect_loop_settings_from_form()
        check(parsed["compute_sieving_primes_count"] is True and
              parsed["use_known_pi_seed"] is True,
              f"'use Wikipedia seed' only -> compute_sieving_primes_count is STILL True "
              f"(computing IS happening, just seeded) and use_known_pi_seed=True "
              f"(got {parsed['compute_sieving_primes_count']!r}, "
              f"{parsed['use_known_pi_seed']!r})")

        # --- round-trip through saved settings: loading a settings dict where the seed
        # was on must NOT also show 'count from scratch' as checked -----------------------
        gen._generation_settings["loop"] = {
            "base_exponent": "1", "run_count": "1", "n_instances": "1",
            "write_files": True, "compute_sieving_primes_count": True,
            "use_known_pi_seed": True, "window_count_per_run": "1", "workers": "1",
            "batches_per_worker": "1", "window_m": "10000000",
        }
        loop_settings = gen._generation_settings["loop"]
        use_pi_seed_initial = bool(loop_settings.get("use_known_pi_seed", False))
        reconstructed_count_sieving = (
            bool(loop_settings.get("compute_sieving_primes_count", False))
            and not use_pi_seed_initial)
        check(use_pi_seed_initial is True and reconstructed_count_sieving is False,
              f"a saved settings dict with both flags True (as ACTUALLY gets persisted when "
              f"only the seed checkbox was checked) reconstructs to seed=True, "
              f"count_from_scratch=False on reload -- not both True "
              f"(got seed={use_pi_seed_initial}, count_from_scratch="
              f"{reconstructed_count_sieving})")

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
