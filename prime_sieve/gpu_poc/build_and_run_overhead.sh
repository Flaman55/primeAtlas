#!/usr/bin/env bash
# build_and_run_overhead.sh -- single-paste WSL script for marking_overhead_poc.cu/.py (see
# marking_overhead_poc.cu's own header, and README.md's "Marking-kernel cost decomposition"
# section, for full background). Same GPU-arch detection as the earlier PoC scripts, same
# log-teeing.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_overhead.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_overhead_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "marking_overhead_poc -- decomposing marking_kernel's real-hardware cost into"
echo "launch overhead / redundant phase computation / real marking work"
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
echo "[3/3] Compiling marking_overhead_poc.cu for $GPU_ARCH and running the sweep..."
nvcc -O3 -arch=$GPU_ARCH -o marking_overhead_poc marking_overhead_poc.cu
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./marking_overhead_poc"

echo
echo "Running marking_overhead_poc.py (two sweeps -- see that file's own docstring for exactly"
echo "what each isolates)..."
python3 marking_overhead_poc.py "$@"
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: DONE. Read the two tables above plus the INTERPRETATION GUIDE at the bottom --"
    echo "this diagnostic doesn't PASS/FAIL, it answers a design question about where"
    echo "marking_kernel's real-hardware time is actually going."
else
    echo "RESULT: FAILED -- see errors above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
