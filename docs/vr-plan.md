# VR support plan

Goal: play SPIKE 2 tables in a VR headset through Visual Pinball X 10.8's
OpenGL build (`VPinballX_GL64.exe`), with the Stern LCD visible in the headset.

Status (2026-11-26):

- **Phase 0 passed.** The live Stern LCD showed in the VR backbox, using a
  placeholder `Virtual DMD` window with the LCD kept on top of it.
- **Phase 1 is done.** Setup saves the VPX folder, and the app picks DX9 or
  GL from it.
- **Phase 2 is done** (commit `16b651001`): a "Play in VR" checkbox, VR
  runtime detection, and the INI keys per launch. The owner played a table
  in the headset with it.
- **Own controller identity is done** (same commit): `Spike2Vpx.Controller`,
  so the app no longer collides with Pinball Asset Decryptor. With it, VPX
  gets the keyboard by itself.
- **Phase 3 is done:** the LCD in the headset, checked by the owner in the
  headset on JAWS and GOTG.
- **Phase 4's backbox fit is done:** DMD flashers fitted to 16:9 and made
  opaque, placed per table from the map, and a VR-only LCD added to tables
  without a VR room. The owner checked JAWS, GOTG, John Wick and Godzilla
  in the headset. Still to do from Phase 4: the B2S backglass check, the
  README VR section, and a "VR verified" column.

See "Plan" below.

## Background: how the app found and launched VPX (before Phase 1)

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
way VPX 10.8 pulls an outside window into VR is the capture above. Phase 0
found how to feed it: a placeholder window, described below.

## Plan

### Phase 0: manual test on the owner's VR PC (done 2026-11-26)

These were hands-on tests in the headset, with scratch scripts and
hand-written display.conf lines, to learn how VPX's capture behaves. The
first test renamed the LCD window to `Virtual DMD`. Later tests covered PUP's
DMD rectangle, then used the placeholder window.

#### Results

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

### Phase 1: choose the VPX folder, not an exe (done, commit `1bc4ae06a`)

- `vpxsetup.VPX_EXES` is the single list of players, with the build as data:
  `VPinballX64.exe` (DirectX 9) and `VPinballX_GL64.exe` (OpenGL, `vr: True`).
  No exe names appear anywhere else.
- Setup saves the **folder** (`vpx_dir`). Choose VPX is a folder picker; picking
  an exe means its folder.
  - An older saved `vpx_exe` is read as its folder.
  - `vpx_exe` is still written (the desktop exe), because app 0.1.0 shares
    `setup.json` and reads only that key.
- `Setup.vpx_executable(vr=False)` picks the exe:
  - desktop play: DX9, or GL when it is the only one there;
  - VR: GL.
- `vpx_version` takes an exe path.

### Phase 2: "Play in VR" per launch (done, commit `16b651001`)

- **UI.** A remembered "Play in VR" checkbox beside Play on the Games page
  (`settings["vr"]`).
  - Hidden when the VPX folder has no VR player.
  - Greyed out, with the reason under it, when no runtime is found.
  - It can always be turned **off**, so a broken VR setup never blocks play.
  - Cabinet mode and exported launch scripts follow it, because both go
    through `Player.play`.
- **Availability** (`vpxsetup.vr_runtime`). VPX loads the
  `openvr_api64.dll` beside it, and that decides what it needs:
  - **OpenComposite** (the DLL contains "OpenComposite"): needs the active
    OpenXR runtime (`HKLM\SOFTWARE\Khronos\OpenXR\1` `ActiveRuntime`). The
    name shown is taken from its manifest.
  - **Valve's loader**: needs the runtime SteamVR registers
    (`%LOCALAPPDATA%\openvr\openvrpaths.vrpath`).
  - The Setup row shows the result, e.g. "VR ready (VirtualDesktopXR (Bundled)
    through OpenComposite)", or "VR unavailable. <why>".
  - `Setup.vr_status()` caches it as `Setup.vr` for the UI.
