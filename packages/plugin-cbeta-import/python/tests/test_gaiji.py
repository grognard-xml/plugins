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


PUA_DECL = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><encodingDesc><charDecl>
    <char xml:id="CB07560">
      <charName>CBETA CHARACTER CB07560</charName>
      <charProp><localName>composition</localName><value>[絅-口+又]</value></charProp>
      <charProp><localName>normalized form</localName><value>網</value></charProp>
      <mapping cb:dec="990600" type="PUA" xmlns:cb="http://www.cbeta.org/ns/1.0">U+F1D88</mapping>
    </char>
    <char xml:id="CB00099">
      <charProp><localName>composition</localName><value>[x]</value></charProp>
      <mapping type="PUA">U+F0001</mapping>
    </char>
  </charDecl></encodingDesc></teiHeader>
</TEI>"""

PUA = "\U000F1D88"


class TestPrivateUse(unittest.TestCase):
    def setUp(self):
        tree = etree.fromstring(PUA_DECL.encode())
        self.char_map = gaiji.load_char_decl(tree)
        self.info = gaiji.load_char_info(tree)

    def _body(self, inner: str):
        return etree.fromstring(
            f'<body xmlns="http://www.tei-c.org/ns/1.0"><p>{inner}</p></body>'.encode()
        )

    def test_pua_mapping_is_not_a_unicode_value(self):
        self.assertNotIn("CB07560", self.char_map)

    def test_char_info_reads_composition_normal_form_and_pua(self):
        i = self.info["CB07560"]
        self.assertEqual((i.composition, i.normalized, i.pua), ("[絅-口+又]", "網", "U+F1D88"))

    def test_pua_text_content_is_not_a_resolution(self):
        g = etree.fromstring(
            f'<g xmlns="http://www.tei-c.org/ns/1.0" ref="#CB07560">{PUA}</g>'.encode()
        )
        self.assertIsNone(gaiji.resolve(g, self.char_map))

    def test_unresolved_g_is_kept_and_shows_normal_form(self):
        body = self._body(f'礙<g ref="#CB07560">{PUA}</g>也')
        kept: dict = {}
        n = gaiji.apply(body, self.char_map, self.info, kept)
        self.assertEqual(n, 0)
        g = body.find(".//{http://www.tei-c.org/ns/1.0}g")
        self.assertEqual(g.get("ref"), "#CB07560")
        self.assertEqual(g.text, "網")
        self.assertEqual(list(kept), ["CB07560"])
        self.assertNotIn(PUA, etree.tostring(body, encoding="unicode"))

    def test_no_normal_form_falls_back_to_geta_mark(self):
        body = self._body('<g ref="#CB00099"/>')
        gaiji.apply(body, self.char_map, self.info, {})
        self.assertEqual(body.find(".//{http://www.tei-c.org/ns/1.0}g").text, "〓")

    def test_siddham_is_left_alone(self):
        body = self._body('<g ref="#SD-A440"/>')
        kept: dict = {}
        gaiji.apply(body, self.char_map, self.info, kept)
        self.assertIsNone(body.find(".//{http://www.tei-c.org/ns/1.0}g").text)
        self.assertEqual(kept, {})


if __name__ == "__main__":
    unittest.main()
