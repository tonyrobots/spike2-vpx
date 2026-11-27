"""Place the WSLg LCD on its assigned Windows display."""

import ctypes
from pathlib import Path
import sys
import threading

import padcontroller
import padisplay
import padlaunch


GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_FRAME = 0x00C00000 | 0x00040000  # WS_CAPTION | WS_THICKFRAME
WS_EX_TOPMOST = 0x00000008
WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_ASYNCWINDOWPOS = 0x0010, 0x0020, 0x4000


def fullscreen_target(board=None):
    if sys.platform != "win32":
        return None
    setting = padisplay.load(Path(board or padlaunch.BOARD) / "display.conf")
    if setting["mode"] != "fullscreen":
        return None
    monitor = next((screen for screen in padisplay.monitors() if screen["n"] == setting["monitor"]), None)
    if monitor:
        x, y, width, height = (monitor[key] for key in ("x", "y", "w", "h"))
        return x, y, x + width, y + height
    return None


#: The LCD's size where VPX captures it in VR: the Stern LCD's 16:9 at its
#: usual window size, made smaller to fit a monitor (vr_target).
VR_SIZE = (1360, 768)
#: The title VPX's CaptureExternalDMD looks for first (captureExt.cpp).
CAPTURE_TITLE = "Virtual DMD"


def vr_target(setting, monitors):
    """Where the LCD goes in VR, as Windows (x, y, w, h): centred on the
    monitor the display setting names (the cabinet's LCD screen), else on
    the main one, and fully inside it. VPX copies the screen at the capture
    window's rectangle, clamped to one monitor, so a rectangle across two
    would shift the picture."""
    number = setting.get("monitor") if setting.get("mode") in ("fullscreen", "window") else None
    monitor = next((m for m in monitors if m["n"] == number), None) \
        or next((m for m in monitors if m.get("primary")), monitors[0])
    w, h = VR_SIZE
    scale = min(1.0, monitor["w"] * 0.9 / w, monitor["h"] * 0.9 / h)
    w, h = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
    return monitor["x"] + (monitor["w"] - w) // 2, monitor["y"] + (monitor["h"] - h) // 2, w, h


def frame_insets(path):
    try:
        with path.open(encoding="ascii") as file:
            insets = tuple(int(value) for value in file.read(80).split())
        if len(insets) == 4 and all(0 <= value <= 256 for value in insets):
            return insets
    except (OSError, ValueError):
        pass
    return None


def outer_bounds(target, insets):
    x, y, right, bottom = target
    left, top, inset_right, inset_bottom = insets
    return x - left, y - top, right + inset_right, bottom + inset_bottom


class VrLcd:
    """The Stern LCD in the VR backbox for one run: display.conf puts the
    LCD's picture borderless on vr_target's rectangle, a CaptureTarget sits
    under it, and close() puts the user's display.conf back. Open it before
    the run starts: padglhost reads display.conf as the LCD opens, and the
    capture window has to exist before VPX looks for it."""

    def __init__(self, launch, board=None, monitors=None):
        self.conf = Path(board or padlaunch.BOARD) / "display.conf"
        monitors = monitors or padisplay.monitors()
        try:
            self.before = self.conf.read_bytes()
        except FileNotFoundError:
            self.before = None
        self.rect = vr_target(padisplay.load(self.conf), monitors)
        setting = dict(padisplay.for_rect(list(self.rect), monitors), border=False)
        padisplay.save(setting, str(self.conf), monitors)
        try:
            self.target = CaptureTarget(launch, self.rect)
        except BaseException:
            self.put_back()
            raise

    def close(self):
        try:
            self.target.close()
        finally:
            self.put_back()

    def put_back(self):
        if self.before is None:
            self.conf.unlink(missing_ok=True)
        else:
            tmp = self.conf.with_name(self.conf.name + ".tmp")
            tmp.write_bytes(self.before)
            tmp.replace(self.conf)        # padglhost may read it at any moment


