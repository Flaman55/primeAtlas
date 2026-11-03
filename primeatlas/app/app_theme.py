"""
app_theme.py -- ThemeMixin of PortalBrowserApp: the font scale and the ttk/Tk color
palette, applied once in __init__ before any child widget exists.
"""
from tkinter import ttk

from primeatlas.app import app_dynamic as _dyn


class ThemeMixin:
    def _apply_font_scale(self, percent):
        """Multiplies `tk scaling` (pixels per point) by percent/100 before any widget
        is built, so every point-sized font -- named fonts and explicit ("Consolas", 9)
        tuples, canvas text included -- grows by the same factor. Pixel sizes (column
        widths, wraplength, paddings) are unaffected; content-fitted widths follow the
        fonts. The named fonts are reconfigured so they re-resolve their point size
        under the new scaling. Restart-required, same as the theme."""
        import tkinter.font as tkfont
        if percent == 100:
            return
        base = float(self.tk.call("tk", "scaling"))
        self.tk.call("tk", "scaling", base * percent / 100)
        for name in tkfont.names(self):
            named = tkfont.nametofont(name, root=self)
            named.configure(size=named.cget("size"))

    def _apply_theme(self, theme_name):
        """Applies primeatlas.core.theme's color palette to every widget class this app
        actually uses -- called once, in __init__, BEFORE any child widget is
        created, so everything built afterward picks up the new colors through
        normal ttk style inheritance / Tk option-database lookup instead of
        needing a live re-walk of the whole widget tree once it already exists.
        Same restart-required UX as `language` (see i18n.py's docstring) --
        Settings > General's theme picker (settings_tab.py) only writes the choice
        to AppSettings, it does not attempt to re-theme the already-built app.

        Two coloring mechanisms, because this app mixes ttk and raw tk widgets:
          - ttk widgets (the large majority -- Frame/Label/Button/Entry/Combobox/
            Checkbutton/Radiobutton/Labelframe/Notebook/Treeview/Scrollbar/
            Panedwindow/Progressbar/Spinbox -- grep-verified against every
            ttk.* call in this file plus settings_tab.py/generation_console.py)
            only obey ttk.Style(), never the Tk option database -- every style
            name actually used anywhere in this app is configured below.
          - the handful of raw tk widgets (tk.Text inside GenerationConsole/
            ScrolledText, tk.Listbox backing every readonly ttk.Combobox's own
            dropdown, tk.Canvas for the Visualize/constellation diagrams) obey
            the Tk option DATABASE instead -- root.option_add() below, which only
            takes effect for widgets that don't pass an explicit bg/fg at
            construction time. The two benchmark-chart Canvases (see
            single_tabs_section.py's _build_benchmark_tab) DO pass an explicit background="white" already
            and are deliberately left untouched here: their plotted line colors
            were chosen assuming a white plot area, and darkening just the
            background without re-picking every plotted series' color would make
            them harder to read, not easier -- consistent with "add
            functionality, don't replace it", this leaves that pre-existing
            choice alone rather than overriding it.

        'clam' is forced as the base ttk theme regardless of the platform
        default (Windows normally defaults to 'vista'/'winnative', which
        silently IGNORES most background/foreground style.configure() calls for
        common widgets -- a well-known tkinter limitation) -- without this, a
        dark palette would visually do nothing on Windows, which is where this
        app actually runs."""
        import tkinter.font as tkfont
        from primeatlas.core.theme import adjusted_palette
        from primeatlas.core.widgets import set_stripe_background
        p = adjusted_palette(theme_name, *_dyn.APP_SETTINGS.theme_brightness(theme_name))
        self._palette = p

        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=p["bg"], foreground=p["fg"],
                         fieldbackground=p["field_bg"])
        style.map(".", foreground=[("disabled", p["disabled_fg"])])

        for cls in ("TFrame", "TLabelframe", "TLabelframe.Label", "TLabel",
                    "TCheckbutton", "TRadiobutton", "TPanedwindow"):
            style.configure(cls, background=p["bg"], foreground=p["fg"])
        # Hint.TLabel: explanatory/secondary text; Status.TLabel: the bottom status line.
        style.configure("Hint.TLabel", foreground=p["hint_fg"])
        status_font = tkfont.nametofont("TkDefaultFont", root=self).actual()
        status_font["weight"] = "bold"
        self._status_font = tkfont.Font(root=self, **status_font)
        style.configure("Status.TLabel", font=self._status_font)
        # Title.TLabel: the About tab's app name; Link.TLabel: clickable links.
        title_font = tkfont.nametofont("TkDefaultFont", root=self).actual()
        title_font.update(weight="bold", size=round(abs(title_font["size"]) * 1.8))
        self._title_font = tkfont.Font(root=self, **title_font)
        style.configure("Title.TLabel", font=self._title_font)
        link_font = tkfont.nametofont("TkDefaultFont", root=self).actual()
        link_font["underline"] = True
        self._link_font = tkfont.Font(root=self, **link_font)
        style.configure("Link.TLabel", foreground=p["link_fg"], font=self._link_font)
        style.map("TCheckbutton", background=[("active", p["bg"])])
        style.map("TRadiobutton", background=[("active", p["bg"])])

        style.configure("TButton", background=p["field_bg"], foreground=p["fg"])
        style.map("TButton",
                  background=[("active", p["select_bg"]), ("disabled", p["bg"])],
                  foreground=[("disabled", p["disabled_fg"])])

        style.configure("TEntry", fieldbackground=p["field_bg"], foreground=p["field_fg"],
                         insertcolor=p["field_fg"])
        style.map("TEntry", fieldbackground=[("disabled", p["bg"])])
        style.configure("TSpinbox", fieldbackground=p["field_bg"], foreground=p["field_fg"],
                         background=p["field_bg"], arrowcolor=p["fg"])

        style.configure("TCombobox", fieldbackground=p["field_bg"], foreground=p["field_fg"],
                         background=p["field_bg"], arrowcolor=p["fg"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", p["field_bg"]), ("disabled", p["bg"])],
                  foreground=[("readonly", p["field_fg"])])
        # ttk.Combobox's dropdown is internally a raw tk.Listbox, NOT a ttk
        # widget -- it obeys the option database, not ttk.Style().
        self.option_add("*TCombobox*Listbox.background", p["field_bg"])
        self.option_add("*TCombobox*Listbox.foreground", p["field_fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", p["select_bg"])
        self.option_add("*TCombobox*Listbox.selectForeground", p["select_fg"])

        style.configure("TNotebook", background=p["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=p["tab_bg"], foreground=p["fg"])
        # Hover ("active") highlights a tab like a button; "selected" is listed first
        # so the current tab keeps its own color while hovered.
        style.map("TNotebook.Tab",
                  background=[("selected", p["tab_selected_bg"]), ("active", p["select_bg"])],
                  foreground=[("selected", p["fg"]), ("active", p["select_fg"])])

        # The clam theme's rowheight is a fixed pixel value; it follows the font so
        # a larger font scale does not clip rows.
        row_height = tkfont.nametofont("TkDefaultFont", root=self).metrics("linespace") + 2
        style.configure("Treeview", background=p["tree_bg"], fieldbackground=p["tree_bg"],
                         foreground=p["fg"], rowheight=row_height)
        set_stripe_background(p["tree_alt_bg"])
        style.map("Treeview",
                  background=[("selected", p["select_bg"])],
                  foreground=[("selected", p["select_fg"])])
        style.configure("Treeview.Heading", background=p["tab_bg"], foreground=p["fg"])
        style.map("Treeview.Heading", background=[("active", p["select_bg"])])

        style.configure("TScrollbar", background=p["tab_bg"], troughcolor=p["bg"],
                         arrowcolor=p["fg"], bordercolor=p["bg"])
        style.configure("TProgressbar", background=p["select_bg"], troughcolor=p["field_bg"])
        style.configure("TSeparator", background=p["border"])

        self.configure(background=p["bg"])
        self.option_add("*Background", p["bg"])
        self.option_add("*Foreground", p["fg"])
        self.option_add("*Text.Background", p["console_bg"])
        self.option_add("*Text.Foreground", p["console_fg"])
        self.option_add("*Text.insertBackground", p["console_fg"])
        self.option_add("*Listbox.Background", p["field_bg"])
        self.option_add("*Listbox.Foreground", p["field_fg"])
        self.option_add("*Canvas.Background", p["bg"])
        self.option_add("*Entry.Background", p["field_bg"])
        self.option_add("*Entry.Foreground", p["field_fg"])
