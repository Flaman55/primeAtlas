# Module: research (Research tab)

Five analyses grouped by the shape of the question: square intervals (Legendre, Oppermann, Brocard),
prime-generating polynomials (Landau, Euler, Bunyakovsky), Goldbach (strong and weak), prime gaps
(Andrica, Firoozbakht, Cramer overlays) and pi(x) approximations (li(x), R(x)). Each is a UI tab plus a
pure-logic window module. A sixth sub-tab, Irreducibility, computes the definitions of the
Irreducibility repository (Lean 4) on the user's input in five sub-tabs: radices and interval atoms,
comparison of numbers in block layouts, residues read from sech combs, ranges of a layout, and
arithmetic on residues.

## Files

| Part | Files |
|---|---|
| Square intervals | `primeatlas/research/research_squares_tab.py`, `research_squares.py`, `squares_window.py` |
| Polynomials | `research_polynomials_tab.py`, `polynomials_window.py` |
| Goldbach | `research_goldbach_tab.py` and its mixins, `research_goldbach.py`, `goldbach_window.py`, `goldbach_paging.py` |
| Gaps | `research_gaps_tab.py`, `gaps_window.py` |
| pi(x) | `research_pi_approx_tab.py`, `pi_approx_window.py` |
| Irreducibility | `research_irreducibility_tab.py`; views `irreducibility_radices_view.py`, `irreducibility_compare_view.py`, `irreducibility_comb_view.py`, `irreducibility_ranges_view.py`, `irreducibility_arith_view.py`; shared `irreducibility_numbers.py`, `irreducibility_widgets.py`, `irreducibility_draw.py`, `irreducibility_cases_window.py`; residue side `irreducibility_core.py`, `irreducibility_residues.py`, `irreducibility_comb.py`; value side `irreducibility_layout.py`, `irreducibility_ops.py`, `irreducibility_selftest.py` |

## Contract

| In | Out |
|---|---|
| ranges or formulas, a data source (stored archive or computed) | result tables, verdicts or measurements, CSV export |

The archive data source reads stored windows; a missing range is offered to the Generation tab
(Goldbach through `offer_generate_missing_range`). pi(x) can query primecount through WSL.

Irreducibility has no data source. Its files split along one line: the residue side
(`irreducibility_core.py`, `irreducibility_residues.py`, `irreducibility_comb.py`) mirrors `Defs.lean`
and `SechComb.lean` function by function (countMod, resid, euclid, prodMod, gcdProd, radices,
evalMod, invMod, digitStep, toMixedRadix, compareRes, blockModulus, baseExtend, flatten,
compareBlocks, intervalAtoms, addRes ... addressRes) and never forms the product of the moduli or
refers to primes; the value side (`irreducibility_layout.py`, `irreducibility_ops.py`,
`irreducibility_selftest.py`) turns numbers into block representations, forms W and other lcm
values, and checks every result against ordinary integers.

| Sub-tab | In | Out |
|---|---|---|
| Radices and atoms | lo..hi (at most 1000 moduli, up to 50000) | one chip per modulus with its radix (radix > 1 marked); the interval atoms below lo and inside, each with its pair a, a + k |
| Comparison | A, B, each with a layout: blocks D and quotient blocks K (start, size, count) | the verdict from residues only, the common moduli with radix and both digits (the deciding one marked), one dial per block modulus, the integer check; random neighbours; a test of 1000 random pairs, every pair listed in a window |
| Comb reading | a, b in 2..200, scale s (raised to 3 when below) | C_a and C_b, the window from the last peak of C_b to a, the reading a mod b |
| Ranges | a layout of its own (or taken from A / B); a number n | W(D), W(K), W and the jump of W for each parameter moved by -3..+3; layouts fitted to n for block sizes 1..5, usable for A or B |
| Arithmetic | A, B (the Comparison fields), b, T, e, p, n | residues of A ⊕ B, A ⊖ B (overflow / underflow flag, period), A ⊗ B (preperiod, period), A ⊘ b (exact, modulo W or none), the address (i, k) when T divides W, A^e (rhythm), appended powers of p; each with the integer check; a test of 450 random operations, every operation listed in a window |

A test opens a window (`CasesWindow`) with one row per case: the task, the result read from
residues (turned back into a number only for display), the integer result in the same notation and
whether they agree, with an 'only errors' filter; the selected row shows its moduli and the residues
(or, for a comparison, radices and mixed-radix digits) below the list. A second run refreshes the
open window.

Every sub-tab computes synchronously, on opening and on its buttons, within the bounds named
above (and `MAX_START`, `MAX_SIZE`, `MAX_COUNT` of `irreducibility_numbers.py`,
`MAX_EXPONENT` of the Arithmetic view); errors go to the sub-tab, not a dialog.

## Parameters and texts

Texts `research_*`. Irreducibility remembers every input field under `research.irreducibility.*`
(A, B and their layouts, the range, the comb, the Ranges layout and n, the Arithmetic parameters)
and computes them when the tab is built.

## Kept data

None.

## Specs and tests

`test_research_squares_tab`, `test_research_polynomials_tab`, `test_research_gaps_tab`,
`test_research_pi_approx_tab`, `test_goldbach_worker`, `test_squares_window`, `test_polynomials_window`,
`test_gaps_window`, `test_pi_approx_window`, `test_irreducibility_core`,
`test_irreducibility_blocks`, `test_research_irreducibility_tab`.

## Known gaps

- Irreducibility: primality read from residues (theorem T6 of the repository) and the
  multiplicative counting of T9 are not shown yet.
- Hardy-Littlewood density comparison is planned as a view of the Constellations tab, not a Research
  sub-tab.
