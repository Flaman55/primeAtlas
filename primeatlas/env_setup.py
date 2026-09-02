"""
env_setup.py -- first-run environment check/installer for PrimeAtlas.

Context (Artur, 2026-09-02): PrimeAtlas's backend scripts (prime_sieve/*, constellation/*)
actually run INSIDE WSL, launched from this native-Windows GUI via wsl.exe (see
generation.py's build_wsl_logged_command()/WslLoggedRunner). On a machine that already has
WSL + Ubuntu + the right system packages set up, that's invisible. On a FRESH machine it
is not: Artur hit this directly setting up a second PC (see his own
"INSTALL_WSL_PRIMEATLAS.md" notes) and had to, by hand: enable the WSL/VirtualMachinePlatform
Windows features (which required a reboot), install Ubuntu, then apt-install python3-full,
python3-numpy, libprimesieve12/-dev, and run ldconfig -- all BEFORE PrimeAtlas could launch
anything successfully. This module automates that discovery+repair, gated on user
confirmation, so a new user only ever clicks a single "Install everything" button (see
env_setup_wizard.py for the UI) instead of following a manual checklist in a text file.

Design decision (confirmed with Artur, 2026-09-02): do the FULL install upfront, on first
run, rather than lazily discovering+installing pieces mid-task. This is not just UX
preference -- it's forced by a real Windows constraint: enabling the WSL/
VirtualMachinePlatform optional features can require a REBOOT before `wsl --install` will
work at all (see RESTART_PENDING_EXIT_CODES below). A lazy "install whatever's missing when
a job needs it" design would have to interrupt an in-progress generation run, ask for a
reboot, and somehow resume -- much worse than blocking once, up front, before any tab is
even built. Truly optional, non-blocking extras (e.g. libgmp-dev/libmpfr-dev for a future
research module that might want arbitrary-precision C libraries) are deliberately NOT part
of this upfront set -- see REQUIRED_APT_PACKAGES's own comment.

Design decision (confirmed with Artur, 2026-09-02): the WSL distro's default user is ROOT,
not an interactively-created personal account. A fresh `wsl --install -d Ubuntu` normally
launches the distro once to run an OOBE step that prompts (in a terminal) for a new UNIX
username+password -- something this module cannot answer non-interactively, and would
otherwise be the one piece of this whole flow that can't be automated. The fix used here:
install with --no-launch (never triggers that OOBE at all), then explicitly set every WSL
invocation this module and the app's own launchers use to `-u root`, plus set /etc/wsl.conf
so that even a bare `wsl` terminal opens as root -- root already exists in any base Ubuntu
rootfs, unrelated to the OOBE step, so this sidesteps the interactive prompt entirely rather
than trying to script an answer to it. NOT YET VERIFIED on a real machine with WSL fully
absent (this sandbox has no Windows/WSL to test against) -- flagged plainly, matching this
project's usual practice; see env_setup_wizard.py's own hand-off note.

Pure Python, no tkinter dependency -- exercised directly by unit tests (see
unitTests/test_env_setup.py), same "backend has zero UI dependency" split as every other
primeatlas/ module (app_settings.py, generation.py, ...). All subprocess-touching functions
are thin and separately named specifically so tests can monkeypatch them without needing a
real Windows/WSL environment.
"""
import os
import re
import subprocess
import tempfile
import time

DEFAULT_WSL_DISTRO = "Ubuntu"

# The two Windows optional features PrimeAtlas's WSL2 backend needs enabled. Matches
# Artur's own manual notes (INSTALL_WSL_PRIMEATLAS.md section 2.1) exactly.
REQUIRED_WINDOWS_FEATURES = (
    "Microsoft-Windows-Subsystem-Linux",
    "VirtualMachinePlatform",
)

