"""
test_installer_script.py -- static checks of installer/PrimeAtlasSetup.iss (the Inno Setup
bootstrapper that becomes PrimeAtlasSetup.exe). Inno's Pascal code can't run here, so this
pins the CONTRACT instead: the product decisions, the directory
layout other code depends on (app_update.git_executable() looks for <install>/git next to
<install>/app), and the measured constraints (Python 3.13, not 3.14: moderngl/glcontext
ship no 3.14 wheels). The real end-to-end check is a silent install of the built exe.

Usage:
    python unitTests/test_installer_script.py
"""
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
ISS_PATH = os.path.join(_REPO_ROOT, "installer", "PrimeAtlasSetup.iss")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def sections(text):
    """{lowercased section name: body text} of an .iss file."""
    out = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^\s*\[([A-Za-z]+)\]\s*$", line)
        if m:
            current = m.group(1).lower()
            out.setdefault(current, "")
            continue
        if current:
            out[current] += line + "\n"
    return out


def setup_directive(body, name):
    m = re.search(rf"^\s*{name}\s*=\s*(.+?)\s*$", body, re.MULTILINE | re.IGNORECASE)
    return m.group(1) if m else None


def main():
    check(os.path.isfile(ISS_PATH), "installer/PrimeAtlasSetup.iss exists")
    if not os.path.isfile(ISS_PATH):
        return
    with open(ISS_PATH, encoding="utf-8-sig") as f:
        text = f.read()
    sec = sections(text)
    setup = sec.get("setup", "")

    # A mangled "\a"/"\b"/"\v" escape once turned {sys}\attrib.exe into {sys}<BEL>ttrib.exe --
    # it still compiled, and the uninstaller's attrib call silently did nothing.
    control = [hex(ord(c)) for c in text if ord(c) < 32 and c not in "\r\n\t"]
    check(not control, f"no control characters in the script (found {control})")

    print("\n--- Setup directives ---")
    check(setup_directive(setup, "PrivilegesRequired") == "lowest",
          "PrivilegesRequired=lowest (no admin rights needed)")
    check(setup_directive(setup, "DefaultDirName") == r"{localappdata}\PrimeAtlas",
          r"default install dir is {localappdata}\PrimeAtlas")
    check(setup_directive(setup, "DisableDirPage") == "no",
          "directory page is ALWAYS shown")
    check(setup_directive(setup, "OutputBaseFilename") == "PrimeAtlasSetup",
          "output file is PrimeAtlasSetup.exe")
    check(re.fullmatch(r"\{\{[0-9A-F-]{36}\}", setup_directive(setup, "AppId") or "") is not None,
          "fixed AppId GUID (reinstall/uninstall must recognize the same app)")

    print("\n--- Shortcuts as two independent checkboxes ---")
    tasks = sec.get("tasks", "")
    icons = sec.get("icons", "")
    task_names = re.findall(r'Name:\s*"?(\w+)"?', tasks)
    check(len(task_names) == 2, f"exactly two tasks (desktop, Start menu) (got {task_names})")
    check("exclusive" not in tasks.lower(), "the two shortcut tasks are not mutually exclusive")
    check(r"{autodesktop}" in icons and r"{autoprograms}" in icons,
          "one shortcut on the desktop, one in the Start menu")
    for line in icons.splitlines():
        if line.strip() and not line.strip().startswith(";"):
            m = re.search(r'Tasks:\s*"?(\w+)"?', line)
            check(m is not None and m.group(1) in task_names,
                  f"every shortcut is gated by its own checkbox task: {line.strip()[:60]}")
            check(r"pythonw.exe" in line and "prime_atlas_v1.py" in line,
                  "shortcut runs pythonw.exe prime_atlas_v1.py (no console window)")

    print("\n--- Offline: pinned, bundled runtimes, no download/cmd.exe code ---")
    m = re.search(r'#define\s+PythonVersion\s+"(\d+)\.(\d+)\.(\d+)"', text)
    check(m is not None and (m.group(1), m.group(2)) == ("3", "13"),
          "private Python is pinned to 3.13.x (moderngl has no 3.14 wheels)")
    for name in ("PythonSha256", "MinGitSha256"):
        m = re.search(rf'#define\s+{name}\s+"([0-9a-f]+)"', text)
        check(m is not None and len(m.group(1)) == 64,
              f"{name} is a full 64-hex-digit SHA-256 (downloads are verified)")
    check("python.org/ftp/python/" in text and "git-for-windows/git/releases/download/" in text,
          "pinned sources are python.org and the official git-for-windows releases")
    code_lower = sec.get("code", "").lower()
    # Windows Defender flagged the first (downloader) build as Trojan:Win32/Bearfoos.B!ml --
    # an ML heuristic that keys on "new unsigned exe downloads files and runs a hidden
    # cmd.exe". The offline build removes both behaviors.
    check("createdownloadpage" not in code_lower and "downloadtemporaryfile" not in code_lower,
          "no download code in the installer itself (Python and MinGit are bundled)")
    check("{cmd}" not in code_lower and "cmd.exe" not in code_lower,
          "git/python are launched directly, never through a hidden cmd.exe")
    files = sec.get("files", "")
    check(r"vendor\python\*" in files and r"vendor\git\*" in files and "external" not in files,
          r"[Files] embeds installer\vendor\python and vendor\git (built by build_installer.py)")
    build_script = os.path.join(_REPO_ROOT, "installer", "build_installer.py")
    check(os.path.isfile(build_script), "installer/build_installer.py exists")
    if os.path.isfile(build_script):
        with open(build_script, encoding="utf-8") as f:
            build = f.read()
        check("sha256" in build and "PrimeAtlasSetup.iss" in build,
              "build_installer.py verifies SHA-256 and reads its pins from PrimeAtlasSetup.iss "
              "(one source of truth for versions/hashes)")

    print("\n--- Layout contract with app_update.git_executable() ---")
    check(r"{app}\python" in text and r"{app}\git" in text and r"{app}\app" in text,
          r"layout is {app}\python, {app}\git, {app}\app (the repo)")
    check(r"cmd\git.exe" in text, r"git is launched as {app}\git\cmd\git.exe")

    print("\n--- Post-install steps ---")
    code = sec.get("code", "")
    check("clone" in code and "pull --ff-only" in code,
          "fresh install clones, reinstall fast-forward-pulls (never overwrites local changes)")
    check("--only-binary=:all:" in code and "requirements.txt" in code,
          "pip installs requirements.txt with --only-binary=:all: (no compiler on user machines)")
    check("--user" not in code, "private Python installs into its own site-packages (no --user)")
    check("install.log" in code, "post-install output goes to an install.log for diagnosis")

    print("\n--- Only an empty/new folder or an earlier PrimeAtlas install is accepted ---")
    # Never install into a location that already holds something else --
    # the uninstaller deletes {app}\python and {app}\git wholesale, which would take a
    # user's own same-named folders with it.
    check(setup_directive(setup, "DirExistsWarning") == "no",
          "Inno's generic 'folder exists' prompt is off -- the precise check below replaces it")
    check("primeatlas-install.id" in code, "an install marker file identifies our own folders")
    check("DirIsEmpty(WizardDirValue)" in code,
          "wpSelectDir rejects a non-empty chosen folder that has no install marker")
    check("ssInstall" in code, "the marker is written at ssInstall, before any file is copied "
                               "(an interrupted install is still recognized as ours)")
    custom = sec.get("custommessages", "")
    check("polish.DirNotEmpty=" in custom and "english.DirNotEmpty=" in custom,
          "the rejection message exists in both languages")
    check("usPostUninstall" in code,
          "uninstall removes the marker only once nothing of ours is left (kept data keeps it, "
          "so reinstalling into the same folder to get the data back is allowed)")
    check("RenameFile" in code,
          "reinstall next to kept data parks CONSTELLATION_PORTAL aside for git clone, then "
          "moves it back")

    print("\n--- Uninstall keeps data unless asked ---")
    check("CONSTELLATION_PORTAL" in code and "MB_DEFBUTTON2" in code,
          "uninstall asks about CONSTELLATION_PORTAL with 'No' (keep) as the default button")
    uninstall_delete = "\n".join(line for line in sec.get("uninstalldelete", "").splitlines()
                                 if not line.strip().startswith(";"))
    check(r"{app}\app" not in uninstall_delete,
          r"[UninstallDelete] never blindly removes {app}\app (it holds the data)")
    run = sec.get("run", "")
    check("postinstall" in run and "skipifsilent" in run,
          "optional 'Launch PrimeAtlas' checkbox on the last page, skipped in silent mode")
    readme = [l for l in run.splitlines() if "#readme" in l]
    check(len(readme) == 1 and "shellexec" in readme[0] and "postinstall" in readme[0],
          "a second last-page checkbox opens the README (GitHub page: a fresh Windows has no "
          "app associated with .md files)")

    print("\n--- Look ---")
    # The default (non-custom-styled) modern wizard clips the checkbox glyphs; the
    # windows11 custom style draws its own controls.
    style = (setup_directive(setup, "WizardStyle") or "").lower().split()
    check("windows11" in style and "dynamic" in style,
          f"WizardStyle uses the windows11 custom style, following light/dark mode (got {style})")
    # Even the windows11 style clips the right edge of each checkbox square above 100%
    # display scaling (e.g. 125%) -- the label is drawn over the DPI-scaled glyph. Both
    # checkbox lists (Tasks page: shortcuts; last page: Run/README) must widen their
    # glyph-to-label gap with DPI.
    init = re.search(r"procedure InitializeWizard;.*?^end;", code, re.DOTALL | re.IGNORECASE | re.MULTILINE)
    init_body = init.group(0) if init else ""
    for list_name in ("TasksList", "RunList"):
        check(re.search(r"WizardForm\." + list_name + r"\.Offset\s*:=.*ScaleX\(", init_body) is not None,
              f"InitializeWizard widens WizardForm.{list_name}.Offset by a DPI-scaled amount")


    print("\n--- Release 1.0.0: one version source, licenses, notes ---")
    version_src = open(os.path.join(_REPO_ROOT, "primeatlas", "core", "version.py"),
                       encoding="utf-8").read()
    m = re.search(r'^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"\s*$', version_src, re.MULTILINE)
    check(m is not None, "primeatlas/core/version.py defines APP_VERSION as X.Y.Z")
    check(re.search(r'^#define\s+AppVersion\s+"', text, re.MULTILINE) is None
          and "#ifndef AppVersion" in text and "#error" in text,
          "the .iss never hard-codes AppVersion; built without /DAppVersion it refuses to compile")
    build = open(os.path.join(_REPO_ROOT, "installer", "build_installer.py"), encoding="utf-8").read()
    check("/DAppVersion=" in build and "version.py" in build,
          "build_installer.py passes /DAppVersion read from primeatlas/core/version.py")
    main_src = open(os.path.join(_REPO_ROOT, "prime_atlas_v1.py"), encoding="utf-8").read()
    check("APP_VERSION" in main_src, "the main window shows the version (title bar)")

    license_path = os.path.join(_REPO_ROOT, "LICENSE.md")
    check(os.path.isfile(license_path), "LICENSE.md exists at the repo root")
    if os.path.isfile(license_path):
        lic = open(license_path, encoding="utf-8").read()
        check("# PolyForm Noncommercial License 1.0.0" in lic and "## Definitions" in lic,
              "LICENSE.md holds the full PolyForm Noncommercial 1.0.0 text")
        check(re.search(r"^Required Notice: Copyright .+", lic, re.MULTILINE) is not None,
              "LICENSE.md carries the licensor's 'Required Notice:' line")
    notice_path = os.path.join(_REPO_ROOT, "NOTICE.md")
    check(os.path.isfile(notice_path), "NOTICE.md exists (README points to it)")
    if os.path.isfile(notice_path):
        notice = open(notice_path, encoding="utf-8").read()
        for needle in ("primesieve", "primecount", "CUDASieve", "Python Software Foundation",
                       "MinGit", "v2.56.0.windows.1", "GPL"):
            check(needle in notice, f"NOTICE.md mentions {needle}")
    readme = open(os.path.join(_REPO_ROOT, "README.md"), encoding="utf-8").read()
    license_section = readme[readme.find("\n## License"):]
    check("`License`" not in license_section and "LICENSE.md" in license_section,
          "README's License section points to the real LICENSE.md file")

    notes_path = os.path.join(_REPO_ROOT, "installer", "release_notes.md")
    check(os.path.isfile(notes_path), "installer/release_notes.md exists")
    if os.path.isfile(notes_path):
        notes = open(notes_path, encoding="utf-8").read()
        pl, en = notes.find("## Polski"), notes.find("## English")
        # Content is English; Polish is only the secondary translation below it.
        check(pl != -1 and en != -1 and en < pl, "release notes: English first, Polish below")
    wf = open(os.path.join(_REPO_ROOT, ".github", "workflows", "installer.yml"),
              encoding="utf-8").read()
    check("release_notes.md" in wf, "the workflow publishes installer/release_notes.md")
    check("--prerelease" in wf, "a tag with a suffix (v1.0.0-rc1) becomes a pre-release")
    check("APP_VERSION" in wf or "version.py" in wf,
          "the workflow refuses a tag that does not match APP_VERSION")

    print("\n--- Languages ---")
    langs = sec.get("languages", "")
    check("Polish.isl" in langs and "Default.isl" in langs, "Polish and English UI")


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
