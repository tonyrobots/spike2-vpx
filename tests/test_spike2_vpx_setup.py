from pathlib import Path
from subprocess import CompletedProcess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import spike2_vpx_setup as setup


def result(code=0, output=b""):
    return CompletedProcess([], code, output, b"")


class StandaloneSetupTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app = setup.Setup(folder.name)
        self.addCleanup(self.app.log.handlers[0].close)

    def test_reboot_survives_relaunch_and_clears_after_a_new_boot(self):
        with patch.object(setup, "boot_session", return_value="100"), \
                patch.object(setup, "elevated", return_value=result(3010)):
            self.app.install_platform("Install")
            reopened = setup.Setup(self.app.data)
            self.addCleanup(reopened.log.handlers[0].close)
            self.assertEqual(reopened.check_wsl().state, "Restart required")
        with patch.object(setup, "boot_session", return_value="200"), \
                patch.object(setup, "run", return_value=result()):
            self.assertEqual(reopened.check_wsl().state, "Ready")
        self.assertNotIn("restart_boot", reopened.settings_path.read_text())

    def test_wsl_failure_has_a_retry_and_does_not_set_a_restart(self):
        def checks():
            return {"wsl": self.app.probe("wsl", self.app.check_wsl)}

        with patch.object(self.app, "checks", side_effect=checks), \
                patch.object(setup, "boot_session", return_value="100"), \
                patch.object(setup, "elevated", return_value=result(1)), \
                patch.object(setup, "run", return_value=result(1)):
            check = self.app.repair("wsl", "install_wsl")["wsl"]
        self.assertEqual((check.state, check.action), ("Setup failed", "install_wsl"))
        self.assertNotIn("restart_boot", self.app.settings)
        self.assertIn("Elevated WSL command", self.app.log_path.read_text(encoding="utf-8"))

    def test_wsl_install_prompt_offers_automated_install_even_on_success_exit(self):
        prompt = "To install, run 'wsl.exe --install'.".encode("utf-16-le")
        with patch.object(setup, "run", return_value=result(output=prompt)):
            check = self.app.check_wsl()
        self.assertEqual((check.state, check.action), ("Missing", "install_wsl"))

    def test_wsl_virtualization_error_offers_firmware_guidance(self):
        for code in (b"HCS_E_HYPERV_NOT_INSTALLED", b"0x80370102"):
            with patch.object(setup, "run", return_value=result(output=code)):
                check = self.app.check_wsl()
            self.assertEqual(check.state, "Needs attention")
            self.assertIn("Intel VT-x or AMD-V", check.detail)

        with patch.object(setup, "distro_registration", return_value=(self.app.runtime_dir, 2)), \
                patch.object(self.app, "wsl", return_value=result(1, b"HCS_E_HYPERV_NOT_INSTALLED")):
            check = self.app.probe("runtime", self.app.check_runtime)
        self.assertEqual(check.state, "Needs attention")
        self.assertIn("BIOS/UEFI", check.detail)

    def test_wslg_requires_session_sockets_for_ready(self):
        version = result(output="WSL version: 2.6.0\r\nWSLg version: 1.0.71\r\n".encode("utf-16-le"))
        with patch.object(setup, "run", return_value=version), \
                patch.object(self.app, "wsl", side_effect=[result(1), result()]) as wsl:
            self.assertEqual(self.app.check_wslg(setup.Check("Missing", "")).state, "Detected")
            self.assertEqual(self.app.check_wslg(setup.Check("Ready", "")).state, "Needs attention")
            self.assertEqual(self.app.check_wslg(setup.Check("Ready", "")).state, "Ready")
        self.assertIn("PULSE_SERVER", wsl.call_args.args[-1])

    def test_runtime_only_accepts_its_own_full_wsl2_distro(self):
        with patch.object(setup, "distro_registration", return_value=(Path("another"), 2)), \
                patch.object(self.app, "wsl") as wsl:
            self.assertEqual(self.app.check_runtime().state, "Needs attention")
            wsl.assert_not_called()
        with patch.object(setup, "distro_registration", return_value=(self.app.runtime_dir, 1)):
            self.assertEqual(self.app.check_runtime().action, "convert_runtime")
        manifest = result(output=(
            f'{{"runtime_version": {setup.runtime.RUNTIME_VERSION}, "variant": "full"}}'.encode()
        ))
        with patch.object(setup, "distro_registration", return_value=(self.app.runtime_dir, 2)), \
                patch.object(self.app, "wsl", side_effect=[manifest, result(output=b"/mnt/c/Program Files"), result()]) as wsl, \
                patch.object(self.app, "arm_execution", return_value=result()) as arm:
            self.assertEqual(self.app.check_runtime().state, "Ready")
        self.assertEqual(wsl.call_args.args[-1], "/mnt/c/Program Files")
        arm.assert_called_once_with("/mnt/c/Program Files", "check")

    def test_runtime_converts_only_its_own_wsl1_distribution_as_the_player(self):
        with patch.object(setup, "distro_registration", return_value=(Path("another"), 1)), \
                patch.object(setup, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "this app's"):
                self.app.convert_runtime()
            run.assert_not_called()
        with patch.object(setup, "distro_registration", return_value=(self.app.runtime_dir, 1)), \
                patch.object(setup, "run", return_value=result()) as run:
            self.app.convert_runtime()
        run.assert_called_once_with(["wsl.exe", "--set-version", setup.DISTRO, "2"], timeout=1800)

    def test_runtime_repairs_missing_arm_handler_and_only_reports_ready_after_probe(self):
        manifest = result(output=(
            f'{{"runtime_version": {setup.runtime.RUNTIME_VERSION}, "variant": "full"}}'.encode()
        ))
        for recovery, expected in ((result(), ("Ready", "")),
                                   (result(1, b"registration refused"), ("Repair needed", "repair_arm"))):
            with patch.object(setup, "distro_registration", return_value=(self.app.runtime_dir, 2)), \
                    patch.object(self.app, "wsl", side_effect=[manifest, result(output=b"/rig"), result()]), \
                    patch.object(self.app, "arm_execution", side_effect=[result(10), recovery]) as arm:
                check = self.app.check_runtime()
            self.assertEqual((check.state, check.action), expected)
            self.assertEqual([call.args for call in arm.call_args_list], [("/rig", "check"), ("/rig", "repair")])

    def test_missing_runtime_import_uses_verified_file_and_private_storage(self):
        with patch.object(setup, "distro_registration", return_value=None), \
                patch.object(setup.payloads, "verify", return_value=(True, "")), \
                patch.object(setup.runtime, "import_image") as import_image:
            self.app.install_runtime()
        distro, target, archive = import_image.call_args.args
        self.assertEqual(distro, "SPIKE2-VPX")
        self.assertEqual(Path(target), self.app.runtime_dir)
        self.assertEqual(Path(archive).parent, self.app.data / "downloads")

    def test_vpx_does_not_read_the_inherited_kit_and_saves_browse_selection(self):
        with patch.object(setup.vpxsetup, "find_vpx", return_value="") as find:
            self.assertEqual(self.app.check_vpx().state, "Missing")
        find.assert_called_once_with(use_kit=False)
        path = self.app.data / "VPinballX64.exe"
        path.touch()
        self.app.choose_vpx(path)
        with patch.object(setup.vpxsetup, "vpx_version", side_effect=[(10, 7, 4), (10, 8, 0)]):
            self.assertEqual(self.app.check_vpx().state, "Needs attention")
            self.assertEqual(self.app.check_vpx().state, "Ready")
        self.assertEqual(self.app.settings["vpx_dir"], str(path.parent.resolve()))

    def test_one_folder_gives_directx_for_desktop_and_opengl_for_vr(self):
        folder = Path(self.app.data).resolve()
        dx9, gl = folder / "VPinballX64.exe", folder / "VPinballX_GL64.exe"
        dx9.touch()
        gl.touch()
        self.app.choose_vpx(folder)
        self.assertEqual(self.app.vpx_executable(), dx9)
        self.assertEqual(self.app.vpx_executable(vr=True), gl)
        self.assertEqual(self.app.settings["vpx_exe"], str(dx9))   # what app 0.1.0 reads
        with patch.object(setup.vpxsetup, "vpx_version", return_value=(10, 8, 0)) as version:
            check = self.app.check_vpx()
        version.assert_called_once_with(dx9)
        self.assertEqual(check.state, "Ready")
        self.assertIn("VR available", check.detail)

    def test_a_folder_without_opengl_is_desktop_only(self):
        folder = Path(self.app.data).resolve()
        (folder / "VPinballX64.exe").touch()
        self.app.choose_vpx(folder / "VPinballX64.exe")       # picking a player picks its folder
        self.assertIsNone(self.app.vpx_executable(vr=True))
        with patch.object(setup.vpxsetup, "vpx_version", return_value=(10, 8, 0)):
            self.assertIn("desktop only (VR needs VPinballX_GL64.exe)", self.app.check_vpx().detail)

    def test_opengl_alone_serves_desktop_and_vr(self):
        folder = Path(self.app.data).resolve()
        (folder / "VPinballX_GL64.exe").touch()
        self.app.choose_vpx(folder)
        self.assertEqual(self.app.vpx_executable(), folder / "VPinballX_GL64.exe")
        self.assertEqual(self.app.vpx_executable(vr=True), folder / "VPinballX_GL64.exe")

    def test_choose_vpx_refuses_a_folder_without_a_player(self):
        (self.app.data / "VPinballX.exe").touch()
        with self.assertRaisesRegex(ValueError, "no VPinballX64.exe or VPinballX_GL64.exe"):
            self.app.choose_vpx(self.app.data)
        self.assertNotIn("vpx_dir", self.app.settings)

    def test_an_older_saved_exe_is_read_as_its_folder(self):
        folder = Path(self.app.data).resolve()
        (folder / "VPinballX64.exe").touch()
        (folder / "VPinballX_GL64.exe").touch()
        self.app.settings["vpx_exe"] = str(folder / "VPinballX64.exe")
        self.assertEqual(self.app.vpx_executable(vr=True), folder / "VPinballX_GL64.exe")

    def test_players_are_matched_by_name_whatever_the_case(self):
        self.assertTrue(setup.vpxsetup.vpx_player("C:/VPX/vpinballx_gl64.EXE")["vr"])
        self.assertIsNone(setup.vpxsetup.vpx_player("C:/VPX/VPinballX.exe"))
        self.assertEqual(setup.vpxsetup.vpx_exe_for(""), "")

    def test_controller_probe_never_offers_to_take_over_another_installation(self):
        with patch.object(setup, "run", side_effect=[
            result(output=b'["Needs attention","PAD.Controller belongs to another installation."]'),
            result(output=b'["Missing","Register the bundled server."]'),
        ]):
            self.assertEqual(self.app.check_controller().action, "")
            self.assertEqual(self.app.check_controller().action, "register_controller")

    @unittest.skipUnless(sys.platform == "win32", "Windows registry")
    def test_controller_mutations_refuse_foreign_machine_registration(self):
        import standalone_controller as controller

        with patch.object(controller, "registration", return_value="foreign"), \
                patch.object(controller.padcontroller, "main") as change:
            with self.assertRaisesRegex(RuntimeError, "another installation"):
                controller.change("register")
            controller.change("unregister")
            change.assert_not_called()
