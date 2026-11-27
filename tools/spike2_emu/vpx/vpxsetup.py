#!/usr/bin/env python3
"""Visual Pinball discovery, table metadata and cabinet settings."""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for path in (HERE, RIG):
    if path not in sys.path:
        sys.path.insert(0, path)

import controller_id  # noqa: E402
import padcabinet  # noqa: E402
import padisplay   # noqa: E402
import padlaunch   # noqa: E402
import padvpx      # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))

VPX_DEFAULT_DIR = r"C:\Visual Pinball"

VPX_MIN = (10, 8, 0)

def controller_registration():
    """(registered, the folder PAD.Controller is registered to): registered
    only when what it points at is still there (PAD-850). The key alone said
    "Registered" while the folder it named had been deleted, and every table
    then stopped on "Can't load PAD.Controller: ActiveX component can't
    create object"; now the tab offers Register again instead."""
    try:
        import winreg
        root = winreg.HKEY_CLASSES_ROOT
        clsid = winreg.QueryValue(root, controller_id.PROGID + "\\CLSID")
        path = winreg.QueryValue(root, "CLSID\\%s\\PythonCOMPath" % clsid)
        server = winreg.QueryValue(root, "CLSID\\%s\\LocalServer32" % clsid)
    except Exception:                                       # noqa: BLE001
        return False, ""
    return registration_ok(path, server), path or ""

def registered_here(path):
    """The registered folder is THIS kit's (PAD-943). A table patched by
    one copy of the app calls whichever PAD.Controller the registry names:
    David's Spike 1 tables stopped on "no Spike 2 run is up" because the
    registration was an older checkout's, with no Spike 1 in it."""
    if not path:
        return False
    try:
        return os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(HERE))
    except OSError:
        return False

def server_exe(server_cmd):
    """The program a LocalServer32 command starts.

    PAD-1229: pywin32 writes that command as ``GetShortPathName(pythonw.exe)``
    with NO quotes, and on a PC with 8.3 short names off (common on a second
    drive, and on some Windows installs) the "short" name is the long one,
    spaces and all: ``C:\\Program Files\\Pinball Asset Decryptor\\python\\
    pythonw.exe "...localserver.py" {clsid}``.  Cut at the first space that
    read "C:\\Program", the check said not registered, and Register said
    "was the administrator prompt declined?" on a PC where it had worked.
    So an unquoted command is read up to the first ``.exe`` the way Windows
    reads it, not to the first space."""
    cmd = (server_cmd or "").strip()
    if cmd.startswith('"'):
        return cmd[1:].split('"', 1)[0]
    low = cmd.lower()
    at = 0
    while True:
        i = low.find(".exe", at)
        if i < 0:
            break
        end = i + 4
        if end == len(cmd) or cmd[end] in " \t":
            return cmd[:end]
        at = end
    return cmd.split(" ", 1)[0]

def quoted_server_cmd(server_cmd):
    """*server_cmd* with its program in quotes when it has a space and none
    (PAD-1229, see server_exe): Windows has to guess where an unquoted path
    with spaces ends.  None when nothing needs changing."""
    cmd = (server_cmd or "").strip()
    if not cmd or cmd.startswith('"'):
        return None
    exe = server_exe(cmd)
    if " " not in exe:
        return None
    return '"%s"%s' % (exe, cmd[len(exe):])

def registration_ok(com_path, server_cmd):
    """The registered folder holds padcontroller.py, and the python the
    server command starts exists."""
    exe = server_exe(server_cmd)
    return (bool(com_path) and os.path.isfile(os.path.join(com_path, "padcontroller.py"))
            and bool(exe) and os.path.isfile(exe))

#: The Visual Pinball X players a VPX folder can hold, in order of preference
#: for desktop play. VR exists only in the OpenGL build (VPX 10.8's stdafx.h
#: defines ENABLE_VR only with ENABLE_SDL), so a VR launch takes the first
#: one marked "vr".
VPX_EXES = (
    {"name": "VPinballX64.exe", "build": "DirectX 9", "vr": False},
    {"name": "VPinballX_GL64.exe", "build": "OpenGL", "vr": True},
)

