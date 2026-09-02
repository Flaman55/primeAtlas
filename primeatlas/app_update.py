"""
app_update.py -- checks GitHub for a newer PrimeAtlas version and applies it.

Context (Artur, 2026-09-02): unlike a packaged/installed application, PrimeAtlas IS its
own git checkout -- the running Python process executes prime_atlas_v1.py directly out of
the same working tree `git log` shows history for (every fix in this project's whole
development history reached Artur's machine exactly this way: a `git commit` here, then
Artur running from that same checkout). So there is no separate release/version-number
scheme to invent: "check for updates" means "is `origin`'s default branch ahead of my
current HEAD", and "download" means a plain `git pull --ff-only` against that branch --
nothing more elaborate (no GitHub Releases API, no downloading/unpacking a zip, no
replacing an installed copy of the app).

This also shapes what download_update() refuses to do: it will only ever fast-forward.
If the local checkout has diverged (uncommitted changes, or local commits `origin` doesn't
have), it reports why and touches nothing -- never force-resets or merges automatically.
A user (Artur) mid-edit on these very files, or with local-only commits not yet pushed,
must not have that work silently clobbered by an "auto-update" feature.

Pure Python, no tkinter dependency -- exercised directly by unit tests
(unitTests/test_app_update.py), same "backend has zero UI dependency" split as every other
primeatlas/ module. All subprocess calls are routed through _run_git() so tests can
monkeypatch that one function without a real git installation or network access -- same
"thin, separately-named, mockable" split env_setup.py's _run_windows() uses.

Runs `git` directly on the Windows side (NOT via wsl.exe) -- this operates on the
Windows-side git checkout itself; WSL has nothing to do with it. Same "plain local
subprocess, not a WSL round-trip" reasoning as primality.py's try_import_sympy()/
LocalLoggedRunner (Faza 2b installer).
"""
import os
import subprocess


def _popen_kwargs_no_window():
    """Mirrors env_setup.py's own helper of the same name -- not imported from there since
    this module is meant to stay a fully independent, minimal-dependency leaf (no reason
    for the update-checker to import the WSL-install module, or vice versa)."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _run_git(args, cwd, timeout=30):
    """Thin, mockable wrapper around a single `git` invocation. Returns
    (returncode, stdout, stderr). returncode is None on total launch failure (git itself
    not installed/not on PATH, or the timeout expiring) -- a normal non-zero exit from git
    itself (e.g. `git fetch` with no network) is NOT an exception here, just a returncode
    the caller inspects, same convention as env_setup.py's _run_windows()."""
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            **_popen_kwargs_no_window())
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return None, "", "git-not-found"
    except subprocess.TimeoutExpired:
        return None, "", "timed-out"
    except OSError as e:
        return None, "", str(e)


def _no_update_result(error):
    return {"ok": False, "update_available": False, "commits_behind": 0,
            "local_commit": None, "remote_commit": None, "error": error}


def check_for_update(repo_dir, branch="main", timeout=20):
    """Fetches `origin` and compares local HEAD against origin/<branch>. Returns:
        {"ok": bool, "update_available": bool, "commits_behind": int,
         "local_commit": str|None, "remote_commit": str|None, "error": str|None}
    ok=False means the check itself could not complete (no network, git missing, repo_dir
    isn't a git checkout, etc) -- error explains why, in whatever text git itself printed
    to stderr (or a short internal label like "git-not-found" for launch failures that
    never reach git's own error reporting). update_available/commits_behind are only
    meaningful when ok=True.

    Deliberately does NOT attempt anything destructive or state-changing beyond the fetch
    itself (which only updates the local `origin/<branch>` remote-tracking ref, not any
    local branch or the working tree) -- see download_update() for the separate,
    explicitly-invoked step that actually changes files."""
    rc, _out, _err = _run_git(["rev-parse", "--is-inside-work-tree"], repo_dir, timeout=5)
    if rc != 0:
        return _no_update_result("not a git checkout")

    rc, _out, err = _run_git(["fetch", "origin", branch], repo_dir, timeout=timeout)
    if rc != 0:
        return _no_update_result(err.strip() or "git fetch failed")

    rc, local_commit, err = _run_git(["rev-parse", "HEAD"], repo_dir, timeout=5)
    if rc != 0:
        return _no_update_result(err.strip() or "could not read local HEAD")
    local_commit = local_commit.strip()

    rc, remote_commit, err = _run_git(
        ["rev-parse", f"origin/{branch}"], repo_dir, timeout=5)
    if rc != 0:
        return _no_update_result(err.strip() or f"could not read origin/{branch}")
    remote_commit = remote_commit.strip()

    if local_commit == remote_commit:
        return {"ok": True, "update_available": False, "commits_behind": 0,
                "local_commit": local_commit, "remote_commit": remote_commit, "error": None}

    rc, count_out, err = _run_git(
        ["rev-list", "--count", f"{local_commit}..{remote_commit}"], repo_dir, timeout=5)
    commits_behind = int(count_out.strip()) if rc == 0 and count_out.strip().isdigit() else 0

    return {"ok": True, "update_available": commits_behind > 0,
            "commits_behind": commits_behind, "local_commit": local_commit,
            "remote_commit": remote_commit, "error": None}


def download_update(repo_dir, branch="main", timeout=60):
    """Applies a previously-detected update via `git pull --ff-only origin <branch>`.
    Returns {"ok": bool, "error": str|None}.

    Refuses up front (without ever calling `git pull`) if the working tree has
    uncommitted changes -- pulling on top of a dirty tree can silently create merge
    conflicts inside files the user is mid-edit on, which this module will never risk.
    --ff-only itself additionally refuses (git exits non-zero rather than creating a merge
    commit) if local HEAD has commits origin/<branch> doesn't -- that divergence is a case
    this module explicitly leaves for the user to resolve by hand, not something it
    guesses at."""
    rc, status_out, err = _run_git(["status", "--porcelain"], repo_dir, timeout=10)
    if rc != 0:
        return {"ok": False, "error": err.strip() or "git status failed"}
    if status_out.strip():
        return {"ok": False,
                "error": "uncommitted local changes -- commit or discard them first"}

    rc, out, err = _run_git(["pull", "--ff-only", "origin", branch], repo_dir, timeout=timeout)
    if rc != 0:
        return {"ok": False, "error": err.strip() or out.strip() or "git pull failed"}
    return {"ok": True, "error": None}
