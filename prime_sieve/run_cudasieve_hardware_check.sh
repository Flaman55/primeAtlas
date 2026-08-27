#!/usr/bin/env bash
# run_cudasieve_hardware_check.sh -- single-command, fully automated real-hardware check for
# prime_sieve_cudasieve.py's three TODO(needs real hardware) items (see that file's module
# header, generate_primes_in_range()'s own docstring, and cmd_build()'s own docstring).
#
# Chains exactly the same three CLI steps settings_tab.py's own installer UI already calls
# (--status / --fetch-license / --build -- see prime_sieve_cudasieve.py's __main__ block),
# skipping straight to build if a binary is already present, then runs
# verify_cudasieve_hardware.py (cudasieve vs primesieve comparison on two real ranges) with
# no further input needed. Everything is also teed to a timestamped log file in this same
# folder in case the terminal scrollback is too long to paste back whole.
#
# Usage (WSL2, from anywhere):
#   bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/run_cudasieve_hardware_check.sh
# (adjust /mnt/h/... if this repo is mounted at a different WSL path on your machine --
# everything else in this script is path-independent, it cd's to its own folder first.)
#
# Exit code: 0 if the final hardware verification passed, non-zero if ANY step failed
# (status/build/verify) -- check the printed [ABORT]/RESULT line either way.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

INSTALL_DIR="${CUDASIEVE_INSTALL_DIR:-$HOME/.primeatlas/cudasieve}"
LOG_FILE="$SCRIPT_DIR/cudasieve_hardware_check_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee "$LOG_FILE") 2>&1

echo "================================================================================"
echo "cudasieve hardware check -- fully automated, single run"
echo "install dir: $INSTALL_DIR"
echo "log file:    $LOG_FILE"
echo "================================================================================"

json_get() {
    # json_get '<json string>' key -- tiny helper, avoids depending on jq being installed.
    python3 -c "import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2]))" "$1" "$2"
}

echo
echo "[1/5] Checking current status..."
STATUS_JSON="$(python3 prime_sieve_cudasieve.py --status "$INSTALL_DIR")"
echo "$STATUS_JSON"

HAS_NVIDIA="$(json_get "$STATUS_JSON" has_nvidia_smi)"
HAS_NVCC="$(json_get "$STATUS_JSON" has_nvcc)"
BINARY_EXISTS="$(json_get "$STATUS_JSON" binary_exists)"

if [ "$HAS_NVIDIA" != "True" ]; then
    echo "[ABORT] nvidia-smi not found -- no visible Nvidia GPU/driver in this WSL session."
    exit 1
fi
if [ "$HAS_NVCC" != "True" ]; then
    echo "[ABORT] nvcc not found -- CUDA Toolkit not installed/on PATH in this WSL session."
    exit 1
fi

if [ "$BINARY_EXISTS" = "True" ]; then
    echo "[*] cudasieve binary already built at $INSTALL_DIR -- skipping clone/build (2-3)."
else
    echo
    echo "[2/5] Cloning CUDASieve + fetching its License text..."
    LICENSE_JSON="$(python3 prime_sieve_cudasieve.py --fetch-license "$INSTALL_DIR")"
    LICENSE_OK="$(json_get "$LICENSE_JSON" ok)"
    if [ "$LICENSE_OK" != "True" ]; then
        echo "[ABORT] --fetch-license failed: $(json_get "$LICENSE_JSON" error)"
        exit 1
    fi
    echo "--- CUDASieve License (GNU GPLv3, read live from the just-cloned repo) ---"
    json_get "$LICENSE_JSON" license_text
    echo "--- end License ---"
    echo "[*] Proceeding straight to build -- you're running this script yourself, on your"
    echo "    own machine, already knowing CUDASieve is GPLv3 (same terms you accepted"
    echo "    building it by hand on 2026-08-23)."

    echo
    echo "[3/5] Building (make) -- this is the slow step, live make output follows..."
    python3 prime_sieve_cudasieve.py --build "$INSTALL_DIR"
    BUILD_EXIT=$?
    if [ $BUILD_EXIT -ne 0 ]; then
        echo "[ABORT] build failed (exit $BUILD_EXIT) -- see make output above."
        exit 1
    fi
fi

echo
echo "[4/5] Re-checking status to confirm the binary is really there..."
STATUS_JSON2="$(python3 prime_sieve_cudasieve.py --status "$INSTALL_DIR")"
echo "$STATUS_JSON2"
BINARY_EXISTS2="$(json_get "$STATUS_JSON2" binary_exists)"
if [ "$BINARY_EXISTS2" != "True" ]; then
    echo "[ABORT] status still reports binary_exists=false after build -- something is wrong."
    exit 1
fi

echo
echo "[5/5] Running hardware verification (cudasieve vs primesieve, two real ranges)..."
python3 verify_cudasieve_hardware.py
VERIFY_EXIT=$?

echo
echo "================================================================================"
if [ $VERIFY_EXIT -eq 0 ]; then
    echo "RESULT: ALL CHECKS PASSED."
else
    echo "RESULT: FAILURES -- see FAIL/ABORT lines above."
fi
echo "Full log saved at: $LOG_FILE"
echo "================================================================================"
exit $VERIFY_EXIT