# System packages installed INSIDE the WSL distro, as root, system-wide (not into a venv --
# see INSTALL_WSL_PRIMEATLAS.md section 6: "Jesli PrimeAtlas jest uruchamiany z aplikacji
# Windows -> venv nie jest uzywany", since this app's own wsl.exe launches never activate
# one). Mirrors that doc's sections 4-5 exactly. Deliberately does NOT include the doc's
# optional 5.3 (libgmp-dev/libmpfr-dev) -- those are specific to research modules that may
# never be used in a given install, have no reboot/feature-enable dependency, and so are a
# genuinely good fit for on-demand, later installation (e.g. a future "Zainstaluj
# GMP/MPFR" button next to whichever Badania sub-tab first needs them) rather than being
# forced on every install of what is meant to become a general-purpose tool, not just a
# magazyn generator (Artur, 2026-09-02).
REQUIRED_APT_PACKAGES = (
    "python3-full", "python3-pip", "python3-numpy",
    "libprimesieve12", "libprimesieve-dev",
)

# dism.exe's own documented exit codes: 0 = success, no reboot needed; 3010/3011 = success,
# reboot required before the enabled feature is actually usable. Anything else is a real
# error (insufficient privileges most commonly, if this ran without the elevation prompt
# being accepted).
RESTART_PENDING_EXIT_CODES = frozenset({3010, 3011})

_WINDOWS_DRIVE_PATH_RE = re.compile(r'^([A-Za-z]):[\\/](.*)$')


def _windows_path_to_wsl(path):
    """Same mapping as generation.py's windows_path_to_wsl() -- duplicated rather than
    imported, matching this app's established pattern (see generation.py's own
    CUDASIEVE_MIN_PRINTABLE_TOP-style comments) of small, stable constants/helpers being
    copied across the native/WSL boundary rather than cross-imported, so this module stays
    usable standalone (it may run before anything else in the app has decided a portal
    folder even matters)."""
    m = _WINDOWS_DRIVE_PATH_RE.match(path)
    if not m:
        return path.replace("\\", "/")
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def _popen_kwargs_no_window():
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


# ------------------------------------------------------------------------------------------
# Thin subprocess layer -- every function below is deliberately small and separately named
# so unit tests can monkeypatch exactly one of them without needing a real Windows/WSL
# environment. None of these use subprocess.run(..., timeout=...) directly against a pipe
# that wraps wsl.exe's own Linux-side process -- see run_cudasieve_wsl_blocking()'s docstring
# in generation.py for the confirmed hang bug that pattern hits. Plain Windows-only commands
# (dism.exe, wsl.exe --status/-l, powershell.exe) are NOT wrapping a Linux-side process and
# do not exhibit that bug, so they use the simpler subprocess.run(..., timeout=...) form;
# anything that runs a command INSIDE the WSL distro uses the same Popen+poll-loop pattern
# WslLoggedRunner/run_cudasieve_wsl_blocking already use in production.
# ------------------------------------------------------------------------------------------

