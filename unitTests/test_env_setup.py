"""
test_env_setup.py -- covers primeatlas/env_setup.py, the first-run WSL/Ubuntu/python3/
numpy/libprimesieve check+install backend (task #512, branch env-setup-wizard).

No real Windows/WSL anywhere in this sandbox (Linux-only) -- every subprocess boundary is
stubbed with a recorder/fake, same approach test_cudasieve_integration.py's Section B uses
for run_cudasieve_wsl_blocking's own Popen()+poll() loop. Four sections:

  A. Pure logic -- _windows_path_to_wsl(), _build_install_ps1_text() string structure,
     module-level constants (no I/O at all).
  B. check_environment() -- WSL-absent / distro-absent / packages-missing / all-ok paths,
     via monkeypatched _run_windows()/_run_inside_wsl_blocking().
  C. run_install() -- restart-required / full-success / elevation-declined / real-failure
     paths, via monkeypatched _run_elevated_ps1().
  D. _run_inside_wsl_blocking()'s own Popen()+poll() loop -- verifies wait()/communicate()
     are NEVER called (the documented Windows hang cause -- see generation.py's
     run_cudasieve_wsl_blocking docstring, which this function's implementation
     deliberately mirrors) and that the timeout path actually returns instead of hanging.

Usage:
    python3 unitTests/test_env_setup.py
"""
import os
import sys
import tempfile
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))  # primeatlas/__init__.py pulls
                                                               # in manifest.py -> window_sharding
                                                               # at import time, same PYTHONPATH
                                                               # need test_cudasieve_integration.py
                                                               # already documented

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


# ============================================================================================
# Section A -- pure logic, no I/O
# ============================================================================================

def section_a():
    print("\n--- Section A: pure logic (path mapping, ps1 text, constants) ---")
    from primeatlas import env_setup as es

    _mapped = es._windows_path_to_wsl(r"D:\storage\portal")
    check(_mapped == "/mnt/d/storage/portal",
          f"Windows drive path must map to /mnt/<lowercase-drive>/... (got {_mapped!r})")
    check(es._windows_path_to_wsl("/already/wsl/style") == "/already/wsl/style",
          "a path with no drive-letter prefix must pass through unchanged (aside from "
          "backslash normalization)")

    check(len(es.REQUIRED_WINDOWS_FEATURES) == 2
          and "Microsoft-Windows-Subsystem-Linux" in es.REQUIRED_WINDOWS_FEATURES
          and "VirtualMachinePlatform" in es.REQUIRED_WINDOWS_FEATURES,
          f"REQUIRED_WINDOWS_FEATURES must be exactly the two WSL2 optional features "
          f"(got {es.REQUIRED_WINDOWS_FEATURES!r})")
    check("libgmp-dev" not in es.REQUIRED_APT_PACKAGES
          and "libmpfr-dev" not in es.REQUIRED_APT_PACKAGES,
          "GMP/MPFR must NOT be in the upfront-install set -- confirmed with Artur "
          "(2026-09-02) as an on-demand, module-specific extra, not part of the forced "
          f"first-run install (got {es.REQUIRED_APT_PACKAGES!r})")
    check("python3-numpy" in es.REQUIRED_APT_PACKAGES
          and "libprimesieve12" in es.REQUIRED_APT_PACKAGES
          and "libprimesieve-dev" in es.REQUIRED_APT_PACKAGES,
          f"REQUIRED_APT_PACKAGES must include numpy + libprimesieve runtime/dev packages "
          f"(got {es.REQUIRED_APT_PACKAGES!r})")

    script = es._build_install_ps1_text("Ubuntu")
    check("Microsoft-Windows-Subsystem-Linux" in script and "VirtualMachinePlatform" in script,
          "install script must enable both required Windows features")
    check("$restartNeeded" in script and "exit 3010" in script,
          "install script must detect dism's own 3010/3011 restart-required exit codes "
          "and propagate a matching exit code so run_install() can tell restart-required "
          "apart from real failure")
    check("wsl.exe --install -d Ubuntu --no-launch" in script,
          "install script must use --no-launch (skips the interactive OOBE username/"
          "password prompt this module cannot answer non-interactively -- see module "
          f"docstring) (script tail: {script[-400:]!r})")
    check("default=root" in script,
          "install script must set /etc/wsl.conf's default user to root, so even a bare "
          "`wsl` terminal never triggers the OOBE prompt this design avoids")
    check("-u root" in script,
          "install script's apt-install step must run as root (no sudo password prompt "
          "possible non-interactively)")
    for pkg in es.REQUIRED_APT_PACKAGES:
        check(pkg in script, f"install script must apt-install {pkg!r}")


