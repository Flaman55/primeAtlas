"""TargetPlannerSection: the Generation tab's target planner (target_planner_view.py) wired to
the planner (target_planner.py), its costs (target_plan_costs.py) and Quick-gen.

Plan uses the engine selected in the Generation form, its per-run cap lowered to the RAM
budget (run_ram.max_windows_in_budget, as the width proposal), the windows of that engine's
store as already done, and the benchmark log the engine proposal reads. Use writes one group
into Quick-gen: an Atlas group into Floor mode (Start = the group's first number, which
also sets the Floor; Width; storage writing on, the planner's purpose being stored
primes), a Pseudosquares group into Pseudosquares mode with print. Nothing starts a run.

A GenerationTab mixin: it uses the widgets, Variables and advice state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
from tkinter import filedialog, messagebox

import storage_kinds

from . import engine_options, run_ram, target_plan_costs, target_planner
from .target_plan_text import errors_text, row_values, summary_text
from .target_planner_view import TargetPlannerView
from .time_simulation_window import format_long_duration
from .window_planning import QUICK_FLOOR_MAX, QUICK_GEN_MAX_WINDOW_WIDTH

MAX_NUMBER = 10 ** (QUICK_FLOOR_MAX + 1) - 1


class TargetPlannerSection:
    def _build_target_planner_section(self, sections):
        view = TargetPlannerView(sections, self.T, self._plan_targets, self._load_targets,
                                 self._use_target_group)
        view.pack(fill="x")
        self._target_planner_view = view

    def _target_atlas_cap(self, engine):
        """The widest Atlas run: the engine's per-run cap, lowered to the RAM budget."""
        fields = self._engine_fields
        engine_cap = engine_options.max_windows_per_run(engine)
        cap = run_ram.max_windows_in_budget(
            lambda w: fields.choice_for_engine(engine, w), self._advice_free_ram, engine_cap,
            QUICK_GEN_MAX_WINDOW_WIDTH)
        return engine_cap if cap is None else cap

    def _plan_targets(self, text):
        view = self._target_planner_view
        T = self.T
        parsed = target_planner.parse_targets(text, MAX_NUMBER)
        if parsed.errors:
            view.show_message(T("target_planner.errors_header") + "\n"
                              + errors_text(parsed.errors, T))
            return
        if not parsed.targets:
            view.show_message(T("target_planner.no_targets"))
            return
        engine = self._engine_fields.engine()
        costs = target_plan_costs.make_costs(self._advice_samples, engine, self._advice_pt1_b())
        cap = self._target_atlas_cap(engine)
        atlas = costs.atlas
        if cap <= 0:
            # Not one window fits the RAM budget: no Atlas run, and the blocks stay uncut.
            atlas, cap = (lambda floor, idx, windows: None), engine_options.max_windows_per_run(
                engine)
        portal = self._get_portal_folder()

        def stored(floor):
            return storage_kinds.engine_target_idxs(portal, floor, QUICK_GEN_MAX_WINDOW_WIDTH,
                                                    engine)

        plan = target_planner.plan_targets(parsed.targets, QUICK_GEN_MAX_WINDOW_WIDTH, stored,
                                           lambda floor: cap, atlas, costs.pss)
        if not plan.groups and plan.unplanned:
            view.show_message(T("target_planner.no_time_model"))
            return

        def duration(seconds):
            return format_long_duration(seconds, T)

        rows = [row_values(n, g, T, duration) for n, g in enumerate(plan.groups, start=1)]
        view.show_plan(plan.groups, rows, summary_text(plan, costs, T, duration))

    def _load_targets(self):
        path = filedialog.askopenfilename(
            title=self.T("target_planner.load_title"),
            filetypes=[("Text", "*.txt *.csv"), ("*", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as error:
            messagebox.showerror(self.T("gen.dialog_title"),
                                 self.T("target_planner.load_failed", error=error))
            return
        self._target_planner_view.set_text(text.rstrip("\n"))

    def _use_target_group(self, group):
        if group.method == target_planner.METHOD_ATLAS:
            self.quick_mode_var.set("floor")
            self._on_quick_mode_changed()
            self.quick_floor_start_var.set(str(group.lo))
            self.quick_floor_width_var.set(str(group.windows))
            self._loop_write_files_var.set(True)
            return
        self.quick_mode_var.set("pseudosquares")
        self._on_quick_mode_changed()
        self.quick_pseudosquares_mode_var.set("print")
        self.quick_pseudosquares_floor_var.set(str(group.floor))
        self.quick_pseudosquares_from_var.set(str(group.lo))
        self.quick_pseudosquares_width_var.set(str(group.windows))
