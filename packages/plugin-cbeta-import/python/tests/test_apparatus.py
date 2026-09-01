import re
import sys
import unittest
from pathlib import Path

# `python/` on the path so `cbeta_import` imports under `unittest discover`
# (pytest adds it via rootdir; `unittest` does not, and this module sorts first
# so it cannot rely on a later test's import side effects).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree

from cbeta_import import cbeta_tei
from cbeta_import.cbeta_tei import convert_cbeta_xml

FX = Path(__file__).parent / "fixtures"
_XID = "{http://www.w3.org/XML/1998/namespace}id"


class ApparatusPerJuanTest(unittest.TestCase):
    def setUp(self):
        self.r = convert_cbeta_xml(FX / "minimal_cbeta.xml", cross_family=False, split_unit="juan")

    def test_matching_juan_gets_back(self):
        j1 = self.r["juan"][0]
        self.assertEqual(j1["report"]["apparatus_apps"], 1)
        self.assertIn("<back", j1["body_xml"])
        self.assertIn('from="#beg0001001"', j1["body_xml"])

    def test_other_juan_has_no_back(self):
        j2 = self.r["juan"][1]
        self.assertEqual(j2["report"].get("apparatus_apps", 0), 0)
        self.assertNotIn("<back", j2["body_xml"])

    def test_cross_family_downgrades_back(self):
        rx = convert_cbeta_xml(FX / "minimal_cbeta.xml", cross_family=True, split_unit="juan")
        b = rx["juan"][0]["body_xml"]
        self.assertIn("<back", b)
        self.assertNotIn("<cb:div", b)  # cb:div type="apparatus" → div
        self.assertIn('<div type="apparatus"', b)


class MultiFileIdCollisionTest(unittest.TestCase):
    def setUp(self):
        self.r = cbeta_tei._convert(
            [FX / "mf_a.xml", FX / "mf_b.xml"],
            work_id="T0999",
            cross_family=False,
            split_unit="juan",
            cache_root=None,
        )

    def test_two_juan(self):
        self.assertEqual([j["n"] for j in self.r["juan"]], ["1", "2"])

    def test_no_duplicate_xml_ids_across_output(self):
        all_ids: list[str] = []
        for j in self.r["juan"]:
            root = etree.fromstring(j["body_xml"].encode())
            all_ids += [e.get(_XID) for e in root.iter() if e.get(_XID)]
        self.assertEqual(len(all_ids), len(set(all_ids)), all_ids)

    def test_second_file_ids_prefixed_and_pointers_rewritten(self):
        j2 = self.r["juan"][1]["body_xml"]
        # file b's streamed ids were namespaced with its stem
        self.assertIn('xml:id="mf_b__beg_1"', j2)
        self.assertIn('from="#mf_b__beg_1"', j2)
        # file a keeps its bare ids
        j1 = self.r["juan"][0]["body_xml"]
        self.assertIn('xml:id="beg_1"', j1)
        self.assertIn('from="#beg_1"', j1)

    def test_each_juan_keeps_its_own_apparatus(self):
        for j in self.r["juan"]:
            self.assertEqual(j["report"]["apparatus_apps"], 1)
            root = etree.fromstring(j["body_xml"].encode())
            app = root.find(f".//{{{'http://www.tei-c.org/ns/1.0'}}}app")
            frm = app.get("from").lstrip("#")
            ids = {e.get(_XID) for e in root.iter() if e.get(_XID)}
            self.assertIn(frm, ids)  # pointer resolves within the same file

    def test_pointer_targets_are_wellformed(self):
        for j in self.r["juan"]:
            self.assertFalse(re.search(r'from="#[^"]*#', j["body_xml"]))  # no double #


class CrossFileStraddleTest(unittest.TestCase):
    def setUp(self):
        # mf_a = juan 1 open+content; mf_straddle = juan 1 RE-ANCHORED + juan 2
        self.r = cbeta_tei._convert(
            [FX / "mf_a.xml", FX / "mf_straddle.xml"],
            work_id="T0999",
            cross_family=False,
            split_unit="juan",
            cache_root=None,
        )

    def test_repeated_juan_merged(self):
        self.assertEqual([j["n"] for j in self.r["juan"]], ["1", "2"])

    def test_stitch_recorded(self):
        self.assertIn("stitched cross-file juan 1", self.r["warnings"])
        self.assertTrue(
            any("stitched a cross-file continuation" in s for s in self.r["juan"][0]["straddles"])
        )

    def test_merged_juan_has_content_from_both_files(self):
        b1 = self.r["juan"][0]["body_xml"]
        self.assertIn('xml:id="p1"', b1)  # from mf_a
        self.assertIn('xml:id="mf_straddle__p1b"', b1)  # from the continuation
        # the re-anchored second <milestone unit="juan"/> for juan 1 is gone
        self.assertEqual(b1.count('unit="juan"'), 1)

    def test_apparatus_from_both_files_lands_in_merged_juan(self):
        j1 = self.r["juan"][0]
        self.assertEqual(j1["report"]["apparatus_apps"], 2)
        self.assertIn('from="#beg_1"', j1["body_xml"])
        self.assertIn('from="#mf_straddle__beg_1"', j1["body_xml"])
        self.assertNotIn("<back", self.r["juan"][1]["body_xml"])

    def test_no_duplicate_ids(self):
        for j in self.r["juan"]:
            root = etree.fromstring(j["body_xml"].encode())
            ids = [e.get(_XID) for e in root.iter() if e.get(_XID)]
            self.assertEqual(len(ids), len(set(ids)), ids)


if __name__ == "__main__":
    unittest.main()
