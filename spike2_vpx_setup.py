"""Setup checks and actions for the standalone Windows player."""

from dataclasses import dataclass
from pathlib import Path
import base64
import json
import logging
import os
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile

from spike2_vpx import payloads, runtime, wsl_up

APP = Path(__file__).resolve().parent
RIG = APP / "tools" / "spike2_emu"
KIT = RIG / "vpx"
sys.path.insert(0, str(KIT))
import vpxsetup  # noqa: E402

DISTRO = "SPIKE2-VPX"
VPX_RELEASE = "https://github.com/vpinball/vpinball/releases/tag/v10.8.0-2051-28dd6c3"
VIRTUALIZATION_HELP = "https://support.microsoft.com/en-us/windows/experience/enable-virtualization-on-windows"
VIRTUALIZATION_GUIDANCE = (
    "WSL 2 could not use hardware virtualization. In Task Manager → Performance → CPU, "
    "check Virtualization. If disabled, enable Intel VT-x or AMD-V (SVM Mode) in your PC's "
    "BIOS/UEFI, then restart and reopen the app. On a virtual machine, check nested "
    "virtualization on the host."
)
ROWS = {
    "wsl": "WSL 2",
    "wslg": "WSLg display and audio",
    "runtime": "SPIKE 2 runtime",
    "vpx": "Visual Pinball X",
    "controller": "PAD.Controller",
}


@dataclass(frozen=True)
class Check:
    state: str
    detail: str
    action: str = ""


def needs_virtualization(detail):
    text = detail.casefold()
    return any(code in text for code in (
        "hcs_e_hyperv_not_installed", "0x80370102", "wsl_e_wsl2_not_supported",
    ))


def run(command, timeout=30):
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                          env=dict(os.environ, WSL_UTF8="1"), timeout=timeout)


def boot_session():
    out = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
               "(Get-CimInstance Win32_OperatingSystem -ErrorAction Stop)"
               ".LastBootUpTime.ToUniversalTime().Ticks"])
    boot = out.stdout.decode("ascii", "replace").strip()
    if out.returncode or not boot.isdigit():
        raise RuntimeError("Windows did not report its current boot session.")
    return boot


def elevated(exe, args, timeout):
    def ps_literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    arguments = subprocess.list2cmdline([str(arg) for arg in args])
    command = (
        f"$ErrorActionPreference='Stop'; "
        f"$p=Start-Process -FilePath {ps_literal(exe)} -ArgumentList "
        f"{ps_literal(arguments)} -Verb RunAs -Wait -PassThru -WindowStyle Hidden; "
        "exit $p.ExitCode"
    )
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                encoded], timeout=timeout)


def vpx_names():
    """The known VPX players for messages: "A or B"."""
    return " or ".join(vpxsetup.vpx_exe_names())


def distro_registration():
    record = wsl_up.distribution_record(DISTRO)
    if record is None:
        return None
    path, version = record
    return Path(path), version