#: The VPX INI keys a launch of a VR-capable player sets, by whether it plays
#: in VR, and puts back when VPX closes. [PlayerVR] AskToTurnOn: 0 = VR
#: whenever a runtime is installed, 2 = never (VPX 10.8 player.cpp:126; its
#: default is 0, so a desktop launch of the OpenGL build must say 2). The
#: captures bring outside windows into the VR backbox (captureExt.cpp): the
#: "Virtual DMD" window as its DMD, B2S/PUP as its backglass.
VR_INI = {
    True: {"PlayerVR": {"AskToTurnOn": 0}, "Player": {"CaptureExternalDMD": 1, "CapturePUP": 1}},
    False: {"PlayerVR": {"AskToTurnOn": 2}},
}

def vr_runtime(folder):
    """What would drive a headset for the VPX in *folder*, as ("<name>", "")
    or ("", why VR cannot start). VPX loads the openvr_api64.dll beside it:
    OpenComposite (a drop-in that turns OpenVR into OpenXR) needs an active
    OpenXR runtime; Valve's loader needs the runtime SteamVR registers."""
    try:
        with open(os.path.join(folder or "", "openvr_api64.dll"), "rb") as f:
            opencomposite = b"OpenComposite" in f.read()
    except OSError:
        opencomposite = False
    if opencomposite:
        xr = openxr_runtime()
        if xr:
            return "%s through OpenComposite" % xr, ""
        return "", "OpenComposite is installed with VPX, but no OpenXR runtime is active."
    if openvr_runtime():
        return "SteamVR", ""
    return "", "No VR runtime found. Install SteamVR, or OpenComposite with an OpenXR runtime."

def openxr_runtime():
    """The active OpenXR runtime's name (its manifest's, else its file's), or
    "" when Windows names none or the manifest is gone."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Khronos\OpenXR\1") as key:
            manifest = winreg.QueryValueEx(key, "ActiveRuntime")[0]
    except (ImportError, OSError):
        return ""
    if not manifest or not os.path.isfile(manifest):
        return ""
    try:
        name = (json.load(open(manifest, encoding="utf-8")).get("runtime") or {}).get("name")
    except (OSError, ValueError, AttributeError):
        name = ""
    return name or "OpenXR (%s)" % os.path.basename(manifest)

def openvr_runtime():
    """The OpenVR runtime folder SteamVR registered (openvrpaths.vrpath, what
    Valve's loader reads), or "" when there is none."""
    path = os.path.join(os.environ.get("LOCALAPPDATA") or "", "openvr", "openvrpaths.vrpath")
    try:
        runtimes = json.load(open(path, encoding="utf-8")).get("runtime") or []
    except (OSError, ValueError, AttributeError):
        return ""
    return next((r for r in runtimes if isinstance(r, str) and os.path.isdir(r)), "")

def vpx_exe_names():
    return [p["name"] for p in VPX_EXES]

def vpx_player(exe):
    """The VPX_EXES entry for *exe* (matched by file name), or None when it
    is not a player the app knows."""
    name = os.path.basename(str(exe or "")).casefold()
    return next((p for p in VPX_EXES if p["name"].casefold() == name), None)

def vpx_exe_for(folder, vr=False):
    """The player in *folder* for desktop play (the first known one there)
    or, with *vr*, for VR (the first VR-capable one), as a path, or ""."""
    for p in VPX_EXES:
        exe = os.path.join(folder or "", p["name"])
        if folder and (p["vr"] or not vr) and os.path.isfile(exe):
            return exe
    return ""

def find_vpx(use_kit=True):
    """The first folder that holds a known VPX player, or ""."""
    kit = padlaunch.kit_load().get("vpx") if use_kit else None
    for d in [kit, VPX_DEFAULT_DIR, os.path.join(os.environ.get("ProgramFiles", ""), "Visual Pinball"),
              os.path.join(os.path.expanduser("~"), "Visual Pinball")]:
        if vpx_exe_for(d):
            return d
    return ""

def vpx_version(exe):
    """The VPX player *exe*'s own file version, as (major, minor, patch), or
    None when it cannot be read (no exe, not Windows)."""
    exe = str(exe or "")
    if not exe or not os.path.isfile(exe) or sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.windll.version
        n = ver.GetFileVersionInfoSizeW(exe, None)
        buf = ctypes.create_string_buffer(n)
        if not n or not ver.GetFileVersionInfoW(exe, 0, n, buf):
            return None
        p, size = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(size)):
            return None
        # VS_FIXEDFILEINFO: signature, struct version, then FileVersionMS/LS
        ms, ls = ctypes.cast(p, ctypes.POINTER(wintypes.DWORD * 4)).contents[2:4]
    except Exception:                                       # noqa: BLE001
        return None
    return (ms >> 16, ms & 0xFFFF, ls >> 16)

