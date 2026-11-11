"""
engine_argv.py -- the script paths and Linux-side argv builders for every engine and tool
the app launches in WSL (orchestrator_loop_v2.py, orchestrator_v3.py direct,
prime_sieve_primesieve.py, primesieve_native.py, pseudosquares_native.py,
pseudosquares_install.py, hybrid_sieve.py, prime_sieve_cudasieve.py,
constellation_finder_v2_3.py, ktuple_sieve_v2_2.py, primecount_query.py), the Windows-side
read of a constellation checkpoint, and the local pip-install argv. The builders return
plain argv lists; wsl_command.build_wsl_logged_command() wraps them for wsl.exe.
"""
import os
import sys

from .wsl_command import windows_path_to_wsl

# Repo root (where prime_sieve/ and constellation/ live): three levels up from
# primeatlas/generation/.
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ORCHESTRATOR_LOOP_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "orchestrator_loop_v2.py"))
ORCHESTRATOR_DIRECT_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "orchestrator_v3.py"))
CONSTELLATION_FINDER_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "constellation", "constellation_finder_v2_3.py"))
KTUPLE_SIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "constellation", "ktuple_sieve_v2_2.py"))


PRIMESIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "prime_sieve_primesieve.py"))
PRIMESIEVE_NATIVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "primesieve_native.py"))
PSEUDOSQUARES_NATIVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "pseudosquares_native.py"))
PSEUDOSQUARES_INSTALL_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "pseudosquares_install.py"))
HYBRID_SIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "hybrid_sieve.py"))
PRIMESIEVE_QUERY_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "primesieve_query.py"))
PRIMECOUNT_QUERY_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "primecount_query.py"))
ENV_VERSIONS_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "env_versions.py"))
PT1_VERIFY_STORE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "pt1_verify_store.py"))
V73_VERIFY_STORE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "v73_verify_store.py"))


# ------------------------------------------------------------------------------------------
# CUDASieve (optional GPU engine) -- argv builders + blocking WSL status/install calls.
# See prime_sieve/prime_sieve_cudasieve.py's own module header for what --status/
# --fetch-license/--build each do and why the install consent-gate is split across two of
# them; this is only the "how do I invoke it from Windows via wsl.exe" layer, same division
# of responsibility every other build_*_argv() in this module already follows.
# ------------------------------------------------------------------------------------------

CUDASIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "prime_sieve_cudasieve.py"))


def build_env_versions_argv():
    """LINUX-side argv for env_versions.py, the Settings -> WSL environment component
    versions probe."""
    return ["python3", windows_path_to_wsl(ENV_VERSIONS_SCRIPT)]


def build_cudasieve_status_argv():
    """`python3 prime_sieve_cudasieve.py --status` -- see that function's own docstring
    for the JSON shape returned."""
    return ["python3", windows_path_to_wsl(CUDASIEVE_SCRIPT), "--status"]


def build_cudasieve_fetch_license_argv():
    """`python3 prime_sieve_cudasieve.py --fetch-license` -- clones/updates CUDASieve and
    returns its OWN current License file text as JSON; see cmd_fetch_license()'s own
    docstring for why this (not a copy embedded in this project) is what the consent
    dialog shows."""
    return ["python3", windows_path_to_wsl(CUDASIEVE_SCRIPT), "--fetch-license"]


def build_cudasieve_build_argv():
    """`python3 -u prime_sieve_cudasieve.py --build` -- runs `make` in the already-cloned
    install dir (see cmd_build()'s own docstring); -u (unbuffered) for the same reason
    build_constellation_finder_argv() uses it -- this is a long-running job whose progress
    lines should reach WslLoggedRunner's log file as they're printed, not only at exit."""
    return ["python3", "-u", windows_path_to_wsl(CUDASIEVE_SCRIPT), "--build"]


def build_primecount_query_argv(op, *args, script_path=None):
    """Returns the LINUX-side argv for primecount_query.py -- mirrors
    primesieve_calc_tab.py's build_primesieve_query_argv() (see that function's own
    docstring), just pointed at a different script and a different op set
    ("pi"/"pi_batch"/"nth"/"version", see primecount_query.py's own module header)."""
    script = script_path if script_path is not None else PRIMECOUNT_QUERY_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return ["python3", "-u", script_wsl, op] + [str(a) for a in args]


