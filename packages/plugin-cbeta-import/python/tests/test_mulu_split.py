import unittest
from pathlib import Path

from lxml import etree

from cbeta_import.constants import CB_NS, TEI_NS
from cbeta_import.cbeta_tei import convert_cbeta_xml
from cbeta_import.mulu_split import split_file

FX = Path(__file__).parent / "fixtures"
_CB = f"{{{CB_NS}}}"
_TEI = f"{{{TEI_NS}}}"


class MuluSplitTest(unittest.TestCase):
    def test_splits_on_mulu_in_document_order(self):
        slices = split_file(FX / "mulu_split.xml")
        self.assertEqual([s.n for s in slices], ["1", "2", "3"])
        self.assertEqual(slices[0].title, "第一品")
        self.assertEqual(slices[1].title, "小節甲")

    def test_mulu_default_with_juan_fallback(self):
        result = convert_cbeta_xml(FX / "minimal_cbeta.xml", split_unit="mulu")
        self.assertIn("fell back to juan", " ".join(result.get("warnings", [])))
        self.assertEqual(len(result["juan"]), 2)

    def test_cross_family_leaves_no_cb_mulu(self):
        result = convert_cbeta_xml(
            FX / "mulu_split.xml",
            cross_family=True,
            split_unit="mulu",
        )
        body = result["juan"][0]["body_xml"]
        self.assertNotIn("cb:mulu", body)
        self.assertNotIn('place="inline"', body)

    def test_section_marker_not_in_slice_elements(self):
        slices = split_file(FX / "mulu_split.xml")
        for sl in slices:
            if not sl.elements:
                continue
            self.assertNotEqual(
                sl.elements[0].tag,
                f"{_CB}mulu",
                msg=f"slice {sl.n} must not start with the section cb:mulu marker",
            )

    def test_no_cbeta_mulu_wrapper_for_section_title(self):
        """Section title belongs in slice metadata (host ``<head>``), not a nested div."""
        result = convert_cbeta_xml(
            FX / "mulu_split.xml",
            cross_family=True,
            split_unit="mulu",
        )
        for row in result["juan"]:
            root = etree.fromstring(row["body_xml"].encode("utf-8"))
            body = root.find(f".//{_TEI}body")
            self.assertIsNotNone(body)
            for child in body:
                if child.get("ana") != "cbeta-mulu":
                    continue
                head = child.find(f"{_TEI}head")
                self.assertIsNone(
                    head,
                    f"slice {row['n']}: cbeta-mulu div should not repeat section title {row['title']!r}",
                )


if __name__ == "__main__":
    unittest.main()
