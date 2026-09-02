#!/usr/bin/env bash
# build_and_run_chunked_marking.sh -- single-paste WSL script for marking_chunked_poc.cu/.py
# (see that file's own header, and README.md's "Chunked marking" section, for full background).
# Same GPU-arch detection as the earlier PoC scripts, same log-teeing. Also builds
# prime_sieve_engine_v4.so if missing (needed for EXACT mode's ground-truth comparison).
#
# marking_chunked_poc.cu links libprimesieve DIRECTLY (unlike marking_poc.cu/marking_overhead_
# poc.cu, which only need CUDA) -- nvcc needs -lprimesieve on the link line for this one.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking.sh
#   bash .../build_and_run_chunked_marking.sh --mode exact    # skip the large stress run
#   bash .../build_and_run_chunked_marking.sh --mode stress   # skip EXACT, just the big run
#   bash .../build_and_run_chunked_marking.sh --mode full     # REAL floor-25 scale (~113.8B
#                                                              # primes); expected to take real
#                                                              # minutes -- see README.md's
#                                                              # "Chunked marking" section

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_chunked_marking_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "marking_chunked_poc -- VRAM-bounded streaming + real marking, combined into one"
echo "single-process pipeline"
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
echo "[3/4] Compiling marking_chunked_poc.cu for $GPU_ARCH (linking libprimesieve)..."
nvcc -O3 -arch=$GPU_ARCH -o marking_chunked_poc marking_chunked_poc.cu -lprimesieve
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above. If this is a missing"
    echo "        primesieve.h/libprimesieve error, it needs the same libprimesieve already"
    echo "        required by prime_sieve_engine_v4.c elsewhere in this project."
    exit 1
fi
echo "[*] Built ./marking_chunked_poc"

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
echo "[4/4] Running marking_chunked_poc.py $@ ..."
echo "      EXACT mode: several small cases forced into multiple tiny chunks, each compared"
echo "      byte-for-byte against a single unchunked real-engine call. STRESS mode: one"
echo "      large-scale run (~8-9*10^8 real sieving primes, chunk_size=20,000,000) -- watch"
echo "      the 'allocated once, resident for the whole run' line to confirm VRAM stays flat."
echo "      FULL mode (--mode full): the real floor-25 scale, ~113.8 billion primes -- expect"
echo "      real minutes to run; not part of the default 'both' run, must be requested explicitly."
python3 marking_chunked_poc.py "$@"
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: PASSED. If EXACT mode ran: all cases matched a single unchunked real-engine"
    echo "call byte-for-byte -- chunking+accumulation is confirmed correct. If STRESS mode ran:"
    echo "see the timing breakdown and the VRAM line above."
else
    echo "RESULT: FAILURES -- see FAIL/mismatch lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
