# ![SPIKE 2 VPX](assets/readme-banner.svg)

Play Stern SPIKE 2 games with Visual Pinball X on Windows x64. VPX runs the
playfield and the SPIKE 2 runtime runs the game, LCD, and audio. The bundled
`PAD.Controller` connects them.

## Download for Windows

### [Download SPIKE 2 VPX v0.1.0 for Windows x64](https://github.com/ajbergh/spike2-vpx/releases/download/v0.1.0/SPIKE2-VPX-Setup-0.1.0-x64.exe)

[Release notes](https://github.com/ajbergh/spike2-vpx/releases/tag/v0.1.0) ·
[SHA-256 checksum](https://github.com/ajbergh/spike2-vpx/releases/download/v0.1.0/SPIKE2-VPX-Setup-0.1.0-x64.exe.sha256) ·
[Setup instructions](#set-up)

Requires Windows 10 build 19044 or later (x64), WSL 2, and Visual Pinball X
10.8 or later (x64). Bring your own Stern SPIKE 2 SD-card image and compatible
VPX table.

### Initial Release

- The Windows launcher sets up a private WSL 2 runtime, imports SPIKE 2
  images, and prepares and launches [supported VPX tables](#supported-vpx-tables).
- Cabinet setup supports separate playfield, backglass, and Stern LCD displays,
  saved display profiles, and launch scripts for front ends.
- [Stern Expression Lighting](#cabinet-lighting) drives compatible Teensy LED
  controllers. The Lighting tab shows which outputs each image provides and
  can mirror speaker patterns onto blades when blade data is unavailable.

## Credits

**SPIKE 2 VPX** is a heavily modified fork of
[Pinball Asset Decryptor](https://github.com/davidvanderburgh/pinball-asset-decryptor)
by **David Vanderburgh**, extended with a Windows launcher, WSL 2 setup, VPX
table integration, cabinet display management, and expression lighting support.
All credit to David Vanderburgh for the underlying decryption and SPIKE 2
emulation foundation.

No Stern or game code is shipped in this repo.

## Screenshots

![Games tab with a sample Godzilla LE pairing ready to play](assets/screenshots/games.png)

<details>
<summary>Show setup and cabinet screenshots</summary>

![Setup checklist showing the WSL 2 requirement and virtualization help](assets/screenshots/setup.png)

![Cabinet tab with the playfield, backglass, and LCD assigned to three example screens](assets/screenshots/cabinet.png)

</details>

## Set up

Open **SPIKE 2 VPX** from the Start menu, or run `python Spike2Vpx.pyw` from a
checkout with x64 Python and Tcl/Tk. For a checkout, install the bundled
Python dependencies with `python -m pip install -r requirements-windows.txt`.

**WSL 2 (Windows Subsystem for Linux) and hardware virtualization are required.**
In the app, select **Set up** and approve the Windows administrator prompt.
Setup enables Virtual Machine Platform, installs or updates WSL as needed, and
imports the app's private `SPIKE2-VPX` distribution. If Windows requests a
restart, restart and reopen the app to continue setup.

If setup reports a virtualization problem, open **Task Manager → Performance →
CPU** and check **Virtualization**. If disabled, consult your PC manufacturer's
instructions for entering BIOS/UEFI. Enable **Intel Virtualization Technology
(VT-x)** or **AMD-V / SVM Mode**, save the firmware settings, and boot back into
Windows. Reopen the app and select **Set up**. A Windows virtual machine needs
nested virtualization enabled on its host.
[Microsoft's guide to enabling virtualization](https://support.microsoft.com/en-us/windows/experience/enable-virtualization-on-windows)

The checklist also covers WSLg display and audio, Visual Pinball X 10.8+ x64,
and the controller. **Get VPX** opens the VPX download page. After installing
VPX, use **Choose VPX** to pick its folder if the app doesn't find it. Desktop
play uses `VPinballX64.exe` (or `VPinballX_GL64.exe` if that's the only one
there). VR uses `VPinballX_GL64.exe`, and the Setup row shows whether the
folder has it.
Settings and setup logs are under `%LOCALAPPDATA%\Spike2Vpx`.

Setup verifies that WSL can execute an ARM program inside a chroot. It
repairs a missing ARM handler in the app's distro, and the launcher checks
again before preparing a game in case WSL has restarted. This repair keeps
your existing distribution, card images, and cache.

## Prepare and play

Supply your own SPIKE 2 SD-card image and a compatible VPX table. Godzilla LE
is the reference title. The VPX kit can create a patched copy of a recognized
table. Keep the patched table and `PADSPIKE2.vbs` together.

```powershell
python tools/spike2_emu/vpx/padvpx.py patch "C:\Tables\Godzilla limited edition.vpx"
.\Play-Spike2Vpx.ps1 -Card "C:\Images\godzilla_le.sdcard.raw" -Table "C:\Tables\Godzilla limited edition (PAD).vpx"
```

Browse **Supported Tables** to find the table version for your game and open
its download page where one is listed. In **Games**, **Get image from Stern**
opens Stern's download page. Use **Import image** with a local `.raw` or a ZIP
containing one `.raw`, or select a folder of raw images. The app reads the
title and edition from the image and checks space for the optional cache.
Choose a compatible VPX table to make a playable `(PAD).vpx` copy, or use an
existing prepared table. The app saves new conversions and their companion
files beside the original table. Prepared pairings appear in the game library.
Select **Play** to start the game and
open VPX. Closing VPX stops the run and returns to the library.

VPX opens directly in play mode with the editor hidden. With the bundled
controller, the table starts loading as soon as the launcher finds its Stern
session, while the emulator is still starting.

The runtime builds the guest filesystem from a card on its first run and
opens the source image read-only. Stern high scores and machine settings are
saved per title in the app's WSL runtime and reused on later launches. The
first launch after upgrading imports any existing save data it finds for
that title in the runtime's rig slots. The PowerShell launcher also accepts
`-VpxExe` and `-Distro` overrides. Manage game volume and card caching in
**Settings**.

## Supported VPX tables

Use the VPX release listed for your Stern SD-card edition. Some download
pages default to a newer release, so check their version history. The app's
**Supported Tables** tab lists the releases targeted by the
[bundled VPX maps](tools/spike2_emu/vpx).

The **Expression lighting** column shows outputs documented in at least one
build of that title. Support can vary by SD-card edition and software version.
**Unverified** means the project has no confirmed lighting result for that
entry. The **Lighting** tab checks your image for blades, speakers, and topper
separately at startup. [Device-table lighting survey](tools/spike2_emu/cablights.py)

| Stern game | SD-card edition | VPX release | Expression lighting |
| --- | --- | --- | --- |
| Aerosmith | Pro | [Aerosmith (Original 2021) 1.01](https://vpuniverse.com/files/file/13403-aerosmith-pro-sterntribute-2017-v102zip-with-vr/?changelog=3668) | Unverified |
| Batman ’66 | Batman ’66 (`batman`) | [Batman 66 1.1.0](https://vpuniverse.com/files/file/6868-batman-66-stern-tribute/) | Unverified |
| The Beatles | The Beatles (`beatles`) | [The Beatles (Original 2018) v007](https://orbitalpin.com/downloads/) | Unverified |
| Black Knight: Sword of Rage | LE | [Black Knight Sword Of Rage LE](https://vpuniverse.com/files/file/32118-black-knight-sword-of-rage-stern-2019/) | Unverified |
| Deadpool | Pro | [JP’s Deadpool 6.10](https://www.vpforums.org/index.php?app=downloads&showfile=15967) | Topper |
| Foo Fighters | Pro, LE | [JP’s Foo Fighters 0.5.0](https://www.vpforums.org/index.php?app=downloads&showfile=19519) | Speakers |
| Godzilla | LE | [Godzilla Limited Edition v2.6](https://vpuniverse.com/files/file/8449-godzilla-limited-edition/) | Topper |
| Guardians of the Galaxy | Pro, LE | [Guardians of the Galaxy 2.1.1](https://vpuniverse.com/files/file/6127-guardians-of-the-galaxy/) | Unverified |
| Iron Maiden: Legacy of the Beast | LE | [Iron Maiden (Original 2022) VPW 1.0.12](https://vpuniverse.com/files/file/12603-iron-maiden-legacy-of-the-beast-original-2022-vpw/) | Unverified |
| James Bond 007 | Pro, LE | [BOND for Visual Pinball X 4.3](https://vpuniverse.com/files/file/11827-bond-60-th/) | Unverified |
| JAWS | LE | [JAWS 50th Anniversary 3.2](https://vpuniverse.com/files/file/25943-jaws_50th_anniversary/) | Unverified |
| John Wick | Pro, LE | [John Wick 3.0](https://vpuniverse.com/files/file/32204-john-wick-legend/) | Blades |
| Jurassic Park | Pro, LE | [Jurassic Park Pro Le 4.02](https://vpuniverse.com/files/file/20502-jurassic-park-pro-le/) or [Jurassic Park 30TH LE Tribute 2.0](https://vpuniverse.com/files/file/20485-jurassic-park-30th-le-stern-2023-tribute/) | Unverified |
| Metallica Remastered | SPIKE 2 (`metallica_spike`) | [Metallica Premium Monsters VPW 2.0.2](https://vpuniverse.com/files/file/6058-metallica-premium-monsters-stern-2013-vpw-mod/) | Blades |
| The Munsters | Pro | [Munsters (Original 2020) 1.05](https://vpuniverse.com/files/file/10068-munsters-original-2020-105vpx/) or [The Munsters Pro MOD 1.0.0](https://vpuniverse.com/files/file/33195-the-munsters-prooriginal-2020-mod/) | Unverified |
| Rush | LE | [Rush LE Tribute 2.0.2](https://vpuniverse.com/files/file/32514-rush-le-tribute-20/) | Blades, speakers |
| Star Wars (2017) | Pro | Llyrric’s Stern-layout build dated July 13, 2025. [Author’s beta thread](https://vpuniverse.com/forums/topic/6988-star-wars-2017-stern-inspired/page/2/) | Topper |
| Teenage Mutant Ninja Turtles | Pro | [Teenage Mutant Ninja Turtles (Stern–Data East mash-up) v2.86d](https://vpuniverse.com/files/file/22296-teenage-mutant-ninja-turtles-stern-data-east-remix-v286-table/) | Unverified |

### SPIKE 2 games with no known public VPX table

As of November 24, 2026, these titles had no public VPX table located for
their Stern playfield. The Home Edition games have their own layouts.
[SPIKE 2 game list](https://www.pinwiki.com/wiki/index.php/Stern_SPIKE%E2%84%A2_System_Repair#SPIKE_2)

- Avengers: Infinity Quest
- Dungeons & Dragons: The Tyrant’s Eye
- Heavy Metal
- Jurassic Park Home Edition
- King Kong: Myth of Terror Island
- Led Zeppelin ([a same-theme VPX original exists](https://vpuniverse.com/files/file/5940-led-zeppelin-pinball/))
- Star Wars Home Edition (2019)
- The Uncanny X-Men
- Venom

Public VPX projects also exist for the following titles. This project has no
bundled maps for those releases.

- Elvira’s House of Horrors ([Elvira VPX mash-up](https://vpuniverse.com/files/file/26714-elvira-mash-up-blood-red-kiss-edition/))
- Stranger Things ([community VPX release](https://vpuniverse.com/files/file/25396-stranger-things/))
- The Mandalorian ([community VPX release](https://vpuniverse.com/files/file/16087-the-mandalorian/))

## Cabinet lighting

Stern Expression Lighting has been tested on a physical cabinet with a
DOF-compatible Teensy strip controller. In **Lighting**, detect or browse to
your DOF `Cabinet.xml`. Assign the detected fixtures, use **Test fixture** to
check their colors and direction, and enable **Use Stern expression lighting
in SPIKE 2 games**. The optional **Use speaker lighting when blade data is
unavailable** setting mirrors the game’s speaker pattern to any assigned
blade that lacks its own data. Select **Save lighting** to apply the setup.

SPIKE 2 VPX claims the Teensy during the game and clears and releases it when
VPX closes. Ordinary VPX sessions can then drive the strips through DOF using
the same cabinet configuration.

## Cabinet displays and front ends

Open **Cabinet** and select **Identify screens**. Assign the VPX playfield,
B2S backglass, and Stern LCD to separate screens, or start with the
**Single-screen preset**. Select **Test layout** to preview the assignments
before saving. Use VPX windowed mode for app-managed playfield placement.
Under **Stern LCD mode**, choose **Borderless fullscreen** or **Windowed**,
then select **Save display layout**. Borderless fullscreen uses the screen
selected under **Stern LCD screen**. The **Automatic (spare screen)** default
uses a spare secondary screen when available and opens a window otherwise.
Windows places the fullscreen LCD using the same display coordinates as
**Identify screens**.
When the cabinet and Windows display numbers differ, Cabinet shows both.
The renderer starts at the selected screen's size for fullscreen play.
The single-screen preset uses VPX and B2S defaults and a windowed Stern LCD.

A managed backglass needs 64-bit B2S Server and a matching `.directb2s`
file. The app carries over a matching file when it patches a table. Use
**Attach backglass** if you downloaded it separately. A custom table
`.res` file takes precedence over the app's backglass placement.
Choose **Disabled** under **B2S backglass** and save the layout to play
without B2S. Select a screen or **B2S default** to turn it back on.

In **Games**, select a prepared game and choose **Export launch script**.
For LaunchBox, use the exported `.bat` as the game's **Application Path**
and leave emulator selection off. The script uses the current SPIKE 2 VPX
settings and stays running until VPX closes. Export again after moving
the app, table, or image to a different path.

## Library and maintenance

In **Games**, use the library cards to see which editions are ready and which
need an image, table, or setup. The detail view shows the matched VPX release
and an SD image version when its filename has one. **Show details** reveals
paths and logs. Add favorites and optional local PNG or GIF artwork, and use
**Recently played** to find games you launched.

The app includes small PNG previews in `assets/backglasses/`. Add a PNG
named for a title's detected ID, such as `godzilla_le.png`, to bundle a
preview for that title. Use artwork you can redistribute. The app previews the
main image in the matching local `.directb2s` beside a prepared table. A
player's custom artwork takes priority. If the backglass has no usable
image, the app uses the bundled title preview or `default.png`.

Press **F11** for the fullscreen cabinet library. Use Up/Down or cabinet
flippers mapped to the left/right Shift keys, Enter or Space to select, and
Esc to leave. In **Cabinet**, choose **Desktop** or **Cabinet** and save your
screen assignments to that profile. **Load profile** applies a saved layout.
**Test layout** outlines the assigned screens. **Test speakers** plays a tone
using the current volume and the Windows default output.

If playback fails, the launch screen shows the last stage reached and a next
action. **Recover session** appears after the app verifies a stale record with
an expired heartbeat and no live processes in its slot. Active or unverifiable
sessions must be closed before retrying.

In **Settings**, **Preview support report** shows the exact text you can save
as a diagnostic ZIP. **Back up library** stores your pairings, artwork paths,
favorites, play history, display profiles, and preferences as JSON. Copy your
image, table, and artwork files separately when moving to another PC. After
restoring, use **Locate image** or **Locate table** for files that moved and
verify the display assignments on the new PC.

## Build and test

Use **Actions → Windows installer → Run workflow** to build an installer.
Enter a version such as `0.1.0`. The workflow runs the tests, compiles the
installer, and smoke-tests it by installing it on a Windows runner and
loading the installed application with its bundled Python. Download the
versioned x64 installer and its SHA-256 file from the workflow run's
**Artifacts** section.

Pushing a tag such as `v0.1.0` uses the tag as the installer version and
attaches the tested installer and checksum to a draft GitHub Release.
The installer is currently unsigned. Review the draft and publish it from
**Releases** when ready.

### Build locally

Run `.\scripts\build-windows-installer.ps1` with full x64 Python with Tcl/Tk
and Inno Setup 6.3 or later. The build writes
`installer\Output\SPIKE2-VPX-Setup.exe`. The installer bundles the tools and
Python. The first setup downloads the upstream runtime image and verifies
its pinned SHA-256. Uninstall preserves the private runtime and player data.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## License

Licensed under the [MIT License](LICENSE). Original work Copyright (c) 2026
David Vanderburgh; SPIKE 2 VPX modifications and additions Copyright (c) 2026
Adam Bergh.
