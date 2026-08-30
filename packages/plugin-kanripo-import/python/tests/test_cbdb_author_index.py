import json
import tempfile
import unittest
from pathlib import Path

import sys

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(_PLUGIN_ROOT / "python"))

from cbdb_author_index import CbdbHit, CbdbPersonIndex  # noqa: E402


class TestCbdbAuthorIndex(unittest.TestCase):
    def test_lookup_exact_primary_with_dynasty(self) -> None:
        index = CbdbPersonIndex(
            by_exact={
                "林億": [
                    self._hit("19323", "宋", "林億", "林億", "exact_primary"),
                ]
            },
            by_suffix={},
            by_norm_primary={"林億": [self._hit("19323", "宋", "林億", "林億", "exact_primary")]},
            cbdb_to_wikidata={"19323": "Q45391844"},
            wikidata_by_name_dynasty={},
        )
        qid, cbdb_id, source = index.lookup("林億", "宋")
        self.assertEqual(qid, "Q45391844")
        self.assertEqual(cbdb_id, "19323")
        self.assertEqual(source, "cbdb_dynasty")

    def test_lookup_suffix_for_manchu_name(self) -> None:
        hit = self._hit("55870", "清", "愛新覺羅弘曆", "愛新覺羅弘曆", "suffix_primary")
        index = CbdbPersonIndex(
            by_exact={},
            by_suffix={"弘曆": [hit]},
            by_norm_primary={"愛新覺羅弘曆": [hit]},
            cbdb_to_wikidata={"55870": "Q129598"},
            wikidata_by_name_dynasty={},
        )
        qid, cbdb_id, source = index.lookup("高宗弘曆", "清")
        self.assertEqual(qid, "Q129598")
        self.assertEqual(cbdb_id, "55870")
        self.assertIn("suffix", source)

    def test_lookup_ming_qing_unique_cross_dynasty(self) -> None:
        hit = self._hit("54562", "清", "毛晉", "毛晉", "exact_primary")
        index = CbdbPersonIndex(
            by_exact={"毛晉": [hit]},
            by_suffix={},
            by_norm_primary={"毛晉": [hit]},
            cbdb_to_wikidata={"54562": "Q6768797"},
            wikidata_by_name_dynasty={},
        )
        qid, cbdb_id, source = index.lookup("毛晉", "明")
        self.assertEqual(qid, "Q6768797")
        self.assertEqual(cbdb_id, "54562")
        self.assertIn(source, {"cbdb_ming_qing", "cbdb_dynasty"})

    def test_lookup_variant_character(self) -> None:
        hit = self._hit("17130", "唐", "房玄齡", "房玄齡", "exact_primary")
        index = CbdbPersonIndex(
            by_exact={"房玄齡": [hit]},
            by_suffix={},
            by_norm_primary={"房玄齡": [hit]},
            cbdb_to_wikidata={"17130": "Q736647"},
            wikidata_by_name_dynasty={},
        )
        qid, cbdb_id, _ = index.lookup("房玄齢", "唐")
        self.assertEqual(qid, "Q736647")
        self.assertEqual(cbdb_id, "17130")

    def test_lookup_cbdb_only_without_wikidata(self) -> None:
        hit = self._hit("99999", "宋", "丁易東", "丁易東", "exact_primary")
        index = CbdbPersonIndex(
            by_exact={"丁易東": [hit]},
            by_suffix={},
            by_norm_primary={"丁易東": [hit]},
            cbdb_to_wikidata={},
            wikidata_by_name_dynasty={},
        )
        qid, cbdb_id, source = index.lookup("丁易東", "宋")
        self.assertEqual(qid, "")
        self.assertEqual(cbdb_id, "99999")
        self.assertEqual(source, "cbdb_dynasty")

    def test_from_ndjson_round_trip(self) -> None:
        row = {
            "authorityId": "19323",
            "primaryName": "林億",
            "searchStrings": ["林億"],
            "metadata": {"dynasty": "宋"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "persons.ndjson"
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            index = CbdbPersonIndex.from_ndjson(
                path,
                cbdb_to_wikidata={"19323": "Q45391844"},
            )
        self.assertEqual(index.lookup("林億", "宋")[0], "Q45391844")
        self.assertEqual(index.lookup("林億", "宋")[1], "19323")

    @staticmethod
    def _hit(cbdb_id: str, dynasty: str, primary: str, matched: str, kind: str) -> CbdbHit:
        return CbdbHit(
            cbdb_id=cbdb_id,
            dynasty=dynasty,
            primary_name=primary,
            matched_string=matched,
            match_kind=kind,
        )


if __name__ == "__main__":
    unittest.main()
