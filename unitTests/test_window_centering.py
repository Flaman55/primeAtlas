"""
test_window_centering.py -- spec tests for opening the visualization's windows centered
on screen (primeatlas/visualization/shared/window_mode.py).

Spec:
  A. centered_position(area, outer size): the top-left corner that centers a window of
     the given outer size (frame included) in the work area; a window larger than the
     area is pinned to the area's top-left edge on that axis instead of going negative.
  B. center_glfw_window(glfw, window): centers the GL window, frame included, in the
     primary monitor's work area -- glfw positions the CLIENT area, so the frame's left/
     top size is added; nothing happens without a monitor.
  C. center_tk_window(toplevel): centers a Tk window (its requested size) on its screen.

Usage:
    python unitTests/test_window_centering.py
"""
import os
import sys

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


def section_a():
    print("\n--- A: centered_position ---")
    from primeatlas.visualization.shared.window_mode import centered_position
    check(centered_position((0, 0, 1920, 1040), (1600, 1000)) == (160, 20), "1600x1000 in a 1920x1040 area")
    check(centered_position((1920, 0, 1920, 1080), (800, 600)) == (2480, 240), "a second monitor's offset is kept")
    check(centered_position((0, 0, 1280, 720), (1600, 1000)) == (0, 0), "a window larger than the area is pinned to its edge")
    check(centered_position((0, 30, 1000, 1000), (401, 401)) == (299, 329), "odd sizes round down")


class _FakeGlfw:
    def __init__(self, monitor=True):
        self.monitor = object() if monitor else None
        self.pos = None

    def get_primary_monitor(self):
        return self.monitor

    def get_monitor_workarea(self, monitor):
        return (0, 0, 1920, 1040)

    def get_window_size(self, window):
        return (1600, 960)

    def get_window_frame_size(self, window):
        return (8, 31, 8, 8)

    def set_window_pos(self, window, x, y):
        self.pos = (x, y)


def section_b():
    print("\n--- B: center_glfw_window ---")
    from primeatlas.visualization.shared.window_mode import center_glfw_window
    g = _FakeGlfw()
    center_glfw_window(g, "win")
    outer_w, outer_h = 1600 + 16, 960 + 39
    expected = ((1920 - outer_w) // 2 + 8, (1040 - outer_h) // 2 + 31)
    check(g.pos == expected, f"the client area is placed so the whole frame is centered (got {g.pos}, want {expected})")
    g = _FakeGlfw(monitor=False)
    center_glfw_window(g, "win")
    check(g.pos is None, "no monitor: the window is left where it is")


class _FakeTk:
    def __init__(self):
        self.geometry_value = None

    def update_idletasks(self):
        pass

    def winfo_reqwidth(self):
        return 500

    def winfo_reqheight(self):
        return 300

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def geometry(self, value):
        self.geometry_value = value


def section_c():
    print("\n--- C: center_tk_window ---")
    from primeatlas.visualization.shared.window_mode import center_tk_window
    t = _FakeTk()
    center_tk_window(t)
    check(t.geometry_value == "+710+390", f"a 500x300 dialog is centered on a 1920x1080 screen (got {t.geometry_value!r})")


if __name__ == "__main__":
    for section in (section_a, section_b, section_c):
        try:
            section()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
