"""The VR backbox DMD fitted to the LCD's 16:9 (vrfit)."""

import json
import math
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "tools" / "spike2_emu" / "vpx"
sys.path.insert(0, str(MAPS))
import vpxfile  # noqa: E402
import vrfit  # noqa: E402

#: a wide DMD flasher, about 3.9:1, with a slightly uneven bottom edge
WIDE = [(170.5, -44.6), (170.5, 103.7), (755.5, 104.6), (755.5, -44.6)]
ROT, HEIGHT = -84.0, 561.0


def flasher(points, rot_x=ROT, height=HEIGHT, dmd=1, rot_y=0.0, mova=1.0):
    rec = vpxfile.biff_record
    out = struct.pack("<i", 20) + rec("MOVA", struct.pack("<f", mova))
    out += rec("FHEI", struct.pack("<f", height)) + rec("FLAX", struct.pack("<f", 488.0)) \
        + rec("FLAY", struct.pack("<f", 38.2)) + rec("FROX", struct.pack("<f", rot_x)) \
        + rec("FROY", struct.pack("<f", rot_y)) + rec("FROZ", struct.pack("<f", 0.0)) \
        + rec("IDMD", struct.pack("<i", dmd)) + rec("NAME", vpxfile.wide("DMD"))
    for x, y in points:
        out += rec("DPNT", b"") + rec("VCEN", struct.pack("<ff", x, y)) + rec("ENDB", b"")
    return out + rec("ENDB", b"")


