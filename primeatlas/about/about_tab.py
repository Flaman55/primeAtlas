"""
about_tab.py -- AboutTab(BaseTab), the last main notebook tab.

Shows the app name with version_label() (release, merges since it and the checked-out
commit) with a copy glyph that puts that version line on the clipboard, a short
description, what the visualizations show, the author with e-mail and
GitHub links, the license, the related projects, a "This computer" frame (Windows and WSL
hardware with the WSL RAM limit, the CPU/RAM details and the values typed for this computer,
read in the background the first time the tab is shown and again on its Refresh glyph, with
a copy glyph, a row that changes the limit: wsl_limit_row.WslLimitRow, told which Generation
jobs run by `running_jobs`, and a "Fill in details..." button opening `machine_prompt`'s
window for the values Windows cannot read), then two
read-only boxes: the CHANGELOG.md entries since the last release (newest first, in the UI
language) with a link to the full file, and NOTICE.md (third-party components).

Links are Link.TLabel labels (styled in PortalBrowserApp._apply_theme) that open their URL
with webbrowser on click; `links` maps "email"/"repo"/"license"/"changelog" to them.

The page does not scroll as a whole, so it has no ScrollPad: the header is a few lines and
the two long contents sit in their own scrolled text boxes sharing the rest.
"""
import os
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from primeatlas.about import system_info
from primeatlas.about.system_info_text import system_info_lines
from primeatlas.about.wsl_limit_row import WslLimitRow
from primeatlas.core import cpu_dynamic, hardware_dynamic
from primeatlas.core.background import run_in_background
from primeatlas.core.base_tab import BaseTab
from primeatlas.core.info_tip import InfoTip
from primeatlas.core.version import read_changelog, version_label
from primeatlas.core.wrap_label import WrapLabel

AUTHOR_NAME = "Artur Flamandzki"
AUTHOR_EMAIL = "flamandzki.artur@gmail.com"
REPO_URL = "https://github.com/Flaman55/primeAtlas"
LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"
CHANGELOG_URL = f"{REPO_URL}/blob/main/CHANGELOG.md"
COPY_GLYPH = "⧉"  # two joined squares
REFRESH_GLYPH = "⟳"  # clockwise open circle arrow