def build_loop_argv(base_exponent, run_count, n_instances, write_files,
                     compute_sieving_primes_count, window_count_per_run,
                     workers, batches_per_worker, window_m, script_path=None):
    """Returns the LINUX-side argv (["python3", "-u", script, args...]) for running
    orchestrator_loop_v2.py -- NOT yet wrapped in a wsl.exe invocation (see
    build_wsl_logged_command() for that). Argument order matches that script's __main__
    CLI EXACTLY (see its module-header "Usage (WSL)" comment): <base_exponent> <run_count>
    <n_instances> <write_files 0/1> <compute_sieving_primes_count 0/1>
    <window_count_per_run> <workers> <batches_per_worker> <window_m> -- ALL 9 positions are
    always passed explicitly, never conditionally omitted, so a value the GUI form shows can
    never silently fall back to that script's own hardcoded default instead (same
    discipline build_instance_cmd() in orchestrator_loop_v2.py itself follows -- see that
    function's docstring).

    window_m: how many numbers each "window" (target_idx step) covers -- a real
    CLI-overridable parameter, same as workers/batches_per_worker, rather than the
    10,000,000 hardcoded in prime_sieve_v3.py/orchestrator_v3.py/
    orchestrator_loop_helpers.py. NOTE (surfaced in the GUI field's own label/tooltip too,
    not just here): changing this for a floor that ALREADY has PRIME_WINDOW_*.bin files
    written with a DIFFERENT window_m breaks auto-resume (the next run would compute a
    wrong/misaligned starting target_idx) -- only safe to change for a floor with no
    existing data yet.

    The `-u` flag forces Python's stdout/stderr to be
    UNBUFFERED instead of the fully-buffered mode it defaults to whenever stdout isn't a
    terminal (exactly the case here -- see build_wsl_logged_command()'s `> logfile`
    redirect). Without it, print() output sits in an in-process buffer and isn't actually
    written to the log file until that buffer fills (several KB) or the process exits --
    for a script whose print volume is low relative to its runtime (constellation_finder_
    v1.py's per-window progress lines, especially early in a long first-time run against a
    heavily-populated floor), that can mean WslLoggedRunner's live tail shows NOTHING for
    a very long time even though the process is working correctly and already writing real
    results to disk incrementally -- indistinguishable from a genuine hang from the GUI's
    point of view."""
    script = script_path if script_path is not None else ORCHESTRATOR_LOOP_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(run_count), str(n_instances),
        "1" if write_files else "0",
        "1" if compute_sieving_primes_count else "0",
        str(window_count_per_run), str(workers), str(batches_per_worker), str(window_m),
    ]


def build_primesieve_argv(base_exponent, target_idx_start, window_count_per_run, window_m,
                           write_files, script_path=None):
    """Returns the LINUX-side argv for prime_sieve_primesieve.py -- the 'primesieve mode'
    engine (see that file's module header for what makes it different from every other
    engine this app can launch: it calls libprimesieve's own primesieve_generate_primes()
    directly, no batching/orchestrator of ours involved at all). Argument order matches
    that script's __main__ CLI exactly: <base_exponent> <target_idx_start>
    <target_idx_count> <window_m> <write_files 0/1> -- deliberately simpler than
    build_loop_argv()'s 9 positions, since workers/batches_per_worker/
    compute_sieving_primes_count have no meaning for this engine.

    Unlike orchestrator_loop_v2.py (which auto-detects its own resume point via
    find_auto_start()), this script takes target_idx_start explicitly -- the GUI already
    computes it via find_continuation_target_idx() while planning the request (see
    _quick_gen_plan_literal_range()), so there's no reason for this simpler script to
    duplicate that disk-scanning logic itself."""
    script = script_path if script_path is not None else PRIMESIEVE_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(target_idx_start), str(window_count_per_run), str(window_m),
        "1" if write_files else "0",
    ]


def build_primesieve_native_argv(base_exponent, target_idx_start, window_count_per_run,
                                  window_m, mode, script_path=None):
    """Linux argv of primesieve_native.py (the primesieve program itself, mode "print" or
    "count"): <base_exponent> <target_idx_start> <target_idx_count> <window_m> <mode>."""
    script = script_path if script_path is not None else PRIMESIEVE_NATIVE_SCRIPT
    return ["python3", "-u", windows_path_to_wsl(script), str(base_exponent),
            str(target_idx_start), str(window_count_per_run), str(window_m), mode]


