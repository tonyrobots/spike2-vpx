# VR support plan

Goal: play SPIKE 2 tables in a VR headset through Visual Pinball X 10.8's
OpenGL build (`VPinballX_GL64.exe`), with the Stern LCD visible in the headset.

Status: Phase 0 passed on 2026-11-26. The live Stern LCD showed in the VR
backbox of JAWS 50th (PAD) and updated smoothly. See "Phase 0 results".
Phase 1 is done. Setup saves the VPX **folder** (`vpx_dir`). An older
`vpx_exe` is read as its folder, and it is still written (the desktop exe)
because app 0.1.0 reads only that key. `vpxsetup.VPX_EXES` is the single
list of players. `Setup.vpx_executable(vr=False)` picks DX9 for desktop play
(GL if DX9 is missing) and GL for VR. Phase 2 is next.

## Background: how the app finds and launches VPX

- `spike2_vpx_setup.py:123` `choose_vpx` rejects any exe not named
  `VPinballX64.exe` and saves the path as `settings["vpx_exe"]` in
  `%LOCALAPPDATA%\Spike2Vpx\setup.json`.
- `spike2_vpx_setup.py:247` `vpx_executable()` keeps only the saved exe's
  folder and appends `VPinballX64.exe` again. **Choosing the GL exe would be
  silently discarded here even if `choose_vpx` accepted it.** This is the main
  bug to fix.
