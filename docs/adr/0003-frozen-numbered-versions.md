# 0003. Numbered engine versions are frozen; changes are new versions proven by tests

Date: 2026-11-03 (recorded). Status: accepted.

## Context
Benchmarks (BENCHMARK.md) and stored data were produced by specific engine versions. Editing an engine
in place would make old measurements and runs irreproducible and hide regressions.

## Decision
A numbered file (`prime_sieve_v4_1.py`, `constellation_finder_v2.py`, `ktuple_sieve_v2.py`, ...) is
never edited in place. A change creates the next version, and the GUI switches to it in the same PR.
A refactor version is proven equal to its frozen reference by tests: the same syntax tree per function
(after the documented renames), and the same output and files for the same CLI runs
(`test_constellation_finder_v2_3`, `test_ktuple_sieve_v2_2`). A performance version is proven at least as
fast by interleaved A/B runs.

## Options rejected
- Edit in place with git history as the record: a benchmark row would no longer name the code that
  produced it.

## Consequences
Old versions stay in the tree (listed as exceptions in `test_line_ceiling.py` when over 1000 lines).
Every frozen step keeps its equivalence test.
