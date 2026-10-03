"""
mode_registry.py -- every viz-mode the shared renderer can run, by its --viz-mode name.
Adding a visualization mode means adding one entry here; shared/ itself never names a
concrete mode.
"""

from primeatlas.visualization.rings.ring.ring_mode import RingMode
from primeatlas.visualization.rings.line.line_mode import LineMode

MODES = {
    RingMode.name: RingMode,
    LineMode.name: LineMode,
}

# The mode R (reset) returns to: the plain sequential rings view.
RESET_MODE = RingMode.name
