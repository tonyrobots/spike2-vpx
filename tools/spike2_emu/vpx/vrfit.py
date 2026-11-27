"""Fit a table's VR backbox DMD to the LCD's 16:9 (docs/vr-plan.md, Phase 4).

The VR backbox DMD is a Flasher with IDMD set. VPX maps the DMD picture over
its drag points' bounding box (top at the smallest y), then rotates it by
RotX about the box's centre and places it at that centre and the flasher's
Height (flasher.cpp).

Each DMD flasher is made 16:9 and opaque. By default it keeps its width and
bottom edge and grows upwards; a map's `vr_backbox` places it instead:
    "vr_backbox": {"<flasher name>": {"width": w, "x": x, "bottom": z}}
in table units: picture width (height = width * 9/16), centre x, and bottom
edge height above the playfield. Each is optional. Moves stay in the plane
the flasher stands in. The values are absolute, so a fitted table is left
alone.

A table with no DMD flasher (no VR room) gets one, ADDED_NAME: a large LCD
where a backbox would stand, saved hidden and shown by a line added to the
script when RenderingMode is 2 (VR), so desktop play never sees it. The map
places it like any other.

GameItems are not in the table's MAC, so the streams are replaced in place;
the script is, so adding the line re-signs the table.
"""

import math
import os
import struct

import vpxfile

ASPECT = 16 / 9
#: Within this of 16:9 a flasher's shape is left as it is.
TOLERANCE = 0.01
#: Table units within which a placed flasher is where its map says.
NEAR = 0.05

#: The LCD added to a table without a DMD flasher, and where it stands by
#: default: a share of the table's width, centred, its bottom edge this high
#: and this far in front of the table's top edge, tilted back as a backbox is.
ADDED_NAME = "PadVrLcd"
ADDED = {"share": 0.85, "bottom": 470.0, "depth": 40.0, "rot_x": -84.0}
SHOW_IN_VR = "If RenderingMode = 2 Then %s.Visible = True" % ADDED_NAME


def _floats(fields, *tags):
    return [struct.unpack_from("<f", fields[t], 0)[0] if t in fields else 0.0 for t in tags]


def dmd_flasher(data):
    """(name, top-level fields, drag points) of a DMD flasher GameItem, else None."""
    if vpxfile.ITEM_TYPES.get(struct.unpack_from("<i", data, 0)[0]) != "Flasher":
        return None
    fields, points, depth = {}, [], 0
    for tag, payload, _ in vpxfile.item_records(data):
        if tag == "DPNT":
            depth += 1
        elif tag == "ENDB" and depth:
            depth -= 1
        elif depth and tag == "VCEN":
            points.append(struct.unpack_from("<ff", payload, 0))
        elif not depth:
            fields.setdefault(tag, payload)
    if not (fields.get("IDMD") and struct.unpack_from("<i", fields["IDMD"], 0)[0]):
        return None
    return vpxfile.unwide(fields.get("NAME", b"")).replace("\x00", ""), fields, points


