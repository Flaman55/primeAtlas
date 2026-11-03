"""
about_tab.py -- AboutTab(BaseTab), the last main notebook tab.

Shows the app name with version_label() (release, merges since it and the checked-out
commit), a short description, what the visualizations show, the author with e-mail and
GitHub links, the license, the related projects, then two read-only boxes: the CHANGELOG.md
entries since the last release (newest first, in the UI language) with a link to the full
file, and NOTICE.md (third-party components).

Links are Link.TLabel labels (styled in PortalBrowserApp._apply_theme) that open their URL
with webbrowser on click; `links` maps "email"/"repo"/"license"/"changelog" to them.

The page does not scroll as a whole, so it has no ScrollPad: the header is a few lines and
the two long contents sit in their own scrolled text boxes sharing the rest.
"""
import os
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from primeatlas.core.base_tab import BaseTab
from primeatlas.core.version import read_changelog, version_label

AUTHOR_NAME = "Artur Flamandzki"
AUTHOR_EMAIL = "flamandzki.artur@gmail.com"
REPO_URL = "https://github.com/Flaman55/primeAtlas"
LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"
CHANGELOG_URL = f"{REPO_URL}/blob/main/CHANGELOG.md"


class AboutTab(BaseTab):
    def __init__(self, parent, repo_root, translator):
        super().__init__(parent, translator)
        self._repo_root = repo_root
        self.links = {}
        self._build_widgets()

    def _build_widgets(self):
        T = self.T
        header = ttk.Frame(self)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text=T("app.title"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=T("about.version", version=version_label(self._repo_root)),
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 8))
        wrapped = [ttk.Label(header, text=T("about.description"), justify="left")]
        wrapped[-1].pack(anchor="w", fill="x", pady=(0, 8))
        wrapped.append(ttk.Label(header, text=T("about.visualization"), justify="left"))
        wrapped[-1].pack(anchor="w", fill="x", pady=(0, 12))

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

        wrapped.append(ttk.Label(header, text=T("about.author_bio"), justify="left"))
        wrapped[-1].pack(anchor="w", fill="x", pady=(12, 2))
        wrapped.append(ttk.Label(header, text=T("about.related_projects"), justify="left"))
        wrapped[-1].pack(anchor="w", fill="x")
        # Paragraphs wrap at the header's current width, so they follow window resizes.
        header.bind("<Configure>", lambda e: [w.configure(wraplength=max(e.width, 200))
                                              for w in wrapped])

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
