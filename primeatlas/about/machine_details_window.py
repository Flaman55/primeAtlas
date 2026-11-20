"""
machine_details_window.py -- MachineDetailsWindow, the window for the values of this computer
that Windows cannot read (machines_file.MANUAL_FIELDS): architecture, release year, turbo
clock, RAM CL and XMP/EXPO, with a how-to of where to find them (BIOS/UEFI only as an option
for advanced users) and, next to XMP/EXPO, a hint when the configured RAM speed is above the
JEDEC maximum of its type (hardware_details.xmp_hint()). Atlas never fills these itself.

The fields start from the entry's typed values. Save stores them on the current entry
(machines_file.set_manual(), blank = None) and closes; a red number field refuses Save.
Cancel and the window's close button store nothing. Opened by about.machine_prompt.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from ..core import hardware_details, machines_file, number_field
from ..core.number_text import number_value
from .system_info_text import gib_text

WRAP = 520
# (attribute, label key, tip key, minimum, maximum, manual field) of the number fields.
NUMBER_FIELDS = (
    ("year", "machine.label_year", "field_tip.machine_year", 1970, 2100, "year"),
    ("turbo", "machine.label_turbo", "field_tip.machine_turbo", 100, 10000, "turbo_mhz"),
    ("cl", "machine.label_cl", "field_tip.machine_cl", 1, 100, "cl"),
)


class MachineDetailsWindow(tk.Toplevel):
    def __init__(self, parent, T, storage, machine_id, entry, on_closed=None):
        super().__init__(parent)
        self.T = T
        self._storage = storage
        self._machine_id = machine_id
        self._on_closed = on_closed
        self.title(T("machine.window_title"))
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.protocol_close)
        manual = entry.get("manual") or {}
        auto = entry.get("auto") or {}

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ram = (f"{gib_text(auto.get('ram_bytes'), T)} {auto.get('ram_type') or ''}"
               f"{'-' + str(auto['ram_mts']) if auto.get('ram_mts') else ''}").strip()
        ttk.Label(body, text=T("machine.read_from_windows",
                               cpu=auto.get("cpu_name") or T("about.system_unknown"), ram=ram),
                  wraplength=WRAP, justify="left").grid(row=0, column=0, columnspan=3,
                                                        sticky="w", pady=(0, 8))
        ttk.Label(body, text=T("machine.howto"), wraplength=WRAP,
                  justify="left").grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(body, text=T("machine.howto_bios"), style="Hint.TLabel", wraplength=WRAP,
                  justify="left").grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 10))

        self.architecture_var = tk.StringVar(value=manual.get("architecture") or "")
        ttk.Label(body, text=T("machine.label_architecture")).grid(row=3, column=0, sticky="w")
        # not a number field: the architecture is a name (Zen 3, Raptor Lake)
        ttk.Entry(body, textvariable=self.architecture_var,
                  width=24).grid(row=3, column=1, sticky="w", pady=2)

        self.number_entries = []
        for row, (attr, label, tip, low, high, field) in enumerate(NUMBER_FIELDS, start=4):
            value = manual.get(field)
            var = tk.StringVar(value="" if value is None else str(value))
            setattr(self, f"{attr}_var", var)
            ttk.Label(body, text=T(label)).grid(row=row, column=0, sticky="w")
            entry_widget = ttk.Entry(body, textvariable=var, width=10)
            entry_widget.grid(row=row, column=1, sticky="w", pady=2)
            number_field.attach(entry_widget, T, tip, minimum=low, maximum=high)
            self.number_entries.append(entry_widget)

        xmp = manual.get("xmp")
        self.xmp_var = tk.StringVar(value="" if xmp is None
                                    else T("machine.xmp_on") if xmp else T("machine.xmp_off"))
        ttk.Label(body, text=T("machine.label_xmp")).grid(row=7, column=0, sticky="w")
        self.xmp_box = ttk.Combobox(body, textvariable=self.xmp_var, state="readonly", width=12,
                                    values=["", T("machine.xmp_on"), T("machine.xmp_off")])
        self.xmp_box.grid(row=7, column=1, sticky="w", pady=2)
        jedec = hardware_details.xmp_hint(auto.get("ram_type"), auto.get("ram_mts"))
        hint = (T("machine.xmp_hint", mts=auto.get("ram_mts"), type=auto.get("ram_type"),
                  jedec=jedec) if jedec else "")
        self.xmp_hint = ttk.Label(body, text=hint, style="Hint.TLabel", wraplength=WRAP - 200,
                                  justify="left")
        self.xmp_hint.grid(row=7, column=2, sticky="w", padx=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text=T("machine.save"), command=self.save).pack(side="left")
        ttk.Button(buttons, text=T("machine.cancel"),
                   command=self.cancel).pack(side="left", padx=(6, 0))

    def _manual(self):
        xmp = self.xmp_var.get()
        values = {field: number_value(getattr(self, f"{attr}_var").get())
                  for attr, _l, _t, _lo, _hi, field in NUMBER_FIELDS}
        values["architecture"] = self.architecture_var.get()
        values["xmp"] = (True if xmp == self.T("machine.xmp_on")
                         else False if xmp == self.T("machine.xmp_off") else None)
        return values

    def save(self):
        variables = [getattr(self, f"{attr}_var") for attr, *_rest in NUMBER_FIELDS]
        if number_field.refuse_problem(variables, self.T, self.T("machine.title")):
            return
        try:
            machines_file.set_manual(self._storage, self._machine_id, self._manual())
        except (machines_file.MachinesFileCorrupt, KeyError, OSError) as error:
            messagebox.showerror(self.T("machine.title"), str(error), parent=self)
            return
        self._close()

    def cancel(self):
        self._close()

    def protocol_close(self):
        self._close()

    def _close(self):
        self.destroy()
        if self._on_closed is not None:
            self._on_closed()
