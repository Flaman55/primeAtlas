"""
updates_section.py -- UpdatesSection, the Updates sub-tab of Settings: the optional-library
(sympy) installer, the primecount and CUDASieve installers (CUDASieve with its license
consent dialog before the build), the WSL environment re-check, and PrimeAtlas's own
self-update via git (app_update.py).

A SettingsTab mixin: it uses the widgets, Variables and state that SettingsTab and its
other mixins set up, so it is never instantiated on its own.
"""
import queue
import threading
import webbrowser

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from ..generation.generation_console import GenerationConsole
from . import app_update

# Same URL prime_sieve_cudasieve.py's own CUDASIEVE_REPO_URL clones from -- duplicated
# here (not imported -- that module is WSL-side, this is the Windows GUI process) purely
# to open the real GitHub page in the user's browser (_on_open_cudasieve_github_clicked
# below), never fetched by this process itself.
CUDASIEVE_REPO_URL = "https://github.com/curtisseizert/CUDASieve"

# Same reasoning as CUDASIEVE_REPO_URL above -- neither primecount nor primesieve is
# authored by this project; both are Kim Walisch's own independent, third-party, open-
# source libraries (BSD license) that prime_count_primecount.py/prime_sieve_primesieve.py
# call into via ctypes (see either module's own attribution header). primesieve is
# installed as part of env_setup.py's generic first-run package set rather than its own
# on-demand installer section like sympy/CUDASieve/primecount each get, so its own
# "Open on GitHub" button lives on the generic environment-setup section below instead of
# a dedicated Labelframe of its own.
PRIMECOUNT_REPO_URL = "https://github.com/kimwalisch/primecount"
PRIMESIEVE_REPO_URL = "https://github.com/kimwalisch/primesieve"


