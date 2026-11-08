"""
pseudosquares_const.py -- fixed values of the Pseudosquares Prime Sieve integration, read by
the WSL-side runner and installer (pseudosquares_native.py, pseudosquares_install.py) and by
the GUI (Quick-gen plan, Settings, setup wizard).

Pseudosquares Prime Sieve is an independent open-source program by Kim Walisch (BSD
2-Clause License), https://github.com/kimwalisch/Pseudosquares-Prime-Sieve -- built from
source inside WSL by pseudosquares_install.py, not part of this project. Upstream has no
releases, so the installer checks out PIN_COMMIT: every benchmark row names the build it
measured, and a pin change is a reviewed repository change.
"""
REPO_URL = "https://github.com/kimwalisch/Pseudosquares-Prime-Sieve"
PIN_COMMIT = "fccb96e93c2586abd9e88dfe95977848a03bc149"
PIN_SHORT = PIN_COMMIT[:7]

# The program sieves [START, STOP] with STOP <= 10^33 (its --help).
MAX_STOP = 10 ** 33
# Highest Atlas floor with numbers under MAX_STOP: floor 32 is [10^32, 10^33).
MAX_FLOOR = len(str(MAX_STOP)) - 2

BINARY_NAME = "pseudosquares_prime_sieve"
BINARY_ENV = "PSEUDOSQUARES_BIN"           # explicit binary path, wins over the install
INSTALL_DIR_REL = ".primeatlas/pseudosquares"  # under the WSL user's home: the clone
BUILD_DIR_NAME = "build"                   # CMake build tree inside the clone

# Build tools installed as root before the build (CMake >= 3.10, a C++ compiler with
# 128-bit integers, git for the clone); the program's other dependencies are vendored.
APT_PACKAGES = ("cmake", "g++", "git")

# --print runs on one thread (the program sets threads = 1 when printing).
PRINT_THREADS = 1
