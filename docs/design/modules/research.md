# Module: research (Research tab)

Five analyses grouped by the shape of the question: square intervals (Legendre, Oppermann, Brocard),
prime-generating polynomials (Landau, Euler, Bunyakovsky), Goldbach (strong and weak), prime gaps
(Andrica, Firoozbakht, Cramer overlays) and pi(x) approximations (li(x), R(x)). Each is a UI tab plus a
pure-logic window module.

## Files

| Part | Files |
|---|---|
| Square intervals | `primeatlas/research/research_squares_tab.py`, `research_squares.py`, `squares_window.py` |
| Polynomials | `research_polynomials_tab.py`, `polynomials_window.py` |
| Goldbach | `research_goldbach_tab.py` and its mixins, `research_goldbach.py`, `goldbach_window.py`, `goldbach_paging.py` |
| Gaps | `research_gaps_tab.py`, `gaps_window.py` |
| pi(x) | `research_pi_approx_tab.py`, `pi_approx_window.py` |

## Contract

| In | Out |
|---|---|
| ranges or formulas, a data source (stored archive or computed) | result tables, verdicts or measurements, CSV export |

The archive data source reads stored windows; a missing range is offered to the Generation tab
(Goldbach through `offer_generate_missing_range`). pi(x) can query primecount through WSL.

## Parameters and texts

Texts `research_*`.

## Kept data

None.

## Specs and tests

`test_research_squares_tab`, `test_research_polynomials_tab`, `test_research_gaps_tab`,
`test_research_pi_approx_tab`, `test_goldbach_worker`, `test_squares_window`, `test_polynomials_window`,
`test_gaps_window`, `test_pi_approx_window`.

## Known gaps

- Hardy-Littlewood density comparison is planned as a view of the Constellations tab, not a Research
  sub-tab.
