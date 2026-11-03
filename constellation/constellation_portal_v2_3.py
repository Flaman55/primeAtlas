"""
constellation_portal_v2_3.py -- the portal root a constellation/k-tuple CLI run works in.
The entry scripts (constellation_finder_v2_3.py, ktuple_sieve_v2_2.py) call
default_portal_folder() once and pass the result down as the `portal` argument of every
function that touches disk; no module keeps it as a global.
"""
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def default_portal_folder():
    """CONSTELLATION_PORTAL_DIR when set (the GUI's Settings tab points it at a custom
    storage location), else a CONSTELLATION_PORTAL folder next to the application root
    (one level up from this file), matching AppSettings.default_storage_path."""
    return os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
        os.path.join(_SCRIPT_DIR, "..", "CONSTELLATION_PORTAL"))
