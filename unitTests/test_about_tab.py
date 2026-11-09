"""
test_about_tab.py -- the app's version label and the About tab.

A. primeatlas/core/version.py: parse_changelog() takes the release from the newest
   "## X.Y.Z — date" heading and the numbered entries (title, English, Polish, wrapped lines
   joined) of the "## Since X.Y.Z" section only; app_version() is "X.Y.Z+N", "X.Y.Z" with no
   entries and "unknown" without CHANGELOG.md; git_commit(root) reads the checked-out commit
   straight from .git (loose ref, packed ref, detached HEAD, a .git file pointing to the git
   dir; in a linked worktree the branch refs come from the main git dir named by its
   `commondir` file) and returns None without a usable .git; version_label(root) is "X.Y.Z+N (abcdef1)"
   with a commit and the bare app_version() without one; on this repo it matches
   `git rev-parse --short=7 HEAD`.
B. CHANGELOG.md: the release is the newest vX.Y.Z tag (pre-release tags aside); the
   "## Since" section names it; its entries are numbered +1..+N, each with English before
   Polish; N is the first-parent merges since the tag, plus one on a branch whose HEAD is
   not a merge (the branch's own entry); every section has English before Polish.
C. The app: the title bar shows version_label; About is the last main tab; it shows the
   version, the visualization summary, the author's name, e-mail, GitHub and license links
   (each opening the right URL) and the related projects; the changes since the release are
   listed newest first in the UI language with a link to the full CHANGELOG.md; NOTICE.md
   is shown read-only; a copy glyph next to the version puts the shown version line on the
   clipboard; every about.* key exists in both locales.

Usage:
    python unitTests/test_about_tab.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core import version  # noqa: E402

failures = []

SHA_A = "0123456789abcdef0123456789abcdef01234567"
SHA_B = "fedcba9876543210fedcba9876543210fedcba98"


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _fake_repo(head, loose=None, packed=None):
    root = tempfile.mkdtemp(prefix="about_version_test_")
    git = os.path.join(root, ".git")
    _write(os.path.join(git, "HEAD"), head)
    for ref, sha in (loose or {}).items():
        _write(os.path.join(git, *ref.split("/")), sha + "\n")
    if packed:
        lines = ["# pack-refs with: peeled fully-peeled sorted"]
        lines += [f"{sha} {ref}" for ref, sha in packed.items()]
        _write(os.path.join(git, "packed-refs"), "\n".join(lines) + "\n")
    return root


SAMPLE_RELEASE = """## 2.3.0 — 2027-01-02

### +1 — Old entry of the release

- English: Old.
- Polski: Stare.

## 2.2.0 — 2026-12-01
"""

SAMPLE_CHANGELOG = """# Changelog

Intro text with ## inside a line.

## Since 2.3.0

### +1 — First change (#40)

- English: One line
  wrapped.
- Polski: Jedna linia
  zawinięta.

### +2 — Second change

- English: Two.
- Polski: Dwa.

