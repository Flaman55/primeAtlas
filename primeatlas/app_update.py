"""
app_update.py -- checks GitHub for a newer PrimeAtlas version and applies it.

Context (Artur, 2026-09-02): unlike a packaged/installed application, PrimeAtlas IS its
own git checkout -- the running Python process executes prime_atlas_v1.py directly out of
the same working tree `git log` shows history for (every fix in this project's whole
development history reached Artur's machine exactly this way: a `git commit` here, then
Artur running from that same checkout). So there is no separate release/version-number
scheme to invent: "check for updates" means "is `origin`'s default branch ahead of my
current HEAD", and "download" means fetching + fast-forwarding to that branch -- nothing
more elaborate (no GitHub Releases API, no downloading/unpacking a zip, no replacing an
installed copy of the app).

This also shapes what download_update() refuses to do: it will only ever fast-forward.
If the local checkout has diverged (uncommitted changes, or local commits `origin` doesn't
have), it reports why and touches nothing -- never force-resets or merges automatically.
A user (Artur) mid-edit on these very files, or with local-only commits not yet pushed,
must not have that work silently clobbered by an "auto-update" feature.

Follow-up (Artur, 2026-09-10, part 1): the Settings > Aktualizacje "Sprawdz teraz" button
correctly detected an update but then failed to download it, surfacing git's own
"fatal: Not possible to fast-forward, aborting." verbatim -- a real, if terse, divergence
error, but one this module can detect proactively (via `git merge-base --is-ancestor`) and
explain in a way Artur can actually act on instead of a raw git error dump (see the
merge-base check in download_update() below). Separately -- the "access" half of what
Artur originally flagged -- this project's git checkouts have repeatedly hit a filesystem
quirk (TEAM_PLAN.md ground rule #7) where a leftover `.git/index.lock`/`HEAD.lock`/etc.
from an interrupted git process, or a momentary hold by another concurrent git invocation
(an IDE's background `git status`, a sync client, ...), makes an otherwise perfectly
fast-forwardable operation fail with a permission-denied-flavored error that has nothing
to do with real history divergence.

Follow-up (Artur, 2026-09-10, part 2): the first fix for that lock problem cleared any
lock file simply because it was older than two minutes. GPT correctly flagged that an
age threshold cannot actually tell a crashed/abandoned lock apart from one still
protecting a real, slow operation -- but GPT's own safer revision then just retried once
and otherwise left the lock in place and reported an error, which Artur rejected for a
different reason: that leaves the user stuck with a problem they have no way to resolve
themselves, and updating the app is not something a user should need to debug by hand.
_run_git_with_lock_recovery() below is the reconciliation of both concerns: it verifies
whether a lock is actually still in use the same way the operating system itself would
(a rename of a file another process still has open fails with a real permission/sharing
error on both Windows and POSIX -- git never opens its own lock files with
FILE_SHARE_DELETE, so a *successful* rename is proof the lock was abandoned, not a guess),
retries automatically for close to half a minute if something keeps refusing to let go,
and only surfaces an error to the user once that whole budget is spent -- at which point
something has genuinely held a git lock far longer than any operation in this project's
own history ever has.

Follow-up (Artur, 2026-09-10, part 3): Artur questioned the whole check-side design --
why route the mere act of checking for an update through git at all, when it is exactly
the `git fetch` call in check_for_update() (run automatically on every app startup, task
#524) that has been the single biggest source of the lock contention parts 1/2 above spent
so much effort recovering from, even though a fetch never touches a single working-tree
file. The answer isn't "git is the wrong tool" in general -- download_update() deliberately
STAYS on git (see its own docstring): applying an update means overwriting real files in a
real git working tree, and git's fetch+merge already gives that step transactional safety
(nothing changes if it fails) and dirty-tree/divergence protection for free, neither of
which a raw file/zip download would have without reinventing them, and both of which matter
because this checkout is Artur's/GPT's actual live development tree, not a disposable
install. But the CHECK step never needed local git state to begin with -- it only needs to
know origin's current HEAD commit, which the GitHub REST API can answer directly over HTTP
without touching `.git` at all. check_for_update() now resolves origin's branch HEAD (and,
if that differs from local HEAD, how many commits behind) via _check_for_update_via_api()
first, and only falls back to the original _check_for_update_via_git_fetch() path when the
API route isn't usable (origin isn't a recognizable github.com remote, or the API request
itself fails for any reason) -- so a non-GitHub remote or a GitHub outage degrades to
exactly today's behavior rather than breaking the feature.

Pure Python, no tkinter dependency -- exercised directly by unit tests
(unitTests/test_app_update.py), same "backend has zero UI dependency" split as every other
primeatlas/ module. All subprocess calls are routed through _run_git() so tests can
monkeypatch that one function without a real git installation or network access -- same
"thin, separately-named, mockable" split env_setup.py's _run_windows() uses. _sleep(),
_try_release_lock_file(), and _github_api_get() get the same treatment so the lock-recovery
retry/backoff schedule and the GitHub API path can both be exercised by tests in well under
a second, with no real network access or ~30-second wait.

Runs `git` directly on the Windows side (NOT via wsl.exe) -- this operates on the
Windows-side git checkout itself; WSL has nothing to do with it. Same "plain local
subprocess, not a WSL round-trip" reasoning as primality.py's try_import_sympy()/
LocalLoggedRunner (Faza 2b installer).
"""
import glob
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


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


