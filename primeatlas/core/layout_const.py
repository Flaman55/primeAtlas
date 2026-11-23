"""
layout_const.py -- the default layout of the app's resizable parts, in one place: the
height of every height grip, the share of every remembered sash and the main window.
Settings > General > "Default layout" (layout_memory.reset_layout) brings these back.

Every value is arbitrary. The line counts fill a 1280 x 720 window about as the lists
stretched to it before the grips owned their height; the person sets their own with the
grips, and layout_memory keeps it in ui_state.json.
"""

# The main window before anything is remembered: maximized; WINDOW_SIZE is its size
# when it is made normal (no position: the window manager places it).
WINDOW_SIZE = (1280, 680)
WINDOW_STATE = "zoomed"

# Charts (Canvas): heights in pixels, a grip step is CHART_STEP_PX.
CHART_STEP_PX = 10
CHART_HEIGHT_PX = 220
CHART_MIN_PX = 120
CHART_MAX_PX = 900

# Line-sized widgets (Text, Listbox, Treeview): heights in lines or rows.
MIN_LINES = 3
MAX_LINES = 200

_LINES = (MIN_LINES, MAX_LINES)
_CHART = (CHART_MIN_PX, CHART_MAX_PX)

# place -> (default, min, max). default None: the widget's owner sizes it until the person
# drags the grip (the Records table follows its row count). A terminal's grip is
# "console.<place>".
GRIPS = {
    "primes.storage": (27, *_LINES),
    "primes.primality_results": (3, 2, MAX_LINES),
    "constellations.storage": (32, *_LINES),
    "constellations.search_results": (5, *_LINES),
    "constellations.calculator": (25, *_LINES),
    "constellations.records": (None, *_LINES),
    "constellations.records_detail": (17, *_LINES),
    "constellations.density": (8, *_LINES),
    "constellations.density_chart": (260, *_CHART),
    "research.squares": (22, *_LINES),
    "research.goldbach": (21, *_LINES),
    "research.gaps": (21, *_LINES),
    "research.pi_approx": (22, *_LINES),
    "research.polynomials": (21, *_LINES),
    "irreducibility.arithmetic": (32, *_LINES),
    "irreducibility.multiplicative": (35, *_LINES),
    "irreducibility.multiplicative_chart": (170, *_CHART),
    "irreducibility.primality": (27, *_LINES),
    "irreducibility.compare": (12, *_LINES),
    "irreducibility.ranges": (5, *_LINES),
    "irreducibility.comb_chart": (240, *_CHART),
    "planner.targets": (6, *_LINES),
    "planner.table": (6, *_LINES),
    "benchmark.table": (10, *_LINES),
    "benchmark.sieve_chart": (CHART_HEIGHT_PX, *_CHART),
    "benchmark.run_chart": (CHART_HEIGHT_PX, *_CHART),
    "benchmark.ram_chart": (CHART_HEIGHT_PX, *_CHART),
    "settings.backups": (5, *_LINES),
    "settings.incomplete": (3, 2, MAX_LINES),
    "settings.full_backup_lists": (5, *_LINES),
    "settings.storage_integrate_results": (5, *_LINES),
    "about.changes": (8, *_LINES),
    "about.notice": (10, *_LINES),
    "console.generation.loop": (20, *_LINES),
    "console.generation.ktuple": (20, *_LINES),
    "console.generation.constellation": (20, *_LINES),
    "console.generation.verify": (12, *_LINES),
    "console.settings.restore": (8, *_LINES),
    "console.settings.full_backup": (5, *_LINES),
    "console.settings.storage_integrate": (4, *_LINES),
    "console.settings.pseudosquares": (5, *_LINES),
    "console.settings.libs": (5, *_LINES),
    "console.settings.primecount": (5, *_LINES),
    "console.settings.cudasieve": (5, *_LINES),
    "console.visualization.rings": (14, *_LINES),
    "console.visualization.sphere": (14, *_LINES),
    "console.visualization.tree": (14, *_LINES),
}

# place -> the first pane's default share of a remembered two-pane sash.
SASH_SHARES = {
    "constellations.storage": 1 / 3,
}