def dotted(v):
    return ".".join(str(x) for x in v) if v else ""

def vpx_tables_dir():
    """Where the patched tables live: the folder chosen on the tab (PAD-848,
    David keeps his in a folder on the desktop), else Visual Pinball's own
    tables folder. The "Patched" marks, the Play list and Patch's output all
    use it."""
    own = padlaunch.kit_load().get("tables")
    if own and os.path.isdir(own):
        return own
    vpx = find_vpx()
    return os.path.join(vpx, "tables") if vpx else ""

CARD_RE = r"^([a-z0-9_]+)-\d+_\d+_\d+.*\.sdcard\.raw$"

def cards_in(folder):
    """Group SPIKE 2 card filenames by title."""
    out = {}
    if folder and os.path.isdir(folder):
        for filename in os.listdir(folder):
            match = re.match(CARD_RE, filename, re.I)
            if match:
                out.setdefault(match[1].lower(), []).append(filename)
    return out

def known_tables(tables_dir=None):
    """Each table the kit can patch: the download it fits (the map's
    `table`), the patched name, whether that is in Visual Pinball's tables
    folder, the title Patch takes for it and the card that title boots.
    Maps for one download (JP's Foo Fighters: Pro and LE) are one row:
    `titles` all of them, preferred first, `title` the one padvpx.choose()
    takes, `models` each one's model, `url` the page its author put the
    download on (PAD-961: the map's, else the catalogue's for that title)."""
    tables_dir = vpx_tables_dir() if tables_dir is None else tables_dir
    cat_urls = {t["title"]: t["url"] for t in load_catalog()["tables"] if t.get("title") and t.get("url")}
    rows = {}
    for title, info in padvpx.maps().items():
        if not info.get("listed", True):
            continue
        try:
            m = json.load(open(info["map"], encoding="utf-8"))
        except (OSError, ValueError):
            m = {}
        t = m.get("table") or {}
        out_name = info["output"] or ""
        row = rows.get(out_name or title)
        if row is None:
            row = rows[out_name or title] = {
                "name": t.get("name") or title, "by": t.get("by") or "",
                "where": t.get("where") or "", "url": t.get("url") or "", "output": out_name,
                "patched": bool(out_name and tables_dir
                                and os.path.isfile(os.path.join(tables_dir, out_name))),
                "titles": [], "models": {}, "fits": []}
        row["titles"].append(title)
        row["url"] = row["url"] or t.get("url") or cat_urls.get(title, "")
        row["models"][title] = info["model"]
        row["fits"].append((title, info))
        row.setdefault("marks", []).extend(m.get("repatch") or [])
        if str(info.get("map", "")).endswith(".shadow.json"):
            row["marks"].extend(SHADOW_REPATCH)
    out = []
    for row in rows.values():
        row.setdefault("marks", []).extend(GENERIC_REPATCH)
    for row in rows.values():
        title, _ = padvpx.choose(row.pop("fits"))
        marks = row.pop("marks")
        row.update(title=title, platform=padvpx.platform_of(title),
                   card=padlaunch.card_for(title, padvpx.platform_of(title)) or "",
                   patched_title=patched_title(tables_dir, row["output"]) if row["patched"] else "",
                   repatch=missed_fixes(tables_dir, row["output"], marks) if row["patched"] else [],
                   source=patched_from(tables_dir, row["output"]) if row["patched"] else "")
        out.append(row)
    return out

GAMENAME_RES = (re.compile(r'^\s*Controller\.GameName\s*=\s*"([^"]+)"', re.M),
                re.compile(r'^\s*Const\s+cGameName\s*=\s*"([^"]+)"', re.M | re.I))

