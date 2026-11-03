"""
wsl_command.py -- the Windows-to-WSL launch layer every Generation run goes through:
Windows-to-WSL path translation, per-run log/exit file allocation under .generation_logs/,
the `wsl.exe -e bash -c "... > log 2>&1; echo $? > exit"` wrapper with its environment
prefix, and the console-less Popen keyword arguments.

Every WSL-launching function takes an explicit `portal_folder` argument: the storage path
can change at runtime (prime_atlas_v2.py's _set_portal_folder rebinds its own module
global), so the caller passes the CURRENT value at each call site.
"""
import os
import re
import shlex
import subprocess
import time


_WINDOWS_DRIVE_PATH_RE = re.compile(r'^([A-Za-z]):[\\/](.*)$')


def windows_path_to_wsl(path):
    """Translates a native Windows absolute path (e.g. "D:\\storage\\...") to its WSL
    mount-point equivalent ("/mnt/d/storage/...") -- the same mapping orchestrator_v3.py's/
    prime_sieve_v3.py's own __main__ blocks hardcode for BASE_STORAGE_10PN. A path with no
    drive-letter prefix is returned with backslashes flipped to forward slashes, unchanged
    otherwise (so already-WSL-style input passes through as-is)."""
    m = _WINDOWS_DRIVE_PATH_RE.match(path)
    if not m:
        return path.replace("\\", "/")
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


GENERATION_LOGS_DIRNAME = ".generation_logs"


def generation_log_paths(portal_folder, prefix):
    """Allocates a fresh (windows_log_path, windows_exit_path, run_id) triple under
    CONSTELLATION_PORTAL/.generation_logs/ for one subprocess run. Both paths sit on the
    same Windows drive WSL already sees under its own /mnt/ mount point -- the Linux-side redirect (see
    build_wsl_logged_command()) and this app's own file-tailing (see WslLoggedRunner) are
    reading/writing the exact same physical file, so no WSL<->Windows translation is ever
    needed on the READ side, only when building the bash command itself."""
    logs_dir = os.path.join(portal_folder, GENERATION_LOGS_DIRNAME)
    os.makedirs(logs_dir, exist_ok=True)
    run_id = f"{prefix}_{int(time.time() * 1000)}_{os.getpid()}"
    return (os.path.join(logs_dir, f"{run_id}.log"),
            os.path.join(logs_dir, f"{run_id}.exit"),
            run_id)


_ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


def build_wsl_logged_command(argv, windows_log_path, windows_exit_path, portal_folder,
                              use_known_pi_seed=False, extra_env=()):
    """Wraps a Linux-side argv (e.g. ["python3", "/mnt/d/.../script.py", "20", ...]) in a
    `wsl.exe -e bash -c "..."` invocation that redirects combined stdout+stderr into
    windows_log_path (translated to its WSL mount path) and writes the process's exit
    code into windows_exit_path afterward -- see WslLoggedRunner's docstring for why
    file redirection is used rather than a subprocess.PIPE on wsl.exe's own stdout.
    Every token is individually shell-quoted (shlex.quote) so the space
    in "Prime numbers storage" (and anything else) survives bash -c's re-parsing --
    the exec-mode `wsl.exe -e <argv>` form used elsewhere in this app deliberately avoids
    a shell entirely for that reason, but the `>`/`;` here are shell syntax and need one. `portal_folder` is the CURRENT storage
    path, passed explicitly by the caller (see this module's docstring for why).

    use_known_pi_seed (default False): sets
    PRIMEATLAS_USE_KNOWN_PI_SEED=1 alongside CONSTELLATION_PORTAL_DIR below, using the exact
    same env-prefix mechanism -- see prime_sieve_v4_1.py's own __main__ block (where it's
    read) and count_sieving_primes_cached()'s docstring for what it does. Every call site
    launches a DIFFERENT script (orchestrator_loop_v2.py, orchestrator_v3.py directly,
    prime_sieve_primesieve.py, ktuple_sieve_v2.py, constellation_finder_v2_1.py) and only the
    first two ever read this var -- the others simply ignore an env var they don't check, so
    it's harmless to leave at its False default for every call site that doesn't pass it
    explicitly (only the Generation tab's classic-engine Pipeline/Loop launches do).

    extra_env: (name, value) pairs set the same way, after the two above -- the sieve
    engine choice and v5 knobs (engine_options.launch_env()). Values are shell-quoted;
    a name that is not an upper-case identifier raises ValueError."""
    log_wsl = windows_path_to_wsl(windows_log_path)
    exit_wsl = windows_path_to_wsl(windows_exit_path)
    inner = " ".join(shlex.quote(str(t)) for t in argv)
    # CONSTELLATION_PORTAL_DIR, set via prime_atlas_v2.py's Settings tab: a plain
    # os.environ[...] set in THIS (Windows) process does NOT automatically cross into
    # wsl.exe's Linux environment (that needs WSLENV, which this app doesn't otherwise use)
    # -- so the override is prepended directly to the bash -c command line instead, the one
    # mechanism guaranteed to work regardless of WSLENV configuration. This makes every WSL
    # launch through this function (i.e. every Generation-tab run) automatically honor
    # whatever storage path is currently configured, with no per-call-site changes needed.
    portal_wsl = windows_path_to_wsl(portal_folder)
    env_prefix = f"CONSTELLATION_PORTAL_DIR={shlex.quote(portal_wsl)} "
    if use_known_pi_seed:
        env_prefix += "PRIMEATLAS_USE_KNOWN_PI_SEED=1 "
    for name, value in extra_env:
        if not _ENV_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid environment variable name: {name!r}")
        env_prefix += f"{name}={shlex.quote(str(value))} "
    bash_cmd = (f"{env_prefix}{inner} > {shlex.quote(log_wsl)} 2>&1; "
                f"echo $? > {shlex.quote(exit_wsl)}")
    return ["wsl.exe", "-e", "bash", "-c", bash_cmd]


def _popen_kwargs_no_window():
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs
