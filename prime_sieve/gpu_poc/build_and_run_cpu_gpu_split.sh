#!/usr/bin/env bash
# build_and_run_cpu_gpu_split.sh -- single-paste WSL script for cpu_gpu_split_poc.py.
#
# Artur's idea: instead of CPU and GPU fighting over the SAME shared write buffer (every design
# in this series so far), split the combined_size RANGE into two disjoint sub-windows and give one
# to CPU (the real, unmodified engine) and the other to GPU (marking_two_tier_poc, unmodified),
# running both AT ONCE. Zero shared-buffer contention, zero cross-device sync during the run --
# only a one-time split up front and a trivial concatenate at the end. See cpu_gpu_split_poc.py's
# own header for the full reasoning and why this is low-risk (it's the same kind of independent-
# window decomposition production already does for its own 1000 separate windows today).
#
# This script builds marking_two_tier_poc's binary (the GPU side reuses it unmodified) and the
# real engine's .so (the CPU side calls it directly via ctypes), then runs the new orchestrator,
# which does NOT need its own nvcc build (pure Python + ctypes + subprocess).
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_cpu_gpu_split.sh --mode exact
#   bash .../build_and_run_cpu_gpu_split.sh --mode full --cpu-fraction 0.5
#   bash .../build_and_run_cpu_gpu_split.sh --mode full --cpu-fraction 0.6 --cpu-workers 24 --gpu-gen-threads 10
#                                                              # try giving CPU the bigger share
#   bash .../build_and_run_cpu_gpu_split.sh --mode full --combined-size 20000000000
#                                                              # 2x the 10-billion baseline --
#                                                              # tests whether the fixed sieving-
#                                                              # prime-generation cost (dominant,
#                                                              # ~219s at the 10B baseline) really
#                                                              # stays roughly flat as the window
#                                                              # grows, per run_full_scale_mode()'s
#                                                              # own docstring in
#                                                              # cpu_gpu_split_poc.py
# Note: STRESS/FULL mode's CPU side now uses a real multi-process architecture by default
# (--cpu-workers 24, matching production's MAX_WORKERS) -- see prepare_cpu_side_parallel()'s
# docstring in cpu_gpu_split_poc.py. EXACT mode always stays single-threaded (small ranges,
# correctness is what matters there, not speed). --combined-size only applies to FULL mode.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_cpu_gpu_split_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "cpu_gpu_split_poc -- CPU and GPU each sieve their own disjoint half of the range, at once"
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
echo "[3/4] Compiling marking_two_tier_poc.cu (the GPU side reuses this binary unmodified)..."
nvcc -O3 -std=c++17 -arch=$GPU_ARCH -Xcompiler -pthread \
     -o marking_two_tier_poc marking_two_tier_poc.cu -lprimesieve
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    exit 1
fi
echo "[*] Built ./marking_two_tier_poc"

if [ -f ../prime_sieve_engine_v4.so ]; then
    echo "[*] ../prime_sieve_engine_v4.so already built -- CPU side and EXACT-mode ground truth"
    echo "    will reuse it."
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
echo "[4/4] Running cpu_gpu_split_poc.py $@ ..."
echo "      EXACT mode: split-then-concatenate result checked byte-for-byte against a single"
echo "      unsplit, unchunked, single-threaded real-engine call over the full window (7 cases,"
echo "      including cpu_fraction=0.0/1.0 edge cases and a nonzero-distance GPU-side-shift"
echo "      case). FULL mode (--mode full): the real floor-25 scale -- watch whether t_wall lands"
echo "      close to max(cpu_elapsed, gpu_total) (real overlap) and whether it beats both"
echo "      production CPU alone (176.018s) and GPU-only two-tier (169.623s) for covering the"
echo "      FULL range."
python3 cpu_gpu_split_poc.py "$@"
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: PASSED. If EXACT mode ran: the range-split-and-concatenate result matched a"
    echo "single unsplit real-engine call byte-for-byte on every case -- the split mechanism is"
    echo "confirmed correct. If FULL mode ran: see the overlap check and direct comparison lines"
    echo "above."
else
    echo "RESULT: FAILURES -- see FAIL/mismatch lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
