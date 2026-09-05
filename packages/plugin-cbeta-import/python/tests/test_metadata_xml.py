import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from lxml import etree

from cbeta_import import _paths, metadata_xml
from cbeta_import.constants import TEI_NS

FIXTURE = Path(__file__).parent / "fixtures" / "minimal_cbeta.xml"
_TEI = f"{{{TEI_NS}}}"


class ParseBylineTest(unittest.TestCase):
    def test_translator_with_honorific_no_space(self):
        dyn, rows = metadata_xml.parse_byline("後秦龜茲國三藏鳩摩羅什奉　詔譯")
        self.assertEqual(dyn, "後秦")  # peeled by known-dynasty fallback
        self.assertEqual(rows[0].role, "translator")
        self.assertEqual(rows[0].person_name, "龜茲國三藏鳩摩羅什")

    def test_dynasty_split_and_multiple_names(self):
        dyn, rows = metadata_xml.parse_byline("後秦 佛陀耶舍共竺佛念譯")
        self.assertEqual(dyn, "後秦")
        self.assertEqual([r.person_name for r in rows], ["佛陀耶舍", "竺佛念"])
        self.assertTrue(all(r.role == "translator" for r in rows))

    def test_author_verb(self):
        _dyn, rows = metadata_xml.parse_byline("唐 玄奘撰")
        self.assertEqual(rows[0].role, "author")
        self.assertEqual(rows[0].person_name, "玄奘")

    def test_anonymous(self):
        _dyn, rows = metadata_xml.parse_byline("失譯")
        self.assertEqual(rows[0].person_name, "失譯")
        self.assertEqual(rows[0].role, "translator")

    def test_cb_type_overrides_role(self):
        _dyn, rows = metadata_xml.parse_byline("宋 求那跋陀羅", cb_type="Translator")
        self.assertEqual(rows[0].role, "translator")


class ExtractFromHeaderTest(unittest.TestCase):
    def test_fixture(self):
        tree = etree.parse(str(FIXTURE))
        meta = metadata_xml.extract_from_header(tree, "T9999")
        self.assertEqual(meta.title, "測試經")
        self.assertEqual(meta.dynasty, "後秦")
        self.assertEqual([c.person_name for c in meta.contributors], ["鳩摩羅什"])
        self.assertEqual(meta.taisho_vol, "99")
        self.assertEqual(meta.taisho_no, "9999")

    def test_real_cbeta_multi_title_header(self):
        # A real CBETA <titleStmt> stacks series / monograph / "No. …" titles;
        # the work title is the monograph (level="m") one, not the first
        # (series) title, and vol/no come from the structured <idno>.
        work = "高僧傳"  # 高僧傳
        author = "慕皕"  # not the real name; just two Han chars
        xml = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
            "<titleStmt>"
            '<title level="s">Taisho Tripitaka</title>'
            '<title level="s" xml:lang="zh-Hant">大藏經</title>'
            f'<title level="m" xml:lang="zh-Hant">{work}</title>'
            f'<title>Taisho Tripitaka, Electronic version, No. 2059 {work}</title>'
            f"<author>梁 {author}撰</author>"
            "</titleStmt>"
            "<extent>14卷</extent>"
            '<publicationStmt><idno type="CBETA">'
            '<idno type="canon">T</idno>.<idno type="vol">50</idno>'
            '.<idno type="no">2059</idno>'
            "</idno></publicationStmt>"
            "<sourceDesc><bibl>x</bibl></sourceDesc>"
            "</fileDesc></teiHeader></TEI>"
        )
        meta = metadata_xml.extract_from_header(etree.fromstring(xml.encode()), "T50n2059")
        self.assertEqual(meta.title, work)
        self.assertEqual(meta.dynasty, "梁")
        self.assertEqual([c.person_name for c in meta.contributors], [author])
        self.assertEqual((meta.taisho_vol, meta.taisho_no), ("50", "2059"))
        self.assertEqual(meta.juan_count, 14)


class WorkInfoEnrichmentTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "data" / "metadata").mkdir(parents=True)
        (root / "data" / "metadata" / "work_info.json").write_text(
            json.dumps(
                {
                    "T9999": {
                        "title": "測試經（正名）",
                        "dynasty": "姚秦",
                        "category": "般若部",
                        "juan_count": 2,
                        "work_qid": "Q12345",
                        "contributors": [
                            {
                                "person_name": "鳩摩羅什",
                                "role": "translator",
                                "dila_id": "A011711",
                                "norbert_id": "4242",
                            }
                        ],
                    },
                    "B9999": {
                        "title": "測試補編經",
                        "dynasty": "",
                        "category": "新編部類",
                        "juan_count": 1,
                        "work_dila_id": "CA0006097",
                        "contributors": [
                            {"person_name": "法舫", "role": "translator", "dila_id": "A007860"}
                        ],
                    },
                }
            ),
            "utf-8",
        )
        self._prev = os.environ.get("GROGNARD_PLUGIN_INSTALL_PATH")
        os.environ["GROGNARD_PLUGIN_INSTALL_PATH"] = str(root)
        _paths.data_dir.cache_clear()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("GROGNARD_PLUGIN_INSTALL_PATH", None)
        else:
            os.environ["GROGNARD_PLUGIN_INSTALL_PATH"] = self._prev
        _paths.data_dir.cache_clear()
        self._tmp.cleanup()

    def test_work_info_wins(self):
        tree = etree.parse(str(FIXTURE))
        meta = metadata_xml.resolve_work_meta(tree, "T9999")
        self.assertEqual(meta.title, "測試經（正名）")
        self.assertEqual(meta.dynasty, "姚秦")
        self.assertEqual(meta.category, "般若部")
        self.assertEqual(meta.work_qid, "Q12345")
        c = meta.contributors[0]
        self.assertEqual(c.dila_id, "A011711")
        self.assertEqual(c.norbert_id, "4242")

    def test_payload_authorship(self):
        tree = etree.parse(str(FIXTURE))
        payload = metadata_xml.resolve_work_meta(tree, "T9999").payload()
        self.assertEqual(payload["dynasty"], "姚秦")
        self.assertEqual(payload["authorship"][0]["dila_id"], "A011711")
        self.assertEqual(payload["authorship"][0]["role"], "translator")

    def test_build_header_has_authority_ref(self):
        tree = etree.parse(str(FIXTURE))
        meta = metadata_xml.resolve_work_meta(tree, "T9999")
        header = metadata_xml.build_tei_header(meta, juan_n="1", source_files=["T99n9999"])
        xml = etree.tostring(header, encoding="unicode")
        self.assertIn('role="translator"', xml)
        self.assertIn("NORBERT:person-4242", xml)  # norbert wins over dila
        self.assertIn('type="CBETA"', xml)
        self.assertIn("plugin cbeta-import", xml)
        # QID work → title carries a Wikidata ref; 部類 lives in <textClass>/<term>
        self.assertIn('ref="https://www.wikidata.org/entity/Q12345"', xml)
        self.assertRegex(xml, r"term>般若部<")
        self.assertRegex(xml, r"textClass>")

    def test_build_header_category_not_in_creation_and_dila_work_ref(self):
        tree = etree.parse(str(FIXTURE))
        meta = metadata_xml.resolve_work_meta(tree, "B9999")
        self.assertEqual(meta.work_dila_id, "CA0006097")
        self.assertEqual(meta.work_qid, "")
        xml = etree.tostring(
            metadata_xml.build_tei_header(meta, juan_n="1", source_files=["B07n9999"]),
            encoding="unicode",
        )
        # no Wikidata QID → the DILA catalog id is the work authority ref
        self.assertIn('ref="DILA:CA0006097"', xml)
        self.assertRegex(xml, r'idno type="DILA">CA0006097<')
        # 部類 goes in <textClass>/<term>, and <creation> holds only <origDate>
        # (a <note> child of <creation> is what tripped TEI-All validation).
        self.assertRegex(xml, r"term>新編部類<")
        creation = re.search(r"<[^>]*creation>(.*?)</[^>]*creation>", xml)
        if creation:
            self.assertNotIn("note", creation.group(1))

    def test_canon_of(self):
        self.assertEqual(metadata_xml.canon_of("T01n0001"), "T")
        self.assertEqual(metadata_xml.canon_of("T0001"), "T")
        self.assertEqual(metadata_xml.canon_of("ZW01n0001"), "ZW")
        self.assertEqual(metadata_xml.canon_of("JB122n…"), "J")  # series letter, not a 2-letter canon
        self.assertEqual(metadata_xml.canon_of(""), "")

    def test_build_header_fills_edition_and_dated_imprint_from_canon(self):
        tree = etree.parse(str(FIXTURE))
        meta = metadata_xml.resolve_work_meta(tree, "T9999")
        self.assertEqual(meta.canon, "T")
        xml = etree.tostring(
            metadata_xml.build_tei_header(meta, juan_n="1", source_files=["T99n9999"]),
            encoding="unicode",
        )
        self.assertRegex(xml, r"edition>大正新脩大藏經 \(Taishō Shinshū Daizōkyō\)<")
        self.assertRegex(xml, r'date from="1924" to="1934">1924–1934<')
        self.assertLess(re.search(r"[:>]edition>", xml).start(), re.search(r"[:<]imprint>", xml).start())

    def test_build_header_uses_when_for_single_year_canon(self):
        meta = metadata_xml.WorkMeta(work_id="S0001", canon="S", title="測試")
        xml = etree.tostring(
            metadata_xml.build_tei_header(meta, juan_n="1"), encoding="unicode"
        )
        self.assertRegex(xml, r'date when="1935">1935<')

    def test_build_header_leaves_empty_imprint_for_unlisted_canon(self):
        meta = metadata_xml.WorkMeta(work_id="A0001", canon="A", title="測試")
        xml = etree.tostring(
            metadata_xml.build_tei_header(meta, juan_n="1"), encoding="unicode"
        )
        self.assertNotIn("edition>", xml)
        self.assertRegex(xml, r"imprint><[^>]*date ?/><[^>]*imprint>")


if __name__ == "__main__":
    unittest.main()
