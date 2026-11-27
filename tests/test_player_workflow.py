from base64 import b64encode
import json
import os
from pathlib import Path
from subprocess import CompletedProcess, run
import sys
import time
from unittest.mock import Mock
import wave
from zipfile import ZipFile

import pytest

from spike2_vpx.player import Game, Player, supported_tables
from spike2_vpx_setup import Setup


@pytest.fixture
def player(tmp_path):
    setup = Setup(tmp_path)
    yield Player(setup)
    setup.log.handlers[0].close()


def test_catalog_lists_bundled_table_versions_for_supported_game_editions():
    rows = supported_tables()
    godzilla = next(row for row in rows if row.game == "Godzilla LE")
    assert godzilla.table == "Godzilla Limited Edition v2.6"
    assert godzilla.url.startswith("https://")
    assert {"Foo Fighters LE", "Foo Fighters Pro"} <= {row.game for row in rows}
    assert "Turtles LE" not in {row.game for row in rows}


def test_backglass_artwork_prefers_local_art_then_title_and_default(tmp_path):
    from spike2_vpx.player import artwork_paths

    override = str(tmp_path / "custom.png")
    custom, title, default = artwork_paths(Game("godzilla_le", "card.raw", artwork=override))
    assert custom == override
    for path, expected in ((title, "godzilla_le.png"), (default, "default.png")):
        assert path.name == expected
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert list(artwork_paths(Game("../outside", "card.raw"))) == [default]


def test_directb2s_preview_uses_only_the_matching_main_image(tmp_path):
    from spike2_vpx import backglass
    from spike2_vpx.player import BACKGLASS_ART

    table = tmp_path / "Godzilla (PAD).vpx"
    table.touch()
    unrelated = tmp_path / "Original.directb2s"
    unrelated.touch()
    assert backglass.preview_key(table) is None
    companion = table.with_suffix(".directb2s")
    png = (BACKGLASS_ART / "godzilla_le.png").read_bytes()
    encoded = b64encode(png).decode("ascii")
    companion.write_text(f'<DirectB2SData><Images><DMDImage Value="ignore"/>'
                         f'<BackglassImage Value="{encoded}"/></Images></DirectB2SData>')
    key = backglass.preview_key(table)
    assert backglass.thumbnail(key) == png
    companion.write_text('<DirectB2SData><Images><BackglassImage Value="bad!"/></Images></DirectB2SData>')
    changed = backglass.preview_key(table)
    assert changed != key
    assert backglass.thumbnail(changed) == b""


def test_directb2s_preview_rejects_xml_entities(tmp_path):
    from spike2_vpx import backglass

    table = tmp_path / "Table.vpx"
    table.with_suffix(".directb2s").write_text(
        '<!DOCTYPE DirectB2SData [<!ENTITY art "aGVsbG8=">]>'
        '<DirectB2SData><Images><BackglassImage Value="&art;"/></Images></DirectB2SData>')
    assert backglass.thumbnail(backglass.preview_key(table)) == b""


