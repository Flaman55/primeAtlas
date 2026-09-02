#!/usr/bin/env bash
# build_and_run_bucketed_marking.sh -- single-paste WSL script for marking_bucketed_poc.cu/.py.
# Integrates sparse_bucketed_poc's real-hardware-confirmed win (128 KB shards, 2.34x speedup on
# the sparse tier's per-chunk cost) into the full two-tier dense/sparse pipeline. See
# marking_bucketed_poc.cu's header and README.md's bucketing sections for full background.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_bucketed_marking.sh --mode exact
#   bash .../build_and_run_bucketed_marking.sh --mode full --gen-threads 24
#   bash .../build_and_run_bucketed_marking.sh --mode full --gen-threads 24 --shard-bits 1048576

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_bucketed_marking_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "marking_bucketed_poc -- dense (unchanged) + bucketed sparse pipeline"
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
echo "[3/3] Compiling and running marking_bucketed_poc..."
nvcc -O3 -std=c++17 -arch=$GPU_ARCH -Xcompiler -pthread -o marking_bucketed_poc marking_bucketed_poc.cu -lprimesieve
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./marking_bucketed_poc"

python3 marking_bucketed_poc.py "$@"
RUN_EXIT=$?

echo
echo "Full log saved at: $LOG_FILE"
exit $RUN_EXIT
