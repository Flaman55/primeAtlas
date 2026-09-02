#!/usr/bin/env bash
# build_and_run_chunked_marking_parallel.sh -- single-paste WSL script for
# marking_chunked_parallel_poc.cu/.py (see that file's own header, and README.md's "Parallel
# chunked marking" section, for full background: this is the direct, real-hardware follow-up to
# marking_chunked_poc's FULL-mode result of TOTAL=1316.729s vs production's 176.018s, adding
# parallel CPU generation across threads + a double-buffered GPU pipeline instead of leaving
# that as a "would probably be faster if..." guess).
#
# Same GPU-arch detection as the earlier PoC scripts, same log-teeing. Also builds
# prime_sieve_engine_v4.so if missing (needed for EXACT mode's ground-truth comparison).
#
# marking_chunked_parallel_poc.cu links libprimesieve AND uses std::thread/mutex/condition_
# variable -- needs -lprimesieve, -std=c++17, and -Xcompiler -pthread on the nvcc link line.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking_parallel.sh
#   bash .../build_and_run_chunked_marking_parallel.sh --mode exact
#   bash .../build_and_run_chunked_marking_parallel.sh --mode stress
#   bash .../build_and_run_chunked_marking_parallel.sh --mode full --gen-threads 24
#                                                              # REAL floor-25 scale; expected to
#                                                              # take real minutes (hopefully
#                                                              # fewer than the prior 1316.729s)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_chunked_marking_parallel_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "marking_chunked_parallel_poc -- parallel CPU generation + double-buffered GPU pipeline,"
echo "combined into one single-process pipeline"
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
echo "[3/4] Compiling marking_chunked_parallel_poc.cu for $GPU_ARCH (linking libprimesieve, "
echo "      C++17, pthreads)..."
nvcc -O3 -std=c++17 -arch=$GPU_ARCH -Xcompiler -pthread \
     -o marking_chunked_parallel_poc marking_chunked_parallel_poc.cu -lprimesieve
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above. If this is a missing"
    echo "        primesieve.h/libprimesieve error, it needs the same libprimesieve already"
    echo "        required by prime_sieve_engine_v4.c elsewhere in this project."
    exit 1
fi
echo "[*] Built ./marking_chunked_parallel_poc"

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
echo "[4/4] Running marking_chunked_parallel_poc.py $@ ..."
echo "      EXACT mode: cases forced into multiple tiny chunks AND multiple generator threads,"
echo "      each compared byte-for-byte against a single unchunked, single-threaded real-engine"
echo "      call. STRESS mode: moderate-scale run for a quick before/after read. FULL mode"
echo "      (--mode full): the real floor-25 scale, ~113.8 billion primes -- not part of the"
echo "      default 'both' run, must be requested explicitly. Add --gen-threads N to override"
echo "      the CPU generator thread count (default: os.cpu_count() on this machine)."
python3 marking_chunked_parallel_poc.py "$@"
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: PASSED. If EXACT mode ran: all cases matched a single unchunked, "
    echo "single-threaded real-engine call byte-for-byte -- multi-threaded generation +"
    echo "chunking+accumulation is confirmed correct. If STRESS/FULL mode ran: see the timing"
    echo "breakdown above, and compare TOTAL against marking_chunked_poc's earlier (serial,"
    echo "single-threaded) numbers for the same scale."
else
    echo "RESULT: FAILURES -- see FAIL/mismatch lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
