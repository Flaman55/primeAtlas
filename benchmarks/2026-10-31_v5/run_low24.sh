#!/bin/bash
# Series B, 24 workers, floors 10-19: ten interleaved rounds v4.1 / v5 (sub-second runs need
# more repetitions than three for a stable median).
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUTD="$HERE/results"
cd "$OUTD"
export ATLAS_ORCH="$REPO/prime_sieve/orchestrator_v3.py"
for r in $(seq 1 10); do
  for v in v4.1 v5; do
    PRIMEATLAS_SCANNER_VERSION=$v BENCH_TMP="${BENCH_ROOT:-/mnt/h}/primeatlas_bench_v5b_low24" \
      python3 "$HERE/bench_atlas.py" "$OUTD/low24_${v}_r$r.json" 10,13,16,19 1 10000000 count 0 24 > /dev/null
    echo "r$r $v rc=$?"
  done
done
