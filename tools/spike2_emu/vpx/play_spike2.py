"""Run a prepared SPIKE 2 title alongside its PAD-patched VPX table."""

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
from shutil import copyfile
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4
from xml.etree.ElementTree import ParseError

# PAD's embedded Windows Python does not add the script directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller_id  # noqa: E402
import padcontroller  # noqa: E402
import padlaunch  # noqa: E402
import padlighting  # noqa: E402
import padmigrate  # noqa: E402
import vpx_lcd  # noqa: E402


def embedded_script(table):
    import olefile
    from vpxfile import biff_records

    # Only the embedded script is needed. Skip the table's other streams.
    with olefile.OleFileIO(str(table)) as ole:
        data = ole.openstream("GameStg/GameData").read()
    return next((body[4:].decode("utf-8", "replace")
                 for tag, body, _ in biff_records(data) if tag == "CODE"), "")


def patched_script(script):
    # The legacy name too: Play moves those tables to this app's (padmigrate).
    return any(marker.lower() in script.lower() for marker in
               ("padspike2.vbs", controller_id.PROGID, controller_id.LEGACY_PROGID))


def read_title(table, script=None):
    from vpxsetup import script_title

    if script is None:
        script = embedded_script(table)
    title = script_title(script)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", title) or not patched_script(script):
        raise ValueError("The table needs an embedded PAD controller script and title.")
    return title


def own_controller(table, script):
    """Move a table prepared for the legacy PAD.Controller to this app's
    controller where it is (padmigrate). Returns what was changed."""
    try:
        return padmigrate.controller_in_place(str(table), script)
    except OSError as exc:
        raise RuntimeError(f"Could not move this table to the {controller_id.PROGID} controller. {exc}") from exc


def hide_score_display(table, script):
    """Hide the table's own score display where it is (scoredisplay): the
    Stern LCD replaces it. Returns what was changed."""
    import scoredisplay

    try:
        return scoredisplay.hide_in_place(str(table), script)
    except OSError as exc:
        raise RuntimeError(f"Could not hide this table's own score display. {exc}") from exc


def fit_for_vr(table, title):
    """Give the table's VR backbox DMD the LCD's 16:9 shape where it is, placed
    as the title's map says (vrfit). Returns what was changed or found."""
    import vrfit

    try:
        return vrfit.backbox_in_place(str(table), padlaunch.table_map(title))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not fit this table's VR backbox to the LCD. {exc}") from exc


def resolve_vpx(exe, vr=False):
    """The player to launch: *exe* as given, else the one found. For VR, a
    player that cannot do VR stands for its folder, whose VR player is taken
    (the app saves the desktop player as vpx_exe)."""
    from vpxsetup import find_vpx, vpx_exe_for, vpx_exe_names, vpx_player

    if not exe:
        found = vpx_exe_for(find_vpx(), vr)
        exe = Path(found) if found else None
    elif vr and not (vpx_player(exe) or {}).get("vr"):
        found = vpx_exe_for(str(Path(exe).parent), vr=True)
        if not found:
            raise ValueError(f"{Path(exe).parent} has no VPX player that can play in VR.")
        exe = Path(found)
    if not exe or not exe.is_file():
        raise ValueError("Pass the path to %s with -VpxExe." % " or ".join(vpx_exe_names()))
    return exe.resolve()


def check_controller():
    import winreg

    name = controller_id.PROGID
    try:
        clsid = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, rf"{name}\CLSID")
        server = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32")
    except OSError as exc:
        raise RuntimeError(f"Register {name} in SPIKE 2 VPX Setup before launching.") from exc
    if not server:
        raise RuntimeError(f"{name} has no registered COM server.")
    # A checkout can be launched against an older registered controller.
    # Only overlap startup when the actual COM server supports waiting for us.
    if not padcontroller.pythoncom:
        return False
    import win32com.client

    com = padcontroller.pythoncom
    com.CoInitialize()
    controller = None
    try:
        controller = win32com.client.Dispatch(name, clsctx=com.CLSCTX_LOCAL_SERVER)
        return controller.PadExternalStartup is True
    except (AttributeError, com.com_error):
        return False
    finally:
        del controller
        com.CoUninitialize()


def card_in_folder(folder, native_title):
    images = [path for path in folder.iterdir() if path.suffix.lower() == ".raw" and path.is_file()]
    title = native_title.lower()
    matches = [path for path in images if path.stem.lower() == title
               or path.name.lower().startswith((title + "-", title + "."))]
    candidates = matches or images
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        names = ", ".join(sorted(path.name for path in candidates))
        raise ValueError(f"Multiple .raw images in {folder}: {names}. Choose one with -Card.")
    raise ValueError(f"No game executable or .raw image in {folder}. Pass a prepared SD image with -Card.")


