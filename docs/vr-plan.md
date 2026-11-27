# VR support plan

Goal: play SPIKE 2 tables in a VR headset through Visual Pinball X 10.8's
OpenGL build (`VPinballX_GL64.exe`), with the Stern LCD visible in the headset.

Status: planning. Nothing is implemented yet. Phase 0 (a manual test on the
Windows VR PC) comes next and decides how Phase 3 is built.

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
  FlexDMD/UltraDMD are stubbed.

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
2. Where the VR setting lives in the UI.

## Notes for the next session

- Run Claude Code natively on Windows (PowerShell), not inside WSL. VPX, the
  launcher and the window APIs are all Windows-side.
- The owner looks in the headset. Ask them to report what they see.
- Follow the owner's CLAUDE.md: one implementation per job, exceptions as data,
  commit only when asked.
