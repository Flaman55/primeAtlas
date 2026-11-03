"""
constellation_dynamic_v2_2.py -- values computed once at import and read by several
constellation_*_v2_2 modules: the portal root (PORTAL_FOLDER) and the import path of
the sibling prime_sieve/ folder. Read as module attributes (_dyn.PORTAL_FOLDER), so a
test that reassigns one is seen by every module. Imported first by each sibling, since
it puts prime_sieve/ on sys.path.
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Self-contained alongside the rest of the app: prime_sieve_v1, window_sharding and
# hit_paging live in the sibling folder ../prime_sieve/.
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "prime_sieve"))

# CONSTELLATION_PORTAL_DIR: optional override for the portal's root folder, used by the
# GUI's Settings tab to point at a custom storage location. Falls back to a
# CONSTELLATION_PORTAL folder next to the application root (one level up from this
# file) when unset, matching AppSettings.default_storage_path.
PORTAL_FOLDER = os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
    os.path.join(_SCRIPT_DIR, "..", "CONSTELLATION_PORTAL"))
