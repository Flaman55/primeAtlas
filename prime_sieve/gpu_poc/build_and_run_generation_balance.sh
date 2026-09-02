#!/usr/bin/env bash
# build_and_run_generation_balance.sh -- single-paste WSL script for generation_balance_poc.cpp.
# CPU-only (no GPU/nvcc needed). Tests whether this codebase's equal-width generator-thread
# range splitting (unchanged since marking_chunked_parallel_poc.cu, still used by
# marking_bucketed_poc.cu today) is a real bottleneck, by comparing it against a Mertens/Li(x)-
# weighted equal-count split -- production's own approach -- on the exact real floor-25 sparse
# range with 24 threads, generation only (no GPU, no marking). See generation_balance_poc.cpp's
# header for the full reasoning: this run's own generate_wall (185.944s for sparse-tier
# generation alone) was 64% longer than production's ENTIRE sieve step (113.352s, both tiers,
# plus phase_mod plus marking) -- this test finds out how much of that gap is just imbalanced
# thread splitting.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_generation_balance.sh
#   bash .../build_and_run_generation_balance.sh <lo> <hi> <n_threads>   # custom range/threads

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_generation_balance_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "generation_balance_poc -- equal-width vs equal-count (Mertens/Li) thread split"
echo "log file: $LOG_FILE"
echo "================================================================================"
echo
echo "This is CPU-only -- no GPU, no CUDA, no nvcc needed. Real floor-25 sparse range,"
echo "generation only (raw primesieve_iterator, no marking), 24 threads by default."
echo "Expect this to take a few minutes -- it generates the real ~113.5 billion sparse-tier"
echo "primes twice (once per split strategy)."
echo

g++ -O3 -std=c++17 -pthread -o generation_balance_poc generation_balance_poc.cpp -lprimesieve
if [ $? -ne 0 ]; then
    echo "[ABORT] g++ compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./generation_balance_poc"
echo

./generation_balance_poc "$@"
RUN_EXIT=$?

echo
echo "Full log saved at: $LOG_FILE"
exit $RUN_EXIT