class CaptureTarget:
    """What VPX captures as the backbox DMD in VR (docs/vr-plan.md, Phase 0):
    a black borderless window titled CAPTURE_TITLE at *rect*, with the
    Stern LCD kept on top of it, so the screen VPX copies there is the LCD.

    VPX keeps the first window it finds by that title, so this one is
    created before VPX starts (ahead of PUP's windows, which it also looks
    for). The LCD isn't renamed or moved from here: display.conf puts its
    picture on *rect*, and this only keeps it in front."""

    CLASS = "Spike2VpxCaptureTarget"
    _wndproc = None                 # kept alive for the window class

    def __init__(self, launch, rect, raise_s=0.25):
        self.launch = launch
        self.rect = tuple(rect)
        self.raise_s = raise_s
        self.raises = 0
        self.error = None
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, name="VR capture target", daemon=True)
        self.thread.start()
        self.ready.wait(5)
        if self.error:
            raise RuntimeError(f"Could not open the VR capture window. {self.error}")
        self.launch.note(f"[display] VR capture window {CAPTURE_TITLE!r} at Windows {self.rect}.")

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        self.launch.note(f"[display] VR capture window closed; the Stern LCD was brought "
                         f"to the front {self.raises} times.")

    def run(self):
        from ctypes import wintypes as wt
        # Own DLL objects with full-width handle types: windll's are shared,
        # and its default int return cuts a 64-bit module handle in half.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32, gdi32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("gdi32")
        kernel32.GetModuleHandleW.restype = wt.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        gdi32.GetStockObject.restype = wt.HGDIOBJ
        user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        user32.RegisterClassW.restype = wt.ATOM
        user32.DestroyWindow.argtypes = [wt.HWND]
        user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
        user32.PeekMessageW.argtypes = [ctypes.c_void_p, wt.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # physical pixels, as padisplay
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
        user32.CreateWindowExW.restype = wt.HWND
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
        user32.WindowFromPoint.restype = wt.HWND
        user32.WindowFromPoint.argtypes = [wt.POINT]
        user32.GetAncestor.restype = wt.HWND
        user32.GetAncestor.argtypes = [wt.HWND, ctypes.c_uint]
        wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", wndproc_type),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", ctypes.c_void_p),
                        ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR)]

        hwnd = None
        try:
            instance = kernel32.GetModuleHandleW(None)
            if CaptureTarget._wndproc is None:
                CaptureTarget._wndproc = wndproc_type(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
            wc = WNDCLASSW(lpfnWndProc=CaptureTarget._wndproc, hInstance=instance,
                           lpszClassName=self.CLASS, hbrBackground=gdi32.GetStockObject(4))  # BLACK_BRUSH
            if not user32.RegisterClassW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:
                raise ctypes.WinError(ctypes.get_last_error())                   # 1410: registered already
            x, y, w, h = self.rect
            hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, self.CLASS, CAPTURE_TITLE,
                                          WS_POPUP | WS_VISIBLE, x, y, w, h, None, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
        except OSError as exc:
            self.error = exc
            self.ready.set()
            return
        self.ready.set()
        msg = wt.MSG()
        centre = wt.POINT(x + w // 2, y + h // 2)
        try:
            while not self.stop.is_set():
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):     # PM_REMOVE
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                lcd = self.lcd()
                if lcd and self.covered(user32, lcd, centre):
                    user32.SetWindowPos(lcd, wt.HWND(-1), 0, 0, 0, 0,
                                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)  # HWND_TOPMOST
                    self.raises += 1
                self.stop.wait(self.raise_s)
        finally:
            user32.DestroyWindow(hwnd)

    def lcd(self):
        if self.launch.slot is None:
            return 0
        prefix = f"[rig {self.launch.slot}: {self.launch.label}] "
        return padcontroller.find_kit_window(" - Stern Spike 2 emulator", title_prefix=prefix)

    @staticmethod
    def covered(user32, lcd, centre):
        """The LCD isn't topmost, or another window is in front of it over the target."""
        if not user32.GetWindowLongW(lcd, GWL_EXSTYLE) & WS_EX_TOPMOST:
            return True
        front = user32.GetAncestor(user32.WindowFromPoint(centre), 2)                # GA_ROOT
        return (front or 0) != lcd


class Placement:
    def __init__(self, launch, target):
        self.launch = launch
        self.target = target
        self.launch.note(f"[display] Assigning the Stern LCD to Windows bounds {self.target}.")
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.watch, name="Stern LCD placement", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)

    def watch(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        context = user32.SetThreadDpiAwarenessContext
        context.restype = ctypes.c_void_p
        old = context(ctypes.c_void_p(-4))  # Per-monitor v2, matching padisplay's physical bounds.
        prefix = f"[rig {self.launch.slot}: {self.launch.label}] "
        frame_file = self.launch.lcd_frame_path()
        confirmed = None
        reported_error = False
        try:
            while not self.stop.is_set():
                hwnd = padcontroller.find_kit_window(" - Stern Spike 2 emulator", title_prefix=prefix)
                try:
                    if hwnd and not user32.IsIconic(ctypes.c_void_p(hwnd)):
                        insets = frame_insets(frame_file)
                        bounds = outer_bounds(self.target, insets) if insets is not None else self.target
                        if self.place(user32, hwnd, bounds) and insets is not None and confirmed != (hwnd, insets):
                            self.launch.note(f"[display] Stern LCD content fits {self.target}, "
                                             f"WSLg frame insets {insets}.")
                            confirmed = hwnd, insets
                except OSError as exc:
                    if not reported_error:
                        self.launch.note(f"[display] Windows could not position the Stern LCD yet: {exc}")
                        reported_error = True
                self.stop.wait(0.5)
        finally:
            if old:
                context(ctypes.c_void_p(old))

    def place(self, user32, hwnd, bounds):
        window = ctypes.c_void_p(hwnd)
        x, y, right, bottom = bounds
        width, height = right - x, bottom - y
        style = user32.GetWindowLongW(window, GWL_STYLE)
        topmost = user32.GetWindowLongW(window, GWL_EXSTYLE) & WS_EX_TOPMOST
        if padcontroller.window_rect(hwnd) == (x, y, width, height) and not style & WS_FRAME and topmost:
            return True
        # A repeated RAIL placement or a replacement HWND can undo the first move.
        flags = SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS
        frame_error = None
        if style & WS_FRAME:
            if user32.SetWindowLongW(window, GWL_STYLE, style & ~WS_FRAME):
                flags |= SWP_FRAMECHANGED
            else:
                frame_error = ctypes.WinError(ctypes.get_last_error())
        if not user32.SetWindowPos(window, ctypes.c_void_p(-1), x, y, width, height, flags):
            raise ctypes.WinError(ctypes.get_last_error())
        if frame_error:
            raise frame_error
        return False
