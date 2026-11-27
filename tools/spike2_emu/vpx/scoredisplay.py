"""Hide a table's own flasher score display, which the Stern LCD replaces.

Some tables draw their rules' text (player, ball, score) on a grid of flasher
tiles: the script's `Digits = Array(...)` and `digitgrid`. With the Stern game
running, nothing meaningful is written there, so it shows stale text beside
the playfield, on the desktop and in VR. Its flashers get opacity 0, which VPX
doesn't draw; the script only ever sets their image and visibility.

GameItems are not in the table's MAC, so the streams are replaced in place,
as padmigrate does for the controller name.
"""

import os
import re
import struct

import vpxfile


def tiles(script):
    """Lower-case names of the flashers in *script*'s score display: its
    `Digits = Array(...)` (comment lines don't count) and `digitgrid`."""
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("'"))
    found = re.search(r"^\s*Digits\s*=\s*Array\(([^)]*)\)", code, re.I | re.M)
    if not found:
        return set()
    names = {n.strip().lower() for n in found.group(1).replace("_", " ").split(",") if n.strip()}
    return names | {"digitgrid"}


def faded(data):
    """*data* (a Flasher GameItem) with opacity 0, else None if it already is."""
    for tag, payload, _ in vpxfile.item_records(data):
        if tag == "FALP":
            if struct.unpack_from("<i", payload)[0] == 0:
                return None
            return vpxfile.set_fields(data, {"FALP": struct.pack("<i", 0)})
    return None


def hide_in_place(path, script):
    """Hide the score display of the table at *path*, whose script is
    *script*, where it is. Returns report lines, [] when there was nothing to
    do. Raises OSError when it can't be written."""
    names = tiles(script)
    if not names:
        return []
    table = vpxfile.VpxTable(path)
    try:
        streams = {}
        for i, data in enumerate(table.items):
            kind, name, _ = table.item_info(data)
            if kind == "Flasher" and name.lower() in names:
                done = faded(data)
                if done:
                    streams["GameItem%d" % i] = done
    finally:
        table.ole.close()
    if not streams:
        return []
    tmp = path + ".score-display.tmp"
    vpxfile.write_patched(path, tmp, streams=streams)
    check = vpxfile.VpxTable(tmp)
    ok = check.verify()
    check.ole.close()
    if not ok:
        os.remove(tmp)
        raise OSError("%s does not verify with its score display hidden; it was left as it was."
                      % os.path.basename(path))
    os.replace(tmp, path)
    return ["the table's own score display (%d flashers) hidden: the Stern LCD replaces it" % len(streams)]
