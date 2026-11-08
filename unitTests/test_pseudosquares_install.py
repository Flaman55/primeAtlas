"""
test_pseudosquares_install.py -- the WSL-side installer of the Pseudosquares Prime Sieve
program builds exactly the pinned upstream commit and reports what is installed.

A. Build steps: a fresh install clones, every install fetches and checks out the pinned
   commit (an existing clone on another commit moves to the pin), then a CMake Release
   configure and a parallel build; no step runs a shell.
B. Status from probes: missing build tools named by their apt package, not cloned, cloned
   at the pin, cloned at another commit, built binary and its version; always ok=True with
   the pinned commit.
C. The root apt command installs exactly the build tools, idempotently.

Usage:
    python unitTests/test_pseudosquares_install.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def part_a():
    import pseudosquares_const as const
    import pseudosquares_install as inst

    d = "/home/u/.primeatlas/pseudosquares"
    build = d + "/build"
    fresh = inst.build_steps(d, cloned=False, jobs=8)
    check(fresh[0] == ["git", "clone", const.REPO_URL, d], "fresh: clone first")
    rest = [["git", "-C", d, "fetch", "origin", const.PIN_COMMIT],
            ["git", "-C", d, "checkout", "--force", "--detach", const.PIN_COMMIT],
            ["cmake", "-S", d, "-B", build, "-DCMAKE_BUILD_TYPE=Release"],
            ["cmake", "--build", build, "--parallel", "8"]]
    check(fresh[1:] == rest, "fresh: fetch the pin, check it out, configure, build")
    again = inst.build_steps(d, cloned=True, jobs=8)
    check(again == rest, "existing clone: no clone, moves to the pin and rebuilds")
    check(all(isinstance(a, str) for step in fresh for a in step),
          "every step is an argv list (no shell)")
    check(inst.build_steps(d, cloned=True, jobs=0)[-1][-1] == "1", "jobs below 1 -> 1")


def part_b():
    import pseudosquares_const as const
    import pseudosquares_install as inst

    d = "/home/u/.primeatlas/pseudosquares"
    binary = d + "/build/" + const.BINARY_NAME
    s = inst.status(d, have_tool=lambda t: t != "cmake", is_dir=lambda p: False,
                    head_commit=lambda p: None, runnable=lambda p: False,
                    version_of=lambda p: "")
    check(s["ok"] and s["pinned"] == const.PIN_SHORT, "status: ok with the pinned commit")
    check(s["tools_missing"] == ["cmake"], "status: missing build tool named by its package")
    check(not s["cloned"] and s["commit"] is None and s["binary_path"] is None,
          "status: nothing installed")
    check(not s["at_pin"], "status: not installed is not at the pin")

    s = inst.status(d, have_tool=lambda t: True, is_dir=lambda p: True,
                    head_commit=lambda p: const.PIN_SHORT, runnable=lambda p: p == binary,
                    version_of=lambda p: "1.2")
    check(s["tools_missing"] == [] and s["cloned"] and s["at_pin"],
          "status: cloned at the pin")
    check(s["binary_path"] == binary and s["version"] == "1.2", "status: built binary, version")
    check(s["install_dir"] == d, "status: names the install dir")

    s = inst.status(d, have_tool=lambda t: True, is_dir=lambda p: True,
                    head_commit=lambda p: "1234567", runnable=lambda p: True,
                    version_of=lambda p: "1.1")
    check(s["commit"] == "1234567" and not s["at_pin"], "status: clone on another commit")

    s = inst.status(d, have_tool=lambda t: True, is_dir=lambda p: True,
                    head_commit=lambda p: const.PIN_SHORT, runnable=lambda p: False,
                    version_of=lambda p: "")
    check(s["at_pin"] and s["binary_path"] is None, "status: cloned at the pin, not built")


def part_c():
    import pseudosquares_const as const
    import pseudosquares_install as inst
    cmd = inst.apt_command()
    check(cmd == "apt-get update -y && apt-get install -y " + " ".join(const.APT_PACKAGES),
          "apt: installs the build tools (install is a no-op when present)")
    check(const.APT_PACKAGES == ("cmake", "g++", "git"), "apt: cmake, g++, git")


def main():
    part_a()
    part_b()
    part_c()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
