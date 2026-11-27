#!/usr/bin/env python3
"""Inspect, patch and run SPIKE 2 VPX tables.

    padvpx tables
    padvpx patch <table.vpx> [--out <folder>] [--card <image>] [--title <title>]
    padvpx card [<title> <image>]
    padvpx library <folder>
    padvpx cache [on|off|check]
    padvpx lcd <layout>
    padvpx player <layout>
    padvpx run <title> [--hidden] [--mute]
    padvpx stop <title>
    padvpx status

Register the controller from the SPIKE 2 VPX Setup window.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

import padisplay   # noqa: E402  where the game window goes (PAD-811)
import padlaunch   # noqa: E402
import vpxfile     # noqa: E402

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ------------------------------------------------------------ the tables --

def maps():
    """Every map in this folder: {title: {"kind": shadow|mashup, "map": path,
    "detect": [words], "output": name, "model": "Pro"|"LE"|"",
    "preferred": bool}}. Several maps can fit one download (JP's Foo Fighters
    is a Pro's playfield, and has an LE map too): the preferred one first."""
    out = {}
    for f in sorted(os.listdir(HERE)):
        if f.endswith(".shadow.json") or f.endswith(".vpxmap.json"):
            m = json.load(open(os.path.join(HERE, f), encoding="utf-8"))
            if (m.get("platform") or "spike2").lower() != "spike2":
                continue
            title = m.get("title") or f.split(".")[0]
            game = m.get("game")            # same rule as padlaunch.game_for
            out[title] = {"kind": "shadow" if f.endswith(".shadow.json") else "mashup",
                          "game": game if isinstance(game, str) and game else title,
                          "map": os.path.join(HERE, f), "detect": m.get("detect", []),
                          "table": m.get("table") or {},
                          "detect_not": m.get("detect_not", []),
                          "output": m.get("output", ""), "model": m.get("model", ""),
                          "preferred": bool(m.get("preferred")),
                          # a ROM table's map names its own patcher
                          "patcher": m.get("patcher", "patch_godzilla.py"),
                          # one patcher, several maps (TMNT's LE and Pro)
                          "patcher_takes_map": bool(m.get("patcher_takes_map")),
                          # PAD-943: which rig the title runs on (spike2 unless said)
                          "platform": (m.get("platform") or "spike2").lower(),
                          # PAD-848: off the tab's Tables list (TMNT's LE: its card
                          # starts no game in the emulator, PAD-829; the Pro plays)
                          "listed": m.get("listed", True) is not False}
    return dict(sorted(out.items(), key=lambda kv: not kv[1]["preferred"]))


def card_title(card):
    """`foo_fighters_le-1_04_0.Release.16G.sdcard.raw` -> foo_fighters_le."""
    m = re.match(r"^([a-z0-9_]+)-\d+_\d+_\d+", os.path.basename(card or ""), re.I)
    return m.group(1).lower() if m else None


def fitting(table_path, script=None):
    """The titles whose map fits this table, preferred first: every `detect`
    word of the map is in the table's script and none of its `detect_not`
    words is (case does not matter). `detect_not` keeps a map off a later
    mod of its table that has a map of its own (PAD-1491: burger's Munsters
    MOD still names Allknowing2012 and mmunsters, so the 1.05 map would take
    it, and a card for munsters_pro picks that map by name)."""
    if script is None:
        from play_spike2 import embedded_script

        script = embedded_script(table_path)
    script = script.lower()
    out = []
    for title, info in maps().items():
        words = [w.lower() for w in info["detect"]]
        if (words and all(w in script for w in words)
                and not any(w.lower() in script for w in info.get("detect_not", []))):
            out.append((title, info))
    return out


def choose(fits, title=None, card=None):
    """Which of the fitting maps a patch takes: the title asked for, else the
    one the card given is for, else the first with a card known
    (padlaunch.card_for), else the preferred."""
    if not fits:
        return None, None
    by = dict(fits)
    for want in (title, card_title(card)):
        if want in by:
            return want, by[want]
        if want and want != title:
            for t, info in fits:
                if info.get("game") == want:
                    return t, info
    for t, info in fits:
        if padlaunch.card_for(t, info.get("platform") or "spike2"):
            return t, info
    return fits[0]


def recognise(table_path, title=None, card=None):
    """Which title's map this table is patched with (see choose()). None
    when no map fits."""
    return choose(fitting(table_path), title, card)


def patch(table_path, outdir=None, card=None, title=None, log=None, *, configure_cabinet=True):
    fits = fitting(table_path)
    if title and title not in dict(fits):
        print("the map for %s does not fit this table; it fits: %s"
              % (title, ", ".join(t for t, _ in fits) or "none"))
        return 2
    title, info = choose(fits, title, card)
    if not title:
        print("this table is not one the kit knows; it can patch: %s" % ", ".join(
            "%s (%s)" % (t, ", ".join(i["detect"])) for t, i in maps().items()))
        return 2
    others = [t for t, _ in fits if t != title]
    if others:
        print("patching for %s%s; it plays as %s too (padvpx patch --title %s)"
              % (title, " (%s)" % info["model"] if info["model"] else "",
                 " or ".join(others), others[0]))
    outdir = outdir or os.path.dirname(os.path.abspath(table_path))
    py = padlaunch.win_python() or sys.executable
    if info["kind"] == "shadow":
        cmd = [py, os.path.join(HERE, "vpxshadow.py"), info["map"], table_path, outdir]
    else:
        cmd = [py, os.path.join(HERE, info["patcher"]), table_path, outdir]
        if info.get("patcher_takes_map"):
            cmd += ["--map", info["map"]]
    print("recognised %s: %s" % (title, " ".join(info["detect"])))
    if log is None:
        r = subprocess.run(cmd)
    else:
        r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
    if r.returncode == 0 and card:
        padlaunch.remember_card(title, os.path.abspath(card))
        print("card for %s: %s" % (title, os.path.abspath(card)))
    if r.returncode == 0:
        out = os.path.join(outdir, info["output"] or
                           os.path.splitext(os.path.basename(table_path))[0] + " (PAD).vpx")
        b2s = copy_backglass(table_path, out)
        if b2s:
            print("backglass: %s" % b2s)
            if configure_cabinet:
                for line in cabinet_res(out):
                    print(line)
        remember_patch(out, table_path, title)
        print("open \"%s\" in Visual Pinball; the game starts with it when its card is known" % out)
    return r.returncode


def patch_record_path(out_vpx):
    """`<name> (PAD).patch.json` beside the patched table (PAD-939)."""
    return out_vpx[:-4] + ".patch.json"


def remember_patch(out_vpx, table_path, title):
    """PAD-939: which download a (PAD) table was patched from, so the tab's
    Patch again runs on it without asking for it once more. Never in the
    patch's way."""
    try:
        with open(patch_record_path(out_vpx), "w", encoding="utf-8") as f:
            json.dump({"source": os.path.abspath(table_path), "title": title}, f)
    except OSError:
        pass


def cabinet_res(out_vpx, kit=None, mons=None):
    """PAD-1304: the patched table's <name>.res (the backglass on the screen
    the Visual Pinball tab's Cabinet row picked) and its B2S DMD, as the
    kit's cabinet settings say. Words for the log; never in the patch's way."""
    try:
        import padcabinet
        import padisplay
        kit = padlaunch.kit_load() if kit is None else kit
        mons = padisplay.monitors() if mons is None else mons
        return padcabinet.write_res(out_vpx, kit, mons, game_name=padcabinet.rom_name(out_vpx))
    except Exception as exc:                                # noqa: BLE001
        return ["backglass screen not set: %s" % exc]


def copy_backglass(table_path, out_vpx):
    """B2S finds a table's backglass by the .vpx name, so <name> (PAD).vpx
    never finds <name>.directb2s: copy it beside the patched table under the
    matching name. Looks beside the original, then beside the output; a
    backglass already at the target is the user's and is left alone. Returns
    the target, or None when there is no backglass to copy."""
    want = os.path.splitext(os.path.basename(table_path))[0].lower() + ".directb2s"
    dst = os.path.splitext(out_vpx)[0] + ".directb2s"
    if os.path.exists(dst):
        return dst
    here = os.path.dirname(os.path.abspath(table_path))
    for d in (here, os.path.dirname(os.path.abspath(out_vpx))):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.lower() == want:   # B2S files ship as .directb2s and .directb2S
                shutil.copy2(os.path.join(d, n), dst)
                return dst
    # a download whose one backglass has a name of its own, in its b2s folder
    # (PAD-926: The Beatles' b2s\The-Beatles-Original-2018) or beside the table
    # when the table is the folder's only one (a tables folder of several
    # would hand one table's backglass to another)
    found = []
    try:
        tables = [n for n in os.listdir(here)
                  if n.lower().endswith(".vpx") and not n.lower().endswith(" (pad).vpx")]
    except OSError:
        tables = []
    for d in ([here] if len(tables) == 1 else []) + [os.path.join(here, "b2s")]:
        try:
            found += [os.path.join(d, n) for n in os.listdir(d)
                      if n.lower().endswith(".directb2s") and not n.lower().endswith(" (pad).directb2s")]
        except OSError:
            continue
    if len(found) == 1:
        shutil.copy2(found[0], dst)
        return dst
    return None


def vpx_ini_path():
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "VPinballX", "VPinballX.ini")


