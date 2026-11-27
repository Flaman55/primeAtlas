# Module: research (Research tab)

Five analyses grouped by the shape of the question: square intervals (Legendre, Oppermann, Brocard),
prime-generating polynomials (Landau, Euler, Bunyakovsky), Goldbach (strong and weak), prime gaps
(Andrica, Firoozbakht, Cramer overlays) and pi(x) approximations (li(x), R(x)). Each is a UI tab plus a
pure-logic window module. A sixth sub-tab, Irreducibility, computes the definitions of the
Irreducibility repository (Lean 4) on the user's input in seven sub-tabs: radices and interval atoms,
comparison of numbers in block layouts, residues read from sech combs, ranges of a layout,
arithmetic on residues, primality read from residues, and multiplicative counting modulo q.

## Files

| Part | Files |
|---|---|
| Square intervals | `primeatlas/research/research_squares_tab.py`, `research_squares.py`, `squares_window.py` |
| Polynomials | `research_polynomials_tab.py`, `polynomials_window.py` |
| Goldbach | `research_goldbach_tab.py` and its mixins, `research_goldbach.py`, `goldbach_window.py`, `goldbach_paging.py` |
| Gaps | `research_gaps_tab.py`, `gaps_window.py` |
| pi(x) | `research_pi_approx_tab.py`, `pi_approx_window.py` |
| Irreducibility | `research_irreducibility_tab.py`; views `irreducibility_radices_view.py`, `irreducibility_compare_view.py`, `irreducibility_comb_view.py`, `irreducibility_ranges_view.py`, `irreducibility_arith_view.py`, `irreducibility_primality_view.py`, `irreducibility_multiplicative_view.py`; shared `irreducibility_numbers.py`, `irreducibility_widgets.py`, `irreducibility_draw.py`, `irreducibility_cases_window.py`; residue side `irreducibility_core.py`, `irreducibility_residues.py`, `irreducibility_comb.py`, `irreducibility_multiplicative.py`; value side `irreducibility_layout.py`, `irreducibility_ops.py`, `irreducibility_primality.py`, `irreducibility_selftest.py` |

## Contract

| In | Out |
|---|---|
| ranges or formulas, a data source (stored archive or computed) | result tables, verdicts or measurements, CSV export |

The archive data source reads stored windows; a missing range is offered to the Generation tab
(Goldbach through `offer_generate_missing_range`). pi(x) can query primecount through WSL.

Irreducibility has no data source. Its files split along one line: the residue side
(`irreducibility_core.py`, `irreducibility_residues.py`, `irreducibility_comb.py`,
`irreducibility_multiplicative.py`) mirrors `Defs.lean`, `SechComb.lean` and `Multiplicative.lean`
function by function (countMod, resid, mulCount, euclid, prodMod, gcdProd, radices,
evalMod, invMod, digitStep, toMixedRadix, compareRes, blockModulus, baseExtend, flatten,
compareBlocks, intervalAtoms, addRes ... addressRes, isPrimeRes) and never forms the product of
the moduli or uses a list of primes or a primality test; multiplicative counting multiplies by g
once per step and never takes a power; the value side (`irreducibility_layout.py`, `irreducibility_ops.py`,
`irreducibility_primality.py`, `irreducibility_selftest.py`) turns numbers into block
representations, forms W and other lcm values, runs isPrimeRes in slices, and checks every result
against ordinary integers.

