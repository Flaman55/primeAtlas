"""hardware_dynamic -- this computer's CPU/RAM details (core.hardware_details.HardwareDetails),
shared by the launch layer (each run records them in benchmark_machines.json) and the About
tab.

DETAILS is None until a read answers: the app reads them once at startup in the background,
and the About tab's read refreshes them through set_details(). A read with nothing known
(PowerShell failed) keeps known details: a failed read has not changed the hardware.
"""
from .hardware_details import HardwareDetails

DETAILS = None


def set_details(details):
    """Stores a read's answer; None or a read with nothing known changes nothing."""
    global DETAILS
    if details is None or details == HardwareDetails():
        return
    DETAILS = details
