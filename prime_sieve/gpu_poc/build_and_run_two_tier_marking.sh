#!/usr/bin/env bash
# build_and_run_two_tier_marking.sh -- single-paste WSL script for marking_two_tier_poc.cu/.py
# (see that file's own header, and README.md's "Two-tier dense/sparse kernel" section, for full
# background: this mirrors prime_sieve_engine_v4.c's own dense/sparse prime-cost split on the
# GPU, in direct response to marking_chunked_parallel_poc's result showing the pipeline had
# become purely GPU-kernel-bound with no more pipelining gains available).
#
# Same GPU-arch detection, log-teeing, and libprimesieve/C++17/pthreads requirements as
# marking_chunked_parallel_poc.cu.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_two_tier_marking.sh
#   bash .../build_and_run_two_tier_marking.sh --mode exact
#   bash .../build_and_run_two_tier_marking.sh --mode stress
#   bash .../build_and_run_two_tier_marking.sh --mode full --gen-threads 24
#                                                              # REAL floor-25 scale

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_two_tier_marking_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "marking_two_tier_poc -- dense (block/prime) + sparse (thread/prime) kernel split,"
echo "mirroring prime_sieve_engine_v4.c's own p_val >= window_m branch"
echo "log file: $LOG_FILE"
echo "================================================================================"

echo
echo "[1/4] Checking for nvcc..."
if ! command -v nvcc >/dev/null 2>&1; then
    echo "[ABORT] nvcc not found on PATH."
    exit 1
fi

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
echo "[3/4] Compiling marking_two_tier_poc.cu for $GPU_ARCH (linking libprimesieve, C++17, "
echo "      pthreads)..."
nvcc -O3 -std=c++17 -arch=$GPU_ARCH -Xcompiler -pthread \
     -o marking_two_tier_poc marking_two_tier_poc.cu -lprimesieve
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./marking_two_tier_poc"

if [ -f ../prime_sieve_engine_v4.so ]; then
    echo "[*] ../prime_sieve_engine_v4.so already built -- EXACT mode will reuse it."
else
    echo "[*] ../prime_sieve_engine_v4.so not found -- building it now..."
    gcc -O3 -shared -fPIC ../prime_sieve_engine_v4.c -o ../prime_sieve_engine_v4.so \
        -lprimesieve -lstdc++ -lm
    if [ $? -ne 0 ]; then
        echo "[ABORT] gcc compile failed -- see errors above."
        exit 1
    fi
    echo "[*] Built ../prime_sieve_engine_v4.so"
fi

echo
echo "[4/4] Running marking_two_tier_poc.py $@ ..."
echo "      EXACT mode: cases exercising dense-only, sparse-heavy, mixed, and a boundary case"
echo "      (combined_size == an actual prime), each compared byte-for-byte against a single"
echo "      unchunked, single-threaded real-engine call. FULL mode (--mode full): the real"
echo "      floor-25 scale -- watch the dense vs sparse timing breakdown to see whether the"
echo "      tier split actually closes the gap with production's 176.018s."
python3 marking_two_tier_poc.py "$@"
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: PASSED. If EXACT mode ran: all cases matched a single unchunked,"
    echo "single-threaded real-engine call byte-for-byte -- the dense/sparse tier split is"
    echo "confirmed correct. If STRESS/FULL mode ran: see the dense vs sparse timing breakdown"
    echo "above and compare TOTAL against marking_chunked_parallel_poc's earlier numbers."
else
    echo "RESULT: FAILURES -- see FAIL/mismatch lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
