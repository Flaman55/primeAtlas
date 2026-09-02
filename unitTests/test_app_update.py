"""
test_app_update.py -- covers primeatlas/app_update.py, the git-fetch/pull based self-update
checker/downloader wired into Settings > Aktualizacje and prime_atlas_v1.py's startup hook
(task #521).

No real git repo, network, or GitHub remote anywhere in this sandbox -- every subprocess
boundary is stubbed by monkeypatching the module's own _run_git(), same "thin, separately
named, mockable" split env_setup.py's _run_windows() uses (see test_env_setup.py's own
docstring for the precedent). Two sections:

  A. check_for_update() -- not-a-repo / fetch-fails / rev-parse-fails / up-to-date /
     N-commits-behind paths.
  B. download_update() -- status-check-fails / dirty-working-tree-refusal / pull-fails /
     pull-succeeds paths.

Usage:
    python3 unitTests/test_app_update.py
"""
import os
import sys

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
# Section A -- check_for_update()
# ============================================================================================

def section_a():
    print("\n--- Section A: check_for_update() ---")
    from primeatlas import app_update as au

    orig_run_git = au._run_git

    def restore():
        au._run_git = orig_run_git

    # --- repo_dir is not a git checkout at all ---
    au._run_git = lambda args, cwd, timeout=30: (
        (1, "", "fatal: not a git repository") if args[:2] == ["rev-parse", "--is-inside-work-tree"]
        else (_ for _ in ()).throw(AssertionError(f"must not go further, got {args!r}")))
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and result["update_available"] is False,
          f"a non-git repo_dir must report ok=False, update_available=False "
          f"(got {result!r})")
    check(result["error"] == "not a git checkout",
          f"the error must clearly say this isn't a git checkout (got {result!r})")

    # --- rev-parse ok, but `git fetch` fails (no network) ---
    au._run_git = lambda args, cwd, timeout=30: (
        (0, "true\n", "") if args[:2] == ["rev-parse", "--is-inside-work-tree"]
        else (1, "", "fatal: unable to access 'origin': network unreachable") if args[0] == "fetch"
        else (_ for _ in ()).throw(AssertionError(f"must not go further, got {args!r}")))
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "network unreachable" in result["error"],
          f"a failed fetch must surface git's own stderr as the error (got {result!r})")

    # --- fetch ok, but reading local HEAD fails (should not normally happen, defensive path) ---
    au._run_git = lambda args, cwd, timeout=30: (
        (0, "true\n", "") if args[:2] == ["rev-parse", "--is-inside-work-tree"]
        else (0, "", "") if args[0] == "fetch"
        else (1, "", "fatal: bad revision 'HEAD'") if args == ["rev-parse", "HEAD"]
        else (_ for _ in ()).throw(AssertionError(f"must not go further, got {args!r}")))
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "bad revision" in result["error"],
          f"a failed local HEAD read must surface as an error (got {result!r})")

    # --- up to date: local HEAD == origin/branch ---
    same_sha = "a" * 40
    au._run_git = lambda args, cwd, timeout=30: (
        (0, "true\n", "") if args[:2] == ["rev-parse", "--is-inside-work-tree"]
        else (0, "", "") if args[0] == "fetch"
        else (0, f"{same_sha}\n", "") if args == ["rev-parse", "HEAD"]
        else (0, f"{same_sha}\n", "") if args == ["rev-parse", "origin/main"]
        else (_ for _ in ()).throw(AssertionError(f"must not call rev-list when up to date, "
                                                    f"got {args!r}")))
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is True and result["update_available"] is False
          and result["commits_behind"] == 0,
          f"identical local/remote SHAs must report update_available=False without ever "
          f"calling rev-list (got {result!r})")
    check(result["local_commit"] == same_sha and result["remote_commit"] == same_sha,
          f"local_commit/remote_commit must be the (stripped) SHAs (got {result!r})")

    # --- N commits behind ---
    local_sha = "b" * 40
    remote_sha = "c" * 40
    au._run_git = lambda args, cwd, timeout=30: (
        (0, "true\n", "") if args[:2] == ["rev-parse", "--is-inside-work-tree"]
        else (0, "", "") if args[0] == "fetch"
        else (0, f"{local_sha}\n", "") if args == ["rev-parse", "HEAD"]
        else (0, f"{remote_sha}\n", "") if args == ["rev-parse", "origin/main"]
        else (0, "7\n", "") if args == ["rev-list", "--count", f"{local_sha}..{remote_sha}"]
        else (_ for _ in ()).throw(AssertionError(f"unexpected call, got {args!r}")))
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is True and result["update_available"] is True
          and result["commits_behind"] == 7,
          f"a diverged local/remote pair must report the real rev-list count "
          f"(got {result!r})")
    check(result["local_commit"] == local_sha and result["remote_commit"] == remote_sha,
          f"local/remote commit SHAs must be threaded through unchanged (got {result!r})")

    # --- N commits behind, but rev-list itself fails -- must not crash, falls back to 0 ---
    au._run_git = lambda args, cwd, timeout=30: (
        (0, "true\n", "") if args[:2] == ["rev-parse", "--is-inside-work-tree"]
        else (0, "", "") if args[0] == "fetch"
        else (0, f"{local_sha}\n", "") if args == ["rev-parse", "HEAD"]
        else (0, f"{remote_sha}\n", "") if args == ["rev-parse", "origin/main"]
        else (1, "", "boom") if args[0] == "rev-list"
        else (_ for _ in ()).throw(AssertionError(f"unexpected call, got {args!r}")))
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is True and result["commits_behind"] == 0
          and result["update_available"] is False,
          f"a failed rev-list must fall back to commits_behind=0/update_available=False "
          f"instead of crashing (got {result!r})")

    # --- git executable itself missing (launch failure, returncode None) ---
    au._run_git = lambda args, cwd, timeout=30: (None, "", "git-not-found")
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and result["error"] == "not a git checkout",
          f"a None returncode from the very first probe must be treated the same as "
          f"'not a git checkout' (rc != 0 covers None too) (got {result!r})")