def placement(points, rot_x, height):
    """{width, x, bottom} of a flasher as it stands in the room, and the depth
    (world y) of its bottom edge.

    VPX moves a vertex v to centre + R(v - centre), z += height, where R is
    RotateX with VPX's row vectors: y' = y cos a, z' = y sin a. The bottom
    edge (largest y) is centre + (0, h/2)."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    h = max(ys) - min(ys)
    a = math.radians(rot_x)
    cy = (min(ys) + max(ys)) / 2
    return ({"width": max(xs) - min(xs), "x": (min(xs) + max(xs)) / 2,
             "bottom": height + math.sin(a) * h / 2},
            cy + math.cos(a) * h / 2)


def reshaped(points, rot_x, height, want=None, aspect=ASPECT):
    """(new points, new height) for a flasher whose drag points are *points*,
    stood up by *rot_x* degrees at *height*: *aspect* wide, placed as *want*
    says ({width, x, bottom}, each optional; else as it is now), in the plane
    it stands in now."""
    now, depth = placement(points, rot_x, height)
    place = dict(now, **(want or {}))
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    new_w = float(place["width"])
    new_h = new_w / aspect
    a = math.radians(rot_x)
    # up the plane is (0, -cos a, -sin a): a bottom dz higher is cos a / sin a * dz nearer in y
    if math.sin(a):
        depth += math.cos(a) / math.sin(a) * (place["bottom"] - now["bottom"])
    cy = depth - math.cos(a) * new_h / 2
    left, top = place["x"] - new_w / 2, cy - new_h / 2
    return ([(left + (x - min(xs)) * new_w / w, top + (y - min(ys)) * new_h / h) for x, y in points],
            place["bottom"] - math.sin(a) * new_h / 2)


def fit(data, want=None):
    """(new GameItem stream, report line) for a DMD flasher that isn't 16:9,
    isn't where *want* ({width, x, bottom}) puts it, or isn't opaque; else
    None. Raises ValueError for one this can't reshape (turned about Y or Z).
    Opaque: VPX blends a DMD flasher when ModulateVsAdd (MOVA) is under 1."""
    found = dmd_flasher(data)
    if not found:
        return None
    name, fields, points = found
    if len(points) < 3:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if not w or not h:
        return None
    rot_x, rot_y, rot_z = _floats(fields, "FROX", "FROY", "FROZ")
    height, = _floats(fields, "FHEI")
    now, _ = placement(points, rot_x, height)
    moved = any(abs(float(v) - now[k]) > NEAR for k, v in (want or {}).items())
    reshape = moved or abs(w / h / ASPECT - 1) > TOLERANCE
    blended = "MOVA" in fields and struct.unpack_from("<f", fields["MOVA"], 0)[0] < 1
    if not reshape and not blended:
        return None
    item, changes, todo = data, [], {}
    if reshape:
        if rot_y or rot_z:
            raise ValueError("its backbox DMD %s is turned about Y or Z" % name)
        new_points, new_height = reshaped(points, rot_x, height, want)
        item = vpxfile.reshape_item(item, new_points)
        nx, ny = [p[0] for p in new_points], [p[1] for p in new_points]
        todo.update({"FHEI": struct.pack("<f", new_height),
                     "FLAX": struct.pack("<f", (min(nx) + max(nx)) / 2),
                     "FLAY": struct.pack("<f", (min(ny) + max(ny)) / 2)})
        if want:
            changes.append("placed as its map says (%s)"
                           % ", ".join("%s %g" % kv for kv in sorted(want.items())))
        else:
            changes.append("reshaped from %.2f:1 to 16:9, growing upwards" % (w / h))
    if blended:
        todo["MOVA"] = struct.pack("<f", 1.0)
        changes.append("made opaque")
    item = vpxfile.set_fields(item, todo)
    return item, "VR backbox: %s %s" % (name, " and ".join(changes))


def added_flasher(left, right, top):
    """The GameItem stream of ADDED_NAME for a table spanning *left*..*right*
    with its top edge at *top*: a hidden, opaque 16:9 DMD flasher, its records
    as VPX writes a flasher (Flasher::SaveData, SavePointData)."""
    rec = vpxfile.biff_record
    i32 = lambda v: struct.pack("<i", v)
    f32 = lambda v: struct.pack("<f", v)
    text = lambda s: i32(len(s)) + s.encode("latin1")
    layer = rec("LOCK", i32(0)) + rec("LAYR", i32(0)) + rec("LANR", text("")) + rec("LVIS", i32(1))
    w = (right - left) * ADDED["share"]
    h = w / ASPECT
    a = math.radians(ADDED["rot_x"])
    cx = (left + right) / 2
    cy = top + ADDED["depth"] - math.cos(a) * h / 2         # the bottom edge at that depth
    height = ADDED["bottom"] - math.sin(a) * h / 2
    corners = [(cx - w / 2, cy - h / 2), (cx - w / 2, cy + h / 2),
               (cx + w / 2, cy + h / 2), (cx + w / 2, cy - h / 2)]
    out = i32(20)                                            # Flasher
    out += rec("FHEI", f32(height)) + rec("FLAX", f32(cx)) + rec("FLAY", f32(cy)) \
        + rec("FROX", f32(ADDED["rot_x"])) + rec("FROY", f32(0)) + rec("FROZ", f32(0)) \
        + rec("COLR", i32(0xFFFFFF)) + rec("TMON", i32(0)) + rec("TMIN", i32(100)) \
        + rec("NAME", vpxfile.wide(ADDED_NAME)) + rec("IMAG", text("")) + rec("IMAB", text("")) \
        + rec("FALP", i32(100)) + rec("MOVA", f32(1.0)) + rec("FVIS", i32(0)) + rec("DSPT", i32(0)) \
        + rec("ADDB", i32(0)) + rec("IDMD", i32(1)) + rec("FLDB", f32(0)) + rec("ALGN", i32(1)) \
        + rec("FILT", i32(0)) + rec("FIAM", i32(100)) + rec("LMAP", text("")) + layer
    for x, y in corners:
        out += rec("DPNT", b"") + rec("VCEN", struct.pack("<ff", x, y)) + rec("POSZ", f32(0)) \
            + rec("SMTH", i32(0)) + rec("SLNG", i32(0)) + rec("ATEX", i32(1)) + rec("TEXC", f32(0)) \
            + layer + rec("ENDB", b"")
    return out + rec("ENDB", b"")


def with_show_in_vr(script):
    """*script* with SHOW_IN_VR as its last line, in its own line endings."""
    nl = "\r\n" if "\r\n" in script else "\n"
    return script.rstrip("\r\n") + nl + nl + "' SPIKE 2 VPX: the LCD in VR (vrfit.py)" + nl + SHOW_IN_VR + nl


def placements(mapping):
    """A map's `vr_backbox`: {flasher name, lower case: {width, x, bottom}}."""
    out = {}
    for name, want in (mapping or {}).get("vr_backbox", {}).items():
        if name == "_":
            continue
        bad = set(want) - {"width", "x", "bottom"}
        if bad or not all(isinstance(v, (int, float)) for v in want.values()) \
                or want.get("width", 1) <= 0:
            raise ValueError("vr_backbox %s takes numbers: width (over 0), x, bottom" % name)
        out[name.lower()] = {k: float(v) for k, v in want.items()}
    return out