class Setup:
    def __init__(self, data=None):
        self.data = Path(data or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Spike2Vpx")
        self.log_path = self.data / "logs" / "setup.log"
        self.platform_log = self.log_path.with_name("wsl-platform.log")
        self.controller_log = self.log_path.with_name("controller-registration.log")
        self.settings_path = self.data / "setup.json"
        self.runtime_dir = self.data / "runtime"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = logging.Logger("spike2-vpx-setup")
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.log.addHandler(handler)
        try:
            settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.settings = settings if isinstance(settings, dict) else {}
        except (OSError, ValueError):
            self.settings = {}

    def save(self):
        with NamedTemporaryFile(mode="w", dir=self.data, encoding="utf-8",
                                suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(self.settings, file, indent=2)
        try:
            temporary.replace(self.settings_path)
        finally:
            temporary.unlink(missing_ok=True)

    def choose_vpx(self, path):
        """Save the Visual Pinball X folder: *path* is the folder, or one of
        the players in it."""
        folder = Path(path).resolve()
        if folder.is_file() and vpxsetup.vpx_player(folder):
            folder = folder.parent
        if not vpxsetup.vpx_exe_for(str(folder)):
            raise ValueError(f"That folder has no {vpx_names()}. "
                             "Choose the folder Visual Pinball X is installed in.")
        self.settings["vpx_dir"] = str(folder)
        # app 0.1.0 reads only vpx_exe, and shares this file with newer versions
        self.settings["vpx_exe"] = vpxsetup.vpx_exe_for(str(folder))
        self.save()

    def check_wsl(self):
        pending = self.settings.get("restart_boot")
        if pending:
            if pending == boot_session():
                return Check("Restart required", "Restart Windows, then reopen SPIKE 2 VPX.")
            self.settings.pop("restart_boot")
            self.save()
        missing = Check("Missing", "Select Set up and approve the Windows administrator prompt. "
                        "The app installs WSL 2 without adding Ubuntu.", "install_wsl")
        try:
            out = run(["wsl.exe", "--status"])
        except FileNotFoundError:
            return missing
        detail = runtime._why(out)
        status = detail.casefold()
        if needs_virtualization(detail):
            return Check("Needs attention", VIRTUALIZATION_GUIDANCE, "install_wsl")
        if out.returncode == 0 and not any(message in status for message in (
            "--install", "virtual machine platform", "wsl_e_wsl_optional_component_required",
        )):
            return Check("Ready", "Windows reports WSL available. The runtime check verifies WSL 2 can start.")
        if "e_accessdenied" in status:
            raise RuntimeError(detail)
        self.log.info("WSL status: %s", detail)
        return missing

    def check_wslg(self, linux):
        out = run(["wsl.exe", "--version"])
        match = re.search(r"(?im)^WSLg[^:\r\n]*:\s*(\d+\.\d+(?:\.\d+)*)",
                          runtime._text(out.stdout).lstrip("\ufeff"))
        if out.returncode != 0 or not match:
            return Check("Missing", "Set up updates WSL to add Linux display and audio support.", "update_wsl")
        if linux.state == "Ready":
            return self.check_wslg_session()
        return Check("Detected", f"WSLg {match[1]} is installed. Install the runtime to check its session.")

    def wsl(self, *command, timeout=60):
        return run(["wsl.exe", "-d", DISTRO, "-e", *command], timeout=timeout)

    def arm_execution(self, linux_rig, mode):
        return run(["wsl.exe", "-d", DISTRO, "-u", "root", "-e", "bash",
                    linux_rig + "/vpx_arm_exec.sh", mode], timeout=30)

    def check_runtime(self):
        registered = distro_registration()
        if registered is None:
            return Check("Missing", "Set up downloads and imports this app’s SPIKE 2 Linux runtime.",
                         "install_runtime")
        base, version = registered
        if base.resolve() != self.runtime_dir.resolve():
            return Check("Needs attention", f"Another WSL distribution uses {DISTRO}. "
                         "Resolve the name conflict, then check again.")
        if version != 2:
            return Check("Repair needed", f"{DISTRO} is registered as WSL 1. "
                         "Back up its data, then select Repair to convert it to WSL 2.",
                         "convert_runtime")
        manifest = self.wsl("cat", "/etc/pad-runtime.json")
        if manifest.returncode:
            raise RuntimeError(runtime._why(manifest))
        image = json.loads(runtime._text(manifest.stdout))
        if (not isinstance(image, dict) or image.get("variant") != "full"
                or image.get("runtime_version") != runtime.RUNTIME_VERSION):
            return Check("Needs attention", f"{DISTRO} needs the full runtime version "
                         f"{runtime.RUNTIME_VERSION}. Back up its data before replacing it.")
        rig = self.wsl("wslpath", "-a", "-u", str(RIG))
        if rig.returncode:
            raise RuntimeError(runtime._why(rig))
        linux_rig = runtime._text(rig.stdout).strip()
        probe = self.wsl("bash", "-ec",
                         'for tool in arm-linux-gnueabihf-gcc gcc '
                         'debugfs fuse2fs fusermount3 ffmpeg python3; do '
                         'command -v "$tool" >/dev/null || { echo "Missing $tool"; exit 1; }; done; '
                         'for file in hwshim.c rootfs.sh playaudio.sh lcdring.py padlink.py padpath.sh; do '
                         'test -r "$1/$file" || { echo "Cannot read $file"; exit 1; }; done; '
                         'python3 -B -c \'import runpy,sys; runpy.run_path(sys.argv[1])\' "$1/padlink.py"',
                         "setup", linux_rig)
        if probe.returncode:
            raise RuntimeError(runtime._why(probe))
        arm = self.arm_execution(linux_rig, "check")
        if arm.returncode == 10:
            self.log.info("Restoring ARM execution for %s: %s", DISTRO, runtime._why(arm))
            arm = self.arm_execution(linux_rig, "repair")
            if arm.returncode:
                return Check("Repair needed", f"WSL could not restore ARM execution. {runtime._why(arm)}",
                             "repair_arm")
        if arm.returncode:
            raise RuntimeError(runtime._why(arm))
        return Check("Ready", f"{DISTRO} · runtime {runtime.RUNTIME_VERSION} · ARM execution verified in a chroot.")

    def repair_arm(self):
        registered = distro_registration()
        if registered is None or registered[0].resolve() != self.runtime_dir.resolve() or registered[1] != 2:
            raise RuntimeError("ARM repair requires this app's SPIKE 2 WSL 2 distribution.")
        rig = self.wsl("wslpath", "-a", "-u", str(RIG))
        if rig.returncode:
            raise RuntimeError(runtime._why(rig))
        out = self.arm_execution(runtime._text(rig.stdout).strip(), "repair")
        if out.returncode:
            raise RuntimeError(runtime._why(out))

    def convert_runtime(self):
        registered = distro_registration()
        if registered is None or registered[0].resolve() != self.runtime_dir.resolve() or registered[1] != 1:
            raise RuntimeError("Conversion requires this app's SPIKE 2 WSL 1 distribution.")
        out = run(["wsl.exe", "--set-version", DISTRO, "2"], timeout=1800)
        if out.returncode:
            raise RuntimeError(runtime._why(out))

    def check_wslg_session(self):
        out = self.wsl("sh", "-ec",
                       'test -n "$DISPLAY" && test -S /mnt/wslg/.X11-unix/X0 && '
                       'test -S "${PULSE_SERVER#unix:}"')
        if out.returncode:
            return Check("Needs attention", "The runtime cannot see WSLg display or audio. "
                         "Enable GUI applications in WSL settings, restart WSL, then check again.")
        return Check("Ready", "The SPIKE 2 runtime can see the WSLg display and audio sockets.")

    def vpx_folder(self):
        """The chosen Visual Pinball X folder (an older setup.json saved an
        exe: its folder), else the first one found."""
        saved = self.settings.get("vpx_dir")
        if isinstance(saved, str) and saved:
            return Path(saved)
        legacy = self.settings.get("vpx_exe")
        if isinstance(legacy, str) and legacy:
            return Path(legacy).parent
        found = vpxsetup.find_vpx(use_kit=False)
        return Path(found) if found else None

    def vpx_executable(self, vr=False):
        """The player to launch from the VPX folder: desktop play, or VR."""
        folder = self.vpx_folder()
        exe = vpxsetup.vpx_exe_for(str(folder), vr) if folder else ""
        return Path(exe) if exe else None

    def check_vpx(self):
        exe = self.vpx_executable()
        if exe is None or not exe.is_file():
            return Check("Missing", "Install Visual Pinball X 10.8 or newer (Windows x64), "
                         "then choose its folder.")
        version = vpxsetup.vpx_version(exe)
        if version is None:
            return Check("Needs attention", f"Windows could not read the version of {exe.name}. "
                         "Choose a folder with a compatible Visual Pinball X.")
        if version < vpxsetup.VPX_MIN:
            return Check("Needs attention", f"VPX {vpxsetup.dotted(version)} detected. "
                         f"Install version {vpxsetup.dotted(vpxsetup.VPX_MIN)} or newer.")
        vr = self.vpx_executable(vr=True)
        builds = (f"VR available ({vr.name})" if vr else
                  "desktop only (VR needs " + next(p["name"] for p in vpxsetup.VPX_EXES if p["vr"]) + ")")
        return Check("Ready", f"VPX {vpxsetup.dotted(version)} · {exe.parent} · {builds}")

    def check_controller(self):
        return self.controller("check")

    def controller(self, action):
        exe = Path(sys.executable).with_name("python.exe")
        if not exe.is_file():
            exe = Path(sys.executable)
        args = [str(KIT / "standalone_controller.py"), action]
        if action == "register":
            out = elevated(exe, [*args, str(self.controller_log)], timeout=300)
            if out.returncode:
                raise RuntimeError(f"Controller registration failed or elevation was declined. "
                                   f"Details in {self.controller_log}.")
            return
        out = run([str(exe), *args], timeout=30)
        if out.returncode:
            raise RuntimeError(runtime._why(out))
        state, detail = json.loads(out.stdout)
        return Check(state, detail, "register_controller" if state in ("Missing", "Repair needed") else "")

    def probe(self, name, fn):
        try:
            check = fn()
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
            self.log.exception("%s check failed", ROWS[name])
            detail = str(exc)
            if name == "runtime" and needs_virtualization(detail):
                check = Check("Needs attention", VIRTUALIZATION_GUIDANCE)
            else:
                check = Check("Check failed", f"{detail} See the setup log and check again.")
        self.log.info("%s — %s: %s", ROWS[name], check.state, check.detail)
        failure = self.settings.get("failure")
        if isinstance(failure, dict) and failure.get("row") == name and failure.get("detail"):
            if check.state in ("Ready", "Detected", "Restart required"):
                self.settings.pop("failure")
                self.save()
            else:
                return Check("Setup failed", f"{failure['detail']} {check.detail} See the setup log.",
                             check.action)
        return check

    def checks(self):
        if sys.platform != "win32" or sys.getwindowsversion().build < 19044:
            return {key: Check("Unavailable", "Requires Windows 11 or Windows 10 build 19044 or newer.")
                    for key in ROWS}
        wsl = self.probe("wsl", self.check_wsl)
        if wsl.state == "Ready":
            linux = self.probe("runtime", self.check_runtime)
            wslg = self.probe("wslg", lambda: self.check_wslg(linux))
            if linux.state == "Ready":
                wsl = Check("Ready", f"WSL 2 started the {DISTRO} distribution.")
        else:
            wslg = linux = Check("Waiting", "Complete WSL 2 setup first.")
        return {"wsl": wsl, "wslg": wslg, "runtime": linux,
                "vpx": self.probe("vpx", self.check_vpx),
                "controller": self.probe("controller", self.check_controller)}

    def install_platform(self, mode):
        boot = boot_session()
        out = elevated("powershell.exe",
                       ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", APP / "installer" / "setup_spike2_wsl.ps1",
                        "-Mode", mode, "-Log", self.platform_log], timeout=900)
        if out.returncode == 3010:
            self.settings["restart_boot"] = boot
            self.save()
        elif out.returncode:
            self.log.error("Elevated WSL command: %s. Platform log: %s",
                           runtime._why(out), self.platform_log)
            raise RuntimeError("WSL setup failed or administrator permission was declined.")

    def install_runtime(self):
        if distro_registration() is not None:
            raise RuntimeError(f"{DISTRO} already exists. Check its status before attempting another import.")
        if self.runtime_dir.exists() and any(self.runtime_dir.iterdir()):
            raise RuntimeError(f"A previous import left files in {self.runtime_dir}. "
                               "Move that folder to a backup location before retrying.")
        image = runtime.IMAGE
        stamp = image.sha256[:12]
        cache = self.data / "downloads" / f"{stamp}-{image.filename}"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not payloads.verify(str(cache), image)[0]:
            runtime._need_room(str(cache.parent), image.size + runtime.DOWNLOAD_SLACK,
                               "download the SPIKE 2 runtime")
            payloads.download(image, str(cache), log=self.log.info)
        runtime.import_image(DISTRO, str(self.runtime_dir), str(cache))

    def repair(self, key, action):
        steps = {"install_wsl": lambda: self.install_platform("Install"),
                 "update_wsl": lambda: self.install_platform("Update"),
                 "install_runtime": self.install_runtime,
                 "convert_runtime": self.convert_runtime,
                 "repair_arm": self.repair_arm,
                 "register_controller": lambda: self.controller("register")}
        self.settings.pop("failure", None)
        self.save()
        self.log.info("Setting up %s", ROWS[key])
        try:
            steps[action]()
            checks = self.checks()
            if checks[key].state in ("Ready", "Detected", "Restart required"):
                return checks
            if key == "wslg" and "restart_boot" in self.settings:
                return checks
            raise RuntimeError(f"{ROWS[key]} did not pass its check after setup.")
        except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
            self.log.exception("%s setup failed", ROWS[key])
            detail = str(exc)
            if key == "runtime" and needs_virtualization(detail):
                detail = VIRTUALIZATION_GUIDANCE
            self.settings["failure"] = {"row": key, "detail": detail}
            self.save()
            return self.checks()
