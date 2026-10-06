"""
mode_registry.py -- every viz-mode the shared renderer can run, by its --viz-mode name.
Adding a visualization mode means adding one entry here; shared/ itself never names a
concrete mode.
"""

from primeatlas.visualization.rings.ring.ring_mode import RingMode
from primeatlas.visualization.rings.line.line_mode import LineMode
from primeatlas.visualization.tree.tree_mode import TreeMode
from primeatlas.visualization.assembly.assembly_mode import AssemblyMode
from primeatlas.visualization.sphere.sphere_mode import SphereMode

MODES = {
    RingMode.name: RingMode,
    LineMode.name: LineMode,
    TreeMode.name: TreeMode,
    AssemblyMode.name: AssemblyMode,
    SphereMode.name: SphereMode,
}
