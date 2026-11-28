# Module: primes (Prime numbers tab)

The Prime numbers tab: the Storage sub-tab (floors and their PGS2 windows, paged previews, search for
one prime, D/P windows and "Verify P against D"), the primesieve calculator and the primality tests.

## Files

| Part | Files |
|---|---|
| Storage sub-tab | `primeatlas/primes/primes_tab.py` (`PrimesTab`), `primes_tree_coordinator.py` (background floor scan) |
| primesieve calculator | `primeatlas/primality/primesieve_calc_tab.py` (count/nth/next/prev through WSL libprimesieve) |
| Primality tests | `primeatlas/primality/primality_tab.py` (UI), `primality.py` (Miller-Rabin, Fermat, Solovay-Strassen, factorization; sympy optional) |

## Contract

| In | Out |
|---|---|
| storage path, a number to find, Refresh | floor tree with totals, window previews, search result or an offer to generate the missing window |

Search runs on the shared search worker (`core/totals_search_coordinator.py`); a missing window is
offered to the Generation tab through `generation_offer_coordinator.py`.

Layout of the Storage sub-tab: the tree pane's width is the wider of the tree's columns (fitted
to their texts) and the floor nav's widest group (`_tree_pane_width()`), or less while the window
is too narrow for it (`_tree_pane_room()`): the detail pane keeps its minimum width (its page
navigation's wider group: the page jump group goes under the buttons in a narrow pane), so both panes stay in view and the tree scrolls sideways. The layout coordinator
(`core/responsive.py`) sets it on a window or content width change; a sash drag snaps back to it.
The floor nav is a `FlowRow` of the app-wide page-nav groups and the page subtotal, laid out for
the tree pane's width.
The tree's horizontal scrollbar is always packed, disabled while the columns fit, so it never
changes the tree's height.

## Refused fields

Each action first refuses a red number field it reads (`number_field.refuse_problem`), after its
"already running" guard: Prime numbers Search (button and Enter) the search number, Primality
Check and Factorize N, the primesieve calculator's Compute only the selected operation's fields
(count lo/hi, nth n/start, next and prev x). An empty field behaves as before. The minima are the
lower bounds the actions check: Primality N 2, primesieve n 1 and start 0, the search number 0.
The primesieve calculator's fields keep to libprimesieve's uint64 range, 0 to 2^64 - 1
(`window_planning.PRIMESIEVE_MAX_STOP`): lo, start and x from 0 to 2^64 - 1, hi (an open end,
the library gets hi - 1) from 1 to 2^64, n up to pi(2^64) (`PRIMESIEVE_MAX_NTH`, the largest n
with an answer from start 0); a value outside would wrap in ctypes and count or find the wrong
numbers, so it is red and Compute refuses it.

## Parameters and texts

Preview page sizes in `primeatlas/app/app_const.py`; texts `primes.*`, `primality.*`, `primesieve_calc.*`.

## Kept data

None of its own (reads prime windows; `DP_PROVEN.txt` / `DP_MISMATCH.txt` are written by
`prime_sieve/dp_verify.py`).

## Specs and tests

`test_primes_tab`, `test_primes_tab_dp`, `test_primality_worker`, `test_primesieve_calc_worker`,
`test_search_worker`, `test_field_refusal_tools_app` (refused fields and minima).

## Known gaps

None.
