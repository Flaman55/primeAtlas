"""
test_app_update.py -- covers primeatlas/app_update.py, the self-update checker/downloader
wired into Settings > Aktualizacje and prime_atlas_v1.py's startup hook (task #521, refined
2026-09-10 across three follow-ups -- lock/access-recovery, OS-verified lock recovery, and
the GitHub-API-based check path -- see app_update.py's own module docstring for the full
story of each).

No real git repo, network, or GitHub remote anywhere in this sandbox -- every subprocess
boundary is stubbed by monkeypatching the module's own _run_git(), same "thin, separately
named, mockable" split env_setup.py's _run_windows() uses (see test_env_setup.py's own
docstring for the precedent). _sleep() and _github_api_get() get the same treatment, so the
lock-recovery retry/backoff schedule (up to ~27 real seconds in production) and the GitHub
API path both run instantly here with no real network access. Four sections:

  A. check_for_update()'s git-fetch fallback path -- not-a-repo / fetch-fails /
     rev-parse-fails / up-to-date / N-commits-behind paths, plus a
     lock-recovery-resolves-it-transparently case. Every test here relies on make_stub()'s
     automatic `git remote get-url origin` failure to force the dispatcher straight past
     the GitHub-API path and into this fallback, exactly like a non-GitHub remote would in
     production.
  A2. check_for_update()'s GitHub-API path -- _parse_github_owner_repo() URL-form parsing,
     _resolve_github_repo(), _github_api_get()'s own error handling, and
     _check_for_update_via_api()'s up-to-date/behind-by-N/malformed-response cases, plus
     confirming check_for_update() itself never calls `git fetch` when the API path
     succeeds, and does fall back to it when the API path is unusable.
  B. download_update() -- status-check-fails / dirty-working-tree-refusal / diverged /
     merge-fails / full-success paths. Deliberately still 100% git-based, unlike check_for_
     update() -- see download_update()'s own docstring for why the two commands took
     different paths in the "part 3" follow-up.
  C. Lock-recovery mechanics -- _looks_like_lock_error() classification,
     _try_release_lock_file() against real temp files (including the OS-verified "still in
     use" case), _release_all_locks(), and _run_git_with_lock_recovery()'s full
     retry/backoff schedule (passive-phase resolution, active-release resolution, and
     budget exhaustion), all with _sleep() mocked out so this runs in well under a second.

Usage:
    python3 unitTests/test_app_update.py
"""
import json
import os
import sys
import tempfile
import urllib.error

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


def make_stub(rules):
    """Builds a _run_git replacement from an ordered list of (predicate, result) pairs --
    predicate(args) -> bool, result is either (rc, out, err) or a callable returning that
    tuple (for cases that need to react to call count). Falls through to an assertion
    failure if no rule matches, so an unexpected call is caught immediately instead of
    silently returning something misleading. Automatically absorbs the harmless
    `rev-parse --git-dir` / `--git-common-dir` probe calls _git_lock_dirs() makes (as long
    as no rule explicitly claims them first) by returning a fixed fake git-dir, so lock
    recovery can be exercised without every test having to stub those two calls by hand."""
    call_log = []

    def stub(args, cwd, timeout=30):
        call_log.append(list(args))
        for predicate, result in rules:
            if predicate(args):
                return result() if callable(result) else result
        if args[:1] == ["rev-parse"] and args[1:2] in (["--git-dir"], ["--git-common-dir"]):
            return 0, ".git\n", ""
        if args == ["remote", "get-url", "origin"]:
            # Default: no usable GitHub remote -- forces check_for_update()'s dispatcher
            # straight to the git-fetch fallback path, so every existing test in Section A
            # (written against that path) keeps working unchanged. Section A2 overrides
            # this per-test where the GitHub-API path itself needs to be exercised.
            return 1, "", "fatal: No such remote 'origin'"
        raise AssertionError(f"unexpected call, got {args!r}")

    stub.call_log = call_log
    return stub


# ============================================================================================
# Section A -- check_for_update()
# ============================================================================================