def _sleep(seconds):
    """Thin, mockable wrapper around time.sleep -- same "thin, separately-named, mockable"
    convention as _run_git(), so tests can run the whole lock-recovery retry/backoff
    schedule instantly instead of actually waiting up to ~30 real seconds."""
    time.sleep(seconds)


def _no_update_result(error):
    return {"ok": False, "update_available": False, "commits_behind": 0,
            "local_commit": None, "remote_commit": None, "error": error}


def _find_lock_files(git_dir):
    """Every `*.lock` file directly under git_dir, plus any nested under refs/ (branch/
    remote-tracking ref locks) -- the handful of lock files git itself creates while
    updating the index, HEAD, ORIG_HEAD, FETCH_HEAD, or a ref. Deliberately does NOT touch
    `.git/objects/**/tmp_obj_*` -- those are a different, self-healing mechanism (git
    regenerates them itself on the next successful operation) and not what blocks a
    fetch/merge the way a ref/index lock does."""
    found = set()
    found.update(glob.glob(os.path.join(git_dir, "*.lock")))
    found.update(glob.glob(os.path.join(git_dir, "refs", "**", "*.lock"), recursive=True))
    return sorted(found)


def _git_lock_dirs(repo_dir):
    """Resolves both the worktree-local git-dir and the shared common git-dir for repo_dir
    (these differ only for a linked worktree; identical for a normal single checkout,
    which is what every real PrimeAtlas install actually is) -- lock files relevant to a
    fetch/merge/status can live in either."""
    git_dirs = set()
    for arg in ("--git-dir", "--git-common-dir"):
        rc, out, _err = _run_git(["rev-parse", arg], repo_dir, timeout=5)
        if rc == 0 and out.strip():
            resolved = out.strip()
            if not os.path.isabs(resolved):
                resolved = os.path.join(repo_dir, resolved)
            git_dirs.add(os.path.normpath(resolved))
    return git_dirs


def _try_release_lock_file(lock_path):
    """Attempts to move a single lock file aside (renamed, never deleted -- same
    non-destructive spirit as everywhere else this codebase touches git internals).
    Returns True if lock_path is confirmed gone afterward -- either the rename succeeded,
    or it was already gone (the git process that held it finished on its own in the
    meantime). This is the operating system's own proof that nothing has the file open
    anymore, NOT a guess based on the file's age: git never opens its own lock files with
    FILE_SHARE_DELETE, so a real, live git process still holding this file makes the
    rename fail with a genuine permission/sharing error, both on Windows and POSIX.
    Returns False in that case -- and only in that case -- meaning the caller must treat
    the lock as still legitimately in use and must not force anything further."""
    try:
        os.rename(lock_path, f"{lock_path}.stale_{int(time.time() * 1000)}")
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _release_all_locks(repo_dir):
    """Attempts to move every lock file currently present for this checkout (across both
    git-dirs from _git_lock_dirs()) out of the way. Returns True only if every single one
    was confirmed free (or none existed) -- a single still-in-use lock makes this return
    False, since leaving even one real lock in place means the git command that follows
    would just fail again anyway."""
    all_released = True
    for git_dir in _git_lock_dirs(repo_dir):
        for lock_path in _find_lock_files(git_dir):
            if not _try_release_lock_file(lock_path):
                all_released = False
    return all_released


