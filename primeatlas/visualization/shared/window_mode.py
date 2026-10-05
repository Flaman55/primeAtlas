"""GLFW fullscreen toggle preserving windowed geometry and the GL context, and
centering the visualization's windows (GLFW and Tk) on screen."""


def centered_position(area, outer_size):
    """Top-left corner centering a window of `outer_size` (width, height, frame
    included) in `area` (x, y, width, height); an axis where the window is larger
    than the area is pinned to the area's edge."""
    ax, ay, aw, ah = area
    w, h = outer_size
    return ax + max(0, (aw - w) // 2), ay + max(0, (ah - h) // 2)


def center_glfw_window(glfw, window):
    """Centers `window`, frame included, in the primary monitor's work area. GLFW
    positions the client area, so the frame's left/top size is added back."""
    monitor = glfw.get_primary_monitor()
    if not monitor:
        return
    width, height = glfw.get_window_size(window)
    left, top, right, bottom = glfw.get_window_frame_size(window)
    x, y = centered_position(glfw.get_monitor_workarea(monitor),
                             (width + left + right, height + top + bottom))
    glfw.set_window_pos(window, x + left, y + top)


def center_tk_window(toplevel):
    """Centers a Tk window (at its requested size) on its screen."""
    toplevel.update_idletasks()
    x, y = centered_position((0, 0, toplevel.winfo_screenwidth(), toplevel.winfo_screenheight()),
                             (toplevel.winfo_reqwidth(), toplevel.winfo_reqheight()))
    toplevel.geometry(f"+{x}+{y}")


class FullscreenToggle:
    def __init__(self, glfw, window):
        self.glfw = glfw
        self.window = window
        self.saved_geometry = None
        self.resume_fullscreen = False

    def hide_for_pause(self):
        """Release exclusive monitor ownership before hiding the window."""
        was_fullscreen = bool(self.glfw.get_window_monitor(self.window))
        if was_fullscreen and not self.toggle():
            return False
        self.resume_fullscreen = was_fullscreen
        self.glfw.hide_window(self.window)
        return True

    def show_after_pause(self):
        """Restore visibility first, then the user's previous fullscreen mode."""
        self.glfw.show_window(self.window)
        if self.resume_fullscreen:
            self.toggle()
        self.resume_fullscreen = False

    def toggle(self):
        api, window = self.glfw, self.window
        if api.get_window_monitor(window):
            if self.saved_geometry is None:
                return False
            x, y, width, height = self.saved_geometry
            api.set_window_monitor(window, None, x, y, width, height, api.DONT_CARE)
            return not bool(api.get_window_monitor(window))
        x, y = api.get_window_pos(window)
        width, height = api.get_window_size(window)
        if width <= 0 or height <= 0:
            return False
        choices = []
        for monitor in api.get_monitors() or []:
            mode = api.get_video_mode(monitor)
            if mode is None:
                continue
            mx, my = api.get_monitor_pos(monitor)
            overlap = max(0, min(x+width,mx+mode.size.width)-max(x,mx)) * max(
                0, min(y+height,my+mode.size.height)-max(y,my))
            choices.append((overlap, monitor, mode))
        if not choices:
            return False
        _, monitor, mode = max(choices, key=lambda item:item[0])
        self.saved_geometry = (x,y,width,height)
        api.set_window_monitor(window, monitor, 0, 0, mode.size.width, mode.size.height,
                               mode.refresh_rate)
        return bool(api.get_window_monitor(window))

    def handle_key(self, key, action):
        if key != self.glfw.KEY_F11:
            return False
        if action == self.glfw.PRESS:
            self.toggle()
        return True
