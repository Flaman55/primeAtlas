"""
app_const.py -- fixed values shared by the primeatlas/app/ modules: preview page sizes
and the startup update-check delay. Read as module attributes (_const.NAME), so a test
that reassigns one before building the app is seen by every tab.
"""

PAGE_SIZE = 500  # entries per page in the preview lists -- windows/hit files can hold
                  # 100k+ entries; decoding is cached per selection, only rendering is paged.
FLOOR_PAGE_SIZE = 200  # PRIME_WINDOW_*.bin files shown per page when a floor node is
                        # expanded in the "Prime numbers" tree -- separate from PAGE_SIZE
                        # above (that one pages through prime NUMBERS inside one file; this
                        # one pages through FILES inside one floor). A floor can hold
                        # thousands of windows -- reading every file's header AND
                        # inserting every file as a tree row on a single expand would
                        # freeze the GUI.


# Delay between the end of PortalBrowserApp.__init__ and the app self-update auto-check:
# long enough that it never competes with the loading screen or the two startup tree
# scans, short enough that it fires well within the first minute of a session.
APP_UPDATE_STARTUP_CHECK_DELAY_MS = 5000