- **Launch.** `Player.play` reads the setting.
  - If VR is on but unavailable, it refuses with the reason.
  - Otherwise it calls `play_spike2.play(..., vr=)` with
    `vpx_executable(vr=)`.
- **INI keys** (`vpxsetup.VR_INI`, applied by `play_spike2.vr_ini`), for
  VR-capable players only:
  - VR: `[PlayerVR] AskToTurnOn = 0`, `[Player] CaptureExternalDMD = 1`,
    `CapturePUP = 1`.
  - Desktop launch of the GL build: `AskToTurnOn = 2`. VPX's default is 0,
    so without this the GL build would go into VR whenever a runtime is
    installed.
  - DX9: nothing.
  - Decision (open question 1): the keys go into the user's **real** INI and
    their old values are put back after VPX exits. VR table-position tweaks
    made in-game are therefore kept, and the user's global config is
    unchanged afterwards.
  - With B2S disabled, the run already uses a temp INI copy, and the keys go
    there. VR tweaks made in that combination are lost, as before.
- **Command line.** `Play-Spike2Vpx.ps1 -Vr` / `play_spike2.py --vr`. In VR, a
  non-VR exe (such as the saved `vpx_exe`) stands for its folder, whose VR
  player is used.
- **Not done, on purpose:**
  - The controller's VR behaviour is unchanged, and all VR window work lives
    in the launcher. Its LCD handling only raises the LCD to topmost, which
    helps.
  - `cabinet.apply` / `.res` writing still run in VR. They keep the B2S
    backglass on a screen, where `CapturePUP` can grab it.
- **What a Phase 2 VR launch gives:** the table plays in the headset, but the
  LCD still opens wherever display.conf puts it, so it isn't in the headset
  yet. That is Phase 3.

### Phase 3: the LCD in the headset (done)

This builds the placeholder design confirmed on GOTG, all in the launcher
(`play_spike2.py` / `vpx_lcd.py`). What was built:

- **Coordinates.** `padisplay.place()` gives the window's rect in Windows
  coordinates (`padloading` uses it). `resolve()` writes the display.conf
  line in X root coordinates (`x_origin`: the smallest monitor left/top).
- **Target.** `vpx_lcd.vr_target`: 1360x768 (`VR_SIZE`), scaled to fit 90%
  of the monitor, centred on the monitor display.conf names (the cabinet's
  LCD screen, as `Player.play` has just written it), else the main one.
- **`vpx_lcd.VrLcd`**, opened by `play_spike2.play(vr=True)` before the run
  starts and closed after it stops:
  - It writes a `mode=window border=0` line at the target, so
    `fullscreen_target()` / `PAD_WINDOWS_LCD` stay off.
  - It opens a `CaptureTarget`: the `Virtual DMD` window, on its own thread,
    which keeps the LCD topmost over the target by z-order only.
  - It puts the user's display.conf back byte for byte, or removes it if
    there was none.
- **INI line endings.** `padvpx.vpx_ini_set` now keeps the file's CRLF and
  BOM. Before, the Phase 2 key put-back rewrote VPX's INI with LF endings,
  with the same contents.
- **Tests:** `tests/test_vr_lcd.py` (coordinates, target, VrLcd put-back,
  launch order, a real Win32 capture window, INI endings).