def vpx_ini_get(keys, section="Player", path=None):
    """The values of `keys` in a section of Visual Pinball's ini, as written
    there ("" for a key that has no line)."""
    path = path or vpx_ini_path()
    got = {k: "" for k in keys}
    try:
        with open(path, encoding="utf-8-sig", errors="surrogateescape") as file:
            lines = file.read().split("\n")
    except OSError:
        return got
    in_sect = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            in_sect = s[1:-1].lower() == section.lower()
        elif in_sect and "=" in s:
            k, v = (part.strip() for part in s.split("=", 1))
            for want in keys:
                if k.lower() == want.lower():
                    got[want] = v
    return got


def vpx_ini_set(keys, section="Player", path=None):
    """Set `keys` in a section of Visual Pinball's ini (`Key = Value` lines
    under `[Section]`), keeping everything else as it is."""
    path = path or vpx_ini_path()
    try:
        with open(path, encoding="utf-8-sig", errors="surrogateescape") as file:
            lines = file.read().split("\n")
    except OSError:
        lines = []
    out, in_sect, seen, done = [], False, set(), False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_sect and not done:
                for k, v in keys.items():
                    if k not in seen:
                        out.append("%s = %s" % (k, v))
                done = True
            in_sect = s[1:-1].lower() == section.lower()
            out.append(ln)
            continue
        if in_sect and "=" in s:
            k = s.split("=", 1)[0].strip()
            for want in keys:
                if k.lower() == want.lower():
                    ln = "%s = %s" % (want, keys[want])
                    seen.add(want)
        out.append(ln)
    if not any(ln.strip().lower() == "[%s]" % section.lower() for ln in out):
        out += ["[%s]" % section]
        in_sect = True
    if in_sect and not done:
        for k, v in keys.items():
            if k not in seen:
                out.append("%s = %s" % (k, v))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as file:
        file.write("\n".join(out))
    return path


