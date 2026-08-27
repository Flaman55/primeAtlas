#!/usr/bin/env bash
# build_and_run.sh -- single-paste WSL script: compiles phase_mod_poc.cu, then runs
# phase_mod_poc.py across a few floors to check correctness and get first real throughput
# numbers for the "przesunieta skala" GPU phase-computation idea (see README.md in this
# folder for full background and what to look at in the output).
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run.sh
# (adjust /mnt/h/... if this repo is mounted at a different WSL path on your machine --
# everything else below is path-independent, it cd's to its own folder first.)
#
# Everything is also teed to a timestamped log file in this same folder.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "phase_mod_poc -- GPU phase-computation proof of concept"
echo "log file: $LOG_FILE"
echo "================================================================================"

echo
echo "[1/4] Checking for nvcc..."
if ! command -v nvcc >/dev/null 2>&1; then
    echo "[ABORT] nvcc not found on PATH. This needs the same CUDA Toolkit already used to "
    echo "        build cudasieve (see prime_sieve/prime_sieve_cudasieve.py's own installer "
    echo "        if that's not set up in this shell session)."
    exit 1
fi
nvcc --version

echo
echo "[2/4] Detecting GPU compute capability (same approach as prime_sieve_cudasieve.py's"
echo "      own _detect_gpu_arch() -- see that file for why this matters: nvcc's default"
echo "      target architecture can produce PTX the installed driver's JIT compiler can't"
echo "      consume -- 'the provided PTX was compiled with an unsupported toolchain' -- so"
echo "      this compiles real SASS for your actual card instead of relying on that default)..."
GPU_ARCH=""
if command -v nvidia-smi >/dev/null 2>&1; then
    COMPUTE_CAP="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '[:space:]')"
    if [[ "$COMPUTE_CAP" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
        GPU_ARCH="sm_${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
        echo "[*] Detected compute capability $COMPUTE_CAP -> $GPU_ARCH"
    fi
fi
if [ -z "$GPU_ARCH" ]; then
    echo "[!] Could not detect GPU compute capability via nvidia-smi -- falling back to"
    echo "    '-arch=native' (nvcc auto-detects the local GPU at compile time; needs a"
    echo "    reasonably recent CUDA Toolkit, which this machine already has for cudasieve)."
    GPU_ARCH="native"
fi

echo
echo "[3/4] Compiling phase_mod_poc.cu for $GPU_ARCH..."
nvcc -O3 -arch=$GPU_ARCH -o phase_mod_poc phase_mod_poc.cu
if [ $? -ne 0 ]; then
    echo "[ABORT] nvcc compile failed -- see errors above."
    echo "        If this is an architecture error, try editing GPU_ARCH by hand in this"
    echo "        script (e.g. GPU_ARCH=sm_120 for Blackwell/RTX 50-series) and re-run."
    exit 1
fi
echo "[*] Built ./phase_mod_poc"

echo
echo "[4/4] Running phase_mod_poc.py across a few floors..."
echo "    Each floor runs the SAME sample of the smallest 20,000,000 real primes (see"
echo "    phase_mod_poc.py's own module docstring for why a full floor-25/28 sieving-prime"
echo "    set can't be materialized at all -- it would be 100+ GB of prime values). Floor 16"
echo "    is included because it's a real historical data point (L_final's pi() there is the"
echo "    5,761,455 figure already seen in this project's own test fixtures); floor 25 and 28"
echo "    match the two floors with real benchmark_log.csv data discussed on 2026-08-27/28."

OVERALL_EXIT=0
for FLOOR in 16 25 28; do
    echo
    echo "--- floor $FLOOR ---"
    python3 phase_mod_poc.py "$FLOOR"
    STEP_EXIT=$?
    if [ $STEP_EXIT -ne 0 ]; then
        echo "[!] floor $FLOOR reported failures (see above)"
        OVERALL_EXIT=1
    fi
done

echo
echo "================================================================================"
if [ $OVERALL_EXIT -eq 0 ]; then
    echo "RESULT: ALL FLOORS PASSED (GPU phases matched Python ground truth exactly at every"
    echo "floor tested). See the per-floor throughput lines above -- that's the real number"
    echo "to look at next, not just pass/fail."
else
    echo "RESULT: AT LEAST ONE FLOOR FAILED -- see FAIL lines above before trusting any"
    echo "throughput numbers from this run."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $OVERALL_EXIT
