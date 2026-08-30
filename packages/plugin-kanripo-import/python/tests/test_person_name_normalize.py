import unittest

from kanripo_import.person_name_normalize import (
    clean_skqs_person_name,
    normalize_person_name,
    normalize_skqs_dynasty,
    names_match,
    person_name_match_variants,
)


class TestPersonNameNormalize(unittest.TestCase):
    def test_nfkc_and_prefix(self) -> None:
        self.assertEqual(normalize_person_name("西洋南懷仁"), "南懷仁")

    def test_variant_characters(self) -> None:
        self.assertEqual(normalize_person_name("房玄齢"), "房玄齡")
        self.assertEqual(normalize_person_name("梅㲄成"), "梅瑴成")
        self.assertEqual(normalize_person_name("荀況"), "荀子")

    def test_clean_catalog_suffix(self) -> None:
        self.assertEqual(clean_skqs_person_name("趙爾巽 等"), "趙爾巽")

    def test_fu_surname_variant(self) -> None:
        self.assertIn("陳傅良", person_name_match_variants("陳傳良"))

    def test_dynasty_alias(self) -> None:
        self.assertEqual(normalize_skqs_dynasty("南朝宋"), "宋")

    def test_names_match(self) -> None:
        self.assertTrue(names_match("房玄齢", "房玄齡"))


if __name__ == "__main__":
    unittest.main()
