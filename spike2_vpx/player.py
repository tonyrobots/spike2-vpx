"""Image, table and saved-game operations used by the desktop window."""

from dataclasses import asdict, dataclass, replace
from base64 import b64encode
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree.ElementTree import ParseError, iterparse
from zipfile import BadZipFile, ZipFile

from spike2_vpx_setup import APP, DISTRO, RIG

# The setup module loads the VPX kit from the same location as the console launcher.
import padisplay
import padlaunch
import padlighting
import padvpx
import play_spike2
from spike2_vpx import cabinet, runtime, sessions, support

STERN_IMAGES = "https://www.sternpinball.com/support/sd-cards/"
BACKGLASS_ART = APP / "assets" / "backglasses"


@dataclass(frozen=True)
class Game:
    title: str
    image: str
    table: str = ""
    image_version: str = ""
    table_release: str = ""
    artwork: str = ""
    favorite: bool = False
    last_played: str = ""

    @property
    def name(self):
        parts = self.title.replace("_", " ").split()
        acronyms = {"le", "se", "tmnt", "jp", "aiq"}
        return " ".join(word.upper() if word in acronyms else word.title() for word in parts)


@dataclass(frozen=True)
class SupportedTable:
    game: str
    table: str
    author: str
    url: str


def artwork_paths(game):
    if game.artwork:
        yield game.artwork
    if re.fullmatch(r"[a-z0-9_-]+", game.title):
        yield BACKGLASS_ART / f"{game.title}.png"
    yield BACKGLASS_ART / "default.png"


def image_version(name):
    match = re.search(r"(?<![0-9])v?([0-9]{1,2})[._]([0-9]{1,2})[._]([0-9]{1,3})(?![0-9])", name)
    return ".".join(match.groups()) if match else ""


def game_from_row(row):
    if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k]
                                            for k in ("title", "image")):
        return None
    optional = {k: row[k] for k in ("table", "image_version", "table_release", "artwork", "last_played")
                if isinstance(row.get(k), str)}
    return Game(row["title"], row["image"], **optional, favorite=row.get("favorite") is True)


def supported_tables():
    """List actual bundled patch maps with the VPX release each map targets."""
    rows = set()
    for mapping in padvpx.maps().values():
        metadata = mapping["table"]
        if not mapping["listed"] or not metadata.get("name"):
            continue
        source = metadata.get("url") or ""
        link = urlsplit(source)
        url = source if link.scheme == "https" and link.hostname else ""
        rows.add(SupportedTable(Game(mapping["game"], "").name, metadata["name"],
                                metadata.get("by") or "", url))
    return sorted(rows, key=lambda row: (row.game.casefold(), row.table.casefold(), row.url))


def file_of_type(path, suffix):
    file = Path(path).resolve()
    if not file.is_file() or file.suffix.casefold() != suffix:
        raise ValueError(f"Choose an existing {suffix} file.")
    return file


def folder_images(folder):
    return sorted((p for p in Path(folder).iterdir() if p.suffix.casefold() == ".raw"
                   and p.is_file()), key=lambda p: p.name.casefold())