def world(points, rot_x, height):
    """Where VPX draws each drag point: rotated about the box centre."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    cy = (min(ys) + max(ys)) / 2
    a = math.radians(rot_x)
    return [(x, cy + (y - cy) * math.cos(a), height + (y - cy) * math.sin(a)) for x, y in points]


def off_plane(point, points, rot_x, height):
    """How far *point* is from the plane a flasher with *points* stands in."""
    a = math.radians(rot_x)
    _, y0, z0 = world(points, rot_x, height)[0]
    return (point[1] - y0) * -math.sin(a) + (point[2] - z0) * math.cos(a)


def box_bottom(points, rot_x, height):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    corners = [(min(xs), max(ys)), (max(xs), max(ys))]
    return world(points + corners, rot_x, height)[-2:]


def placed(item):
    _, fields, points = vrfit.dmd_flasher(item)
    return points, struct.unpack("<f", fields["FHEI"])[0]


class FitTest(unittest.TestCase):
    def assert_in_plane(self, points, height):
        for corner in world(points, ROT, height):
            self.assertAlmostEqual(off_plane(corner, WIDE, ROT, HEIGHT), 0, places=3)

    def test_by_default_it_keeps_its_width_and_bottom_edge_and_grows_upwards(self):
        new, height = vrfit.reshaped(WIDE, ROT, HEIGHT)
        xs, ys = [p[0] for p in new], [p[1] for p in new]
        self.assertAlmostEqual((max(xs) - min(xs)) / (max(ys) - min(ys)), 16 / 9, places=6)
        self.assertEqual(xs, [p[0] for p in WIDE])
        for b, a in zip(box_bottom(WIDE, ROT, HEIGHT), box_bottom(new, ROT, height)):
            for u, v in zip(b, a):
                self.assertAlmostEqual(u, v, places=3)
        top = lambda pts, h: max(v[2] for v in world(pts, ROT, h))
        self.assertGreater(top(new, height), top(WIDE, HEIGHT) + 150)
        self.assert_in_plane(new, height)

    def test_the_item_gets_the_new_points_and_height_once(self):
        item, line = vrfit.fit(flasher(WIDE))
        points, height = placed(item)
        new, want_height = vrfit.reshaped(WIDE, ROT, HEIGHT)
        for p, q in zip(points, new):
            self.assertAlmostEqual(p[0], q[0], places=3)
            self.assertAlmostEqual(p[1], q[1], places=3)
        self.assertAlmostEqual(height, want_height, places=3)
        self.assertIn("3.9", line)
        self.assertIsNone(vrfit.fit(item))

    def test_leaves_alone_what_it_should(self):
        self.assertIsNone(vrfit.fit(flasher([(0, 0), (0, 90), (160.5, 90), (160.5, 0)])))   # 16:9 within 1%
        self.assertIsNone(vrfit.fit(flasher(WIDE, dmd=0)))
        with self.assertRaisesRegex(ValueError, "turned about Y or Z"):
            vrfit.fit(flasher(WIDE, rot_y=10.0))

    def test_a_blended_dmd_is_made_opaque(self):
        item, line = vrfit.fit(flasher(WIDE, mova=0.9))
        self.assertEqual(struct.unpack("<f", vrfit.dmd_flasher(item)[1]["MOVA"])[0], 1.0)
        self.assertIn("reshaped", line)
        self.assertIn("opaque", line)
        self.assertIsNone(vrfit.fit(item))
        square = [(0, 0), (0, 90), (160, 90), (160, 0)]
        item, line = vrfit.fit(flasher(square, mova=0.9))
        self.assertEqual(line, "VR backbox: DMD made opaque")
        self.assertEqual(vrfit.dmd_flasher(item)[2], square)

    def test_a_map_places_it_in_its_plane_and_again_changes_nothing(self):
        for want in ({"width": 570.0, "x": 460.0, "bottom": 490.0},
                     {"width": 620.0, "x": 438.0, "bottom": 450.0}):
            with self.subTest(want=want):
                item, line = vrfit.fit(flasher(WIDE, mova=0.9), want)
                self.assertIn("placed as its map says", line)
                points, height = placed(item)
                now, _ = vrfit.placement(points, ROT, height)
                for k, v in want.items():
                    self.assertAlmostEqual(now[k], v, places=2)
                xs, ys = [p[0] for p in points], [p[1] for p in points]
                self.assertAlmostEqual((max(xs) - min(xs)) / (max(ys) - min(ys)), 16 / 9, places=4)
                self.assert_in_plane(points, height)
                self.assertIsNone(vrfit.fit(item, want))
                # From a flasher already given the default fit: the same place.
                again, _ = vrfit.fit(vrfit.fit(flasher(WIDE))[0], want)
                for p, q in zip(placed(again)[0], points):
                    self.assertAlmostEqual(p[0], q[0], places=2)
                    self.assertAlmostEqual(p[1], q[1], places=2)

    def test_a_taller_one_gets_shorter_from_the_top(self):
        tall = [(163.3, -141.7), (163.3, 222.7), (788.3, 222.7), (788.3, -141.7)]
        new, _ = vrfit.reshaped(tall, -83.0, 655.0)
        ys = [p[1] for p in new]
        self.assertAlmostEqual(625 / (max(ys) - min(ys)), 16 / 9, places=6)


class AddedLcdTest(unittest.TestCase):
    def test_a_table_without_a_dmd_gets_a_large_hidden_one_where_a_backbox_stands(self):
        item = vrfit.added_flasher(0.0, 952.0, 0.0)
        name, fields, points = vrfit.dmd_flasher(item)
        self.assertEqual(name, vrfit.ADDED_NAME)
        self.assertEqual(struct.unpack("<i", fields["FVIS"])[0], 0)          # the script shows it in VR
        self.assertEqual(struct.unpack("<f", fields["MOVA"])[0], 1.0)
        height = struct.unpack("<f", fields["FHEI"])[0]
        now, depth = vrfit.placement(points, vrfit.ADDED["rot_x"], height)
        self.assertAlmostEqual(now["width"], 952 * vrfit.ADDED["share"], places=3)
        self.assertAlmostEqual(now["x"], 476.0, places=3)
        self.assertAlmostEqual(now["bottom"], vrfit.ADDED["bottom"], places=3)
        self.assertAlmostEqual(depth, vrfit.ADDED["depth"], places=3)
        self.assertIsNone(vrfit.fit(item))                                   # 16:9 and opaque already
        # Every record is one VPX writes for a flasher, and the item ends where it should.
        records = list(vpxfile.item_records(item))
        self.assertEqual(records[-1][0], "ENDB")
        self.assertEqual(records[-1][2] + 8, len(item))

    def test_the_map_places_it_like_any_other(self):
        item, _ = vrfit.fit(vrfit.added_flasher(0.0, 952.0, 0.0), {"width": 700.0, "bottom": 500.0})
        name, fields, points = vrfit.dmd_flasher(item)
        now, _ = vrfit.placement(points, vrfit.ADDED["rot_x"], struct.unpack("<f", fields["FHEI"])[0])
        self.assertAlmostEqual(now["width"], 700.0, places=2)
        self.assertAlmostEqual(now["bottom"], 500.0, places=2)
        self.assertEqual(struct.unpack("<i", fields["FVIS"])[0], 0)

    def test_the_script_shows_it_in_vr_only(self):
        for script, nl in (("Option Explicit\r\nSub A\r\nEnd Sub\r\n", "\r\n"), ("Option Explicit\nEnd Sub", "\n")):
            with self.subTest(nl=nl):
                out = vrfit.with_show_in_vr(script)
                self.assertTrue(out.endswith(nl + vrfit.SHOW_IN_VR + nl))
                self.assertIn("RenderingMode = 2", out)
                self.assertEqual("\n" in out.replace("\r\n", ""), nl == "\n")


class MapTest(unittest.TestCase):
    def test_values_are_checked(self):
        self.assertEqual(vrfit.placements({"vr_backbox": {"_": ["why"], "DMD": {"width": 570}}}),
                         {"dmd": {"width": 570.0}})
        for bad in ({"wide": 570}, {"width": "570"}, {"width": 0}, {"height": 300}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "takes numbers"):
                vrfit.placements({"vr_backbox": {"DMD": bad}})
        self.assertEqual(vrfit.placements({}), {})

    def test_every_shipped_map_reads(self):
        for path in sorted(MAPS.glob("*.json")):
            with self.subTest(map=path.name):
                m = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(m, dict):
                    vrfit.placements(m)


if __name__ == "__main__":
    unittest.main()
