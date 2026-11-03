"""
constellation_const_v2_3.py -- fixed values shared by the constellation_*_v2_3 modules:
the per-floor state file names under 10p{N}/constellations/, the portal-root stop
marker and the diagnostics switch. Read as module attributes (_const.NAME).
"""

CHECKPOINT_FILENAME = "CHECKPOINT.txt"
WINDOW_INDEX_FILENAME = "WINDOW_INDEX.tsv"
LAST_VALUES_FILENAME = "LAST_VALUES.tsv"
# Portal-ROOT (not per-floor) marker, checked once per window in process_floor()'s own
# loop -- see that function's docstring for why a graceful, window-boundary-only
# stop matters here (append_prime_window()'s header-then-payload write order means a
# kill mid-window could corrupt a hit file, not just lose progress). One marker for the
# whole portal is enough since the GUI never runs more than one constellation_finder_
# v2_2.py instance at a time (same assumption WslLoggedRunner's own kill_pattern already
# relies on). Written by the GUI's Stop handler (constellation_section.py), never by
# this script -- this side only ever reads it.
STOP_REQUEST_FILENAME = "STOP_REQUEST.txt"

# Crash-diagnosis instrumentation for process_floor()'s per-window loop (heartbeat line
# every HEARTBEAT_EVERY windows, plus fsync'd step-by-step detail for the first
# DETAILED_DIAG_WINDOWS windows of every batch), to locate which sub-step
# (read/peek/match/checkpoint) a silently dying WSL process was in. Off by default; set
# True while diagnosing a crash. Checked per branch (not around an already-built print()),
# so disabling it also skips the string-building/timing work.
CONSTELLATION_DIAG_ENABLED = False

#: Every window name this floor's scan has finished, one per line, append-only. Tracked
#: by name rather than by done_range= lines: "first|last" resolves against the CURRENT
#: window list, so a window generated later between two scanned ones would count as done
#: without being searched. With the log, the search covers exactly the windows in storage
#: that are not in it, wherever they lie (the same name-based diff backup/restore uses).
#: CHECKPOINT.txt keeps its ranges (GUI progress, backups, and the fallback for a floor
#: whose log does not exist yet).
DONE_LOG_FILENAME = "DONE_WINDOWS.txt"

BOUNDARY_MARKER_FILENAME = "BOUNDARY_CHECKED.txt"