class Player:
    def __init__(self, setup):
        self.setup = setup
        self.log_path = setup.log_path.with_name("player.log")
        self.audio_path = setup.data / "audio.json"

    def library(self):
        rows = self.setup.settings.get("games")
        if not isinstance(rows, list):
            return []
        return [game for row in rows if (game := game_from_row(row))]

    def save(self, game):
        games = [row for row in self.library()
                 if (row.title, Path(row.image)) != (game.title, Path(game.image))]
        self.setup.settings["games"] = [asdict(game), *(asdict(row) for row in games)]
        self.setup.save()

    def update_game(self, game, **changes):
        updated = replace(game, **changes)
        self.save(updated)
        return updated

    def record_played(self, game):
        # A front-end launch may stay open while the desktop edits the library.
        try:
            latest = json.loads(self.setup.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            latest = None
        if isinstance(latest, dict):
            self.setup.settings = latest
        stored = next((row for row in self.library()
                       if (row.title, row.image, row.table) == (game.title, game.image, game.table)), None)
        if stored:
            self.update_game(stored, last_played=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def table_release(self, game):
        if game.table_release:
            return game.table_release
        if not game.table:
            return ""
        table = Path(game.table)
        matches = [m["table"].get("name") for m in padvpx.maps().values()
                   if m["game"].casefold() == game.title and m["output"]
                   and m["output"].casefold() == table.name.casefold() and m["table"].get("name")]
        return matches[0] if len(set(matches)) == 1 else table.stem

    def remove(self, game):
        self.setup.settings["games"] = [asdict(row) for row in self.library() if row != game]
        self.setup.save()

    def relink_image(self, previous, image):
        if image.title != previous.title:
            raise ValueError(f"Choose an SD-card image for {previous.name}.")
        game = replace(previous, image=image.image, image_version=image.image_version)
        games = [row for row in self.library() if row != previous and
                 (row.title, Path(row.image)) != (game.title, Path(game.image))]
        self.setup.settings["games"] = [asdict(game), *(asdict(row) for row in games)]
        self.setup.save()
        return game

    def inspect_image(self, path):
        image = file_of_type(path, ".raw")
        paths = padlaunch.padpath.to_wsl_many([str(RIG), str(image)], DISTRO)
        script = paths[0] + "/inspect_vpx_card.py"
        out = self.setup.wsl("python3", "-B", script, paths[1], timeout=150)
        if out.returncode:
            try:
                error = json.loads(out.stdout)["error"]
            except (ValueError, TypeError, KeyError):
                error = runtime._why(out)
            raise ValueError(error)
        return Game(json.loads(out.stdout)["title"], str(image), image_version=image_version(image.name))

    def import_archive(self, path, expected=None):
        source = file_of_type(path, ".zip")
        directory = self.setup.data / "images"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            with ZipFile(source) as archive:
                images = [member for member in archive.infolist()
                          if not member.is_dir() and Path(member.filename).suffix.casefold() == ".raw"
                          and not member.filename.startswith("__MACOSX/")]
                if len(images) != 1 or images[0].file_size == 0:
                    raise ValueError("Import a ZIP containing one non-empty .raw image, or extract the image yourself.")
                member = images[0]
                if member.file_size > shutil.disk_usage(directory).free:
                    raise ValueError(f"Free up space on {directory.anchor} to extract this image "
                                     f"({member.file_size / 1024**3:.1f} GiB required).")
                # Use app-owned names. An archive entry cannot choose where we write.
                with TemporaryDirectory(dir=directory) as stage:
                    extracted = Path(stage) / "card.raw"
                    with archive.open(member) as data, extracted.open("wb") as out:
                        shutil.copyfileobj(data, out, length=1024 * 1024)
                    game = self.inspect_image(extracted)
                    if expected and game.title != expected.title:
                        raise ValueError(f"This image is for {game.name}. Choose an image for {expected.name}.")
                    destination = directory / (uuid4().hex + ".raw")
                    extracted.replace(destination)
        except (BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError(f"Unable to extract this ZIP. Download it again or extract the .raw manually. {exc}") from exc
        return replace(game, image=str(destination), image_version=image_version(Path(member.filename).name)
                       or image_version(source.name))

    def prepare_image(self, path, expected=None):
        imported = Path(path).suffix.casefold() == ".zip"
        game = self.import_archive(path, expected) if imported else self.inspect_image(path)
        if expected and game.title != expected.title:
            raise ValueError(f"This image is for {game.name}. Choose an image for {expected.name}.")
        if not padlaunch.cache_on():
            note = "Extracted and verified the ZIP image." if imported else "Read directly from the source image."
            return game, note
        try:
            launch = padlaunch.Launch(game.title, game.image, dist=DISTRO, prepared=True)
            info = launch.cache_check()
        except Exception:
            if imported:
                Path(game.image).unlink(missing_ok=True)
            raise
        return game, padlaunch.space_words(info or {})[1] + "."

    def layout(self, monitors):
        return cabinet.saved_layout(self.setup.settings, monitors)

    def preflight(self, game):
        if not Path(game.image).is_file():
            raise ValueError("The SD-card image was moved or is missing. Use Import image to locate it again.")
        if not game.table or not Path(game.table).is_file():
            raise ValueError("The VPX table was moved or is missing. Use Choose table to locate it again.")
        monitors = padisplay.monitors()
        roles = cabinet.resolve(self.layout(monitors), monitors)
        return cabinet.backglass_warnings(game.table, roles)

    def attach_backglass(self, game, path):
        table = file_of_type(game.table, ".vpx")
        source = file_of_type(path, ".directb2s")
        try:
            with source.open("rb") as file:
                events = iterparse(file, events=("start", "end"))
                if next(events)[1].tag != "DirectB2SData":
                    raise ValueError("Choose a valid .directb2s backglass file.")
                for event, element in events:
                    if event == "end":
                        element.clear()
        except (ParseError, StopIteration) as exc:
            raise ValueError("Choose a valid .directb2s backglass file.") from exc
        destination = table.with_suffix(".directb2s")
        if destination.exists():
            raise ValueError("A backglass already exists beside this VPX table.")
        with NamedTemporaryFile(dir=table.parent, delete=False) as file:
            temporary = Path(file.name)
        try:
            shutil.copyfile(source, temporary)
            # Publish without replacing an existing companion.
            if os.name == "nt":
                temporary.rename(destination)
            else:
                destination.hardlink_to(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def export(self, game, path):
        warnings = self.preflight(game)
        table = file_of_type(game.table, ".vpx")
        image = file_of_type(game.image, ".raw")
        if self.inspect_image(image).title != game.title:
            raise ValueError("The image now contains a different title. Select the image again.")
        self.compatible(game, table, play_spike2.embedded_script(table))
        target = Path(path)
        if target.suffix.casefold() not in (".cmd", ".bat"):
            raise ValueError("Save the launch script as a .cmd or .bat file.")

        values = json.dumps([str(APP / "Play-Spike2Vpx.ps1"), str(image), str(table), game.title])
        payload = b64encode(values.encode("ascii")).decode("ascii")
        command = (
            "try { $ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
            f"$json=[Text.Encoding]::ASCII.GetString([Convert]::FromBase64String('{payload}')); "
            "$values=ConvertFrom-Json $json; "
            "& $values[0] -Card $values[1] -Table $values[2] -AppGame $values[3]; exit $LASTEXITCODE } "
            "catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
        )
        encoded = b64encode(command.encode("utf-16-le")).decode("ascii")
        script = ("@echo off\n"
                  "rem WSL may stay running after VPX closes. Leave it running between games.\n"
                  f"rem When done playing, run wsl --terminate {DISTRO} in PowerShell to free WSL memory.\n"
                  "setlocal DisableDelayedExpansion\n"
                  '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
                  f"-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}\n"
                  "exit /b %errorlevel%\n")
        if max(map(len, script.splitlines())) > 8191:
            raise ValueError("The image and table paths are too long for a Windows launch script.")
        with NamedTemporaryFile(mode="w", encoding="ascii", newline="\r\n", dir=target.parent,
                                delete=False) as file:
            temporary = Path(file.name)
            try:
                file.write(script)
                file.close()
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return warnings

    def compatible(self, game, table, script):
        title = play_spike2.read_title(table, script)
        mapping = padlaunch.table_map(title)
        if not mapping or padlaunch.game_for(title).casefold() != game.title:
            raise ValueError(f"This table is prepared for {title}. Choose a table for {game.name}.")
        if ("padspike2.vbs" in script.casefold()
                and not (table.parent / "PADSPIKE2.vbs").is_file()):
            raise ValueError("PADSPIKE2.vbs is missing beside this table. Choose the original VPX file to prepare a new copy.")

    def prepare_table(self, game, path, progress):
        table = file_of_type(path, ".vpx")
        script = play_spike2.embedded_script(table)
        if play_spike2.patched_script(script):
            self.compatible(game, table, script)
            pairing = replace(game, table=str(table), table_release="")
            return replace(pairing, table_release=self.table_release(pairing))
        matches = [(title, info) for title, info in padvpx.fitting(str(table), script)
                   if info["game"].casefold() == game.title]
        if not matches:
            raise ValueError(f"No patch map matches this table and {game.name}. Choose a compatible VPX file.")
        title, info = padvpx.choose(matches, title=game.title)
        if not info["output"]:
            raise ValueError("This table map does not name a prepared output file.")
        progress(f"Creating a playable copy for {game.name}…", False)
        with TemporaryDirectory(prefix=".spike2-vpx-", dir=table.parent) as stage:
            stage = Path(stage)
            with self.log_path.open("ab") as log:
                if padvpx.patch(str(table), outdir=str(stage), title=title, log=log,
                                configure_cabinet=False):
                    raise RuntimeError("Table conversion failed. See the player log for details.")
            prepared = stage / info["output"]
            helper = stage / "PADSPIKE2.vbs"
            if not helper.exists():
                shutil.copyfile(RIG / "vpx" / helper.name, helper)
            self.compatible(game, prepared, play_spike2.embedded_script(prepared))

            for suffix in (".ini", ".pov", ".res"):
                source = table.with_suffix(suffix)
                if source.is_file():
                    shutil.copy2(source, prepared.with_suffix(suffix))

            companions = [file for file in stage.iterdir()
                          if file.name.startswith(prepared.stem + ".") and file != prepared]
            suffixes = [file.name[len(prepared.stem):] for file in companions]
            target = table.with_name(prepared.name)
            copy_number = 2
            while any(os.path.lexists(target.with_name(target.stem + suffix))
                      for suffix in (*suffixes, ".vpx", ".ini", ".pov", ".res", ".directb2s", ".vbs")):
                name = prepared.stem.removesuffix(" (PAD)")
                target = table.with_name(f"{name} {copy_number} (PAD).vpx")
                copy_number += 1

            published = []
            try:
                for file, suffix in zip(companions, suffixes):
                    destination = target.with_name(target.stem + suffix)
                    file.rename(destination)
                    published.append(destination)
                helper.replace(table.parent / helper.name)
                prepared.rename(target)
            except OSError:
                for file in published:
                    file.unlink(missing_ok=True)
                raise
        if target.with_suffix(".directb2s").is_file():
            padvpx.cabinet_res(str(target))
        return replace(game, table=str(target),
                       table_release=info["table"].get("name") or prepared.stem)

    def lighting_record(self, game):
        """Cache identity includes the file metadata so replacement images get a new scan."""
        try:
            path = Path(game.image).resolve(strict=True)
            info = path.stat()
        except OSError:
            return None
        identity = (game.title, os.path.normcase(str(path)), info.st_size, info.st_mtime_ns,
                    info.st_ctime_ns, info.st_ino)
        key = sha256(json.dumps(identity).encode("ascii")).hexdigest()
        return self.setup.data / "lighting-scans" / f"{key}.json"

    def game_lighting(self, game):
        record = self.lighting_record(game)
        if record is None:
            return None
        try:
            roles = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(roles, list) and all(isinstance(role, str) and role in padlighting.ROLES for role in roles):
            return frozenset(roles)
        return None

    def play(self, game, progress, timeout=180, *, lighting_update=None):
        vr = self.setup.vr_wanted()
        if self.setup.check_vpx().state != "Ready":
            raise ValueError("Choose a compatible Visual Pinball X folder in Setup.")
        if vr:
            runtime, why = self.setup.vr_status()
            if not runtime:
                raise ValueError(f"Enable VR is on, but VR is unavailable. {why} "
                                 "Turn off Enable VR to play on the desktop.")
        exe = self.setup.vpx_executable(vr=vr)
        if exe is None:
            raise ValueError("Choose a compatible Visual Pinball X folder in Setup.")
        progress("Checking files", False)
        overlap = play_spike2.check_controller()
        if self.inspect_image(game.image).title != game.title:
            raise ValueError("The image now contains a different title. Select the image again.")
        table = file_of_type(game.table, ".vpx")
        script = play_spike2.embedded_script(table)
        self.compatible(game, table, script)
        title = play_spike2.read_title(table, script)
        for line in play_spike2.own_controller(table, script) + play_spike2.hide_score_display(table, script):
            self.setup.log.info("%s", line)
        if vr:
            for line in play_spike2.fit_for_vr(table, title):
                self.setup.log.info("%s", line)
        monitors = padisplay.monitors()
        layout = self.layout(monitors)
        roles = cabinet.resolve(layout, monitors)
        disable_b2s = layout.get("backglass") == cabinet.DISABLED_B2S
        sessions.check_available(self.setup, game.title)
        board = self.setup.data / "rig-board"
        if self.setup.settings.get("cabinet_layout") is not None:
            cabinet.apply(board, roles, monitors, None if disable_b2s else table)
        else:
            cabinet.apply_lcd(board, roles.get("lcd"), monitors)
        progress("Starting Stern", False)
        launch = padlaunch.Launch(title, game.image, dist=DISTRO, minutes=0, prepared=True,
                                  audio_control=str(self.audio_path))
        started = False
        lighting_record = self.lighting_record(game)

        def report(message, playing):
            nonlocal started
            started = started or playing
            progress(message, playing)

        def report_lighting(roles, message):
            if roles is not None and lighting_record and lighting_record == self.lighting_record(game):
                try:
                    lighting_record.parent.mkdir(exist_ok=True, parents=True)
                    support.atomic_write(lighting_record, json.dumps(roles).encode("ascii"))
                except OSError:
                    self.setup.log.exception("Could not save game lighting compatibility")
            if lighting_update:
                lighting_update(message)
            elif message:
                progress(message, False)

        result = play_spike2.play(launch, exe.resolve(), table, timeout, progress=report, overlap=overlap,
                                  disable_b2s=disable_b2s, lighting=self.setup.settings.get("lighting"),
                                  lighting_report=report_lighting, vr=vr)
        if started:
            try:
                self.record_played(game)
            except OSError:
                self.setup.log.exception("Could not save the last played date")
        if result:
            self.setup.log.error("Visual Pinball X exited with code %s. Runtime log: %s", result, launch.logfile)
        return result

    def profiles(self):
        profiles = self.setup.settings.get("display_profiles")
        return profiles if isinstance(profiles, dict) else {}

    def save_layout(self, layout, monitors, profile=None):
        board = self.setup.data / "rig-board"
        cabinet.apply(board, cabinet.resolve(layout, monitors), monitors)
        self.setup.settings.pop("lcd_monitor", None)
        self.setup.settings["cabinet_layout"] = layout
        if profile:
            self.setup.settings["display_profiles"] = {**self.profiles(), profile: layout}
            self.setup.settings["display_profile"] = profile
        self.setup.save()

    def save_preferences(self, volume, cache):
        support.atomic_write(self.audio_path, json.dumps({"gain": volume / 100, "muted": volume == 0}).encode("utf-8"))
        padlaunch.set_cache_on(cache)
        self.setup.settings["volume"] = volume
        self.setup.save()

    def restore(self, data):
        previous = self.setup.settings.copy()
        old_audio = self.audio_path.read_bytes() if self.audio_path.exists() else None
        old_cache = padlaunch.cache_on()
        preferences = data["preferences"]
        portable = support.backup(previous, old_cache)["preferences"]
        self.setup.settings = {**{key: value for key, value in previous.items() if key not in portable},
                               **preferences}
        try:
            self.save_preferences(preferences.get("volume", 100), data["card_cache"])
        except OSError:
            self.setup.settings = previous
            try:
                if old_audio is None:
                    self.audio_path.unlink(missing_ok=True)
                else:
                    support.atomic_write(self.audio_path, old_audio)
                padlaunch.set_cache_on(old_cache)
            except OSError:
                self.setup.log.exception("Could not restore preferences after a failed backup import")
            raise
