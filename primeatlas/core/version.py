"""
version.py -- PrimeAtlas's version, read from CHANGELOG.md, its single source.

The release number is the newest "## X.Y.Z — date" heading of CHANGELOG.md. Every merge
into main after that release appends one numbered entry ("### +N — title") to the
"## Since X.Y.Z" section above it, so the running code is release X.Y.Z plus its N merges:
app_version() is "X.Y.Z+N", or "X.Y.Z" right after a release. unitTests/test_about_tab.py
keeps N equal to the first-parent merges on main since the tag vX.Y.Z.

Shown in the main window's title bar and the About tab, and read (by regex, without
importing the package, which needs numpy) by installer/build_installer.py, which passes the
release number to Inno Setup as /DAppVersion, and by .github/workflows/installer.yml, which
refuses to publish a release whose tag doesn't match it. A release renames "## Since X.Y.Z"
to "## A.B.C — date", then tags vA.B.C (or vA.B.C-rc1 for a pre-release).

Every copy of the app is a git checkout that Settings > Updates fast-forwards along the
default branch, and its CHANGELOG.md moves with it; version_label() adds the checked-out
commit. git_commit() reads it from the files under .git instead of running git, which is
not on PATH in an installed copy; in a linked worktree the branch refs come from the main
git dir its `commondir` file names.
"""
import os
import re
from dataclasses import dataclass

CHANGELOG_NAME = "CHANGELOG.md"
UNKNOWN_VERSION = "unknown"

_SHA_RE = re.compile(r"[0-9a-f]{40}")
RELEASE_HEADING_RE = re.compile(r"^## (\d+\.\d+\.\d+) — ", re.MULTILINE)
_SINCE_HEADING_RE = re.compile(r"^## Since (\d+\.\d+\.\d+)[ \t]*$", re.MULTILINE)
_ENTRY_HEADING_RE = re.compile(r"^### \+(\d+) — (.+?)[ \t]*$", re.MULTILINE)
_ENTRY_LANG_RE = re.compile(r"^- (English|Polski): ", re.MULTILINE)


@dataclass(frozen=True)
class ChangeEntry:
    number: int
    title: str
    english: str
    polish: str


@dataclass(frozen=True)
class Changelog:
    release: str            # newest released X.Y.Z, UNKNOWN_VERSION without one
    since: str              # X.Y.Z of the "## Since" heading, None without the section
    entries: tuple          # ChangeEntry, in file order (oldest first)


def _join_lines(block):
    return " ".join(line.strip() for line in block.strip().splitlines())


def _parse_entry(number, title, body):
    texts = {}
    marks = list(_ENTRY_LANG_RE.finditer(body))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        texts[mark.group(1)] = _join_lines(body[mark.end():end])
    return ChangeEntry(int(number), title, texts.get("English", ""), texts.get("Polski", ""))


def parse_changelog(text):
    """Changelog of CHANGELOG.md's text: the newest release and the entries of the
    "## Since" section, which ends at the next "## " heading."""
    release = RELEASE_HEADING_RE.search(text)
    since = _SINCE_HEADING_RE.search(text)
    entries = []
    if since:
        nxt = re.search(r"^## ", text[since.end():], re.MULTILINE)
        section = text[since.end():since.end() + nxt.start()] if nxt else text[since.end():]
        heads = list(_ENTRY_HEADING_RE.finditer(section))
        for i, head in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(section)
            entries.append(_parse_entry(head.group(1), head.group(2),
                                        section[head.end():end]))
    return Changelog(release.group(1) if release else UNKNOWN_VERSION,
                     since.group(1) if since else None, tuple(entries))


def read_changelog(repo_root):
    """Changelog of repo_root/CHANGELOG.md; an empty one (UNKNOWN_VERSION) without the file."""
    return parse_changelog(_read(os.path.join(repo_root, CHANGELOG_NAME)) or "")


def app_version(repo_root):
    """"X.Y.Z+N" with N merges since release X.Y.Z, "X.Y.Z" with none."""
    log = read_changelog(repo_root)
    return f"{log.release}+{len(log.entries)}" if log.entries else log.release


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


def _common_dir(git_dir):
    """The directory holding the shared refs: the one a linked worktree's `commondir` file
    names (relative to git_dir or absolute), git_dir itself otherwise."""
    common = _read(os.path.join(git_dir, "commondir"))
    if not common:
        return git_dir
    return os.path.normpath(common if os.path.isabs(common) else os.path.join(git_dir, common))


def _resolve_ref(git_dir, ref):
    """A loose ref in git_dir (a worktree's own refs) or the common dir, then packed-refs of
    the common dir."""
    common = _common_dir(git_dir)
    for directory in dict.fromkeys((git_dir, common)):
        loose = _read(os.path.join(directory, *ref.split("/")))
        if loose and _SHA_RE.fullmatch(loose):
            return loose
    packed = _read(os.path.join(common, "packed-refs")) or ""
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
    """"X.Y.Z+N (abcdef1)" with the checked-out commit, the bare app_version() without one."""
    version = app_version(repo_root)
    commit = git_commit(repo_root)
    return f"{version} ({commit[:7]})" if commit else version
