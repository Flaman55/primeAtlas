"""threads_field -- ThreadsField, the app-wide control of a thread count (a ttk.Spinbox).

It shows a variable it does not own: the form's StringVar that the launch, the settings and
the remembered-fields store read. That variable holds a word of the field ("Auto", "Max") or
a number; the Spinbox shows the word with the count it stands for, "Max (8)", from its own
display variable. Max stands for the CPU count WSL reports (core.cpu_dynamic); another word
for resolve(word), or nothing ("Auto" of a program that picks its own count shows bare).

The list holds the words and 1..CPU count (1..threads_choice.CAP while it is unknown). A
number above the count cannot stay: typed, picked, set by code or loaded from the store, it
becomes `over` ("Max"), or the count itself for a field without words. Every new count
(core.cpu_dynamic.set_wsl_cpus) refits and relabels every field; refresh() relabels after
something resolve() reads has changed. Both directions are synced in an idle job, not inside
a variable trace: a variable set inside its own trace would skip the other traces (the store's
save, the Spinbox's own display).

Text that is no number and no word, or below 1, is red (core.number_field).
"""
import tkinter as tk
from tkinter import ttk

from . import cpu_dynamic, number_field, threads_choice

MAX_WORD = "Max"


class ThreadsField(ttk.Spinbox):
    def __init__(self, parent, T, variable, words=(), over=None, resolve=None, width=8, **kw):
        self.variable = variable
        self._words = tuple(words)
        self._over = over
        self._resolve = resolve
        self._display = tk.StringVar(master=parent)
        self._pending = None
        super().__init__(parent, textvariable=self._display, width=width, **kw)
        self.number_field = number_field.attach(self, T, words=self._words, minimum=1,
                                                text_of=threads_choice.word_of)
        self._variable_trace = variable.trace_add("write", lambda *_: self._schedule())
        self._display.trace_add("write", lambda *_: self._from_display())
        cpu_dynamic.add_listener(self._on_cpus)
        self.bind("<Destroy>", self._destroyed, add="+")
        self._settle()

    def refresh(self):
        """Relabels the words (after a value resolve() reads has changed)."""
        self._schedule()

    def _count(self, word):
        if word.lower() == MAX_WORD.lower():
            return cpu_dynamic.WSL_CPUS
        return self._resolve(word) if self._resolve is not None else None

    def _word(self, text):
        """The field's own spelling of `text` when it is one of its words, else None."""
        for word in self._words:
            if text.strip().lower() == word.lower():
                return word
        return None

    def _shown(self, value):
        word = self._word(value)
        return threads_choice.label(word, self._count(word)) if word else value

    def _from_display(self):
        text = threads_choice.word_of(self._display.get())
        if text != self.variable.get():
            self.variable.set(text)
        self._schedule()

    def _on_cpus(self, _count):
        self._schedule()

    def _schedule(self):
        if self._pending is None:
            try:
                self._pending = self.after_idle(self._settle)
            except tk.TclError:  # a trace of a variable that outlives the field
                pass

    def _settle(self):
        self._pending = None
        value = self.variable.get()
        fitted = threads_choice.fit(value, cpu_dynamic.WSL_CPUS, self._over)
        if fitted != value:
            self.variable.set(fitted)
        choices = threads_choice.choices(self._words, cpu_dynamic.WSL_CPUS, self._count)
        if [str(v) for v in self.cget("values")] != choices:
            self.configure(values=choices)
        shown = self._shown(fitted)
        if self._display.get() != shown and (
                self._word(fitted) or threads_choice.word_of(self._display.get()) != fitted):
            self._display.set(shown)

    def _destroyed(self, event):
        if event.widget is not self:
            return
        cpu_dynamic.remove_listener(self._on_cpus)
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        try:
            self.variable.trace_remove("write", self._variable_trace)
        except tk.TclError:
            pass