""" + SAMPLE_RELEASE


def _test_changelog_parsing():
    print("\n--- A. version.py: CHANGELOG.md parsing ---")
    log = version.parse_changelog(SAMPLE_CHANGELOG)
    check(log.release == "2.3.0" and log.since == "2.3.0",
          f"release and Since heading are read ({log.release}, {log.since})")
    check([e.number for e in log.entries] == [1, 2],
          f"only the Since section's entries count ({[e.number for e in log.entries]})")
    first = log.entries[0] if log.entries else None
    check(first is not None and first.title == "First change (#40)"
          and first.english == "One line wrapped." and first.polish == "Jedna linia zawinięta.",
          f"an entry's title and wrapped English/Polish text are read ({first})")
    released = version.parse_changelog("# Changelog\n\n" + SAMPLE_RELEASE)
    check(released.release == "2.3.0" and released.since is None and not released.entries,
          "right after a release there is no Since section and no entries")
    root = tempfile.mkdtemp(prefix="about_version_test_")
    check(version.app_version(root) == version.UNKNOWN_VERSION,
          "app_version() without CHANGELOG.md is 'unknown'")
    _write(os.path.join(root, "CHANGELOG.md"), SAMPLE_CHANGELOG)
    check(version.app_version(root) == "2.3.0+2",
          f"app_version() is X.Y.Z+N ({version.app_version(root)})")
    _write(os.path.join(root, "CHANGELOG.md"), "# Changelog\n\n" + SAMPLE_RELEASE)
    check(version.app_version(root) == "2.3.0", "app_version() with no entries is X.Y.Z")


def _test_version():
    print("\n--- A. version.py: commit label ---")
    app_version = version.app_version(_REPO_ROOT)
    check(re.fullmatch(r"\d+\.\d+\.\d+(\+\d+)?", app_version) is not None,
          f"this repo's app_version() is X.Y.Z or X.Y.Z+N ({app_version})")
    git_commit = getattr(version, "git_commit", None)
    version_label = getattr(version, "version_label", None)
    check(callable(git_commit) and callable(version_label),
          "version.py has git_commit() and version_label()")
    if not (callable(git_commit) and callable(version_label)):
        return
    loose = _fake_repo("ref: refs/heads/main\n", loose={"refs/heads/main": SHA_A})
    check(git_commit(loose) == SHA_A, "a loose branch ref is read")
    packed = _fake_repo("ref: refs/heads/main\n",
                        packed={"refs/heads/main": SHA_B, "refs/tags/v1": SHA_A})
    check(git_commit(packed) == SHA_B, "a packed branch ref is read")
    both = _fake_repo("ref: refs/heads/main\n", loose={"refs/heads/main": SHA_A},
                      packed={"refs/heads/main": SHA_B})
    check(git_commit(both) == SHA_A, "a loose ref wins over a stale packed one")
    detached = _fake_repo(SHA_B + "\n")
    check(git_commit(detached) == SHA_B, "a detached HEAD is read")
    linked = tempfile.mkdtemp(prefix="about_version_test_")
    _write(os.path.join(linked, ".git"), f"gitdir: {os.path.join(loose, '.git')}\n")
    check(git_commit(linked) == SHA_A, "a .git file pointing to the git dir is followed")
    worktree = tempfile.mkdtemp(prefix="about_version_test_")
    wt_git = os.path.join(loose, ".git", "worktrees", "wt")
    _write(os.path.join(wt_git, "HEAD"), "ref: refs/heads/main\n")
    _write(os.path.join(wt_git, "commondir"), "../..\n")
    _write(os.path.join(worktree, ".git"), f"gitdir: {wt_git}\n")
    check(git_commit(worktree) == SHA_A, "a linked worktree reads its branch from commondir")
    wt_packed = os.path.join(packed, ".git", "worktrees", "wt")
    _write(os.path.join(wt_packed, "HEAD"), "ref: refs/heads/main\n")
    _write(os.path.join(wt_packed, "commondir"), os.path.join(packed, ".git") + "\n")
    linked_packed = tempfile.mkdtemp(prefix="about_version_test_")
    _write(os.path.join(linked_packed, ".git"), f"gitdir: {wt_packed}\n")
    check(git_commit(linked_packed) == SHA_B,
          "a linked worktree reads a packed ref through an absolute commondir")
    wt_detached = os.path.join(loose, ".git", "worktrees", "det")
    _write(os.path.join(wt_detached, "HEAD"), SHA_B + "\n")
    _write(os.path.join(wt_detached, "commondir"), "../..\n")
    linked_detached = tempfile.mkdtemp(prefix="about_version_test_")
    _write(os.path.join(linked_detached, ".git"), f"gitdir: {wt_detached}\n")
    check(git_commit(linked_detached) == SHA_B, "a detached linked worktree reads its own HEAD")
    check(git_commit(tempfile.mkdtemp(prefix="about_version_test_")) is None, "no .git -> None")
    check(git_commit(_fake_repo("ref: refs/heads/gone\n")) is None, "a missing ref -> None")
    check(git_commit(_fake_repo("garbage\n")) is None, "an unreadable HEAD -> None")
    _write(os.path.join(loose, "CHANGELOG.md"), SAMPLE_CHANGELOG)
    check(version_label(loose) == f"2.3.0+2 ({SHA_A[:7]})",
          f"label with a commit ({version_label(loose)})")
    bare = tempfile.mkdtemp(prefix="about_version_test_")
    _write(os.path.join(bare, "CHANGELOG.md"), SAMPLE_CHANGELOG)
    check(version_label(bare) == "2.3.0+2", "label without a commit is the bare version")
    try:
        real = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=_REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        real = None
    if real:
        check(version_label(_REPO_ROOT) == f"{app_version} ({real})",
              f"label on this repo matches git ({version_label(_REPO_ROOT)})")


def _test_changelog():
    print("\n--- B. CHANGELOG.md ---")
    path = os.path.join(_REPO_ROOT, "CHANGELOG.md")
    check(os.path.isfile(path), "CHANGELOG.md exists")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    releases = re.findall(r"^## (\d+\.\d+\.\d+) — \d{4}-\d{2}-\d{2}$", text, re.MULTILINE)
    check("1.0.0" in releases, "the 1.0.0 release is kept")
    for body in re.split(r"^## .*$", text, flags=re.MULTILINE)[1:]:
        en = min((i for i in (body.find("### English"), body.find("- English:")) if i >= 0),
                 default=-1)
        pl = max(body.find("### Polski"), body.find("- Polski:"))
        check(0 <= en < pl, "each section has English before Polish")
    log = version.parse_changelog(text)
    check(releases and log.release == releases[0],
          f"the release is the newest '## X.Y.Z — date' heading ({log.release})")
    numbers = [e.number for e in log.entries]
    check(numbers == list(range(1, len(numbers) + 1)),
          f"entries are numbered +1..+N in order ({numbers})")
    for e in log.entries:
        check(e.title and e.english and e.polish, f"+{e.number} has a title, English and Polish")
    if log.entries:
        check(log.since == log.release, f"the Since section names the release ({log.since})")

    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=_REPO_ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "--exclude", "*-*")
    if not tag:
        print("SKIPPED (no git or no release tag): merge counter")
        return
    check(tag == f"v{log.release}", f"the release is the newest release tag ({tag})")
    merges = int(git("rev-list", "--first-parent", "--merges", "--count", f"{tag}..HEAD"))
    head_is_merge = len(git("rev-list", "--parents", "-n", "1", "HEAD").split()) > 2
    expected = merges + (0 if head_is_merge else 1)
    check(len(log.entries) == expected,
          f"entries since {tag} match the merges ({len(log.entries)} entries, {merges} merges, "
          f"HEAD {'is' if head_is_merge else 'is not'} a merge, so {expected} expected)")


def _all_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _all_widgets(child)


def _test_app():
    print("\n--- C. About tab ---")
    import tkinter as tk
    import tkinter.messagebox as messagebox
    import webbrowser
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    opened = []
    webbrowser.open = lambda url, *a, **k: opened.append(url)
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    try:
        app.update()
        label = version.version_label(_REPO_ROOT)
        check(label in app.title(), f"title shows the version label ({app.title()!r})")
        notebook = app.main_notebook
        tabs = notebook.tabs()
        about = getattr(app, "about_tab_widget", None)
        check(about is not None, "the app has an About tab widget")
        if about is None:
            return
        last_text = notebook.tab(tabs[-1], "text")
        check(last_text == about.T("tabs.about") != "tabs.about",
              f"About is the last main tab ({last_text!r})")
        texts = []
        for w in _all_widgets(about):
            try:
                texts.append(str(w.cget("text")))
            except tk.TclError:
                pass
        joined = "\n".join(texts)
        from primeatlas.about import about_tab as about_module
        for needle, what in ((label, "version label"),
                             (about_module.AUTHOR_NAME, "author name"),
                             (about_module.AUTHOR_EMAIL, "e-mail"),
                             (about_module.REPO_URL, "GitHub link"),
                             (about.T("about.visualization"), "visualization summary"),
                             (about.T("about.related_projects"), "related projects")):
            check(needle in joined, f"About shows the {what}")
        changes = about.changes_text.get("1.0", "end").strip()
        log = version.read_changelog(_REPO_ROOT)
        if log.entries:
            newest = log.entries[-1]
            text = newest.polish if about.T.language == "pl" else newest.english
            check(changes.startswith(f"+{newest.number} — {newest.title}\n{text}"),
                  "the changes box starts with the newest entry in the UI language")
            check(changes.count("\n\n+") == len(log.entries) - 1,
                  "the changes box lists every entry since the release")
        check(str(about.changes_text.cget("state")) == "disabled", "the changes box is read-only")
        frames = [str(w.cget("text")) for w in _all_widgets(about)
                  if w.winfo_class() == "TLabelframe"]
        check(any(log.release in f for f in frames), f"the changes frame names the release ({frames})")
        for key, url in (("email", f"mailto:{about_module.AUTHOR_EMAIL}"),
                         ("repo", about_module.REPO_URL),
                         ("license", about_module.LICENSE_URL),
                         ("changelog", about_module.CHANGELOG_URL)):
            link = about.links.get(key)
            check(link is not None, f"{key} link exists")
            if link is not None:
                link.event_generate("<Button-1>")
                app.update()
                check(opened and opened[-1] == url, f"{key} link opens {url} (got {opened[-1:]})")
        with open(os.path.join(_REPO_ROOT, "NOTICE.md"), encoding="utf-8") as f:
            notice = f.read().strip()
        shown = about.notice_text.get("1.0", "end").strip()
        check(shown == notice, "NOTICE.md is shown in full")
        check(str(about.notice_text.cget("state")) == "disabled", "NOTICE.md is read-only")
        copy = getattr(about, "version_copy", None)
        check(copy is not None, "a copy glyph sits next to the version")
        if copy is not None:
            check(str(copy.cget("text")) == about_module.COPY_GLYPH and copy.winfo_class() == "TLabel",
                  "it is a small glyph label, not a button")
            app.clipboard_clear()
            app.clipboard_append("old")
            copy.event_generate("<Button-1>")
            app.update()
            want = about.T("about.version", version=label)
            check(app.clipboard_get() == want,
                  f"Copy puts the version line on the clipboard ({app.clipboard_get()!r})")
    finally:
        app.destroy()
    locales = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
    keys = {}
    for lang in ("en", "pl"):
        with open(os.path.join(locales, f"strings_{lang}.json"), encoding="utf-8") as f:
            keys[lang] = {k for k in json.load(f) if k.startswith("about.") or k == "tabs.about"}
    check(keys["en"] and keys["en"] == keys["pl"],
          f"about.* keys match in both locales ({sorted(keys['en'] ^ keys['pl'])})")


def main():
    _test_changelog_parsing()
    _test_version()
    _test_changelog()
    _test_app()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
