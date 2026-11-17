"""number_field -- attach(entry, T, ...): the app-wide behaviour of a field that takes a number
(an Entry or a Spinbox): a whole number by default, a fraction with fraction=True, also one of
`words` (e.g. "Auto"), within an optional minimum/maximum (a callable follows a changing cap);
`text_of` turns the shown text into the text read (a label "Max (8)" read as "Max").

The field's text is read by core.number_text on every change, typed, pasted or set by code
through its textvariable:
  - a whole number or an empty field: nothing shown, normal style;
  - invalid or out-of-range text: the field turns red (INVALID_STYLE, INVALID_SPINBOX_STYLE,
    colour from the theme palette);
  - ambiguous text ("3,000": 3000 or 3): while the field has focus, a popup under it,
    "Could be:" and one button per reading; a click writes that number's plain digits into
    the field. Left ambiguous, the field turns red (no value is taken) and its hover tip
    lists the readings; coming back reopens the popup.
A whole number or an empty field clears the red and the popup at once; red and the popup wait
SETTLE_MS after the last change (typing "1,000,000" passes through the ambiguous "1,000") and
show at once when the field is left.
Hovering the field for TIP_DELAY_MS shows the accepted forms (and why the text is invalid)
in an InfoTip below the field; nothing while the popup is open. problem_field(variables)
names a field whose text is not a usable value, so a run can refuse it instead of falling
back to a default.
"""
import tkinter as tk
import weakref
from tkinter import ttk

from .info_tip import GAP_PX, InfoTip
from .number_text import AMBIGUOUS, INVALID, read_number

INVALID_STYLE = "Invalid.TEntry"
INVALID_SPINBOX_STYLE = "Invalid.TSpinbox"
AMBIGUOUS_PROBLEM = "ambiguous"
RANGE_PROBLEM = "range"
TIP_DELAY_MS = 600          # rest on a field before its hint shows: passing over shows nothing
FOCUS_OUT_GRACE_MS = 150    # a click on the popup's button lands before it closes
SETTLE_MS = 600             # pause in typing before red or the popup shows


_FIELDS = weakref.WeakSet()


def attach(entry, T, fraction=False, words=(), minimum=None, maximum=None, text_of=None):
    """Makes `entry` (ttk.Entry or ttk.Spinbox) a number field; returns its NumberField."""
    return NumberField(entry, T, fraction, words, minimum, maximum, text_of)


def problem_field(variables):
    """The first number field bound to one of `variables` whose text is not a usable value
    (invalid, ambiguous or out of range), or None. An empty field is no problem."""
    names = {str(v) for v in variables}
    for field in list(_FIELDS):
        # A ThreadsField shows a form variable it does not own (`variable`).
        shown = {field.variable_name, str(getattr(field.entry, "variable", ""))}
        if shown & names and field.problem is not None:
            return field
    return None


def refuse_problem(variables, T, title):
    """True (after an error naming the reason, with the cursor in the field) when one of the
    number fields bound to `variables` holds no usable value; a run calls it first."""
    field = problem_field(variables)
    if field is None:
        return False
    from tkinter import messagebox
    messagebox.showerror(title, T("number_field.fix_field", reason=field.problem_text()))
    try:
        field.entry.focus_set()
        field.refresh(at_once=True)
    except tk.TclError:
        pass
    return True


def _bound(limit):
    return limit() if callable(limit) else limit