def section_a():
    print("\n--- Section A: check_for_update() ---")
    from primeatlas import app_update as au

    orig_run_git = au._run_git
    orig_sleep = au._sleep

    def restore():
        au._run_git = orig_run_git
        au._sleep = orig_sleep

    au._sleep = lambda seconds: None  # every test in this section runs instantly

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

    # --- rev-parse ok, GitHub-API path unusable (make_stub's default remote-get-url
    #     failure), and the git-fetch fallback's own `git fetch` fails for a real (non-lock)
    #     reason -- must not trigger any retry/recovery ---
    stub = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a == ["rev-parse", "HEAD"], (0, f"{'a' * 40}\n", "")),
        (lambda a: a[0] == "fetch",
         (1, "", "fatal: unable to access 'origin': network unreachable")),
    ])
    au._run_git = stub
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "network unreachable" in result["error"],
          f"a failed fetch (non-lock error) must surface git's own stderr as the error "
          f"(got {result!r})")
    check(len(stub.call_log) == 4,
          f"a genuine network error must NOT trigger the lock-recovery retry schedule -- "
          f"expected exactly 4 calls (rev-parse is-inside-work-tree, rev-parse HEAD, "
          f"remote get-url [fails, forcing fallback], one fetch attempt), got "
          f"{stub.call_log!r}")

    # --- fetch is blocked by a lock error transiently, then succeeds on its own -- this is
    #     the passive-retry phase of _run_git_with_lock_recovery() doing its job ---
    fetch_attempts = {"n": 0}

    def flaky_fetch():
        fetch_attempts["n"] += 1
        if fetch_attempts["n"] < 3:
            return 128, "", "fatal: Unable to create '.git/index.lock': File exists."
        return 0, "", ""

    au._run_git = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a[0] == "fetch", flaky_fetch),
        (lambda a: a == ["rev-parse", "HEAD"], (0, f"{'a' * 40}\n", "")),
        (lambda a: a == ["rev-parse", "origin/main"], (0, f"{'a' * 40}\n", "")),
    ])
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is True,
          f"a fetch that only transiently hits a lock error must succeed once the lock "
          f"clears on its own, without ever surfacing an error (got {result!r})")
    check(fetch_attempts["n"] == 3,
          f"expected exactly 3 fetch attempts (1 initial + 2 retries before success), got "
          f"{fetch_attempts['n']}")

    # --- reading local HEAD fails (should not normally happen, defensive path) -- this is
    #     now checked before either the API or git-fetch path is even attempted ---
    au._run_git = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a == ["rev-parse", "HEAD"], (1, "", "fatal: bad revision 'HEAD'")),
    ])
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "bad revision" in result["error"],
          f"a failed local HEAD read must surface as an error (got {result!r})")

    # --- up to date: local HEAD == origin/branch ---
    same_sha = "a" * 40
    au._run_git = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a == ["rev-parse", "HEAD"], (0, f"{same_sha}\n", "")),
        (lambda a: a == ["rev-parse", "origin/main"], (0, f"{same_sha}\n", "")),
        (lambda a: a[0] == "rev-list",
         lambda: (_ for _ in ()).throw(AssertionError("must not call rev-list when up to date"))),
    ])
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
    au._run_git = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a == ["rev-parse", "HEAD"], (0, f"{local_sha}\n", "")),
        (lambda a: a == ["rev-parse", "origin/main"], (0, f"{remote_sha}\n", "")),
        (lambda a: a == ["rev-list", "--count", f"{local_sha}..{remote_sha}"],
         (0, "7\n", "")),
    ])
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is True and result["update_available"] is True
          and result["commits_behind"] == 7,
          f"a diverged local/remote pair must report the real rev-list count "
          f"(got {result!r})")

    # --- N commits behind, but rev-list itself fails -- must not crash, falls back to 0 ---
    au._run_git = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a == ["rev-parse", "HEAD"], (0, f"{local_sha}\n", "")),
        (lambda a: a == ["rev-parse", "origin/main"], (0, f"{remote_sha}\n", "")),
        (lambda a: a[0] == "rev-list", (1, "", "boom")),
    ])
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
# Section A2 -- check_for_update()'s GitHub-API path
# ============================================================================================

