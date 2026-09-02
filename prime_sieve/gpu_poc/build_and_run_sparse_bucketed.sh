#!/usr/bin/env bash
# build_and_run_sparse_bucketed.sh -- single-paste WSL script for sparse_bucketed_poc.cu/.py.
# Tests whether bucket-sorting sparse-tier primes' target positions by shard (before doing the
# actual atomic writes) improves throughput vs. the naive scattered write -- direct follow-up to
# sparse_overhead_poc's real-hardware finding that the atomic write is 85.3% of sparse_kernel's
# cost. See sparse_bucketed_poc.cu's own header and README.md's "Sparse-kernel cost decomposition"
# section for full background.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_sparse_bucketed.sh
#   bash .../build_and_run_sparse_bucketed.sh --n-primes 100000000   # bigger sample

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_sparse_bucketed_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "sparse_bucketed_poc -- does bucket-sorting writes by shard improve locality?"
echo "log file: $LOG_FILE"
echo "================================================================================"

echo
echo "[1/3] Checking for nvcc..."
if ! command -v nvcc >/dev/null 2>&1; then
    echo "[ABORT] nvcc not found on PATH."
    exit 1
fi

echo
echo "[2/3] Detecting GPU compute capability..."
GPU_ARCH=""
if command -v nvidia-smi >/dev/null 2>&1; then
    COMPUTE_CAP="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '[:space:]')"
    if [[ "$COMPUTE_CAP" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
        GPU_ARCH="sm_${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
        echo "[*] Detected compute capability $COMPUTE_CAP -> $GPU_ARCH"
    fi
fi
if [ -z "$GPU_ARCH" ]; then
    echo "[!] Could not detect via nvidia-smi -- falling back to -arch=native."
    GPU_ARCH="native"
fi

echo
echo "[3/3] Compiling and running sparse_bucketed_poc..."
nvcc -O3 -arch=$GPU_ARCH -o sparse_bucketed_poc sparse_bucketed_poc.cu -lprimesieve
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./sparse_bucketed_poc"

python3 sparse_bucketed_poc.py "$@"
RUN_EXIT=$?

echo
echo "Full log saved at: $LOG_FILE"
exit $RUN_EXIT
