"""Fullscreen transitions with a deterministic multi-monitor GLFW adapter."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import sys

path=Path(__file__).resolve().parents[1]/'primeatlas/ring_viz/window_mode.py'
spec=importlib.util.spec_from_file_location('window_mode',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeGLFW:
    KEY_F11=300
    PRESS=1
    REPEAT=2
    DONT_CARE=-1
    def __init__(self):
        self.monitor=None
        self.pos=(2100,100)
        self.size=(800,600)
        self.monitors=[1,2]
        self.calls=[]
    def get_window_monitor(self,w): return self.monitor
    def get_window_pos(self,w): return self.pos
    def get_window_size(self,w): return self.size
    def get_monitors(self): return self.monitors
    def get_monitor_pos(self,m): return ((m-1)*1920,0)
    def get_video_mode(self,m):
        return SimpleNamespace(size=SimpleNamespace(width=1920,height=1080),refresh_rate=60)
    def hide_window(self,w):
        assert self.monitor is None, 'Cannot hide an exclusive fullscreen window'
        self.visible = False
    def show_window(self,w):
        self.visible = True
    def set_window_monitor(self,w,m,x,y,width,height,rate):
        self.calls.append((m,x,y,width,height,rate))
        self.monitor=m
        self.pos=(x,y)
        self.size=(width,height)


class FullscreenTests(unittest.TestCase):
    def test_fullscreen_pause_releases_monitor_and_resume_restores_mode(self):
        api = FakeGLFW()
        toggle = module.FullscreenToggle(api, object())
        toggle.toggle()
        for _ in range(2):
            self.assertTrue(toggle.hide_for_pause())
            self.assertIsNone(api.monitor)
            self.assertFalse(api.visible)
            toggle.show_after_pause()
            self.assertTrue(api.visible)
            self.assertEqual(api.monitor, 2)
        toggle.toggle()
        self.assertEqual((api.pos, api.size), ((2100, 100), (800, 600)))

    def test_windowed_pause_stays_windowed_on_resume(self):
        api = FakeGLFW()
        toggle = module.FullscreenToggle(api, object())
        self.assertTrue(toggle.hide_for_pause())
        toggle.show_after_pause()
        self.assertIsNone(api.monitor)
        self.assertTrue(api.visible)
        self.assertEqual(api.calls, [])

    def test_failed_monitor_release_does_not_hide_window(self):
        api = FakeGLFW()
        api.monitor = 2
        api.visible = True
        toggle = module.FullscreenToggle(api, object())
        self.assertFalse(toggle.hide_for_pause())
        self.assertTrue(api.visible)

    def test_round_trip_on_current_monitor(self):
        api=FakeGLFW()
        toggle=module.FullscreenToggle(api,object())
        self.assertTrue(toggle.toggle())
        self.assertEqual(api.monitor,2)
        self.assertTrue(toggle.toggle())
        self.assertEqual(api.pos,(2100,100))
        self.assertEqual(api.size,(800,600))
        self.assertIsNone(api.monitor)

    def test_key_repeat_does_not_toggle(self):
        api=FakeGLFW()
        toggle=module.FullscreenToggle(api,object())
        self.assertFalse(toggle.handle_key(1,api.PRESS))
        toggle.handle_key(api.KEY_F11,api.PRESS)
        toggle.handle_key(api.KEY_F11,api.REPEAT)
        toggle.handle_key(api.KEY_F11,0)
        self.assertEqual(len(api.calls),1)

    def test_no_monitor_and_minimized(self):
        api=FakeGLFW()
        toggle=module.FullscreenToggle(api,object())
        api.monitors=[]
        self.assertFalse(toggle.toggle())
        api.monitors=[1]
        api.size=(0,0)
        self.assertFalse(toggle.toggle())
        self.assertEqual(api.calls,[])

    def test_new_geometry_saved_after_user_resize(self):
        api=FakeGLFW()
        toggle=module.FullscreenToggle(api,object())
        toggle.toggle(); toggle.toggle()
        api.pos=(10,20); api.size=(900,700)
        toggle.toggle(); toggle.toggle()
        self.assertEqual((api.pos,api.size),((10,20),(900,700)))


def device_smoke():
    """Opt-in native GLFW round trip; does not start Atlas or generate primes."""
    import glfw
    if not glfw.init():
        raise RuntimeError('GLFW initialization failed')
    try:
        glfw.window_hint(glfw.VISIBLE,glfw.FALSE)
        window=glfw.create_window(640,480,'Fullscreen smoke',None,None)
        if not window:
            raise RuntimeError('Window creation failed')
        original=(glfw.get_window_pos(window),glfw.get_window_size(window))
        toggle=module.FullscreenToggle(glfw,window)
        assert toggle.toggle(), 'Entering fullscreen failed'
        glfw.poll_events()
        assert toggle.hide_for_pause(), 'Could not release fullscreen for pause'
        glfw.poll_events()
        assert not glfw.get_window_monitor(window), 'Paused window still owns monitor'
        assert not glfw.get_window_attrib(window, glfw.VISIBLE), 'Paused window is visible'
        toggle.show_after_pause()
        glfw.poll_events()
        assert glfw.get_window_monitor(window), 'Resume did not restore fullscreen'
        assert glfw.get_window_attrib(window, glfw.VISIBLE), 'Resumed window is hidden'
        assert toggle.toggle(), 'Leaving fullscreen failed'
        glfw.poll_events()
        assert not glfw.get_window_monitor(window)
        assert glfw.get_window_size(window)==original[1]
        print('Native GLFW fullscreen pause/resume passed; monitor released and window size restored.')
    finally:
        glfw.terminate()


if __name__=='__main__':
    if '--device-smoke' in sys.argv:
        sys.argv.remove('--device-smoke')
        device_smoke()
    unittest.main()
