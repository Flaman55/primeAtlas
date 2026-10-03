"""
test_app_icon.py -- covers primeatlas/core/app_icon.py and the places that use it: the
PrimeAtlas globe icon for the Tk windows, the visualization GLFW window, the
taskbar, and the installer's shortcuts.

Why AppUserModelID matters: the app runs as pythonw.exe, so without an explicit
AppUserModelID Windows groups the window under Python and shows Python's icon on the
taskbar no matter what icon the window itself sets.

Usage:
    python unitTests/test_app_icon.py
"""
import os
import re
import struct
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core import app_icon  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def read(rel):
    with open(os.path.join(_REPO_ROOT, rel), encoding="utf-8-sig") as f:
        return f.read()


def ico_sizes(path):
    with open(path, "rb") as f:
        data = f.read()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    sizes = set()
    for i in range(count):
        w, h = struct.unpack_from("<BB", data, 6 + 16 * i)
        sizes.add((w or 256, h or 256))
    return reserved, kind, sizes


def section_assets():
    print("\n--- Assets ---")
    check(os.path.isfile(app_icon.ICO_PATH), "primeatlas.ico exists")
    if os.path.isfile(app_icon.ICO_PATH):
        reserved, kind, sizes = ico_sizes(app_icon.ICO_PATH)
        check(reserved == 0 and kind == 1, "ICO header is a valid icon (type 1)")
        wanted = {(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)}
        check(wanted <= sizes, f"ICO holds every size Windows uses across DPI settings "
                               f"(missing {sorted(wanted - sizes)})")
    check(os.path.isfile(app_icon.PNG_PATH), "256 px PNG exists (Tk iconphoto fallback)")
    for size in app_icon.GLFW_ICON_SIZES:
        path = app_icon.rgba_path(size)
        check(os.path.isfile(path) and os.path.getsize(path) == size * size * 4,
              f"raw RGBA {size}x{size} icon exists with exactly {size * size * 4} bytes")


