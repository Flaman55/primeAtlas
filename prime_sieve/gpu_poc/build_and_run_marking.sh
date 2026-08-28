#!/usr/bin/env bash
# build_and_run_marking.sh -- single-paste WSL script for marking_poc.cu/marking_poc.py (see
# marking_poc.cu's own header, and README.md's "Marking-kernel follow-up" section, for full
# background). Same GPU-arch detection as the earlier PoC scripts (avoids the PTX/driver
# mismatch that hit the first PoC on 2026-08-28), same log-teeing. Also builds
# prime_sieve_engine_v4.so if it isn't already present (needed for EXACT mode's ground-truth
# comparison -- marking_poc.py builds it too if missed here, this just does it up front so
# build errors show up before the GPU run starts).
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_marking.sh
#   bash .../build_and_run_marking.sh --mode exact       # skip the throughput run
#   bash .../build_and_run_marking.sh --mode throughput  # skip the exact-verification run

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_marking_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "marking_poc -- real GPU MARKING (not just phase computation) proof of concept"
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
echo "[3/4] Compiling marking_poc.cu for $GPU_ARCH..."
nvcc -O3 -arch=$GPU_ARCH -o marking_poc marking_poc.cu
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./marking_poc"

if [ -f ../prime_sieve_engine_v4.so ]; then
    echo "[*] ../prime_sieve_engine_v4.so already built -- EXACT mode will reuse it."
else
    echo "[*] ../prime_sieve_engine_v4.so not found -- building it now (same real production"
    echo "    engine file, needed as ground truth for EXACT mode)..."
    if ! command -v gcc >/dev/null 2>&1; then
        echo "[ABORT] gcc not found on PATH."
        exit 1
    fi
    gcc -O3 -shared -fPIC ../prime_sieve_engine_v4.c -o ../prime_sieve_engine_v4.so \
        -lprimesieve -lstdc++ -lm
    if [ $? -ne 0 ]; then
        echo "[ABORT] gcc compile failed -- see errors above."
        exit 1
    fi
    echo "[*] Built ../prime_sieve_engine_v4.so"
fi

echo
echo "[4/4] Running marking_poc.py $@ ..."
echo "      EXACT mode compares byte-for-byte against the real prime_sieve_engine_v4.so"
echo "      across a set of edge cases including the self-elimination guard; THROUGHPUT mode"
echo "      times one realistic-shaped batch (20,000,000 sample primes marking a 10^8-wide"
echo "      combined range at floor 25). See marking_poc.py's own docstring for what each"
echo "      mode does and does not prove."
python3 marking_poc.py "$@"
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: PASSED. If EXACT mode ran: all cases matched the real production engine"
    echo "byte-for-byte, including the self-elimination guard edge cases. If THROUGHPUT mode"
    echo "ran: see the kernel timing and work-units/s numbers above."
else
    echo "RESULT: FAILURES -- see FAIL/mismatch lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
