import json
import os
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
                    }
                }
            ),
            "utf-8",
        )
        self._prev = os.environ.get("LJB_PLUGIN_INSTALL_PATH")
        os.environ["LJB_PLUGIN_INSTALL_PATH"] = str(root)
        _paths.data_dir.cache_clear()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("LJB_PLUGIN_INSTALL_PATH", None)
        else:
            os.environ["LJB_PLUGIN_INSTALL_PATH"] = self._prev
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
        self.assertIn("般若部", xml)
        self.assertIn("plugin cbeta-import", xml)


if __name__ == "__main__":
    unittest.main()
