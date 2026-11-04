"""
ui_state.py -- remembered form fields: one JSON file per install
(primeatlas/core/locales/ui_state.json, next to app_settings.json) holding the last value
of every remembered field as a flat {key: value} map, and remember(), which binds one tk
Variable or input widget to one key.

A remembered field is restored when its tab is built and saved whenever it changes, with
no Save or Run click. Writes are debounced (SAVE_DELAY_MS after the first change of a
burst) and atomic; PortalBrowserApp.destroy() flushes a pending write. The file is per
install, not per storage folder: switching the storage folder keeps the forms as they are.

Not remembered, by design: one-shot fields whose stale value would act on its own at the
next start (Quick-gen's starting point, the k-tuple reset-checkpoint box), status and
result labels, page and go-to fields, search boxes. The Settings tab (explicit Save
buttons, app_settings.json) and the visualization tabs (parameters saved at launch) keep
their own persistence.

The store itself is ui_state_store.UiStateStore (no tkinter import, so app_dynamic can open
it before any window exists); the app's store lives in ui_state_dynamic.STORE, which
remember() reads at call time.
"""
import tkinter as tk
from tkinter import ttk

from .ui_state_store import SAVE_DELAY_MS, UI_STATE_FILENAME, UiStateStore  # noqa: F401

_VALUE_TYPES = (
    (tk.BooleanVar, (bool,)),
    (tk.IntVar, (int,)),
    (tk.DoubleVar, (int, float)),
    (tk.StringVar, (str,)),
)


def _fits(var, value):
    for var_type, value_types in _VALUE_TYPES:
        if isinstance(var, var_type):
            return isinstance(value, value_types) and not (
                bool not in value_types and isinstance(value, bool))
    return True


def _attach_var(widget):
    """The widget's textvariable, or a new StringVar holding its current text, attached as
    its textvariable and kept on the widget (a collected StringVar would unset the Tcl
    variable and blank the field)."""
    name = str(widget.cget("textvariable"))
    existing = getattr(widget, "_ui_state_var", None)
    if existing is not None and str(existing) == name:
        return existing
    if name:
        var = tk.StringVar(master=widget, name=name)
    else:
        var = tk.StringVar(master=widget, value=widget.get())
        widget.configure(textvariable=var)
    widget._ui_state_var = var
    return var


def remember(key, target, *, store=None, restore=True, choices=None, widget=None):
    """Binds `target` (a tk Variable, or an Entry/Spinbox/Combobox, which gets a StringVar
    textvariable) to `key` and returns the Variable.

    restore=True puts the saved value into the field now, when there is one of the
    variable's type; restore=False only saves later changes (a form that already read its
    values from the store). A read-only Combobox (`target` itself, or `widget` for a
    Variable bound to one) restores only a value it currently lists. choices= gives the
    ids parallel to a read-only Combobox's translated labels: the id is saved and the
    label at the same position restored, so the value survives a language change; a dict
    {id: label} does the same for a Variable whose Combobox is built later."""
    if store is None:
        from . import ui_state_dynamic
        store = ui_state_dynamic.STORE
    if isinstance(target, tk.Variable):
        var = target
    else:
        widget = target
        var = _attach_var(target)
    combo = widget if isinstance(widget, ttk.Combobox) else None

    if restore and store.has(key):
        _restore(store.get(key), var, combo, choices)

    def _save(*_args):
        try:
            value = var.get()
        except tk.TclError:  # e.g. an IntVar holding typed text
            return
        if choices is not None:
            ids, labels = _choice_lists(choices, combo)
            if value not in labels:
                return
            value = ids[labels.index(value)]
        store.set(key, value)

    var.trace_add("write", _save)
    return var


def _choice_lists(choices, combo):
    """(ids, labels) of a choices= argument: a dict's keys and values, or a list of ids
    parallel to the Combobox's current values."""
    if isinstance(choices, dict):
        return list(choices), list(choices.values())
    labels = [str(v) for v in combo.cget("values")] if combo is not None else []
    return list(choices), labels


def _restore(value, var, combo, choices):
    if choices is not None:
        ids, labels = _choice_lists(choices, combo)
        if value in ids and ids.index(value) < len(labels):
            var.set(labels[ids.index(value)])
        return
    if not _fits(var, value):
        return
    if combo is not None and "readonly" in str(combo.cget("state")):
        if str(value) not in [str(v) for v in combo.cget("values")]:
            return
    try:
        var.set(value)
    except tk.TclError:
        pass