class AboutTab(BaseTab):
    def __init__(self, parent, repo_root, translator, running_jobs=lambda: [],
                 machine_prompt=None):
        super().__init__(parent, translator)
        self._repo_root = repo_root
        self._running_jobs = running_jobs
        self._machine_prompt = machine_prompt
        self._system_info = None
        if machine_prompt is not None:
            machine_prompt.add_listener(self._after_machine_window)
        self.links = {}
        self._system_read = False
        self._build_widgets()
        # Reading the hardware starts WSL, so it waits until the tab is first shown. The tab
        # sits in a scrolled container, so <Map> fires at build; the notebook selecting the
        # page that holds this tab is the moment it is shown.
        notebook = self.master
        while notebook is not None and not isinstance(notebook, ttk.Notebook):
            notebook = notebook.master
        if notebook is not None:
            notebook.bind("<<NotebookTabChanged>>",
                          lambda _e: self._read_system_once(notebook), add="+")

    def _build_widgets(self):
        T = self.T
        header = ttk.Frame(self)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text=T("app.title"), style="Title.TLabel").pack(anchor="w")
        version_row = ttk.Frame(header)
        version_row.pack(anchor="w", pady=(0, 8))
        version_text = T("about.version", version=version_label(self._repo_root))
        ttk.Label(version_row, text=version_text, style="Hint.TLabel").pack(side="left")
        # A copy glyph, not a button: hovering names it (InfoTip popup), a click copies.
        copy_tip = InfoTip(version_row, lambda: T("common.copy"))
        self.version_copy = copy_tip.label
        self.version_copy.configure(text=COPY_GLYPH, cursor="hand2")
        self.version_copy.bind("<Button-1>", lambda _e: self._copy_to_clipboard(version_text))
        self.version_copy.pack(side="left", padx=(6, 0))
        WrapLabel(header, text=T("about.description")).pack(anchor="w", fill="x", pady=(0, 8))
        WrapLabel(header, text=T("about.visualization")).pack(anchor="w", fill="x",
                                                               pady=(0, 12))

        facts = ttk.Frame(header)
        facts.pack(anchor="w", fill="x")
        rows = (
            ("about.author_label", AUTHOR_NAME, None, None),
            ("about.email_label", AUTHOR_EMAIL, "email", f"mailto:{AUTHOR_EMAIL}"),
            ("about.repo_label", REPO_URL, "repo", REPO_URL),
            ("about.license_label", T("about.license_name"), "license", LICENSE_URL),
        )
        for row, (label_key, value, link_key, url) in enumerate(rows):
            ttk.Label(facts, text=T(label_key)).grid(row=row, column=0, sticky="w",
                                                      padx=(0, 12), pady=1)
            value_label = ttk.Label(facts, text=value,
                                    style="Link.TLabel" if url else "TLabel")
            value_label.grid(row=row, column=1, sticky="w", pady=1)
            if url:
                value_label.configure(cursor="hand2")
                value_label.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
                self.links[link_key] = value_label

        WrapLabel(header, text=T("about.author_bio")).pack(anchor="w", fill="x", pady=(12, 2))
        WrapLabel(header, text=T("about.related_projects")).pack(anchor="w", fill="x")

        self._build_system_frame()

        changelog = read_changelog(self._repo_root)
        changes = ttk.LabelFrame(self, text=T("about.changes_frame", release=changelog.release))
        changes.pack(fill="both", expand=True, padx=16, pady=(8, 0))
        full = ttk.Label(changes, text=T("about.changes_full"), style="Link.TLabel",
                         cursor="hand2")
        full.pack(anchor="w", padx=4, pady=(4, 0))
        full.bind("<Button-1>", lambda _e: webbrowser.open(CHANGELOG_URL))
        self.links["changelog"] = full
        self.changes_text = ScrolledText(changes, height=8, wrap="word", font=("Consolas", 9))
        self.changes_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.changes_text.insert("1.0", self._changes_text(changelog))
        self.changes_text.configure(state="disabled")

        notice = ttk.LabelFrame(self, text=T("about.notice_frame"))
        notice.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self.notice_text = ScrolledText(notice, height=10, wrap="word", font=("Consolas", 9))
        self.notice_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.notice_text.insert("1.0", self._read_notice())
        self.notice_text.configure(state="disabled")

    def _build_system_frame(self):
        T = self.T
        frame = ttk.LabelFrame(self, text=T("about.system_frame"))
        frame.pack(fill="x", padx=16, pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        self.system_text = ttk.Label(frame, text=T("about.system_reading"), justify="left")
        self.system_text.grid(row=0, column=0, sticky="nw", padx=4, pady=4)
        glyphs = ttk.Frame(frame)
        glyphs.grid(row=0, column=1, sticky="ne", padx=4, pady=4)
        for attr, glyph, tip, action in (
                ("system_copy", COPY_GLYPH, "common.copy",
                 lambda: self._copy_to_clipboard(str(self.system_text.cget("text")))),
                ("system_refresh", REFRESH_GLYPH, "about.system_refresh", self._read_system)):
            label = InfoTip(glyphs, lambda k=tip: T(k)).label
            label.configure(text=glyph, cursor="hand2")
            label.bind("<Button-1>", lambda _e, a=action: a())
            label.pack(side="left", padx=(6, 0))
            setattr(self, attr, label)
        self.wsl_limit = WslLimitRow(frame, T, running_jobs=lambda: self._running_jobs(),
                                     on_saved=self._read_system)
        self.wsl_limit.grid(row=1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))
        self.machine_button = ttk.Button(frame, text=T("machine.button"),
                                         command=self._open_machine_details)
        if self._machine_prompt is not None:
            self.machine_button.grid(row=2, column=0, sticky="w", padx=4, pady=(0, 4))

    def _read_system_once(self, notebook):
        page = notebook.select()
        shown = page and (str(self) + ".").startswith(str(page) + ".")
        if shown and not self._system_read:
            self._system_read = True
            self._read_system()

    def _show_system_lines(self):
        """The last read's lines with this computer's typed values as they are now."""
        T = self.T
        if self._system_info is None:
            self.system_text.configure(text=T("about.system_unknown"))
            return
        machine = (self._machine_prompt.current_entry()
                   if self._machine_prompt is not None else None)
        self.system_text.configure(
            text="\n".join(system_info_lines(self._system_info, T, machine)))

    def _open_machine_details(self):
        self._machine_prompt.open_details()

    def _after_machine_window(self):
        """Saved values show at once, without reading the hardware again."""
        if self.system_text.winfo_exists() and self._system_info is not None:
            self._show_system_lines()

    def _read_system(self):
        T = self.T
        self.system_text.configure(text=T("about.system_reading"))

        def done(info, error):
            if not self.system_text.winfo_exists():
                return
            self._system_info = info if error is None else None
            self._show_system_lines()
            if error is None:
                hardware_dynamic.set_details(info.details)
                self.wsl_limit.show(info)
                if info.wsl is not None:
                    cpu_dynamic.set_wsl_cpus(info.wsl.cpus)
        # Looked up at call time, so the read can be replaced without touching the tab.
        run_in_background(self, lambda _report: system_info.read_system_info(), on_done=done)

    def _changes_text(self, changelog):
        polish = getattr(self.T, "language", None) == "pl"
        lines = [f"+{e.number} — {e.title}\n{e.polish if polish else e.english}"
                 for e in reversed(changelog.entries)]
        return "\n\n".join(lines) if lines else self.T("about.changes_none")

    def _read_notice(self):
        try:
            with open(os.path.join(self._repo_root, "NOTICE.md"), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return self.T("about.notice_missing")
