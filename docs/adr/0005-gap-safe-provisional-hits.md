# 0005. k-tuple sieve finds ahead of the exhaustive search go to a provisional log

Date: 2026-11-03 (recorded; in force since `ktuple_sieve_v2.py`). Status: accepted.

## Context
The exhaustive search appends hits above each pattern's last stored value and decides "already known"
by that value. The targeted k-tuple sieve jumps around a floor and finds hits far ahead of the
exhaustive frontier. Written into the shared hit file, one such hit raised the last value and every
smaller, genuinely new hit the exhaustive search found afterwards was dropped (`ktuple_sieve_v1.py`).

## Decision
`ktuple_hit_store` computes the exhaustive frontier from the finder's done ranges. Confirmed hits below
it go into the shared hit file through the deduplicating append; hits at or beyond it go to
`PROVISIONAL_HITS_10p{N}_k{K}_v{V}.txt` and are found again, and recorded normally, when the exhaustive
search reaches them.

## Options rejected
- None recorded.

## Consequences
The provisional log can hold hits not yet in the shared file; the Constellations tab shows the shared
file only. `test_ktuple_sieve_v2_provisional` runs the routing against every version.
