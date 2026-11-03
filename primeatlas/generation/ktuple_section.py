"""
ktuple_section.py -- KtupleSection, Section C of the Generation tab: the
ktuple_sieve_v2_1.py form (pattern, strategy, Advanced fields), its console, and the
Run/Auto/Stop/finish handlers.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import queue

import tkinter as tk
from tkinter import ttk, messagebox
import pattern_catalog_v1

from .generation_console import GenerationConsole
from .engine_argv import build_ktuple_sieve_argv
from .generation_settings import _KTUPLE_STRATEGY_KEYS, save_generation_settings
from .window_planning import recommended_digit_sweep_n_locations
from .wsl_command import generation_log_paths, build_wsl_logged_command


class KtupleSection:
    def _build_ktuple_section(self, sections):
        """Section C: the k-tuple sieve form, its Run/Auto/Stop row and its console."""
        # --- Section C: ktuple_sieve_v2_1.py (targeted k-tuple candidate sieve) -----
        # Complementary to Section B: that one pattern-matches against windows
        # already fully sieved by prime_sieve; this one hunts a single, sparse
        # pattern (e.g. k=15) directly, via a residue wheel + trial division +
        # Miller-Rabin, across scattered window locations -- see ktuple_sieve_v2_1.py's
        # own module docstring for why that's a fundamentally different (and, for a
        # sparse-enough pattern, far cheaper) approach than fully sieving a wide
        # enough span for Section B to find the same thing.
        ktuple_outer = ttk.Labelframe(sections, text=self.T("gen.section_ktuple"))
        ktuple_outer.pack(fill="x", pady=(6, 0))

        ktuple_settings = self._generation_settings["ktuple"]

        ktuple_pattern_row = ttk.Frame(ktuple_outer)
        ktuple_pattern_row.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(ktuple_pattern_row, text=self.T("gen.ktuple_field_k")).pack(side="left")
        self._ktuple_k_values = pattern_catalog_v1.all_k()
        self.ktuple_k_combo = ttk.Combobox(
            ktuple_pattern_row, state="readonly", width=6,
            values=[str(k) for k in self._ktuple_k_values])
        self.ktuple_k_combo.pack(side="left", padx=(6, 16))
        self.ktuple_k_combo.bind("<<ComboboxSelected>>", self._on_ktuple_k_changed)

        ttk.Label(ktuple_pattern_row, text=self.T("gen.ktuple_field_variant")).pack(side="left")
        self._ktuple_variants = []
        self.ktuple_variant_combo = ttk.Combobox(ktuple_pattern_row, state="readonly", width=10)
        self.ktuple_variant_combo.pack(side="left", padx=(6, 0))
        self.ktuple_variant_combo.bind(
            "<<ComboboxSelected>>", self._on_ktuple_variant_changed)

        self.ktuple_pattern_info_var = tk.StringVar(value="")
        ttk.Label(ktuple_outer, textvariable=self.ktuple_pattern_info_var,
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=8, pady=(0, 4))

        ktuple_form = ttk.Frame(ktuple_outer)
        ktuple_form.pack(fill="x", padx=8, pady=(0, 4))

        self._ktuple_vars = {}

        def add_ktuple_field(row, col, key, label, width=10):
            ttk.Label(ktuple_form, text=label).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(ktuple_settings.get(key, "")))
            ttk.Entry(ktuple_form, textvariable=var, width=width).grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
            self._ktuple_vars[key] = var

        add_ktuple_field(0, 0, "base_exponent", self.T("gen.ktuple_field_base_exponent"))
        add_ktuple_field(0, 1, "n_locations", self.T("gen.ktuple_field_n_locations"))
        # Auto button: recommended_digit_sweep_n_locations()'s own suggestion --
        # see _on_ktuple_n_locations_auto_clicked()'s docstring for why this
        # exists (a shared n_locations field left digit_sweep's per-branch depth
        # much thinner than intended). Occupies the free grid slot right
        # after n_locations's own entry (columns 2/3), same "Auto button right
        # next to the field it fills" placement as the loop pipeline's own
        # workers Auto button above.
        ttk.Button(ktuple_form, text=self.T("quick.auto_button"), width=6,
                   command=self._on_ktuple_n_locations_auto_clicked).grid(
            row=0, column=4, sticky="w", padx=(0, 8), pady=2)
        add_ktuple_field(1, 0, "window_m", self.T("gen.ktuple_field_window_m"), width=14)

        ttk.Label(ktuple_form, text=self.T("gen.ktuple_field_strategy")).grid(
            row=1, column=2, sticky="w", padx=(0, 4), pady=2)
        self.ktuple_strategy_combo = ttk.Combobox(
            ktuple_form, state="readonly", width=16,
            values=[self.T("gen.ktuple_strategy_even"), self.T("gen.ktuple_strategy_concentrated"),
                    self.T("gen.ktuple_strategy_manual_list"), self.T("gen.ktuple_strategy_manual_step"),
                    self.T("gen.ktuple_strategy_digit_sweep")])
        self.ktuple_strategy_combo.grid(row=1, column=3, sticky="w", padx=(0, 20), pady=2)
        _saved_strategy = ktuple_settings.get("strategy", "concentrated")
        self.ktuple_strategy_combo.current(
            _KTUPLE_STRATEGY_KEYS.index(_saved_strategy)
            if _saved_strategy in _KTUPLE_STRATEGY_KEYS else 1)

        # "step": optional override for even/concentrated (both auto-compute their
        # own step otherwise -- see ktuple_locations_v2_1.step_for_even()/
        # step_for_concentrated()), REQUIRED for manual_step. Visible in the
        # primary form (not tucked behind Advanced) since it's central to how
        # every non-manual_list strategy now behaves -- see the checkpoint/step
        # design, which avoids every Run re-scanning the same locations with
        # nothing persisted in between.
        add_ktuple_field(2, 0, "step", self.T("gen.ktuple_field_step"), width=14)

        ktuple_advanced_row = ttk.Frame(ktuple_outer)
        ktuple_advanced_row.pack(fill="x", padx=8)
        self._ktuple_advanced_visible = False
        self.ktuple_advanced_toggle_btn = ttk.Button(
            ktuple_advanced_row, text=self.T("gen.advanced_show"),
            command=self._on_toggle_ktuple_advanced)
        self.ktuple_advanced_toggle_btn.pack(side="left")

        ktuple_advanced_content = ttk.Frame(ktuple_outer)
        self._ktuple_advanced_content = ktuple_advanced_content
        # NOT packed here -- starts collapsed, see _on_toggle_ktuple_advanced().

        ktuple_advanced_form = ttk.Frame(ktuple_advanced_content)
        ktuple_advanced_form.pack(fill="x")

        def add_ktuple_advanced_field(row, col, key, label, width=10):
            ttk.Label(ktuple_advanced_form, text=label).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(ktuple_settings.get(key, "")))
            ttk.Entry(ktuple_advanced_form, textvariable=var, width=width).grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
            self._ktuple_vars[key] = var

        add_ktuple_advanced_field(
            0, 0, "fragment_width", self.T("gen.ktuple_field_fragment_width"), width=18)
        add_ktuple_advanced_field(
            0, 1, "fragment_start", self.T("gen.ktuple_field_fragment_start"), width=18)
        add_ktuple_advanced_field(1, 0, "deep_prime_limit", self.T("gen.ktuple_field_deep_prime_limit"))
        add_ktuple_advanced_field(1, 1, "mr_rounds", self.T("gen.ktuple_field_mr_rounds"))
        # pass_counter: strategy=digit_sweep only -- the starting pass number (only
        # used the first time, before any checkpoint exists -- default 0). Each pass
        # sweeps the whole floor
        # once more with every drilled position committing to a DIFFERENT digit
        # than the pass before (a different rate per position, so the explored path
        # looks scrambled/varied rather than a single repeated digit -- see
        # ktuple_locations_v2_1.py's digit_sweep_locations() PATH VARIETY note). Kept in
        # Advanced alongside the other rarely-touched fields since the default
        # is already the intended starting value.
        add_ktuple_advanced_field(2, 0, "pass_counter", self.T("gen.ktuple_field_pass_counter"))
        ttk.Label(ktuple_advanced_form, text=self.T("gen.ktuple_field_manual_offsets")).grid(
            row=3, column=0, sticky="w", padx=(0, 4), pady=2)
        _manual_offsets_var = tk.StringVar(value=str(ktuple_settings.get("manual_offsets", "")))
        ttk.Entry(ktuple_advanced_form, textvariable=_manual_offsets_var, width=50).grid(
            row=3, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=2)
        self._ktuple_vars["manual_offsets"] = _manual_offsets_var

        ktuple_btn_row = ttk.Frame(ktuple_outer)
        ktuple_btn_row.pack(fill="x", padx=8, pady=(4, 4))
        self.ktuple_run_btn = ttk.Button(
            ktuple_btn_row, text=self.T("common.run"),
            command=lambda: self._launch_ktuple(auto=False))
        self.ktuple_run_btn.pack(side="left")
        # "Auto": same launch path as Run, only auto=True differs -- keeps looping
        # batch after batch (checkpointing after each, see ktuple_sieve_v2_1.
        # run_ktuple_job()'s own docstring) inside the SAME WSL process until a
        # confirmed hit, Stop, or the floor is exhausted, rather than requiring a
        # fresh Run click per batch.
        self.ktuple_auto_btn = ttk.Button(
            ktuple_btn_row, text=self.T("gen.ktuple_auto_button"),
            command=lambda: self._launch_ktuple(auto=True))
        self.ktuple_auto_btn.pack(side="left", padx=(6, 0))
        self.ktuple_stop_btn = ttk.Button(
            ktuple_btn_row, text=self.T("common.stop"), command=self._on_stop_ktuple,
            state="disabled")
        self.ktuple_stop_btn.pack(side="left", padx=(6, 0))
        self.ktuple_status_label = tk.StringVar(value=self.T("common.ready"))
        ttk.Label(ktuple_btn_row, textvariable=self.ktuple_status_label).pack(
            side="left", padx=(12, 0))

        # Reset-checkpoint: a plain checkbox rather than its own button/action --
        # checked, it adds --reset-checkpoint to whichever of Run/Auto is clicked
        # next (see _launch_ktuple), so resetting never needs its own separate WSL
        # round trip just to delete one small text file. Left checked afterward
        # (not auto-unchecked) -- deliberately, so a person who wants to restart a
        # SEQUENCE of runs from scratch doesn't have to re-check it before every
        # click.
        self._ktuple_reset_checkpoint_var = tk.BooleanVar(
            value=bool(ktuple_settings.get("reset_checkpoint", False)))
        ttk.Checkbutton(
            ktuple_outer, text=self.T("gen.ktuple_check_reset_checkpoint"),
            variable=self._ktuple_reset_checkpoint_var).pack(anchor="w", padx=8, pady=(0, 4))

        self.ktuple_console = GenerationConsole(
            ktuple_outer, self.T, height=20)
        self.ktuple_output = self.ktuple_console.text
        self._register_scroll_exclude(self.ktuple_console.text.frame)

        self._ktuple_runner = None
        self._ktuple_output_queue = queue.Queue()

        if self._ktuple_k_values:
            _saved_k = ktuple_settings.get("k", "")
            try:
                _saved_k_int = int(_saved_k) if _saved_k else None
            except ValueError:
                _saved_k_int = None
            self.ktuple_k_combo.current(
                self._ktuple_k_values.index(_saved_k_int)
                if _saved_k_int in self._ktuple_k_values else 0)
            self._on_ktuple_k_changed(restore_variant_id=ktuple_settings.get("variant_id"))

    def _on_ktuple_k_changed(self, _event=None, restore_variant_id=None):
        """Repopulates the variant combo for whichever k is now selected -- same
        two-combo cascade as the Constellation calculator tab's own
        _on_const_calc_k_changed(). `restore_variant_id`, given only on initial
        build (see _build_ktuple_section()'s own call), re-selects a persisted
        variant instead of always defaulting to index 0, so the form reopens showing
        whatever pattern was last used here."""
        k_str = self.ktuple_k_combo.get()
        if not k_str:
            return
        self._ktuple_variants = pattern_catalog_v1.patterns_for_k(int(k_str))
        self.ktuple_variant_combo.configure(
            values=[self.T("const_calc.variant_label", id=w["id"])
                    for w in self._ktuple_variants])
        if self._ktuple_variants:
            idx = 0
            if restore_variant_id not in (None, ""):
                for i, w in enumerate(self._ktuple_variants):
                    if str(w["id"]) == str(restore_variant_id):
                        idx = i
                        break
            self.ktuple_variant_combo.current(idx)
        else:
            self.ktuple_variant_combo.set("")
        self._on_ktuple_variant_changed()

    def _on_ktuple_variant_changed(self, _event=None):
        idx = self.ktuple_variant_combo.current()
        if idx < 0 or idx >= len(self._ktuple_variants):
            self.ktuple_pattern_info_var.set("")
            return
        w = self._ktuple_variants[idx]
        offsets_str = ", ".join(str(o) for o in w["offsets"])
        if w["record_digits"] is not None:
            self.ktuple_pattern_info_var.set(self.T(
                "const_calc.pattern_info", offsets=offsets_str,
                record_digits=w["record_digits"], discoverer=w["discoverer"],
                date=w["date"]))
        else:
            self.ktuple_pattern_info_var.set(
                self.T("const_calc.pattern_info_untracked", offsets=offsets_str))

    def _on_ktuple_n_locations_auto_clicked(self):
        """Auto button for the shared "n_locations" field -- primarily meant for
        strategy=digit_sweep (see recommended_digit_sweep_n_locations()'s own
        docstring for why it exists: the field is shared across all five
        strategies, so a single static default couldn't fit digit_sweep's
        per-branch-depth needs without either being far too small for it or far
        too large for the other four). Reads base_exponent/window_m straight from
        their own fields (both already on screen, no WSL round-trip needed --
        unlike _on_workers_auto_clicked's CPU probe, this is pure arithmetic), and
        fills n_locations with the recommendation. Like every other Auto button in
        this app, only ever SUGGESTS a value -- the field stays freely editable
        afterward."""
        base_exponent_str = self._ktuple_vars["base_exponent"].get().strip()
        window_m_str = self._ktuple_vars["window_m"].get().strip()
        if not base_exponent_str.isdigit() or not window_m_str.isdigit():
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.error_base_exponent_int"))
            return
        base_exponent = int(base_exponent_str)
        window_m = int(window_m_str)
        recommended = recommended_digit_sweep_n_locations(base_exponent, window_m)
        self._ktuple_vars["n_locations"].set(str(recommended))
        numbers_total = recommended * window_m
        messagebox.showinfo(self.T("quick.dialog_title"), self.T(
            "gen.ktuple_auto_n_locations_result",
            recommended=f"{recommended:,}", numbers_total=f"{numbers_total:,}"))

    def _on_toggle_ktuple_advanced(self):
        """Same show/hide-together idiom as _on_toggle_loop_advanced() -- see that
        method's own docstring."""
        if self._ktuple_advanced_visible:
            self._ktuple_advanced_content.pack_forget()
            self._ktuple_advanced_visible = False
            self.ktuple_advanced_toggle_btn.configure(text=self.T("gen.advanced_show"))
        else:
            self._ktuple_advanced_content.pack(
                fill="x", padx=8, pady=(0, 4), before=self.ktuple_console.toggle_row)
            self._ktuple_advanced_visible = True
            self.ktuple_advanced_toggle_btn.configure(text=self.T("gen.advanced_hide"))

    def _show_ktuple_terminal(self):
        self.ktuple_console.show()

    def _launch_ktuple(self, auto):
        """Shared by both the Run button (auto=False -- one batch, checkpointed,
        per click) and the Auto button (auto=True -- ktuple_sieve_v2_1.py itself
        keeps looping batch after batch inside this one WSL process until a
        confirmed hit, Stop, or the floor is exhausted -- see
        ktuple_sieve_v2_1.run_ktuple_job()'s own docstring). Everything below the
        auto-specific argv flag is identical between the two."""
        if self._ktuple_runner is not None and self._ktuple_runner.is_running():
            return
        # See _other_engine_is_running()'s own docstring -- backstop for a
        # non-button call path, same reasoning as _on_run_constellation()'s own.
        if self._other_engine_is_running("ktuple"):
            return
        base_exponent = self._ktuple_vars["base_exponent"].get().strip()
        if not base_exponent.isdigit():
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.error_base_exponent_int"))
            return

        k_idx = self.ktuple_k_combo.current()
        variant_idx = self.ktuple_variant_combo.current()
        if k_idx < 0 or variant_idx < 0 or variant_idx >= len(self._ktuple_variants):
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_no_pattern"))
            return
        pattern = self._ktuple_variants[variant_idx]

        n_locations = self._ktuple_vars["n_locations"].get().strip()
        window_m = self._ktuple_vars["window_m"].get().strip()
        step = self._ktuple_vars["step"].get().strip()
        fragment_width = self._ktuple_vars["fragment_width"].get().strip()
        fragment_start = self._ktuple_vars["fragment_start"].get().strip() or "0"
        deep_prime_limit = self._ktuple_vars["deep_prime_limit"].get().strip() or "2000"
        mr_rounds = self._ktuple_vars["mr_rounds"].get().strip() or "40"
        manual_offsets_str = self._ktuple_vars["manual_offsets"].get().strip()
        pass_counter = self._ktuple_vars["pass_counter"].get().strip() or "0"

        numeric_ok = (
            n_locations.isdigit() and window_m.isdigit() and fragment_start.isdigit()
            and deep_prime_limit.isdigit() and mr_rounds.isdigit() and pass_counter.isdigit()
            and (not fragment_width or fragment_width.isdigit())
            and (not step or step.isdigit()))
        if not numeric_ok:
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_numeric_fields"))
            return

        strategy_idx = self.ktuple_strategy_combo.current()
        strategy = (_KTUPLE_STRATEGY_KEYS[strategy_idx]
                    if 0 <= strategy_idx < len(_KTUPLE_STRATEGY_KEYS) else "concentrated")

        manual_offsets = None
        if strategy == "manual_list":
            try:
                manual_offsets = [int(tok) for tok in manual_offsets_str.replace(",", " ").split()]
            except ValueError:
                manual_offsets = []
            if not manual_offsets:
                messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_manual_offsets"))
                return
        elif strategy == "manual_step" and not step:
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_manual_step_needs_step"))
            return

        reset_checkpoint = self._ktuple_reset_checkpoint_var.get()

        self._generation_settings["ktuple"] = {
            "base_exponent": base_exponent, "k": str(pattern["k"]),
            "variant_id": str(pattern["id"]), "n_locations": n_locations,
            "window_m": window_m, "strategy": strategy, "step": step,
            "fragment_width": fragment_width, "fragment_start": fragment_start,
            "manual_offsets": manual_offsets_str, "deep_prime_limit": deep_prime_limit,
            "mr_rounds": mr_rounds, "reset_checkpoint": reset_checkpoint,
            "pass_counter": pass_counter,
        }
        save_generation_settings(self._get_portal_folder(), self._generation_settings)

        argv = build_ktuple_sieve_argv(
            base_exponent, pattern["k"], pattern["id"],
            n_locations=int(n_locations), window_m=int(window_m), strategy=strategy,
            step=int(step) if step else None,
            fragment_width=int(fragment_width) if fragment_width else None,
            fragment_start=int(fragment_start) if strategy != "manual_list" else None,
            manual_offsets=manual_offsets, deep_prime_limit=int(deep_prime_limit),
            mr_rounds=int(mr_rounds), auto=auto, reset_checkpoint=reset_checkpoint,
            pass_counter=int(pass_counter) if strategy == "digit_sweep" else None)
        log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "ktuple")
        cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

        self.ktuple_console.append(self._new_run_separator())
        self._ktuple_output_queue = queue.Queue()
        self._ktuple_runner = self._new_wsl_runner(
            cmd, log_path, exit_path, self._ktuple_output_queue,
            kill_pattern="ktuple_sieve_v2_1.py")
        self._ktuple_runner.start()
        self.ktuple_run_btn.configure(state="disabled")
        self.ktuple_auto_btn.configure(state="disabled")
        self.ktuple_stop_btn.configure(state="normal")
        self._lock_other_run_buttons("ktuple")
        self.ktuple_status_label.set(self.T("common.running"))
        self._show_ktuple_terminal()

    def _on_stop_ktuple(self):
        if self._ktuple_runner is not None:
            self._ktuple_runner.stop()
            self.ktuple_status_label.set(self.T("common.stopping"))

    def _on_ktuple_finished(self, _returncode=None):
        """Mirrors _on_constellation_finished() -- confirmed hits land in the same
        per-(k,variant) hit files Section B writes to, so the Constellations tab
        needs the same post-run refresh. _drain_output_queue() only knows about
        the plain run_btn/stop_btn pair shared with every other section, not this
        section's own extra Auto button or the other two engines' own Run
        buttons, so _unlock_other_run_buttons() below resets all of those instead
        (auto=True's own internal batch-after-batch looping happens inside this
        ONE WSL process -- see _launch_ktuple()'s own docstring -- so this exit
        always means the whole ktuple session is genuinely over, same reasoning
        as _on_loop_finished's own unconditional unlock)."""
        self.reload_constellations_tree()
        self._unlock_other_run_buttons()

    def _poll_ktuple_output(self):
        self._drain_output_queue(self._ktuple_output_queue, self.ktuple_console,
                                  self.ktuple_run_btn, self.ktuple_stop_btn,
                                  self.ktuple_status_label,
                                  on_exit=self._on_ktuple_finished)
        self.after(150, self._poll_ktuple_output)
