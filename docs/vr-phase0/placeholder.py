"""Phase 0 placeholder test (docs/vr-plan.md), kept for reference by Phase 3.

Opens a borderless black Win32 window titled 'Virtual DMD', which VPX GL's
CaptureExternalDMD finds before PUP's windows, and keeps the SPIKE 2 LCD
topmost over it until VPX closes.

Before you run it:
  - Start this script BEFORE launching the table.
  - Put the LCD's visible area on the same rect through the rig board's
    display.conf, in X root coordinates. Windows x + 2560 on the owner's PC,
    where the 2nd monitor is at -2560:
      game monitor=1 mode=window border=0 x=4060 y=100 w=1024 h=576 fs=0
  - The rect must lie fully inside one monitor; VPX clamps the copy to the
    monitor, which shifts the image.

Confirmed on GOTG (PAD) in VR, 2026-11-26.
"""
import ctypes, ctypes.wintypes as wt, time
X, Y, W, H = 1500, 100, 1024, 576
u=ctypes.windll.user32; k=ctypes.windll.kernel32; g=ctypes.windll.gdi32
u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
u.FindWindowA.restype=wt.HWND; u.FindWindowA.argtypes=[ctypes.c_char_p,ctypes.c_char_p]
u.WindowFromPoint.restype=wt.HWND; u.WindowFromPoint.argtypes=[wt.POINT]; u.GetAncestor.restype=wt.HWND; u.GetAncestor.argtypes=[wt.HWND,ctypes.c_uint]
u.DefWindowProcW.restype=ctypes.c_ssize_t; u.DefWindowProcW.argtypes=[wt.HWND,ctypes.c_uint,wt.WPARAM,wt.LPARAM]
u.CreateWindowExW.restype=wt.HWND
WNDPROC=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,wt.HWND,ctypes.c_uint,wt.WPARAM,wt.LPARAM)
class WNDCLASSW(ctypes.Structure):
    _fields_=[("style",ctypes.c_uint),("lpfnWndProc",WNDPROC),("cbClsExtra",ctypes.c_int),("cbWndExtra",ctypes.c_int),
              ("hInstance",wt.HINSTANCE),("hIcon",wt.HICON),("hCursor",ctypes.c_void_p),("hbrBackground",wt.HBRUSH),
              ("lpszMenuName",wt.LPCWSTR),("lpszClassName",wt.LPCWSTR)]
proc=WNDPROC(lambda h,m,w,l: u.DefWindowProcW(h,m,w,l))
wc=WNDCLASSW(); wc.lpfnWndProc=proc; wc.hInstance=k.GetModuleHandleW(None); wc.lpszClassName="Spike2VpxDmdTarget"
wc.hbrBackground=g.GetStockObject(4)  # BLACK_BRUSH
u.RegisterClassW(ctypes.byref(wc))
WS_POPUP, WS_VISIBLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000000, 0x10000000, 0x80, 0x08000000
ph=u.CreateWindowExW(WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE,"Spike2VpxDmdTarget","Virtual DMD",WS_POPUP|WS_VISIBLE,X,Y,W,H,None,None,wc.hInstance,None)
def title(h): b=ctypes.create_unicode_buffer(512); u.GetWindowTextW(h,b,512); return b.value
def rect(h): r=wt.RECT(); u.GetWindowRect(h,ctypes.byref(r)); return (r.left,r.top,r.right,r.bottom)
def top_at(x,y): return title(u.GetAncestor(u.WindowFromPoint(wt.POINT(x,y)),2))[:40]
print(f"placeholder {ph and hex(ph)} rect {rect(ph)}; FindWindowA('Virtual DMD') -> {hex(u.FindWindowA(None,b'Virtual DMD') or 0)}", flush=True)
t0=time.time()
def lcd():
    f=[]; cb=ctypes.WINFUNCTYPE(ctypes.c_bool,wt.HWND,wt.LPARAM)(lambda h,_:(f.append(h) if u.IsWindowVisible(h) and "Stern Spike 2 emulator" in title(h) else None) or True)
    u.EnumWindows(cb,0); return f[0] if f else None
state={"lcd":None,"last":None,"raises":0,"vpx":False,"pup":False,"done":False,"rep":None}
def tick():
    s=state; now=time.time()-t0
    if not s["lcd"]:
        s["lcd"]=lcd()
        if s["lcd"]: print(f"[{now:5.1f}] LCD {hex(s['lcd'])}", flush=True)
        return
    h=s["lcd"]
    if not u.IsWindow(h): s["done"]=True; return
    r=rect(h)
    if r!=s["last"]: s["last"]=r; print(f"[{now:5.1f}] LCD rect {r} (want {(X-32,Y-32,X+W+32,Y+H+32)})", flush=True)
    if not u.GetWindowLongW(h,-20)&8 or top_at(X+W//2,Y+H//2)!=title(h)[:40]:
        u.SetWindowPos(h, wt.HWND(-1), 0,0,0,0, 0x1|0x2|0x10); s["raises"]+=1
    v=u.FindWindowA(None,b"Visual Pinball Player")
    if v and not s["vpx"]: s["vpx"]=True; s["rep"]=time.time(); print(f"[{now:5.1f}] VPX player up", flush=True)
    if s["vpx"] and not v: s["done"]=True
    if u.FindWindowA(None,b"PUPSCREEN5") and not s["pup"]: s["pup"]=True; print(f"[{now:5.1f}] PUPSCREEN5 up", flush=True)
    if s["rep"] and time.time()-s["rep"]>25:
        s["rep"]=None; print(f"[{now:5.1f}] check: raised {s['raises']}x; top at centre {top_at(X+W//2,Y+H//2)!r}, corners {top_at(X+3,Y+3)!r} / {top_at(X+W-3,Y+H-3)!r}", flush=True)
msg=wt.MSG()
while not state["done"] and time.time()-t0<3600:
    while u.PeekMessageW(ctypes.byref(msg),None,0,0,1): u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))
    tick(); time.sleep(0.25)
print(f"[{time.time()-t0:5.1f}] VPX gone; closing placeholder (raised LCD {state['raises']}x)")
u.DestroyWindow(ph)
