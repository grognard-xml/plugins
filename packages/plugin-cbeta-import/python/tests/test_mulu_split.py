import unittest
from pathlib import Path

from lxml import etree

from cbeta_import.constants import CB_NS, TEI_NS
from cbeta_import.cbeta_tei import convert_cbeta_xml
from cbeta_import.mulu_split import split_body_into_mulu, split_file

FX = Path(__file__).parent / "fixtures"
_CB = f"{{{CB_NS}}}"
_TEI = f"{{{TEI_NS}}}"


def _contexts(sl) -> list[str]:
    return [
        e.text
        for e in sl.elements
        if e.tag == f"{_TEI}head" and e.get("type") == "context"
    ]


def _heads(sl) -> list[tuple[str, str]]:
    return [(e.get("type") or "", e.text) for e in sl.elements if e.tag == f"{_TEI}head"]


class MuluWorkContextTest(unittest.TestCase):
    """玄應-style dictionary: sections are cited works' juan, inside the dictionary's own juan."""

    def setUp(self):
        self.slices = split_file(FX / "mulu_work_context.xml")

    def test_titles_are_the_sections_own(self):
        self.assertEqual(
            [s.title for s in self.slices],
            ["小乘經　單本", "第一卷", "第二卷", "第一卷", "第一卷"],
        )

    def test_every_section_keeps_the_title_of_its_work(self):
        # the work (level 2) is carried into each of its juan, never joined into one title
        self.assertEqual(_contexts(self.slices[1]), ["小乘經　單本", "正法念經"])
        self.assertEqual(_contexts(self.slices[2]), ["小乘經　單本", "正法念經"])
        self.assertEqual(_contexts(self.slices[3]), ["小乘經　單本", "中阿含經"])
        self.assertEqual(self.slices[1].elements[0].tag, f"{_TEI}head")
        self.assertEqual(
            _heads(self.slices[1]),
            [("context", "小乘經　單本"), ("context", "正法念經"), ("", "第一卷")],
        )

    def test_context_survives_a_juan_boundary_while_its_heading_is_in_force(self):
        # 增一阿含經 (level 2) is still under 小乘經　單本 (level 1), in the next juan of 音義
        self.assertEqual(_contexts(self.slices[4]), ["小乘經　單本", "增一阿含經"])

    def test_juan_opening_moves_to_the_first_section_of_its_juan(self):
        # nothing of juan 2's opening is left at the end of the previous section
        tail = [e for e in self.slices[3].elements if e.tag == f"{_CB}jhead" or e.tag == f"{_CB}juan"]
        self.assertFalse(any("音義卷第二" in "".join(e.itertext()) for e in tail))
        first_of_juan2 = self.slices[4]
        text = "".join("".join(e.itertext()) for e in first_of_juan2.elements)
        self.assertIn("音義卷第二", text)
        # the opening comes before the headings
        self.assertEqual(first_of_juan2.elements[0].get("unit"), "juan")

    def test_sections_know_their_juan(self):
        self.assertEqual([s.in_juan for s in self.slices], ["1", "1", "1", "1", "2"])

    def test_list_stays_in_its_own_section_with_the_juan_opening(self):
        first = self.slices[0]
        text = "".join("".join(e.itertext()) for e in first.elements)
        self.assertIn("音義卷第一", text)
        self.assertIn("中阿含經", text)

    def test_converted_body_opens_with_its_heads_and_flags_them(self):
        result = convert_cbeta_xml(FX / "mulu_work_context.xml", cross_family=True, split_unit="mulu")
        row = result["juan"][1]
        self.assertTrue(row["heads_included"])
        self.assertEqual(row["in_juan"], "1")
        root = etree.fromstring(row["body_xml"].encode("utf-8"))
        heads = root.find(f".//{_TEI}body").findall(f"{_TEI}head")
        self.assertEqual(
            [(h.get("type"), "".join(h.itertext())) for h in heads],
            [("context", "小乘經　單本"), ("context", "正法念經"), (None, "第一卷")],
        )


class MuluTitleWithGaijiTest(unittest.TestCase):
    """A title is the whole mulu, not just the text before its first child (大集賢護菩<g>薩</g>經)."""

    XML = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:cb="http://www.cbeta.org/ns/1.0"><text><body>'
        '<cb:div type="other"><cb:mulu type="其他" level="2">大集賢護菩<g ref="#CB16765">\U000f1d88</g>經</cb:mulu>'
        '<head>大集賢護菩<g ref="#CB16765">\U000f1d88</g>經</head>'
        '<entry><form>矛</form><def>甲。</def></entry></cb:div></body></text></TEI>'
    )

    def test_title_and_head_keep_the_gaiji(self):
        from cbeta_import import gaiji

        root = etree.fromstring(self.XML.encode())
        info = {"CB16765": gaiji.GaijiInfo("CB16765", "[x]", "薩", "U+F1D88")}
        (sl,) = split_body_into_mulu(root, {}, info)
        self.assertEqual(sl.title, "大集賢護菩薩經")
        heads = [e for e in sl.elements if e.tag == f"{_TEI}head"]
        self.assertEqual(len(heads), 1)  # the source head is the section's head, not repeated
        self.assertEqual(heads[0].find(f"{_TEI}g").get("ref"), "#CB16765")


class MuluSplitTest(unittest.TestCase):
    def test_splits_on_mulu_in_document_order(self):
        slices = split_file(FX / "mulu_split.xml")
        self.assertEqual([s.n for s in slices], ["1", "2", "3"])
        self.assertEqual(slices[0].title, "第一品")
        self.assertEqual(slices[1].title, "小節甲")

    def test_contentless_headings_folded_not_emitted_as_empty_slices(self):
        slices = split_file(FX / "mulu_empty_section.xml")
        # Every emitted slice carries body content — no empty <body> reaches the host.
        for sl in slices:
            self.assertTrue(sl.elements, f"slice {sl.n} ({sl.title!r}) has no content")
        # Numbering is contiguous 1..N over the emitted slices only.
        self.assertEqual([s.n for s in slices], [str(i + 1) for i in range(len(slices))])
        # A section's title is its own heading; the 科 group heading above it is context.
        self.assertEqual([s.title for s in slices], ["攝摩騰", "竺法蘭", "朱士行"])
        self.assertEqual(_contexts(slices[0]), ["譯經篇"])
        self.assertEqual(_contexts(slices[1]), ["譯經篇"])
        self.assertEqual(_contexts(slices[2]), ["義解篇"])
        # The trailing content-less heading is recorded as a straddle note.
        self.assertTrue(
            any("附錄" in note for note in slices[-1].straddles),
            slices[-1].straddles,
        )

    def test_contentless_headings_convert_without_empty_body(self):
        result = convert_cbeta_xml(
            FX / "mulu_empty_section.xml",
            cross_family=True,
            split_unit="mulu",
        )
        self.assertEqual([j["n"] for j in result["juan"]], ["1", "2", "3"])
        for row in result["juan"]:
            root = etree.fromstring(row["body_xml"].encode("utf-8"))
            body = root.find(f".//{_TEI}body")
            self.assertIsNotNone(body)
            self.assertTrue(
                "".join(body.itertext()).strip() or len(body),
                f"section {row['n']} serialized an empty <body>",
            )

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