def build_pseudosquares_native_argv(base_exponent, target_idx_start, window_count_per_run,
                                    window_m, mode, threads, script_path=None):
    """Linux argv of pseudosquares_native.py (the Pseudosquares Prime Sieve program, mode
    "print" or "count"): <base_exponent> <target_idx_start> <target_idx_count> <window_m>
    <mode> <threads, 0 = the program's own choice>."""
    script = script_path if script_path is not None else PSEUDOSQUARES_NATIVE_SCRIPT
    return ["python3", "-u", windows_path_to_wsl(script), str(base_exponent),
            str(target_idx_start), str(window_count_per_run), str(window_m), mode,
            str(threads)]


def build_pseudosquares_install_argv(command, script_path=None):
    """Linux argv of pseudosquares_install.py: command "--status" (one JSON line) or
    "--build" (clone/check out the pinned commit and build it, live text)."""
    script = script_path if script_path is not None else PSEUDOSQUARES_INSTALL_SCRIPT
    return ["python3", "-u", windows_path_to_wsl(script), command]


def build_hybrid_argv(base_exponent, iterations, width_windows, filter_prime_count, write_files,
                      script_path=None):
    """Return the WSL argv for the ``hybrid_sieve.py`` extension runner.

    This deliberately has a compact, hybrid-specific contract rather than borrowing
    ``build_loop_argv()``'s window-count semantics.  A hybrid stage's reach is
    determined by the visible ``filter_prime_count`` (``k_adv``), not by a fixed
    numeric-width multiplier: the runner derives its exact extension bound only after
    it has built that filter-prime prefix.  The base floor selects the existing,
    continuous storage that supplies MAIN; ``iterations`` requests successive hybrid
    extensions of that base.

    CLI order:
    ``<base_exponent> <iterations> <width_windows> <filter_prime_count> <write_files 0/1>``.
    """
    script = script_path if script_path is not None else HYBRID_SIEVE_SCRIPT
    return [
        "python3", "-u", windows_path_to_wsl(script),
        str(base_exponent), str(iterations), str(width_windows), str(filter_prime_count),
        "1" if write_files else "0",
    ]


def build_hybrid_narrow_argv(start, end, main_cap, filter_prime_count, write_files,
                             script_path=None):
    """Build the one-standard-window experimental Hybrid invocation."""
    script = script_path if script_path is not None else HYBRID_SIEVE_SCRIPT
    return [
        "python3", "-u", windows_path_to_wsl(script), "narrow",
        str(start), str(end), str(main_cap), str(filter_prime_count),
        "1" if write_files else "0",
    ]


def build_cudasieve_argv(base_exponent, target_idx_start, window_count_per_run, window_m,
                          write_files, script_path=None):
    """Returns the LINUX-side argv for prime_sieve_cudasieve.py -- the GPU 'cudasieve mode'
    engine. Argument order matches that script's __main__ CLI exactly, and is deliberately
    identical in shape to build_primesieve_argv()'s: <base_exponent> <target_idx_start>
    <target_idx_count> <window_m> <write_files 0/1> -- both engines skip the batching/
    orchestrator machinery entirely, so neither has a workers/batches_per_worker/
    compute_sieving_primes_count concept to pass through."""
    script = script_path if script_path is not None else CUDASIEVE_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(target_idx_start), str(window_count_per_run), str(window_m),
        "1" if write_files else "0",
    ]


def build_orchestrator_direct_argv(base_exponent, target_idx_start, window_count_per_run,
                                    window_m, write_files, compute_sieving_primes_count,
                                    workers, batches_per_worker, script_path=None):
    """Returns the LINUX-side argv for launching orchestrator_v3.py DIRECTLY -- bypassing
    orchestrator_loop_v2.py's own wrapper CLI (build_loop_argv()), which only ever
    auto-continues from wherever a floor's storage currently ends (see that function's own
    docstring) and has no way to target an arbitrary target_idx.

    This is the fallback engine for _offer_generate_missing_prime_window() when the
    requested window falls beyond libprimesieve's own uint64 ceiling (PRIMESIEVE_MAX_STOP)
    -- primesieve mode (build_primesieve_argv(), this app's usual single-arbitrary-window
    engine for that call site) simply cannot reach floors that high (e.g. 10^30 is roughly
    eleven orders of magnitude past 2**64-1). orchestrator_v3.py has no such ceiling and,
    unlike its own loop wrapper, DOES accept an explicit start_window on its own __main__
    CLI (see that script's argument parsing) -- so calling it directly, with start_auto
    forced off, gets the exact same 'write just the one window asked for, gaps before it
    and all' behavior primesieve mode provides at the low end, just through the slower
    engine at any magnitude. Argument order matches orchestrator_v3.py's own CLI exactly:
    <base_exponent> <window_count> <start_auto 0/1> <start_window> <write_files 0/1>
    <compute_sieving_primes_count 0/1> <workers> <batches_per_worker> <window_m>."""
    script = script_path if script_path is not None else ORCHESTRATOR_DIRECT_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(window_count_per_run),
        "0", str(target_idx_start),
        "1" if write_files else "0",
        "1" if compute_sieving_primes_count else "0",
        str(workers), str(batches_per_worker), str(window_m),
    ]