def _run_windows(argv, timeout=30):
    """Runs a plain Windows-side command. Returns (returncode, stdout, stderr).
    returncode is None on total launch failure (FileNotFoundError -- the executable itself
    doesn't exist, e.g. wsl.exe on a machine with WSL fully absent) or timeout."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            **_popen_kwargs_no_window())
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return None, "", "executable-not-found"
    except subprocess.TimeoutExpired:
        return None, "", "timed-out"
    except OSError as e:
        return None, "", str(e)


def _run_inside_wsl_blocking(distro, bash_command, timeout=120):
    """Runs `bash_command` inside `distro` AS ROOT (see this module's own docstring for
    why root, not a per-user sudo flow -- this also conveniently means apt installs never
    need a password prompt). Uses the same Popen()+manual poll()-loop+file-redirected-
    output pattern as generation.py's run_cudasieve_wsl_blocking(), for the exact same
    documented reason (subprocess.run's own timeout handling can hang forever against
    wsl.exe's stdout pipe -- see that function's docstring). Returns
    (returncode_or_None, stdout_text). returncode is None on launch failure or timeout (in
    which case the underlying wsl.exe/Linux process may still be running in the
    background -- same caveat as run_cudasieve_wsl_blocking)."""
    tmp_dir = tempfile.gettempdir()
    run_id = f"primeatlas_env_setup_{int(time.time() * 1000)}_{os.getpid()}"
    log_path = os.path.join(tmp_dir, f"{run_id}.log")
    exit_path = os.path.join(tmp_dir, f"{run_id}.exit")
    log_wsl = _windows_path_to_wsl(log_path)
    exit_wsl = _windows_path_to_wsl(exit_path)
    # Plain single-quoting (not shlex) is safe here: log_wsl/exit_wsl are ALWAYS this
    # function's own generated temp paths (never user/caller-controlled content).
    full_cmd = f"({bash_command}) > '{log_wsl}' 2>&1; echo $? > '{exit_wsl}'"
    argv = ["wsl.exe", "-d", distro, "-u", "root", "-e", "bash", "-c", full_cmd]
    try:
        proc = subprocess.Popen(argv, **_popen_kwargs_no_window())
    except OSError:
        return None, ""
    deadline = time.time() + timeout
    while proc.poll() is None:
        if time.time() > deadline:
            try:
                proc.kill()
            except OSError:
                pass
            for p in (log_path, exit_path):
                try:
                    os.remove(p)
                except OSError:
                    pass
            return None, ""
        time.sleep(0.2)
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            stdout = f.read()
    except OSError:
        stdout = ""
    returncode = None
    try:
        with open(exit_path, encoding="utf-8", errors="replace") as f:
            code_text = f.read().strip()
        if code_text.isdigit():
            returncode = int(code_text)
    except OSError:
        pass
    for p in (log_path, exit_path):
        try:
            os.remove(p)
        except OSError:
            pass
    return returncode, stdout


# ------------------------------------------------------------------------------------------
# Checks -- pure(ish) orchestration around the thin layer above. Each check is independent
# and best-effort: a check that can't determine an answer (WSL not reachable at all) reports
# ok=False with an honest detail string, never raises.
# ------------------------------------------------------------------------------------------

def _check_wsl_present():
    """Distinguishes 'wsl.exe does not exist at all' (feature never enabled, or pre-Win10
    1903) from 'wsl.exe exists and reports a working install'. Does NOT try to parse
    dism/wsl's own (possibly localized) text to distinguish finer-grained reasons for
    failure -- see this module's own docstring: the install path is idempotent, so exact
    root-cause detection isn't needed to decide what to run next, only whether SOMETHING
    is missing."""
    returncode, stdout, stderr = _run_windows(["wsl.exe", "--status"], timeout=15)
    if returncode is None:
        return {"id": "wsl_present", "ok": False,
                "detail": "wsl.exe not found (WSL feature likely not enabled)"}
    if returncode == 0:
        return {"id": "wsl_present", "ok": True, "detail": stdout.strip()[:300]}
    return {"id": "wsl_present", "ok": False,
            "detail": (stderr or stdout or "wsl.exe --status returned an error").strip()[:300]}


def _check_distro_present(distro):
    returncode, stdout, stderr = _run_windows(["wsl.exe", "-l", "-q"], timeout=15)
    if returncode is None:
        return {"id": "distro_present", "ok": False, "detail": "wsl.exe not reachable"}
    # `wsl -l -q` prints one distro name per line, often UTF-16-decoded-as-mojibake with
    # embedded NUL bytes on some Windows builds -- strip NULs before comparing, same
    # defensive normalization this app's other WSL-output parsers already need.
    names = [line.replace("\x00", "").strip() for line in stdout.splitlines()]
    names = [n for n in names if n]
    found = any(n.lower() == distro.lower() for n in names)
    return {"id": "distro_present", "ok": found,
            "detail": f"installed distros: {names}" if names else "no distro installed"}


def _check_packages(distro, timeout=60):
    """One combined probe inside WSL for python3/numpy/libprimesieve -- three separate
    round-trips would be three times the wsl.exe cold-start cost for no real benefit,
    since the wizard only ever acts on 'is everything OK or not', not on which ONE package
    is missing (the install step reinstalls the whole REQUIRED_APT_PACKAGES set either
    way, same idempotent-reasoning as _check_wsl_present())."""
    probe = (
        "python3 -c 'import numpy' >/dev/null 2>&1 && echo NUMPY_OK || echo NUMPY_MISSING; "
        "python3 -c \"import ctypes; ctypes.CDLL('libprimesieve.so.12')\" "
        ">/dev/null 2>&1 && echo PRIMESIEVE_OK || echo PRIMESIEVE_MISSING"
    )
    returncode, stdout = _run_inside_wsl_blocking(distro, probe, timeout=timeout)
    if returncode is None:
        return {"id": "packages", "ok": False,
                "detail": "could not reach WSL to check packages"}
    numpy_ok = "NUMPY_OK" in stdout
    primesieve_ok = "PRIMESIEVE_OK" in stdout
    ok = numpy_ok and primesieve_ok
    detail = f"numpy={'ok' if numpy_ok else 'missing'}, " \
             f"libprimesieve={'ok' if primesieve_ok else 'missing'}"
    return {"id": "packages", "ok": ok, "detail": detail,
            "numpy_ok": numpy_ok, "primesieve_ok": primesieve_ok}


def check_environment(distro=DEFAULT_WSL_DISTRO, timeout=60):
    """Runs every check in order, short-circuiting the later, more expensive ones once an
    earlier prerequisite is already known to be missing (no point probing for numpy inside
    a distro that isn't even installed). Returns a report dict:
        {"all_ok": bool, "distro": str, "checks": [check, ...]}
    where each check is {"id", "ok", "detail", ...}. Never raises -- every failure mode
    (WSL absent, distro absent, WSL unreachable, package probe timeout) is captured as
    ok=False with an explanatory detail string, same "never crash the caller, always
    return an honest report" contract as check_environment()'s siblings elsewhere in this
    app (e.g. run_cudasieve_wsl_blocking's two-tuple contract)."""
    checks = []
    wsl_check = _check_wsl_present()
    checks.append(wsl_check)
    if not wsl_check["ok"]:
        checks.append({"id": "distro_present", "ok": False,
                        "detail": "skipped -- WSL itself is not available"})
        checks.append({"id": "packages", "ok": False,
                        "detail": "skipped -- WSL itself is not available"})
        return {"all_ok": False, "distro": distro, "checks": checks}

    distro_check = _check_distro_present(distro)
    checks.append(distro_check)
    if not distro_check["ok"]:
        checks.append({"id": "packages", "ok": False,
                        "detail": f"skipped -- {distro} is not installed"})
        return {"all_ok": False, "distro": distro, "checks": checks}

    packages_check = _check_packages(distro, timeout=timeout)
    checks.append(packages_check)
    all_ok = wsl_check["ok"] and distro_check["ok"] and packages_check["ok"]
    return {"all_ok": all_ok, "distro": distro, "checks": checks}


# ------------------------------------------------------------------------------------------
# Install -- one elevated PowerShell script covering EVERY step that needs Administrator
# rights (dism.exe feature-enable, `wsl --install`), so accepting ONE UAC prompt covers the
# whole sequence rather than one prompt per elevated command. Steps that don't need
# elevation (the WSL-internal apt install, since it runs as root INSIDE the distro, not as
# Windows Administrator) still run from inside the same script for simplicity -- being
# elevated doesn't hurt them, and it keeps the whole sequence in one place to reason about.
# ------------------------------------------------------------------------------------------

def _build_install_ps1_text(distro, need_features=True, need_distro=True, need_packages=True):
    """Builds the PowerShell script text run (elevated) by run_install(). Pure string
    building -- no subprocess calls here, so this is directly unit-testable without any
    Windows/WSL environment (see unitTests/test_env_setup.py). Exit code contract: 0 = full
    success; 3010 = success but a reboot is required before continuing (mirrors dism.exe's
    own convention, checked explicitly after each feature-enable step rather than trusted
    to propagate through $LASTEXITCODE, since PowerShell doesn't always forward a native
    exe's exit code automatically); any other non-zero = a real failure, detail in the
    transcript this script also writes to its own log file.

    Logging design (Artur, 2026-09-02, third fix from the same real-hardware session --
    the previous two got this script actually elevating and running with readable output,
    which is what surfaced this one): every `exit N` here MUST remain a plain top-level
    statement, never inside a pipe or nested scriptblock -- _run_elevated_ps1() previously
    piped this whole script's output into `Out-File` (`& script.ps1 *>&1 | Out-File ...`)
    to fix the UTF-16 mojibake bug, but that silently broke exit-code propagation instead:
    on real hardware the script correctly detected RESTART_REQUIRED and called `exit 3010`,
    yet run_install() received code 1. Making the script's OWN exit code the pipeline's
    exit code is not reliably guaranteed once it's a pipeline producer rather than a bare
    top-level script -- so instead of changing how the OUTER call captures output,
    logging is now self-contained: this script computes its own log path from
    $PSCommandPath (which _run_elevated_ps1 computes as ps1_path + ".log" in Python --
    same path, computed independently on each side) and appends to it itself via
    Add-Content -Encoding UTF8 through a small Log helper, used everywhere in place of a
    bare Write-Output. _run_elevated_ps1 goes back to a completely unadorned
    `-File ps1_path` invocation with no pipe or redirection wrapped around it at all, so
    `exit 3010`/`exit 1`/`exit 0` here always ends up as this script's own real process
    exit code with zero ambiguity -- the classic, unsurprising way exit codes are meant to
    work for a top-level .ps1 script.

    Checklist design (Artur, 2026-09-02, fourth fix, same real-hardware session -- the
    previous three got this script actually running steps correctly, which is what
    surfaced this one): run_install() used to always build and run the FULL linear
    sequence (features -> distro -> default-root-user -> apt packages) no matter what
    check_environment() had just found. On a machine that already had the WSL2 features
    enabled -- e.g. right after the reboot THIS SAME SCRIPT had just required -- that meant
    unconditionally re-running `wsl --install -d Ubuntu --no-launch` against an
    ALREADY-installed distro, which failed outright on real hardware with
    Wsl/InstallDistro/ERROR_ALREADY_EXISTS (exit code -1 -- not one of the 1/2 codes this
    script already tolerated as harmless, and WSL's exact "already exists" exit code
    clearly isn't stable enough to enumerate). need_features/need_distro/need_packages are
    plain Python booleans decided by run_install() from a check_environment() report
    BEFORE this text is even built, not runtime PowerShell conditionals -- a step that
    isn't needed is simply never emitted into the script at all, so a machine where
    everything is already present never launches an elevated process in the first place
    (see run_install()). As a second, defense-in-depth layer for the specific bug that was
    hit (in case a distro that check_environment() somehow missed genuinely does already
    exist), the wsl_install step also inspects its own output text for ALREADY_EXISTS and
    treats that as a harmless no-op regardless of exit code, alongside the historical 1/2
    tolerance."""
    lines = [
        '$ErrorActionPreference = "Stop"',
        '$LogPath = $PSCommandPath + ".log"',
        'if (Test-Path $LogPath) { Remove-Item $LogPath -Force }',
        'function Log($msg) {',
        '    Write-Output $msg',
        '    Add-Content -Path $LogPath -Value $msg -Encoding UTF8',
        '}',
        '',
    ]
    if need_features:
        lines.append('$restartNeeded = $false')
        lines.append('Log "STEP:features"')
        for name in REQUIRED_WINDOWS_FEATURES:
            lines.append(f'Log "STEP:enable_feature:{name}"')
            lines.append(
                f'dism.exe /online /enable-feature /featurename:{name} /all /norestart '
                f'2>&1 | ForEach-Object {{ Log $_ }}')
            lines.append(
                'if ($LASTEXITCODE -eq 3010 -or $LASTEXITCODE -eq 3011) { $restartNeeded = $true }')
            lines.append(
                f'elseif ($LASTEXITCODE -ne 0) {{ Log "FEATURE_ENABLE_FAILED:{name}:$LASTEXITCODE"; exit 1 }}')
        lines.append('if ($restartNeeded) {')
        lines.append('    Log "RESTART_REQUIRED"')
        lines.append('    exit 3010')
        lines.append('}')
        lines.append('')
    if need_distro:
        lines.append('Log "STEP:wsl_install"')
        lines.append(f'$wslInstallOutput = & wsl.exe --install -d {distro} --no-launch 2>&1')
        lines.append('$wslInstallOutput | ForEach-Object { Log $_ }')
        lines.append('$wslInstallExit = $LASTEXITCODE')
        # Some WSL versions report an already-installed distro as exit code 1 or 2
        # (historical tolerance, kept as a fallback); others -- confirmed on real
        # hardware -- report a genuinely different, non-enumerable code (-1 seen in
        # practice) but always include this marker text in the output either way, so
        # checking for the text directly is the more robust signal.
        lines.append('$alreadyExists = ($wslInstallOutput -join "`n") -match "ALREADY_EXISTS"')
        lines.append(
            'if ($wslInstallExit -ne 0 -and $wslInstallExit -ne 1 -and $wslInstallExit -ne 2 '
            '-and -not $alreadyExists) {')
        lines.append('    Log "WSL_INSTALL_FAILED:$wslInstallExit"')
        lines.append('    exit 1')
        lines.append('}')
        lines.append('')
        lines.append('Log "STEP:default_root_user"')
        lines.append(
            f'wsl.exe -d {distro} -u root -e bash -c "printf \'[user]\\ndefault=root\\n\' '
            f'> /etc/wsl.conf" 2>&1 | ForEach-Object {{ Log $_ }}')
        lines.append(f'wsl.exe --terminate {distro}')
        lines.append('')
    if need_packages:
        apt_packages = " ".join(REQUIRED_APT_PACKAGES)
        lines.append('Log "STEP:apt_packages"')
        lines.append(
            f'wsl.exe -d {distro} -u root -e bash -c "apt-get update -y && apt-get install -y '
            f'{apt_packages} && ldconfig" 2>&1 | ForEach-Object {{ Log $_ }}')
        lines.append('if ($LASTEXITCODE -ne 0) {')
        lines.append('    Log "APT_INSTALL_FAILED:$LASTEXITCODE"')
        lines.append('    exit 1')
        lines.append('}')
        lines.append('')
    lines.append('Log "STEP:done"')
    lines.append('exit 0')
    return "\n".join(lines) + "\n"


def _run_elevated_ps1(ps1_path, timeout=1800):
    """Launches ps1_path elevated (a single UAC prompt) via
    Start-Process ... -Verb RunAs -Wait -PassThru, and recovers the ELEVATED process's own
    exit code by having the (non-elevated) outer PowerShell print it, since the outer
    process's own exit code is powershell.exe's, not the elevated child's. Returns
    (returncode_or_None, transcript_text). NOT the WSL-pipe-hang-prone pattern (this wraps
    powershell.exe/Start-Process, not wsl.exe's own bash process -- see this module's
    header comment on why subprocess.run(..., timeout=...) is safe here).

    Bug 1 fixed here (Artur, 2026-09-02, caught on real hardware): Start-Process's own
    -RedirectStandardOutput/-RedirectStandardError/-RedirectStandardInput parameters are NOT
    supported together with -Verb RunAs -- elevation goes through ShellExecuteEx, which has
    no redirected-handle model for Start-Process to hook into. Combining them does not throw
    a terminating error; Start-Process just writes a non-terminating "parameter is incorrect"
    error to the error stream and returns $null, so $p.ExitCode reads as empty. The original
    version of this function used -RedirectStandardOutput and treated that empty result as
    "elevation was declined", which fired instantly and unconditionally on real hardware --
    well before any UAC dialog could plausibly have been shown, let alone dismissed.

    Bug 2 (same session, caught via the wizard's own "Copy log" button once bug 1 was
    fixed): a bare `*>` redirect (the first fix's own approach) defers to Windows
    PowerShell 5.1's own default encoding for file redirection, which is UTF-16LE, not
    UTF-8 -- reading that back as UTF-8 decoded every 2-byte-per-character run into
    mojibake.

    Bug 3 (same session, caught on the very next real-hardware run once bugs 1-2 were
    fixed and the script was actually completing steps): piping the elevated script's
    output into Out-File to fix bug 2 (`& script.ps1 *>&1 | Out-File ...`) turned the
    script into a pipeline PRODUCER rather than a bare top-level script -- and `exit 3010`
    inside a script in that position does not reliably become the pipeline's/process's own
    exit code. On real hardware the script printed RESTART_REQUIRED and called `exit 3010`
    correctly, yet run_install() received code 1 instead.

    All three are fixed together by moving logging OUT of this function entirely: the
    elevated .ps1 script (_build_install_ps1_text) now writes its own log file directly, at
    $PSCommandPath + ".log" (Add-Content -Encoding UTF8, computed from its own path so it
    lines up with log_path here without needing to pass anything in), via a small Log
    helper used everywhere in place of Write-Output -- see that function's own docstring.
    That leaves this function free to go back to the simplest possible invocation: a bare
    `-File ps1_path`, no pipe, no redirection wrapped around it at all, so `exit N` inside
    the script always becomes this function's own, unambiguous elevated exit code -- the
    ordinary way a top-level .ps1's exit code is meant to work -- while -Verb RunAs -Wait
    -PassThru (still with no -RedirectStandard* parameter, per bug 1) remains the normal,
    documented way to capture it.

    -WindowStyle Hidden is passed too (compatible with -Verb RunAs, unlike
    -RedirectStandard*): without it, an elevated console window visibly flashes open and
    scrolls through dism/wsl/apt output on the user's desktop for the whole install --
    confusing alongside the wizard's own log widget, which already shows the same content
    via the Log helper above, and a likely source of Artur seeing what looked like two
    different, disagreeing "terminals" during testing."""
    log_path = ps1_path + ".log"
    launcher = (
        f'$p = Start-Process -FilePath "powershell.exe" '
        f'-ArgumentList \'-NoProfile\',\'-ExecutionPolicy\',\'Bypass\',\'-File\',\'{ps1_path}\' '
        f'-Verb RunAs -Wait -PassThru -WindowStyle Hidden; '
        f'Write-Output $p.ExitCode'
    )
    returncode, stdout, stderr = _run_windows(
        ["powershell.exe", "-NoProfile", "-Command", launcher], timeout=timeout)
    transcript = ""
    try:
        with open(log_path, encoding="utf-8-sig", errors="replace") as f:
            transcript = f.read()
    except OSError:
        pass
    if returncode != 0:
        # The OUTER (non-elevated) launcher itself failed to even start Start-Process --
        # e.g. the user declined the UAC prompt (Start-Process -Verb RunAs raises when
        # the elevation request is cancelled). Distinct from the INNER script failing.
        return None, (stderr or stdout or transcript or "elevation was declined or failed")
    last_line = stdout.strip().splitlines()[-1] if stdout.strip() else ""
    try:
        elevated_code = int(last_line)
    except ValueError:
        elevated_code = None
    return elevated_code, transcript


def run_install(distro=DEFAULT_WSL_DISTRO, timeout=1800, work_dir=None, report=None):
    """Runs only the install steps check_environment() says are actually missing (Windows
    features, WSL+distro, apt packages -- any subset), behind a single UAC elevation
    prompt (or none at all if nothing is missing). Returns {"ok": bool, "restart_required":
    bool, "transcript": str, "error": str-or-None}.

    report, if given, is a check_environment() result the caller already has -- typically
    the wizard's own last check, which is what enabled its "Install everything" button in
    the first place, so reusing it here avoids paying for a second, redundant WSL round-
    trip immediately before every install. If not given, this function runs its own
    check_environment() call first (capped at 60s regardless of `timeout`, since that
    parameter governs the elevated install itself, not this quick pre-check).

    Checklist design (Artur, 2026-09-02): this function used to unconditionally build and
    run the FULL linear sequence every time, regardless of what was actually missing. On a
    machine that already had the WSL2 features enabled -- e.g. right after the reboot this
    very function had just required -- that meant blindly re-running `wsl --install -d
    Ubuntu --no-launch` against an ALREADY-installed distro, which failed outright on real
    hardware (Wsl/InstallDistro/ERROR_ALREADY_EXISTS). See _build_install_ps1_text's own
    docstring for the full story and the matching fix on the script-generation side; this
    function's own part of that fix is deciding, from the report, which of
    need_features/need_distro/need_packages are actually True and passing only those
    through -- if none are, no elevation is attempted at all.

    restart_required=True means the Windows features were just enabled and a REBOOT is
    needed before the rest of this sequence (WSL distro install, apt packages) can
    meaningfully run -- callers (env_setup_wizard.py) must stop here, tell the user to
    restart, and persist enough state (AppSettings.setup_completed stays False) to resume
    this same function after the app is relaunched post-reboot; see that module for the
    resume flow. Safe to call again after a restart -- the checklist naturally skips the
    features step entirely on the resumed run (check_environment() will find WSL already
    present), no separate 'which step was I on' state needed.

    NOT YET RUN on real Windows hardware (this sandbox has no Windows/WSL) -- see
    env_setup_wizard.py's own hand-off note. work_dir lets tests point the scratch .ps1
    file somewhere other than the real temp dir; defaults to tempfile.gettempdir()."""
    if report is None:
        report = check_environment(distro=distro, timeout=min(timeout, 60))
    checks_by_id = {c["id"]: c for c in report.get("checks", [])}
    need_features = not checks_by_id.get("wsl_present", {}).get("ok", False)
    need_distro = not checks_by_id.get("distro_present", {}).get("ok", False)
    need_packages = not checks_by_id.get("packages", {}).get("ok", False)
    if not (need_features or need_distro or need_packages):
        return {"ok": True, "restart_required": False,
                "transcript": "STEP:nothing_to_install\n", "error": None}

    work_dir = work_dir or tempfile.gettempdir()
    ps1_path = os.path.join(
        work_dir, f"primeatlas_env_setup_{int(time.time() * 1000)}.ps1")
    script_text = _build_install_ps1_text(
        distro, need_features=need_features, need_distro=need_distro,
        need_packages=need_packages)
    try:
        with open(ps1_path, "w", encoding="utf-8") as f:
            f.write(script_text)
    except OSError as e:
        return {"ok": False, "restart_required": False, "transcript": "",
                "error": f"could not write install script: {e}"}
    try:
        returncode, transcript = _run_elevated_ps1(ps1_path, timeout=timeout)
    finally:
        try:
            os.remove(ps1_path)
        except OSError:
            pass
        try:
            os.remove(ps1_path + ".log")
        except OSError:
            pass
    if returncode is None:
        return {"ok": False, "restart_required": False, "transcript": transcript,
                "error": "elevation was declined or the installer could not be launched"}
    if returncode in RESTART_PENDING_EXIT_CODES:
        return {"ok": False, "restart_required": True, "transcript": transcript, "error": None}
    if returncode == 0:
        return {"ok": True, "restart_required": False, "transcript": transcript, "error": None}
    return {"ok": False, "restart_required": False, "transcript": transcript,
            "error": f"install script exited with code {returncode}"}