def section_glfw_images():
    print("\n--- glfw_icon_images() ---")
    images = app_icon.glfw_icon_images()
    check([img[0] for img in images] == list(app_icon.GLFW_ICON_SIZES),
          "one image per GLFW icon size, in order")
    for w, h, pixels in images:
        check(len(pixels) == h and all(len(row) == w for row in pixels)
              and all(len(px) == 4 for px in pixels[h // 2]),
              f"{w}x{h}: pixels[row][col] = RGBA, the nested shape pyGLFW's wrap() indexes")
        check(pixels[0][0][3] == 0 and pixels[h // 2][w // 2][3] == 255,
              f"{w}x{h}: transparent corner, opaque centre")
    check(app_icon.glfw_icon_images(assets_dir=os.path.join(_REPO_ROOT, "nonexistent")) == [],
          "missing assets => empty list, never an exception")


def section_app_user_model_id():
    print("\n--- set_app_user_model_id() ---")
    calls = []

    class FakeShell32:
        def SetCurrentProcessExplicitAppUserModelID(self, value):
            calls.append(value)
            return 0

    check(app_icon.set_app_user_model_id(shell32=FakeShell32(), os_name="nt") is True
          and calls == [app_icon.APP_USER_MODEL_ID],
          "on Windows it sets the process AppUserModelID")

    class BrokenShell32:
        def SetCurrentProcessExplicitAppUserModelID(self, value):
            raise OSError("no shell32")
    check(app_icon.set_app_user_model_id(shell32=BrokenShell32(), os_name="nt") is False,
          "a failing shell32 call returns False, never raises")
    check(app_icon.set_app_user_model_id(shell32=FakeShell32(), os_name="posix") is False,
          "no-op outside Windows")


def section_tk():
    print("\n--- apply_tk_icon() ---")

    class FakeRoot:
        def __init__(self, fail_bitmap=False, fail_photo=False):
            self.calls = []
            self.fail_bitmap = fail_bitmap
            self.fail_photo = fail_photo

        def iconbitmap(self, default=None):
            self.calls.append(("iconbitmap", default))
            if self.fail_bitmap:
                raise RuntimeError("TclError")

        def iconphoto(self, default, image):
            self.calls.append(("iconphoto", default))
            if self.fail_photo:
                raise RuntimeError("TclError")

    root = FakeRoot()
    check(app_icon.apply_tk_icon(root, os_name="nt", photo_factory=lambda **kw: object()) is True
          and root.calls == [("iconbitmap", app_icon.ICO_PATH)],
          "Windows: iconbitmap(default=ICO) -- 'default' also covers every later Toplevel")
    root = FakeRoot(fail_bitmap=True)
    check(app_icon.apply_tk_icon(root, os_name="nt", photo_factory=lambda **kw: object()) is True
          and root.calls[-1] == ("iconphoto", True),
          "a failing iconbitmap falls back to iconphoto(PNG)")
    root = FakeRoot(fail_bitmap=True, fail_photo=True)
    check(app_icon.apply_tk_icon(root, os_name="nt", photo_factory=lambda **kw: object()) is False,
          "both failing => False, never raises (an icon is never worth a crash)")
    root = FakeRoot()
    app_icon.apply_tk_icon(root, os_name="posix", photo_factory=lambda **kw: object())
    check(root.calls == [("iconphoto", True)], "non-Windows goes straight to iconphoto(PNG)")


def section_wiring():
    print("\n--- Wiring ---")
    main_src = read("prime_atlas_v2.py")
    check("set_app_user_model_id()" in main_src, "prime_atlas_v2.py sets the AppUserModelID")
    check("apply_tk_icon(self)" in main_src, "the main window gets the icon")
    check("apply_tk_icon(self)" in read("primeatlas/settings/env_setup_wizard.py"),
          "the first-run WSL wizard window gets the icon")
    check("primeatlas.ico" in read("startup_dependency_check.py"),
          "the pre-import dependency dialogs get the icon (by path -- no primeatlas import)")
    gl = read("primeatlas/visualization/shared/gl_setup.py")
    check("set_window_icon" in gl, "the visualization GLFW window gets the icon")
    aumid = gl.find("set_app_user_model_id()")
    check(aumid != -1 and aumid < gl.find("glfw.create_window("),
          "the visualization renderer sets the AppUserModelID BEFORE creating its window (a separate process)")

    iss = read("installer/PrimeAtlasSetup.iss")
    check(re.search(r"^SetupIconFile=.*primeatlas\.ico\s*$", iss, re.MULTILINE) is not None,
          "the installer exe itself uses the icon")
    icon_lines = [l for l in iss.splitlines() if l.startswith("Name:") and "pythonw.exe" in l]
    check(len(icon_lines) == 2 and all("IconFilename:" in l and "primeatlas.ico" in l
                                        for l in icon_lines),
          "both shortcuts use the icon")
    # Inno creates [Icons] BEFORE ssPostInstall, where the repo is git-cloned, so an icon
    # path inside {app}\app does not exist yet when the shortcut is made (blank icon). The
    # installer must ship its own copy via [Files] and point every icon reference at it.
    check(re.search(r'^Source:\s*"\.\.\\primeatlas\\core\\assets\\primeatlas\.ico";\s*DestDir:\s*"\{app\}"',
                    iss, re.MULTILINE) is not None,
          r"[Files] installs primeatlas.ico into {app} itself (exists before [Icons] runs)")
    check(all(r'IconFilename: "{app}\primeatlas.ico"' in l for l in icon_lines),
          r"both shortcuts point at {app}\primeatlas.ico, never at the not-yet-cloned repo")
    check(re.search(r"^UninstallDisplayIcon=\{app\}\\primeatlas\.ico\s*$", iss, re.MULTILINE)
          is not None, r"Apps & features also uses {app}\primeatlas.ico")
    check(all(f'AppUserModelID: "{app_icon.APP_USER_MODEL_ID}"' in l for l in icon_lines),
          "both shortcuts carry the same AppUserModelID as the running app (pinned shortcut "
          "and open window share one taskbar button)")
    check("UninstallDisplayIcon=" in iss and "primeatlas.ico" in
          re.search(r"^UninstallDisplayIcon=(.*)$", iss, re.MULTILINE).group(1),
          "Apps & features shows the icon")


if __name__ == "__main__":
    section_assets()
    section_glfw_images()
    section_app_user_model_id()
    section_tk()
    section_wiring()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
