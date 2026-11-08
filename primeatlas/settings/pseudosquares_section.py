"""
pseudosquares_section.py -- PseudosquaresSection, the Settings > Updates block of the
Pseudosquares Prime Sieve program (Kim Walisch, BSD 2-Clause License): its status, one
Install / Rebuild button and a link to its GitHub page.

Install / Rebuild: a status probe (pseudosquares_install.py --status), the build tools
installed as root when any is missing (wsl.exe -u root, no password), then the build of the
pinned commit shown live in the section's console, then a fresh status. The same button
moves an install on another commit to the pin. The license is BSD 2-Clause, which asks for
the copyright notice to be kept, not for consent, so the build needs no accept step (NOTICE.md
lists the program).

A SettingsTab mixin: it uses self.T, self.wsl (the WSL helper bundle) and Tk's after(), so it
is never instantiated on its own.
"""
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import pseudosquares_const

from ..generation.generation_console import GenerationConsole


def status_text(ok, payload, T):
    """The status line of a probe result: (ok, report dict) or (False, error text)."""
    if not ok:
        return T("settings.pseudosquares_status_error", error=str(payload)[:200])
    tools = payload.get("tools_missing") or []
    if payload.get("binary_path"):
        key = ("settings.pseudosquares_status_installed" if payload.get("at_pin")
               else "settings.pseudosquares_status_other_commit")
        return T(key, version=payload.get("version") or "?",
                 commit=payload.get("commit") or "?", pinned=payload.get("pinned") or "")
    if payload.get("cloned"):
        text = T("settings.pseudosquares_status_not_built", commit=payload.get("commit") or "?")
    else:
        text = T("settings.pseudosquares_status_missing")
    if tools:
        text += " " + T("settings.pseudosquares_status_tools", tools=", ".join(tools))
    return text


class PseudosquaresSection:
    def _build_pseudosquares_section(self, outer):
        self._pseudosquares_busy = False
        frame = ttk.Labelframe(outer, text=self.T("settings.pseudosquares_frame"))
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text=self.T("settings.pseudosquares_hint",
                                     pinned=pseudosquares_const.PIN_SHORT),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(6, 4))
        row = ttk.Frame(frame)
        row.pack(fill="x", padx=6, pady=(0, 4))
        self.pseudosquares_status_var = tk.StringVar(
            value=self.T("settings.pseudosquares_status_not_checked"))
        ttk.Label(row, textvariable=self.pseudosquares_status_var).pack(side="left")
        self.pseudosquares_check_btn = ttk.Button(
            row, text=self.T("settings.pseudosquares_check_button"),
            command=self._on_check_pseudosquares_status)
        self.pseudosquares_check_btn.pack(side="left", padx=(10, 0))
        self.pseudosquares_install_btn = ttk.Button(
            row, text=self.T("settings.pseudosquares_install_button"),
            command=self._on_install_pseudosquares_clicked)
        self.pseudosquares_install_btn.pack(side="left", padx=(6, 0))
        ttk.Button(row, text=self.T("settings.pseudosquares_open_github_button"),
                   command=lambda: webbrowser.open(pseudosquares_const.REPO_URL)).pack(
            side="left", padx=(6, 0))
        self.pseudosquares_console = GenerationConsole(
            frame, self.T, height=5, start_visible=True,
            window_title=self.T("settings.pseudosquares_frame"))

    def _pseudosquares_set_busy(self, busy):
        self._pseudosquares_busy = busy
        state = "disabled" if busy else "normal"
        self.pseudosquares_check_btn.configure(state=state)
        self.pseudosquares_install_btn.configure(state=state)

    def _pseudosquares_log(self, text):
        self.pseudosquares_console.append(text if text.endswith("\n") else text + "\n")

    def _pseudosquares_probe(self):
        """(ok, payload) of the status probe; never raises (runs on a worker thread)."""
        try:
            argv = self.wsl["build_pseudosquares_install_argv"]("--status")
            return self.wsl["run_pseudosquares_status_wsl_blocking"](argv, 60)
        except Exception as e:  # noqa: BLE001 -- the busy flag must always be released
            return False, f"{type(e).__name__}: {e}"

    def _on_check_pseudosquares_status(self):
        if self._pseudosquares_busy:
            return
        self._pseudosquares_set_busy(True)
        self.pseudosquares_status_var.set(self.T("settings.pseudosquares_status_checking"))

        def worker():
            ok, payload = self._pseudosquares_probe()
            self.after(0, lambda: self._on_pseudosquares_status(ok, payload))

        threading.Thread(target=worker, daemon=True).start()

    def _on_pseudosquares_status(self, ok, payload):
        self._pseudosquares_set_busy(False)
        self.pseudosquares_status_var.set(status_text(ok, payload, self.T))

    def _on_install_pseudosquares_clicked(self):
        if self._pseudosquares_busy:
            return
        self._pseudosquares_set_busy(True)
        self._pseudosquares_log(self.T("settings.pseudosquares_preparing"))

        def worker():
            tools, error = self._prepare_pseudosquares_install()
            self.after(0, lambda: self._after_pseudosquares_prepare(tools, error))

        threading.Thread(target=worker, daemon=True).start()

    def _prepare_pseudosquares_install(self):
        """(build tools installed, error text or None): the status probe, then the missing
        build tools as root. Blocking, no Tk calls (runs on a worker thread)."""
        ok, payload = self._pseudosquares_probe()
        if not ok:
            return [], self.T("settings.pseudosquares_status_error", error=str(payload)[:800])
        tools = payload.get("tools_missing") or []
        if not tools:
            return [], None
        try:
            done, detail = self.wsl["run_pseudosquares_tools_install_wsl_blocking"](600)
        except Exception as e:  # noqa: BLE001 -- see _pseudosquares_probe
            done, detail = False, f"{type(e).__name__}: {e}"
        if not done:
            return [], self.T("settings.pseudosquares_tools_failed", error=str(detail)[:800])
        return tools, None

    def _after_pseudosquares_prepare(self, tools, error):
        if tools:
            self._pseudosquares_log(self.T("settings.pseudosquares_installed_tools",
                                           tools=", ".join(tools)))
        if error:
            self._pseudosquares_log(error)
            self._pseudosquares_set_busy(False)
            return
        self._pseudosquares_log(self.T("settings.pseudosquares_build_starting",
                                       pinned=pseudosquares_const.PIN_SHORT))
        argv = self.wsl["build_pseudosquares_install_argv"]("--build")
        log_path, exit_path, _run_id = self.wsl["generation_log_paths"](
            self.wsl["get_portal_folder"](), "pseudosquares_build")
        cmd = self.wsl["build_wsl_logged_command"](argv, log_path, exit_path)
        self._pseudosquares_queue = queue.Queue()
        self._pseudosquares_runner = self.wsl["WslLoggedRunner"](
            cmd, log_path, exit_path, self._pseudosquares_queue,
            kill_pattern="pseudosquares_install.py")
        self._pseudosquares_runner.start()
        self._poll_pseudosquares_queue()

    def _poll_pseudosquares_queue(self):
        try:
            while True:
                item = self._pseudosquares_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    self._pseudosquares_log(self.T(
                        "settings.pseudosquares_build_done" if item[1] == 0
                        else "settings.pseudosquares_build_failed", code=item[1]))
                    self._pseudosquares_set_busy(False)
                    self._on_check_pseudosquares_status()
                    return
                self.pseudosquares_console.append(item)
        except queue.Empty:
            pass
        self.after(150, self._poll_pseudosquares_queue)