- The exe name is also hardcoded in:
  - `tools/spike2_emu/vpx/vpxsetup.py:105` `find_vpx` (searches folders for `VPinballX64.exe`)
  - `tools/spike2_emu/vpx/vpxsetup.py:110` `vpx_version(folder)` (reads that exe's version resource)
  - `tools/spike2_emu/vpx/play_spike2.py:51` `resolve_vpx`
  - `Spike2Vpx.pyw:1135` file-picker filter
  - `README.md:75`
  - tests: `tests/test_play_spike2.py`, `tests/test_player_workflow.py`, `tests/test_spike2_vpx_setup.py`
- The app's Play button goes `spike2_vpx/player.py:403` `Player.play` →
  `setup.vpx_executable()` → `play_spike2.play(...)`.
- `play_spike2.play` (`tools/spike2_emu/vpx/play_spike2.py`) runs
  `<exe> -ExtMinimized [-Ini <temp ini>] -play <table>`. When B2S is disabled it
  copies the user's VPX INI to a temp folder and sets keys with
  `padvpx.vpx_ini_set` (`tools/spike2_emu/vpx/padvpx.py:247`). That temp-INI
  mechanism already exists and should be extended rather than duplicated.
- `Play-Spike2Vpx.ps1 -VpxExe <path>` (without `-AppGame`) passes the exe
  straight to `resolve_vpx`, which uses it as-is. **Phase 0 can launch the GL
  exe this way with no code changes.**
- Window handling:
  - The Stern LCD is a WSLg window titled
    `[rig N: PAD-VPX] <title> - Stern Spike 2 emulator (...)`, set by
    `XStoreName` in `tools/spike2_emu/padglhost.c`.
  - `padcontroller.find_kit_window` (`tools/spike2_emu/vpx/padcontroller.py:233`)
    finds windows by that title, and `vpx_lcd.Placement` uses it to place the
    LCD fullscreen on its assigned monitor.
  - `padcontroller._place_player` / `_frame_player` (around line 3044) move the
    VPX playfield window and make it borderless.
  - `spike2_vpx/cabinet.py` `apply` writes monitor assignments and B2S `.res` files.
- `PAD.Controller` returns Empty for `RawDmdPixels` / `RawDmdColoredPixels`
  (`padcontroller.py:3730`). VPX's script-driven DMD path is not used, and the
  full-colour LCD is too large to push through COM per frame anyway.
- Table patching replaces FlexDMD and UltraDMD with stub objects
  (`tools/spike2_emu/vpx/vpxshadow.py:752`).

## Facts from VPX 10.8.0 source

Tag `v10.8.0-2051-28dd6c3` of https://github.com/vpinball/vpinball.

- **VR exists only in the GL build.** `stdafx.h:110`: `ENABLE_VR` is defined
  only under `ENABLE_SDL` ("No VR support with DX9 possible"). The GL build is
  `cmake/CMakeLists_gl-win-x64.txt` (output name `VPinballX_GL64`, links
  `openvr_api`). The release ships both exes; the Developer GL zip contains
  only the GL exe.
- **VR on/off** (`src/core/player.cpp:126`): `[PlayerVR] AskToTurnOn`.
  - 0 = use VR whenever the SteamVR runtime is installed (`vr::VR_IsRuntimeInstalled`, not "running").
  - 1 = if SteamVR isn't running, ask in a message box.
  - 2 = VR disabled.
  - The player's default is **0**. The options dialog's default is 1. So a
    cabinet user who picks the GL exe and has SteamVR installed gets VR
    without asking for it. **The launcher must set this key on every GL launch
    (0 for VR, 2 for non-VR).**
- **External window capture** (`captureExt.cpp`, started at `player.cpp:1679`
  only in VR):
  - `[Player] CaptureExternalDMD = 1` captures a window found by `FindWindowA`
    on an **exact** title, then exact class, from: `"Virtual DMD"`, `"pygame"`,
    `"PUPSCREEN1"`, `"formDMD"`, `"PUPSCREEN5"`. The result goes to the DMD
    texture (`m_texdmd`) shown in the table's VR backbox.
  - `[Player] CapturePUP = 1` does the same for the backglass:
    `"PUPSCREEN2"`, `"Form1"`, `"B2S Backglass Server"`, `"B2S Background"`,
    `"B2S DMD"`. **B2S should just work.**
  - Capture uses DXGI desktop duplication, so the source window must be
    on-screen and not covered.
- Other `[PlayerVR]` keys: `VRPreview` (desktop mirror mode), `ShrinkPreview`.
  In VR, the `[PlayerVR]` section holds the window position instead of `[Player]`.
- Both builds read the same INI (`%APPDATA%\VPinballX\VPinballX.ini`, from
  `vpinball.cpp:183`) and both accept `-ExtMinimized`, `-Ini`, `-TableIni` and
  `-play` (`main.cpp:207-218`).
- VR runs unthrottled (OpenVR sets the frame pace) and the pause menu is
  disabled in VR (`player.cpp:4367`).

## The owner's VR PC: OpenComposite, not SteamVR

- `VPinballX_GL64.exe` (Panasony build 10.8.0.2079) imports `openvr_api64.dll`.
  In the VPX folder that DLL is **OpenComposite**: it translates OpenVR calls to
  OpenXR. The real Valve loader has been renamed `openvr_api64_steam.dll`.
- The active OpenXR runtime is Virtual Desktop
  (`HKLM\SOFTWARE\Khronos\OpenXR\1` → `virtualdesktop-openxr.json`). SteamVR is
  installed but isn't used.
- VPX's code path doesn't change: `AskToTurnOn`, the capture keys and the
  window-title lookup all behave the same.
- What does change: Phase 2 must not check for "SteamVR installed". The check
  should be a VR-capable exe plus any working OpenVR runtime (SteamVR, or
  OpenComposite with an OpenXR runtime).

## The core problem

For SPIKE 2 the Stern LCD *is* the game's main display. It's a WSLg desktop
window, so in a headset you would see the playfield but not the LCD. The only
way VPX 10.8 pulls an outside window into VR is the capture above. The
LCD's title doesn't match the capture list, and it can't simply be renamed,
because `find_kit_window` finds the LCD by that title.

## Plan

### Phase 0: manual test on the Windows VR PC (do this first)

You need: `VPinballX_GL64.exe`, SteamVR running with a headset, and a set-up
SPIKE 2 table with a VR backbox (Aerosmith "with VR" is listed in the README).

1. Back up `%APPDATA%\VPinballX\VPinballX.ini`, then set
   `[PlayerVR] AskToTurnOn = 0`, `[Player] CaptureExternalDMD = 1` and
   optionally `[Player] CapturePUP = 1`.
2. Launch:
   `.\Play-Spike2Vpx.ps1 -Card <image.raw> -Table <table.vpx> -VpxExe "<path>\VPinballX_GL64.exe"`
3. Note the starting state. Expected: playfield in the headset, LCD only on the
   desktop. Also confirm the controller, switches and game work under the GL build.
4. Run a helper script (to be written in the session scratchpad, not the repo).
   About 40 lines of Python with ctypes. It should:
   - find the LCD window the way `find_kit_window` does ("Stern Spike 2 emulator" in the title);
   - rename it to exactly `Virtual DMD` with `SetWindowTextW`;
   - confirm `FindWindowA(None, "Virtual DMD")` returns that window;
   - poll the title every second for about 60 seconds and report if WSLg changes it back;
   - optionally move the window fully on-screen and on top.
5. In the headset: does the LCD appear in the backbox, and does it update smoothly?
6. Restore the INI.

| Result | Next step |
|---|---|
| LCD shows in the headset and the title stays `Virtual DMD` | Phase 3 option (a) |
| LCD shows, but the title reverts | Re-apply the title from the launcher, or option (b) |
| VPX finds the window but the backbox is blank | The table's VR backbox doesn't use VPX's DMD texture; patch tables per title |
| VPX never finds the window, or the capture is black | Option (b) |

### Phase 0 results (2026-11-26)

Setup: JAWS 50th (PAD), `VPinballX_GL64.exe` 10.8.0.2079 (Panasony) through
OpenComposite and Virtual Desktop. Launched with
`Play-Spike2Vpx.ps1 -Python "<app>\python\python.exe" -Distro SPIKE2-VPX ...`.
The system Python lacks `olefile`. Monitors: main 0,0 2560x1440; 2nd
-2560,468 2560x1440.

- The playfield, controller, switches and game all work under the GL build in VR.
- Renaming the LCD with `SetWindowTextW` works: `FindWindowA("Virtual DMD")`
  returns it. The LCD's class is `RAIL_WINDOW` (shared by every WSLg window)
  and its owner is `msrdc.exe`, so class lookup is useless.
- With a windowed LCD fully inside one monitor, the whole LCD appeared in the
  VR backbox and updated smoothly. It is squashed vertically because the
  table's backbox DMD area is not 16:9. That is a per-table fix.
- **How VPX's capture works** (`captureExt.cpp` in 10.8.0):
  - It looks for the window by title until found, then keeps the **handle**.
  - One second later it binds to the **monitor** the window is on, and stays
    on that monitor for the rest of the session.
  - Every frame it re-reads the window's rect, clamped to that monitor. Moving
    the window within that monitor is followed live.
  - A window bigger than its monitor gives an invalid copy region, and nothing
    restarts a failed duplication.
- What that means for us:
  - The title only has to be `Virtual DMD` at the moment VPX finds the window.
    WSLg and the renderer put the old title back whenever the window is
    reconfigured; that is harmless once VPX has the handle.
  - The window must already be on its final monitor when VPX finds it.
- **A fullscreen LCD can never be captured.** Its `GetWindowRect` includes
  32 px of invisible border on every side, so it is larger than its monitor.
  VR mode needs a windowed LCD that fits inside one monitor.
- **Bug: the windowed LCD lands in the wrong place on multi-monitor setups.**
  `padisplay.save` writes x/y in Windows coordinates. `padglhost` uses them as
  X root coordinates, whose origin is the virtual desktop's top-left (here
  -2560,0). The window lands 2560 px too far left. The test used a hand-written
  `display.conf` line (`x=740 y=700` gives Windows -1820,700).
