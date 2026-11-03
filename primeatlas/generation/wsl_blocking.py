"""
wsl_blocking.py -- blocking WSL calls with a hang-safe timeout (Popen plus a manual poll
loop over log/exit files, never wait()/communicate()): CUDASieve --status/--fetch-license,
primecount queries, and the primecount apt install.

Every WSL-launching function takes an explicit `portal_folder` argument: the storage path
can change at runtime (PortalBrowserApp's _set_portal_folder rebinds its own module
global), so the caller passes the CURRENT value at each call site.
"""
import json
import os
import shlex
import subprocess
import time

from .wsl_command import (_popen_kwargs_no_window, build_wsl_logged_command,
                          generation_log_paths, windows_path_to_wsl)


def run_cudasieve_wsl_blocking(argv, portal_folder, timeout=120):
    """Blocking wsl.exe call for --status/--fetch-license (both answer in a few seconds at
    most under normal conditions -- --fetch-license's git clone/fetch is the slow part,
    hence the longer default timeout than a quick status ping). Returns (True, payload)/
    (False, error_message), same two-tuple contract as run_primesieve_query_wsl()
    (primesieve_calc_tab.py) and every other WSL-launching call in this app.

    `portal_folder` is an explicit parameter, not a bare module global -- see this
    module's own docstring for why every WSL-launching function here takes it that way
    (settings_tab.py's wsl_helpers wraps this in a lambda supplying the CURRENT storage
    path, same as it already does for build_wsl_logged_command).

    Does NOT use the simple subprocess.run(cmd, timeout=timeout) pattern
    run_primesieve_query_wsl() uses (primesieve_calc_tab.py):

    1) subprocess.run() against wsl.exe's own stdout pipe can hang indefinitely from
       this windowed/console-less Tk process, even when the same command returns
       instantly from a terminal -- the console-allocation/pipe-hang failure mode
       build_wsl_logged_command()'s docstring documents.
    2) With file redirection instead of a pipe, subprocess.run(..., timeout=timeout)
       can still hang: on Windows, when Popen.communicate(timeout=timeout) raises
       TimeoutExpired, subprocess.run() calls process.kill() and then
       process.communicate() a SECOND time with NO timeout (see subprocess.py). If
       wsl.exe doesn't die from kill() (a killed Windows-side wrapper does not
       necessarily take the Linux process down -- see WslLoggedRunner), that untimed
       call can hang forever, defeating `timeout=` regardless of its value.

    So this uses WslLoggedRunner's pattern instead: Popen() (non-blocking) plus a
    manual proc.poll() loop, never wait()/communicate(). (run_primesieve_query_wsl()
    carries the same latent risk, but its sub-second queries make the timeout path
    unlikely.)

    The actual Popen/poll/log-read mechanics live in _run_wsl_blocking_via_logfile() below
    -- factored out so primecount's own blocking WSL calls (run_primecount_wsl_blocking(),
    used by the Research -> pi(x) approximations tab's "primecount" data-source mode) reuse
    this exact same hang-safe pattern instead of the naive subprocess.run(..., timeout=...)
    run_primesieve_query_wsl() uses -- primecount's
    own calls (an apt-get install, or a pi_batch query against a deliberately huge x) are
    exactly the kind of longer-running WSL call most likely to actually trigger the timeout
    codepath this whole docstring is about, unlike a single sub-second primesieve query."""
    return _run_wsl_blocking_via_logfile(argv, portal_folder, "cudasieve_query", timeout)


def _wait_for_wsl_process(proc, timeout, cleanup_paths):
    """Polls an already-started Popen `proc` until it exits or `timeout` elapses, NEVER
    calling wait()/communicate() (see run_cudasieve_wsl_blocking's own docstring for the
    real, confirmed-live hang this specifically avoids) -- the shared timeout-safe core
    every blocking-WSL-call function in this module builds on. On timeout, kills the
    process and removes every path in `cleanup_paths` before returning False (the
    underlying wsl.exe/WSL-side process may still be running afterward regardless --
    kill() only stops THIS function from waiting on it any longer, see the call sites'
    own comments); returns True once the process has genuinely exited on its own."""
    deadline = time.time() + timeout
    while proc.poll() is None:
        if time.time() > deadline:
            try:
                proc.kill()
            except OSError:
                pass
            for p in cleanup_paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
            return False
        time.sleep(0.2)
    return True


