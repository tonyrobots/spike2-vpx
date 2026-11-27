"""The Stern LCD in the VR backbox (docs/vr-plan.md, Phase 3)."""

import ctypes
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "spike2_emu" / "vpx"))
sys.path.insert(0, str(ROOT / "tools" / "spike2_emu"))
import padisplay  # noqa: E402
import play_spike2 as play  # noqa: E402
import vpx_lcd  # noqa: E402

#: a 2560x1440 screen left of a 3840x2160 main one
MAIN = {"n": 1, "x": 0, "y": 0, "w": 3840, "h": 2160, "primary": True}
LEFT = {"n": 2, "x": -2560, "y": 468, "w": 2560, "h": 1440, "primary": False}


class XCoordinatesTest(unittest.TestCase):
    def test_a_monitor_left_of_the_main_one_moves_the_x_origin(self):
        line = padisplay.resolve({"mode": "window", "monitor": 1, "rx": 1500, "ry": 100,
                                  "w": 1024, "h": 576}, [MAIN, LEFT])
        self.assertIn("rx=1500 ry=100 x=4060 y=100 w=1024 h=576 fs=0", line)
        line = padisplay.resolve({"mode": "fullscreen", "monitor": 2}, [MAIN, LEFT])
        self.assertIn("x=0 y=468 w=2560 h=1440 fs=1", line)

    def test_a_monitor_above_moves_it_down(self):
        above = {"n": 2, "x": 200, "y": -1080, "w": 1920, "h": 1080, "primary": False}
        line = padisplay.resolve({"mode": "fullscreen", "monitor": 1}, [MAIN, above])
        self.assertIn("x=0 y=1080 w=3840 h=2160", line)

    def test_place_stays_in_windows_coordinates(self):
        place = padisplay.place({"mode": "fullscreen", "monitor": 2}, [MAIN, LEFT])
        self.assertEqual((place["x"], place["y"], place["w"], place["h"]), (-2560, 468, 2560, 1440))
        self.assertIsNone(padisplay.place({"mode": "free"}, [MAIN]))

    def test_one_monitor_is_unchanged(self):
        line = padisplay.resolve({"mode": "fullscreen", "monitor": 1}, [MAIN])
        self.assertIn("x=0 y=0 w=3840 h=2160 fs=1", line)


class VrTargetTest(unittest.TestCase):
    def inside(self, rect, monitor):
        x, y, w, h = rect
        return (monitor["x"] <= x and x + w <= monitor["x"] + monitor["w"]
                and monitor["y"] <= y and y + h <= monitor["y"] + monitor["h"])

    def test_the_cabinet_lcd_screen_holds_it_centred(self):
        rect = vpx_lcd.vr_target({"mode": "fullscreen", "monitor": 2}, [MAIN, LEFT])
        self.assertEqual(rect, (-2560 + 600, 468 + 336, 1360, 768))
        self.assertTrue(self.inside(rect, LEFT))

    def test_without_an_lcd_screen_it_is_the_main_one(self):
        for setting in ({"mode": "free", "monitor": 2}, {"mode": "fullscreen", "monitor": 7}):
            with self.subTest(setting=setting):
                self.assertTrue(self.inside(vpx_lcd.vr_target(setting, [LEFT, MAIN]), MAIN))

    def test_a_small_monitor_gets_a_smaller_16_9_rectangle(self):
        small = {"n": 1, "x": 0, "y": 0, "w": 1280, "h": 720, "primary": True}
        x, y, w, h = vpx_lcd.vr_target({"mode": "free"}, [small])
        self.assertTrue(self.inside((x, y, w, h), small))
        self.assertLess(w, 1280)
        self.assertAlmostEqual(w / h, 16 / 9, places=1)