- **Desktop border around the captured LCD.** A windowed or Windows-placed LCD
  has a 32 px transparent shadow margin inside its `GetWindowRect`, and the
  capture shows the desktop through it.
  - Fix, confirmed in the headset: **X-native fullscreen**. A display.conf
    line with `fs=1` and the X-coordinate monitor rect (here `x=0 y=468
    w=2560 h=1440`), without `PAD_WINDOWS_LCD`'s Windows-side fullscreen. The
    window rect then equals the monitor exactly (-2560,468 to 0,1908), with
    no margin.
  - Cost: it takes up a whole monitor.
  - Untested fallback for single-monitor VR setups: a borderless black window
    just behind a windowed LCD, so the margin captures as black.
  - The change from window to fullscreen applied live, and VPX kept capturing,
    because the window stayed on the monitor VPX had bound to.
- Moving the WSLg window from the Windows side doesn't hold: activation, or the
  renderer re-applying display.conf, puts it back. Place it through display.conf.
- **GOTG (PUP table), 2026-11-26.**
  - VPX's DMD capture locked onto PUP's `PUPSCREEN5` (0,575 512x288). It
    exists before a late LCD rename, and VPX keeps the first match for the
    whole session.
  - Capture copies screen pixels at the target window's rect, so anything
    covering that rect shows in VR.
  - A windowed LCD (display.conf `mode=window border=0 x=2560 y=575 w=512
    h=288 fs=0`, in X coordinates) with its visible area exactly on PUP's rect
    and kept topmost showed **perfectly**: no border, no squashing. GOTG's
    backbox DMD area is presumably 16:9.
  - `mode=window` also keeps `PAD_WINDOWS_LCD`'s Windows-side fullscreen off.
    `play_spike2.py:229` turns it on for `mode=fullscreen`, and its 0.5 s
    placement loop fights any other position.
