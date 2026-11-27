"""A table's own flasher score display, hidden (scoredisplay)."""

from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "spike2_emu" / "vpx"))
import scoredisplay  # noqa: E402
import vpxfile  # noqa: E402


def tile(opacity=100):
    rec = vpxfile.biff_record
    return (struct.pack("<i", 20) + rec("FALP", struct.pack("<i", opacity))
            + rec("NAME", vpxfile.wide("digit001")) + rec("ENDB", b""))


def opacity(data):
    return struct.unpack("<i", dict((t, p) for t, p, _ in vpxfile.item_records(data))["FALP"])[0]


class ScoreDisplayTest(unittest.TestCase):
    def test_the_scripts_own_tiles_and_grid(self):
        script = ("Sub DMDInit\r\n    Dim i\r\n    Digits = Array(digit001, digit002, _\r\n"
                  "        Digit003)\r\nEnd Sub\r\n")
        self.assertEqual(scoredisplay.tiles(script), {"digit001", "digit002", "digit003", "digitgrid"})

    def test_no_display_or_a_commented_out_one_is_none(self):
        script = "'Sub DMDInit\n'    Digits = Array(digit001, digit002, _\n'        digit003)\n"
        self.assertEqual(scoredisplay.tiles(script), set())
        self.assertEqual(scoredisplay.tiles("Dim hsEnteredDigits(3)\n"), set())
        self.assertEqual(scoredisplay.hide_in_place("no-such-table.vpx", "Option Explicit\n"), [])

    def test_a_tile_is_faded_once(self):
        faded = scoredisplay.faded(tile())
        self.assertEqual(opacity(faded), 0)
        self.assertIsNone(scoredisplay.faded(faded))


if __name__ == "__main__":
    unittest.main()
