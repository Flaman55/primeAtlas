"""
test_about_tab.py -- the app's version label and the About tab.

A. primeatlas/core/version.py: APP_VERSION is X.Y.Z; git_commit(root) reads the checked-out
   commit straight from .git (loose ref, packed ref, detached HEAD, a .git file pointing to
   the git dir) and returns None without a usable .git; version_label(root) is
   "X.Y.Z (abcdef1)" with a commit and "X.Y.Z" without one; on this repo it matches
   `git rev-parse --short=7 HEAD`.
B. CHANGELOG.md: its newest entry is APP_VERSION, every entry has an English section before
   a Polish one.
C. The app: the title bar shows version_label; About is the last main tab; it shows the
   version, the visualization summary, the author's name, e-mail, GitHub and license links (each opening the right
   URL) and the related projects; NOTICE.md is shown read-only; every about.* key exists
   in both locales.

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


def _test_version():
    print("\n--- A. version.py ---")
    check(re.fullmatch(r"\d+\.\d+\.\d+", version.APP_VERSION) is not None,
          f"APP_VERSION is X.Y.Z ({version.APP_VERSION})")
    check(version.APP_VERSION == "1.1.0", "APP_VERSION is bumped to 1.1.0")
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
    check(git_commit(tempfile.mkdtemp(prefix="about_version_test_")) is None, "no .git -> None")
    check(git_commit(_fake_repo("ref: refs/heads/gone\n")) is None, "a missing ref -> None")
    check(git_commit(_fake_repo("garbage\n")) is None, "an unreadable HEAD -> None")
    check(version_label(loose) == f"{version.APP_VERSION} ({SHA_A[:7]})",
          f"label with a commit ({version_label(loose)})")
    check(version_label(tempfile.mkdtemp(prefix="about_version_test_")) == version.APP_VERSION,
          "label without a commit is the bare version")
    try:
        real = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=_REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        real = None
    if real:
        check(version_label(_REPO_ROOT) == f"{version.APP_VERSION} ({real})",
              f"label on this repo matches git ({version_label(_REPO_ROOT)})")


def _test_changelog():
    print("\n--- B. CHANGELOG.md ---")
    path = os.path.join(_REPO_ROOT, "CHANGELOG.md")
    check(os.path.isfile(path), "CHANGELOG.md exists")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    entries = re.findall(r"^## (\d+\.\d+\.\d+)\b", text, re.MULTILINE)
    check(entries and entries[0] == version.APP_VERSION,
          f"the newest entry is APP_VERSION (entries {entries})")
    check("1.0.0" in entries, "the 1.0.0 entry is kept")
    for body in re.split(r"^## \d+\.\d+\.\d+.*$", text, flags=re.MULTILINE)[1:]:
        en, pl = body.find("### English"), body.find("### Polski")
        check(0 <= en < pl, "each entry has English before Polish")


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
    import prime_atlas_v2
    sys.argv = ["prime_atlas_v2.py"]
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
        for key, url in (("email", f"mailto:{about_module.AUTHOR_EMAIL}"),
                         ("repo", about_module.REPO_URL),
                         ("license", about_module.LICENSE_URL)):
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