# ============================================================================================
# Section B -- check_environment()
# ============================================================================================

def section_b():
    print("\n--- Section B: check_environment() ---")
    from primeatlas import env_setup as es

    orig_run_windows = es._run_windows
    orig_run_wsl = es._run_inside_wsl_blocking

    def restore():
        es._run_windows = orig_run_windows
        es._run_inside_wsl_blocking = orig_run_wsl

    # --- WSL entirely absent (wsl.exe not found) ---
    es._run_windows = lambda argv, timeout=30: (None, "", "executable-not-found")
    es._run_inside_wsl_blocking = lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("must not probe WSL when wsl.exe is absent")))
    try:
        report = es.check_environment(distro="Ubuntu", timeout=5)
    finally:
        restore()
    check(report["all_ok"] is False,
          f"WSL-absent report must have all_ok=False (got {report!r})")
    check(report["checks"][0]["id"] == "wsl_present" and report["checks"][0]["ok"] is False,
          f"first check must be wsl_present=False (got {report['checks'][0]!r})")
    check(len(report["checks"]) == 3,
          f"even the short-circuited path must report all 3 check ids (distro_present/"
          f"packages marked skipped) so the wizard can show a full checklist, not a "
          f"truncated one (got {len(report['checks'])} checks)")

    # --- WSL present, but the target distro is not installed ---
    es._run_windows = lambda argv, timeout=30: (
        (0, "kernel version: 5.15.0\n", "") if argv[:2] == ["wsl.exe", "--status"]
        else (0, "Debian\n", "") if argv[:3] == ["wsl.exe", "-l", "-q"]
        else (1, "", "unexpected call"))
    es._run_inside_wsl_blocking = lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("must not probe packages when distro absent")))
    try:
        report = es.check_environment(distro="Ubuntu", timeout=5)
    finally:
        restore()
    check(report["all_ok"] is False and report["checks"][0]["ok"] is True
          and report["checks"][1]["ok"] is False,
          f"distro-absent report must have wsl_present=True, distro_present=False, "
          f"all_ok=False (got checks={report['checks']!r})")

    # --- WSL + distro present, but numpy/libprimesieve missing ---
    es._run_windows = lambda argv, timeout=30: (
        (0, "kernel version: 5.15.0\n", "") if argv[:2] == ["wsl.exe", "--status"]
        else (0, "Ubuntu\n", "") if argv[:3] == ["wsl.exe", "-l", "-q"]
        else (1, "", "unexpected call"))
    es._run_inside_wsl_blocking = (
        lambda distro, cmd, timeout=60: (0, "NUMPY_MISSING\nPRIMESIEVE_MISSING\n"))
    try:
        report = es.check_environment(distro="Ubuntu", timeout=5)
    finally:
        restore()
    pkg_check = report["checks"][2]
    check(report["all_ok"] is False and pkg_check["ok"] is False
          and pkg_check.get("numpy_ok") is False and pkg_check.get("primesieve_ok") is False,
          f"packages-missing report must have all_ok=False with both sub-flags False "
          f"(got {pkg_check!r})")

    # --- Fully OK ---
    es._run_windows = lambda argv, timeout=30: (
        (0, "kernel version: 5.15.0\n", "") if argv[:2] == ["wsl.exe", "--status"]
        else (0, "Ubuntu\n", "") if argv[:3] == ["wsl.exe", "-l", "-q"]
        else (1, "", "unexpected call"))
    es._run_inside_wsl_blocking = (
        lambda distro, cmd, timeout=60: (0, "NUMPY_OK\nPRIMESIEVE_OK\n"))
    try:
        report = es.check_environment(distro="Ubuntu", timeout=5)
    finally:
        restore()
    check(report["all_ok"] is True,
          f"fully-satisfied environment must report all_ok=True (got {report!r})")
    check(all(c["ok"] for c in report["checks"]),
          f"every individual check must be ok=True in the all_ok=True case "
          f"(got {report['checks']!r})")

    # --- Distro name matching is case-insensitive (wsl -l -q output casing varies) ---
    es._run_windows = lambda argv, timeout=30: (
        (0, "kernel version: 5.15.0\n", "") if argv[:2] == ["wsl.exe", "--status"]
        else (0, "ubuntu\n", "") if argv[:3] == ["wsl.exe", "-l", "-q"]
        else (1, "", "unexpected call"))
    es._run_inside_wsl_blocking = (
        lambda distro, cmd, timeout=60: (0, "NUMPY_OK\nPRIMESIEVE_OK\n"))
    try:
        report = es.check_environment(distro="Ubuntu", timeout=5)
    finally:
        restore()
    check(report["checks"][1]["ok"] is True,
          f"distro name match must be case-insensitive ('ubuntu' vs requested 'Ubuntu') "
          f"(got {report['checks'][1]!r})")