def startup_error(launch):
    problem = "Stern runtime did not become ready" if launch.alive() else "Stern runtime exited during startup"
    return RuntimeError(f"{problem}. See {launch.logfile}")


def wait_for_rig(launch, deadline):
    while launch.alive() and time.monotonic() < deadline:
        record = padcontroller.Rig.board_slot(launch.slot)
        if record and record.get("label") == launch.label:
            if record.get("game") != launch.title:
                raise RuntimeError("The rig started a different title from the table's map.")
            return padcontroller.Rig(launch.title, record=record)
        time.sleep(0.2)
    raise startup_error(launch)


def wait_for_game(launch, rig, deadline, player=None):
    while launch.alive() and time.monotonic() < deadline:
        if player is not None and player.poll() is not None:
            return False
        if padcontroller.block_in_wsl(rig, timeout=min(5, max(0.1, deadline - time.monotonic()))):
            return True
        time.sleep(0.5)
    if player is not None and player.poll() is not None:
        return False
    raise startup_error(launch)


def b2s_disabled_ini(exe, target):
    from padvpx import vpx_ini_path, vpx_ini_set

    choices = (Path(vpx_ini_path()), exe.parent / "VPinballX.ini",
               exe.parent / "assets" / "Default_VPinballX.ini")
    for source in choices:
        try:
            copyfile(source, target)
        except FileNotFoundError:
            continue
        break
    # ScriptGlobalTable.Setting reads Controller from VPX's global INI.
    vpx_ini_set({"ForceDisableB2S": 1}, section="Controller", path=target)


def vr_ini(exe, vr, ini=None):
    """Set VR_INI's keys for this launch of *exe* in *ini* (a run's own copy),
    else in the user's VPX INI. Returns what puts the user's INI back, or None
    when there is nothing to put back: a DirectX player has no VR keys, and a
    copy is thrown away. The real INI is used so the VR table position a
    player sets in-game is kept: VPX saves it there."""
    from padvpx import vpx_ini_get, vpx_ini_path, vpx_ini_set
    from vpxsetup import VR_INI, vpx_player

    player = vpx_player(exe)
    if not player or not player["vr"]:
        return None
    path = str(ini) if ini else vpx_ini_path()
    keys = VR_INI[bool(vr)]
    before = {section: vpx_ini_get(values, section=section, path=path) for section, values in keys.items()}
    for section, values in keys.items():
        vpx_ini_set(values, section=section, path=path)
    if ini:
        return None

    def put_back():
        for section, values in before.items():
            vpx_ini_set(values, section=section, path=path)
    return put_back


def lighting_sources(launch, rig, deadline):
    """Return active and discoverable sources after this run publishes its tables."""
    until = min(deadline, time.monotonic() + 5)
    while launch.alive():
        try:
            if rig.share:
                marker = padcontroller.read_block(Path(rig.dump) / "lighting-tables", 64)
            else:
                result = rig._wsl(["cat", rig.wsl_dump("lighting-tables")], timeout=1)
                marker = result.stdout if result is not None and result.returncode == 0 else None
            fields = marker.split() if marker else []
            if len(fields) == 2 and fields[0] == launch.lighting_scan.encode("ascii"):
                nodes_current = fields[1] == b"1"
                if rig.share:
                    tables = rig.tables_dir(launch.title)
                    return read_lighting_sources(launch, tables, nodes_current,
                                                 Path(rig.dump) / "topper_off")
                # A fresh directory prevents a failed fetch from reusing another run's files.
                with TemporaryDirectory(prefix="spike2-lighting-") as folder:
                    if rig.fetch(rig.wsl_dump("tables"), [launch.title], folder):
                        return read_lighting_sources(launch, Path(folder) / launch.title, nodes_current)
        except (OSError, ValueError):
            pass
        if time.monotonic() >= until:
            break
        time.sleep(0.2)
    return {}, None


def read_lighting_sources(launch, tables, nodes_current, topper_off=None):
    tables = Path(tables)
    if not nodes_current or not (tables / "node_ident.txt").is_file():
        # A verified device table with no LED rows is conclusive on its own.
        with (tables / "device_xy.txt").open(encoding="utf-8", errors="replace") as stream:
            has_leds = any(line.startswith("led ") for line in stream)
        return {}, None if has_leds else ()
    options = {"topper_enabled": launch.lighting_topper, "topper_off": topper_off}
    active = padlighting.stern_sources(tables, **options)
    available = active if launch.lighting_topper else padlighting.stern_sources(
        tables, include_optional_topper=True, **options)
    return active, tuple(available)