def build_constellation_finder_argv(base_exponent=None, max_windows=None, script_path=None):
    """Returns the LINUX-side argv for constellation_finder_v2_3.py, whose CLI is
    `[<base_exponent>] [--max-windows N]` -- base_exponent is a single OPTIONAL
    positional arg, omitted entirely (not passed as an empty string) when it's
    None/blank, matching that script's own auto-detect-every-populated-floor behavior
    (list_floors_with_data()) when it's called with no argument at all. Not yet wrapped
    in a wsl.exe invocation -- see build_wsl_logged_command(). Uses `-u` (unbuffered
    stdout) for the same reason build_loop_argv() does (see its docstring); with this
    script's low per-window print volume, full buffering would hold output back for long.

    max_windows (see constellation_finder_v2_3.process_floor() for why a run is capped):
    omitted
    entirely when None, same "don't pass what wasn't explicitly set" shape as
    base_exponent -- callers use this to bound a single run's own file-open volume,
    letting constellation_section.py's own batch-continuation logic relaunch a fresh WSL
    process for each slice instead of one process carrying the whole floor."""
    script = script_path if script_path is not None else CONSTELLATION_FINDER_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    argv = ["python3", "-u", script_wsl]
    if base_exponent not in (None, ""):
        argv.append(str(base_exponent))
    if max_windows is not None:
        argv += ["--max-windows", str(max_windows)]
    return argv


def read_constellation_checkpoint(portal_folder, base_exponent):
    """Windows-side read of a floor's own CHECKPOINT.txt (last fully-processed PGS2
    source window -- constellation_progress_v2_3.py's write_done_ranges() still writes
    this same "last_processed_file=" line alongside its own done_range= ones, see that
    function's docstring) -- same parsing as that script's own read_checkpoint(), kept
    as a small separate copy here rather than imported cross-language: this runs from
    the GUI's own Windows-side process (generation_tab.py), never inside WSL, and the
    constellation_*_v2_3 modules need prime_sieve/ on sys.path and the engine's own
    numpy/pattern-catalog imports -- reading three lines of a text file needs neither. Returns None if the floor has no checkpoint
    yet (never scanned, or scanned floor doesn't exist).

    Used by the auto-retry logic in constellation_section.py's own
    _maybe_auto_retry_constellation() -- comparing this before/after a relaunch is how
    that method tells "genuine forward progress" apart from "relaunching into the same
    dead end"."""
    path = os.path.join(portal_folder, f"10p{base_exponent}", "constellations", "CHECKPOINT.txt")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("last_processed_file="):
                return line.split("=", 1)[1].strip()
    return None


