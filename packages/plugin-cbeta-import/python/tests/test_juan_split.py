import unittest
from pathlib import Path

from cbeta_import.cbeta_tei import convert_cbeta_xml
from cbeta_import.juan_split import serialize_juan_body, split_file

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_cbeta.xml"


class TestJuanSplit(unittest.TestCase):
    def test_splits_on_milestone(self):
        slices = split_file(FIXTURE)
        self.assertEqual([s.n for s in slices], ["1", "2"])

    def test_first_juan_keeps_leading_content(self):
        slices = split_file(FIXTURE)
        xml = serialize_juan_body(slices[0])
        self.assertIn("docNumber", xml)
        self.assertIn("卷第一", xml)
        self.assertNotIn("卷第二", xml)

    def test_open_block_title(self):
        slices = split_file(FIXTURE)
        self.assertIn("卷第一", slices[0].title)
        self.assertIn("卷第二", slices[1].title)

    def test_no_straddle_in_fixture(self):
        slices = split_file(FIXTURE)
        self.assertEqual([s.straddles for s in slices], [[], []])


class TestTransform(unittest.TestCase):
    def setUp(self):
        self.result = convert_cbeta_xml(FIXTURE, rel_path="T/T99/T99n9999.xml")

    def test_work_id_parsed(self):
        self.assertEqual(self.result["work_id"], "minimal_cbeta")  # fixture stem
        self.assertEqual(len(self.result["juan"]), 2)

    def test_metadata_extracted(self):
        self.assertEqual(self.result["title"], "測試經")
        self.assertEqual(self.result["dynasty"], "後秦")
        self.assertEqual(self.result["authorship"][0]["person_name"], "鳩摩羅什")
        self.assertEqual(self.result["authorship"][0]["role"], "translator")
        self.assertEqual(self.result["taisho_no"], "9999")

    def test_gaiji_resolved(self):
        j1 = self.result["juan"][0]
        self.assertEqual(j1["report"]["gaiji_resolved"], 1)
        self.assertNotIn("<g ", j1["body_xml"])
        self.assertIn("𡸀", j1["body_xml"])

    def test_style_dropped(self):
        j1 = self.result["juan"][0]
        self.assertGreaterEqual(j1["report"]["style_dropped"], 1)
        self.assertNotIn("margin-left", j1["body_xml"])

    def test_orig_note_dropped_mod_kept(self):
        j1 = self.result["juan"][0]
        self.assertEqual(j1["report"]["orig_notes_dropped"], 1)
        self.assertNotIn('type="orig"', j1["body_xml"])
        self.assertIn('type="mod"', j1["body_xml"])

    def test_reprint_line_dropped(self):
        j2 = self.result["juan"][1]
        self.assertEqual(j2["report"]["reprint_lines_dropped"], 1)
        self.assertNotIn('ed="R138"', j2["body_xml"])
        self.assertIn('ed="T"', j2["body_xml"])


if __name__ == "__main__":
    unittest.main()
