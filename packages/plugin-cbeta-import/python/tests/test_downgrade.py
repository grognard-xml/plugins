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


class DictionaryDefTest(unittest.TestCase):
    """``cb:def`` (the definition of a dictionary entry) is not TEI: without a mapping a project on
    the TEI-ALL schema drops every definition of a work like 一切經音義."""

    def test_single_p_becomes_def_with_p_attributes(self):
        body = _frag(
            '<entry><form>池沼</form><cb:def><p xml:id="p1" rend="inline">之遶反<lb n="1"/>'
            '說文<note place="inline">注</note>。</p></cb:def></entry>'
        )
        self.assertEqual(downgrade.dictionary_defs(body), 1)
        entry = body[0]
        self.assertIsNone(entry.find(f"{_CB}def"))
        d = entry.find(f"{_TEI}def")
        self.assertEqual(d.get("{http://www.w3.org/XML/1998/namespace}id"), "p1")
        self.assertIsNone(d.get("rend"))  # "inline" is what a <def> is anyway
        self.assertIsNone(d.find(f"{_TEI}p"))  # <def> takes phrase content only
        self.assertEqual("".join(d.itertext()), "之遶反說文注。")
        self.assertIsNotNone(d.find(f"{_TEI}lb"))
        self.assertIsNotNone(d.find(f"{_TEI}note"))

    def test_each_paragraph_becomes_its_own_def_in_order(self):
        body = _frag(
            '<entry><cb:def>前<p rend="inline big">一</p><lb n="2"/><p>二</p> 後<note>n</note></cb:def></entry>'
        )
        downgrade.dictionary_defs(body)
        defs = body[0].findall(f"{_TEI}def")
        self.assertEqual(["".join(d.itertext()) for d in defs], ["前", "一", "二 後n"])
        self.assertEqual(defs[1].get("rend"), "big")
        self.assertIsNotNone(defs[1].find(f"{_TEI}lb"))  # follows the <def> it came after

    def test_text_of_the_cb_def_is_not_lost(self):
        body = _frag('<entry><cb:def>裸文字<p>段</p></cb:def><cb:def/></entry>')
        downgrade.dictionary_defs(body)
        self.assertEqual("".join(body.itertext()), "裸文字段")

    def test_entry_place_becomes_rend(self):
        body = _frag('<entry place="inline"><form>x</form></entry>')
        downgrade._normalize_place_attrs(body)
        self.assertNotIn("place", body[0].attrib)
        self.assertEqual(body[0].get("rend"), "inline")

    def test_juan_heading_note_is_kept(self):
        body = _frag(
            '<cb:juan n="1" fun="open"><cb:mulu type="卷"/><cb:jhead>音義卷第一'
            '<note place="inline">大乘單本</note></cb:jhead></cb:juan><p>正文</p>'
        )
        downgrade.juan_blocks(body)
        head = body.find(f"{_TEI}head")
        self.assertEqual(head.get("type"), "juan")
        self.assertEqual(head.find(f"{_TEI}note").text, "大乘單本")
        # an opening heading without a note is still dropped (its title is on the juan <div>)
        plain = _frag('<cb:juan n="1" fun="open"><cb:jhead>音義卷第一</cb:jhead></cb:juan><p>x</p>')
        downgrade.juan_blocks(plain)
        self.assertIsNone(plain.find(f"{_TEI}head"))

    def test_remaining_cb_elements_are_counted(self):
        body = _frag('<cb:event><p>x</p></cb:event><cb:event/><cb:def/>')
        self.assertEqual(downgrade.remaining_cb_elements(body), {"event": 2, "def": 1})


DICT_FIXTURE = Path(__file__).parent / "fixtures" / "dictionary_entries.xml"


class DictionaryEndToEndTest(unittest.TestCase):
    def test_cross_family_has_no_cb_def_and_keeps_every_character(self):
        result = convert_cbeta_xml(DICT_FIXTURE, cross_family=True, split_unit="juan")
        body = result["juan"][0]["body_xml"]
        self.assertNotIn("<cb:def", body)
        self.assertNotIn("<cb:", body)
        self.assertEqual(body.count("<def"), 3)
        for text in ("之遶反說文沼池也", "池水也", "又作梱同苦本反", "三蒼梱門限也", "注文",
                     "大乘單本", "一名某經"):
            self.assertIn(text, "".join(etree.fromstring(body.encode()).itertext()))
        self.assertEqual(result["juan"][0]["report"]["defs_to_tei"], 3)
        self.assertNotIn("CBETA-specific elements left", " ".join(result["warnings"]))

    def test_mulu_split_keeps_the_note_in_a_head_that_repeats_the_title(self):
        result = convert_cbeta_xml(DICT_FIXTURE, cross_family=True, split_unit="mulu")
        text = "".join("".join(etree.fromstring(j["body_xml"].encode()).itertext()) for j in result["juan"])
        self.assertIn("一名某經", text)

    def test_cbeta_family_keeps_cb_def(self):
        body = convert_cbeta_xml(DICT_FIXTURE, cross_family=False, split_unit="juan")["juan"][0]["body_xml"]
        self.assertIn("<cb:def", body)

    def test_unknown_cb_elements_are_reported_not_silent(self):
        import tempfile

        src = DICT_FIXTURE.read_text(encoding="utf-8").replace(
            "</cb:div>\n    <cb:juan n=\"1\" fun=\"close\">",
            "<cb:event><p>事件</p></cb:event></cb:div>\n    <cb:juan n=\"1\" fun=\"close\">",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "T88n8889.xml"
            path.write_text(src, encoding="utf-8")
            result = convert_cbeta_xml(path, cross_family=True, split_unit="juan")
        self.assertTrue(any("cb:event x1" in w for w in result["warnings"]), result["warnings"])


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
