"""
version.py -- the single source of PrimeAtlas's version number.

Shown in the main window's title bar and the About tab, and read (by regex, without
importing the package, which needs numpy) by installer/build_installer.py, which passes it
to Inno Setup as /DAppVersion, and by .github/workflows/installer.yml, which refuses to
publish a release whose tag doesn't match it. Bump it here, add the CHANGELOG.md entry,
then tag vX.Y.Z (or vX.Y.Z-rc1 for a pre-release) to publish.

Every copy of the app is a git checkout that Settings > Updates fast-forwards along the
default branch, so the version number alone does not identify the running code;
version_label() adds the checked-out commit. git_commit() reads it from the files under
.git instead of running git, which is not on PATH in an installed copy.
"""
import os
import re

APP_VERSION = "1.1.0"

_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _git_dir(repo_root):
    """The git directory of `repo_root`: .git itself, or the directory a .git file (a
    linked worktree or submodule) points to."""
    dot_git = os.path.join(repo_root, ".git")
    if os.path.isdir(dot_git):
        return dot_git
    text = _read(dot_git)
    if text and text.startswith("gitdir:"):
        path = text[len("gitdir:"):].strip()
        return path if os.path.isabs(path) else os.path.join(repo_root, path)
    return None


def _resolve_ref(git_dir, ref):
    loose = _read(os.path.join(git_dir, *ref.split("/")))
    if loose and _SHA_RE.fullmatch(loose):
        return loose
    packed = _read(os.path.join(git_dir, "packed-refs")) or ""
    for line in packed.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref and _SHA_RE.fullmatch(parts[0]):
            return parts[0]
    return None


def git_commit(repo_root):
    """Full SHA of the commit checked out in `repo_root`, or None without a readable .git."""
    git_dir = _git_dir(repo_root)
    if git_dir is None:
        return None
    head = _read(os.path.join(git_dir, "HEAD"))
    if not head:
        return None
    if _SHA_RE.fullmatch(head):
        return head
    if head.startswith("ref:"):
        return _resolve_ref(git_dir, head[len("ref:"):].strip())
    return None


def version_label(repo_root):
    """"X.Y.Z (abcdef1)" with the checked-out commit, the bare APP_VERSION without one."""
    commit = git_commit(repo_root)
    return f"{APP_VERSION} ({commit[:7]})" if commit else APP_VERSION