def _looks_like_lock_error(text):
    """True if a failed git invocation's stderr looks like the lock/permission quirk this
    project has hit repeatedly (TEAM_PLAN.md ground rule #7) rather than a genuine history
    divergence or network failure -- used to decide whether _run_git_with_lock_recovery()
    should attempt its retry/recovery schedule at all."""
    text = (text or "").lower()
    return (
        ("unable to create" in text and "lock" in text)
        or "cannot lock ref" in text
        or "unable to unlink" in text
        or "index.lock" in text
        or "another git process seems to be running" in text
    )


# Passive phase: a few short, non-destructive retries -- covers the common case of a
# short-lived concurrent git invocation (e.g. an IDE's background `git status`) that
# releases the lock on its own well within this window.
_LOCK_PASSIVE_RETRY_DELAYS = (0.5, 1.0, 1.5)

# Active phase: once the passive retries are exhausted, alternate between attempting an
# OS-verified release and, if that's refused, waiting before checking again. Total worst
# case is roughly 3s (passive) + 8 * 3s (active) =~ 27s -- comfortably longer than any
# fetch/merge this repo has ever taken in this project's history, but still bounded so
# Settings > Aktualizacje can never hang indefinitely.
_LOCK_RELEASE_ROUNDS = 8
_LOCK_RELEASE_WAIT_SECONDS = 3.0


def _run_git_with_lock_recovery(args, cwd, timeout=30):
    """Runs a git command and, if it fails because of a leftover/contended lock file
    rather than a real git error, keeps retrying instead of immediately handing the user
    an error they have no way to act on -- see the module docstring's "part 2" follow-up
    for why this replaced both the earlier blind age-based auto-clear and a later
    "retry once, then just report it" revision. Returns the same (returncode, stdout,
    stderr) tuple _run_git() does; a non-lock failure (including a genuine divergence
    error) is returned immediately on the very first attempt, unchanged."""
    rc, out, err = _run_git(args, cwd, timeout=timeout)
    if rc == 0 or not _looks_like_lock_error(err):
        return rc, out, err

    for delay in _LOCK_PASSIVE_RETRY_DELAYS:
        _sleep(delay)
        rc, out, err = _run_git(args, cwd, timeout=timeout)
        if rc == 0 or not _looks_like_lock_error(err):
            return rc, out, err

    for _round in range(_LOCK_RELEASE_ROUNDS):
        if _release_all_locks(cwd):
            rc, out, err = _run_git(args, cwd, timeout=timeout)
            if rc == 0 or not _looks_like_lock_error(err):
                return rc, out, err
        else:
            _sleep(_LOCK_RELEASE_WAIT_SECONDS)

    return rc, out, err


_GITHUB_API_BASE = "https://api.github.com"

_GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$")


