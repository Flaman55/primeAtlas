"""env_versions.py -- one-shot WSL-side probe of the component versions PrimeAtlas runs on
(Settings -> WSL environment -> "Component versions"): distro, Python, numpy, gcc, and for
libprimesieve and libprimecount the version, the file this Python process loads, the file
every built engine .so resolves (ldd), and every distinct copy in the linker cache; for the
Pseudosquares Prime Sieve program its path, version and build commit.

Two copies of one library (an apt package next to a build under /usr/local) are reported
as a duplicate: the loader picks one by linker-cache order, so an install or removal of
either copy changes the version the engines run on without any change in this app.

Usage (WSL):
    python3 env_versions.py

Prints exactly one line of JSON to stdout, also on failure ({"ok": false, "error": ...}),
which wsl_blocking.run_env_versions_wsl_blocking() parses. Runs on the system python3
with stdlib only; numpy is optional and reported as None when missing.
"""
import ctypes
import ctypes.util
import glob
import json
import os
import platform
import re
import subprocess
import sys

import pseudosquares_const
import pseudosquares_native

_HERE = os.path.dirname(os.path.abspath(__file__))
LIBRARIES = ("primesieve", "primecount")
ENGINE_GLOB = "prime_sieve_engine_*.so"
_SO_VERSION = re.compile(r"\.so\.(\d+(?:\.\d+)*)$")


def parse_os_release(text):
    """PRETTY_NAME from /etc/os-release, without quotes; "" when absent."""
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _soname_matches(name, lib):
    return name == f"lib{lib}.so" or name.startswith(f"lib{lib}.so.")


def ldconfig_paths(text, lib):
    """Paths of every lib<lib>.so[.N] entry of `ldconfig -p`, in cache order."""
    out = []
    for line in text.splitlines():
        if "=>" not in line:
            continue
        left, path = line.split("=>", 1)
        fields = left.split()
        if fields and _soname_matches(fields[0], lib):
            out.append(path.strip())
    return out


def distinct_copies(paths, realpath=os.path.realpath):
    """Sorted distinct files behind `paths` (symlinks to one file are one copy)."""
    return sorted({realpath(p) or p for p in paths})


def version_from_filename(path):
    """"12.15" from .../libprimesieve.so.12.15; None for an unversioned name."""
    match = _SO_VERSION.search(path or "")
    return match.group(1) if match else None


def loaded_from_maps(text, lib):
    """The lib<lib>.so file mapped into a process, from its /proc/<pid>/maps."""
    for line in text.splitlines():
        fields = line.split()
        if fields and _soname_matches(os.path.basename(fields[-1]), lib):
            return fields[-1]
    return None


def ldd_path(text, lib):
    """The file ldd resolves lib<lib>.so[.N] to; None when ldd does not list it."""
    for line in text.splitlines():
        if "=>" not in line:
            continue
        left, right = line.split("=>", 1)
        fields = left.split()
        target = right.split()
        if fields and target and _soname_matches(fields[0], lib):
            return target[0]
    return None


def lib_entry(version, loaded, copies, engines):
    """One library's report: version (from the library's own call), the file Python loads,
    every distinct copy with its file-name version, and {engine .so: file it resolves}."""
    return {
        "version": version,
        "loaded": loaded,
        "copies": [{"path": p, "version": version_from_filename(p)} for p in copies],
        "engines": dict(engines),
    }


def duplicates(libs):
    """Names of the libraries with more than one distinct copy."""
    return [name for name, entry in libs.items() if len(entry["copies"]) > 1]


def engines_differ(entry):
    """True when an engine resolves a different file than this Python process loads. Both
    sides are real files already (collect() resolves the ldd paths, /proc/self/maps names
    the mapped file), so a plain comparison holds also on the Windows side."""
    loaded = entry["loaded"]
    return bool(loaded) and any(p != loaded for p in entry["engines"].values())


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _library_version(lib):
    """Loads lib<lib> the way prime_sieve_primesieve.py / prime_count_primecount.py do
    (find_library, then the unversioned name) and returns <lib>_version(), or None."""
    path = ctypes.util.find_library(lib) or f"lib{lib}.so"
    try:
        handle = ctypes.CDLL(path)
        fn = getattr(handle, f"{lib}_version")
    except (OSError, AttributeError):
        return None
    fn.restype = ctypes.c_char_p
    raw = fn()
    return raw.decode() if raw else None


def _numpy_version():
    try:
        import numpy
    except ImportError:
        return None
    return numpy.__version__


def pseudosquares_entry(binary, version, commit):
    """The Pseudosquares Prime Sieve program: its path, version, the commit of the
    installer's clone it was built from (None for a binary from elsewhere) and whether
    that is the pinned build; None when no program is found."""
    if not binary:
        return None
    return {"path": binary, "version": version, "commit": commit,
            "at_pin": commit == pseudosquares_const.PIN_SHORT}


def _pseudosquares():
    binary = pseudosquares_native.find_binary()
    if not binary:
        return None
    version = pseudosquares_native.parse_version(_run([binary, "--version"]))
    return pseudosquares_entry(binary, version, pseudosquares_native.build_commit(binary))


def collect():
    ldconfig = _run(["ldconfig", "-p"])
    versions = {lib: _library_version(lib) for lib in LIBRARIES}
    maps = _read("/proc/self/maps")
    engine_files = sorted(glob.glob(os.path.join(_HERE, ENGINE_GLOB)))
    ldd_out = {f: _run(["ldd", f]) for f in engine_files}
    libs = {}
    for lib in LIBRARIES:
        engines = {}
        for f, text in ldd_out.items():
            path = ldd_path(text, lib)
            if path:
                engines[os.path.basename(f)] = os.path.realpath(path)
        libs[lib] = lib_entry(versions[lib], loaded_from_maps(maps, lib),
                              distinct_copies(ldconfig_paths(ldconfig, lib)), engines)
    gcc = _run(["gcc", "-dumpfullversion"]).strip() or None
    return {
        "ok": True,
        "distro": parse_os_release(_read("/etc/os-release")),
        "python": platform.python_version(),
        "numpy": _numpy_version(),
        "gcc": gcc,
        "libs": libs,
        "duplicates": duplicates(libs),
        "pseudosquares": _pseudosquares(),
    }


def main():
    try:
        report = collect()
    except Exception as e:  # noqa: BLE001 -- the caller always parses one JSON line
        report = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