def _read_and_cleanup_wsl_log(log_path, exit_path):
    """Reads log_path's full text and exit_path's exit code (both written by
    build_wsl_logged_command()'s own `> log 2>&1; echo $? > exit` convention, or by a
    caller building an equivalent raw bash command directly, e.g. run_primecount_
    install_wsl_blocking()'s apt-get chain) -- ALWAYS removes both files afterward,
    regardless of whether either read actually succeeded. Returns (log_text_or_None,
    exit_code_or_None) -- either half independently None if that particular file
    couldn't be read/parsed, never raises."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            log_text = f.read().strip()
    except OSError:
        log_text = None
    exit_code = None
    try:
        with open(exit_path, encoding="utf-8", errors="replace") as f:
            exit_code = int(f.read().strip())
    except (OSError, ValueError):
        pass
    for p in (log_path, exit_path):
        try:
            os.remove(p)
        except OSError:
            pass
    return log_text, exit_code


def _run_wsl_blocking_via_logfile(argv, portal_folder, log_prefix, timeout):
    """Shared Popen/manual-poll/file-log implementation behind run_cudasieve_wsl_blocking()
    (see that function's own docstring for why this exists instead of a plain
    subprocess.run(cmd, timeout=timeout) call). `log_prefix` is only ever used to
    namespace the temp log/exit filenames (generation_log_paths()'s own `prefix`
    argument) -- everything else about this function is fully generic.

    Returns (True, payload)/(False, error_message), same two-tuple contract as
    run_primesieve_query_wsl() -- `payload` is the FULL parsed JSON dict on success (not
    just its "result" field), matching this function's own existing callers (e.g.
    updates_section.py's CUDASieve status handler reads specific keys off of it). See
    run_primecount_wsl_blocking() below for a DIFFERENT contract (unwrapped result,
    structured failure) -- the two contracts are kept as separate functions."""
    log_path, exit_path, _run_id = generation_log_paths(portal_folder, log_prefix)
    cmd = build_wsl_logged_command(argv, log_path, exit_path, portal_folder)
    try:
        proc = subprocess.Popen(cmd, **_popen_kwargs_no_window())
    except OSError as e:
        return False, f"Could not launch WSL: {e}"
    if not _wait_for_wsl_process(proc, timeout, (log_path, exit_path)):
        return False, f"Timed out after {timeout}s."
    stdout, _exit_code = _read_and_cleanup_wsl_log(log_path, exit_path)
    if stdout is None:
        return False, "Could not read WSL output log"
    last_line = stdout.splitlines()[-1] if stdout else ""
    try:
        payload = json.loads(last_line)
    except (ValueError, IndexError):
        detail = stdout or "(no output)"
        return False, detail[:2000]
    if payload.get("ok"):
        return True, payload
    return False, payload.get("error", "unknown error")


def run_primecount_wsl_blocking(argv, portal_folder, timeout=120):
    """primecount_query.py's own blocking WSL call (a "pi"/"pi_batch"/"nth"/"version"
    query) -- same hang-safe Popen/poll/file-log pattern as run_cudasieve_wsl_blocking()
    (see that function for why not a plain subprocess.run(timeout=...)); a pi_batch
    query against a huge x is exactly the kind of long WSL call that reaches the
    timeout path.

    Does NOT reuse _run_wsl_blocking_via_logfile() above -- that function collapses a
    failure down to a bare message string (matching its own existing callers' needs),
    but research_pi_approx_tab.py's "primecount" data-source mode needs to tell "please
    install it" (primecount_query.py's own "error_kind": "not_installed") apart from any
    OTHER failure, to offer an install prompt instead of a generic error dialog. So this
    function keeps its own, richer contract instead:

    Returns (True, result) on success -- `result` already unwrapped from the query
    script's own {"ok": true, "result": ...} envelope (an int, a list of ints, or a
    version string, depending on the op). Returns (False, {"message": str, "kind": str
    or None}) on failure -- "kind" is "not_installed" specifically when primecount_
    query.py reported that, else None for every other failure (bad input, timeout, WSL
    launch failure, unparseable output)."""
    log_path, exit_path, _run_id = generation_log_paths(portal_folder, "primecount")
    cmd = build_wsl_logged_command(argv, log_path, exit_path, portal_folder)
    try:
        proc = subprocess.Popen(cmd, **_popen_kwargs_no_window())
    except OSError as e:
        return False, {"message": f"Could not launch WSL: {e}", "kind": None}
    if not _wait_for_wsl_process(proc, timeout, (log_path, exit_path)):
        return False, {"message": f"Timed out after {timeout}s.", "kind": None}
    stdout, _exit_code = _read_and_cleanup_wsl_log(log_path, exit_path)
    if stdout is None:
        return False, {"message": "Could not read WSL output log", "kind": None}
    last_line = stdout.splitlines()[-1] if stdout else ""
    try:
        payload = json.loads(last_line)
    except (ValueError, IndexError):
        detail = stdout or "(no output)"
        return False, {"message": detail[:2000], "kind": None}
    if payload.get("ok"):
        return True, payload.get("result")
    return False, {"message": payload.get("error", "unknown error"),
                    "kind": payload.get("error_kind")}


def run_primecount_install_wsl_blocking(portal_folder, timeout=300):
    """Idempotent apt install of libprimecount + its dev headers (primecount,
    libprimecount8, libprimecount-dev, libprimecount-dev-common), run as root inside WSL
    (`wsl.exe -u root` -- needs no password at all, regardless of whether the distro's
    own interactively-configured default user has passwordless sudo or not). Safe to
    click more than once -- apt-get install on
    already-installed packages is a fast no-op.

    NOT a python3-script invocation (unlike every other WSL call in this module) -- the
    apt-get chain needs real shell operators (`&&`) between its steps, which
    build_wsl_logged_command()'s own per-token shlex.quote() join can't carry (each
    token gets individually quoted, turning `&&` into a literal argument instead of a
    shell operator) -- so this builds its own raw bash command string directly instead
    of going through that function, but reuses the exact same Popen/poll/timeout safety
    (_wait_for_wsl_process) as every other function in this module.

    Checks the REAL exit code (via _read_and_cleanup_wsl_log's own exit_path parsing)
    rather than trying to parse stdout as JSON -- apt-get's own output is plain text,
    not a query script's one-line JSON payload. Returns (True, None) on success,
    (False, error_detail) otherwise.

    Deliberately NOT wired through env_setup.py's own heavier elevated-PowerShell
    REQUIRED_APT_PACKAGES flow -- that one handles enabling WSL itself, installing a
    distro, etc. (Administrator-elevated Windows-side steps this on-demand installer has
    no business touching, since by the time ANY tab is usable, WSL and its distro
    already work). Research-module-specific optional C libraries get an on-demand
    install button in Settings -> Updates, next to whichever Research sub-tab first
    needs them, not a blanket first-run install everyone pays for."""
    log_path, exit_path, _run_id = generation_log_paths(portal_folder, "primecount_install")
    log_wsl = windows_path_to_wsl(log_path)
    exit_wsl = windows_path_to_wsl(exit_path)
    bash_cmd = (
        "apt-get update -y && apt-get install -y primecount libprimecount8 "
        "libprimecount-dev libprimecount-dev-common && ldconfig "
        f"> {shlex.quote(log_wsl)} 2>&1; echo $? > {shlex.quote(exit_wsl)}"
    )
    cmd = ["wsl.exe", "-u", "root", "-e", "bash", "-c", bash_cmd]
    try:
        proc = subprocess.Popen(cmd, **_popen_kwargs_no_window())
    except OSError as e:
        return False, f"Could not launch WSL: {e}"
    if not _wait_for_wsl_process(proc, timeout, (log_path, exit_path)):
        return False, f"Timed out after {timeout}s."
    output, exit_code = _read_and_cleanup_wsl_log(log_path, exit_path)
    if exit_code == 0:
        return True, None
    detail = (output or "")[-1000:]
    return False, detail or f"apt-get install failed (exit code {exit_code})"
