"""
pseudosquares_install.py -- installs the Pseudosquares Prime Sieve program inside WSL: a
clone of its upstream repository at the pinned commit (pseudosquares_const.PIN_COMMIT) in
~/.primeatlas/pseudosquares, built with CMake into its build/ folder, where
pseudosquares_native.find_binary() looks first. Outside this repository and outside the
storage folder: a third-party program's own source and build tree.

Pseudosquares Prime Sieve is by Kim Walisch, BSD 2-Clause License,
https://github.com/kimwalisch/Pseudosquares-Prime-Sieve; its LICENSE file stays in the
clone. The build tools (cmake, g++, git) are apt packages installed as root before the build
(apt_command(): Settings runs it through `wsl.exe -u root`, the setup wizard in its elevated
script); this script runs as the WSL user.

Run inside WSL:
    python3 pseudosquares_install.py --status   one JSON line: what is installed
    python3 pseudosquares_install.py --build    clone or move to the pin, build; live text
"""
import json
import os
import shutil
import subprocess
import sys

import pseudosquares_const as const
from pseudosquares_native import default_install_dir, head_commit, parse_version


def apt_command():
    """Root shell command installing the build tools; a no-op for installed ones."""
    return "apt-get update -y && apt-get install -y " + " ".join(const.APT_PACKAGES)


def build_steps(install_dir, cloned, jobs):
    """The argv of every build step: clone (fresh install only), fetch and check out the
    pinned commit, configure (Release), build on `jobs` threads."""
    build = install_dir + "/" + const.BUILD_DIR_NAME
    steps = [] if cloned else [["git", "clone", const.REPO_URL, install_dir]]
    return steps + [
        ["git", "-C", install_dir, "fetch", "origin", const.PIN_COMMIT],
        ["git", "-C", install_dir, "checkout", "--force", "--detach", const.PIN_COMMIT],
        ["cmake", "-S", install_dir, "-B", build, "-DCMAKE_BUILD_TYPE=Release"],
        ["cmake", "--build", build, "--parallel", str(max(1, jobs))],
    ]


def status(install_dir, have_tool, is_dir, head_commit, runnable, version_of):
    """What is installed, from the probes passed in (see _probe_status)."""
    binary = install_dir + "/" + const.BUILD_DIR_NAME + "/" + const.BINARY_NAME
    cloned = is_dir(install_dir + "/.git")
    commit = head_commit(install_dir) if cloned else None
    built = runnable(binary)
    return {
        "ok": True,
        "tools_missing": [t for t in const.APT_PACKAGES if not have_tool(t)],
        "cloned": cloned,
        "commit": commit,
        "pinned": const.PIN_SHORT,
        "at_pin": commit == const.PIN_SHORT,
        "binary_path": binary if built else None,
        "version": version_of(binary) if built else "",
        "install_dir": install_dir,
    }


def _version_of(binary):
    proc = subprocess.run([binary, "--version"], capture_output=True, text=True)
    return parse_version(proc.stdout)


def _probe_status(install_dir):
    return status(install_dir,
                  have_tool=lambda t: shutil.which(t) is not None,
                  is_dir=os.path.isdir,
                  head_commit=head_commit,
                  runnable=lambda p: os.path.isfile(p) and os.access(p, os.X_OK),
                  version_of=_version_of)


def cmd_status(install_dir):
    try:
        report = _probe_status(install_dir)
    except Exception as e:  # noqa: BLE001 -- the caller always parses one JSON line
        report = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(report))


def cmd_build(install_dir):
    missing = [t for t in const.APT_PACKAGES if shutil.which(t) is None]
    if missing:
        print(f"[!] Build tools missing: {' '.join(missing)} -- install them as root: "
              f"{apt_command()}")
        sys.exit(1)
    cloned = os.path.isdir(os.path.join(install_dir, ".git"))
    if not cloned and os.path.exists(install_dir) and os.listdir(install_dir):
        print(f"[!] {install_dir} exists and is not a clone; move it away and build again")
        sys.exit(1)
    os.makedirs(os.path.dirname(install_dir), exist_ok=True)
    print(f"[*] Pseudosquares Prime Sieve (Kim Walisch, BSD 2-Clause, {const.REPO_URL})")
    print(f"[*] Building commit {const.PIN_SHORT} in {install_dir}")
    for step in build_steps(install_dir, cloned, os.cpu_count() or 1):
        print(f"[*] {' '.join(step)}", flush=True)
        code = subprocess.run(step).returncode
        if code != 0:
            print(f"[!] Step failed (exit {code}): {' '.join(step)}")
            sys.exit(code)
    report = _probe_status(install_dir)
    if not report["binary_path"]:
        print("[!] The build finished but produced no program")
        sys.exit(1)
    print(f"[*] Built {report['binary_path']} (version {report['version']}, "
          f"commit {report['commit']})")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("--status", "--build"):
        sys.exit(__doc__)
    target = sys.argv[2] if len(sys.argv) > 2 else default_install_dir()
    if sys.argv[1] == "--status":
        cmd_status(target)
    else:
        cmd_build(target)