# ============================================================================================
# Section B -- download_update()
# ============================================================================================

def section_b():
    print("\n--- Section B: download_update() ---")
    from primeatlas import app_update as au

    orig_run_git = au._run_git

    def restore():
        au._run_git = orig_run_git

    # --- `git status --porcelain` itself fails ---
    au._run_git = lambda args, cwd, timeout=30: (
        (1, "", "fatal: not a git repository") if args[0] == "status"
        else (_ for _ in ()).throw(AssertionError(f"must not go further, got {args!r}")))
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "not a git repository" in result["error"],
          f"a failed status check must surface as an error, never attempt pull "
          f"(got {result!r})")

    # --- dirty working tree -- must refuse WITHOUT ever calling pull ---
    au._run_git = lambda args, cwd, timeout=30: (
        (0, " M primeatlas/settings_tab.py\n", "") if args[0] == "status"
        else (_ for _ in ()).throw(AssertionError(f"must never call pull on a dirty tree, "
                                                    f"got {args!r}")))
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "uncommitted" in result["error"],
          f"a dirty working tree must be refused with a clear error, and pull must never "
          f"be invoked (got {result!r})")

    # --- clean tree, but `git pull --ff-only` itself fails (e.g. diverged history) ---
    au._run_git = lambda args, cwd, timeout=30: (
        (0, "", "") if args[0] == "status"
        else (1, "", "fatal: Not possible to fast-forward, aborting.") if args[0] == "pull"
        else (_ for _ in ()).throw(AssertionError(f"unexpected call, got {args!r}")))
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "fast-forward" in result["error"],
          f"a failed ff-only pull must surface git's own stderr, not silently succeed "
          f"(got {result!r})")

    # --- clean tree, pull succeeds -- and confirm --ff-only is actually passed ---
    captured_argv = []

    def spying_run_git(args, cwd, timeout=30):
        captured_argv.append(args)
        if args[0] == "status":
            return 0, "", ""
        if args[0] == "pull":
            return 0, "Updating a1b2c3..d4e5f6\nFast-forward\n", ""
        raise AssertionError(f"unexpected call, got {args!r}")

    au._run_git = spying_run_git
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result == {"ok": True, "error": None},
          f"a successful ff-only pull must report ok=True, error=None (got {result!r})")
    pull_calls = [a for a in captured_argv if a[0] == "pull"]
    check(len(pull_calls) == 1 and "--ff-only" in pull_calls[0] and "origin" in pull_calls[0]
          and "main" in pull_calls[0],
          f"download_update must call `git pull --ff-only origin <branch>` -- never a plain "
          f"pull that could create a merge commit (got {pull_calls!r})")


# ============================================================================================

if __name__ == "__main__":
    section_a()
    section_b()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All checks passed.")
