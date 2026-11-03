"""
test_app_update_locks.py -- primeatlas/settings/app_update.py's git plumbing below the
update check itself:

  C. Lock-recovery mechanics -- _looks_like_lock_error() classification,
     _try_release_lock_file() against real temp files (including the OS-verified "still in
     use" case), _release_all_locks(), and _run_git_with_lock_recovery()'s full
     retry/backoff schedule (passive-phase resolution, active-release resolution, and
     budget exhaustion), all with _sleep() mocked out so this runs in well under a second.
  D. git executable resolution -- the installer's private MinGit under <install>/git,
     which is not on PATH.

No real git repo or network: every subprocess boundary is stubbed by monkeypatching the
module's own helpers. The update check and download are in test_app_update.py.

Usage: python unitTests\\test_app_update_locks.py
"""
import os
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))  # primeatlas/__init__.py pulls
                                                               # in manifest.py -> window_sharding
                                                               # at import time, same PYTHONPATH
                                                               # need test_env_setup.py already
                                                               # documented

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


# ============================================================================================
# Section C -- lock-recovery mechanics
# ============================================================================================

def section_c():
    print("\n--- Section C: lock-recovery mechanics ---")
    from primeatlas.settings import app_update as au

    # --- _looks_like_lock_error() classification ---
    lock_texts = [
        "fatal: Unable to create '.git/index.lock': File exists.",
        "error: cannot lock ref 'refs/remotes/origin/main': Unable to create...",
        "warning: unable to unlink '.git/ORIG_HEAD.lock': Operation not permitted",
        "Another git process seems to be running in this repository",
    ]
    for text in lock_texts:
        check(au._looks_like_lock_error(text), f"must classify as a lock error: {text!r}")

    non_lock_texts = [
        "fatal: Not possible to fast-forward, aborting.",
        "fatal: unable to access 'origin': network unreachable",
        "fatal: not a git repository (or any of the parent directories): .git",
        "",
        None,
    ]
    for text in non_lock_texts:
        check(not au._looks_like_lock_error(text),
              f"must NOT classify as a lock error: {text!r}")
    check(not au._looks_like_lock_error("fatal: Not possible to fast-forward, aborting."),
          "the real divergence message must never be mistaken for a lock error -- this is "
          "an actual message observed on real hardware, and misclassifying it would "
          "make download_update() retry a genuine divergence instead of reporting it")

    # --- _try_release_lock_file() against a real temp file ---
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = os.path.join(tmp, "index.lock")
        with open(lock_path, "w"):
            pass
        result = au._try_release_lock_file(lock_path)
        check(result is True, "releasing a real, unheld lock file must succeed")
        check(not os.path.exists(lock_path),
              "the original lock path must be gone after a successful release")
        renamed = [f for f in os.listdir(tmp) if f.startswith("index.lock.stale_")]
        check(len(renamed) == 1,
              f"the lock must be renamed aside (never deleted), got {os.listdir(tmp)!r}")

        # already-gone lock -- must report success (someone else cleaned it up)
        check(au._try_release_lock_file(os.path.join(tmp, "already_gone.lock")) is True,
              "releasing an already-nonexistent lock file must report success")

        # simulate the OS refusing the rename (a real, live process still has it open) --
        # this is the exact case that must NEVER be forced further
        still_locked_path = os.path.join(tmp, "still_locked.lock")
        with open(still_locked_path, "w"):
            pass
        orig_rename = os.rename

        def deny_rename(src, dst):
            raise PermissionError("simulated: file still in use by another process")

        os.rename = deny_rename
        try:
            result = au._try_release_lock_file(still_locked_path)
        finally:
            os.rename = orig_rename
        check(result is False,
              "a rename refused by the OS must report False, never be forced through")
        check(os.path.exists(still_locked_path),
              "a lock the OS refuses to release must be left completely untouched")

    # --- _release_all_locks() ---
    with tempfile.TemporaryDirectory() as tmp:
        git_dir = os.path.join(tmp, ".git")
        os.makedirs(os.path.join(git_dir, "refs", "remotes", "origin"))
        for name in ("index.lock", "ORIG_HEAD.lock"):
            with open(os.path.join(git_dir, name), "w"):
                pass
        with open(os.path.join(git_dir, "refs", "remotes", "origin", "main.lock"), "w"):
            pass

        orig_git_lock_dirs = au._git_lock_dirs
        au._git_lock_dirs = lambda repo_dir: {git_dir}
        try:
            result = au._release_all_locks(tmp)
        finally:
            au._git_lock_dirs = orig_git_lock_dirs
        check(result is True,
              "releasing a full set of genuinely-unheld locks (including one nested under "
              "refs/) must report True")
        check(len(au._find_lock_files(git_dir)) == 0,
              "no *.lock files (renamed or original) should remain findable after a "
              "successful full release")

        # one of several locks refuses to release -- must still attempt the others, and
        # must report False overall
        with open(os.path.join(git_dir, "index.lock"), "w"):
            pass
        with open(os.path.join(git_dir, "ORIG_HEAD.lock"), "w"):
            pass
        orig_try_release = au._try_release_lock_file
        attempted = []

        def picky_release(path):
            attempted.append(path)
            return "ORIG_HEAD" not in path  # index.lock releases fine, ORIG_HEAD does not

        au._try_release_lock_file = picky_release
        au._git_lock_dirs = lambda repo_dir: {git_dir}
        try:
            result = au._release_all_locks(tmp)
        finally:
            au._try_release_lock_file = orig_try_release
            au._git_lock_dirs = orig_git_lock_dirs
        check(result is False,
              "if even one lock refuses to release, _release_all_locks must report False")
        check(len(attempted) == 2,
              f"both locks must have been attempted, not short-circuited after the first "
              f"failure (got {attempted!r})")

    # --- _run_git_with_lock_recovery() retry/backoff schedule, fully mocked ---
    # NOTE: _sleep stays mocked for this whole subsection (restore_step() below only
    # resets _run_git/_release_all_locks between cases) -- resetting it after every case
    # like the sections above do would silently fall back to the REAL time.sleep for every
    # case after the first, since nothing re-arms it before the next call. That would still
    # look like it "worked" (the retries would just really wait a few seconds instead of
    # being instant) while quietly recording nothing into `sleeps`, which is exactly the
    # bug this comment is here to prevent reintroducing.
    orig_run_git = au._run_git
    orig_sleep = au._sleep
    orig_release = au._release_all_locks

    def restore_step():
        au._run_git = orig_run_git
        au._release_all_locks = orig_release

    def restore_all():
        restore_step()
        au._sleep = orig_sleep

    sleeps = []
    au._sleep = lambda seconds: sleeps.append(seconds)

    try:
        # immediate success -- no retries, no sleeps at all
        sleeps.clear()
        calls = {"n": 0}
        def immediate_ok(args, cwd, timeout=30):
            calls["n"] += 1
            return 0, "ok", ""
        au._run_git = immediate_ok
        try:
            rc, out, err = au._run_git_with_lock_recovery(["status"], "/fake/repo")
        finally:
            restore_step()
        check(rc == 0 and calls["n"] == 1 and sleeps == [],
              f"an immediate success must call git exactly once and never sleep "
              f"(calls={calls['n']}, sleeps={sleeps!r})")

        # immediate non-lock failure -- no retries, no sleeps
        sleeps.clear()
        calls = {"n": 0}
        def immediate_fail(args, cwd, timeout=30):
            calls["n"] += 1
            return 1, "", "fatal: Not possible to fast-forward, aborting."
        au._run_git = immediate_fail
        try:
            rc, out, err = au._run_git_with_lock_recovery(["merge"], "/fake/repo")
        finally:
            restore_step()
        check(rc == 1 and calls["n"] == 1 and sleeps == [],
              f"a genuine (non-lock) failure must never trigger the retry schedule "
              f"(calls={calls['n']}, sleeps={sleeps!r})")

        # resolved during the passive phase (2nd retry succeeds)
        sleeps.clear()
        calls = {"n": 0}
        def resolves_passively(args, cwd, timeout=30):
            calls["n"] += 1
            if calls["n"] < 3:
                return 128, "", "fatal: Unable to create '.git/index.lock': File exists."
            return 0, "ok", ""
        au._run_git = resolves_passively
        try:
            rc, out, err = au._run_git_with_lock_recovery(["fetch"], "/fake/repo")
        finally:
            restore_step()
        check(rc == 0 and calls["n"] == 3,
              f"expected exactly 3 git calls (1 initial + 2 passive retries), got "
              f"{calls['n']}")
        check(sleeps == list(au._LOCK_PASSIVE_RETRY_DELAYS[:2]),
              f"expected exactly the first 2 passive delays to have been slept, got "
              f"{sleeps!r}")

        # passive phase exhausted, resolved by the very first release round
        sleeps.clear()
        calls = {"n": 0}
        release_calls = {"n": 0}
        passive_count = len(au._LOCK_PASSIVE_RETRY_DELAYS)

        def resolves_on_first_release(args, cwd, timeout=30):
            calls["n"] += 1
            if calls["n"] <= 1 + passive_count:
                return 128, "", "fatal: Unable to create '.git/index.lock': File exists."
            return 0, "ok", ""

        def release_always_succeeds(repo_dir):
            release_calls["n"] += 1
            return True

        au._run_git = resolves_on_first_release
        au._release_all_locks = release_always_succeeds
        try:
            rc, out, err = au._run_git_with_lock_recovery(["merge"], "/fake/repo")
        finally:
            restore_step()
        check(rc == 0,
              f"must eventually succeed once a release round frees the lock (rc={rc})")
        check(release_calls["n"] == 1,
              f"expected exactly 1 release attempt (the first round succeeds "
              f"immediately), got {release_calls['n']}")
        check(sleeps == list(au._LOCK_PASSIVE_RETRY_DELAYS),
              f"a successful release round must retry git immediately, without an extra "
              f"release-wait sleep (got sleeps={sleeps!r})")

        # lock never releases -- budget fully exhausted, real error still returned
        sleeps.clear()
        calls = {"n": 0}
        release_calls = {"n": 0}

        def never_resolves(args, cwd, timeout=30):
            calls["n"] += 1
            return 128, "", "fatal: Unable to create '.git/index.lock': File exists."

        def release_never_succeeds(repo_dir):
            release_calls["n"] += 1
            return False

        au._run_git = never_resolves
        au._release_all_locks = release_never_succeeds
        try:
            rc, out, err = au._run_git_with_lock_recovery(["merge"], "/fake/repo")
        finally:
            restore_step()
        check(rc == 128 and "index.lock" in err,
              f"once the whole recovery budget is exhausted, the real underlying git "
              f"error must still be returned -- never a generic/opaque failure "
              f"(got rc={rc}, err={err!r})")
        check(calls["n"] == 1 + passive_count,
              f"git itself must be retried only during the passive phase (a release that "
              f"never succeeds must not trigger further git calls) -- expected "
              f"{1 + passive_count}, got {calls['n']}")
        check(release_calls["n"] == au._LOCK_RELEASE_ROUNDS,
              f"every one of the {au._LOCK_RELEASE_ROUNDS} release rounds must have been "
              f"attempted before giving up, got {release_calls['n']}")
        expected_sleeps = list(au._LOCK_PASSIVE_RETRY_DELAYS) + (
            [au._LOCK_RELEASE_WAIT_SECONDS] * au._LOCK_RELEASE_ROUNDS)
        check(sleeps == expected_sleeps,
              f"expected the passive delays followed by one release-wait per failed round "
              f"(got {sleeps!r}, expected {expected_sleeps!r})")
    finally:
        restore_all()


