#!/usr/bin/env bash
# build_and_run_resident.sh -- single-paste WSL script for phase_mod_resident_poc.cu (see
# that file's own header, and README.md's "Resident-primes follow-up" section, for full
# background). Same GPU-arch detection as build_and_run.sh (avoids the same PTX/driver
# mismatch that hit the first PoC on 2026-08-28), same log-teeing.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_resident.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_resident_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "phase_mod_resident_poc -- resident-primes, multi-window GPU proof of concept"
echo "log file: $LOG_FILE"
echo "================================================================================"

echo
echo "[1/4] Checking for nvcc..."
if ! command -v nvcc >/dev/null 2>&1; then
    echo "[ABORT] nvcc not found on PATH."
    exit 1
fi
nvcc --version

echo
echo "[2/4] Detecting GPU compute capability..."
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
echo "[3/4] Compiling phase_mod_resident_poc.cu for $GPU_ARCH..."
nvcc -O3 -arch=$GPU_ARCH -o phase_mod_resident_poc phase_mod_resident_poc.cu
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./phase_mod_resident_poc"

echo
echo "[4/4] Running phase_mod_resident_poc.py (floor 25, 1000 windows of 10,000,000 each,"
echo "      20,000,000 resident sample primes -- see that file's own docstring)..."
python3 phase_mod_resident_poc.py
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: PASSED (all captured + checksum-verified windows matched Python ground"
    echo "truth). See the timing breakdown above -- 'amortized per-window' and the"
    echo "extrapolated total-vs-real-benchmark line are the numbers that actually answer"
    echo "whether resident primes fixes the transfer bottleneck from the first PoC."
else
    echo "RESULT: FAILURES -- see FAIL lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
