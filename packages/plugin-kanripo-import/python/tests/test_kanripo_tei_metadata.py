import os
import unittest
from pathlib import Path

from kanripo_import.kanripo_tei import convert_kanripo_txt

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "minimal_kanripo.txt"
METADATA_JSON = PLUGIN_ROOT / "data" / "metadata" / "krp_works_by_id.json"


class TestKanripoTeiMetadata(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GROGNARD_PLUGIN_INSTALL_PATH"] = str(PLUGIN_ROOT)
        from kanripo_import.work_metadata import clear_work_metadata_cache

        clear_work_metadata_cache()

    def test_fixture_has_no_bundled_metadata(self) -> None:
        result = convert_kanripo_txt(FIXTURE)
        self.assertEqual(result["meta"]["kanripo_id"], "KRTEST1")
        self.assertEqual(result.get("metadata_xml"), "")

    @unittest.skipUnless(METADATA_JSON.is_file(), "run npm run build:metadata first")
    def test_skqs_work_enriches_meta(self) -> None:
        import tempfile

        sample = (
            "#+TITLE: 周易古占法\n"
            "#+PROPERTY: ID KR1a0030\n"
            "#+PROPERTY: JUAN 1\n"
            "#+PROPERTY: SOURCE tls\n\n"
            "<pb:KR1a0030_tls_001-1a>¶\n"
            "正文。\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "KR1a0030_001.txt"
            path.write_text(sample, encoding="utf-8")
            result = convert_kanripo_txt(path)
        meta = result["meta"]
        self.assertEqual(meta["time_dynasty"], "宋")
        self.assertEqual(meta["vols"], "1")
        self.assertEqual(meta["authorship"][0]["person_name"], "程迥")
        self.assertEqual(meta["edition_label"], "文淵閣四庫全書")
        self.assertEqual(meta["edition_date"], "1782")
        self.assertIn('kr_id="KR1a0030"', result["metadata_xml"])


if __name__ == "__main__":
    unittest.main()