- **Live check without the headset** (2026-11-26, JAWS, `play_spike2.py
  --vr`, owner's two-monitor PC):
  - The capture window was at Windows (-1960, 804) 1360x768, centred on the
    LCD screen.
  - The LCD's window rect was exactly that plus WSLg's 32 px margin, so its
    picture sat on the target. The LCD was in front at the centre and
    corners, and 207 of 209 sample points over the target showed the game.
  - VPX loaded Virtual Desktop's OpenXR runtime through OpenComposite. With
    no headset streaming, OpenComposite showed "OpenComposite Error - info in
    log" and VPX went back to its editor. That is expected without a headset.
  - After VPX was closed, display.conf was back byte for byte, the rig was
    released, and the VR INI keys had their earlier values.
- **Headset check:** JAWS and GOTG from the app, by the owner (2026-11-27).
  One-monitor PCs aren't checked yet; the target there is centred on the
  main screen, under the LCD, over VPX's preview window.

The original steps:

1. **Fix the windowed-LCD coordinate bug first.**
   - `padisplay` writes the game window's x/y in Windows coordinates, but
     `padglhost` uses them as X root coordinates. Under WSLg the X origin is
     the virtual desktop's top-left: the smallest monitor left/top, here
     (-2560, 0).
   - So convert when writing the line (x - min_left, y - min_top), and test it
     with monitors left of and above the main one.
   - This also fixes windowed LCDs for non-VR users with that monitor layout.
2. **Choose the target rect (as data):** where the LCD is captured from.
   - It must lie fully inside one monitor, on-screen and uncovered.
   - Default: the LCD's own monitor from the cabinet layout if one is
     assigned, else the main monitor. 16:9, about 1024x576, away from the VPX
     preview window.
   - Refuse clearly if no monitor can hold it.
3. **Placeholder window.** A launcher-owned borderless `WS_POPUP` window
   titled `Virtual DMD` (`WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`, black brush)
   at the target rect.
   - It runs on its own thread with a message loop. It must be created
     **before** VPX starts, so it wins over PUP's windows, and it is
     destroyed in the run's cleanup.
   - `docs/vr-phase0/placeholder.py` is the tested reference.
4. **LCD over it.** For the run, write a display.conf line with
   `mode=window border=0 fs=0` and the target rect in X coordinates. Put the
   user's line back after the run, like the INI keys.
   - `mode=window` keeps `vpx_lcd.fullscreen_target()` and
     `PAD_WINDOWS_LCD` off, so their placement loop can't fight the window.
5. **Keep the LCD topmost over the target** for the whole session, by
   z-order only. In Phase 0 the LCD was pushed back 9 times during startup.
   - Find the LCD by its title as today. It is never renamed, so the title
     lookups stay as they are.
6. **Tests**, then **headset checks:** JAWS (no PUP) and GOTG (PUP), started
   from the app with the checkbox, and with one monitor and with two.

### Phase 4: per-table fit and polish

- **Squashed backboxes such as JAWS.** In 10.8 the VR backbox DMD is a
  Flasher with `IDMD` set (`flasher.cpp:398`). VPX stretches the captured
  texture over the flasher's shape, which comes from its corner (drag)
  points. Those points can't be changed from the script.
  - Step 1: read the shape automatically. `vpxshadow` or the launcher finds
    the `IDMD` flasher and takes its corner points' bounding-box aspect.
    - Checked against VPX source (`flasher.cpp` around line 1157): the
      texture is mapped over the drag points' x/y bounding box (image
      alignment Wrap), then the flasher is rotated rigidly (`FROX` etc.,
      about -84° to stand it up). So the shown aspect is that bounding box's
      width/height, and rotation doesn't change it.
    - Measured 2026-11-26 (read-only probe of the `(PAD)` tables: Flasher
      items with `IDMD` set, `VCEN` of each `DPNT`):

      | Table | DMD flashers | Aspect (16:9 = 1.778) |
      |---|---|---|
      | JAWS | `DMD` 585x149, `DMD002` 653x164 | 3.92, 3.99: classic 128x32 shape, hence the squash |
      | GOTG | `DMD` 625x364 | 1.72: close to 16:9, which is why it looked right |
      | John Wick | none | no DMD in the VR backbox at all |
      | Godzilla | none | no DMD in the VR backbox at all |

    - So some tables have **no `IDMD` flasher**, and the LCD can't appear in
      their backbox without adding one (an opt-in table edit, as data), or
      showing it some other way. Check the VR rooms of the other supported
      tables the same way.
    - What letterbox costs on JAWS: a 3.92:1 area on a 2560-wide screen is
      at most about 2304x588. The 16:9 LCD inside it is 1045x588, so it fills
      less than half the DMD's width in the headset, but isn't distorted.
      Reshaping the flasher to 16:9 fills it, but grows it over the backbox
      art.
  - **Reshape (built, owner's choice 2026-11-27, Decision 5).**
    `vrfit.backbox_in_place`, from `play_spike2.fit_for_vr` (both callers,
    VR launches only, after `own_controller`):
    - Each `IDMD` flasher keeps its width and gets a 16:9 height, anchored
      at the bottom and growing upwards. Taller-than-16:9 ones (GOTG) get a
      little shorter from the top. Within 1% it's left alone, so it runs
      once.
    - VPX places the flasher about its bounding-box centre (`RenderSetup`
      recomputes it; the saved `FLAX`/`FLAY` are not used) at `FHEI`, then
      RotateX (row vectors: y' = y cos a, z' = y sin a). So the centre moves
      by -cos(a)·dh/2 in y and the height by -sin(a)·dh/2, which keeps the
      bottom edge in place. A flasher turned about Y or Z is left as it is,
      with a log line.
    - GameItems aren't in the MAC: the streams are replaced via a `.tmp`,
      verified and `os.replace`d, as `padmigrate` does.
    - Checked on a scratch copy of JAWS: `DMD` 585x149 → 585x329, height
      561 → 650.4; `DMD002` 653x164 → 653x368. Both verify, and the
      bottom-edge world position matches to 0.1 units. A second run changes
      nothing. Tests: `tests/test_vrfit.py`.
    - First headset look (JAWS, 2026-11-27): the right size, but the art
      behind showed through the picture. JAWS's `DMD` has ModulateVsAdd
      (`MOVA`) 0.9 with additive blend. VPX blends a DMD flasher when `MOVA`
      is under 1 and draws it solid at 1, which was hidden while it sat
      on the backbox's black DMD window. So the fit also sets `MOVA` to 1,
      on its own for tables already reshaped. GOTG's is 0.9 too (not
      additive). `DMD002` is already 1.
    - Second look: opaque and right, but a little off in size and place. So
      a table's map can place each DMD flasher, as data: `"vr_backbox":
      {"DMD": {"width": 570, "x": 463, "bottom": 490}}` (table units:
      picture width, centre x, bottom edge height above the playfield; the
      bottom edge keeps its depth). The values are absolute, so playing again
      is a no-op, and a table already reshaped lands in the same place. The
      automatic fit is the same function with the flasher's own values.
      JAWS: the automatic fit's values (585, 463, 486.8) looked close. The
      owner's try at 620, 438, 450 showed only the top of the picture. The
      first version kept the bottom edge's depth, so 37 units lower stood the
      whole picture 4 units further back. The backbox has a dark surface just
      behind the DMD window at nearly the same tilt, and with two nearly
      parallel surfaces a 4-unit shift moves their crossing line a long way,
      so most of the picture was behind it. Now a move stays in the plane
      the flasher stands in (`reshaped`; test: every corner on the author's
      plane). The owner's JAWS was put back on that plane by hand
      (scratchpad `jaws_repair.py`).
    - Placing it from the table, not by eye: the dark surface is
      `PinCab_DMD`, one textured quad 1.3-7.2 units behind the flasher's
      plane. Its texture's black screen window (found by pixel scan),
      mapped through the quad's corners into the flasher's plane, gives
      the window: width 648, x 464, bottom 470.5, 383 tall (1.69:1). The
      picture stays 16:9 and fills the window's full height (owner): JAWS's
      map is width 681, x 464, bottom 470.5, overhanging the sides by about
      16 units each.
      The same method works for other tables whose cabinet has a DMD panel
      texture; the probes are in the scratchpad (`prim_probe.py`,
      `image_out.py`, `black_window.py`).
  - Letterbox (black bars in the capture) was the alternative; not built.
  - Also check that every VR table's backbox uses VPX's DMD texture, given
    that FlexDMD/UltraDMD are stubbed (`vpxshadow.py:752`).
- Check that `CapturePUP` shows the B2S backglass in VR backboxes. Its
  window must be on-screen and uncovered.
- Add a README VR section: needs the GL build plus SteamVR, or OpenComposite
  with an OpenXR runtime (Virtual Desktop and others), and the checkbox.
- Add a "VR verified" column to the supported-tables list.

### Own controller identity (done, commit `16b651001`)

- **Why.** SPIKE 2 VPX is a fork of Pinball Asset Decryptor and kept its
  COM identity, `PAD.Controller`. Windows keeps one registration per name, and
  the last app to register wins. On the owner's PC that was PAD, so every
  table ran PAD's older controller.
  - Found in the first Phase 2 VR test: the owner had to click VPX before
    playing. PAD's copy doesn't hand the keyboard back to VPX on runs the
    launcher starts (no `external_start`). Its log showed no hand-back.
  - Settings also leaked between the two apps (PAD's `player` placement in
    `~\.pad-vpx.json`).
- **Identity.** `controller_id.py` holds the name `Spike2Vpx.Controller` and
  its own CLSID, plus the legacy pair. Registration, Setup's check, the
  launcher's check, `padvpx status` and `vpxshadow`'s generated script all
  take the name from there. `PADSPIKE2.vbs` is static text, and
  `tests/test_controller_id.py` keeps it in step.
- **Tables prepared under the old name** are moved to the new one where they
  are, on Play (`padmigrate.controller_in_place`, called from `Player.play`
  and the CLI):
  - Scripted tables: the `CreateObject` line and its error message are
    rewritten, and the table is re-signed and verified, as
    `vpxsounds.quiet_in_place` does. If it doesn't verify, it's left as it
    was and Play refuses.
  - ROM tables: a legacy `PADSPIKE2.vbs` beside the table is replaced with
    this app's copy, as preparing a table already does.
  - `patched_script` accepts both names.
- **Registration.** Setup registers the new name. It also unregisters the
  legacy name, but only when it points at this installation (an upgrade from
  0.1.0). Pinball Asset Decryptor's registration is never touched.
- **Still shared:** the `PADSPIKE2.vbs` file name. A ROM table prepared by
  each app in one folder shares one helper, and the last app to prepare or
  play it wins. Renaming it would need all four ROM patchers changed.

### After the phase 3-4 commit

- **VR runs saved the preview window as the desktop playfield placement.**
  The controller's `_watch_player` saves where VPX's window settles as the
  kit's `player`; in VR that window is VPX's 640x640 preview, so every
  later desktop run was shrunk to 640 wide. That saving (inherited from
  Pinball Asset Decryptor's hand-moved windowed player) is removed: in this
  app `player` belongs to the cabinet layout and `padvpx player`. The
  owner's bad value was removed by hand.
- **The template's own score display floated left of the table**, in VR
  and on the desktop (JAWS, JP Pro LE, Foo Fighters, Deadpool: JPSalas's
  template). It's 42 flashers (`Digits = Array(digit001...)` and
  `digitgrid`) at x about -1100 to -340 showing the old rules' text, which
  the Stern game no longer drives. The script sets their image and
  visibility, so `scoredisplay.hide_in_place`, on every Play (both
  callers, after `own_controller`), gives them opacity 0 (FALP), which VPX
  doesn't draw. Found from the script's own `Digits = Array`, so no
  per-table data. Checked on copies of JAWS and JP Pro LE (42 hidden each,
  verify, second run no-op) and GOTG (commented-out display, untouched).
- **A VR room's DMD can be saved hidden with nothing to show it**
  (VR_Room_JPs_Deadpool_1.8: flasher `DMD`, FVIS 0, and the script's own
  `Sub DMD` takes that name, so it can't reach it). The fit now also makes
  a hidden DMD flasher visible (not `PadVrLcd`, hidden on purpose). Checked
  on a copy: made visible, verify, second run no-op; JAWS and GOTG
  untouched.
  - In the headset its spot was blocked by the backbox's DMD frame, so
    `deadpool_pro`'s map puts it over the backglass art instead: 1180 wide
    (the glass is 1239), x 473, its bottom at 780, just above the grey
    divider (top face 778), as the owner asked. Both Deadpool downloads share that map, and the
    other has no `DMD` flasher, so a `vr_backbox` entry for a flasher a
    table hasn't is now skipped instead of refused.
- **Jurassic Park 30th LE has no VR room or cabinet models**, so in VR only
  the playfield (and the added `PadVrLcd`) shows. A table matter; a VR-room
  version of the table is the fix.

### Follow-ups outside VR

- The `PADSPIKE2.vbs` name collision above.
- The B2S-disabled temp-INI path loses every in-game VPX setting change,
  not just VR ones.
- The Windows-side fullscreen LCD (`PAD_WINDOWS_LCD`) leaves WSLg's 32 px
  shadow margin outside the monitor. That's harmless on the desktop, but it's
  why that LCD can't be captured.

## Decisions

1. **VR INI keys:** set in the user's real INI for the launch and put back
   afterwards. With B2S disabled they go into the run's temp copy instead.
   (Owner agreed to Phase 2 on 2026-11-26.)
2. **VR in the UI:** a remembered "Enable VR" checkbox beside Play, shown
   only when Play is; ticked, the button reads "Play in VR". There's no exe
   choice in the UI (owner, 2026-11-26/27).
3. **The controller stays unchanged for VR**: window work lives in the
   launcher (owner, 2026-11-26).
4. **SPIKE 2 VPX gets its own controller identity**, moving old tables in
   place, so it can be installed beside Pinball Asset Decryptor (owner,
   2026-11-26).
5. **Backbox DMDs are reshaped to 16:9**, anchored at the bottom and growing
   upwards, in the table where it is, on VR Play (owner, 2026-11-27). A
   table's map can place it (`vr_backbox`), always 16:9.
6. **The capture target** stays the LCD's screen, else the main one,
   centred, 1360x768 or smaller (owner, 2026-11-27).
7. **Tables with no VR room get a large LCD** where the backbox would be,
   so they're playable (owner, 2026-11-27). `vrfit.added_flasher`: a DMD
   flasher `PadVrLcd`, 85% of the table's width, centred, bottom edge 470
   up and 40 in front of the table's top, tilted -84°, saved hidden. A line
   appended to the script (`If RenderingMode = 2 Then PadVrLcd.Visible =
   True`) shows it in VR only. Added once, on VR Play, re-signed and
   verified; a map's `vr_backbox` places it like any other. Checked on
   copies of John Wick and Godzilla: one item added, the script otherwise
   the same, both verify, and a second run does nothing. Not yet seen in
   the headset.

Still open: nothing.

## Notes for the next session

- Run Claude Code natively on Windows (PowerShell), not inside WSL. VPX, the
  launcher and the window APIs are all Windows-side.
- The owner looks in the headset. Ask them to report what they see.
- Follow the owner's rules: one implementation per job, exceptions as data,
  commit only when asked.
- To run the dev app, use the installed app's Python
  (`D:\Program Files\SPIKE 2 VPX\python`), because the system Python lacks
  `olefile`. Its `python313._pth` puts the *installed* app folder on the path
  rather than the script's folder, so put the repo first:
  `python.exe -c "import sys, runpy; sys.path.insert(0, r'<repo>'); runpy.run_path(r'<repo>\Spike2Vpx.pyw', run_name='__main__')"`.
  - Setup registers `Spike2Vpx.Controller` to the checkout it runs from,
    with an administrator prompt. Pinball Asset Decryptor keeps
    `PAD.Controller`.
- Tests: a venv with `requirements-dev.txt`, then `python -m pytest -q`.
