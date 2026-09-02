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
import shutil
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

    # --- Regression: the script must log via its own self-contained Log helper (writing
    #     to $PSCommandPath + ".log" with Add-Content -Encoding UTF8), not bare Write-Output
    #     piped through some OUTER capture mechanism. Two real-hardware bugs from the same
    #     session drove this: piping the whole script through `Out-File` to fix a UTF-16
    #     mojibake bug then broke `exit 3010` propagation, because a script that is a
    #     pipeline producer doesn't reliably hand its own exit code to the process the way
    #     a bare top-level script does. Self-contained logging lets _run_elevated_ps1 go
    #     back to a completely unadorned -File invocation (see that function's own
    #     regression test below) while still getting UTF-8-correct, readable log output.
    check("function Log" in script,
          f"install script must define its own Log helper (see _build_install_ps1_text's "
          f"docstring for why logging must be self-contained, not piped from outside) "
          f"(got {script[:400]!r})")
    check("$LogPath = $PSCommandPath" in script,
          f"the script must derive its own log path from $PSCommandPath, matching what "
          f"_run_elevated_ps1 computes independently as ps1_path + '.log' in Python "
          f"(got {script[:400]!r})")
    check("Add-Content" in script and "-Encoding UTF8" in script,
          f"the Log helper must append with an explicit UTF8 encoding -- Windows "
          f"PowerShell 5.1's redirection/Out-File defaults are UTF-16LE, which produces "
          f"mojibake when read back as UTF-8 (got {script[:400]!r})")
    check("Write-Output $msg" not in script or "function Log" in script,
          "any remaining bare Write-Output must only be the one inside the Log helper "
          "itself (console echo), not a parallel, unlogged output path")
    check(script.count('exit 3010') == 1 and 'exit 3010' in script
          and "Out-File" not in script,
          f"exit statements must remain plain top-level statements in THIS script, not "
          f"wrapped in an external pipe -- confirms bug 3's fix (no Out-File piping "
          f"survives in the generated script itself) (got exit-3010 count "
          f"{script.count('exit 3010')})")

    # --- Regression: checklist mode -- each step must be entirely OMITTED (not just
    #     runtime-guarded) when its need_* flag is False. Real-hardware bug: run_install()
    #     used to always emit and run the FULL sequence, so re-running it right after a
    #     features-only reboot tried `wsl --install -d Ubuntu --no-launch` against an
    #     ALREADY-installed distro and crashed with Wsl/InstallDistro/ERROR_ALREADY_EXISTS.
    features_only = es._build_install_ps1_text(
        "Ubuntu", need_features=True, need_distro=False, need_packages=False)
    check("dism.exe" in features_only, "need_features=True must still enable the features")
    check("wsl.exe --install" not in features_only and "apt-get install" not in features_only,
          f"need_distro=False/need_packages=False must omit those steps entirely, not just "
          f"guard them at runtime (got {features_only!r})")

    distro_only = es._build_install_ps1_text(
        "Ubuntu", need_features=False, need_distro=True, need_packages=False)
    check("dism.exe" not in distro_only and "apt-get install" not in distro_only
          and "wsl.exe --install" in distro_only,
          f"need_distro=True alone must emit only the WSL-install step (got {distro_only!r})")
    check("ALREADY_EXISTS" in distro_only,
          f"the distro-install step must tolerate ERROR_ALREADY_EXISTS by text, not just by "
          f"exit code -- WSL reported exit code -1 for this on real hardware, not one of "
          f"the historically-tolerated 1/2 (got {distro_only!r})")

    packages_only = es._build_install_ps1_text(
        "Ubuntu", need_features=False, need_distro=False, need_packages=True)
    check("dism.exe" not in packages_only and "wsl.exe --install" not in packages_only
          and "apt-get install" in packages_only,
          f"need_packages=True alone must emit only the apt-install step "
          f"(got {packages_only!r})")

    nothing_needed = es._build_install_ps1_text(
        "Ubuntu", need_features=False, need_distro=False, need_packages=False)
    check("dism.exe" not in nothing_needed and "wsl.exe --install" not in nothing_needed
          and "apt-get install" not in nothing_needed and "STEP:done" in nothing_needed,
          f"with nothing needed the script must still be well-formed (just does nothing) "
          f"(got {nothing_needed!r})")


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

    # Explicit "everything missing" report, passed to every run_install() call below that
    # expects the full sequence to run -- keeps these tests deterministic regardless of
    # whether this sandbox happens to have a real wsl.exe (it doesn't), rather than relying
    # on run_install()'s own self-check fallback to coincidentally agree.
    _ALL_MISSING_REPORT = {
        "all_ok": False, "distro": "Ubuntu",
        "checks": [
            {"id": "wsl_present", "ok": False},
            {"id": "distro_present", "ok": False},
            {"id": "packages", "ok": False},
        ],
    }

    # --- Regression: the elevated launcher must never combine -Verb RunAs with any
    #     -RedirectStandard* parameter. That combination is a real Windows/PowerShell
    #     limitation (elevation goes through ShellExecuteEx, which has no redirected-handle
    #     model) -- Start-Process silently writes a non-terminating error and returns $null
    #     instead of throwing, so $p.ExitCode used to read as empty and _run_elevated_ps1
    #     misreported this as "elevation declined" even though no UAC prompt was ever shown.
    #     Caught by Artur on real hardware (2026-09-02): the install failed instantly, far
    #     too fast for a real UAC decision. An interim fix piped the ELEVATED process's own
    #     output into Out-File -Encoding utf8 to also fix a second real bug from the same
    #     session (Windows PowerShell 5.1's default redirection encoding is UTF-16LE, not
    #     UTF-8, which produced mojibake once elevation started succeeding) -- but that pipe
    #     turned out to be a THIRD bug: it made the exit code of `exit 3010` inside the
    #     elevated script unreliable (confirmed on real hardware: the script correctly
    #     printed RESTART_REQUIRED and called exit 3010, yet this function received 1).
    #     All three are now fixed by moving logging into the elevated script itself (see
    #     _build_install_ps1_text's own docstring/regression test in section_a) and letting
    #     THIS function go back to the simplest possible invocation: -File, no pipe, no
    #     redirection at all -- exit codes only ever need to be unambiguous, not captured.
    #     This test drives the real _run_elevated_ps1 (only _run_windows is faked) so it
    #     exercises the actual launcher string built.
    captured_argv = []
    orig_run_windows = es._run_windows

    def spying_run_windows(argv, timeout=30):
        captured_argv.append(argv)
        return 0, "0\n", ""

    es._run_windows = spying_run_windows
    probe_ps1 = os.path.join(work_dir, "probe.ps1")
    with open(probe_ps1, "w", encoding="utf-8") as f:
        f.write("# probe\n")
    try:
        es._run_elevated_ps1(probe_ps1, timeout=5)
    finally:
        es._run_windows = orig_run_windows
        os.remove(probe_ps1)
    check(len(captured_argv) == 1, "_run_elevated_ps1 must invoke _run_windows exactly once")
    launcher = captured_argv[0][-1] if captured_argv else ""
    check("-RedirectStandardOutput" not in launcher and "-RedirectStandardError" not in launcher
          and "-RedirectStandardInput" not in launcher,
          f"the elevated launcher must never pass -RedirectStandard* alongside -Verb RunAs "
          f"-- Start-Process silently fails on that combination (got {launcher!r})")
    check("-Verb RunAs" in launcher and "-PassThru" in launcher and "-Wait" in launcher,
          f"launcher must still elevate via -Verb RunAs, wait for it, and capture the exit "
          f"code via -PassThru (got {launcher!r})")
    check("-File" in launcher and probe_ps1 in launcher,
          f"launcher must invoke the script via a bare -File (got {launcher!r})")
    check("*>" not in launcher and "Out-File" not in launcher and " | " not in launcher,
          f"the launcher must NOT pipe or redirect the elevated script's output in any way "
          f"-- that broke exit-code propagation on real hardware (bug 3); logging is now "
          f"self-contained inside the script itself (got {launcher!r})")

    # --- Restart required ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (3010, "STEP:features\nRESTART_REQUIRED\n")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir, report=_ALL_MISSING_REPORT)
    finally:
        restore()
    check(result["restart_required"] is True and result["ok"] is False,
          f"restart-required exit code (3010) must set restart_required=True, ok=False "
          f"(got {result!r})")

    # --- Full success ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (0, "STEP:done\n")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir, report=_ALL_MISSING_REPORT)
    finally:
        restore()
    check(result["ok"] is True and result["restart_required"] is False,
          f"exit code 0 must be ok=True, restart_required=False (got {result!r})")

    # --- Elevation declined (UAC cancelled -> None returncode) ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (None, "elevation was declined")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir, report=_ALL_MISSING_REPORT)
    finally:
        restore()
    check(result["ok"] is False and result["restart_required"] is False
          and result["error"] is not None,
          f"declined elevation must be ok=False with a non-None error, not silently "
          f"treated as either success or restart-required (got {result!r})")

    # --- Real failure (e.g. apt install failed) ---
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (1, "APT_INSTALL_FAILED:100\n")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir, report=_ALL_MISSING_REPORT)
    finally:
        restore()
    check(result["ok"] is False and result["restart_required"] is False
          and result["error"] is not None,
          f"a real non-zero/non-3010 exit code must be ok=False with an error message "
          f"(got {result!r})")

    # --- Regression: checklist skip -- if the passed-in report says everything is already
    #     satisfied, run_install() must not launch an elevated process AT ALL (no UAC
    #     prompt for nothing). This is the actual real-hardware bug's root fix: it's what
    #     stops run_install() from ever re-running `wsl --install` against a distro the
    #     caller's own report already says is present.
    elevated_calls = []
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: elevated_calls.append(ps1_path) or (0, "")
    _ALL_OK_REPORT = {
        "all_ok": True, "distro": "Ubuntu",
        "checks": [
            {"id": "wsl_present", "ok": True},
            {"id": "distro_present", "ok": True},
            {"id": "packages", "ok": True},
        ],
    }
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir, report=_ALL_OK_REPORT)
    finally:
        restore()
    check(len(elevated_calls) == 0,
          f"run_install() must not elevate at all when the report says nothing is missing "
          f"(got {len(elevated_calls)} elevated call(s))")
    check(result["ok"] is True and result["restart_required"] is False,
          f"an already-satisfied report must report ok=True immediately (got {result!r})")

    # --- Regression: checklist partial -- only the steps the report says are missing may
    #     be built into the script (mirrors section_a's _build_install_ps1_text checks, but
    #     exercised through the real run_install() -> _build_install_ps1_text call chain).
    _PACKAGES_ONLY_REPORT = {
        "all_ok": False, "distro": "Ubuntu",
        "checks": [
            {"id": "wsl_present", "ok": True},
            {"id": "distro_present", "ok": True},
            {"id": "packages", "ok": False},
        ],
    }
    captured_scripts = []

    def spying_elevated_capture_script(ps1_path, timeout=1800):
        with open(ps1_path, encoding="utf-8") as f:
            captured_scripts.append(f.read())
        return 0, "STEP:done\n"

    es._run_elevated_ps1 = spying_elevated_capture_script
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir, report=_PACKAGES_ONLY_REPORT)
    finally:
        restore()
    check(len(captured_scripts) == 1, "a partial report must still elevate exactly once")
    built_script = captured_scripts[0] if captured_scripts else ""
    check("dism.exe" not in built_script and "wsl.exe --install" not in built_script
          and "apt-get install" in built_script,
          f"packages-only report must build a script containing only the apt-install step "
          f"(got {built_script!r})")
    check(result["ok"] is True, f"successful partial install must report ok=True (got {result!r})")

    # --- Regression: report=None falls back to a real (here: monkeypatched)
    #     check_environment() call, so callers that don't already have a report still work.
    orig_check_environment = es.check_environment
    es.check_environment = lambda distro, timeout=60: dict(_ALL_MISSING_REPORT, distro=distro)
    es._run_elevated_ps1 = lambda ps1_path, timeout=1800: (0, "STEP:done\n")
    try:
        result = es.run_install(distro="Ubuntu", work_dir=work_dir)
    finally:
        restore()
        es.check_environment = orig_check_environment
    check(result["ok"] is True,
          f"report=None must fall back to run_install()'s own check_environment() call "
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
        es.run_install(distro="Ubuntu", work_dir=work_dir, report=_ALL_MISSING_REPORT)
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
# Section E -- AppSettings.env_status / set_env_status (task #517, on-demand status readback)
# ============================================================================================
#
# Not exercised by env_setup.py itself -- this is the persistence layer settings_tab.py's
# on-demand "Zweryfikuj srodowisko" status label and env_setup_wizard.py's _on_check_done()
# both depend on (Artur, 2026-09-02: the wizard closed too fast to read and Settings had no
# status of its own). Mirrors cudasieve_status's own untested-in-isolation precedent for
# every OTHER property in app_settings.py -- this one gets its own coverage specifically
# because it's brand new this session, not because the module as a whole is usually tested
# here (it normally isn't; see test_env_setup.py's own module docstring for the four
# sections that ARE this file's usual scope).

def section_e():
    print("\n--- Section E: AppSettings.env_status / set_env_status ---")
    import primeatlas.app_settings as app_settings_module
    from primeatlas.app_settings import AppSettings

    # AppSettings does NOT actually scope its JSON file to the script_dir constructor arg
    # -- self._path is always os.path.join(LOCALES_DIR, SETTINGS_FILENAME), a single
    # shared per-install location (see the module's own docstring: "every small
    # per-install runtime setting lives in ONE place"). So the only way to sandbox this
    # test away from Artur's REAL app_settings.json (which may already have a real
    # env_status from an actual wizard run) is to monkeypatch the module-level
    # LOCALES_DIR itself before constructing AppSettings, same "patch the module global,
    # not the instance" approach this file already uses for es.tempfile.gettempdir
    # elsewhere. Confirmed this is load-bearing, not defensive: an earlier version of
    # this test pointed AppSettings at a fresh tempfile.mkdtemp() script_dir and still
    # read back a pre-existing all_ok=True report from the real repo location.
    tmp_dir = tempfile.mkdtemp(prefix="env_status_test_")
    orig_locales_dir = app_settings_module.LOCALES_DIR
    app_settings_module.LOCALES_DIR = tmp_dir
    try:
        a = AppSettings(tmp_dir)
        check(a.env_status is None,
              f"a fresh install must report env_status=None until the first real check "
              f"(got {a.env_status!r})")

        missing_report = {
            "all_ok": False, "distro": "Ubuntu",
            "checks": [{"id": "wsl_present", "ok": True},
                       {"id": "distro_present", "ok": False},
                       {"id": "packages", "ok": False}],
        }
        a.set_env_status(missing_report)
        check(a.env_status == missing_report,
              "set_env_status() must be readable back immediately via env_status")

        # A second AppSettings instance over the SAME (still-patched) LOCALES_DIR --
        # confirms this actually hit disk (app_settings.json) rather than only living in
        # the first instance's memory, same round-trip check cudasieve_status's own
        # docstring assumes but this property had never had automated coverage for until
        # now.
        b = AppSettings(tmp_dir)
        check(b.env_status == missing_report,
              "env_status must persist to disk and be readable from a fresh AppSettings "
              "instance over the same directory")

        ok_report = {
            "all_ok": True, "distro": "Ubuntu",
            "checks": [{"id": "wsl_present", "ok": True},
                       {"id": "distro_present", "ok": True},
                       {"id": "packages", "ok": True}],
        }
        b.set_env_status(ok_report)
        c = AppSettings(tmp_dir)
        check(c.env_status == ok_report,
              "a later set_env_status() call must overwrite the previous report, not "
              "merge/append to it")
    finally:
        app_settings_module.LOCALES_DIR = orig_locales_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================================================

if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All checks passed.")