| Sub-tab | In | Out |
|---|---|---|
| Radices and atoms | lo..hi (at most 1000 moduli, up to 50000) | one chip per modulus with its radix (radix > 1 marked); the interval atoms below lo and inside, each with its pair a, a + k |
| Comparison | A, B, each with a layout: blocks D and quotient blocks K (start, size, count) | the verdict from residues only, the common moduli with radix and both digits (the deciding one marked), one dial per block modulus, the integer check; random neighbours; a test of 1000 random pairs, every pair listed in a window |
| Comb reading | a, b in 2..200, scale s (raised to 3 when below) | C_a and C_b, the window from the last peak of C_b to a, the reading a mod b |
| Ranges | a layout of its own (or taken from A / B); a number n | W(D), W(K), W and the jump of W for each parameter moved by -3..+3; layouts fitted to n for block sizes 1..5, usable for A or B |
| Arithmetic | A, B (the Comparison fields), b, T, e, p, n | residues of A ⊕ B, A ⊖ B (overflow / underflow flag, period), A ⊗ B (preperiod, period), A ⊘ b (exact, modulo W or none), the address (i, k) when T divides W, A^e (rhythm), appended powers of p; each with the integer check; a test of 450 random operations, every operation listed in a window |
| Primality | A with its layout (the Comparison fields), fuel (1 to 10^9 divisors, default 10^6) | the verdict of isPrimeRes (prime: m reached A or m² > A; composite: the divisor m, or A < 2; no answer: fuel used up or stopped), the step count, the first and last 10 steps (m, m vs A, m² vs A, A mod m), the integer check (Miller-Rabin); a note when (isqrt(A) + 1)² ≥ W, where the run may go on up to A, and Fit for primality, which sets W above (isqrt(A) + 1)²; a test of 1000 numbers, every number listed in a window |
| Multiplicative counting | q (2 to 10^5), g (auto or 1..q - 1), N (any size) | the order of g (Auto: the smallest g of the largest order among 1..100, the least primitive root for a prime q, a note when none has order q - 1); whether g^t mod q and t mod (q - 1) are equal at the same pairs of steps, or the first differing pair; N mod q and the step t reaching it (discrete logarithm); N a square mod q by the parity of t, given only when g has order q - 1, q > 2 and q ∤ N; the integer check (q prime by Miller-Rabin, Euler's criterion); the cycle table (every step up to 200, else the first 20, the step with 2 around it, the last 3); for q ≤ 101 the sech comb of modulus q - 1 over two cycles with the returns to 1 marked; a test of 1000 random primes q and N, every case listed in a window |

A test opens a window (`CasesWindow`) with one row per case: the task, the result read from
residues (turned back into a number only for display), the integer result in the same notation and
whether they agree, with an 'only errors' filter; the selected row shows its moduli and the residues
(or, for a comparison, radices and mixed-radix digits) below the list. A second run refreshes the
open window.

Every sub-tab computes synchronously, on opening and on its buttons, within the bounds named
above (and `MAX_START`, `MAX_SIZE`, `MAX_COUNT` of `irreducibility_numbers.py`,
`MAX_EXPONENT` of the Arithmetic view); errors go to the sub-tab, not a dialog. Primality is the
exception: it runs only on its button, in slices of about 50 ms (`SLICE_SECONDS`) scheduled by
the Tk event loop, so the window stays responsive and Stop can end the run; Check primality
during a run starts over, and closing the view cancels the run.

## Parameters and texts

Texts `research_*`. Irreducibility remembers every input field under `research.irreducibility.*`
(A, B and their layouts, the range, the comb, the Ranges layout and n, the Arithmetic parameters,
the Primality fuel) and computes them when the tab is built, except Primality.

## Refused fields

Every action below first refuses a red field it reads (`number_field.refuse_problem`), after its
"already running" guard, with exactly the fields it reads; a refusal changes no page and opens
no window:

| Action | Fields |
|---|---|
| Gaps Run | n from, n to |
| Squares Run | required count, n from, n to |
| Polynomials Run | n from, n to |
| pi(x) Run | x from, x to, step |
| Goldbach Run | n |
| Goldbach Visualize | n; the Visualize window's "from" while that window is open |
| Visualize window: Check | "to", "from" |
| Visualize window: row Previous, Next | "from" |
| Visualize window: row Go | its page, "from" |
| Visualize window: old base Go | its page |
| Visualize window: decompose | its n (after the "no window checked yet" message) |
| Decomposition list: Go | its page |

A field's minimum is the lowest value its action accepts: Gaps and Squares 1, Polynomials 0,
pi(x) x from/to 2 and step 1, Goldbach n and the window's "to" 2, the window's "from" and
decompose 4, every page field 1. A Visualize window opened by Visualize reads its "from" from
its remembered text; `_goldbach_queue_viz` checks that value with its own message.

## Kept data

None.

## Specs and tests

`test_research_squares_tab`, `test_research_polynomials_tab`, `test_research_gaps_tab`,
`test_research_pi_approx_tab`, `test_goldbach_worker`, `test_squares_window`, `test_polynomials_window`,
`test_gaps_window`, `test_pi_approx_window`, `test_irreducibility_core`,
`test_irreducibility_blocks`, `test_research_irreducibility_tab`, `test_field_refusal_app`
(refused fields and minima).



## Known gaps

- The Irreducibility sub-tab does not refuse a red field yet: its views read the text with
  their own checks and write the message into the view.
