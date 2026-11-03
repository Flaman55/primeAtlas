"""
test_app_sandbox.py -- GUI tests never run the app against the user's real storage.

A. isolate_app() (app_sandbox.py): app_dynamic.PORTAL_FOLDER and
   APP_SETTINGS.storage_path both name a new, empty temp folder, and
   primeatlas/locales/app_settings.json is left byte-for-byte unchanged.
   isolate_app(portal) points both at the test's own seeded folder and keeps its files.
B. Every unitTests/test_*.py that constructs the full app (prime_atlas_v2._build_gui())
   calls isolate_app(...) on a code line before the first construction (the app scans
   and recovers storage while it is built).

Usage:
    python unitTests/test_app_sandbox.py
"""
import glob
import os
import re
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _test_isolate():
    print("\n--- A. isolate_app() ---")
    from app_sandbox import isolate_app
    from primeatlas.core import app_settings
    settings_file = os.path.join(app_settings.LOCALES_DIR, app_settings.SETTINGS_FILENAME)
    before = _read(settings_file)
    prime_atlas_v2, portal = isolate_app()
    from primeatlas.app import app_dynamic
    temp_root = os.path.realpath(tempfile.gettempdir())
    check(os.path.realpath(portal).startswith(temp_root), f"portal is under the temp folder ({portal})")
    check(os.path.isdir(portal) and not os.listdir(portal), "portal is a new, empty folder")
    check(app_dynamic.PORTAL_FOLDER == portal, "PORTAL_FOLDER names the portal")
    check(os.path.realpath(app_dynamic.APP_SETTINGS.storage_path) == os.path.realpath(portal),
          "APP_SETTINGS.storage_path names the portal")
    app_dynamic.APP_SETTINGS.save()
    check(_read(settings_file) == before, "app_settings.json is unchanged")
    seeded = tempfile.mkdtemp(prefix="app_sandbox_seeded_")
    try:
        marker = os.path.join(seeded, "benchmark_log.csv")
        with open(marker, "w", encoding="utf-8") as f:
            f.write("run_timestamp_utc\n")
        _, given = isolate_app(seeded)
        check(given == seeded and app_dynamic.PORTAL_FOLDER == seeded,
              "isolate_app(portal) uses the given folder")
        check(os.path.isfile(marker), "the given folder keeps its seeded files")
    finally:
        shutil.rmtree(seeded, ignore_errors=True)


def _test_sources():
    print("\n--- B. app-building tests are isolated ---")
    for path in sorted(glob.glob(os.path.join(_SCRIPT_DIR, "test_*.py"))):
        with open(path, encoding="utf-8") as f:
            source = f.read()
        build = re.search(r"^[ \t]+[^#\n]*prime_atlas_v2\._build_gui\(\)", source, re.M)
        if build is None:
            continue
        name = os.path.basename(path)
        isolate = re.search(r"^[ \t]+[^#\n]*\bisolate_app\(", source, re.M)
        check(isolate is not None and isolate.start() < build.start(),
              f"{name} calls isolate_app() before building the app")


def main():
    _test_isolate()
    _test_sources()
    print()
    print("=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for message in failures:
            print(f"  FAIL: {message}")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
