"""
goldbach_paging.py -- page sizes shared by the Goldbach sub-tab's views and its
background job: the job computes one page of rows or pairs per call, the views draw
and page through them. Plain constants, no tkinter, so the job module does not depend
on the UI modules.
"""

GOLDBACH_VIZ_ROWS_PER_COL = 14  # per-n decomposition cards drawn in ONE column of the
    # Visualize diagram before wrapping to a new column -- see goldbach_viz_section.py's
    # multi-column layout, which fills the window's width instead of piling every row
    # into one narrow strip with empty space beside it.
GOLDBACH_VIZ_MAX_COLS = 3  # cap on how many columns the card grid wraps into, so a
    # huge window doesn't stretch the diagram absurdly wide.
GOLDBACH_CASCADE_ROW_CAP = GOLDBACH_VIZ_ROWS_PER_COL * GOLDBACH_VIZ_MAX_COLS
    # PAGE SIZE for the per-n decomposition rows, one backend goldbach_window_rows()
    # call per page (see row_offset there) -- the coverage verdict and counterexample
    # list are always computed over the FULL window regardless of which page is
    # requested. Prev/Next buttons in the Visualize window (goldbach_viz_section.py's
    # _on_goldbach_viz_row_prev/_next) step through pages of this size, matching the
    # pagination pattern used elsewhere for large lists (Primes tab preview,
    # benchmark log, etc. -- see _update_nav_controls).
GOLDBACH_DECOMPOSE_ROW_CAP = 300  # defensive cap on how many (p, q) pairs the "Decompose
    # number" detail window displays per page: goldbach_worker_section.py pages
    # goldbach_all_decompositions by it, and goldbach_decompose_section.py's
    # _goldbach_show_decomposition_detail draws one page. The buildable_from_base
    # verdict and total count are always computed over the FULL scan regardless of
    # this cap, only the displayed rows are truncated.
