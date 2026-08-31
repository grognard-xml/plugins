import unittest
from pathlib import Path

from lxml import etree

from cbeta_import import xml_whitespace
from cbeta_import.cbeta_tei import convert_cbeta_xml
from cbeta_import.constants import TEI_NS

_TEI = f"{{{TEI_NS}}}"
FX = Path(__file__).parent / "fixtures"


class CollapseNewlinesTest(unittest.TestCase):
    def test_three_becomes_two(self):
        self.assertEqual(xml_whitespace.collapse_excess_newlines("a\n\n\nb"), "a\n\nb")

    def test_many_becomes_two(self):
        self.assertEqual(xml_whitespace.collapse_excess_newlines("a" + "\n" * 20 + "b"), "a\n\nb")

    def test_two_unchanged(self):
        self.assertEqual(xml_whitespace.collapse_excess_newlines("a\n\nb"), "a\n\nb")

    def test_tree_text_nodes(self):
        root = etree.fromstring(
            f'<p xmlns="{TEI_NS}">head{"\n" * 10}tail</p>'.encode(),
        )
        n = xml_whitespace.collapse_tree_newlines(root)
        self.assertEqual(n, 1)
        self.assertEqual(root.text, "head\n\ntail")

    def test_apparatus_padding_fixture(self):
        padded = f"""<back xmlns="{TEI_NS}">
  <div type="apparatus"><p>校注{"\n" * 50}</p></div>
</back>"""
        root = etree.fromstring(padded.encode())
        xml_whitespace.collapse_tree_newlines(root)
        text = root.find(f".//{_TEI}p").text
        self.assertNotIn("\n\n\n", text or "")
        self.assertTrue((text or "").endswith("\n\n"))


class ConvertWhitespaceTest(unittest.TestCase):
    def test_convert_caps_apparatus_padding(self):
        fixture = FX / "padded_apparatus.xml"
        result = convert_cbeta_xml(fixture, cross_family=False, split_unit="juan")
        body = result["juan"][0]["body_xml"]
        self.assertNotIn("\n\n\n", body)
        self.assertIn("<back", body)


if __name__ == "__main__":
    unittest.main()
