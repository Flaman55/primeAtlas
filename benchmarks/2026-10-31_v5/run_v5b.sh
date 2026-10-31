#!/bin/bash
# Engine v5 after the start-overhead fix (slices no shorter than one segment, one worker
# process per slice, lazy imports). Part 1: series B interleaved v4.1 / v5, three rounds,
# same harness for both. Part 2: the full publication set (series A-E) for v5.
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUTD="$HERE/results"
cd "$REPO" && { git log --oneline -1; git status --short; sha256sum prime_sieve/prime_sieve_engine_v5.so; } > "$HERE/commit.txt"
cd "$OUTD"
export ATLAS_ORCH="$REPO/prime_sieve/orchestrator_v3.py"
T="${BENCH_ROOT:-/mnt/h}/primeatlas_bench_v5b"
run() { echo "[$(date +%T)] $1"; BENCH_TMP="${T}_$1" python3 "$HERE/bench_atlas.py" "$OUTD/$1.json" "${@:2}"; echo "[$(date +%T)] $1 rc=$?"; }

# Part 1: interleaved A/B
for r in 1 2 3; do
  for v in v4.1 v5; do
    export PRIMEATLAS_SCANNER_VERSION=$v
    run ab_${v}_B_24w_r$r 10,13,16,19,20,21,22,23,24,25 1 10000000 count 0 24
    run ab_${v}_B_1w_r$r 10,13,16,19,20,21 1 10000000 count 0 1
  done
done

# Part 2: publication set, v5
export PRIMEATLAS_SCANNER_VERSION=v5
for i in 1 2 3; do run E_1000x1e7_1w_floor25_r$i 25 1000 10000000 count 0 1; done
run D_100x1e7_1w 10,13,16,19,20,21,22,23,24,25 100 10000000 count 0 1
run B_1x1e7_1w 10,13,16,19,20,21,22,23,24,25 1 10000000 count 0 1
run A_1000x1e7_24w 10,13,16,19,20,21,22,23,24,25 1000 10000000 count,write 0 24
run B_1x1e7_24w 10,13,16,19,20,21,22,23,24,25 1 10000000 count 0 24
run C_1x1e10_24w_count 10,13,16,19,20,22,25 1 10000000000 count 0 24
# Series C at floor 20, repeated three times after the set (C_rerun_floor20_r1..r3)
for i in 1 2 3; do run C_rerun_floor20_r$i 20 1 10000000000 count 0 24; done
echo ALL_DONE