- **Phase 3 design, from these results: a placeholder target.**
  - Before starting VPX, the launcher creates its own borderless Win32 window
    titled `Virtual DMD` (no WSLg margin). It is first in VPX's search list, so
    it beats PUP.
  - The launcher places the windowed LCD so that its visible area exactly
    covers that window, and keeps it topmost.
  - The same path for PUP and non-PUP tables. Any monitor count. The LCD keeps
    its title, so the lookups stay as they are.
  - Needs the windowed-LCD coordinate fix.
  - **Confirmed on GOTG, 2026-11-26.**
    - Setup: a placeholder `WS_POPUP` window, `WS_EX_TOOLWINDOW |
      WS_EX_NOACTIVATE`, black brush, titled `Virtual DMD`, created before
      launch at 1500,100 1024x576, away from PUP's rect. The LCD's visible
      area sat on it via display.conf (X `x=4060 y=100 w=1024 h=576`) and was
      kept topmost.
    - The full LCD showed in the VR backbox with no border, even with
      `PUPSCREEN5` open.
    - The LCD had to be raised to topmost 9 times during startup, so the
      launcher must keep doing that.
    - **The target rect must lie fully inside one monitor.** At first it ran
      64 px past the main screen's right edge. VPX clamps the copy to the
      monitor, so the image came out shifted. After moving it 100 px left it
      was perfect, and VPX followed both moves live.
    - The script used: `docs/vr-phase0/placeholder.py`.
  - The backbox DMD aspect stays per table (JAWS squashes, GOTG fits).
- Earlier choice for Phase 3, replaced by the placeholder design above: option (a), without the mirror window. The launcher puts
  the LCD in a windowed spot that fits inside one monitor, then gives it the
  `Virtual DMD` title once before VPX starts searching. `padglhost` setting the
  title in VR mode is the cleaner version. Either way, the LCD lookup has to
  stop depending on the title (keep the handle).

### Phase 1: accept either exe

- In `vpxsetup`, keep one list of known VPX exes, with the build type as data,
  e.g. `VPinballX64.exe` (DX9) and `VPinballX_GL64.exe` (GL, VR-capable). No
  exe names anywhere else.