# ------------------------------------------------------------- the runs ---

def platform_of(title):
    """What a title's map says it runs on: "spike2" unless it says (PAD-943)."""
    return (maps().get(title) or {}).get("platform") or "spike2"


def run(title, hidden=False, mute=False):
    platform = platform_of(title)
    card = padlaunch.card_for(title, platform)
    if not card:
        print("no card for %s (looked in %s)" % (title, padlaunch.card_places(title, platform)))
        return 2
    launch = padlaunch.Launch(title, card)
    slot = launch.take_slot()
    env = launch.env()
    if hidden:
        env = [e for e in env if not e.startswith("PAD_HIDDEN=")] + ["PAD_HIDDEN=1"]
    if mute or hidden:
        env = [e for e in env if not e.startswith("PAD_AUDIO=")] + ["PAD_AUDIO=0"]
    head, launch.as_root = launch.head()
    cmd = head + env + ["bash", "%s/watch.sh" % launch.rig_wsl, str(launch.minutes)]
    out = open(launch.logfile, "ab")
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                     creationflags=_CREATE_NO_WINDOW)
    print("started %s on rig slot %d from %s (log %s)" % (title, slot, card, launch.logfile))
    return 0


def stop(title):
    from padcontroller import Rig
    title = padlaunch.game_for(title)
    rec = Rig.board_run(title)
    if not rec:
        print("no run of %s on the board" % title)
        return 1
    if rec.get("label") != padlaunch.LABEL:
        print("the run of %s on slot %s is %s's, not the kit's; leaving it"
              % (title, rec.get("slot"), rec.get("label") or "somebody"))
        return 1
    launch = padlaunch.Launch(title, "", dist=rec.get("distro"))
    slot = launch.slot = int(rec.get("slot"))
    launch.stop()
    print("stopped %s on slot %d" % (title, slot))
    return 0


