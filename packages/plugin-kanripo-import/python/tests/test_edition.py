import os
import unittest
from pathlib import Path

from kanripo_import.edition import clear_edition_cache, resolve_edition

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class TestEditionResolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["LJB_PLUGIN_INSTALL_PATH"] = str(PLUGIN_ROOT)
        clear_edition_cache()

    def test_skqs_source_with_locator(self) -> None:
        info = resolve_edition(source="四庫全書 文淵閣版, V143.1, p1 - V144.1")
        self.assertEqual(info.edition_profile, "skqs_wyg")
        self.assertEqual(info.edition_label, "文淵閣四庫全書")
        self.assertEqual(info.edition_date, "1782")
        self.assertEqual(info.source_locator, "V143.1, p1 - V144.1")

    def test_zhengdaozang_source(self) -> None:
        info = resolve_edition(source="正統道藏 Zhengtong Daozang")
        self.assertEqual(info.edition_profile, "zhengdaozang")
        self.assertEqual(info.edition_label, "正統道藏")
        self.assertEqual(info.edition_date, "1445")
        self.assertEqual(info.source_locator, "")

    def test_witness_fallback(self) -> None:
        info = resolve_edition(source="", witness_code="WYG")
        self.assertEqual(info.edition_profile, "skqs_wyg")
        self.assertEqual(info.edition_label, "文淵閣四庫全書")
        self.assertEqual(info.edition_date, "1782")

    def test_no_match(self) -> None:
        info = resolve_edition(source="unknown edition", witness_code="tls")
        self.assertEqual(info.edition_profile, "")
        self.assertEqual(info.edition_label, "")
        self.assertEqual(info.edition_date, "")
        self.assertEqual(info.source_locator, "")


if __name__ == "__main__":
    unittest.main()