class UpdatesSection:
    # ---- app self-update ---------------------------------------------------

    def _on_auto_update_check_toggled(self):
        self.app_settings.set_auto_update_check(self.auto_update_check_var.get())

    def _on_auto_update_download_toggled(self):
        self.app_settings.set_auto_update_download(self.auto_update_download_var.get())

    def _on_check_app_update_clicked(self):
        self._check_for_app_update()

    def _check_for_app_update(self):
        """Runs app_update.check_for_update() (a `git fetch` against GitHub) on a
        background thread -- same "daemon thread + self.after(0, ...) callback" shape
        every other network/WSL-touching probe in this file uses, since a real network
        round-trip must never block the GUI thread. Reused for BOTH the manual 'Check
        now' button (_on_check_app_update_clicked above) and PortalBrowserApp's own
        startup hook (which only calls this at all when AppSettings.auto_update_check is
        on) -- single code path, so the status label always reflects the most recent
        check regardless of which one triggered it.

        On finding an update: downloads it immediately, with no prompt, if
        AppSettings.auto_update_download is on; otherwise asks via a plain Yes/No dialog
        first. Either way, a successful download is followed by _offer_restart_after_
        update() -- the new code is on disk but not yet running until the process
        restarts."""
        if self._app_update_check_running:
            return
        self._app_update_check_running = True
        self.app_update_check_btn.configure(state="disabled")
        self.app_update_status_var.set(self.T("settings.app_update_status_checking"))
        repo_dir = self.wsl.get("repo_dir")

        def worker():
            # try/except is load-bearing here, not defensive boilerplate -- see every
            # other worker() in this file for why an uncaught exception here would leave
            # _app_update_check_running stuck True forever (self.after(...) below would
            # never fire).
            try:
                result = app_update.check_for_update(repo_dir)
            except Exception as e:  # noqa: BLE001 -- must always resolve the guard flag
                result = {"ok": False, "update_available": False, "commits_behind": 0,
                          "local_commit": None, "remote_commit": None,
                          "error": f"{type(e).__name__}: {e}"}
            self.after(0, lambda: self._on_app_update_check_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_app_update_check_result(self, result):
        self._app_update_check_running = False
        self.app_update_check_btn.configure(state="normal")
        if not result["ok"]:
            self.app_update_status_var.set(
                self.T("settings.app_update_status_error", error=str(result["error"])[:200]))
            return
        if not result["update_available"]:
            self.app_update_status_var.set(self.T("settings.app_update_status_up_to_date"))
            return
        self.app_update_status_var.set(self.T(
            "settings.app_update_status_available", count=result["commits_behind"]))
        if self.app_settings.auto_update_download:
            self._download_app_update()
            return
        if messagebox.askyesno(self.T("settings.dialog_title"),
                                self.T("settings.app_update_confirm_download",
                                       count=result["commits_behind"])):
            self._download_app_update()

    def _download_app_update(self):
        if self._app_update_download_running:
            return
        self._app_update_download_running = True
        self.app_update_check_btn.configure(state="disabled")
        self.app_update_status_var.set(self.T("settings.app_update_status_downloading"))
        repo_dir = self.wsl.get("repo_dir")

        def worker():
            try:
                result = app_update.download_update(repo_dir)
            except Exception as e:  # noqa: BLE001 -- must always resolve the guard flag
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self.after(0, lambda: self._on_app_update_download_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_app_update_download_result(self, result):
        self._app_update_download_running = False
        self.app_update_check_btn.configure(state="normal")
        if not result["ok"]:
            self.app_update_status_var.set(self.T(
                "settings.app_update_status_download_failed", error=str(result["error"])[:200]))
            return
        self.app_update_status_var.set(self.T("settings.app_update_status_downloaded"))
        self._offer_restart_after_update()

    def _offer_restart_after_update(self):
        """After a successful update (fetch + fast-forward via app_update.download_update()
        -- see that module's docstring for the fetch/merge-base/merge sequence and its
        lock-recovery handling), the new code is on disk but not yet running --
        same "process needs replacing" situation _restart_now_or_warn() handles for
        theme/language, so this reuses _has_running_job()/restart_app() directly rather
        than duplicating that safety check. Unlike the theme/language case, this ALWAYS
        asks first (even when restarting right now would be perfectly safe) -- an update
        can touch far more of the app than a theme swap, so a silent auto-restart here
        would be more surprising than helpful, regardless of the auto_update_download
        setting (that setting only governs skipping the DOWNLOAD prompt, not this one)."""
        if self._has_running_job():
            messagebox.showinfo(self.T("settings.dialog_title"),
                                 self.T("settings.app_update_restart_blocked_job_running"))
            return
        if messagebox.askyesno(self.T("settings.dialog_title"),
                                self.T("settings.app_update_restart_confirm")):
            from .app_restart import restart_app
            self.after(150, restart_app)

    # ---- optional libraries (sympy installer) ---------------------------------------------

    def _refresh_libs_status(self):
        """Re-checks whether sympy is importable RIGHT NOW in this same Python
        environment (try_import_sympy() never caches a failed import -- see that
        function's own docstring), not just after an install finishes -- also called at
        tab-construction time so the label is correct even if sympy was already present
        (installed manually, or by a previous session's install here)."""
        installed = self.wsl["try_import_sympy"]() is not None
        self.libs_status_var.set(self.T(
            "settings.libs_sympy_installed" if installed else "settings.libs_sympy_missing"))
        self.install_sympy_btn.configure(
            state="disabled" if (installed or self._libs_install_running) else "normal")

    def _on_check_libs_status(self):
        self._refresh_libs_status()

    def _on_install_sympy(self):
        if self._libs_install_running:
            return
        argv = self.wsl["build_pip_install_argv"]("sympy")
        q = queue.Queue()
        runner = self.wsl["LocalLoggedRunner"](argv, q)
        self._libs_runner = runner
        self._libs_queue = q
        self._libs_install_running = True
        self.install_sympy_btn.configure(state="disabled")
        self._libs_log(self.T("settings.libs_install_starting", package="sympy") + "\n")
        runner.start()
        self._poll_libs_queue()

    def _poll_libs_queue(self):
        try:
            while True:
                item = self._libs_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    code = item[1]
                    self._libs_install_running = False
                    if code == 0:
                        self._libs_log(self.T("settings.libs_install_done") + "\n")
                        # A fresh `import sympy` in THIS process usually picks up a
                        # just-installed package without needing a restart (pip writes
                        # straight into site-packages, and a previously FAILED import
                        # isn't cached the way a successful one is) -- but a .pth-file
                        # edge case can still require one, so this note is a safety net,
                        # not a promise, same spirit as the language-switch dialog.
                        messagebox.showinfo(
                            self.T("settings.dialog_title"),
                            self.T("settings.libs_install_restart_note"))
                    else:
                        self._libs_log(self.T("settings.libs_install_failed", code=code) + "\n")
                    self._refresh_libs_status()
                    return
                self._libs_log(item)
        except queue.Empty:
            pass
        self.after(150, self._poll_libs_queue)

    def _libs_log(self, text):
        self.libs_console.append(text)

    # ---- primecount (optional exact prime-counting library) installer ---------------------
    #
    # Flow: [Check status] -> version query via WSL (background thread, real round-trip,
    # same reasoning as CUDASieve's own status probe below) -> status label + enable/
    # disable the install button. [Install primecount] -> apt-get install (background
    # thread, WSL, run as root -- see run_primecount_install_wsl_blocking's own docstring)
    # -> log output -> re-run the status probe on completion, same "no second manual
    # click needed" pattern as CUDASieve's own install flow.

    def _primecount_log(self, text):
        self.primecount_console.append(text)

    def _on_open_primecount_github_clicked(self):
        """Opens primecount's real GitHub page -- attribution for Kim Walisch's own
        independent project (see PRIMECOUNT_REPO_URL's own comment), same reasoning as
        _on_open_cudasieve_github_clicked above; the install button itself remains
        fully self-sufficient (a plain apt-get install), this is purely for someone who
        wants to see the actual source/README/license before trusting it."""
        webbrowser.open(PRIMECOUNT_REPO_URL)

    def _on_open_primesieve_github_clicked(self):
        """Same attribution reasoning as _on_open_primecount_github_clicked above, for
        primesieve -- installed as part of the generic environment check below rather
        than through its own dedicated installer section, so its GitHub link lives on
        that section's own button row instead of a Labelframe of its own."""
        webbrowser.open(PRIMESIEVE_REPO_URL)

    def _on_check_primecount_status(self):
        if self._primecount_status_running:
            return
        self._primecount_status_running = True
        self.primecount_status_var.set(self.T("settings.primecount_status_checking"))

        def worker():
            # try/except is load-bearing, not defensive boilerplate -- see
            # _on_check_cudasieve_status's own worker() for why (an uncaught exception
            # here would silently kill this daemon thread, leaving the guard flag stuck
            # True and the label on "checking..." forever).
            try:
                argv = self.wsl["build_primecount_query_argv"]("version")
                ok, result = self.wsl["run_primecount_wsl_blocking"](argv, 30)
            except Exception as e:  # noqa: BLE001 -- must always resolve the guard flag
                ok, result = False, {"message": f"{type(e).__name__}: {e}", "kind": None}
            self.after(0, lambda: self._on_primecount_status_result(ok, result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_primecount_status_result(self, ok, result):
        self._primecount_status_running = False
        if ok:
            self.primecount_status_var.set(
                self.T("settings.primecount_status_installed", version=result))
            self.install_primecount_btn.configure(state="disabled")
            return
        kind = result.get("kind") if isinstance(result, dict) else None
        message = result.get("message") if isinstance(result, dict) else str(result)
        if kind == "not_installed":
            self.primecount_status_var.set(self.T("settings.primecount_status_missing"))
        else:
            self.primecount_status_var.set(
                self.T("settings.primecount_status_error", error=str(message)[:200]))
        self.install_primecount_btn.configure(
            state="disabled" if self._primecount_install_running else "normal")

    def _on_install_primecount_clicked(self):
        if self._primecount_install_running:
            return
        self._primecount_install_running = True
        self.install_primecount_btn.configure(state="disabled")
        self._primecount_log(self.T("settings.primecount_installing") + "\n")

        def worker():
            try:
                ok, error = self.wsl["run_primecount_install_wsl_blocking"](300)
            except Exception as e:  # noqa: BLE001 -- must always resolve the guard flag
                ok, error = False, f"{type(e).__name__}: {e}"
            self.after(0, lambda: self._on_primecount_install_result(ok, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_primecount_install_result(self, ok, error):
        self._primecount_install_running = False
        if ok:
            self._primecount_log(self.T("settings.primecount_install_done") + "\n")
        else:
            self._primecount_log(
                self.T("settings.primecount_install_failed", error=str(error)[:800]) + "\n")
        # Re-probes status regardless of ok/failure -- same "reflect reality without a
        # second manual click" pattern as CUDASieve's own _on_check_cudasieve_status()
        # call at the end of a build; also correctly re-enables install_primecount_btn
        # on a failed install (via _on_primecount_status_result's own "still missing"
        # branch), which this method's own try/except never does directly.
        self._on_check_primecount_status()

    # ---- CUDASieve (GPU engine) installer ----------------------------------------------
    #
    # Flow: [Check status] -> quick WSL probe (background thread, since unlike
    # try_import_sympy() this is a real wsl.exe round-trip, not an in-process import --
    # see run_cudasieve_wsl_blocking()'s own docstring) -> status label + enable/disable
    # the install button. [Install] -> fetch-license (background thread) -> modal
    # consent dialog showing the license text JUST fetched (never a copy embedded in this
    # project) -> only on Accept, a WslLoggedRunner-driven `make` build (same live-log
    # shape as every Generation-tab job) -> re-run the status probe on completion so the
    # label reflects reality without a second manual click.

    def _cudasieve_log(self, text):
        self.cudasieve_console.append(text)

    def _show_cached_cudasieve_status(self):
        """Called once from __init__ instead of probing WSL -- see that call site's own
        comment. Renders whatever the last real Check status/Download/Install call
        found (AppSettings.cudasieve_status), or a neutral "not checked yet" label if this
        install has never run one. Routes through _on_cudasieve_status_result() itself
        (not a separate rendering path) so the two can never drift out of sync -- the
        cost is one harmless re-save of the same cached value back to app_settings."""
        cached = self.app_settings.cudasieve_status
        if cached is None:
            self.cudasieve_status_var.set(self.T("settings.cudasieve_status_not_checked"))
            return
        self._on_cudasieve_status_result(cached.get("ok"), cached.get("payload"))

    def _on_check_cudasieve_status(self):
        if self._cudasieve_status_running:
            return
        self._cudasieve_status_running = True
        self.cudasieve_status_var.set(self.T("settings.cudasieve_status_checking"))

        def worker():
            # try/except is load-bearing here, not defensive boilerplate: ANY exception
            # raised inside it (before or during the WSL call) would silently kill this
            # daemon thread -- self.after(...) below would never run, so
            # _cudasieve_status_running would never go back to False and the label would
            # stay on "checking..." forever, indistinguishable from a real wsl.exe hang.
            try:
                argv = self.wsl["build_cudasieve_status_argv"]()
                ok, payload = self.wsl["run_cudasieve_wsl_blocking"](argv, 30)
            except Exception as e:  # noqa: BLE001 -- must always resolve the guard flag
                ok, payload = False, f"{type(e).__name__}: {e}"
            self.after(0, lambda: self._on_cudasieve_status_result(ok, payload))

        threading.Thread(target=worker, daemon=True).start()

    def _on_cudasieve_status_result(self, ok, payload):
        self._cudasieve_status_running = False
        # Persisted so a restart shows this same result instead of falling back to
        # "not checked yet" -- see AppSettings.cudasieve_status's own docstring for why
        # this app deliberately never re-probes WSL on its own at startup. Also reached
        # from _show_cached_cudasieve_status() with the very value it just read back out
        # of this same setting -- a harmless no-op re-save in that path.
        self.app_settings.set_cudasieve_status(ok, payload)
        if not ok:
            self.cudasieve_status_var.set(
                self.T("settings.cudasieve_status_error", error=str(payload)[:200]))
            # Still lets the user try to install even if the status probe itself failed
            # (e.g. WSL cold-start hiccup) -- the install flow's own fetch-license step
            # will surface the real error again if it's persistent.
            self.install_cudasieve_btn.configure(
                state="disabled" if self._cudasieve_install_running else "normal")
            return
        if payload.get("binary_exists"):
            # Once actually installed, the button reads as "done, nothing left to do"
            # (disabled) rather than staying clickable -- the status line above already
            # names the exact path (payload["binary_path"]).
            self.cudasieve_status_var.set(self.T(
                "settings.cudasieve_status_installed", path=payload.get("binary_path") or ""))
            self.install_cudasieve_btn.configure(
                text=self.T("settings.cudasieve_install_button"), state="disabled")
            return
        if payload.get("cloned"):
            # Cloned (via Install's own fetch-license step, possibly from a previous,
            # not-yet-built run) but not yet built -- distinct from "missing entirely" so
            # the status label reflects exactly what's going on between those two steps.
            # Button stays disabled here (verify the CUDA toolchain by hand first, then
            # use Atlas's own build) -- see prime_sieve_cudasieve.py's cmd_build()
            # docstring for the toolchain issues a failed build here usually means.
            self.cudasieve_status_var.set(self.T(
                "settings.cudasieve_status_cloned_not_built",
                path=payload.get("install_dir") or ""))
            self.install_cudasieve_btn.configure(state="disabled")
            return
        if not payload.get("has_nvidia_smi"):
            self.cudasieve_status_var.set(self.T("settings.cudasieve_status_no_gpu"))
        elif not payload.get("has_nvcc"):
            self.cudasieve_status_var.set(self.T("settings.cudasieve_status_no_nvcc"))
        else:
            self.cudasieve_status_var.set(self.T("settings.cudasieve_status_missing"))
        self.install_cudasieve_btn.configure(
            state="disabled" if self._cudasieve_install_running else "normal")

    def _on_open_cudasieve_github_clicked(self):
        """Opens the real GitHub page rather than an in-app clone-only button -- Install
        below remains fully self-sufficient (clones/updates on its own), this is purely
        for someone who wants to inspect/clone by hand before trusting the automated
        build (git clone URL, README, releases, issues)."""
        webbrowser.open(CUDASIEVE_REPO_URL)

    def _on_install_cudasieve_clicked(self):
        if self._cudasieve_install_running:
            return
        self._cudasieve_install_running = True
        self.install_cudasieve_btn.configure(state="disabled")
        self._cudasieve_log(self.T("settings.cudasieve_fetching_license") + "\n")

        def worker():
            # See the matching comment in _on_check_cudasieve_status's worker() -- same
            # silent-thread-death hazard applies here.
            try:
                argv = self.wsl["build_cudasieve_fetch_license_argv"]()
                ok, payload = self.wsl["run_cudasieve_wsl_blocking"](argv, 120)
            except Exception as e:  # noqa: BLE001 -- must always resolve the guard flag
                ok, payload = False, f"{type(e).__name__}: {e}"
            self.after(0, lambda: self._on_cudasieve_license_fetched(ok, payload))

        threading.Thread(target=worker, daemon=True).start()

    def _on_cudasieve_license_fetched(self, ok, payload):
        if not ok:
            self._cudasieve_log(self.T(
                "settings.cudasieve_license_fetch_failed", error=str(payload)[:800]) + "\n")
            self._cudasieve_install_running = False
            self.install_cudasieve_btn.configure(state="normal")
            return
        license_text = payload.get("license_text") or ""
        self._show_cudasieve_consent_dialog(license_text)

    def _show_cudasieve_consent_dialog(self, license_text):
        """Modal Toplevel showing the REAL, just-fetched License file of the repository
        that was just cloned/updated on disk -- see cmd_fetch_license()'s own docstring
        (prime_sieve_cudasieve.py) for why this is read back from the actual clone rather
        than a copy kept in this project. Declining leaves the clone on disk (harmless --
        unbuilt source is not a usable engine) and simply resets the install flow; only
        Accept proceeds to the `make` build step."""
        dialog = tk.Toplevel(self)
        dialog.title(self.T("settings.cudasieve_consent_title"))
        dialog.geometry("700x520")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        ttk.Label(dialog, text=self.T("settings.cudasieve_consent_intro"),
                  wraplength=670, justify="left").pack(anchor="w", padx=10, pady=(10, 6))
        text_widget = ScrolledText(dialog, font=("Consolas", 9), wrap="word")
        text_widget.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        text_widget.insert("1.0", license_text)
        text_widget.configure(state="disabled")
        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))

        def on_accept():
            dialog.destroy()
            self._start_cudasieve_build()

        def on_decline():
            dialog.destroy()
            self._cudasieve_install_running = False
            self.install_cudasieve_btn.configure(state="normal")
            self._cudasieve_log(self.T("settings.cudasieve_consent_declined") + "\n")

        ttk.Button(btn_row, text=self.T("settings.cudasieve_consent_decline"),
                   command=on_decline).pack(side="right")
        ttk.Button(btn_row, text=self.T("settings.cudasieve_consent_accept"),
                   command=on_accept).pack(side="right", padx=(0, 6))
        dialog.protocol("WM_DELETE_WINDOW", on_decline)

    def _start_cudasieve_build(self):
        self._cudasieve_log(self.T("settings.cudasieve_build_starting") + "\n")
        argv = self.wsl["build_cudasieve_build_argv"]()
        log_path, exit_path, _run_id = self.wsl["generation_log_paths"](
            self.wsl["get_portal_folder"](), "cudasieve_build")
        cmd = self.wsl["build_wsl_logged_command"](argv, log_path, exit_path)
        q = queue.Queue()
        runner = self.wsl["WslLoggedRunner"](
            cmd, log_path, exit_path, q, kill_pattern="prime_sieve_cudasieve.py")
        self._cudasieve_runner = runner
        self._cudasieve_queue = q
        runner.start()
        self._poll_cudasieve_queue()

    def _poll_cudasieve_queue(self):
        try:
            while True:
                item = self._cudasieve_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    code = item[1]
                    self._cudasieve_install_running = False
                    if code == 0:
                        self._cudasieve_log(self.T("settings.cudasieve_build_done") + "\n")
                    else:
                        self._cudasieve_log(
                            self.T("settings.cudasieve_build_failed", code=code) + "\n")
                    self.install_cudasieve_btn.configure(state="normal")
                    self._on_check_cudasieve_status()
                    return
                self._cudasieve_log(item)
        except queue.Empty:
            pass
        self.after(150, self._poll_cudasieve_queue)

    # ---- environment setup re-check ---------------------------------------

    def _on_verify_environment_clicked(self):
        """Opens the same first-run environment wizard (env_setup_wizard.py) on demand,
        as a Toplevel of THIS running app (master=self.winfo_toplevel(), matching the
        pattern already used for the cudasieve consent dialog above) rather than a second
        tk.Tk() root -- see env_setup_wizard.py's own module docstring. force=True so it
        re-shows even though AppSettings.setup_completed is already True from an earlier
        successful check; this call is itself synchronous from the caller's point of view
        (it blocks -- via wait_window -- only until the wizard closes, same as any other
        modal dialog in this app), not a background job needing its own queue/poll loop."""
        from .env_setup_wizard import maybe_run_first_run_wizard
        maybe_run_first_run_wizard(self.app_settings, self.T, force=True,
                                    master=self.winfo_toplevel())
        # wait_window (inside maybe_run_first_run_wizard) blocks until the Toplevel is
        # closed -- by that point the wizard has already called
        # AppSettings.set_env_status() (env_setup_wizard.py's _on_check_done()), so this
        # tab's own label just needs to re-read it, same as _show_cached_env_status()
        # does at build time -- without this call the label would keep showing whatever
        # status was cached before the wizard ran, even though AppSettings was updated.
        self._show_cached_env_status()

    def _show_cached_env_status(self):
        """Renders AppSettings.env_status (the last real check_environment() report, from
        either the automatic startup check or an on-demand one here) into
        self.env_status_var. A neutral "not checked yet" label if this install has never
        run a check at all. Mirrors _show_cached_cudasieve_status()'s read-cached-value
        pattern, but -- unlike that one -- safe to call directly at widget-build time: it's
        a plain local JSON read, no WSL subprocess involved, so there's no mainloop()-
        startup race to defer past."""
        report = self.app_settings.env_status
        if report is None:
            self.env_status_var.set(self.T("settings.env_status_not_checked"))
            return
        if report.get("all_ok"):
            self.env_status_var.set(self.T("settings.env_status_ok"))
            return
        from .env_setup_wizard import _CHECK_LABEL_KEYS
        missing_labels = [
            self.T(_CHECK_LABEL_KEYS.get(c["id"], "wizard.check_error"),
                    distro=report.get("distro", ""))
            for c in report.get("checks", []) if not c.get("ok")
        ]
        self.env_status_var.set(self.T(
            "settings.env_status_missing", missing=", ".join(missing_labels)))

    def _build_updates_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        libs_frame = ttk.Labelframe(outer, text=self.T("settings.libs_frame"))
        libs_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(libs_frame, text=self.T("settings.libs_hint"),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(6, 4))
        libs_btn_row = ttk.Frame(libs_frame)
        libs_btn_row.pack(fill="x", padx=6, pady=(0, 4))
        self.libs_status_var = tk.StringVar(value="")
        ttk.Label(libs_btn_row, textvariable=self.libs_status_var).pack(side="left")
        ttk.Button(libs_btn_row, text=self.T("settings.libs_check_button"),
                   command=self._on_check_libs_status).pack(side="left", padx=(10, 0))
        self.install_sympy_btn = ttk.Button(
            libs_btn_row, text=self.T("settings.libs_install_sympy_button"),
            command=self._on_install_sympy)
        self.install_sympy_btn.pack(side="left", padx=(6, 0))
        self.libs_console = GenerationConsole(
            libs_frame, self.T, height=5, start_visible=True,
            window_title=self.T("settings.libs_frame"))
        self.libs_output = self.libs_console.text

        # primecount (Kim Walisch's exact combinatorial prime-counting library, BSD
        # license, companion to primesieve -- see prime_sieve/prime_count_primecount.py's
        # own module docstring) -- on-demand installer for the Research -> pi(x)
        # approximations tab's "primecount" data-source mode. Same simple shape as the sympy
        # section above (status label + check/install buttons + a log area), not
        # CUDASieve's own heavier consent-dialog/build flow below -- this is a single
        # apt-get install of an already-BSD-licensed system package, no license text to
        # show, no compilation step (see run_primecount_install_wsl_blocking's own
        # docstring). Unlike sympy's _refresh_libs_status() (a synchronous, in-process
        # import check, cheap enough to run at __init__ time), the status check here is a
        # REAL wsl.exe round trip -- starts as "not checked yet" and only ever probes on
        # an explicit click, same reasoning as CUDASieve's own status var below.
        primecount_frame = ttk.Labelframe(outer, text=self.T("settings.primecount_frame"))
        primecount_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(primecount_frame, text=self.T("settings.primecount_hint"),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(6, 4))
        primecount_btn_row = ttk.Frame(primecount_frame)
        primecount_btn_row.pack(fill="x", padx=6, pady=(0, 4))
        self.primecount_status_var = tk.StringVar(
            value=self.T("settings.primecount_status_not_checked"))
        ttk.Label(primecount_btn_row, textvariable=self.primecount_status_var).pack(side="left")
        ttk.Button(primecount_btn_row, text=self.T("settings.primecount_check_button"),
                   command=self._on_check_primecount_status).pack(side="left", padx=(10, 0))
        ttk.Button(
            primecount_btn_row, text=self.T("settings.primecount_open_github_button"),
            command=self._on_open_primecount_github_clicked).pack(side="left", padx=(6, 0))
        self.install_primecount_btn = ttk.Button(
            primecount_btn_row, text=self.T("settings.primecount_install_button"),
            command=self._on_install_primecount_clicked)
        self.install_primecount_btn.pack(side="left", padx=(6, 0))
        self.primecount_console = GenerationConsole(
            primecount_frame, self.T, height=5, start_visible=True,
            window_title=self.T("settings.primecount_frame"))
        self.primecount_output = self.primecount_console.text
        self._primecount_status_running = False
        self._primecount_install_running = False

        # CUDASieve (optional GPU engine) installer. Separate Labelframe from the sympy
        # one above: different license
        # (GPLv3, not MIT), different runtime (WSL subprocess, not this same Python
        # process), and its own mandatory consent dialog -- see
        # _on_install_cudasieve_clicked's own docstring block above.
        cudasieve_frame = ttk.Labelframe(outer, text=self.T("settings.cudasieve_frame"))
        cudasieve_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(cudasieve_frame, text=self.T("settings.cudasieve_hint"),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(6, 4))
        cudasieve_btn_row = ttk.Frame(cudasieve_frame)
        cudasieve_btn_row.pack(fill="x", padx=6, pady=(0, 4))
        self.cudasieve_status_var = tk.StringVar(
            value=self.T("settings.cudasieve_status_not_checked"))
        ttk.Label(cudasieve_btn_row, textvariable=self.cudasieve_status_var).pack(side="left")
        ttk.Button(cudasieve_btn_row, text=self.T("settings.cudasieve_check_button"),
                   command=self._on_check_cudasieve_status).pack(side="left", padx=(10, 0))
        ttk.Button(
            cudasieve_btn_row, text=self.T("settings.cudasieve_open_github_button"),
            command=self._on_open_cudasieve_github_clicked).pack(side="left", padx=(6, 0))
        self.install_cudasieve_btn = ttk.Button(
            cudasieve_btn_row, text=self.T("settings.cudasieve_install_button"),
            command=self._on_install_cudasieve_clicked, state="disabled")
        self.install_cudasieve_btn.pack(side="left", padx=(6, 0))
        self.cudasieve_console = GenerationConsole(
            cudasieve_frame, self.T, height=5, start_visible=True,
            window_title=self.T("settings.cudasieve_frame"))
        self.cudasieve_output = self.cudasieve_console.text

        # Environment setup re-check -- reuses the exact same
        # check_environment()/run_install() flow the first-run wizard (env_setup.py,
        # env_setup_wizard.py) runs automatically at startup, opened here on demand as a
        # Toplevel of THIS already-running app (see env_setup_wizard.py's own module
        # docstring for why: a second, independent tk.Tk() root while one is already
        # alive is unreliable across platforms). Useful if WSL/a package got uninstalled
        # or broken after the first-run check already passed once.
        env_frame = ttk.Labelframe(outer, text=self.T("settings.env_frame"))
        env_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(env_frame, text=self.T("settings.env_hint"),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(6, 4))
        env_btn_row = ttk.Frame(env_frame)
        env_btn_row.pack(fill="x", padx=6, pady=(0, 6))
        self.env_status_var = tk.StringVar(value=self.T("settings.env_status_not_checked"))
        ttk.Label(env_btn_row, textvariable=self.env_status_var).pack(side="left")
        ttk.Button(env_btn_row, text=self.T("settings.env_recheck_button"),
                   command=self._on_verify_environment_clicked).pack(side="left", padx=(10, 0))
        # Attribution for libprimesieve, installed as part of this same environment
        # check (REQUIRED_APT_PACKAGES) rather than through its own dedicated installer
        # section -- see PRIMESIEVE_REPO_URL's own comment above for why the link lives
        # here instead of a separate Labelframe.
        ttk.Button(env_btn_row, text=self.T("settings.env_open_primesieve_github_button"),
                   command=self._on_open_primesieve_github_clicked).pack(side="left", padx=(6, 0))
        # Seeded immediately (unlike _show_cached_cudasieve_status(), which __init__
        # defers past _build_widgets() to avoid a live WSL round-trip racing mainloop()
        # startup) -- AppSettings.env_status is a plain local JSON read with no subprocess
        # involved, so there's no such race to avoid here.
        self._show_cached_env_status()

        # PrimeAtlas's own self-update -- checks GitHub (via `git fetch` against this
        # checkout's own `origin` remote) for newer commits on main and, on request,
        # applies them by fetching and fast-forwarding (`git merge --ff-only`, with
        # proactive/automatic recovery from leftover git lock files -- see
        # primeatlas/settings/app_update.py's own module docstring for the full
        # fetch/merge-base/merge sequence and why this reuses git directly instead of a
        # separate release/version-number scheme).
        app_update_frame = ttk.Labelframe(outer, text=self.T("settings.app_update_frame"))
        app_update_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(app_update_frame, text=self.T("settings.app_update_hint"),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(6, 4))

        app_update_toggle_row = ttk.Frame(app_update_frame)
        app_update_toggle_row.pack(fill="x", padx=6, pady=(0, 4))
        self.auto_update_check_var = tk.BooleanVar(value=self.app_settings.auto_update_check)
        ttk.Checkbutton(
            app_update_toggle_row, text=self.T("settings.app_update_auto_check_label"),
            variable=self.auto_update_check_var,
            command=self._on_auto_update_check_toggled).pack(side="left")
        self.auto_update_download_var = tk.BooleanVar(
            value=self.app_settings.auto_update_download)
        ttk.Checkbutton(
            app_update_toggle_row, text=self.T("settings.app_update_auto_download_label"),
            variable=self.auto_update_download_var,
            command=self._on_auto_update_download_toggled).pack(side="left", padx=(16, 0))

        app_update_btn_row = ttk.Frame(app_update_frame)
        app_update_btn_row.pack(fill="x", padx=6, pady=(0, 6))
        self.app_update_status_var = tk.StringVar(
            value=self.T("settings.app_update_status_not_checked"))
        ttk.Label(app_update_btn_row, textvariable=self.app_update_status_var).pack(
            side="left")
        self.app_update_check_btn = ttk.Button(
            app_update_btn_row, text=self.T("settings.app_update_check_button"),
            command=self._on_check_app_update_clicked)
        self.app_update_check_btn.pack(side="left", padx=(10, 0))