def play(launch, exe, table, timeout, progress=None, *, overlap=False, disable_b2s=False,
         lighting=None, lighting_report=None, vr=False):
    # COM can discover the run from the board independently of VPX's environment.
    if padcontroller.Rig.board_run(launch.title):
        raise RuntimeError(f"Close the existing {launch.title} rig before starting this table.")
    lighting = padlighting.settings(lighting)
    config = None
    notice = ""

    def report_lighting(available, message=""):
        if message:
            launch.note(message)
        if lighting_report:
            lighting_report(available, message)
        elif message:
            if progress:
                progress(message, False)
            else:
                print(message, file=sys.stderr, flush=True)

    if lighting.get("enabled"):
        try:
            config = padlighting.prepare(lighting, padcontroller._dof_dirs(), table.parent)
        except (OSError, ValueError, TypeError, ParseError) as exc:
            notice = f"Stern lighting skipped. {exc}"
    if config or lighting_report:
        launch.lighting_scan = uuid4().hex
    if config:
        launch.lighting_topper = any(role == "topper" for _, role, _ in config[1])
    with ExitStack() as cleanup:
        if vr:
            # Before the run starts, and closed after it stops (callbacks run last
            # first), so the LCD isn't moved back while the game is still up.
            cleanup.callback(vpx_lcd.VrLcd(launch).close)
        cleanup.callback(launch.stop)
        command = [str(exe), "-ExtMinimized"]
        ini = None
        if disable_b2s:
            folder = cleanup.enter_context(TemporaryDirectory(prefix="spike2-vpx-b2s-"))
            ini = Path(folder) / "VPinballX.ini"
            b2s_disabled_ini(exe, ini)
            command.extend(["-Ini", str(ini)])
        put_back = vr_ini(exe, vr, ini)
        if put_back:
            cleanup.callback(put_back)          # after VPX has closed and saved its own
        command.extend(["-play", str(table)])
        target = vpx_lcd.fullscreen_target()
        launch.windows_lcd = target
        launch.start()
        if target:
            cleanup.callback(vpx_lcd.Placement(launch, target).close)
        deadline = time.monotonic() + timeout
        rig = wait_for_rig(launch, deadline)
        overlap = overlap and rig.prepared_launch
        if progress:
            progress("Connecting controller", False)
        if not overlap or config:
            wait_for_game(launch, rig, deadline)
        lights = link = None
        if config:
            controllers, mappings, brightness = config
            sources, available = lighting_sources(launch, rig, deadline)
            wanted = {role for _, role, _ in mappings}
            unavailable = wanted - sources.keys()
            mirrored = set()
            if lighting.get("speaker_fallback") and sources.get("speaker"):
                mirrored = unavailable & {"left", "right"}
                mappings = [(fixture, "speaker" if role in mirrored else role, pixels)
                            for fixture, role, pixels in mappings]
                unavailable -= mirrored
            try:
                if available is None:
                    raise ValueError("The game's lighting tables were unavailable.")
                if unavailable == wanted:
                    raise ValueError("This image has no usable Stern lighting for your assigned fixtures.")
                lights = padlighting.Session(controllers, mappings, sources, brightness, launch.note)
                try:
                    if not padcontroller.SHARE_ON or not rig.share or not padcontroller.coilmap.has_magic(
                            padcontroller.read_block(rig.led_path(), padcontroller.READ_N)):
                        link = padcontroller.RigLink(rig)
                        cleanup.callback(link.close)
                except Exception as exc:
                    launch.note(f"Expression lighting link unavailable: {exc}")
                cleanup.callback(lights.close)
                launch.note("Expression lighting owns " +
                            ", ".join(device.port for device in lights.configs.values()))
                messages = []
                if mirrored:
                    messages.append("Speaker lighting on " + ", ".join(
                        padlighting.ROLES[role].lower() for role in sorted(mirrored)) + ".")
                if unavailable:
                    messages.append("Stern lighting unavailable for " + ", ".join(
                        padlighting.ROLES[role].lower() for role in sorted(unavailable)) + ".")
                notice = " ".join(messages)
            except (OSError, ValueError) as exc:
                fallback = "" if disable_b2s else " Your usual DOF setup can control the strips."
                notice = f"Stern lighting skipped. {exc}{fallback}"
            report_lighting(available, notice)
        elif notice:
            report_lighting(None, notice)
        env = dict(os.environ, PAD_WSL_DISTRO=rig.distro, PAD_ROOT_WSL=rig.root,
                   PAD_SLOT=str(launch.slot), PAD_VPX_LINK="1")
        if progress:
            progress("Opening VPX", False)
        with subprocess.Popen(command, cwd=exe.parent,
                              env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP) as vpx:
            if lights:
                def read_lights():
                    if link:
                        blocks = link.blocks()
                        if blocks:
                            return blocks[0]
                    if padcontroller.SHARE_ON and rig.share:
                        return padcontroller.read_block(rig.led_path(), padcontroller.READ_N)

                lights.start(read_lights, lambda: vpx.poll() is None and launch.alive())
            if overlap and not config:
                try:
                    if not wait_for_game(launch, rig, deadline, vpx):
                        return vpx.returncode
                except BaseException:
                    if vpx.poll() is None:
                        vpx.terminate()
                    raise
            if lighting_report and not config:
                _, available = lighting_sources(launch, rig, deadline)
                report_lighting(available)
            if progress:
                progress("Playing in Visual Pinball X", True)
            while True:
                try:
                    return vpx.wait()
                except KeyboardInterrupt:
                    print("Close VPX to stop the Stern runtime and release its slot.", file=sys.stderr)


