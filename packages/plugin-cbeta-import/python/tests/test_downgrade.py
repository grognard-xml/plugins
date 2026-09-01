import unittest
from pathlib import Path

from lxml import etree

from cbeta_import import downgrade
from cbeta_import.cbeta_tei import convert_cbeta_xml
from cbeta_import.constants import CB_NS, TEI_NS

FIXTURE = Path(__file__).parent / "fixtures" / "cross_family.xml"
_CB = f"{{{CB_NS}}}"
_TEI = f"{{{TEI_NS}}}"


def _frag(xml: str) -> etree._Element:
    return etree.fromstring(
        f'<body xmlns="{TEI_NS}" xmlns:cb="{CB_NS}">{xml}</body>'
    )


class PhoneticGlossTest(unittest.TestCase):
    def test_yin_with_tone(self):
        body = _frag("<p>誦<cb:yin><cb:zi>吽</cb:zi><cb:sg>引</cb:sg></cb:yin>真言</p>")
        downgrade.phonetic_glosses(body)
        p = body[0]
        self.assertIsNone(p.find(f"{_CB}yin"))
        self.assertIn("吽", "".join(p.itertext()))
        note = p.find(f"{_TEI}note")
        self.assertEqual(note.get("type"), "gloss")
        self.assertEqual(note.text, "引")
        self.assertEqual(p.text, "誦吽")  # head char stays inline before the note

    def test_sg_fangie_subtype(self):
        body = _frag('<p>底<cb:yin><cb:zi>底</cb:zi><cb:sg type="fangie">丁以反</cb:sg><cb:sg>引</cb:sg></cb:yin></p>')
        downgrade.phonetic_glosses(body)
        notes = body[0].findall(f"{_TEI}note")
        self.assertEqual([n.get("subtype") for n in notes], ["fanqie", None])

    def test_fan_bare_text_yin(self):
        # real T54n2128 (慧琳 一切經音義) shape: fanqie is bare text on <cb:yin>,
        # no <cb:sg> and no <note>. §10.4 sanity check — was silently dropped.
        body = _frag("<p>似<cb:fan><cb:zi>蠅</cb:zi><cb:yin>以繒反</cb:yin></cb:fan>而大</p>")
        downgrade.phonetic_glosses(body)
        p = body[0]
        self.assertIsNone(p.find(f"{_CB}fan"))
        note = p.find(f"{_TEI}note")
        self.assertEqual(note.get("type"), "gloss")
        self.assertEqual(note.get("subtype"), "fanqie")
        self.assertEqual(note.text, "以繒反")
        self.assertEqual(p.text, "似蠅")  # headword stays inline before the note
        self.assertTrue(("".join(p.itertext())).endswith("而大"))

    def test_fan_yin_with_interrupting_lb(self):
        body = _frag(
            '<p><cb:fan><cb:zi>x</cb:zi><cb:yin>俱<lb n="0372a21" ed="T"/>籰反'
            "</cb:yin></cb:fan></p>"
        )
        downgrade.phonetic_glosses(body)
        self.assertEqual(body[0].find(f"{_TEI}note").text, "俱籰反")

    def test_fan(self):
        body = _frag('<p>誦<cb:fan><cb:zi>儒</cb:zi><cb:yin><note place="inline">仁祚切</note></cb:yin></cb:fan>字</p>')
        downgrade.phonetic_glosses(body)
        p = body[0]
        self.assertIsNone(p.find(f"{_CB}fan"))
        self.assertIn("儒", "".join(p.itertext()))
        note = p.find(f"{_TEI}note")
        self.assertEqual(note.get("subtype"), "fanqie")
        self.assertEqual(note.text, "仁祚切")
        self.assertTrue(("".join(p.itertext())).endswith("字"))  # tail preserved


class TranslationTermsTest(unittest.TestCase):
    def test_tt_to_seg(self):
        body = _frag(
            '<p><cb:tt type="app"><cb:t xml:lang="zh">甲</cb:t>'
            '<cb:t xml:lang="pi" place="foot">Gandhabha</cb:t></cb:tt></p>'
        )
        downgrade.translation_terms(body)
        self.assertIsNone(body.find(f".//{_CB}tt"))
        segs = body.findall(f".//{_TEI}seg")
        self.assertEqual(segs[0].get("subtype"), "cb:tt:app")  # outer
        self.assertEqual(segs[1].get("subtype"), "cb:t")
        _lang = "{http://www.w3.org/XML/1998/namespace}lang"
        self.assertEqual([s.get(_lang) for s in segs[1:]], ["zh", "pi"])
        self.assertEqual(segs[2].get("place"), "foot")


class JuanBlockTest(unittest.TestCase):
    def test_open_removed_close_to_trailer(self):
        body = _frag(
            '<cb:juan n="1" fun="open"><cb:jhead>經卷一</cb:jhead></cb:juan>'
            "<p>x</p>"
            '<cb:juan n="1" fun="close"><cb:jhead>經卷一</cb:jhead></cb:juan>'
        )
        downgrade.juan_blocks(body)
        self.assertIsNone(body.find(f"{_CB}juan"))
        trailer = body.find(f"{_TEI}trailer")
        self.assertEqual(trailer.text, "經卷一")