def section_a2():
    print("\n--- Section A2: check_for_update() GitHub-API path ---")
    from primeatlas import app_update as au

    # --- _parse_github_owner_repo(): every common remote URL form, plus non-matches ---
    github_forms = [
        "https://github.com/Flaman55/primeAtlas.git",
        "https://github.com/Flaman55/primeAtlas",
        "git@github.com:Flaman55/primeAtlas.git",
        "ssh://git@github.com/Flaman55/primeAtlas.git",
        "https://github.com/Flaman55/primeAtlas/",
    ]
    for url in github_forms:
        result = au._parse_github_owner_repo(url)
        check(result == ("Flaman55", "primeAtlas"),
              f"must parse owner/repo out of {url!r} (got {result!r})")

    non_github = ["https://gitlab.com/Flaman55/primeAtlas.git",
                  "/local/path/to/repo", "", None]
    for url in non_github:
        result = au._parse_github_owner_repo(url)
        check(result is None, f"must NOT match a non-github.com remote: {url!r} (got "
                               f"{result!r})")

    # --- _resolve_github_repo(): wraps `git remote get-url origin` + the parser above ---
    orig_run_git = au._run_git

    def restore_run_git():
        au._run_git = orig_run_git

    au._run_git = lambda args, cwd, timeout=30: (
        (0, "https://github.com/Flaman55/primeAtlas.git\n", "")
        if args == ["remote", "get-url", "origin"]
        else (_ for _ in ()).throw(AssertionError(f"unexpected call, got {args!r}")))
    try:
        result = au._resolve_github_repo("/fake/repo")
    finally:
        restore_run_git()
    check(result == ("Flaman55", "primeAtlas"),
          f"must resolve owner/repo from a real github.com origin (got {result!r})")

    au._run_git = lambda args, cwd, timeout=30: (0, "git@internal-server:team/repo.git\n", "")
    try:
        result = au._resolve_github_repo("/fake/repo")
    finally:
        restore_run_git()
    check(result is None, f"a non-github.com origin must resolve to None (got {result!r})")

    au._run_git = lambda args, cwd, timeout=30: (1, "", "fatal: No such remote 'origin'")
    try:
        result = au._resolve_github_repo("/fake/repo")
    finally:
        restore_run_git()
    check(result is None,
          f"a failed `git remote get-url` must resolve to None, not raise (got {result!r})")

    # --- _github_api_get(): error handling, real urllib.request.urlopen mocked out ---
    import urllib.request as _urllib_request
    orig_urlopen = _urllib_request.urlopen

    class _FakeResponse:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def restore_urlopen():
        _urllib_request.urlopen = orig_urlopen

    _urllib_request.urlopen = lambda request, timeout=10: _FakeResponse(
        json.dumps({"sha": "d" * 40}).encode("utf-8"))
    try:
        ok, data, err = au._github_api_get("/repos/Flaman55/primeAtlas/commits/main")
    finally:
        restore_urlopen()
    check(ok is True and data == {"sha": "d" * 40} and err is None,
          f"a successful GitHub API call must return the parsed JSON body "
          f"(got ok={ok!r}, data={data!r}, err={err!r})")

    def raise_http_error(request, timeout=10):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", hdrs=None, fp=None)

    _urllib_request.urlopen = raise_http_error
    try:
        ok, data, err = au._github_api_get("/repos/x/y/commits/main")
    finally:
        restore_urlopen()
    check(ok is False and data is None and "404" in err,
          f"an HTTP error must be reported cleanly, not raised (got ok={ok!r}, err={err!r})")

    def raise_url_error(request, timeout=10):
        raise urllib.error.URLError("name resolution failed")

    _urllib_request.urlopen = raise_url_error
    try:
        ok, data, err = au._github_api_get("/repos/x/y/commits/main")
    finally:
        restore_urlopen()
    check(ok is False and data is None and err,
          f"a network-level error (e.g. no DNS/no internet) must be reported cleanly, not "
          f"raised (got ok={ok!r}, err={err!r})")

    _urllib_request.urlopen = lambda request, timeout=10: _FakeResponse(b"not valid json{{{")
    try:
        ok, data, err = au._github_api_get("/repos/x/y/commits/main")
    finally:
        restore_urlopen()
    check(ok is False and data is None and err,
          f"unparsable response data must be reported cleanly, not raised "
          f"(got ok={ok!r}, err={err!r})")

    # --- _check_for_update_via_api(): the higher-level orchestration, _github_api_get()
    #     mocked directly (no real urllib involved from here on) ---
    orig_github_api_get = au._github_api_get

    def restore_api():
        au._run_git = orig_run_git
        au._github_api_get = orig_github_api_get

    local_sha = "a" * 40
    remote_sha = "b" * 40

    # up to date: local == remote -- compare API must never be called
    au._run_git = lambda args, cwd, timeout=30: (
        0, "https://github.com/Flaman55/primeAtlas.git\n", "")
    api_calls = []

    def api_up_to_date(path, timeout=10):
        api_calls.append(path)
        if "/commits/" in path:
            return True, {"sha": local_sha}, None
        raise AssertionError(f"must not call compare when up to date, got {path!r}")

    au._github_api_get = api_up_to_date
    try:
        result = au._check_for_update_via_api("/fake/repo", "main", 10, local_sha)
    finally:
        restore_api()
    check(result == {"ok": True, "update_available": False, "commits_behind": 0,
                      "local_commit": local_sha, "remote_commit": local_sha, "error": None},
          f"identical local/remote SHAs via the API path must report up to date without "
          f"ever calling compare (got {result!r})")
    check(len(api_calls) == 1,
          f"expected exactly 1 GitHub API call (the commits lookup) when up to date, got "
          f"{api_calls!r}")

    # N commits behind: local != remote -- compare API supplies ahead_by
    au._run_git = lambda args, cwd, timeout=30: (
        0, "https://github.com/Flaman55/primeAtlas.git\n", "")

    def api_behind(path, timeout=10):
        if "/commits/" in path:
            return True, {"sha": remote_sha}, None
        if "/compare/" in path:
            check(path == f"/repos/Flaman55/primeAtlas/compare/{local_sha}...{remote_sha}",
                  f"compare URL must use local...remote in that order (got {path!r})")
            return True, {"ahead_by": 5, "behind_by": 0, "status": "behind"}, None
        raise AssertionError(f"unexpected API path, got {path!r}")

    au._github_api_get = api_behind
    try:
        result = au._check_for_update_via_api("/fake/repo", "main", 10, local_sha)
    finally:
        restore_api()
    check(result == {"ok": True, "update_available": True, "commits_behind": 5,
                      "local_commit": local_sha, "remote_commit": remote_sha, "error": None},
          f"a real difference must report commits_behind from the compare API's ahead_by "
          f"(got {result!r})")

    # commits lookup itself fails -- must signal "fall back", not raise or hard-fail
    au._run_git = lambda args, cwd, timeout=30: (
        0, "https://github.com/Flaman55/primeAtlas.git\n", "")
    au._github_api_get = lambda path, timeout=10: (False, None, "simulated network failure")
    try:
        result = au._check_for_update_via_api("/fake/repo", "main", 10, local_sha)
    finally:
        restore_api()
    check(result is None,
          f"a failed commits-lookup API call must return None (signalling fallback), not "
          f"an error result (got {result!r})")

    # malformed commits response (missing "sha") -- same "fall back" signal
    au._run_git = lambda args, cwd, timeout=30: (
        0, "https://github.com/Flaman55/primeAtlas.git\n", "")
    au._github_api_get = lambda path, timeout=10: (True, {"unexpected": "shape"}, None)
    try:
        result = au._check_for_update_via_api("/fake/repo", "main", 10, local_sha)
    finally:
        restore_api()
    check(result is None,
          f"a malformed commits response must return None (signalling fallback), not "
          f"crash (got {result!r})")

    # non-github remote -- must return None WITHOUT ever calling _github_api_get
    au._run_git = lambda args, cwd, timeout=30: (
        0, "git@internal-server:team/repo.git\n", "")

    def must_not_be_called(path, timeout=10):
        raise AssertionError("must never call the GitHub API for a non-github.com remote")

    au._github_api_get = must_not_be_called
    try:
        result = au._check_for_update_via_api("/fake/repo", "main", 10, local_sha)
    finally:
        restore_api()
    check(result is None,
          f"a non-github.com remote must return None without ever touching the API "
          f"(got {result!r})")

    # --- check_for_update()'s dispatcher: API success must mean NO `git fetch` at all;
    #     API failure must fall back to a real `git fetch` ---
    orig_sleep = au._sleep
    au._sleep = lambda seconds: None

    def restore_dispatch():
        restore_api()
        au._sleep = orig_sleep

    stub = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a == ["rev-parse", "HEAD"], (0, f"{local_sha}\n", "")),
        (lambda a: a == ["remote", "get-url", "origin"],
         (0, "https://github.com/Flaman55/primeAtlas.git\n", "")),
        (lambda a: a[0] == "fetch",
         lambda: (_ for _ in ()).throw(AssertionError(
             "check_for_update() must never call `git fetch` when the API path succeeds"))),
    ])
    au._run_git = stub
    au._github_api_get = lambda path, timeout=10: (True, {"sha": local_sha}, None)
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore_dispatch()
    check(result["ok"] is True and result["update_available"] is False,
          f"a working API path must produce a normal up-to-date result "
          f"(got {result!r})")

    fetch_stub = make_stub([
        (lambda a: a[:2] == ["rev-parse", "--is-inside-work-tree"], (0, "true\n", "")),
        (lambda a: a == ["rev-parse", "HEAD"], (0, f"{local_sha}\n", "")),
        (lambda a: a == ["remote", "get-url", "origin"],
         (0, "https://github.com/Flaman55/primeAtlas.git\n", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a == ["rev-parse", "origin/main"], (0, f"{local_sha}\n", "")),
    ])
    au._run_git = fetch_stub
    au._github_api_get = lambda path, timeout=10: (False, None, "simulated GitHub outage")
    try:
        result = au.check_for_update("/fake/repo", branch="main")
    finally:
        restore_dispatch()
    check(result["ok"] is True,
          f"when the API path fails, check_for_update() must fall back to a real "
          f"`git fetch` and still succeed (got {result!r})")
    check(any(a[0] == "fetch" for a in fetch_stub.call_log),
          f"the git-fetch fallback must actually have called `git fetch` "
          f"(got {fetch_stub.call_log!r})")


# ============================================================================================
# Section B -- download_update()
# ============================================================================================

def section_b():
    print("\n--- Section B: download_update() ---")
    from primeatlas import app_update as au

    orig_run_git = au._run_git
    orig_sleep = au._sleep

    def restore():
        au._run_git = orig_run_git
        au._sleep = orig_sleep

    au._sleep = lambda seconds: None

    # --- `git status --porcelain` itself fails ---
    au._run_git = make_stub([
        (lambda a: a[0] == "status", (1, "", "fatal: not a git repository")),
    ])
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "not a git repository" in result["error"],
          f"a failed status check must surface as an error, never attempt fetch/merge "
          f"(got {result!r})")

    # --- dirty working tree -- must refuse WITHOUT ever calling fetch/merge ---
    au._run_git = make_stub([
        (lambda a: a[0] == "status", (0, " M primeatlas/settings_tab.py\n", "")),
        (lambda a: a[0] in ("fetch", "merge", "merge-base"),
         lambda: (_ for _ in ()).throw(AssertionError("must never touch fetch/merge on a dirty tree"))),
    ])
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "uncommitted" in result["error"],
          f"a dirty working tree must be refused with a clear error, and fetch/merge must "
          f"never be invoked (got {result!r})")

    # --- clean tree, but `git fetch` fails for a real reason ---
    au._run_git = make_stub([
        (lambda a: a[0] == "status", (0, "", "")),
        (lambda a: a[0] == "fetch",
         (1, "", "fatal: unable to access 'origin': network unreachable")),
    ])
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "network unreachable" in result["error"],
          f"a failed fetch must surface as an error (got {result!r})")

    # --- clean tree, fetch ok, but genuine divergence (merge-base says HEAD is NOT an
    #     ancestor of origin/<branch>) -- must give a clear, actionable message, and must
    #     never attempt the merge itself ---
    au._run_git = make_stub([
        (lambda a: a[0] == "status", (0, "", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a[0] == "merge-base", (1, "", "")),
        (lambda a: a[0] == "merge",
         lambda: (_ for _ in ()).throw(AssertionError("must never merge on genuine divergence"))),
    ])
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "diverged" in result["error"]
          and "origin/main" in result["error"],
          f"genuine divergence must produce a clear, actionable message naming the "
          f"branch, and never attempt the merge (got {result!r})")

    # --- merge-base itself errors out (rc not in {0, 1}) ---
    au._run_git = make_stub([
        (lambda a: a[0] == "status", (0, "", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a[0] == "merge-base", (128, "", "fatal: not a valid object name HEAD")),
    ])
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "not a valid object name" in result["error"],
          f"a real merge-base error (not the divergence rc==1 case) must surface its own "
          f"stderr (got {result!r})")

    # --- clean tree, fetch ok, ancestor confirmed, but the ff-only merge itself fails for
    #     a real reason (defensive -- should be rare given the ancestor check just passed) ---
    au._run_git = make_stub([
        (lambda a: a[0] == "status", (0, "", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a[0] == "merge-base", (0, "", "")),
        (lambda a: a[0] == "merge", (1, "", "fatal: some unexpected merge failure")),
    ])
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is False and "unexpected merge failure" in result["error"],
          f"a genuine merge failure must surface git's own stderr, not silently succeed "
          f"(got {result!r})")

    # --- full success -- and confirm --ff-only / origin / branch are actually passed ---
    stub = make_stub([
        (lambda a: a[0] == "status", (0, "", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a[0] == "merge-base", (0, "", "")),
        (lambda a: a[0] == "merge",
         (0, "Updating a1b2c3..d4e5f6\nFast-forward\n", "")),
    ])
    au._run_git = stub
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result == {"ok": True, "error": None},
          f"a successful fetch + ff-only merge must report ok=True, error=None "
          f"(got {result!r})")
    merge_calls = [a for a in stub.call_log if a[0] == "merge"]
    check(len(merge_calls) == 1 and "--ff-only" in merge_calls[0]
          and f"origin/main" in merge_calls[0],
          f"download_update must call `git merge --ff-only origin/<branch>` -- never a "
          f"plain merge that could create a merge commit (got {merge_calls!r})")

    # --- lock error on fetch resolved by the passive-retry phase, then everything else
    #     proceeds normally to a real success ---
    fetch_attempts = {"n": 0}

    def flaky_fetch():
        fetch_attempts["n"] += 1
        if fetch_attempts["n"] < 2:
            return 128, "", "fatal: Unable to create '.git/index.lock': File exists."
        return 0, "", ""

    au._run_git = make_stub([
        (lambda a: a[0] == "status", (0, "", "")),
        (lambda a: a[0] == "fetch", flaky_fetch),
        (lambda a: a[0] == "merge-base", (0, "", "")),
        (lambda a: a[0] == "merge", (0, "Fast-forward\n", "")),
    ])
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
    check(result["ok"] is True,
          f"a transient lock error on fetch must be recovered from automatically "
          f"(got {result!r})")
    check(fetch_attempts["n"] == 2,
          f"expected exactly 2 fetch attempts (1 initial + 1 passive retry), got "
          f"{fetch_attempts['n']}")

    # --- lock error on merge resolved only after an OS-verified release round ---
    merge_attempts = {"n": 0}

    def flaky_merge():
        merge_attempts["n"] += 1
        if merge_attempts["n"] <= 1 + len(au._LOCK_PASSIVE_RETRY_DELAYS):
            return 128, "", "fatal: Unable to create '.git/index.lock': File exists."
        return 0, "Fast-forward\n", ""

    au._run_git = make_stub([
        (lambda a: a[0] == "status", (0, "", "")),
        (lambda a: a[0] == "fetch", (0, "", "")),
        (lambda a: a[0] == "merge-base", (0, "", "")),
        (lambda a: a[0] == "merge", flaky_merge),
    ])
    released = {"called": False}
    orig_release = au._release_all_locks
    au._release_all_locks = lambda repo_dir: released.__setitem__("called", True) or True
    try:
        result = au.download_update("/fake/repo", branch="main")
    finally:
        restore()
        au._release_all_locks = orig_release
    check(result["ok"] is True,
          f"a lock error surviving the passive phase must be resolved by an OS-verified "
          f"release round (got {result!r})")
    check(released["called"],
          "an OS-verified release attempt must actually have been made once the passive "
          "retries were exhausted")


# ============================================================================================
# Section C -- lock-recovery mechanics
# ============================================================================================

def section_c():
    print("\n--- Section C: lock-recovery mechanics ---")
    from primeatlas import app_update as au

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
          "the exact message Artur's machine hit on 2026-09-10, and misclassifying it would "
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

if __name__ == "__main__":
    section_a()
    section_a2()
    section_b()
    section_c()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All checks passed.")