class NumberField:
    def __init__(self, entry, T, fraction=False, words=(), minimum=None, maximum=None,
                 text_of=None):
        self.entry = entry
        self._text_of = text_of
        entry.number_field = self
        self._T = T
        self._fraction = fraction
        self._words = tuple(words)
        self._minimum = minimum
        self._maximum = maximum
        kind = entry.winfo_class()
        self._style = str(entry.cget("style")) or kind
        self._invalid_style = INVALID_SPINBOX_STYLE if kind == "TSpinbox" else INVALID_STYLE
        self.reading = read_number("")
        self.problem = None
        self.popup = None
        self.popup_title = ""
        self.candidate_buttons = []
        self._settle = None
        self.tip = InfoTip(entry.master, self._tip_text, anchor=entry, below=True,
                           delay_ms=TIP_DELAY_MS)
        self._trace = None
        self._hook_variable()
        _FIELDS.add(self)
        for event in ("<KeyRelease>", "<<Paste>>", "<<Cut>>"):
            entry.bind(event, lambda _e: entry.after_idle(self.refresh), add="+")
        entry.bind("<FocusIn>", lambda _e: self._late_variable() or self.refresh(at_once=True),
                   add="+")
        entry.bind("<FocusOut>", lambda _e: entry.after(FOCUS_OUT_GRACE_MS, self._focus_left),
                   add="+")
        entry.bind("<Destroy>", self._destroyed, add="+")
        self.refresh(at_once=True)
        # core.ui_state.remember() gives a bare entry its textvariable (and the saved value)
        # after the tab has built the field.
        entry.after_idle(self._late_variable)

    @property
    def variable_name(self):
        return self._trace[0] if self._trace else None

    def _hook_variable(self):
        """Follows the entry's textvariable, if it has one and it is not followed yet."""
        name = str(self.entry.cget("textvariable"))
        if not name or (self._trace and self._trace[0] == name):
            return False
        self._unhook_variable()
        entry = self.entry
        # Tcl runs the newest trace first, before the entry's own trace has copied the value
        # into the widget, so the value is read from the variable itself.
        command = entry.register(lambda *_a: self.refresh(entry.tk.globalgetvar(name)))
        entry.tk.call("trace", "add", "variable", name, "write", command)
        self._trace = (name, command)
        return True

    def _unhook_variable(self):
        if self._trace is not None:
            name, command = self._trace
            try:
                self.entry.tk.call("trace", "remove", "variable", name, "write", command)
                self.entry.deletecommand(command)
            except tk.TclError:
                pass
            self._trace = None

    def _late_variable(self):
        if self._alive() and self._hook_variable():
            self.refresh(at_once=True)

    def refresh(self, text=None, at_once=False):
        try:
            text = self.entry.get() if text is None else str(text)
        except tk.TclError:
            return
        if self._text_of is not None:
            text = self._text_of(text)
        self.reading = read_number(text, fraction=self._fraction, words=self._words)
        self.problem = self._problem()
        self._cancel_settle()
        if at_once or self.problem is None:
            self._apply()
        else:
            self._settle = self.entry.after(SETTLE_MS, self._apply)

    def _alive(self):
        try:
            return bool(self.entry.winfo_exists())
        except tk.TclError:
            return False

    def _problem(self):
        state, value = self.reading.state, self.reading.value
        if state == INVALID:
            return self.reading.reason
        if state == AMBIGUOUS:
            return AMBIGUOUS_PROBLEM
        if value is None or isinstance(value, str):
            return None
        low, high = _bound(self._minimum), _bound(self._maximum)
        if (low is not None and value < low) or (high is not None and value > high):
            return RANGE_PROBLEM
        return None

    def problem_text(self):
        """Why the text is not a usable value ("" when it is)."""
        problem = self.problem
        if problem is None:
            return ""
        if problem == AMBIGUOUS_PROBLEM:
            return self._T("number_field.could_be") + " " + " / ".join(
                str(v) for v in self.reading.candidates)
        if problem == RANGE_PROBLEM:
            low, high = _bound(self._minimum), _bound(self._maximum)
            if low is None:
                return self._T("number_field.reason_max", high=high)
            if high is None:
                return self._T("number_field.reason_min", low=low)
            return self._T("number_field.reason_range", low=low, high=high)
        return self._T(f"number_field.reason_{problem}")

    def _apply(self):
        self._settle = None
        if not self._alive():
            return
        problem = self.problem
        focused = self._focused()
        red = problem is not None and (problem != AMBIGUOUS_PROBLEM or not focused)
        self.entry.configure(style=self._invalid_style if red else self._style)
        if problem == AMBIGUOUS_PROBLEM and focused:
            if self.popup is None or [b.cget("text") for b in self.candidate_buttons] != [
                    str(v) for v in self.reading.candidates]:
                self._show_popup(self.reading.candidates)
        else:
            self._hide_popup()

    def _focused(self):
        try:
            return self.entry.focus_get() is self.entry
        except (tk.TclError, KeyError):
            return False

    def _cancel_settle(self):
        if self._settle is not None:
            self.entry.after_cancel(self._settle)
            self._settle = None

    def _tip_text(self):
        if self.popup is not None:
            return ""
        text = self._T("number_field.help")
        if self._fraction:
            text += "\n" + self._T("number_field.help_fraction")
        if self.problem is not None:
            text += "\n\n" + self.problem_text()
        return text

    def _show_popup(self, candidates):
        self._hide_popup()
        self.tip.hide()
        entry = self.entry
        popup = tk.Toplevel(entry)
        popup.wm_overrideredirect(True)
        frame = ttk.Frame(popup, padding=6, relief="solid", borderwidth=1)
        frame.pack()
        self.popup_title = self._T("number_field.could_be")
        ttk.Label(frame, text=self.popup_title).pack(anchor="w")
        self.candidate_buttons = []
        for value in candidates:
            button = ttk.Button(frame, text=str(value), takefocus=0,
                                command=lambda v=value: self._choose(v))
            button.pack(anchor="w", fill="x", pady=(2, 0))
            self.candidate_buttons.append(button)
        popup.update_idletasks()
        top = entry.winfo_toplevel()
        right = top.winfo_rootx() + top.winfo_width()
        x = max(top.winfo_rootx(), min(entry.winfo_rootx(), right - popup.winfo_reqwidth()))
        y = entry.winfo_rooty() + entry.winfo_height() + GAP_PX
        popup.wm_geometry(f"+{x}+{y}")
        self.popup = popup

    def _hide_popup(self):
        if self.popup is not None:
            try:
                self.popup.destroy()
            except tk.TclError:
                pass
        self.popup = None
        self.candidate_buttons = []

    def _choose(self, value):
        self.entry.delete(0, "end")
        self.entry.insert(0, str(value))
        self.refresh()

    def _focus_left(self):
        if not self._alive():
            return
        if self._settle is not None:
            self._cancel_settle()
            self._apply()
        if self.popup is None:
            if self.problem == AMBIGUOUS_PROBLEM:
                self._apply()
            return
        try:
            focus = self.entry.focus_get()
            x, y = self.popup.winfo_pointerxy()
            under = self.popup.winfo_containing(x, y)
        except (tk.TclError, KeyError):
            focus = under = None
        if focus is self.entry or (under is not None
                                   and str(under).startswith(str(self.popup))):
            return
        self._hide_popup()
        self._apply()

    def _destroyed(self, event):
        if event.widget is not self.entry:
            return
        self._cancel_settle()
        self._hide_popup()
        self.tip.hide()
        self._unhook_variable()
        _FIELDS.discard(self)