def _parse_github_owner_repo(remote_url):
    """Extracts (owner, repo) from a github.com remote URL in any of its common forms
    (`https://github.com/<owner>/<repo>.git`, `https://github.com/<owner>/<repo>`,
    `git@github.com:<owner>/<repo>.git`, `ssh://git@github.com/<owner>/<repo>.git`).
    Returns None for anything that doesn't match -- a non-GitHub remote (a private git
    server, a local path, ...) is a perfectly normal setup this function must recognize as
    "API path not usable" rather than raise on."""
    if not remote_url:
        return None
    match = _GITHUB_REMOTE_RE.search(remote_url.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _resolve_github_repo(repo_dir):
    """Returns (owner, repo) for origin's GitHub remote, or None if origin's URL couldn't
    be read at all or isn't a recognizable github.com remote. This is the one and only
    local git call the whole GitHub-API check path makes -- `git remote get-url` reads a
    single line out of `.git/config`, never creates a lock file, and is safe to call even
    while another git operation is genuinely in progress."""
    rc, remote_url, _err = _run_git(["remote", "get-url", "origin"], repo_dir, timeout=5)
    if rc != 0:
        return None
    return _parse_github_owner_repo(remote_url)


def _github_api_get(path, timeout=10):
    """Thin, mockable wrapper around a single GitHub REST API GET request -- same "thin,
    separately-named, mockable" convention as _run_git(). Returns (ok, data, error): data
    is the parsed JSON body on success, error is a short human-readable string on failure.
    Never raises -- any DNS/network/HTTP/timeout/malformed-JSON problem is caught here and
    reported through the return value instead, so a GitHub outage or firewall degrades to a
    normal, handled "API path unavailable" instead of an unhandled exception."""
    url = f"{_GITHUB_API_BASE}{path}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "PrimeAtlas-self-updater",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
        return True, json.loads(body), None
    except urllib.error.HTTPError as e:
        return False, None, f"GitHub API returned HTTP {e.code} for {path}"
    except urllib.error.URLError as e:
        return False, None, f"could not reach the GitHub API: {e.reason}"
    except (TimeoutError, OSError) as e:
        return False, None, f"GitHub API request failed: {e}"
    except (ValueError, json.JSONDecodeError) as e:
        return False, None, f"GitHub API returned unparsable data: {e}"


def _check_for_update_via_api(repo_dir, branch, timeout, local_commit):
    """The primary check path (see the module docstring's "part 3" follow-up) -- resolves
    origin/<branch>'s current HEAD commit via the GitHub REST API instead of `git fetch`,
    touching `.git` only once (the read-only remote-URL lookup in _resolve_github_repo()).
    Returns the same result dict check_for_update() does on success, or None if the API
    path isn't usable for any reason at all (non-GitHub remote, network failure, malformed
    response, ...) -- callers must treat None as "fall back to the git-fetch path", not as
    a hard failure of the whole check."""
    github_repo = _resolve_github_repo(repo_dir)
    if github_repo is None:
        return None
    owner, repo = (urllib.parse.quote(part, safe="") for part in github_repo)

    ok, data, _err = _github_api_get(
        f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(branch, safe='')}", timeout)
    if not ok or not isinstance(data, dict) or not isinstance(data.get("sha"), str):
        return None
    remote_commit = data["sha"]

    if local_commit == remote_commit:
        return {"ok": True, "update_available": False, "commits_behind": 0,
                "local_commit": local_commit, "remote_commit": remote_commit, "error": None}

    ok, data, _err = _github_api_get(
        f"/repos/{owner}/{repo}/compare/{local_commit}...{remote_commit}", timeout)
    commits_behind = 0
    if ok and isinstance(data, dict) and isinstance(data.get("ahead_by"), int):
        commits_behind = data["ahead_by"]

    return {"ok": True, "update_available": commits_behind > 0,
            "commits_behind": commits_behind, "local_commit": local_commit,
            "remote_commit": remote_commit, "error": None}


def _check_for_update_via_git_fetch(repo_dir, branch, timeout, local_commit):
    """Fallback check path used when _check_for_update_via_api() reports the API route
    isn't usable -- this is the original (pre-2026-09-10-part-3) `git fetch`-based check,
    kept verbatim as a safety net so a non-GitHub remote or a GitHub API outage degrades to
    exactly the prior behavior instead of breaking the feature. Goes through
    _run_git_with_lock_recovery() for the fetch, same as before part 3, since this path can
    still hit the lock contention parts 1/2 addressed."""
    rc, _out, err = _run_git_with_lock_recovery(
        ["fetch", "origin", branch], repo_dir, timeout=timeout)
    if rc != 0:
        return _no_update_result(err.strip() or "git fetch failed")

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


def check_for_update(repo_dir, branch="main", timeout=20):
    """Compares local HEAD against origin/<branch>'s current HEAD. Returns:
        {"ok": bool, "update_available": bool, "commits_behind": int,
         "local_commit": str|None, "remote_commit": str|None, "error": str|None}
    ok=False means the check itself could not complete (no network, git missing, repo_dir
    isn't a git checkout, etc) -- error explains why. update_available/commits_behind are
    only meaningful when ok=True.

    Tries the GitHub-API-based path first (_check_for_update_via_api()) and falls back to
    the git-fetch-based path (_check_for_update_via_git_fetch()) only if that reports the
    API route isn't usable -- see the module docstring's "part 3" follow-up for why. Either
    way, this never attempts anything destructive or state-changing to the working tree --
    see download_update() for the separate, explicitly-invoked step that actually changes
    files."""
    rc, _out, _err = _run_git(["rev-parse", "--is-inside-work-tree"], repo_dir, timeout=5)
    if rc != 0:
        return _no_update_result("not a git checkout")

    rc, local_commit, err = _run_git(["rev-parse", "HEAD"], repo_dir, timeout=5)
    if rc != 0:
        return _no_update_result(err.strip() or "could not read local HEAD")
    local_commit = local_commit.strip()

    api_result = _check_for_update_via_api(repo_dir, branch, timeout, local_commit)
    if api_result is not None:
        return api_result

    return _check_for_update_via_git_fetch(repo_dir, branch, timeout, local_commit)


def download_update(repo_dir, branch="main", timeout=60):
    """Applies a previously-detected update by fetching `origin` and, if that leaves HEAD
    a strict ancestor of origin/<branch>, fast-forwarding onto it (`git merge --ff-only`,
    the same end effect as `git pull --ff-only origin <branch>` -- split into its two
    steps here so a real divergence can be reported with a clear, actionable message
    instead of git's own terse "fatal: Not possible to fast-forward, aborting."). Every
    git call that could plausibly hit a lock (status, fetch, merge-base, merge) goes
    through _run_git_with_lock_recovery() -- see that function and the module docstring's
    "part 2" follow-up. Returns {"ok": bool, "error": str|None}.

    Refuses up front (without ever calling fetch/merge) if the working tree has
    uncommitted changes -- pulling on top of a dirty tree can silently create merge
    conflicts inside files the user is mid-edit on, which this module will never risk.
    Genuine divergence (local HEAD has commits origin/<branch> doesn't) is detected
    explicitly via `git merge-base --is-ancestor` and left for the user to resolve by
    hand, not guessed at or auto-merged."""
    rc, status_out, err = _run_git_with_lock_recovery(
        ["status", "--porcelain"], repo_dir, timeout=10)
    if rc != 0:
        return {"ok": False, "error": err.strip() or "git status failed"}
    if status_out.strip():
        return {"ok": False,
                "error": "uncommitted local changes -- commit or discard them first"}

    rc, _out, err = _run_git_with_lock_recovery(
        ["fetch", "origin", branch], repo_dir, timeout=timeout)
    if rc != 0:
        return {"ok": False, "error": err.strip() or "git fetch failed"}

    rc, _out, err = _run_git_with_lock_recovery(
        ["merge-base", "--is-ancestor", "HEAD", f"origin/{branch}"], repo_dir, timeout=10)
    if rc == 1:
        return {"ok": False, "error": (
            f"local checkout has commits that origin/{branch} doesn't have -- "
            f"auto-update only ever fast-forwards and refuses to touch history that has "
            f"diverged. Resolve by hand, e.g. `git log origin/{branch}..HEAD` to see "
            f"what's local-only, then decide whether to push it, stash it, or discard it."
        )}
    if rc not in (0, 1):
        return {"ok": False,
                "error": err.strip() or "could not determine fast-forward eligibility"}

    rc, out, err = _run_git_with_lock_recovery(
        ["merge", "--ff-only", f"origin/{branch}"], repo_dir, timeout=timeout)
    if rc != 0:
        return {"ok": False, "error": err.strip() or out.strip() or "git merge failed"}
    return {"ok": True, "error": None}
