"""
base_tab.py -- BaseTab(ttk.Frame), the common base class for every GUI tab class in
this package (refactor-phase2 branch, 2026-08-24: the OOP-cleanup follow-up to the
refactor branch's Faza 1-4 tab-by-tab extraction -- see README.md's "GUI module
conventions" section for the full history and the "Known gaps" this addresses).

Before this, each of the 9 tab classes (PrimesTab, PrimesieveCalcTab, PrimalityTab,
ConstellationsHitsTab, ConstellationsCalcTab, ConstellationsRecordsTab,
ResearchGoldbachTab, GenerationTab, BenchmarkTab, SettingsTab) independently
subclassed ttk.Frame directly and repeated the identical `self.T = translator`
assignment, plus, in four of them, byte-for-byte identical "switch the shared
totals_progress bar to a spinning indeterminate state, then back" boilerplate, and in
five of them, byte-for-byte identical "copy this text to the clipboard" boilerplate.
This class factors out exactly those two kinds of duplication -- nothing else. Every
tab class's own constructor signature stays exactly as varied as it needs to be (see
each class's own docstring for why -- they genuinely need different collaborators,
from a single `translator` for the smallest tabs up to eight separate callables/
values for the largest); this base class only standardizes the ONE thing every single
one of them shares.

_start_busy_progress()/_stop_busy_progress() assume self.totals_progress exists,
which only the tabs constructed with that collaborator actually have (see each
subclass's own docstring for whether it receives one) -- calling either from a tab
that lacks it raises AttributeError immediately, exactly as the duplicated inline
code they replace would have if used the same way. Deliberately does NOT also set
self.status here: the translated message text differs per call site (or is entirely
absent, e.g. GenerationTab's own multi-step progress accounting), so callers keep
setting self.status themselves right where they already did.
"""
from tkinter import ttk


class BaseTab(ttk.Frame):
    def __init__(self, parent, translator):
        super().__init__(parent)
        self.T = translator

    def _copy_to_clipboard(self, text):
        """Copies `text` to the system clipboard; a no-op if text is falsy (empty
        string or None) -- the same guard every duplicated copy-button handler this
        replaces already had (nothing to copy yet -> nothing happens)."""
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _start_busy_progress(self):
        """Switches self.totals_progress to indeterminate spin mode, for a tab's own
        single-shot compute job while it's in flight. Pair with
        _stop_busy_progress() once the job's result callback fires."""
        self.totals_progress.stop()
        self.totals_progress.configure(mode="indeterminate")
        self.totals_progress.start(80)

    def _stop_busy_progress(self):
        """Resets self.totals_progress back to its normal determinate resting state
        (maximum=1, value=0 -- an empty bar, matching every duplicated call site's
        own resting state)."""
        self.totals_progress.stop()
        self.totals_progress.configure(mode="determinate", maximum=1, value=0)
