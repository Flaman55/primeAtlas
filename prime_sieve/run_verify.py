"""run_verify.py -- the verification P -> D that follows a pt1 run (orchestrator_v3.py).

With PRIMEATLAS_PT1_VERIFY=1 the orchestrator, once a pt1 run that writes its windows has
finished, proves the P windows of that run's target_idx range with one of the two store
verifiers: the pt1.1 proof (pt1_verify_store.py) or the v7.3 sieve (v73_verify_store.py, in
passes of PRIMEATLAS_VERIFY_PASS_NUMBERS numbers). The method and the pass width are the
Generation tab's Section D fields, so one choice serves both that section and the pipeline.
The verification runs after the whole run, not per slab: the v7.3 sieve costs a near fixed
time per pass, so it pays off on one wide pass over the run's windows.

Environment: PRIMEATLAS_PT1_VERIFY (0 or 1), PRIMEATLAS_VERIFY_METHOD (proof or sieve,
default proof), PRIMEATLAS_VERIFY_PASS_NUMBERS (default DEFAULT_PASS_NUMBERS).
Standard library only: the native Windows GUI imports the method names.
"""
import os

VERIFY_ENV = "PRIMEATLAS_PT1_VERIFY"
METHOD_ENV = "PRIMEATLAS_VERIFY_METHOD"
PASS_NUMBERS_ENV = "PRIMEATLAS_VERIFY_PASS_NUMBERS"
METHOD_PROOF = "proof"
METHOD_SIEVE = "sieve"
METHODS = (METHOD_PROOF, METHOD_SIEVE)
SCRIPTS = {METHOD_PROOF: "pt1_verify_store.py", METHOD_SIEVE: "v73_verify_store.py"}
# Numbers per v7.3 pass: 10^11 takes a ~3.3 GB buffer (arbitrary, sized for a 32 GB machine).
DEFAULT_PASS_NUMBERS = 10 ** 11
RANGE_FLAG = "--range"


def verify_from_env(environ):
    """True when `environ` (a mapping) sets VERIFY_ENV to 1; False when it is unset, blank or
    0. Raises ValueError for any other value."""
    raw = str(environ.get(VERIFY_ENV) or "").strip()
    if raw in ("", "0"):
        return False
    if raw == "1":
        return True
    raise ValueError(f"{VERIFY_ENV} must be 0 or 1, got {raw!r}")


def from_env(environ):
    """(method, pass_numbers) when VERIFY_ENV is 1, else None. Raises ValueError for a
    value outside the accepted ones."""
    if not verify_from_env(environ):
        return None
    method = str(environ.get(METHOD_ENV) or "").strip() or METHOD_PROOF
    if method not in METHODS:
        raise ValueError(f"{METHOD_ENV} must be one of {', '.join(METHODS)}, got {method!r}")
    raw = str(environ.get(PASS_NUMBERS_ENV) or "").strip()
    if not raw:
        return method, DEFAULT_PASS_NUMBERS
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError(f"{PASS_NUMBERS_ENV} must be a whole number >= 1, got {raw!r}")
    return method, int(raw)


def verifier_argv(method, base_exponent, threads, window_m, start_idx, stop_idx,
                  pass_numbers, script_dir):
    """The store verifier's arguments (after the interpreter) for the windows
    start_idx..stop_idx of the floor."""
    argv = [os.path.join(script_dir, SCRIPTS[method]), str(base_exponent), str(threads),
            str(window_m), "0"]
    if method == METHOD_SIEVE:
        argv.append(str(pass_numbers))
    return argv + [RANGE_FLAG, str(start_idx), str(stop_idx)]


def pop_range(argv):
    """(argv without RANGE_FLAG and its two values, start_idx, stop_idx); (argv, 0, None)
    without the flag."""
    if RANGE_FLAG not in argv:
        return list(argv), 0, None
    at = argv.index(RANGE_FLAG)
    return argv[:at] + argv[at + 3:], int(argv[at + 1]), int(argv[at + 2])
