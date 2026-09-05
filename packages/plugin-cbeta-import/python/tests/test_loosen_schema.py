import importlib.util
import unittest
from pathlib import Path

from lxml import etree

_PKG = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("loosen_schema", _PKG / "scripts" / "loosen_schema.py")
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)

MINI = (Path(__file__).parent / "fixtures" / "mini_cbeta.rng").read_text("utf-8")

_TAGGED = """<doc xmlns="http://www.tei-c.org/ns/1.0">
  <p xml:id="p1">如是我聞。<persName ref="DILA:A1" key="A1">竺<lb ed="T"/>佛念</persName>在
    <placeName ref="DILA:PL1">王舍城</placeName>。時<date era_id="5" jdn="1721426.5">
      <dyn>後秦</dyn><year>十四年</year></date>。<roleName>三藏</roleName>
    <nobleTitle ref="Q9"><placeName>鄱陽</placeName><roleName>王</roleName></nobleTitle>。</p>
</doc>"""


class LoosenSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loose = ls.loosen_rng(MINI)
        cls.rng = etree.RelaxNG(etree.fromstring(cls.loose.encode()))
        cls.base = etree.RelaxNG(etree.fromstring(MINI.encode()))

    def test_marker_and_idempotent(self):
        self.assertIn(ls.MARKER, self.loose)
        self.assertEqual(ls.loosen_rng(self.loose), self.loose)

    def test_compiles_as_relaxng(self):
        self.assertIsNotNone(self.rng)  # setUpClass would have thrown otherwise

    def test_baseline_rejects_tagged_doc(self):
        self.assertFalse(self.base.validate(etree.fromstring(_TAGGED.encode())))

    def test_loosened_accepts_tagged_doc(self):
        doc = etree.fromstring(_TAGGED.encode())
        ok = self.rng.validate(doc)
        self.assertTrue(ok, [str(e) for e in self.rng.error_log])

    def test_authority_attrs_only_where_missing(self):
        root = etree.fromstring(self.loose.encode())
        R = "{http://relaxng.org/ns/structure/1.0}"
        defs = {d.get("name"): d for d in root.iter(f"{R}define")}

        def direct_attrs(name):
            el = defs[name].find(f"{R}element")
            return {a.get("name") for a in el.iter(f"{R}attribute")}

        # byline had no ref/key → both added directly
        self.assertTrue({"ref", "key"} <= direct_attrs("tei_byline"))
        # title already had them via att.canonical → NOT added directly
        self.assertNotIn("ref", direct_attrs("tei_title"))
        # date wires in the sanmiao parts + resolution defines
        date_refs = {r.get("name") for r in defs["tei_date"].iter(f"{R}ref")}
        self.assertIn("ljb_sanmiao_date_parts", date_refs)
        self.assertIn("ljb_sanmiao_att_resolution", date_refs)
        res_attrs = {a.get("name") for a in defs["ljb_sanmiao_att_resolution"].iter(f"{R}attribute")}
        self.assertIn("era_id", res_attrs)

    def test_model_phrase_expanded(self):
        root = etree.fromstring(self.loose.encode())
        R = "{http://relaxng.org/ns/structure/1.0}"
        mp = next(d for d in root.iter(f"{R}define") if d.get("name") == "tei_model.phrase")
        names = {r.get("name") for r in mp.iter(f"{R}ref")}
        self.assertTrue(
            {"tei_persName", "tei_placeName", "tei_date", "ljb_nobleTitle"} <= names
        )

    def test_sch_passthrough(self):
        self.assertEqual(ls.loosen_sch("<schema/>"), "<schema/>")


_BUNDLED = _PKG / "data" / "schema" / "cbeta_p5.rng"


@unittest.skipUnless(_BUNDLED.exists(), "bundled cbeta_p5.rng not built")
class LoosenSchemaV2Test(unittest.TestCase):
    """v2 model loosenings — shared target for the non-CBETA corpus importers."""

    @classmethod
    def setUpClass(cls):
        cls.text = _BUNDLED.read_text("utf-8")
        cls.rng = etree.RelaxNG(etree.fromstring(cls.text.encode()))

    def test_is_v2(self):
        self.assertIn("grognard-cbeta-loosen v2", self.text)

    def test_div_is_dual_namespace(self):
        root = etree.fromstring(self.text.encode())
        R = "{http://relaxng.org/ns/structure/1.0}"
        div = next(d for d in root.iter(f"{R}define") if d.get("name") == "tei_div")
        el = div.find(f"{R}element")
        self.assertIsNone(el.get("name"))
        ns = {n.get("ns") for n in el.iter(f"{R}name")}
        self.assertEqual(
            ns,
            {"http://www.cbeta.org/ns/1.0", "http://www.tei-c.org/ns/1.0"},
        )

    def _doc(self, body: str) -> etree._Element:
        return etree.fromstring(
            (
                '<TEI xmlns="http://www.tei-c.org/ns/1.0" '
                'xmlns:cb="http://www.cbeta.org/ns/1.0">'
                "<teiHeader><fileDesc>"
                "<titleStmt><title>x</title><author role=\"editor\">y</author></titleStmt>"
                "<publicationStmt><publisher/></publicationStmt>"
                "<sourceDesc><p>s</p></sourceDesc></fileDesc>"
                "<profileDesc><creation><date>唐</date></creation>"
                "<textClass><keywords><term>k</term></keywords></textClass></profileDesc>"
                "</teiHeader><text><body>" + body + "</body></text></TEI>"
            ).encode()
        )

    def test_plain_tei_div_validates_in_body(self):
        doc = self._doc('<div type="juan" n="1"><p>正文</p></div>')
        self.assertTrue(self.rng.validate(doc), [str(e) for e in self.rng.error_log])

    def test_cb_div_still_validates_in_body(self):
        doc = self._doc(
            '<milestone unit="juan" n="1"/><cb:div type="other"><p>正文</p></cb:div>'
        )
        self.assertTrue(self.rng.validate(doc), [str(e) for e in self.rng.error_log])


if __name__ == "__main__":
    unittest.main()
