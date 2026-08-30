import unittest

from kanripo_import.authorship_wikidata import (
    enrich_authorship_rows,
    match_wikidata_author,
    role_bucket,
)


class TestAuthorshipWikidata(unittest.TestCase):
    def test_role_bucket(self) -> None:
        self.assertEqual(role_bucket("撰"), "author")
        self.assertEqual(role_bucket("編"), "editor")

    def test_match_by_name_and_role(self) -> None:
        authors = [
            {"qid": "Q197649", "role": "author", "labels": ["鄭玄"]},
            {"qid": "Q5365469", "role": "editor", "labels": ["王應麟"]},
        ]
        used: set[str] = set()
        self.assertEqual(
            match_wikidata_author("王應麟", "編", authors, used_qids=used),
            "Q5365469",
        )
        used.add("Q5365469")
        self.assertEqual(
            match_wikidata_author("鄭玄", "撰", authors, used_qids=used),
            "Q197649",
        )

    def test_match_normalized_label_variant(self) -> None:
        authors = [{"qid": "Q10889061", "role": "author", "labels": ["傅崧卿", "Fu Songqing"]}]
        self.assertEqual(
            match_wikidata_author("傳崧卿", "注", authors, used_qids=set()),
            "Q10889061",
        )

    def test_enrich_prefers_skqs_table_over_generic_name_index(self) -> None:
        rows = [{"person_name": "鄭玄", "function": "撰", "time_dynasty": "漢"}]
        count = enrich_authorship_rows(
            rows,
            skqs_authors={"鄭玄|漢": "Q197649"},
            persons_by_name={"鄭玄": "Q999999"},
        )
        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["wikidata_qid"], "Q197649")

    def test_enrich_prefers_work_authors_then_name_index(self) -> None:
        rows = [
            {"person_name": "王應麟", "function": "編"},
            {"person_name": "鄭玄", "function": "撰"},
        ]
        work_authors = [{"qid": "Q5365469", "role": "editor", "labels": ["王應麟"]}]
        count = enrich_authorship_rows(
            rows,
            wikidata_authors=work_authors,
            persons_by_name={"鄭玄": "Q197649"},
        )
        self.assertEqual(count, 2)
        self.assertEqual(rows[0]["wikidata_qid"], "Q5365469")
        self.assertEqual(rows[1]["wikidata_qid"], "Q197649")


if __name__ == "__main__":
    unittest.main()