class VrLcdTest(unittest.TestCase):
    def open(self, folder, conf=None, target=None):
        if conf is not None:
            (Path(folder) / "display.conf").write_bytes(conf)
        with patch.object(vpx_lcd, "CaptureTarget", target or Mock()) as capture:
            return vpx_lcd.VrLcd(Mock(), board=folder, monitors=[MAIN, LEFT]), capture

    def test_the_run_gets_a_borderless_window_on_the_target_and_the_line_goes_back(self):
        original = b"# mine\ngame monitor=2 mode=fullscreen border=0 x=0 y=468 w=2560 h=1440 fs=1\n"
        with TemporaryDirectory() as folder:
            lcd, capture = self.open(folder, original)
            capture.assert_called_once()
            self.assertEqual(capture.call_args.args[1], (-1960, 804, 1360, 768))
            line = (Path(folder) / "display.conf").read_text()
            self.assertIn("mode=window border=0", line)
            self.assertIn("x=600 y=804 w=1360 h=768 fs=0", line)       # X root coordinates
            self.assertIsNone(vpx_lcd.fullscreen_target(folder))        # no Windows-side placement
            lcd.close()
            capture.return_value.close.assert_called_once_with()
            self.assertEqual((Path(folder) / "display.conf").read_bytes(), original)

    def test_no_setting_before_means_none_after(self):
        with TemporaryDirectory() as folder:
            lcd, _ = self.open(folder)
            self.assertTrue((Path(folder) / "display.conf").exists())
            lcd.close()
            self.assertFalse((Path(folder) / "display.conf").exists())

    def test_a_capture_window_that_fails_puts_the_setting_back(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "no window"):
                self.open(folder, b"game monitor=1 mode=free\n", Mock(side_effect=RuntimeError("no window")))
            self.assertEqual((Path(folder) / "display.conf").read_bytes(), b"game monitor=1 mode=free\n")


class IniLineEndingsTest(unittest.TestCase):
    def test_setting_a_key_keeps_vpxs_crlf_and_bom(self):
        import padvpx

        for raw in (b"\xef\xbb\xbf[Player]\r\nCapturePUP = 0\r\n[PlayerVR]\r\nAskToTurnOn = 1\r\n",
                    b"[Player]\nCapturePUP = 0\n"):
            with self.subTest(raw=raw[:12]), TemporaryDirectory() as folder:
                path = Path(folder) / "VPinballX.ini"
                path.write_bytes(raw)
                padvpx.vpx_ini_set({"CapturePUP": 1}, path=str(path))
                self.assertEqual(path.read_bytes(), raw.replace(b"CapturePUP = 0", b"CapturePUP = 1"))


class VrLaunchOrderTest(unittest.TestCase):
    def run_play(self, vr):
        events = []
        launch = Mock(title="godzilla_le", slot=2)
        launch.start.side_effect = lambda: events.append("start")
        launch.stop.side_effect = lambda: events.append("stop")
        rig = SimpleNamespace(distro="SPIKE2-VPX", root="/slots/2/root", prepared_launch=False)
        lcd = Mock()
        lcd.return_value.close.side_effect = lambda: events.append("lcd closed")

        def opened(*_):
            events.append("lcd opened")
            return lcd.return_value

        def start(command, **_):
            events.append("vpx")
            proc = MagicMock()
            proc.__enter__.return_value.wait.return_value = 0
            return proc

        with patch.object(play.vpx_lcd, "VrLcd", side_effect=opened), \
                patch.object(play, "vr_ini", return_value=None), \
                patch.object(play.vpx_lcd, "fullscreen_target", return_value=None), \
                patch.object(play.padcontroller.Rig, "board_run", return_value=None), \
                patch.object(play, "wait_for_rig", return_value=rig), \
                patch.object(play, "wait_for_game"), \
                patch.object(play.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
                patch.object(play.subprocess, "Popen", side_effect=start):
            self.assertEqual(play.play(launch, Path("VPinballX_GL64.exe"), Path("table.vpx"), 30, vr=vr), 0)
        return events

    def test_the_lcd_is_set_up_before_the_run_and_put_back_after_it_stops(self):
        self.assertEqual(self.run_play(True), ["lcd opened", "start", "vpx", "stop", "lcd closed"])

    def test_a_desktop_run_leaves_it_alone(self):
        self.assertEqual(self.run_play(False), ["start", "vpx", "stop"])


@unittest.skipUnless(sys.platform == "win32", "Win32 windows")
class CaptureWindowTest(unittest.TestCase):
    def test_vpx_finds_the_window_by_title_at_the_target(self):
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        launch = Mock(slot=None)
        target = vpx_lcd.CaptureTarget(launch, (40, 40, 320, 180), raise_s=0.05)
        try:
            hwnd = user32.FindWindowW("Spike2VpxCaptureTarget", vpx_lcd.CAPTURE_TITLE)
            self.assertTrue(hwnd)
            rect = (ctypes.c_long * 4)()
            context = user32.SetThreadDpiAwarenessContext
            context.restype = ctypes.c_void_p
            old = context(ctypes.c_void_p(-4))
            user32.GetWindowRect(ctypes.c_void_p(hwnd), rect)
            context(ctypes.c_void_p(old))
            self.assertEqual(tuple(rect), (40, 40, 360, 220))
        finally:
            target.close()
        self.assertFalse(user32.FindWindowW("Spike2VpxCaptureTarget", vpx_lcd.CAPTURE_TITLE))
        self.assertEqual(launch.note.call_count, 2)


if __name__ == "__main__":
    unittest.main()