def build_ktuple_sieve_argv(base_exponent, k, variant_id, n_locations=1000, window_m=10_000_000,
                             strategy="concentrated", step=None, fragment_width=None,
                             fragment_start=None, manual_offsets=None, deep_prime_limit=2000,
                             mr_rounds=40, auto=False, reset_checkpoint=False, pass_counter=None,
                             script_path=None):
    """Returns the LINUX-side argv for ktuple_sieve_v2_2.py -- see that script's own
    argparse block for the exact CLI shape (three required positionals: base_exponent,
    k, variant_id; the rest are optional flags with the same defaults this function
    uses). `-u` for the same unbuffered-stdout reason build_constellation_finder_argv()
    uses -- this script's per-location print volume is lower still (each location does
    real work: wheel-stride + trial-division + Miller-Rabin, not just a window read), so
    buffering would hide live progress even more than that script's own case did.

    Unlike build_constellation_finder_argv(), base_exponent/k/variant_id are all
    REQUIRED here (ktuple_sieve_v2_2.py has no auto-detect-every-floor mode -- a k-tuple
    hunt is always FOR one specific pattern, at a caller-chosen floor, never implicit).

    `strategy` -- one of "even", "concentrated", "manual_list", "manual_step",
    "digit_sweep" (see ktuple_sieve_v2_2.py's own module docstring for what each means;
    all but manual_list share a checkpoint-driven continuation mechanism, manual_list
    is a one-shot with no checkpoint). `step`/`fragment_start` are left OUT of argv
    entirely when None -- ktuple_sieve_v2_2.py's own CLI defaults (auto-computed step per
    strategy, fragment_start=0) then apply, same "don't pass what wasn't explicitly
    set" shape as `fragment_width`/`manual_offsets`/`pass_counter` already had.
    `pass_counter` only matters for strategy=digit_sweep (default 0 on the script side
    when omitted, and only used the first time -- once a checkpoint exists the script's
    own next_offset field takes over and this starting value is ignored). `auto`/
    `reset_checkpoint` are plain boolean flags (only appended when True -- argparse's
    own store_true default is already False)."""
    script = script_path if script_path is not None else KTUPLE_SIEVE_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    argv = ["python3", "-u", script_wsl, str(base_exponent), str(k), str(variant_id),
            "--n-locations", str(n_locations), "--window-m", str(window_m),
            "--strategy", strategy,
            "--deep-prime-limit", str(deep_prime_limit), "--mr-rounds", str(mr_rounds)]
    if step is not None:
        argv += ["--step", str(step)]
    if fragment_width is not None:
        argv += ["--fragment-width", str(fragment_width)]
    if fragment_start is not None:
        argv += ["--fragment-start", str(fragment_start)]
    if manual_offsets:
        argv += ["--manual-offsets"] + [str(o) for o in manual_offsets]
    if pass_counter is not None:
        argv += ["--pass-counter", str(pass_counter)]
    if auto:
        argv.append("--auto")
    if reset_checkpoint:
        argv.append("--reset-checkpoint")
    return argv


def build_pt1_verify_argv(base_exponent, threads, window_m, max_windows=0, script_path=None):
    """The LINUX-side argv of pt1_verify_store.py (its module docstring has the CLI):
    proves the floor's P windows, the first max_windows of them (0 = all)."""
    script = script_path if script_path is not None else PT1_VERIFY_STORE_SCRIPT
    return ["python3", "-u", windows_path_to_wsl(script), str(base_exponent), str(threads),
            str(window_m), str(max_windows)]


def build_v73_verify_argv(base_exponent, threads, window_m, max_windows, pass_numbers,
                          script_path=None):
    """The LINUX-side argv of v73_verify_store.py (its module docstring has the CLI): proves
    the floor's P windows by v7.2 sieve passes of up to pass_numbers numbers, the first
    max_windows of them (0 = all)."""
    script = script_path if script_path is not None else V73_VERIFY_STORE_SCRIPT
    return ["python3", "-u", windows_path_to_wsl(script), str(base_exponent), str(threads),
            str(window_m), str(max_windows), str(pass_numbers)]


def build_pip_install_argv(package, upgrade=False):
    """[sys.executable, -m, pip, install, package] -- installs into the SAME
    Python environment this GUI process itself runs under (sys.executable, not a bare
    "python"/"python3" on PATH, which could resolve to a different interpreter). No
    --user: pip falls back to a user install by itself when site-packages isn't writable
    (so still no admin rights needed), while the Windows installer's private Python keeps
    its packages in its own site-packages -- same reasoning as
    startup_dependency_check.build_pip_argv(). Used by the Settings tab's
    optional-library installer -- currently only sympy (see
    primeatlas/primality/primality.py's try_import_sympy()), kept general in case a future
    optional dependency needs the same treatment."""
    # --no-warn-script-location: pip's "is the Scripts folder on PATH?" warning calls
    # Path.resolve() on every PATH entry, and a PATH entry that is a redirection
    # (reparse) point can make Windows raise WinError 448 and pip abort the install.
    argv = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
            "--no-warn-script-location"]
    if upgrade:
        argv.append("--upgrade")
    argv.append(package)
    return argv
