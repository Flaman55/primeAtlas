#!/usr/bin/env bash
# build_and_run_chunked.sh -- single-paste WSL script for phase_mod_chunked_poc.py (see that
# file's own docstring, and README.md's "Chunked/streaming follow-up" section, for full
# background). Reuses the SAME phase_mod_resident_poc binary from the previous step unchanged
# -- builds it if not already present, otherwise skips straight to running.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked.sh
#   bash .../build_and_run_chunked.sh --n-chunks 100   # bigger stress test, once default passes

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/gpu_poc_chunked_run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "phase_mod_chunked_poc -- kubelkowanie / streaming GPU proof of concept"
echo "log file: $LOG_FILE"
echo "================================================================================"

if [ -x ./phase_mod_resident_poc ]; then
    echo
    echo "[1/3] ./phase_mod_resident_poc already built -- skipping compile."
else
    echo
    echo "[1/3] Building phase_mod_resident_poc (not found)..."
    if ! command -v nvcc >/dev/null 2>&1; then
        echo "[ABORT] nvcc not found on PATH."
        exit 1
    fi
    GPU_ARCH=""
    if command -v nvidia-smi >/dev/null 2>&1; then
        COMPUTE_CAP="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '[:space:]')"
        if [[ "$COMPUTE_CAP" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
            GPU_ARCH="sm_${BASH_REMATCH[1]}${BASH_REMATCH[2]}"
            echo "[*] Detected compute capability $COMPUTE_CAP -> $GPU_ARCH"
        fi
    fi
    [ -z "$GPU_ARCH" ] && GPU_ARCH="native"
    nvcc -O3 -arch=$GPU_ARCH -o phase_mod_resident_poc phase_mod_resident_poc.cu
    if [ $? -ne 0 ]; then
        echo "[ABORT] nvcc compile failed -- see errors above."
        exit 1
    fi
    echo "[*] Built ./phase_mod_resident_poc"
fi

if [ -f ./iterator_chunk_gen.so ]; then
    echo
    echo "[2/3] ./iterator_chunk_gen.so already built -- skipping compile."
else
    echo
    echo "[2/3] Building iterator_chunk_gen.so (not found) -- streams primes via"
    echo "      primesieve_iterator, the same mechanism prime_sieve_engine_v4.c's own"
    echo "      production sieve loop uses (see that file's generate_and_sieve_segment_bits()"
    echo "      and iterator_chunk_gen.c's own header for the full story)..."
    if ! command -v gcc >/dev/null 2>&1; then
        echo "[ABORT] gcc not found on PATH."
        exit 1
    fi
    gcc -O3 -shared -fPIC iterator_chunk_gen.c -o iterator_chunk_gen.so -lprimesieve
    if [ $? -ne 0 ]; then
        echo "[ABORT] gcc compile failed -- see errors above. If this is a missing"
        echo "        primesieve.h/libprimesieve error, it needs the same libprimesieve"
        echo "        already required by prime_sieve_engine_v4.c/prime_sieve_primesieve.py"
        echo "        elsewhere in this project (apt install libprimesieve-dev, or see"
        echo "        https://github.com/kimwalisch/primesieve)."
        exit 1
    fi
    echo "[*] Built ./iterator_chunk_gen.so"
fi

echo
echo "[3/3] Running phase_mod_chunked_poc.py $@ ..."
echo "      Default: 10 chunks x 20,000,000 primes = 200,000,000 total. Pass --n-chunks N"
echo "      to scale up (see phase_mod_chunked_poc.py's own docstring for what higher values"
echo "      prove that this default doesn't)."
python3 phase_mod_chunked_poc.py "$@"
RUN_EXIT=$?

echo
echo "================================================================================"
if [ $RUN_EXIT -eq 0 ]; then
    echo "RESULT: PASSED. See 'peak VRAM for prime data' and the total wall-time lines above."
else
    echo "RESULT: FAILURES -- see FAIL lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $RUN_EXIT
