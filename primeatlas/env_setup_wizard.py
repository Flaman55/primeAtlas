"""
env_setup_wizard.py -- first-run environment check/install wizard UI (task #513).

Drives primeatlas/env_setup.py's check_environment()/run_install() from a standalone
tkinter window, shown from prime_atlas_v1.py's main() BEFORE PortalBrowserApp is
constructed (that class doesn't exist yet at this point in startup, and env_setup's own
docstring explains why this has to happen before anything else: enabling the WSL Windows
features can require a reboot, so nothing downstream should even try to run first).

Flow: on open, silently runs check_environment() in a background thread (see
_start_check() -- threading.Thread + self.after(0, ...), same pattern
settings_tab.py's _on_check_cudasieve_status() uses, for the same reason: this is a real
multi-second WSL round-trip, not something to block Tk's mainloop on). If everything is
already OK, marks AppSettings.setup_completed True and closes itself almost immediately --
a user on an already-set-up machine should barely see this window flash by. If something
is missing, shows a small checklist and enables one "Install everything" button, which
runs env_setup.run_install() (a single elevated PowerShell script, one UAC prompt) in
another background thread, then re-checks automatically.

Same UI shown twice: once automatically on a fresh/incomplete install (gated on
AppSettings.setup_completed, as a standalone tk.Tk() root -- see _EnvSetupWizardRoot), and
again on demand from Settings > Aktualizacje's own 'Zweryfikuj srodowisko' button
(settings_tab.py), which runs it as a tk.Toplevel of the ALREADY-alive app instead (see
_EnvSetupWizardToplevel) -- creating a second, independent tk.Tk() root while one is
already running is unreliable across platforms (window-manager focus, event-loop
interaction), so the on-demand path reuses the existing root's real Tcl interpreter rather
than spinning up a second one. Both share every bit of actual logic via
_EnvSetupWizardMixin -- one implementation, not two that could drift apart.

NOT YET RUN on a real machine with WSL fully absent (this sandbox has no Windows/WSL) --
same caveat as env_setup.py's own module docstring. Hand off to Artur for a real
end-to-end test (task #515) before this gates every future PrimeAtlas install.
"""
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from . import env_setup

_CHECK_LABEL_KEYS = {
    "wsl_present": "wizard.check_wsl",
    "distro_present": "wizard.check_distro",
    "packages": "wizard.check_packages",
}


