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

## Parameters and texts

Preview page sizes in `primeatlas/app/app_const.py`; texts `primes.*`, `primality.*`, `primesieve_calc.*`.

## Kept data

None of its own (reads prime windows; `DP_PROVEN.txt` / `DP_MISMATCH.txt` are written by
`prime_sieve/dp_verify.py`).

## Specs and tests

`test_primes_tab`, `test_primes_tab_dp`, `test_primality_worker`, `test_primesieve_calc_worker`,
`test_search_worker`.

## Known gaps

None.
