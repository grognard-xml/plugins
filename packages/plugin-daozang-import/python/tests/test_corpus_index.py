import unittest

from daozang_import.corpus_index import (
    CorpusEntry,
    entry_id,
    is_catalogue,
    parse_dz_no,
    parse_filename,
    search_index,
    title_from_filename,
)
from daozang_import.daozang_tei import variant_from_relpath


def _entry(dz_no: str, title: str, **overrides) -> CorpusEntry:
    fields = {
        "id": f"dz{dz_no.zfill(4)}-test",
        "dz_no": dz_no,
        "title": title,
        "section": "",
        "dynasty": "",
        "authors": "",
        "file_title": "",
        "rel_path": f"trad/{dz_no}.txt",
        "bytes": 10,
    }
    fields.update(overrides)
    return CorpusEntry(**fields)


class TestCorpusIndex(unittest.TestCase):
    def test_parse_dz_no(self) -> None:
        self.assertEqual(parse_dz_no("DZ0001 靈寶無量度人上品妙經"), "1")
        self.assertEqual(parse_dz_no("0145 上清大洞真經"), "145")

    def test_title_from_filename(self) -> None:
        self.assertEqual(
            title_from_filename("DZ0001 靈寶無量度人上品妙經", "1"),
            "靈寶無量度人上品妙經",
        )

    def test_parse_filename(self) -> None:
        section, title, dynasty, authors = parse_filename(
            "正統道藏洞真部本文類-元始說先天道德經批注-宋-李嘉謀.txt"
        )
        self.assertEqual(section, "正統道藏洞真部本文類")
        self.assertEqual(title, "元始說先天道德經批注")
        self.assertEqual(dynasty, "宋")
        self.assertEqual(authors, "李嘉謀")

    def test_parse_filename_without_dynasty_and_author(self) -> None:
        section, title, dynasty, authors = parse_filename(
            "正統道藏洞真部本文類-靈寶無量度人上品妙經.txt"
        )
        self.assertEqual(section, "正統道藏洞真部本文類")
        self.assertEqual(title, "靈寶無量度人上品妙經")
        self.assertEqual(dynasty, "")
        self.assertEqual(authors, "")

    def test_is_catalogue(self) -> None:
        self.assertTrue(is_catalogue("目錄/總目錄.txt"))
        self.assertFalse(is_catalogue("正統道藏洞真部本文類-黃帝陰符經.txt"))

    def test_variant_from_relpath(self) -> None:
        self.assertEqual(variant_from_relpath("繁体/DZ0001.txt"), "trad")
        self.assertEqual(variant_from_relpath("简体/DZ0001.txt"), "simp")

    def test_search_index(self) -> None:
        entries = [
            _entry("1", "靈寶無量度人上品妙經"),
            _entry("145", "上清大洞真經"),
        ]
        hits = search_index(entries, "大洞")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].title, "上清大洞真經")

    def test_search_matches_metadata_fields(self) -> None:
        entries = [
            _entry("3", "元始說先天道德經註解", dynasty="宋", authors="李家謀（注）"),
            _entry("145", "上清大洞真經"),
        ]
        self.assertEqual(len(search_index(entries, "李家謀")), 1)
        self.assertEqual(len(search_index(entries, "宋")), 1)

    def test_entry_id_unique_for_chinese_filenames(self) -> None:
        first = entry_id("", "正統道藏洞真部本文類-黃帝陰符經.txt")
        second = entry_id("", "正統道藏洞玄部本文類-太上洞玄靈寶十師度人妙經.txt")
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("dz0000-"))


if __name__ == "__main__":
    unittest.main()