def backbox_in_place(path, mapping=None):
    """Fit every DMD flasher of the table at *path* where it is, placed as
    *mapping*'s `vr_backbox` says, adding one to a table that has none.
    Returns report lines, [] when there was nothing to do. Raises ValueError
    for a map naming a flasher the table hasn't, and OSError when it can't be
    written."""
    wants = placements(mapping)
    table = vpxfile.VpxTable(path)
    try:
        streams, rep, names, new_items, script = {}, [], set(), [], None
        for i, data in enumerate(table.items):
            found = dmd_flasher(data)
            if not found:
                continue
            names.add(found[0].lower())
            try:
                done = fit(data, wants.get(found[0].lower()))
            except ValueError as exc:
                rep.append("VR backbox: left as it is, %s" % exc)
                continue
            if done:
                streams["GameItem%d" % i], line = done
                rep.append(line)
        if not names:
            edge = lambda tag, default: (struct.unpack("<f", table.gamedata_field(tag))[0]
                                         if table.gamedata_field(tag) else default)
            item = added_flasher(edge("LEFT", 0.0), edge("RGHT", 952.0), edge("TOPX", 0.0))
            done = fit(item, wants.get(ADDED_NAME.lower()))
            new_items.append(done[0] if done else item)
            names.add(ADDED_NAME.lower())
            script = with_show_in_vr(table.script())
            rep.append("VR backbox: the table has no DMD there, so a large LCD (%s) was added, "
                       "shown in VR only" % ADDED_NAME)
    finally:
        table.ole.close()
    missing = set(wants) - names
    if missing:
        raise ValueError("vr_backbox names %s, which isn't a DMD in this table's backbox"
                         % ", ".join(sorted(missing)))
    if not streams and not new_items:
        return rep
    tmp = path + ".vr-backbox.tmp"
    vpxfile.write_patched(path, tmp, new_items=new_items, script=script, streams=streams)
    check = vpxfile.VpxTable(tmp)
    ok = check.verify()
    check.ole.close()
    if not ok:
        os.remove(tmp)
        raise OSError("%s does not verify with its backbox DMD reshaped; it was left as it was."
                      % os.path.basename(path))
    os.replace(tmp, path)
    return rep