# ============================================================================================
# Section C -- run_install()
# ============================================================================================

def section_c():
    print("\n--- Section C: run_install() ---")
    from primeatlas import env_setup as es

    orig_elevated = es._run_elevated_ps1
    work_dir = tempfile.mkdtemp(prefix="env_setup_install_test_")

    def restore():
        es._run_elevated_ps1 = orig_elevated

    # --- Restart required ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (3010, "STEP:features\nRESTART_REQUIRED\n")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir)
    finally:
        restore()
    check(result["restart_required"] is True and result["ok"] is False,
          f"restart-required exit code (3010) must set restart_required=True, ok=False "
          f"(got {result!r})")

    # --- Full success ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (0, "STEP:done\n")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir)
    finally:
        restore()
    check(result["ok"] is True and result["restart_required"] is False,
          f"exit code 0 must be ok=True, restart_required=False (got {result!r})")

    # --- Elevation declined (UAC cancelled -> None returncode) ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (None, "elevation was declined")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir)
    finally:
        restore()
    check(result["ok"] is False and result["restart_required"] is False
          and result["error"] is not None,
          f"declined elevation must be ok=False with a non-None error, not silently "
          f"treated as either success or restart-required (got {result!r})")

    # --- Real failure (e.g. apt install failed) ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (1, "APT_INSTALL_FAILED:100\n")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir)
    finally:
        restore()
    check(result["ok"] is False and result["restart_required"] is False
          and result["error"] is not None,
          f"a real non-zero/non-3010 exit code must be ok=False with an error message "
          f"(got {result!r})")

    # --- The .ps1 scratch file must always be cleaned up, even on failure ---
    written_paths = []
    real_open = open

    def spying_run_elevated(ps1_path, timeout=1800):
        written_paths.append(ps1_path)
        check(os.path.exists(ps1_path), f".ps1 file must exist while _run_elevated_ps1 runs "
                                         f"(got missing path {ps1_path!r})")
        return 1, "boom"

    es._run_elevated_ps1 = spying_run_elevated
    try:
        es.run_install(distro="Ubuntu", work_dir=work_dir)
    finally:
        restore()
    check(len(written_paths) == 1 and not os.path.exists(written_paths[0]),
          f"run_install() must remove its scratch .ps1 file afterward regardless of "
          f"outcome (path {written_paths[0] if written_paths else '?'!r} still exists)")


# ============================================================================================
# Section D -- _run_inside_wsl_blocking()'s Popen()+poll() loop safety
# ============================================================================================

class _FakePopen:
    """Same shape as test_cudasieve_integration.py's own _FakePopen -- records whether
    wait()/communicate() were ever called (the exact untimed fallback that caused the real
    documented Windows hang in run_cudasieve_wsl_blocking, which this function's
    implementation deliberately mirrors)."""

    instances = []

    def __init__(self, poll_sequence):
        self._poll_sequence = list(poll_sequence)
        self.kill_called = False
        self.wait_called = False
        self.communicate_called = False
        _FakePopen.instances.append(self)

    def poll(self):
        if self._poll_sequence:
            return self._poll_sequence.pop(0)
        return None

    def kill(self):
        self.kill_called = True

    def wait(self, timeout=None):
        self.wait_called = True
        raise AssertionError(
            "wait() must NEVER be called by _run_inside_wsl_blocking -- exactly the "
            "untimed fallback call documented as the real Windows hang cause in "
            "generation.py's run_cudasieve_wsl_blocking, which this mirrors")

    def communicate(self, timeout=None):
        self.communicate_called = True
        raise AssertionError("communicate() must NEVER be called -- same reasoning as wait()")