def test_image_title_comes_from_the_content_probe(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    image = tmp_path / "custom name.RAW"
    image.write_bytes(b"original")
    monkeypatch.setattr(module.padlaunch.padpath, "to_wsl_many",
                        lambda paths, distro: ["/rig", "/mnt/c/custom name.RAW"])
    player.setup.wsl = Mock(return_value=CompletedProcess([], 0, b'{"title":"godzilla_le"}', b""))
    assert player.inspect_image(image) == Game("godzilla_le", str(image))
    player.setup.wsl.assert_called_once_with("python3", "-B", "/rig/inspect_vpx_card.py",
                                             "/mnt/c/custom name.RAW", timeout=150)
    assert image.read_bytes() == b"original"


def test_rejects_prepared_table_for_another_edition(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    table = tmp_path / "Jaws (PAD).vpx"
    table.touch()
    monkeypatch.setattr(module.play_spike2, "embedded_script",
                        lambda _: 'Controller.GameName = "jaws_le"\nCreateObject("Spike2Vpx.Controller")')
    with pytest.raises(ValueError, match="prepared for jaws_le"):
        player.prepare_table(Game("godzilla_le", "card.raw"), table, Mock())
    assert not player.library()


@pytest.mark.parametrize("existing_conversion", [False, True])
def test_conversion_publishes_beside_source_and_saves_pairing(player, tmp_path, monkeypatch,
                                                            existing_conversion):
    from spike2_vpx import player as module

    tables = tmp_path / "VPX tables"
    tables.mkdir()
    table = tables / "Original.vpx"
    table.write_bytes(b"original table")
    table.with_suffix(".ini").write_bytes(b"[Player]\n")
    table.with_suffix(".res").write_bytes(b"custom placement")
    backglass = tables / "Downloaded backglass.directb2s"
    backglass.write_bytes(b"backglass")
    base = tables / "Godzilla limited edition (PAD).vpx"
    if existing_conversion:
        base.write_bytes(b"earlier conversion")
        base.with_suffix(".directb2s").write_bytes(b"earlier backglass")
    patched = 'Controller.GameName = "godzilla_le"\nLoadVPM "01000000", "PADSPIKE2.vbs", 3.10'
    monkeypatch.setattr(module.play_spike2, "embedded_script",
                        lambda path: "Godzilla SEGA.VBS" if Path(path) == table else patched)
    monkeypatch.setattr(module.padlaunch, "win_python", lambda: sys.executable)

    def patcher(cmd, **kwargs):
        assert Path(cmd[2]) == table
        prepared = Path(cmd[3]) / base.name
        prepared.write_bytes(b"prepared")
        prepared.with_suffix(".script.vbs").write_text(patched)
        return CompletedProcess(cmd, 0)

    monkeypatch.setattr(module.padvpx.subprocess, "run", patcher)
    cabinet_res = Mock()
    monkeypatch.setattr(module.padvpx, "cabinet_res", cabinet_res)
    game = player.prepare_table(Game("godzilla_le", "card.raw"), table, Mock())
    player.save(game)
    prepared = Path(game.table)
    expected = "Godzilla limited edition 2 (PAD).vpx" if existing_conversion else base.name
    assert prepared == tables / expected
    assert table.read_bytes() == b"original table"
    assert backglass.read_bytes() == prepared.with_suffix(".directb2s").read_bytes() == b"backglass"
    assert prepared.with_suffix(".ini").read_bytes() == b"[Player]\n"
    assert prepared.with_suffix(".res").read_bytes() == b"custom placement"
    assert prepared.with_suffix(".script.vbs").read_text() == patched
    assert json.loads(prepared.with_suffix(".patch.json").read_text()) == {
        "source": str(table), "title": "godzilla_le"}
    assert prepared.read_bytes() == b"prepared"
    assert prepared.with_name("PADSPIKE2.vbs").is_file()
    assert not list(tables.glob(".spike2-vpx-*"))
    cabinet_res.assert_called_once_with(str(prepared))
    if existing_conversion:
        assert base.read_bytes() == b"earlier conversion"
        assert base.with_suffix(".directb2s").read_bytes() == b"earlier backglass"
    reopened = Setup(tmp_path)
    try:
        assert Player(reopened).library() == [game]
        player.remove(game)
        assert player.library() == []
        assert Path(game.table).is_file()
    finally:
        reopened.log.handlers[0].close()


def test_failed_conversion_leaves_source_folder_intact(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    tables = tmp_path / "Tables"
    tables.mkdir()
    table = tables / "Original.vpx"
    table.write_bytes(b"original table")
    monkeypatch.setattr(module.play_spike2, "embedded_script", lambda path: "Godzilla SEGA.VBS")

    def fail_patch(path, *, outdir, **kwargs):
        (Path(outdir) / "PADSPIKE2.vbs").write_bytes(b"partial conversion")
        return 1

    monkeypatch.setattr(module.padvpx, "patch", fail_patch)
    with pytest.raises(RuntimeError, match="Table conversion failed"):
        player.prepare_table(Game("godzilla_le", "card.raw"), table, Mock())
    assert list(tables.iterdir()) == [table]
    assert table.read_bytes() == b"original table"


def test_play_refuses_a_saved_image_replaced_with_another_title(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    player.setup.vpx_executable = Mock(return_value=tmp_path / "VPinballX64.exe")
    player.setup.check_vpx = Mock(return_value=Mock(state="Ready"))
    monkeypatch.setattr(module.play_spike2, "check_controller", Mock())
    player.inspect_image = Mock(return_value=Game("jaws_le", "card.raw"))
    launch = Mock()
    monkeypatch.setattr(module.padlaunch, "Launch", launch)
    with pytest.raises(ValueError, match="different title"):
        player.play(Game("godzilla_le", "card.raw", "table.vpx"), Mock())
    launch.assert_not_called()


def test_play_in_vr_refuses_plainly_when_vr_is_unavailable(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    player.setup.settings["vr"] = True
    player.setup.check_vpx = Mock(return_value=Mock(state="Ready"))
    player.setup.vr_status = Mock(return_value=("", "No VR runtime found."))
    launch = Mock()
    monkeypatch.setattr(module.padlaunch, "Launch", launch)
    with pytest.raises(ValueError, match="Enable VR is on, but VR is unavailable. No VR runtime found."):
        player.play(Game("godzilla_le", "card.raw", "table.vpx"), Mock())
    launch.assert_not_called()


def test_play_in_vr_launches_the_vr_player(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    player.setup.settings["vr"] = True
    player.setup.check_vpx = Mock(return_value=Mock(state="Ready"))
    player.setup.vr_status = Mock(return_value=("SteamVR", ""))
    player.setup.vpx_executable = Mock(side_effect=lambda vr=False: None if vr else tmp_path / "VPinballX64.exe")
    with pytest.raises(ValueError, match="Visual Pinball X folder"):
        player.play(Game("godzilla_le", "card.raw", "table.vpx"), Mock())
    player.setup.vpx_executable.assert_called_once_with(vr=True)


def test_zip_import_extracts_one_verified_card_without_using_archive_paths(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    source = tmp_path / "Stern image.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("../../card.RAW", b"card")
        archive.writestr("readme.txt", b"instructions")
    original = source.read_bytes()

    def inspect(path):
        assert path.read_bytes() == b"card"
        return Game("godzilla_le", str(path))

    player.inspect_image = inspect
    monkeypatch.setattr(module.padlaunch, "cache_on", lambda: False)
    game, _ = player.prepare_image(source)
    assert game.title == "godzilla_le"
    assert Path(game.image).parent == tmp_path / "images"
    assert Path(game.image).read_bytes() == b"card"
    assert list((tmp_path / "images").iterdir()) == [Path(game.image)]
    assert source.read_bytes() == original


def test_zip_import_rejects_ambiguous_images_and_cleans_failed_verification(player, tmp_path):
    source = tmp_path / "Stern image.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("card1.raw", b"card")
        archive.writestr("card2.raw", b"card")
    with pytest.raises(ValueError, match="one non-empty"):
        player.import_archive(source)
    with ZipFile(source, "w") as archive:
        archive.writestr("card1.raw", b"card")
    player.inspect_image = Mock(side_effect=ValueError("Not a SPIKE 2 image"))
    with pytest.raises(ValueError, match="Not a SPIKE 2 image"):
        player.import_archive(source)
    assert not list((tmp_path / "images").iterdir())


def test_cabinet_uses_device_identity_and_preflights_backglass(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module
    from spike2_vpx import cabinet

    screens = [
        {"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True, "device": "play"},
        {"n": 2, "x": -1280, "y": 0, "w": 1280, "h": 720, "primary": False, "device": "lcd"},
        {"n": 3, "x": 0, "y": -720, "w": 1280, "h": 720, "primary": False, "device": "glass",
         "display_number": 4},
    ]
    assert cabinet.screen_name({"n": 2, "display_number": 3}) == "Screen 2 (Windows 3)"
    assert cabinet.screen_name({"n": 1, "display_number": 1}) == "Screen 1"
    image, table = tmp_path / "card.raw", tmp_path / "Godzilla (PAD).vpx"
    image.touch()
    table.touch()
    game = Game("godzilla_le", str(image), str(table))
    kit_save = Mock()
    monkeypatch.setattr(module.padlaunch, "kit_save", kit_save)
    monkeypatch.setattr(module.padlaunch, "kit_load", lambda: {})
    monkeypatch.setattr(module.padisplay, "monitors", lambda: screens)
    monkeypatch.setattr(cabinet, "backglass_available", lambda: True)
    layout = {"playfield": "play", "backglass": "glass", "lcd": "lcd"}
    player.save_layout(layout, screens)
    assert kit_save.call_args.args[0]["player"] == {"monitor": 1}
    # X root coordinates: the virtual desktop's top-left (-1280, -720) is X's 0,0.
    assert "x=0 y=720 w=1280 h=720" in (tmp_path / "rig-board" / "display.conf").read_text()
    assert "Attach a .directb2s" in player.preflight(game)[0]
    source = tmp_path / "original.directb2s"
    source.write_text("<DirectB2SData/>")
    companion = player.attach_backglass(game, source)
    assert companion.name == "Godzilla (PAD).directb2s"
    with pytest.raises(ValueError, match="already exists"):
        player.attach_backglass(game, source)
    assert not player.preflight(game)
    cabinet.apply(tmp_path / "rig-board", cabinet.resolve(layout, screens), screens, table)
    assert cabinet.padcabinet.parse_screenres(table.with_suffix(".res").read_text())[4] == "4"
    table.with_suffix(".res").write_text("custom")
    assert "custom .res" in player.preflight(game)[0]
    cabinet.apply(tmp_path / "rig-board", cabinet.resolve(layout, screens), screens, table)
    assert table.with_suffix(".res").read_text() == "custom"
    screens[1]["n"], screens[2]["n"] = 3, 2
    assert cabinet.resolve(layout, screens)["lcd"]["n"] == 3
    disabled = {**layout, "backglass": cabinet.DISABLED_B2S}
    assert "backglass" not in cabinet.resolve(disabled, screens)
    assert cabinet.saved_layout({"cabinet_layout": disabled}, screens)["backglass"] == cabinet.DISABLED_B2S
    with pytest.raises(ValueError, match="different screen"):
        cabinet.resolve({"lcd": "play", "playfield": "play"}, screens)
    screens.pop()
    with pytest.raises(ValueError, match="backglass screen is disconnected"):
        player.preflight(game)


def test_play_defaults_to_borderless_fullscreen_on_a_spare_display(player, tmp_path, monkeypatch):
    from spike2_vpx import cabinet
    from spike2_vpx import player as module

    primary = {"n": 1, "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True, "device": "primary"}
    spare = {"n": 2, "x": -1280, "y": 0, "w": 1280, "h": 720, "primary": False, "device": "spare"}
    screens = [primary, spare]
    image, table = tmp_path / "card.raw", tmp_path / "Godzilla (PAD).vpx"
    image.touch()
    table.touch()
    game = Game("godzilla_le", str(image), str(table))
    player.setup.vpx_executable = Mock(return_value=tmp_path / "VPinballX64.exe")
    player.setup.check_vpx = Mock(return_value=Mock(state="Ready"))
    player.inspect_image = Mock(return_value=game)
    monkeypatch.setattr(module.padisplay, "monitors", lambda: screens)
    monkeypatch.setattr(module.play_spike2, "check_controller", Mock())
    monkeypatch.setattr(module.play_spike2.padcontroller.Rig, "board_run", Mock(return_value=None))
    monkeypatch.setattr(module.play_spike2, "embedded_script", lambda _: (
        'Controller.GameName = "godzilla_le"\nCreateObject("Spike2Vpx.Controller")'))
    monkeypatch.setattr(module.padlaunch, "Launch", Mock())
    path = tmp_path / "rig-board" / "display.conf"

    def start(*_, lighting_report, **__):
        assert "monitor=2 mode=fullscreen border=0" in path.read_text()
        assert "x=0 y=0 w=1280 h=720 fs=1" in path.read_text()      # X root coordinates
        lighting_report((), "Stern lighting skipped.")
        return 0

    monkeypatch.setattr(module.play_spike2, "play", start)
    notice = Mock()
    assert player.game_lighting(game) is None
    assert player.play(game, Mock(), lighting_update=notice) == 0
    notice.assert_called_once_with("Stern lighting skipped.")
    assert player.game_lighting(game) == frozenset()
    image.write_bytes(b"replacement build")
    assert player.game_lighting(game) is None
    assert "lcd" not in cabinet.resolve({}, [primary])
    assert "lcd" not in cabinet.resolve({"backglass": "spare"}, screens)
    assert "lcd" not in cabinet.resolve({"lcd": cabinet.WINDOWED_LCD}, screens)
    assert cabinet.resolve({"lcd": "primary"}, [primary])["lcd"] == primary


def test_moved_image_can_restore_the_saved_pairing(player, tmp_path):
    old = Game("godzilla_le", str(tmp_path / "missing.raw"), str(tmp_path / "table.vpx"))
    player.save(old)
    with pytest.raises(ValueError, match="Import image"):
        player.preflight(old)
    with pytest.raises(ValueError, match="Godzilla LE"):
        player.relink_image(old, Game("godzilla_pro", "wrong.raw"))
    game = player.relink_image(old, Game("godzilla_le", str(tmp_path / "new.raw")))
    assert player.library() == [game]
    assert game.table == old.table


def test_recovery_requires_an_expired_owned_record_and_no_live_processes(player, monkeypatch):
    from spike2_vpx import sessions

    board = player.setup.data / "rig-board"
    board.mkdir()
    record = board / "slot-2.run"
    record.write_text('{"emu":"spike2","distro":"SPIKE2-VPX","game":"godzilla_le",'
                      '"label":"PAD-VPX-320","slot":2,"pid":92}')
    stale = time.time() - 300
    probe = Mock(return_value=CompletedProcess([], 0, b"0\n", b""))
    monkeypatch.setattr(sessions, "run", probe)
    monkeypatch.setattr(sessions.padpath, "to_wsl", lambda *_: "/rig")
    with pytest.raises(RuntimeError, match="active or its status"):
        sessions.check_available(player.setup, "godzilla_le")
    probe.assert_not_called()
    os.utime(record, (stale, stale))
    probe.side_effect = [CompletedProcess([], 0, b"", b""), CompletedProcess([], 0, b"1", b"")]
    with pytest.raises(RuntimeError, match="active or its status"):
        sessions.check_available(player.setup, "godzilla_le")
    assert record.is_file()
    probe.side_effect = None
    with pytest.raises(sessions.StaleSession, match="Recover"):
        sessions.check_available(player.setup, "godzilla_le")
    sessions.recover(player.setup, "godzilla_le")
    assert not record.exists()
    assert ("PAD_SLOT=2" in probe.call_args.args[0])
    sessions.check_available(player.setup, "godzilla_le")


def test_recovery_refuses_records_owned_by_another_distribution(player, monkeypatch):
    from spike2_vpx import sessions

    board = player.setup.data / "rig-board"
    board.mkdir()
    record = board / "slot-2.run"
    record.write_text('{"emu":"spike2","distro":"Debian","game":"godzilla_le",'
                      '"label":"PAD-VPX-320","slot":2,"pid":92}')
    with pytest.raises(RuntimeError, match="recovery scope"):
        sessions.recover(player.setup, "godzilla_le")
    assert record.is_file()


def test_game_metadata_and_backup_round_trip_without_machine_registration(player, tmp_path, monkeypatch):
    from spike2_vpx import support
    from spike2_vpx import player as module

    original = Game("godzilla_le", str(tmp_path / "godzilla_le-1_16_0.raw"),
                    str(tmp_path / "Godzilla limited edition (PAD).vpx"))
    player.save(original)
    updated = player.update_game(original, favorite=True, artwork=str(tmp_path / "cover.png"))
    player.record_played(updated)
    assert player.library()[0].last_played
    assert player.table_release(updated) == "Godzilla Limited Edition v2.6"
    assert module.image_version(original.image) == "1.16.0"
    player.setup.settings.update(display_profiles={"Desktop": {"lcd": "windowed"}, "Cabinet": {}},
                                 display_profile="Desktop", volume=55, restart_boot="machine-only")
    path = tmp_path / "backup.json"
    support.atomic_write(path, module.json.dumps(support.backup(player.setup.settings, False)).encode())
    data = support.read_backup(path)
    assert "restart_boot" not in data["preferences"]
    player.setup.settings["games"] = []
    cache_set = Mock()
    monkeypatch.setattr(module.padlaunch, "set_cache_on", cache_set)
    player.restore(data)
    assert player.library()[0].favorite
    assert player.setup.settings["volume"] == 55
    assert player.setup.settings["restart_boot"] == "machine-only"
    assert player.profiles()["Desktop"] == {"lcd": "windowed"}
    cache_set.assert_called_once_with(False)


def test_support_zip_exports_the_preview_without_raw_logs(player, tmp_path):
    from spike2_vpx import support
    from spike2_vpx_setup import Check

    player.log_path.write_text("Normal start\nERROR opening C:\\Users\\example\\table.vpx\n")
    preview = support.report(player.setup, {"vpx": Check("Ready", "VPX 10.8.0 · local")})
    assert "VPX 10.8.0" in preview
    assert "ERROR opening [path removed]" in preview
    assert "example" not in preview and "Normal start" not in preview
    path = tmp_path / "support.zip"
    support.write_report(path, preview)
    with ZipFile(path) as bundle:
        assert bundle.namelist() == ["support-report.txt"]
        assert bundle.read(bundle.namelist()[0]).decode() == preview


def test_audio_test_sends_a_bounded_tone_to_the_windows_default_output(monkeypatch):
    from spike2_vpx import support

    used = []

    def play(path, flags):
        assert flags == 3
        used.append(Path(path))
        with wave.open(path, "rb") as audio:
            assert (audio.getnchannels(), audio.getframerate(), audio.getnframes()) == (1, 16000, 8000)
            assert any(audio.readframes(8000))

    monkeypatch.setitem(sys.modules, "winsound", Mock(PlaySound=play, SND_FILENAME=1, SND_NODEFAULT=2))
    support.test_tone(50)
    assert len(used) == 1 and not used[0].exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows batch launcher")
def test_export_runs_from_another_folder_and_preserves_paths_and_exit_code(player, tmp_path, monkeypatch):
    from spike2_vpx import player as module

    app = tmp_path / "app & files"
    app.mkdir()
    monkeypatch.setattr(module, "APP", app)
    (app / "Play-Spike2Vpx.ps1").write_text(
        "param($Card, $Table, $AppGame)\n"
        "[IO.File]::WriteAllText($env:SPIKE2_EXPORT_TEST_ARGS, "
        "(ConvertTo-Json -Compress @($Card, $Table, $AppGame)))\n"
        "exit 37\n", encoding="ascii")
    image, table = tmp_path / "L’été 100%!.raw", tmp_path / "Godzilla's & Sons (PAD).vpx"
    image.touch()
    table.touch()
    monkeypatch.setattr(module.play_spike2, "embedded_script", lambda _: (
        'Controller.GameName = "godzilla_le"\nCreateObject("Spike2Vpx.Controller")'))
    player.inspect_image = Mock(return_value=Game("godzilla_le", str(image)))
    script = tmp_path / "Launch Godzilla.bat"
    player.export(Game("godzilla_le", str(image), str(table)), script)
    result_file = tmp_path / "arguments.json"
    result = run(["cmd.exe", "/d", "/c", str(script)], cwd=app, capture_output=True, timeout=20,
                 env=dict(os.environ, SPIKE2_EXPORT_TEST_ARGS=str(result_file)))
    assert result.returncode == 37, result.stderr.decode(errors="replace")
    assert module.json.loads(result_file.read_text(encoding="utf-8-sig")) == [
        str(image), str(table), "godzilla_le"]
