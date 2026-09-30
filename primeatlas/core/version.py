"""
version.py -- the single source of PrimeAtlas's version number.

Shown in the main window's title bar, and read (by regex, without importing the package,
which needs numpy) by installer/build_installer.py, which passes it to Inno Setup as
/DAppVersion, and by .github/workflows/installer.yml, which refuses to publish a release
whose tag doesn't match it. Bump it here, then tag vX.Y.Z (or vX.Y.Z-rc1 for a
pre-release) to publish.
"""
APP_VERSION = "1.0.0"
