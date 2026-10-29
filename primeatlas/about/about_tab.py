"""
about_tab.py -- AboutTab(BaseTab), the last main notebook tab.

Shows the app name with version_label() (APP_VERSION plus the checked-out commit), a short
description, what the visualizations show, the author with e-mail and GitHub links, the
license, the related projects and NOTICE.md (third-party components) read-only below.

Links are Link.TLabel labels (styled in PortalBrowserApp._apply_theme) that open their URL
with webbrowser on click; `links` maps "email"/"repo"/"license" to them.

The page does not scroll as a whole, so it has no ScrollPad: the header is a few lines and
NOTICE.md, the only long content, sits in its own scrolled text box filling the rest.
"""
import os
import webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from primeatlas.core.base_tab import BaseTab
from primeatlas.core.version import version_label

AUTHOR_NAME = "Artur Flamandzki"
AUTHOR_EMAIL = "flamandzki.artur@gmail.com"
REPO_URL = "https://github.com/Flaman55/primeAtlas"
LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"


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

        notice = ttk.LabelFrame(self, text=T("about.notice_frame"))
        notice.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self.notice_text = ScrolledText(notice, height=10, wrap="word", font=("Consolas", 9))
        self.notice_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.notice_text.insert("1.0", self._read_notice())
        self.notice_text.configure(state="disabled")

    def _read_notice(self):
        try:
            with open(os.path.join(self._repo_root, "NOTICE.md"), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return self.T("about.notice_missing")
