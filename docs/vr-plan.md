# VR support plan

Goal: play SPIKE 2 tables in a VR headset through Visual Pinball X 10.8's
OpenGL build (`VPinballX_GL64.exe`), with the Stern LCD visible in the headset.

Status (2026-11-26):

- **Phase 0 passed.** The live Stern LCD showed in the VR backbox, using a
  placeholder `Virtual DMD` window with the LCD kept on top of it.
- **Phase 1 is done.** Setup saves the VPX folder, and the app picks DX9 or
  GL from it.
- **Phase 2 is done** but not yet committed: a "Play in VR" checkbox, VR
  runtime detection, and the INI keys per launch. The table plays in the
  headset, but the LCD isn't there yet.
- **Own controller identity is done**, also not yet committed:
  `Spike2Vpx.Controller`, so the app no longer collides with Pinball Asset
  Decryptor.
- **Phase 3 is next:** the LCD in the headset.

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

### Phase 2: "Play in VR" per launch (done, not yet committed)

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

### Phase 3: the LCD in the headset (next)

This builds the placeholder design confirmed on GOTG, all in the launcher
(`play_spike2.py` / `vpx_lcd.py`).

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
    Check how flasher rotation affects this.
  - Default, no table edits: **letterbox in the capture.** Give the
    placeholder the flasher's aspect and centre the 16:9 LCD inside it. The
    bars come out black.
  - Opt-in per table, as data: **reshape the flasher** to 16:9 in the
    patched copy, keeping its centre. It fills the area, but check it
    against the backbox art.
  - Also check that every VR table's backbox uses VPX's DMD texture, given
    that FlexDMD/UltraDMD are stubbed (`vpxshadow.py:752`).
- Check that `CapturePUP` shows the B2S backglass in VR backboxes. Its
  window must be on-screen and uncovered.
- Add a README VR section: needs the GL build plus SteamVR, or OpenComposite
  with an OpenXR runtime (Virtual Desktop and others), and the checkbox.
- Add a "VR verified" column to the supported-tables list.

### Own controller identity (done, not yet committed)

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
2. **VR in the UI:** a remembered "Play in VR" checkbox beside Play. There's
   no exe choice in the UI (owner, 2026-11-26).
3. **The controller stays unchanged for VR**: window work lives in the
   launcher (owner, 2026-11-26).
4. **SPIKE 2 VPX gets its own controller identity**, moving old tables in
   place, so it can be installed beside Pinball Asset Decryptor (owner,
   2026-11-26).

Still open, for Phase 3:

- The default target monitor and size.
- Letterbox or reshape as the default for tables like JAWS (recommendation:
  letterbox).

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