# ============================================================================================
# Section D -- which git binary _run_git() launches
# ============================================================================================

def section_d():
    """The Windows installer (installer/PrimeAtlasSetup.iss) lays out <install>/app (this
    repo), <install>/python and <install>/git (portable MinGit, NOT on PATH). Self-update
    must find that private git, else it reports git-not-found on every installed machine."""
    print("\n--- Section D: git executable resolution ---")
    from primeatlas.settings import app_update as au

    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "app")
        os.makedirs(repo)
        bundled = os.path.join(root, "git", "cmd", "git.exe")

        check(au.git_executable(repo) == "git",
              "no bundled git next to the repo => plain 'git' from PATH (unchanged behavior)")

        os.makedirs(os.path.dirname(bundled))
        open(bundled, "w").close()
        check(au.git_executable(repo) == bundled,
              "bundled <install>/git/cmd/git.exe exists => it is used, even if PATH has another git")
        check(au.git_executable(repo + os.sep) == bundled,
              "a trailing separator on the repo dir does not break the lookup")

        seen = {}
        orig_run = au.subprocess.run

        class _Done:
            returncode, stdout, stderr = 0, "ok", ""

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return _Done()
        au.subprocess.run = fake_run
        try:
            rc, out, _ = au._run_git(["status"], cwd=repo)
        finally:
            au.subprocess.run = orig_run
        check(seen.get("argv") == [bundled, "status"] and rc == 0,
              f"_run_git launches the resolved git binary (got {seen.get('argv')!r})")

        def missing_run(argv, **kwargs):
            raise FileNotFoundError(argv[0])
        au.subprocess.run = missing_run
        try:
            result = au._run_git(["status"], cwd=os.path.join(root, "elsewhere"))
        finally:
            au.subprocess.run = orig_run
        check(result == (None, "", "git-not-found"),
              "no git anywhere still reports git-not-found, never raises")


# ============================================================================================

if __name__ == "__main__":
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
