import json
import unittest
from pathlib import Path

from kanripo_import.metadata_xml import build_metadata_xml
from kanripo_import.work_metadata import (
    clear_work_metadata_cache,
    load_work_metadata_index,
    lookup_work_metadata,
)

METADATA_JSON = (
    Path(__file__).resolve().parents[2] / "data" / "metadata" / "krp_works_by_id.json"
)


@unittest.skipUnless(METADATA_JSON.is_file(), "run npm run build:metadata first")
class TestKanripoWorkMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        clear_work_metadata_cache()

    def test_index_loads(self) -> None:
        index = load_work_metadata_index()
        self.assertGreater(len(index), 9000)

    def test_cheng_jiong_skqs(self) -> None:
        work = lookup_work_metadata("KR1a0030")
        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(work.title, "周易古占法")
        self.assertEqual(work.vols, "1")
        self.assertEqual(work.time_dynasty, "宋")
        self.assertEqual(len(work.authorship), 1)
        self.assertEqual(work.authorship[0].person_name, "程迥")
        self.assertEqual(work.authorship[0].person_id, "")

    def test_wikidata_sidecar(self) -> None:
        work = lookup_work_metadata("KR1a0030")
        assert work is not None
        self.assertIsNotNone(work.wikidata)
        assert work.wikidata is not None
        self.assertEqual(work.wikidata.wikidata_work_qid, "Q99692775")
        self.assertTrue(work.wikidata.ws_url.startswith("https://zh.wikisource.org/"))
        sidecar = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "metadata"
            / "krp_wikidata_by_kr_id.json"
        )
        if sidecar.is_file():
            doc = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertIn("KR1a0030", doc.get("entries") or {})
            works_doc = json.loads(METADATA_JSON.read_text(encoding="utf-8"))
            embedded = (works_doc.get("entries") or {}).get("KR1a0030") or {}
            self.assertNotIn("wikidata", embedded)

    def test_bu_shang_dates_and_vols(self) -> None:
        work = lookup_work_metadata("KR1a0002")
        assert work is not None
        self.assertEqual(work.vols, "11")
        self.assertEqual(work.time_dynasty, "周")
        self.assertEqual(work.authorship[0].person_name, "卜商")
        self.assertEqual(work.authorship[0].date_not_before, "-507")
        self.assertEqual(work.authorship[0].date_not_after, "-400")

    def test_kr1a0003_hybrid_author_wikidata(self) -> None:
        work = lookup_work_metadata("KR1a0003")
        assert work is not None
        by_name = {a.person_name: a.wikidata_qid for a in work.authorship}
        self.assertEqual(by_name.get("王應麟"), "Q5365469")
        self.assertEqual(by_name.get("鄭玄"), "Q197649")

    def test_chen_jingyuan_daoist_person_id(self) -> None:
        work = lookup_work_metadata("KR5a0087")
        assert work is not None
        self.assertEqual(work.dzid, "DZ0087")
        self.assertEqual(work.authorship[0].person_name, "陳景元")
        self.assertEqual(work.authorship[0].person_id, "15903")
        self.assertEqual(work.source, "正統道藏 Zhengtong Daozang")
        self.assertEqual(work.edition_profile, "zhengdaozang")
        self.assertEqual(work.edition_label, "正統道藏")
        self.assertEqual(work.edition_date, "1445")

    def test_skqs_edition_fields(self) -> None:
        work = lookup_work_metadata("KR1e0004")
        assert work is not None
        self.assertEqual(work.edition_label, "文淵閣四庫全書")
        self.assertEqual(work.edition_date, "1782")
        self.assertEqual(work.source_locator, "V143.1, p1 - V144.1")
        self.assertEqual(work.edition_profile, "skqs_wyg")

    def test_dz_multi_author_kr5a0001(self) -> None:
        work = lookup_work_metadata("KR5a0001")
        assert work is not None
        names = [a.person_name for a in work.authorship]
        self.assertEqual(names, ["嚴東", "葛巢甫"])

    def test_dz_multi_author_kr5f0014(self) -> None:
        work = lookup_work_metadata("KR5f0014")
        assert work is not None
        self.assertGreaterEqual(len(work.authorship), 11)
        names = [a.person_name for a in work.authorship]
        self.assertIn("曹操", names)
        self.assertIn("張預", names)
        self.assertTrue(work.authorship[0].person_id)

    def test_metadata_xml_fragment(self) -> None:
        work = lookup_work_metadata("KR1a0002")
        assert work is not None
        xml = build_metadata_xml(work, juan="1")
        self.assertIn('kr_id="KR1a0002"', xml)
        self.assertIn("<dyn>周</dyn>", xml)
        self.assertIn('notBefore="-507"', xml)
        self.assertIn("<persName>卜商</persName>", xml)


class TestKanripoMetadataManifest(unittest.TestCase):
    @unittest.skipUnless(METADATA_JSON.is_file(), "run npm run build:metadata first")
    def test_manifest_stats(self) -> None:
        manifest = json.loads(
            (METADATA_JSON.parent / "manifest.json").read_text(encoding="utf-8")
        )
        stats = manifest["stats"]
        self.assertGreaterEqual(stats["works"], 9000)
        self.assertGreater(stats["with_time_dynasty"], 3000)
        self.assertGreater(stats["with_author_dates"], 1000)


if __name__ == "__main__":
    unittest.main()