class _EnvSetupWizardMixin:
    """All the actual widget-building/check/install logic, shared by both the standalone-
    root and Toplevel variants below (see this module's own docstring for why there are
    two). A plain mixin (not a base class with its own __init__) since tk.Tk and
    tk.Toplevel have incompatible constructors -- each concrete subclass calls its own
    parent __init__ first, then this mixin's _init_wizard()."""

    # Overridden to False on _EnvSetupWizardToplevel -- see that class's own comment.
    _auto_close_when_ready = True

    def _init_wizard(self, app_settings, T, distro):
        self.app_settings = app_settings
        self.T = T
        self.distro = distro
        self.result = "pending"  # "ready" | "skip" | "closed" | "restart"
        self.title(T("wizard.title"))
        self.geometry("640x480")
        self.minsize(560, 420)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_widgets()
        # Deferred via after(), not called directly from __init__ -- lets the window
        # actually paint (title bar, initial "Checking environment..." label) before the
        # first real WSL round-trip starts, same "let something render before the first
        # slow step" reasoning as prime_atlas_v1.py's own loading_frame.update() call.
        self.after(150, self._start_check)

    def _build_widgets(self):
        ttk.Label(self, text=self.T("wizard.intro"), wraplength=600, justify="left").pack(
            anchor="w", padx=12, pady=(12, 6))
        self.status_var = tk.StringVar(value=self.T("wizard.checking"))
        ttk.Label(self, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12)
        self.checklist_frame = ttk.Frame(self)
        self.checklist_frame.pack(fill="x", padx=12, pady=(6, 6))
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=12, pady=(0, 6))
        self._progress_busy()
        self.log_widget = ScrolledText(self, height=10, font=("Consolas", 9), state="disabled")
        self.log_widget.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        self.install_btn = ttk.Button(btn_row, text=self.T("wizard.install_button"),
                                       command=self._on_install_clicked, state="disabled")
        self.install_btn.pack(side="right")
        self.recheck_btn = ttk.Button(btn_row, text=self.T("wizard.recheck_button"),
                                       command=self._start_check, state="disabled")
        self.recheck_btn.pack(side="right", padx=(0, 6))
        self.skip_btn = ttk.Button(btn_row, text=self.T("wizard.skip_button"),
                                    command=self._on_skip_clicked)
        self.skip_btn.pack(side="left")
        self.copy_log_btn = ttk.Button(btn_row, text=self.T("wizard.copy_log_button"),
                                        command=self._on_copy_log_clicked)
        self.copy_log_btn.pack(side="left", padx=(6, 0))

    def _progress_busy(self):
        """Switches the bar into its moving, animated state. Always pair with
        _progress_idle() on completion -- see that method's docstring for why leaving the
        bar in indeterminate mode after stop() looks broken rather than finished."""
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

    def _progress_idle(self):
        """Stops the animation AND switches to determinate mode at value=0, so the trough
        renders fully empty. ttk.Progressbar.stop() alone is not enough: an indeterminate
        bar that is merely stopped keeps showing whatever small colored block happened to
        be mid-sweep when stop() was called, sitting there motionless. A user glancing at
        that (Artur, 2026-09-02, live test on real hardware) cannot tell it apart from a
        stuck/hung install -- there is no visual difference between "idle, waiting for you
        to click a button" and "frozen". An empty determinate bar reads unambiguously as
        idle instead."""
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress["value"] = 0

    def _log(self, text):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _on_copy_log_clicked(self):
        """Copies the log widget's full text to the clipboard, so a user hitting an error
        here (no other way to select/copy multi-line text out of a ttk-themed window on
        every platform, and this window has no menu bar or right-click context menu) can
        paste the real error text elsewhere -- e.g. back to whoever is helping them debug
        it, exactly the gap Artur hit on real hardware (2026-09-02) trying to report the
        "elevation was declined" bug. self.update() right after clipboard_append() is the
        standard Tk idiom for making the clipboard content actually stick around after this
        window closes (X11 in particular only owns the clipboard while the owning window is
        alive unless something forces a flush)."""
        text = self.log_widget.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        original_text = self.copy_log_btn.cget("text")
        self.copy_log_btn.configure(text=self.T("wizard.copy_log_done"))
        self.after(1200, lambda: self.copy_log_btn.configure(text=original_text))

    def _render_checklist(self, report):
        for child in self.checklist_frame.winfo_children():
            child.destroy()
        for c in report["checks"]:
            row = ttk.Frame(self.checklist_frame)
            row.pack(fill="x", anchor="w")
            symbol = "[OK]" if c["ok"] else "[--]"
            ttk.Label(row, text=symbol, width=6).pack(side="left")
            label_key = _CHECK_LABEL_KEYS.get(c["id"], "wizard.check_error")
            ttk.Label(row, text=self.T(label_key, distro=self.distro)).pack(side="left")

    # ---- check ----------------------------------------------------------------------

    def _start_check(self):
        self.install_btn.configure(state="disabled")
        self.recheck_btn.configure(state="disabled")
        self.status_var.set(self.T("wizard.checking"))
        self._progress_busy()

        def worker():
            # try/except is load-bearing here (same reasoning as every WSL-touching
            # worker() in settings_tab.py): an uncaught exception would silently kill
            # this daemon thread, and self.after(...) below would never fire, leaving
            # the wizard stuck on "Checking environment..." forever.
            try:
                report = env_setup.check_environment(distro=self.distro)
            except Exception as e:  # noqa: BLE001 -- must always resolve back to the UI
                report = {"all_ok": False, "distro": self.distro,
                          "checks": [{"id": "error", "ok": False, "detail": str(e)}]}
            self.after(0, lambda: self._on_check_done(report))

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_done(self, report):
        self._progress_idle()
        # Stashed so _on_install_clicked can hand it straight to run_install() -- this
        # check just ran (it's literally what decided whether install_btn is even enabled
        # below), so re-running check_environment() a second time right before install
        # would just be a redundant WSL round-trip; see run_install()'s own docstring.
        self._last_report = report
        # Persisted on EVERY check (ready or missing), not just the ready branch below --
        # settings_tab.py's on-demand button reads this back once this window closes, so
        # it can keep showing a real status line instead of nothing (see AppSettings.
        # env_status's own docstring: this is exactly what Artur hit, 2026-09-02 -- the
        # on-demand wizard flashed "ready" and closed too fast to read, and Settings itself
        # had nowhere to show the result afterward).
        self.app_settings.set_env_status(report)
        self._render_checklist(report)
        self.recheck_btn.configure(state="normal")
        if report["all_ok"]:
            self.status_var.set(self.T("wizard.status_ready"))
            self.result = "ready"
            self.app_settings.set_setup_completed(True)
            self._log(self.T("wizard.log_ready"))
            if self._auto_close_when_ready:
                self.after(600, self.destroy)
            else:
                # On-demand (Settings button) check: relabel the skip button to "Zamknij"
                # (Close) instead of auto-vanishing -- the whole point of clicking this
                # button was to READ a result, so it must stay on screen until the user
                # dismisses it themselves (Artur, 2026-09-02: the 600ms auto-close made it
                # impossible to read even a successful result on demand).
                self.skip_btn.configure(text=self.T("wizard.close_button"))
        else:
            self.status_var.set(self.T("wizard.status_missing"))
            self.install_btn.configure(state="normal")

    # ---- install --------------------------------------------------------------------

    def _on_install_clicked(self):
        self.install_btn.configure(state="disabled")
        self.recheck_btn.configure(state="disabled")
        self.skip_btn.configure(state="disabled")
        self.status_var.set(self.T("wizard.status_installing"))
        self._progress_busy()
        self._log(self.T("wizard.log_install_starting"))

        def worker():
            try:
                result = env_setup.run_install(
                    distro=self.distro, report=getattr(self, "_last_report", None))
            except Exception as e:  # noqa: BLE001 -- same reasoning as _start_check's worker
                result = {"ok": False, "restart_required": False, "transcript": "",
                          "error": str(e)}
            self.after(0, lambda: self._on_install_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_done(self, result):
        self._progress_idle()
        if result.get("transcript"):
            self._log(result["transcript"])
        if result["restart_required"]:
            self.result = "restart"
            self.status_var.set(self.T("wizard.status_restart_required"))
            self._log(self.T("wizard.log_restart_required"))
            self.install_btn.configure(state="disabled")
            self.recheck_btn.configure(state="disabled")
            self.skip_btn.configure(text=self.T("wizard.close_button"), state="normal")
            return
        if result["ok"]:
            self._log(self.T("wizard.log_install_done"))
            self.skip_btn.configure(state="normal")
            self._start_check()
            return
        self.status_var.set(self.T("wizard.status_install_failed"))
        self._log(self.T("wizard.log_install_failed", error=result.get("error") or ""))
        self.install_btn.configure(state="normal")
        self.recheck_btn.configure(state="normal")
        self.skip_btn.configure(state="normal")

    # ---- close ------------------------------------------------------------------------

    def _on_skip_clicked(self):
        self.result = "skip"
        self.destroy()

    def _on_close(self):
        if self.result == "pending":
            self.result = "closed"
        self.destroy()


class _EnvSetupWizardRoot(tk.Tk, _EnvSetupWizardMixin):
    """Standalone root window -- used pre-GUI, before PortalBrowserApp (and therefore any
    other Tk root) exists at all."""

    def __init__(self, app_settings, T, distro=env_setup.DEFAULT_WSL_DISTRO):
        tk.Tk.__init__(self)
        self._init_wizard(app_settings, T, distro)


class _EnvSetupWizardToplevel(tk.Toplevel, _EnvSetupWizardMixin):
    """Modal child of the ALREADY-running PortalBrowserApp -- used by Settings >
    Aktualizacje's on-demand re-check (see this module's own docstring for why this is a
    Toplevel of the existing root rather than a second tk.Tk())."""

    # The automatic startup wizard (_EnvSetupWizardRoot) SHOULD auto-close fast when
    # everything is already fine -- a working machine should barely see it flash by. But
    # this Toplevel is only ever opened because the user explicitly clicked "Zweryfikuj
    # srodowisko" wanting to READ a result, so it must stay open until they dismiss it
    # themselves (Artur, 2026-09-02: the 600ms auto-close made even a successful on-demand
    # check unreadable).
    _auto_close_when_ready = False

    def __init__(self, master, app_settings, T, distro=env_setup.DEFAULT_WSL_DISTRO):
        tk.Toplevel.__init__(self, master)
        self.transient(master)
        self.grab_set()
        self._init_wizard(app_settings, T, distro)


def maybe_run_first_run_wizard(app_settings, translator, distro=env_setup.DEFAULT_WSL_DISTRO,
                                force=False, master=None):
    """Called from prime_atlas_v1.py's main(), BEFORE PortalBrowserApp is constructed
    (master=None, the default -- runs as a standalone root; see _EnvSetupWizardRoot).
    Returns True if startup should proceed (environment confirmed ready, or the user chose
    to skip/proceed anyway), False if the app should exit now instead (window closed
    without finishing, or a Windows restart is pending -- see env_setup.run_install()'s
    docstring for why nothing downstream can usefully run until then; this same function
    naturally resumes past the already-enabled features step on the next launch after
    that restart, no separate 'which step was I on' state needed).

    force=True re-shows the wizard even when AppSettings.setup_completed is already True
    -- used by Settings > Aktualizacje's 'Zweryfikuj srodowisko' button (settings_tab.py),
    which also passes master=<the already-running PortalBrowserApp instance> so this runs
    as a Toplevel of the live app instead of spinning up a second tk.Tk() root (see
    _EnvSetupWizardToplevel) -- one implementation either way, not a second, divergent one
    living in settings_tab.py itself."""
    if not force and app_settings.setup_completed:
        return True
    if master is not None:
        wizard = _EnvSetupWizardToplevel(master, app_settings, translator, distro=distro)
        master.wait_window(wizard)
    else:
        wizard = _EnvSetupWizardRoot(app_settings, translator, distro=distro)
        wizard.mainloop()
    return wizard.result in ("ready", "skip")
