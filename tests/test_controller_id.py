"""SPIKE 2 VPX's own controller name, and moving tables off the legacy one."""

from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

KIT = Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "vpx"
sys.path.insert(0, str(KIT))
import controller_id  # noqa: E402
import padmigrate  # noqa: E402

LEGACY_SCRIPT = ("' PAD.Controller once Table1_Init has run\n"
                 "\tSet Controller = CreateObject(\"PAD.Controller\")\n"
                 "\tIf Err Then MsgBox \"Can't load PAD.Controller: \" & Err.Description\n")


class IdentityTest(unittest.TestCase):
    def test_the_fork_has_its_own_name_and_class_id(self):
        self.assertNotEqual(controller_id.PROGID.casefold(), controller_id.LEGACY_PROGID.casefold())
        self.assertNotEqual(controller_id.CLSID.casefold(), controller_id.LEGACY_CLSID.casefold())

    def test_nothing_in_the_kit_creates_the_legacy_controller(self):
        # PADSPIKE2.vbs is static text, so it can't import the name: this keeps it in step.
        made = re.compile(r'CreateObject\(\\?"([^"\\]+\.Controller)\\?"\)', re.I)
        for path in [*KIT.glob("*.py"), *KIT.glob("*.vbs")]:
            for name in made.findall(path.read_text(encoding="utf-8", errors="replace")):
                with self.subTest(path=path.name):
                    self.assertEqual(name, controller_id.PROGID)
        helper = (KIT / "PADSPIKE2.vbs").read_text(encoding="utf-8", errors="replace")
        self.assertIn('CreateObject("%s")' % controller_id.PROGID, helper)


class MoveTest(unittest.TestCase):
    def test_creation_and_its_error_message_move_and_comments_stay(self):
        moved = padmigrate.moved(LEGACY_SCRIPT)
        self.assertIn('CreateObject("Spike2Vpx.Controller")', moved)
        self.assertIn("Can't load Spike2Vpx.Controller: ", moved)
        self.assertTrue(moved.startswith("' PAD.Controller once Table1_Init"))
        self.assertFalse(padmigrate.legacy(moved))
        self.assertTrue(padmigrate.legacy('Set c = createobject("pad.controller")'))

    def test_a_current_table_is_left_alone(self):
        with TemporaryDirectory() as folder:
            table = Path(folder) / "Jaws (PAD).vpx"
            table.write_bytes(b"not read")
            self.assertEqual(padmigrate.controller_in_place(str(table), padmigrate.moved(LEGACY_SCRIPT)), [])
            self.assertEqual(table.read_bytes(), b"not read")

    def test_a_legacy_scripted_table_is_rewritten_and_re_signed_in_place(self):
        written = {}

        class Table:
            def __init__(self, path):
                self.ole = SimpleNamespace(close=lambda: None)
                self.path = path

            def script(self):
                return LEGACY_SCRIPT

            def verify(self):
                return True

        def write_patched(src, dst, script=None):
            written["script"] = script
            Path(dst).write_bytes(b"re-signed")

        fake = SimpleNamespace(VpxTable=Table, write_patched=write_patched)
        with TemporaryDirectory() as folder, patch.dict(sys.modules, vpxfile=fake):
            table = Path(folder) / "Jaws (PAD).vpx"
            table.write_bytes(b"legacy")
            report = padmigrate.controller_in_place(str(table), LEGACY_SCRIPT)
            self.assertEqual(table.read_bytes(), b"re-signed")
            self.assertEqual(written["script"], padmigrate.moved(LEGACY_SCRIPT))
            self.assertEqual(len(report), 1)
            self.assertEqual(list(Path(folder).iterdir()), [table])

    def test_a_table_that_does_not_verify_is_left_as_it_was(self):
        class Table:
            def __init__(self, path):
                self.ole = SimpleNamespace(close=lambda: None)

            def script(self):
                return LEGACY_SCRIPT

            def verify(self):
                return False

        fake = SimpleNamespace(VpxTable=Table,
                               write_patched=lambda src, dst, script=None: Path(dst).write_bytes(b"bad"))
        with TemporaryDirectory() as folder, patch.dict(sys.modules, vpxfile=fake):
            table = Path(folder) / "Jaws (PAD).vpx"
            table.write_bytes(b"legacy")
            with self.assertRaisesRegex(OSError, "does not verify"):
                padmigrate.controller_in_place(str(table), LEGACY_SCRIPT)
            self.assertEqual(table.read_bytes(), b"legacy")
            self.assertEqual(list(Path(folder).iterdir()), [table])

    def test_a_rom_tables_legacy_helper_is_replaced_with_this_apps(self):
        script = 'LoadVPM "01000000","PADSPIKE2.vbs",3.10'
        with TemporaryDirectory() as folder:
            table = Path(folder) / "Godzilla (PAD).vpx"
            helper = Path(folder) / "PADSPIKE2.vbs"
            helper.write_text('Set Controller = CreateObject("PAD.Controller")', encoding="utf-8")
            self.assertEqual(len(padmigrate.controller_in_place(str(table), script)), 1)
            self.assertEqual(helper.read_bytes(), (KIT / "PADSPIKE2.vbs").read_bytes())
            self.assertEqual(padmigrate.controller_in_place(str(table), script), [])


@unittest.skipUnless(sys.platform == "win32", "Windows registry")
class LegacyRegistrationTest(unittest.TestCase):
    def check_drop(self, path):
        import standalone_controller as controller

        registry = SimpleNamespace(HKEY_LOCAL_MACHINE=0, QueryValue=lambda root, key: path)
        register = SimpleNamespace(UnregisterServer=Mock())
        server = SimpleNamespace(register=register)
        with patch.dict(sys.modules, {"win32com": SimpleNamespace(server=server),
                                      "win32com.server": server, "win32com.server.register": register}):
            controller.drop_legacy(registry)
        return register.UnregisterServer

    def test_registering_drops_this_installations_legacy_name_only(self):
        self.check_drop(str(KIT)).assert_called_once_with(
            controller_id.LEGACY_CLSID, controller_id.LEGACY_PROGID)
        self.check_drop(r"D:\Program Files\Pinball Asset Decryptor\tools\spike2_emu\vpx").assert_not_called()