def section_d():
    print("\n--- Section D: _run_inside_wsl_blocking() Popen()+poll() loop ---")
    from primeatlas import env_setup as es

    orig_popen = es.subprocess.Popen
    orig_tempdir = es.tempfile.gettempdir
    scratch_dir = tempfile.mkdtemp(prefix="env_setup_wsl_block_test_")
    es.tempfile.gettempdir = lambda: scratch_dir

    # --- Success path: poll() returns None once, then 0; log/exit files carry real content,
    #     written directly by this test (standing in for what the real bash -c redirect
    #     would have produced) before poll() reports the process has exited. ---
    _FakePopen.instances.clear()
    written = {}

    def fake_popen(argv, **kw):
        check(argv[:4] == ["wsl.exe", "-d", "Ubuntu", "-u"] and argv[4] == "root",
              f"_run_inside_wsl_blocking must invoke wsl.exe -d <distro> -u root ... "
              f"(got {argv[:6]!r})")
        # Extract the log/exit paths this call generated from the bash -c command line,
        # then simulate the redirect having already happened.
        bash_cmd = argv[-1]
        import re as _re
        m = _re.search(r"> '([^']+)' 2>&1; echo \$\? > '([^']+)'", bash_cmd)
        check(m is not None, f"bash -c command must contain the expected redirect shape "
                              f"(got {bash_cmd!r})")
        log_wsl, exit_wsl = m.group(1), m.group(2)
        # Map /mnt/<drive>/... back to a real local path under scratch_dir for this fake --
        # simplest correct approach: since _windows_path_to_wsl(scratch_dir/...) always
        # produces /mnt/<drive>/rest, and this test doesn't run on Windows, just write to
        # the ORIGINAL (pre-mapping) Windows-style paths the function itself used.
        written["log_wsl"] = log_wsl
        written["exit_wsl"] = exit_wsl
        return _FakePopen([None, 0])

    es.subprocess.Popen = fake_popen
    try:
        # On this Linux sandbox _windows_path_to_wsl() only rewrites an actual "X:\..."
        # drive path -- a plain POSIX scratch_dir path passes through with backslashes
        # (none present) unchanged, so log_wsl/exit_wsl above are the SAME real paths
        # _run_inside_wsl_blocking generated, writable directly.
        returncode_holder = {}

        def run_and_capture():
            rc, out = es._run_inside_wsl_blocking("Ubuntu", "true", timeout=5)
            returncode_holder["rc"] = rc
            returncode_holder["out"] = out

        # Popen is called synchronously inside _run_inside_wsl_blocking before the poll
        # loop -- write the fake output files from within fake_popen itself isn't possible
        # (paths aren't known until Popen is called), so instead pre-create them from a
        # wrapper that fires right after Popen sees the argv.
        original_fake_popen = fake_popen

        def fake_popen_and_seed(argv, **kw):
            p = original_fake_popen(argv, **kw)
            with open(written["log_wsl"], "w", encoding="utf-8") as f:
                f.write("hello from wsl\n")
            with open(written["exit_wsl"], "w", encoding="utf-8") as f:
                f.write("0\n")
            return p

        es.subprocess.Popen = fake_popen_and_seed
        run_and_capture()
    finally:
        es.subprocess.Popen = orig_popen
        es.tempfile.gettempdir = orig_tempdir

    check(returncode_holder.get("rc") == 0 and "hello from wsl" in returncode_holder.get("out", ""),
          f"success path must return the real (returncode, stdout) pair "
          f"(got {returncode_holder!r})")
    check(len(_FakePopen.instances) == 1 and not _FakePopen.instances[0].wait_called
          and not _FakePopen.instances[0].communicate_called,
          "success path must never call wait()/communicate() -- only poll()")

    # --- Timeout path: poll() always returns None -> must return (None, "") without ever
    #     calling wait()/communicate(), must call kill(), fast (real 0.3s timeout). ---
    _FakePopen.instances.clear()
    es.tempfile.gettempdir = lambda: scratch_dir

    def never_returning_popen(argv, **kw):
        return _FakePopen([])  # empty sequence -> poll() always falls through to None

    es.subprocess.Popen = never_returning_popen
    try:
        t0 = time.time()
        rc, out = es._run_inside_wsl_blocking("Ubuntu", "sleep 999", timeout=0.3)
        elapsed = time.time() - t0
    finally:
        es.subprocess.Popen = orig_popen
        es.tempfile.gettempdir = orig_tempdir

    check(rc is None and out == "",
          f"timeout path must return (None, '') (got ({rc!r}, {out!r}))")
    check(elapsed < 3.0,
          f"timeout path must return promptly (within a few seconds of the 0.3s timeout), "
          f"not hang (took {elapsed:.2f}s)")
    check(len(_FakePopen.instances) == 1 and _FakePopen.instances[0].kill_called
          and not _FakePopen.instances[0].wait_called
          and not _FakePopen.instances[0].communicate_called,
          "timeout path must call kill() but never wait()/communicate()")


# ============================================================================================

if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All checks passed.")