def script_title(text):
    for rx in GAMENAME_RES:
        match = rx.search(text)
        if match:
            return match.group(1)
    return ""

def patched_title(tables_dir, out_name):
    """The title a (PAD) table was patched for, from the script every patcher
    writes beside it (`<name>.script.vbs`): an earlier patch may be for another
    model than Patch takes now (PAD-900: Bond's table, patched for the LE
    before the Pro map). "" when the script is not there or names none; a
    name that is none of the row's titles is the table's own, not a model."""
    try:
        text = open(os.path.join(tables_dir, out_name[:-4] + ".script.vbs"),
                    encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    return script_title(text)

GENERIC_REPATCH = [
    {"old": "' PAD: no FlexDMD here",
     "why": "the table's own FlexDMD window opened, and could sit over the machine's screen"},
]

SHADOW_REPATCH = [
    {"absent": "' PAD: the table's own playfield sounds play beside the machine's switches and coils",
     "why": "its targets, lanes, spinners, bumpers and trough make no sound"},
]

def missed_fixes(tables_dir, out_name, marks):
    """PAD-939: the fixes a (PAD) table was patched before. A map's `repatch`
    lists {"old": a line only an earlier patcher wrote, "why": what patching
    again mends} (The Beatles' six-ball trough, PAD-933); the script written
    beside the table is read for them. The `why` of each one found. A mark
    with `absent` instead is a line every newer script has (PAD-1212): it is
    missed when the script lacks it."""
    if not marks:
        return []
    try:
        text = open(os.path.join(tables_dir, out_name[:-4] + ".script.vbs"),
                    encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    squash = lambda t: re.sub(r"\s+", " ", t).lower()      # noqa: E731
    text = squash(text)
    # each once: a table two titles' maps fit (GotG's LE and Pro, PAD-976;
    # Foo Fighters', PAD-968) carries the same mark in both, and the row
    # gathers every map's
    return list(dict.fromkeys(k["why"] for k in marks
                              if (k.get("old") and squash(k["old"]).strip() in text)
                              or (k.get("absent") and squash(k["absent"]).strip() not in text)))

def patched_from(tables_dir, out_name):
    """The download a (PAD) table was patched from (padvpx.remember_patch,
    PAD-939), while it is still there: Patch again runs on it. "" when the
    table was patched before the record or the download moved."""
    try:
        src = json.load(open(os.path.join(tables_dir, out_name[:-4] + ".patch.json"),
                             encoding="utf-8")).get("source") or ""
    except (OSError, ValueError, AttributeError):
        return ""
    return src if os.path.isfile(src) else ""

DROPPED = {"Jurassic Park Limited Edition (PAD).vpx": "JPSalas & marty's Jurassic Park Pro Le 4.02"}

def patched_in(tables_dir):
    """The (PAD) tables in a tables folder: what can be opened."""
    if not tables_dir or not os.path.isdir(tables_dir):
        return []
    return sorted(f for f in os.listdir(tables_dir) if f.lower().endswith(".vpx") and "(PAD)" in f
                  and f not in DROPPED)

def cabinet_state(kit, mons):
    """PAD-1304: the Cabinet row: where the backglass goes (0 = where B2S
    puts it, else a screen), the B2S DMD hidden or not, the DOF events the
    buttons are sent as (0 = not sent; `suggested` the tab offers), the
    screens to pick from and the bulbs chosen per title."""
    c = padcabinet.settings(kit)
    c["suggested"] = dict(padcabinet.SUGGESTED_DOF)
    c["screens"] = [{"n": m["n"], "w": m["w"], "h": m["h"], "x": m["x"], "y": m["y"],
                     "primary": bool(m.get("primary"))} for m in mons]
    return c

def set_cabinet(changes, tables_dir=None, mons=None):
    """Save cabinet settings and put every patched table's .res and B2S DMD
    in line with them (a table with no backglass beside it is left alone)."""
    d = padcabinet.update(padlaunch.kit_load(), **changes)
    padlaunch.kit_save(d)
    mons = padisplay.monitors() if mons is None else mons
    tables_dir = vpx_tables_dir() if tables_dir is None else tables_dir
    said = []
    for name in patched_in(tables_dir):
        out = os.path.join(tables_dir, name)
        if os.path.isfile(os.path.splitext(out)[0] + ".directb2s"):
            said += ["%s: %s" % (name, w) for w in padvpx.cabinet_res(out, kit=d, mons=mons)]
    return {"result": "ok", "cabinet": cabinet_state(d, mons), "said": said}

def table_bulbs(output, title, tables_dir=None):
    """The named bulbs of a patched table's backglass, and the ones chosen
    to follow BACKBOX GI for *title*."""
    tables_dir = vpx_tables_dir() if tables_dir is None else tables_dir
    b2s = os.path.splitext(os.path.join(tables_dir or "", output))[0] + ".directb2s"
    chosen = padcabinet.settings(padlaunch.kit_load())["gi_bulbs"].get(title, [])
    return {"names": padcabinet.bulb_names(b2s) if os.path.isfile(b2s) else [],
            "chosen": chosen, "backglass": os.path.basename(b2s) if os.path.isfile(b2s) else ""}

def set_bulbs(title, names):
    d = padcabinet.set_bulbs(padlaunch.kit_load(), title, names)
    padlaunch.kit_save(d)
    return {"result": "ok", "chosen": padcabinet.settings(d)["gi_bulbs"].get(title, [])}

CATALOG = os.path.join(HERE, "catalog.json")

def load_catalog():
    """The kit's survey of SPIKE 2 Visual Pinball tables (catalog.json, PAD-943): {"platforms": {...}, "tables": [...]},
    or empty when the file is not there."""
    try:
        d = json.load(open(CATALOG, encoding="utf-8"))
    except (OSError, ValueError):
        return {"platforms": {}, "tables": []}
    return {"platforms": d.get("platforms") or {}, "tables": d.get("tables") or []}

def card_space(lib=None, kit=None):
    """PAD-964: what starting each title's game costs the disk, for the tab's
    rows before Play: the card the launch would boot for every Spike 2 title
    in the folder (padlaunch.card_for), asked of cardmount.sh's own room rule
    in one call (Launch.cache_check: a dry run of the copier, nothing copied).
    {"space": {title: {state, words, need_gb, free_gb, label}}, "cache":
    {kind, dir, free_gb, size_gb, limit_gb, used_gb} or None, "card_cache":
    on/off}; "error" when WSL did not answer (the rows then say nothing)."""
    kit = padlaunch.kit_load() if kit is None else kit
    lib = (os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or "") if lib is None else lib
    cards = {}
    for title in sorted(cards_in(lib)):
        card = padlaunch.card_for(title, "spike2")
        if card and card.lower().endswith(".raw"):
            cards[title] = card
    out = {"space": {}, "cache": None, "card_cache": padlaunch.cache_on(kit)}
    if not cards:
        return out
    la = padlaunch.Launch(next(iter(cards)), next(iter(cards.values())))
    why = padlaunch.no_linux(la.distro)
    if why:
        out["error"] = why
        return out
    got = la.cache_check(list(cards.values()))
    if not got:
        out["error"] = "The emulator's Linux did not answer what the cards cost its disk."
        return out
    by_img = {}
    for rec in got["checks"].values():
        by_img[rec["img"]] = rec
    wsl = dict(zip(cards.values(), padlaunch.padpath.to_wsl_many(list(cards.values()), la.distro)))
    for title, card in cards.items():
        rec = by_img.get(wsl[card])
        if not rec:
            continue
        state, words = padlaunch.space_words(rec)
        out["space"][title] = {"state": state, "words": words, "label": rec["label"],
                               "need_gb": round(rec["need_kb"] / 1048576.0, 1),
                               "free_gb": round(rec["free_kb"] / 1048576.0, 1),
                               "evict_n": rec["evict_n"], "host": rec["host"]}
    c = got.get("cache")
    if c:
        out["cache"] = {"kind": c["kind"], "dir": c["dir"], "limit_gb": c["limit_gb"],
                        "free_gb": round(c["avail_kb"] / 1048576.0, 1),
                        "size_gb": round(c["size_kb"] / 1048576.0, 1),
                        "used_gb": round(c["used_kb"] / 1048576.0, 1)}
    return out