- `vpx_version` takes an exe path, not a folder.
- `find_vpx`, `Setup.vpx_executable`, `Setup.choose_vpx`, `resolve_vpx` and
  the file-picker filter all resolve through that list. `vpx_executable()`
  returns the exact saved exe.
- Update the README and tests. Confirm the GL exe has a readable version
  resource; `check_vpx` depends on it.

### Phase 2: VR setting per launch

- Add a VR setting (probably on the Cabinet tab), offered only when the
  selected exe is VR-capable and SteamVR is installed.
- On every GL launch, write `AskToTurnOn` (0 when VR is on, 2 otherwise) and,
  in VR, `CaptureExternalDMD` / `CapturePUP`.
- In VR mode, skip `cabinet.apply` monitor assignment,
  `_place_player` / `_frame_player`, and `.res` writing. Keep the LCD windowed
  and on-screen so capture can grab it.

### Phase 3: LCD in the headset (Phase 0 picks the option)

- **(a)** In VR mode, title the LCD window exactly `Virtual DMD`
  (`padglhost.c`), and change LCD lookup to something other than the title:
  the tracked window handle, the process, or a class.
- **(b)** A small Windows-side mirror window titled `Virtual DMD` that shows
  the LCD frames.
- Per table: check that the VR backbox shows VPX's DMD texture, given that
  FlexDMD/UltraDMD are stubbed. Fix the aspect ratio of the backbox DMD area,
  which isn't 16:9 (JAWS squashes the LCD vertically). Not yet looked at how the
  table defines that area. Likely fix: patch its size in `vpxshadow`, with the
  size per table as data.
- **Systematic fix for squashed backboxes such as JAWS (for later).**
  - In 10.8 the VR backbox DMD is a Flasher with `IDMD` set
    (`flasher.cpp:398`). VPX stretches the captured texture over the
    flasher's shape, which comes from its corner (drag) points. Those points
    can't be changed from the script.
  - Step 1: read the shape automatically. When patching, `vpxshadow` finds
    the `IDMD` flasher and takes the aspect ratio of its corner points'
    bounding box (to check: flasher rotation).
  - Option 1, the default (no table edits): **letterbox in the capture.**
    Give the placeholder window the flasher's aspect and centre the 16:9 LCD
    inside it. The placeholder is black, so the bars come out black. The
    picture is correct but doesn't fill the whole area.
  - Option 2, opt-in per table as data: **reshape the flasher.** Change its
    corner points in the patched copy to 16:9, keeping the centre. It fills
    the area, but it may overlap the backbox art, so check it per table.
- Fix the windowed-LCD coordinate bug (X root vs Windows coordinates) in
  `padisplay` before relying on a windowed LCD.

### Phase 4: polish

SteamVR setup check, a README VR section, and a "VR verified" column in the
supported-tables list.

## Open decisions (ask the owner)

1. **Where to write VR INI keys.** The temp `-Ini` copy throws away VR
   table-position tweaks the player makes in-game, because VPX saves them to
   the temp file. Writing to the real INI keeps them but changes the user's
   global VPX config. Recommendation: write to the real INI. Not yet answered.
   (The existing B2S-disabled path has the same issue, and VR combined with
   disabled B2S would lose tweaks.)
2. Where the VR setting lives in the UI. Proposed (2026-11-26):
   - A remembered "Play in VR" checkbox beside Play on the Games page.
   - Disabled, with a one-line reason, when the folder has no GL exe or no VR
     runtime is installed.
   - Export launch script and cabinet mode follow it.
   - No exe choice anywhere in the UI.

   Waiting for the owner's OK.

## Notes for the next session

- Run Claude Code natively on Windows (PowerShell), not inside WSL. VPX, the
  launcher and the window APIs are all Windows-side.
- The owner looks in the headset. Ask them to report what they see.
- Follow the owner's CLAUDE.md: one implementation per job, exceptions as data,
  commit only when asked.
