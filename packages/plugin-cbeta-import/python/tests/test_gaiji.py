import unittest

from lxml import etree

from cbeta_import import gaiji

CHAR_DECL = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><encodingDesc><charDecl>
    <char xml:id="CB00001"><mapping type="unicode">U+478B</mapping></char>
    <char xml:id="CB00002">
      <mapping type="unicode">U+3401 U+4E00</mapping>
    </char>
    <char xml:id="CB00003">
      <mapping type="unicode"></mapping>
      <mapping type="normal_unicode">U+91CC</mapping>
    </char>
    <char xml:id="CB00004"><mapping type="unicode">直</mapping></char>
    <char xml:id="CB00005"><mapping type="foo">U+0041</mapping></char>
  </charDecl></encodingDesc></teiHeader>
</TEI>"""


class TestLoadCharDecl(unittest.TestCase):
    def setUp(self):
        self.m = gaiji.load_char_decl(etree.fromstring(CHAR_DECL.encode()))

    def test_single_codepoint_notation(self):
        self.assertEqual(self.m["CB00001"], "䞋")

    def test_multi_codepoint_sequence(self):
        self.assertEqual(self.m["CB00002"], "㐁一")

    def test_falls_back_to_normal_unicode(self):
        self.assertEqual(self.m["CB00003"], "里")

    def test_literal_character_passes_through(self):
        self.assertEqual(self.m["CB00004"], "直")

    def test_non_unicode_mapping_ignored(self):
        self.assertNotIn("CB00005", self.m)


class TestResolve(unittest.TestCase):
    def test_no_literal_u_plus_in_output(self):
        g = etree.fromstring(
            '<g xmlns="http://www.tei-c.org/ns/1.0" ref="#CB00001"/>'
        )
        self.assertEqual(gaiji.resolve(g, {"CB00001": "䞋"}), "䞋")


if __name__ == "__main__":
    unittest.main()
