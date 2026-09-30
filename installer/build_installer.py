"""
build_installer.py -- builds installer/Output/PrimeAtlasSetup.exe, the OFFLINE Windows
installer: the pinned CPython and MinGit runtimes are bundled inside the exe instead of being
downloaded by it.

Why offline: the first (downloader) build was quarantined by Windows Defender as
Trojan:Win32/Bearfoos.B!ml -- an ML heuristic that keys on a new unsigned exe downloading
files and running a hidden cmd.exe. Bundling removes both behaviors; at install time only
the (signed) git.exe and python.exe touch the network, for `git clone` and `pip install`.

Steps:
  1. read the pinned versions/URLs/SHA-256 hashes from PrimeAtlasSetup.iss (#define lines --
     the single source of truth, also checked by unitTests/test_installer_script.py),
  2. download each ZIP into installer/vendor/ unless an already-downloaded copy has the
     right hash, verify sha256, refuse on mismatch,
  3. extract to installer/vendor/python and installer/vendor/git (fresh every build),
  4. run ISCC.exe (Inno Setup 6) on the script.

Usage (Windows, from the repo root or anywhere):
    python installer/build_installer.py [--iscc PATH_TO_ISCC.exe]
"""
import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

INSTALLER_DIR = os.path.dirname(os.path.abspath(__file__))
ISS_PATH = os.path.join(INSTALLER_DIR, "PrimeAtlasSetup.iss")
VENDOR_DIR = os.path.join(INSTALLER_DIR, "vendor")

ISCC_CANDIDATES = (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
    os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
)


def read_defines(iss_text):
    """#define NAME "value" pairs, with ISPP string concatenation (+) of earlier defines
    and literals resolved -- enough for the URL defines in PrimeAtlasSetup.iss."""
    defines = {}
    for m in re.finditer(r'^#define\s+(\w+)\s+(.+?)\s*$', iss_text, re.MULTILINE):
        parts = [p.strip() for p in m.group(2).split("+")]
        value = ""
        for part in parts:
            if part.startswith('"') and part.endswith('"'):
                value += part[1:-1]
            else:
                value += defines[part]
        defines[m.group(1)] = value
    return defines


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_verified(url, expected_sha256, dest):
    if os.path.isfile(dest) and sha256_of(dest) == expected_sha256:
        print(f"cached  {os.path.basename(dest)}")
        return
    print(f"download {url}")
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    actual = sha256_of(tmp)
    if actual != expected_sha256:
        os.remove(tmp)
        sys.exit(f"SHA-256 mismatch for {url}\n  expected {expected_sha256}\n  got      {actual}")
    os.replace(tmp, dest)


def _make_writable_and_retry(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def extract_fresh(zip_path, expected_sha256, target):
    """Extracts zip_path into an empty target. Skipped when target already holds an
    extraction of this exact ZIP (stamp file) -- re-deleting thousands of files on every
    build is slow, and on a OneDrive-synced checkout can hit transient access-denied."""
    stamp = os.path.join(target, ".extracted-from-sha256")
    try:
        with open(stamp, encoding="ascii") as f:
            if f.read().strip() == expected_sha256:
                print(f"cached  {os.path.relpath(target, INSTALLER_DIR)}")
                return
    except OSError:
        pass
    if os.path.isdir(target):
        shutil.rmtree(target, onerror=_make_writable_and_retry)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(target)
    with open(stamp, "w", encoding="ascii") as f:
        f.write(expected_sha256)
    print(f"extract {os.path.basename(zip_path)} -> {os.path.relpath(target, INSTALLER_DIR)}")


def find_iscc(explicit):
    for candidate in ([explicit] if explicit else []) + list(ISCC_CANDIDATES):
        if candidate and os.path.isfile(candidate):
            return candidate
    found = shutil.which("ISCC")
    if found:
        return found
    sys.exit("ISCC.exe (Inno Setup 6) not found -- install it (winget install "
             "JRSoftware.InnoSetup) or pass --iscc")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--iscc", help="path to ISCC.exe")
    args = parser.parse_args()

    with open(ISS_PATH, encoding="utf-8-sig") as f:
        d = read_defines(f.read())
    os.makedirs(VENDOR_DIR, exist_ok=True)
    runtimes = (
        (d["PythonUrl"], d["PythonSha256"], f"python-{d['PythonVersion']}-amd64.zip", "python"),
        (d["MinGitUrl"], d["MinGitSha256"], f"MinGit-{d['MinGitVersion']}-64-bit.zip", "git"),
    )
    for url, sha, zip_name, subdir in runtimes:
        zip_path = os.path.join(VENDOR_DIR, zip_name)
        fetch_verified(url, sha, zip_path)
        extract_fresh(zip_path, sha, os.path.join(VENDOR_DIR, subdir))

    iscc = find_iscc(args.iscc)
    result = subprocess.run([iscc, "/Q", ISS_PATH])
    if result.returncode != 0:
        sys.exit(f"ISCC failed with exit code {result.returncode}")
    print(f"built {os.path.join(INSTALLER_DIR, 'Output', 'PrimeAtlasSetup.exe')}")


if __name__ == "__main__":
    main()