def status():
    kit = padlaunch.kit_load()
    print("kit file: %s" % padlaunch.KIT)
    print("distro: %s" % (padlaunch.distro() or "the default"))
    print("rig: %s" % padlaunch.rig_dir())
    print("library: %s" % (os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or "(none)"))
    cards = kit.get("cards") or {}
    for t in sorted(set(maps()) | set(cards)):
        c = padlaunch.card_for(t, platform_of(t))
        print("  %-18s %s" % (t, c or "no card"))
    from padcontroller import Rig, BOARD
    try:
        names = sorted(n for n in os.listdir(BOARD) if n.endswith(".run"))
    except OSError:
        names = []
    for n in names:
        try:
            rec = json.load(open(os.path.join(BOARD, n), encoding="utf-8"))
            print("run: slot %s %s (%s)" % (rec.get("slot"), rec.get("game"), rec.get("label")))
        except (OSError, ValueError):
            pass
    try:
        import winreg
        from controller_id import PROGID
        k = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, PROGID + "\\CLSID")
        print("controller: registered (%s)" % winreg.QueryValue(k, None))
    except Exception:                                       # noqa: BLE001
        print("controller: open the SPIKE 2 VPX Setup window to register it")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "patch":
        outdir = card = title = None
        args = []
        i = 0
        while i < len(rest):
            if rest[i] == "--out" and i + 1 < len(rest):
                outdir = rest[i + 1]
                i += 2
            elif rest[i] == "--card" and i + 1 < len(rest):
                card = rest[i + 1]
                i += 2
            elif rest[i] == "--title" and i + 1 < len(rest):
                title = rest[i + 1]
                i += 2
            else:
                args.append(rest[i])
                i += 1
        if len(args) != 1:
            print(__doc__)
            return 2
        return patch(args[0], outdir, card, title)
    if cmd == "card":
        if len(rest) == 2:
            padlaunch.remember_card(rest[0], os.path.abspath(rest[1]))
            print("card for %s: %s" % (rest[0], os.path.abspath(rest[1])))
            return 0
        for t, c in sorted((padlaunch.kit_load().get("cards") or {}).items()):
            print("%-18s %s" % (t, c))
        return 0
    if cmd == "player":
        # Visual Pinball's own playfield window: borderless in windowed
        # mode, so it cannot be dragged, and 10.8 ignores WindowPosX/Y in
        # its ini - the controller moves it once when a table starts
        # (PAD-811, PAD-845: borderless, dragged to move, 16 px from an edge
        # to resize, double-click to fill the screen, in the table's
        # proportions, and remembered where it is left; `player frame on`
        # gives it a title bar instead)
        d = padlaunch.kit_load()
        if len(rest) == 2 and rest[0] == "frame" and rest[1] in ("on", "off"):
            d["player_frame"] = rest[1] == "on"
        elif len(rest) in (2, 3, 4) and all(v.lstrip("-").isdigit() for v in rest):
            vals = [int(v) for v in rest]
            d["player"] = {"x": vals[0], "y": vals[1]}
            if len(vals) >= 3:
                d["player"]["w"] = vals[2]          # the height follows the table's proportions
        elif rest and rest[0] == "monitor" and len(rest) == 2:
            d["player"] = {"monitor": int(rest[1])}
        elif rest and rest[0] == "off":
            d.pop("player", None)
        else:
            print(json.dumps(d.get("player", {}), indent=1) or "off")
            return 0
        padlaunch.kit_save(d)
        print("player window: %s, frame %s (applied when a table is next opened; a width scales"
              " the picture, its height follows the table's proportions)"
              % (json.dumps(d.get("player", "off")), "on" if d.get("player_frame") else "off"))
        return 0
    if cmd == "cache":
        # PAD-964: `padvpx cache` says whether a game copies its card into
        # the emulator's cache first and what each title's card costs the
        # disk; `cache on|off` sets the first
        import vpxsetup
        if rest and rest[0] in ("on", "off"):
            padlaunch.set_cache_on(rest[0] == "on")
        elif rest:
            print("usage: padvpx cache [on|off]")
            return 2
        got = vpxsetup.card_space()
        print("caching: %s" % ("on" if got["card_cache"] else "off (the game reads the image where it lies)"))
        c = got.get("cache")
        if c:
            print("cache: %s, %s GB free of %s GB (%s)" % (c["dir"], c["free_gb"], c["size_gb"],
                                                        "the shared card store" if c["kind"] == "store"
                                                        else "the emulator's own disk"))
        if got.get("error"):
            print(got["error"])
        for t, s in sorted(got["space"].items()):
            print("%-20s %-8s %s" % (t, s["state"], s["words"]))
        return 0
    if cmd == "display":
        # the game window for every run, desktop and Visual Pinball alike
        # (PAD-811): padisplay.py's commands, applied live by the renderer
        return padisplay.main(rest)
    if cmd == "lcd":
        # where the game's LCD window goes: `padvpx lcd top` (on top, upper
        # middle of the main screen), `padvpx lcd monitor 2` (fills that
        # screen), `padvpx lcd 100 0 960 540`, `padvpx lcd off`. Since PAD-811
        # these are the display setting (padvpx display), borderless, which
        # the renderer applies live; the kit keeps only "on top".
        d = padlaunch.kit_load()
        mons = padisplay.monitors()
        if rest and rest[0] == "monitor" and len(rest) == 2:
            s = {"mode": "fullscreen", "monitor": int(rest[1]), "border": False}
        elif len(rest) == 4:
            x, y, w, h = (int(v) for v in rest)
            mon = next((m for m in mons if m["x"] <= x < m["x"] + m["w"]
                        and m["y"] <= y < m["y"] + m["h"]), mons[0])
            s = {"mode": "window", "monitor": mon["n"], "border": False,
                 "rx": x - mon["x"], "ry": y - mon["y"], "w": w, "h": h}
        elif rest and rest[0] == "top":
            from padcontroller import lcd_rect
            x, y, w, h = lcd_rect({}, [(m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"]) for m in mons])
            s = {"mode": "window", "monitor": 1, "border": False,
                 "rx": x - mons[0]["x"], "ry": y - mons[0]["y"], "w": w, "h": h}
        elif rest and rest[0] == "off":
            s = {"mode": "free"}
        else:
            print("game window: %s" % padisplay.describe(padisplay.load(), mons))
            return 0
        padisplay.save(s)
        d["lcd"] = {"topmost": s["mode"] != "free"}
        d["layout"] = ""                    # none of the tab's layouts now (PAD-1231)
        padlaunch.kit_save(d)
        print("game window: %s" % padisplay.describe(s, mons))
        return 0
    if cmd == "library" and len(rest) == 1:
        d = padlaunch.kit_load()
        d["library"] = os.path.abspath(rest[0])
        padlaunch.kit_save(d)
        print("library: %s" % d["library"])
        return 0
    if cmd == "run" and rest:
        return run(rest[0], hidden="--hidden" in rest, mute="--mute" in rest)
    if cmd == "stop" and rest:
        return stop(rest[0])
    if cmd == "status":
        return status()
    if cmd == "tables":
        for t, i in maps().items():
            print("%-18s %-7s %-40s %s" % (t, i["kind"], i["output"], ", ".join(i["detect"])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
