"""
test_ui_state_app.py -- remembered form fields across a restart of the real app.

Builds the app on a temp storage folder with the remembered-fields store on a temp file,
changes fields on every remembering tab (Quick-gen, the Generation forms without pressing
Run, Research, Constellations, Primality, the primesieve calculator, Benchmark), closes
the app and builds it again on the same file. Checks: every changed field comes back,
including a translated drop-down by id and a mode / preset / operation whose dependent
frame shows again; Quick-gen's starting point and the k-tuple reset-checkpoint box are not
remembered; closing flushes a pending write. Migration: a storage folder's
.portal_generation_settings.json fills an empty store once (without reset_checkpoint), and
is not read again, nor is another storage folder's file. Windows, real display:
    python unitTests/test_ui_state_app.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _build_app(portal, state_path):
    from app_sandbox import isolate_app
    from primeatlas.core import ui_state_dynamic
    from primeatlas.core.ui_state import UiStateStore
    prime_atlas_v2, _portal = isolate_app(portal)
    ui_state_dynamic.STORE = UiStateStore(state_path)
    app = prime_atlas_v2._build_gui()()
    app.update()
    return app


def _type(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


def check_migration(work):
    from primeatlas.core.ui_state import UiStateStore
    from primeatlas.generation import generation_settings as gs
    portal = os.path.join(work, "portal_legacy")
    os.makedirs(portal)
    with open(os.path.join(portal, gs.GENERATION_SETTINGS_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"loop": {"workers": "7", "engine": "v5"},
                   "ktuple": {"base_exponent": "31", "reset_checkpoint": True}}, f)
    state_path = os.path.join(work, "migrated_ui_state.json")
    app = _build_app(portal, state_path)
    passed = True
    try:
        gen = app.generation_tab_widget
        passed &= check(gen._loop_vars["workers"].get() == "7"
                        and gen._engine_fields.engine_var.get() == "v5",
                        "the storage folder's legacy file fills the pipeline form")
        passed &= check(gen._ktuple_vars["base_exponent"].get() == "31",
                        "... and the k-tuple form")
        passed &= check(gen._ktuple_reset_checkpoint_var.get() is False,
                        "a legacy reset_checkpoint=true is not carried over")
    finally:
        app.destroy()
    with open(state_path, encoding="utf-8") as f:
        saved = json.load(f)
    passed &= check(saved.get(gs.MIGRATED_KEY) is True
                    and "generation.ktuple.reset_checkpoint" not in saved,
                    "the store marks the migration done and holds no reset_checkpoint")

    with open(os.path.join(portal, gs.GENERATION_SETTINGS_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"loop": {"workers": "9"}}, f)
    other = os.path.join(work, "portal_other")
    os.makedirs(other)
    with open(os.path.join(other, gs.GENERATION_SETTINGS_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"loop": {"workers": "5"}}, f)
    store = UiStateStore(state_path)
    passed &= check(gs.load_generation_settings(store, portal)["loop"]["workers"] == "7"
                    and gs.load_generation_settings(store, other)["loop"]["workers"] == "7",
                    "after the migration no legacy file is read again")
    return passed


def check_restart(work):
    portal = os.path.join(work, "portal")
    os.makedirs(portal)
    state_path = os.path.join(work, "ui_state.json")
    passed = True

    app = _build_app(portal, state_path)
    try:
        gen = app.generation_tab_widget
        T = gen.T
        gen.quick_mode_var.set("explore")
        gen._on_quick_mode_changed()
        gen.quick_explore_floor_var.set("23")
        gen.quick_explore_width_var.set("250")
        gen.quick_floor_start_var.set("10**21")
        gen.quick_hybrid_target_var.set(T("quick.hybrid_target_fill_gap"))
        gen._loop_vars["workers"].set("12")
        gen._engine_fields.engine_var.set("v5")
        gen._const_base_exponent_var.set("18")
        gen._ktuple_vars["base_exponent"].set("30")
        gen.ktuple_strategy_combo.current(4)
        gen._ktuple_reset_checkpoint_var.set(True)

        gaps = app.research_gaps_tab_widget
        gaps.gaps_overlay_combo.current(1)
        _type(gaps.gaps_n_to_entry, "777")
        gaps.gaps_source_var.set("storage")
        squares = app.research_squares_tab_widget
        custom = list(squares._current_preset_id.__globals__["_PRESET_IDS"]).index("custom")
        squares.squares_preset_combo.current(custom)
        squares._on_squares_preset_changed()
        _type(squares.squares_required_count_entry, "3")
        poly = app.research_polynomials_tab_widget
        _type(poly.poly_custom_formula_entry, "n**2 + n + 17")

        primality = app.primality_tab_widget
        _type(primality.primality_number_entry, "97")
        primality.primality_use_sympy_var.set(False)
        calc = app.primesieve_calc_tab_widget
        calc.primesieve_calc_op_combo.current(1)
        calc._on_primesieve_calc_operation_changed()
        _type(calc.primesieve_calc_n_entry, "50")
        app.benchmark_tab_widget.log_scale_var.set(True)

        const_calc = app.constellations_calc_tab_widget
        const_calc.k_combo.current(1)
        const_calc._on_k_changed()
        last_variant = len(const_calc._variants) - 1
        const_calc.variant_combo.current(last_variant)
        const_calc._on_variant_changed()
        chosen = (const_calc.k_combo.get(), const_calc.variant_combo.get())
        _type(const_calc.exp_entry, "20")
        _type(app.constellations_records_tab_widget.floor_from_entry, "12")
        app.update()
    finally:
        app.destroy()

    with open(state_path, encoding="utf-8") as f:
        saved = json.load(f)
    passed &= check(saved.get("quick.explore_floor") == "23" and saved.get("quick.mode") == "explore",
                    "closing the app writes the pending changes")
    passed &= check("quick.floor_start" not in saved, "Quick-gen's starting point is not stored")
    passed &= check(saved.get("quick.hybrid_target") == "fill_gap",
                    f"a translated drop-down is stored by id ({saved.get('quick.hybrid_target')!r})")
    passed &= check(saved.get("generation.ktuple.strategy") == "digit_sweep"
                    and "generation.ktuple.reset_checkpoint" not in saved,
                    "k-tuple strategy stored by key, reset checkpoint not stored")

    app = _build_app(portal, state_path)
    try:
        gen = app.generation_tab_widget
        T = gen.T
        passed &= check(gen.quick_mode_var.get() == "explore"
                        and gen.quick_hint_var.get() == T("quick.hint_explore"),
                        "Quick-gen mode and its hint come back")
        passed &= check(gen.quick_explore_floor_var.get() == "23"
                        and gen.quick_explore_width_var.get() == "250",
                        "Quick-gen fields come back")
        passed &= check(gen.quick_floor_start_var.get() == "" and gen.quick_floor_var.get() == "21"
                        and all(str(p["floor_entry"].cget("state")) == "normal"
                                for p in gen._quick_panels),
                        "the starting point starts blank; the Floor it filled stays, editable")
        passed &= check(gen.quick_hybrid_target_var.get() == T("quick.hybrid_target_fill_gap"),
                        "the Hybrid target comes back")
        passed &= check(gen._loop_vars["workers"].get() == "12"
                        and gen._engine_fields.engine_var.get() == "v5",
                        "pipeline form values come back without a Run")
        passed &= check(gen._const_base_exponent_var.get() == "18"
                        and gen._ktuple_vars["base_exponent"].get() == "30"
                        and gen.ktuple_strategy_combo.current() == 4,
                        "constellation and k-tuple forms come back")
        passed &= check(gen._ktuple_reset_checkpoint_var.get() is False,
                        "the reset-checkpoint box starts unchecked")

        gaps = app.research_gaps_tab_widget
        passed &= check(gaps.gaps_overlay_combo.current() == 1 and gaps.gaps_n_to_entry.get() == "777"
                        and gaps.gaps_source_var.get() == "storage", "Research gaps fields come back")
        squares = app.research_squares_tab_widget
        passed &= check(squares._current_preset_id() == "custom"
                        and squares.squares_custom_frame.winfo_manager() != ""
                        and squares.squares_required_count_entry.get() == "3",
                        "squares preset, its custom fields and the required count come back")
        passed &= check(app.research_polynomials_tab_widget.poly_custom_formula_entry.get()
                        == "n**2 + n + 17", "polynomial formula comes back")
        primality = app.primality_tab_widget
        passed &= check(primality.primality_number_entry.get() == "97"
                        and primality.primality_use_sympy_var.get() is False,
                        "Primality fields come back")
        calc = app.primesieve_calc_tab_widget
        passed &= check(calc.primesieve_calc_op_combo.current() == 1
                        and calc._primesieve_calc_nth_frame.winfo_manager() == "grid"
                        and calc._primesieve_calc_count_frame.winfo_manager() == ""
                        and calc.primesieve_calc_n_entry.get() == "50",
                        "primesieve calculator operation, its fields and values come back")
        passed &= check(app.benchmark_tab_widget.log_scale_var.get() is True,
                        "Benchmark log scale comes back")
        const_calc = app.constellations_calc_tab_widget
        passed &= check((const_calc.k_combo.get(), const_calc.variant_combo.get()) == chosen
                        and const_calc.exp_entry.get() == "20",
                        f"constellation calculator k, variant and floor come back ({chosen})")
        passed &= check(app.constellations_records_tab_widget.floor_from_entry.get() == "12",
                        "constellation records floor range comes back")
    finally:
        app.destroy()
    return passed


def main():
    from tkinter import messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    messagebox.showwarning = lambda *a, **k: None
    work = tempfile.mkdtemp(prefix="primeatlas_ui_state_app_test_")
    try:
        passed = check_migration(work)
        passed &= check_restart(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
