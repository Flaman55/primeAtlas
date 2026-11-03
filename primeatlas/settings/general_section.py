"""
general_section.py -- GeneralSection, the General sub-tab of Settings: the language and
theme pickers with their restart-to-apply guard, the ScrollPad width field, the
brightness/font-size (readability) fields, and the storage-path field.

A SettingsTab mixin: it uses the widgets, Variables and state that SettingsTab and its
other mixins set up, so it is never instantiated on its own.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ..core.app_settings import SCROLL_PAD_WIDTH_MAX, SCROLL_PAD_WIDTH_MIN
from ..core.theme import (BRIGHTNESS_DEFAULT, BRIGHTNESS_MAX, BRIGHTNESS_MIN, FONT_SCALE_DEFAULT,
                          FONT_SCALE_MAX, FONT_SCALE_MIN)
from ..core.widgets import set_scroll_pad_width
from .restore_job import STATUS_RUNNING
from ..core.i18n import Translator


class GeneralSection:
    # ---- language -----------------------------------------------------------------------

    def _on_language_selected(self, _event=None):
        label = self.language_var.get()
        code = self._language_codes_by_label.get(label)
        if code is None or code == self.app_settings.language:
            return
        self.app_settings.set_language(code)
        # The person changing language usually can't read the CURRENT one (that's why
        # they're switching) -- so if a restart has to be deferred (job running), that
        # notice has to speak the NEWLY chosen language, not self.T (still bound to the
        # language the app was launched with). A throwaway Translator for just this one
        # popup is cheap and doesn't touch self.T or rebuild any other widget.
        self._restart_now_or_warn(notice_translator=Translator(code).t)

    # ---- theme ----------------------------------------------------------------------

    def _on_theme_selected(self, _event=None):
        label = self.theme_var.get()
        code = self._theme_codes_by_label.get(label)
        if code is None or code == self.app_settings.theme:
            return
        self.app_settings.set_theme(code)
        # Unlike the language switch above, a deferred-restart notice can stay in
        # self.T's CURRENT language -- picking a theme doesn't affect what language
        # the person reads, so there's no need for language's throwaway-Translator
        # trick here.
        self._restart_now_or_warn(notice_translator=self.T)

    # ---- restart-to-apply (language/theme) ---------------------------------------------

    def _has_running_job(self):
        """True if restarting the process right now would silently kill in-progress work.
        Checks this tab's own jobs directly (it already tracks them) plus, via the
        is_any_job_running callback in wsl_helpers, the Generation tab's three runners --
        this tab has no direct reference to GenerationTab itself (see this module's own
        docstring on wsl_helpers), so that cross-tab check has to be threaded through from
        prime_atlas_v2.py the same way every other cross-tab capability here is."""
        if self._active_job is not None and self._active_job.status == STATUS_RUNNING:
            return True
        if self._full_backup_job_running:
            return True
        if self._storage_integrate_job_running:
            return True
        is_any_job_running = self.wsl.get("is_any_job_running")
        return bool(is_any_job_running and is_any_job_running())

    def _restart_now_or_warn(self, notice_translator):
        """Restarts PrimeAtlas immediately so the theme/language change just saved above
        actually takes effect -- UNLESS a background job is currently in flight somewhere
        in the app, in which case restarting would silently kill it; in that case fall
        back to a restart-required note instead of yanking the process out from under a
        running job.

        notice_translator is a T(key, **kwargs)-shaped callable -- self.T for the theme
        case, or a throwaway language-specific Translator.t for the language case (see the
        two call sites' own comments)."""
        if self._has_running_job():
            messagebox.showinfo(notice_translator("settings.dialog_title"),
                                 notice_translator("settings.restart_blocked_job_running"))
            return
        from .app_restart import restart_app
        # Deferred via after() rather than called synchronously so the combobox's own
        # <<ComboboxSelected>> event handler returns normally (and the AppSettings.save()
        # call above is fully flushed to disk) before the process gets replaced.
        self.after(150, restart_app)

    def _on_scroll_pad_width_changed(self, _event=None):
        """Applies the field live: saves the clamped width and resizes every ScrollPad.
        A non-integer entry is reverted to the saved width."""
        try:
            width = int(self.scroll_pad_width_var.get())
        except ValueError:
            self.scroll_pad_width_var.set(str(self.app_settings.scroll_pad_width))
            return
        self.app_settings.set_scroll_pad_width(width)
        width = self.app_settings.scroll_pad_width
        self.scroll_pad_width_var.set(str(width))
        set_scroll_pad_width(width)

    def _load_readability_fields(self):
        """Fills the brightness/font-size fields from the saved values (brightness of
        the current theme)."""
        background, text = self.app_settings.theme_brightness(self.app_settings.theme)
        self.background_brightness_var.set(str(background))
        self.text_brightness_var.set(str(text))
        self.font_scale_var.set(str(self.app_settings.font_scale))

    def _on_readability_apply(self):
        """Saves the brightness shifts (for the current theme) and the font size, then
        restarts like the theme switch -- both are applied once at startup. A
        non-integer entry reverts every field and saves nothing; unchanged values do not
        restart."""
        settings = self.app_settings
        try:
            background = int(self.background_brightness_var.get())
            text = int(self.text_brightness_var.get())
            font_scale = int(self.font_scale_var.get())
        except ValueError:
            self._load_readability_fields()
            return
        before = (settings.theme_brightness(settings.theme), settings.font_scale)
        settings.set_theme_brightness(settings.theme, background, text)
        settings.set_font_scale(font_scale)
        self._load_readability_fields()
        if (settings.theme_brightness(settings.theme), settings.font_scale) != before:
            self._restart_now_or_warn(notice_translator=self.T)

    def _on_readability_reset(self):
        self.background_brightness_var.set(str(BRIGHTNESS_DEFAULT))
        self.text_brightness_var.set(str(BRIGHTNESS_DEFAULT))
        self.font_scale_var.set(str(FONT_SCALE_DEFAULT))
        self._on_readability_apply()

    # ---- storage path -----------------------------------------------------------------

    def _path_status_text(self):
        return (self.T("settings.path_custom") if self.app_settings.is_custom
                else self.T("settings.path_default"))

    def _on_browse_path(self):
        chosen = filedialog.askdirectory(
            initialdir=self.path_var.get() or self.app_settings.default_storage_path,
            title=self.T("settings.path_browse_title"))
        if chosen:
            self.path_var.set(chosen)

    def _on_save_path(self):
        new_path = self.path_var.get().strip()
        if not new_path:
            messagebox.showerror(self.T("settings.dialog_title"),
                                  self.T("settings.path_empty_msg"))
            return
        self.app_settings.set_storage_path(new_path)
        self.wsl["set_portal_folder"](self.app_settings.storage_path)
        self.path_var.set(self.app_settings.storage_path)
        self.path_status_var.set(self._path_status_text())
        self._refresh_backup_list()
        self._scan_incomplete_restores()
        messagebox.showinfo(self.T("settings.dialog_title"),
                             self.T("settings.path_saved_msg", path=self.app_settings.storage_path))

    def _on_reset_path(self):
        self.app_settings.set_storage_path(None)
        self.wsl["set_portal_folder"](self.app_settings.storage_path)
        self.path_var.set(self.app_settings.storage_path)
        self.path_status_var.set(self._path_status_text())
        self._refresh_backup_list()
        self._scan_incomplete_restores()

    def _build_general_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        lang_frame = ttk.Labelframe(outer, text=self.T("settings.language_frame"))
        lang_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(lang_frame, text=self.T("settings.language_label")).grid(
            row=0, column=0, sticky="w", padx=6, pady=6)
        available = Translator.available_languages()
        self._language_codes_by_label = {label: code for code, label in available}
        self._language_labels_by_code = {code: label for code, label in available}
        current_label = self._language_labels_by_code.get(
            self.app_settings.language, self.app_settings.language)
        self.language_var = tk.StringVar(value=current_label)
        language_combo = ttk.Combobox(
            lang_frame, textvariable=self.language_var, state="readonly",
            values=[label for _code, label in available], width=20)
        language_combo.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=6)
        language_combo.bind("<<ComboboxSelected>>", self._on_language_selected)
        ttk.Label(lang_frame, text=self.T("settings.language_restart_note"),
                  style="Hint.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=6)

        # Theme picker -- same restart-required pattern as language above (see
        # prime_atlas_v2.py's PortalBrowserApp._apply_theme() docstring for why a
        # live re-theme of every already-built widget is a much larger, riskier
        # change than re-applying colors once at the next startup). Only two
        # options, so no need for language's available()-style discovery list --
        # the (code, label) pairs are just written out directly here.
        theme_frame = ttk.Labelframe(outer, text=self.T("settings.theme_frame"))
        theme_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(theme_frame, text=self.T("settings.theme_label")).grid(
            row=0, column=0, sticky="w", padx=6, pady=6)
        theme_options = [("light", self.T("settings.theme_light")),
                          ("dark", self.T("settings.theme_dark"))]
        self._theme_codes_by_label = {label: code for code, label in theme_options}
        self._theme_labels_by_code = {code: label for code, label in theme_options}
        current_theme_label = self._theme_labels_by_code.get(
            self.app_settings.theme, self._theme_labels_by_code["light"])
        self.theme_var = tk.StringVar(value=current_theme_label)
        theme_combo = ttk.Combobox(
            theme_frame, textvariable=self.theme_var, state="readonly",
            values=[label for _code, label in theme_options], width=20)
        theme_combo.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=6)
        theme_combo.bind("<<ComboboxSelected>>", self._on_theme_selected)
        ttk.Label(theme_frame, text=self.T("settings.theme_restart_note"),
                  style="Hint.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=6)

        ui_frame = ttk.Labelframe(outer, text=self.T("settings.ui_frame"))
        ui_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(ui_frame, text=self.T("settings.scroll_pad_width_label")).grid(
            row=0, column=0, sticky="w", padx=6, pady=6)
        self.scroll_pad_width_var = tk.StringVar(value=str(self.app_settings.scroll_pad_width))
        width_spin = ttk.Spinbox(
            ui_frame, textvariable=self.scroll_pad_width_var, from_=SCROLL_PAD_WIDTH_MIN,
            to=SCROLL_PAD_WIDTH_MAX, increment=4, width=6,
            command=self._on_scroll_pad_width_changed)
        width_spin.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=6)
        width_spin.bind("<Return>", self._on_scroll_pad_width_changed)
        width_spin.bind("<FocusOut>", self._on_scroll_pad_width_changed)
        ttk.Label(ui_frame, text=self.T("settings.scroll_pad_width_note",
                                        min=SCROLL_PAD_WIDTH_MIN, max=SCROLL_PAD_WIDTH_MAX),
                  style="Hint.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=6)

        # Brightness (per theme) and font size are applied once at startup, so they
        # are committed together by one Apply button instead of on every spin click.
        self.background_brightness_var = tk.StringVar()
        self.text_brightness_var = tk.StringVar()
        self.font_scale_var = tk.StringVar()
        readability_rows = (
            ("settings.background_brightness_label", self.background_brightness_var,
             BRIGHTNESS_MIN, BRIGHTNESS_MAX, 5),
            ("settings.text_brightness_label", self.text_brightness_var,
             BRIGHTNESS_MIN, BRIGHTNESS_MAX, 5),
            ("settings.font_scale_label", self.font_scale_var,
             FONT_SCALE_MIN, FONT_SCALE_MAX, 10),
        )
        for row, (label_key, var, low, high, step) in enumerate(readability_rows, start=1):
            ttk.Label(ui_frame, text=self.T(label_key)).grid(
                row=row, column=0, sticky="w", padx=6, pady=(0, 6))
            ttk.Spinbox(ui_frame, textvariable=var, from_=low, to=high, increment=step,
                        width=6).grid(row=row, column=1, sticky="w", padx=(0, 12), pady=(0, 6))
            ttk.Label(ui_frame, text=self.T("settings.readability_range", min=low, max=high),
                      style="Hint.TLabel").grid(row=row, column=2, sticky="w", padx=(0, 6), pady=(0, 6))
        self._load_readability_fields()
        readability_buttons = ttk.Frame(ui_frame)
        readability_buttons.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))
        ttk.Button(readability_buttons, text=self.T("settings.readability_apply"),
                   command=self._on_readability_apply).pack(side="left")
        ttk.Button(readability_buttons, text=self.T("settings.readability_reset"),
                   command=self._on_readability_reset).pack(side="left", padx=(6, 0))
        ttk.Label(ui_frame, text=self.T("settings.readability_note"), style="Hint.TLabel",
                  wraplength=760, justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 6))

        path_frame = ttk.Labelframe(outer, text=self.T("settings.path_frame"))
        path_frame.pack(fill="x", pady=(0, 8))
        self.path_var = tk.StringVar(value=self.wsl["get_portal_folder"]())
        ttk.Entry(path_frame, textvariable=self.path_var, width=70).grid(
            row=0, column=0, sticky="we", padx=6, pady=6)
        path_frame.columnconfigure(0, weight=1)
        ttk.Button(path_frame, text=self.T("settings.path_browse"),
                   command=self._on_browse_path).grid(row=0, column=1, padx=4)
        ttk.Button(path_frame, text=self.T("settings.path_save"),
                   command=self._on_save_path).grid(row=0, column=2, padx=4)
        ttk.Button(path_frame, text=self.T("settings.path_reset"),
                   command=self._on_reset_path).grid(row=0, column=3, padx=(4, 6))
        self.path_status_var = tk.StringVar(value=self._path_status_text())
        ttk.Label(path_frame, textvariable=self.path_status_var, style="Hint.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 6))