class MuluDivTest(unittest.TestCase):
    def test_cb_div_renamed_and_type_mapped(self):
        body = _frag('<cb:div type="品"><p>x</p></cb:div>')
        downgrade.mulu_and_divs(body)
        div = body[0]
        self.assertEqual(div.tag, f"{_TEI}div")
        self.assertEqual(div.get("type"), "pin")

    def test_empty_mulu_dropped(self):
        body = _frag('<cb:mulu type="附文" level="1"/><p>x</p>')
        rep = downgrade.mulu_and_divs(body)
        self.assertEqual(rep["mulu_dropped"], 1)
        self.assertEqual([c.tag for c in body], [f"{_TEI}p"])

    def test_empty_juan_mulu_becomes_milestone(self):
        # <cb:mulu type="卷"> survives the juan split into the body; it is not a
        # TEI element, so keep it as <milestone unit="mulu"> for round-trip.
        body = _frag('<cb:mulu type="卷" n="1"/><p>x</p>')
        rep = downgrade.mulu_and_divs(body)
        self.assertEqual(rep["mulu_to_marker"], 1)
        self.assertIsNone(body.find(f"{_CB}mulu"))
        ms = body.find(f"{_TEI}milestone")
        self.assertEqual((ms.get("unit"), ms.get("type"), ms.get("n")), ("mulu", "卷", "1"))

    def test_bare_mulu_builds_div_nesting(self):
        body = _frag(
            '<p>前言</p>'
            '<cb:mulu level="1" n="1" type="品">第一品</cb:mulu><p>a</p>'
            '<cb:mulu level="2" n="1" type="其他">小節</cb:mulu><p>b</p>'
            '<cb:mulu level="1" n="2" type="品">第二品</cb:mulu><p>c</p>'
        )
        rep = downgrade.mulu_and_divs(body)
        self.assertEqual(rep["mulu_to_div"], 3)
        # 前言 stays at body level; then two level-1 <div>s
        self.assertEqual(body[0].tag, f"{_TEI}p")
        divs = body.findall(f"{_TEI}div")
        self.assertEqual(len(divs), 2)
        self.assertEqual(divs[0].get("type"), "pin")
        self.assertEqual(divs[0].find(f"{_TEI}head").text, "第一品")
        # nested level-2 div inside the first
        inner = divs[0].findall(f"{_TEI}div")
        self.assertEqual(len(inner), 1)
        self.assertEqual(inner[0].get("type"), "other")
        self.assertEqual([p.text for p in divs[1].findall(f"{_TEI}p")], ["c"])

    def test_mulu_marker_when_divs_present(self):
        body = _frag(
            '<cb:mulu level="1" type="品">品一</cb:mulu>'
            '<cb:div type="pin"><p>x</p></cb:div>'
        )
        rep = downgrade.mulu_and_divs(body)
        self.assertEqual(rep["mulu_to_marker"], 1)
        self.assertIsNone(body.find(f"{_CB}mulu"))
        ms = body.find(f"{_TEI}milestone")
        self.assertEqual(ms.get("unit"), "mulu")

    def test_nested_mulu_consumed_into_head(self):
        body = _frag(
            '<cb:div type="品">'
            '<cb:mulu level="3" type="其他">1 攝摩騰</cb:mulu><head>攝摩騰一</head><p>x</p>'
            '</cb:div>'
        )
        rep = downgrade.mulu_and_divs(body)
        self.assertGreaterEqual(rep["mulu_consumed_into_head"], 1)
        self.assertIsNone(body.find(f"{_CB}mulu"))
        div = body.find(f"{_TEI}div")
        self.assertEqual(div.find(f"{_TEI}head").text, "攝摩騰一")

    def test_place_on_p_becomes_rend(self):
        body = _frag('<p place="inline">續段。</p>')
        rep = downgrade.apply_cross_family(body)
        p = body.find(f"{_TEI}p")
        self.assertIsNone(p.get("place"))
        self.assertEqual(p.get("rend"), "inline")
        self.assertGreaterEqual(rep["place_attrs_normalised"], 1)


class StructuralTest(unittest.TestCase):
    def test_docnumber_and_cb_attrs(self):
        body = _frag(
            '<cb:docNumber>No. 1</cb:docNumber>'
            '<p cb:type="verse" cb:word-count="4">諸法從緣起</p>'
        )
        downgrade.structural(body)
        label = body.find(f"{_TEI}label")
        self.assertEqual(label.get("type"), "docNumber")
        p = body.find(f"{_TEI}p")
        self.assertEqual(p.get("ana"), "verse")
        self.assertNotIn(f"{_CB}word-count", p.attrib)

    def test_cb_note_key_dropped(self):
        body = _frag('<note cb:note_key="B07.0015a03.07" type="add">x</note>')
        downgrade.structural(body)
        self.assertNotIn(f"{_CB}note_key", body[0].attrib)


class EndToEndTest(unittest.TestCase):
    def test_cross_family_leaves_no_cb_elements(self):
        result = convert_cbeta_xml(FIXTURE, cross_family=True, split_unit="juan")
        body = result["juan"][0]["body_xml"]
        self.assertNotIn("<cb:", body)
        self.assertNotIn(' cb:type=', body)
        self.assertIn('type="gloss"', body)
        self.assertIn('<seg', body)
        self.assertIn('<trailer', body)
        rep = result["juan"][0]["report"]
        self.assertGreaterEqual(rep["phonetic_gloss_downgraded"], 2)
        self.assertGreaterEqual(rep["tt_to_seg"], 1)

    def test_cbeta_family_keeps_cb_but_downgrades_phonetics(self):
        result = convert_cbeta_xml(FIXTURE, cross_family=False, split_unit="juan")
        body = result["juan"][0]["body_xml"]
        self.assertIn("<cb:div", body)
        self.assertIn("<cb:juan", body)
        self.assertNotIn("<cb:yin", body)  # §5.2 is unconditional
        self.assertNotIn("<cb:fan", body)
        self.assertIn('type="gloss"', body)


if __name__ == "__main__":
    unittest.main()
