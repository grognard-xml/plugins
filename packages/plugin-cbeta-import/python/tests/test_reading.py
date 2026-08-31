import unittest
from pathlib import Path

from cbeta_import.cbeta_tei import convert_cbeta_xml
from cbeta_import.juan_split import split_file

FX = Path(__file__).parent / "fixtures"


class ReadingImportTest(unittest.TestCase):
    def setUp(self):
        self.fixture = FX / "minimal_cbeta.xml"

    def test_clean_removes_anchors_and_back(self):
        full = convert_cbeta_xml(self.fixture, cross_family=False, clean=False, split_unit="juan")
        clean = convert_cbeta_xml(self.fixture, cross_family=False, clean=True, split_unit="juan")
        j1 = clean["juan"][0]
        self.assertNotIn("<anchor", j1["body_xml"])
        self.assertNotIn("<back", j1["body_xml"])
        self.assertGreater(full["juan"][0]["report"].get("apparatus_apps", 0), 0)
        self.assertGreater(j1["report"]["collation_anchors_removed"], 0)

    def test_strip_lb_only_when_requested(self):
        with_lb = convert_cbeta_xml(
            self.fixture, cross_family=False, clean=False, strip_lb=False, split_unit="juan"
        )
        no_lb = convert_cbeta_xml(
            self.fixture, cross_family=False, clean=False, strip_lb=True, split_unit="juan"
        )
        self.assertIn("<lb", with_lb["juan"][0]["body_xml"])
        self.assertNotIn("<lb", no_lb["juan"][0]["body_xml"])
        self.assertGreater(no_lb["juan"][0]["report"]["line_breaks_removed"], 0)

    def test_clean_keeps_lb_by_default(self):
        clean = convert_cbeta_xml(
            self.fixture, cross_family=False, clean=True, strip_lb=False, split_unit="juan"
        )
        self.assertIn("<lb", clean["juan"][0]["body_xml"])


class NestedJuanSplitTest(unittest.TestCase):
    def test_splits_nested_milestones(self):
        slices = split_file(FX / "nested_juan.xml")
        self.assertEqual([s.n for s in slices], ["1", "2"])
        xml1 = "".join(etree_tostring(slices[0].elements))
        xml2 = "".join(etree_tostring(slices[1].elements))
        self.assertIn("卷一", xml1)
        self.assertNotIn("卷二正文", xml1)
        self.assertIn("卷二正文", xml2)


def etree_tostring(elements):
    from lxml import etree

    for el in elements:
        yield etree.tostring(el, encoding="unicode")


if __name__ == "__main__":
    unittest.main()