def play_app_game(title, card, table, timeout):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from spike2_vpx.player import Game, Player
    from spike2_vpx_setup import Setup

    setup = Setup()
    try:
        player = Player(setup)
        game = Game(title, str(card), str(table))
        for warning in player.preflight(game):
            print(warning, file=sys.stderr, flush=True)
        return player.play(game, lambda message, _: print(message, flush=True), timeout)
    finally:
        for handler in setup.log.handlers:
            handler.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--game-dir", help="Executable title directory, or Windows folder containing a .raw image")
    source.add_argument("--card", type=Path, help="Prepared SPIKE 2 card image")
    parser.add_argument("--table", type=Path, required=True, help="PAD-patched .vpx file")
    parser.add_argument("--vpx-exe", type=Path, help="Override the installed VPX player")
    parser.add_argument("--vr", action="store_true", help="Play in a VR headset (needs VPX's OpenGL build)")
    parser.add_argument("--distro", help="Override the prepared WSL distribution")
    parser.add_argument("--app-game", help="Launch an exported app pairing using the app settings")
    parser.add_argument("--startup-timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        if sys.platform != "win32":
            raise RuntimeError("This launcher requires Windows and WSL.")
        if args.startup_timeout < 1:
            raise ValueError("Startup timeout must be positive.")
        if args.app_game:
            if not args.card:
                raise ValueError("An exported game requires a card image.")
            return play_app_game(args.app_game, args.card, args.table, args.startup_timeout)
        table = args.table.resolve(strict=True)
        if not table.is_file() or table.suffix.lower() != ".vpx":
            raise ValueError("Pass a PAD-patched .vpx table.")
        title = read_title(table)
        mapping = padlaunch.table_map(title)
        if not mapping or mapping.get("platform", "spike2") != "spike2":
            raise ValueError(f"No SPIKE 2 map was found for {title}.")
        native_title = padlaunch.game_for(title)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", native_title):
            raise ValueError(f"Invalid native SPIKE 2 game name in the map for {title}.")
        exe = resolve_vpx(args.vpx_exe, args.vr)
        overlap = check_controller()
        script = embedded_script(table)
        for line in own_controller(table, script) + hide_score_display(table, script):
            print(line, flush=True)
        if args.vr:
            for line in fit_for_vr(table, title):
                print(line, flush=True)

        distro = args.distro or padlaunch.distro()
        card = args.card
        game_dir = args.game_dir
        if game_dir and not game_dir.startswith("/"):
            folder = Path(game_dir).resolve(strict=True)
            if not folder.is_dir():
                raise ValueError("-GameDir requires a directory. Pass an image file with -Card.")
            if (folder / "game").is_file():
                game_dir = padlaunch.padpath.to_wsl(str(folder), distro)
            else:
                card = card_in_folder(folder, native_title)
                game_dir = None
        if card:
            card = card.resolve(strict=True)
            if not card.is_file():
                raise ValueError("-Card requires a prepared SPIKE 2 image file.")
        else:
            game_dir = game_dir.rstrip("/")
            probe = subprocess.run(padlaunch.wsl_head(distro) + ["-e", "test", "-x", game_dir + "/game"],
                                   capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            if probe.returncode:
                detail = padlaunch._text(probe.stderr).strip()
                raise RuntimeError(f"WSL could not access an executable at {game_dir}/game. {detail}".strip())
        launch = padlaunch.Launch(title, str(card) if card else None, dist=distro, minutes=0,
                                  game_dir=game_dir, prepared=True)
        settings_path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Spike2Vpx" / "setup.json"
        try:
            settings = padlighting.settings(json.loads(settings_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            settings = {}
        return play(launch, exe, table, args.startup_timeout, overlap=overlap,
                    lighting=settings.get("lighting"), vr=args.vr)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
        print(f"SPIKE 2 VPX: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
