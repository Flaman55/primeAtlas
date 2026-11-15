"""TargetPlannerView: the Generation tab's target planner section. A Show/Hide button over a
collapsed body: the hint with a "How does it work?" button revealing the plain-language
how-to, the targets text field with Load file and Plan, the message line (no targets, bad
lines), the plan table and its summary, and Use, enabled while a row is selected.

The view holds no planning: on_plan(text), on_load() and on_use(group) are the section's
(target_planner_section.py); it shows what the section hands back.
"""
import tkinter as tk
from tkinter import ttk

from ..core.widgets import RevealFrame, StripedTreeview

COLUMNS = ("number", "floor", "from", "to", "windows", "targets", "method", "time")
_WIDTHS = {"number": 40, "floor": 50, "from": 220, "to": 220, "windows": 80, "targets": 70,
           "method": 120, "time": 90}


class TargetPlannerView(ttk.Labelframe):
    def __init__(self, parent, T, on_plan, on_load, on_use, wraplength=760):
        super().__init__(parent, text=T("target_planner.section_title"))
        self._T = T
        self._on_use = on_use
        self.groups = []
        self.toggle_button = ttk.Button(self, text=T("target_planner.show"),
                                        command=self._toggle)
        self.toggle_button.pack(anchor="w", padx=8, pady=(4, 4))
        self.body = RevealFrame(self, fill="x", padx=8, pady=(0, 6))

        hint = ttk.Frame(self.body)
        hint.pack(fill="x")
        ttk.Label(hint, text=T("target_planner.hint"), wraplength=wraplength, justify="left",
                  style="Hint.TLabel").pack(side="left")
        self.howto_button = ttk.Button(self.body, text=T("target_planner.howto_show"),
                                       command=self._toggle_howto)
        self.howto_button.pack(anchor="w", pady=(4, 0))
        self.howto_area = RevealFrame(self.body, fill="x", pady=(4, 0))
        self.howto_label = ttk.Label(self.howto_area, text=T("target_planner.howto"),
                                     wraplength=wraplength, justify="left")
        self.howto_label.pack(anchor="w")
        self._after_howto = ttk.Frame(self.body)
        self._after_howto.pack(fill="x")

        ttk.Label(self._after_howto, text=T("target_planner.field_targets")).pack(
            anchor="w", pady=(6, 2))
        self.text = tk.Text(self._after_howto, height=6, width=80, wrap="none")
        self.text.pack(fill="x")
        buttons = ttk.Frame(self._after_howto)
        buttons.pack(anchor="w", pady=(4, 0))
        self.load_button = ttk.Button(buttons, text=T("target_planner.load_button"),
                                      command=on_load)
        self.load_button.pack(side="left")
        self.plan_button = ttk.Button(buttons, text=T("target_planner.plan_button"),
                                      command=lambda: on_plan(self.get_text()))
        self.plan_button.pack(side="left", padx=(8, 0))

        self.message_var = tk.StringVar()
        ttk.Label(self._after_howto, textvariable=self.message_var, wraplength=wraplength,
                  justify="left").pack(anchor="w", pady=(4, 0))
        self.tree = StripedTreeview(self._after_howto, columns=COLUMNS, show="headings",
                                    height=6, selectmode="browse")
        for column in COLUMNS:
            self.tree.heading(column, text=T(f"target_planner.col_{column}"))
            self.tree.column(column, width=_WIDTHS[column], stretch=column in ("from", "to"),
                             anchor="w")
        self.tree.pack(fill="x", pady=(4, 0))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_use())
        self.summary_var = tk.StringVar()
        ttk.Label(self._after_howto, textvariable=self.summary_var, wraplength=wraplength,
                  justify="left").pack(anchor="w", pady=(4, 0))
        self.use_button = ttk.Button(self._after_howto, text=T("target_planner.use_button"),
                                     command=self._use, state="disabled")
        self.use_button.pack(anchor="w", pady=(4, 0))

    def _toggle(self):
        visible = not self.body.visible
        self.body.reveal(visible)
        self.toggle_button.configure(
            text=self._T("target_planner.hide" if visible else "target_planner.show"))

    def _toggle_howto(self):
        visible = not self.howto_area.visible
        self.howto_area.reveal(visible, before=self._after_howto)
        self.howto_button.configure(text=self._T(
            "target_planner.howto_hide" if visible else "target_planner.howto_show"))

    def get_text(self):
        return self.text.get("1.0", "end-1c")

    def set_text(self, text):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)

    def show_message(self, message):
        """A message instead of a plan: the table and the summary are cleared."""
        self.show_plan([], [], "")
        self.message_var.set(message)

    def show_plan(self, groups, rows, summary):
        """groups: the plan's target_planner.Group list; rows: their table values."""
        self.groups = list(groups)
        self.tree.delete(*self.tree.get_children())
        for values in rows:
            self.tree.insert("", "end", values=values)
        self.message_var.set("")
        self.summary_var.set(summary)
        self._sync_use()

    def _selected_group(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return self.groups[self.tree.index(selection[0])]

    def _sync_use(self):
        self.use_button.configure(
            state="normal" if self._selected_group() is not None else "disabled")

    def _use(self):
        group = self._selected_group()
        if group is not None:
            self._on_use(group)
