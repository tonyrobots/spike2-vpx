"""Check or register this copy of the SPIKE 2 VPX COM server."""

from contextlib import redirect_stderr, redirect_stdout
import json
import os
import sys

# The bundled Python uses an isolated search path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import controller_id  # noqa: E402
import padcontroller  # noqa: E402
import vpxsetup  # noqa: E402


def registration(root, prefix="", progid=controller_id.PROGID, clsid_=controller_id.CLSID):
    import winreg

    def default(key):
        try:
            return winreg.QueryValue(root, prefix + key) or ""
        except FileNotFoundError:
            return ""

    clsid = default(rf"{progid}\CLSID")
    base = rf"CLSID\{clsid_}"
    paths = default(base + r"\PythonCOMPath")
    server = default(base + r"\LocalServer32")
    if (clsid and clsid.casefold() != clsid_.casefold()
            or paths and not vpxsetup.registered_here(paths)
            or server and not paths):
        return "foreign"
    if clsid and vpxsetup.registration_ok(paths, server):
        expected = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        actual = vpxsetup.server_exe(server)
        if os.path.normcase(os.path.realpath(actual)) == os.path.normcase(os.path.realpath(expected)):
            return "ours"
    return "partial" if clsid or paths or server else "absent"


def check():
    import winreg

    if padcontroller.pythoncom is None:
        return "Unavailable", "Repair this app’s Python bundle to install pywin32."
    state = registration(winreg.HKEY_CLASSES_ROOT)
    if state == "foreign":
        return "Needs attention", f"{controller_id.PROGID} belongs to another installation. " \
            "Unregister it from that installation, then check again."
    if state == "absent":
        return "Missing", "Set up registers the bundled controller with Windows."
    if state == "ours":
        import win32com.client

        try:
            controller = win32com.client.Dispatch(controller_id.PROGID,
                                                 clsctx=padcontroller.pythoncom.CLSCTX_LOCAL_SERVER)
            if str(controller.Version) == padcontroller.VERSION:
                return "Ready", "Windows activated the controller bundled with this app."
        except padcontroller.pythoncom.com_error as exc:
            return "Repair needed", f"Windows could not activate the bundled controller. {exc}"
    return "Repair needed", "Set up repairs the bundled controller’s COM registration."


def change(action):
    import winreg

    # Check the machine registry directly as the elevated user may be a
    # different account from the player who ran the first check.
    state = registration(winreg.HKEY_LOCAL_MACHINE, "Software\\Classes\\")
    if action == "unregister":
        if state == "ours":
            padcontroller.main(["--unregister"])
        return
    if state == "foreign" or registration(winreg.HKEY_CLASSES_ROOT) == "foreign":
        raise RuntimeError(f"{controller_id.PROGID} belongs to another installation.")
    padcontroller.main(["--register"])
    drop_legacy(winreg)


def drop_legacy(winreg):
    """Unregister the PAD.Controller this installation registered before it had
    its own name (0.1.0), so an upgrade leaves no registration behind pointing
    here. One that another app (Pinball Asset Decryptor) owns is left alone."""
    try:
        path = winreg.QueryValue(winreg.HKEY_LOCAL_MACHINE,
                                 rf"Software\Classes\CLSID\{controller_id.LEGACY_CLSID}\PythonCOMPath")
    except OSError:
        return
    if vpxsetup.registered_here(path):
        from win32com.server import register

        register.UnregisterServer(controller_id.LEGACY_CLSID, controller_id.LEGACY_PROGID)
        print(f"unregistered this installation's {controller_id.LEGACY_PROGID}")


def main():
    action = sys.argv[1]
    if action == "check":
        print(json.dumps(check()))
    elif action == "unregister":
        change(action)
    elif action == "register":
        import traceback

        with open(sys.argv[2], "w", encoding="utf-8") as log:
            with redirect_stdout(log), redirect_stderr(log):
                try:
                    change(action)
                except Exception:
                    traceback.print_exc()
                    return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
