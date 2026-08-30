import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(_PLUGIN_ROOT / "python"))

from cbdb_author_index import CbdbHit, CbdbPersonIndex  # noqa: E402
from cbdb_text_author_index import CbdbTextAuthorIndex  # noqa: E402


class TestCbdbTextAuthorIndex(unittest.TestCase):
    def test_lookup_by_exact_work_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cbdb.sqlite3"
            self._seed_db(db_path)
            person_index = CbdbPersonIndex(
                by_exact={},
                by_suffix={},
                by_norm_primary={},
                cbdb_to_wikidata={"9001": "Q9001"},
                wikidata_by_name_dynasty={},
            )
            index = CbdbTextAuthorIndex.open(db_path, person_index=person_index)
            assert index is not None
            qid, cbdb_id, source, note = index.lookup("馬純", "宋", {"陶朱新錄"})
            self.assertEqual(qid, "Q9001")
            self.assertEqual(cbdb_id, "9001")
            self.assertEqual(source, "cbdb_text_author")
            self.assertIn("text:陶朱新錄", note)

    def test_lookup_cbdb_only_without_wikidata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cbdb.sqlite3"
            self._seed_db(db_path)
            person_index = CbdbPersonIndex(
                by_exact={},
                by_suffix={},
                by_norm_primary={},
                cbdb_to_wikidata={},
                wikidata_by_name_dynasty={},
            )
            index = CbdbTextAuthorIndex.open(db_path, person_index=person_index)
            assert index is not None
            qid, cbdb_id, source, _ = index.lookup("馬純", "宋", {"陶朱新錄"})
            self.assertEqual(qid, "")
            self.assertEqual(cbdb_id, "9001")
            self.assertEqual(source, "cbdb_text_author")

    def test_lookup_requires_unique_cbdb_author(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cbdb.sqlite3"
            self._seed_db(db_path, extra_author=True)
            person_index = CbdbPersonIndex(
                by_exact={},
                by_suffix={},
                by_norm_primary={},
                cbdb_to_wikidata={"9001": "Q9001", "9002": "Q9002"},
                wikidata_by_name_dynasty={},
            )
            index = CbdbTextAuthorIndex.open(db_path, person_index=person_index)
            assert index is not None
            qid, cbdb_id, _, _ = index.lookup("馬純", "宋", {"陶朱新錄"})
            self.assertEqual(qid, "")
            self.assertEqual(cbdb_id, "")

    def test_suggest_authors_for_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "cbdb.sqlite3"
            self._seed_db(db_path)
            person_index = CbdbPersonIndex(
                by_exact={},
                by_suffix={},
                by_norm_primary={},
                cbdb_to_wikidata={},
                wikidata_by_name_dynasty={},
            )
            index = CbdbTextAuthorIndex.open(db_path, person_index=person_index)
            assert index is not None
            hints = index.suggest_authors_for_titles({"陶朱新錄"}, dynasty="宋")
            self.assertEqual(len(hints), 1)
            self.assertEqual(hints[0]["name"], "馬純")
            self.assertEqual(hints[0]["cbdb_id"], "9001")

    def _seed_db(self, path: Path, *, extra_author: bool = False) -> None:
        db = sqlite3.connect(str(path))
        db.executescript(
            """
            CREATE TABLE DYNASTIES (c_dy INTEGER PRIMARY KEY, c_dynasty_chn TEXT);
            CREATE TABLE BIOG_MAIN (
                c_personid INTEGER PRIMARY KEY,
                c_name_chn TEXT,
                c_dy INTEGER
            );
            CREATE TABLE ALTNAME_DATA (
                c_personid INTEGER,
                c_alt_name_chn TEXT
            );
            CREATE TABLE TEXT_CODES (
                c_textid INTEGER PRIMARY KEY,
                c_title_chn TEXT,
                c_title_alt_chn TEXT
            );
            CREATE TABLE BIOG_TEXT_DATA (
                c_textid INTEGER,
                c_personid INTEGER,
                c_role_id INTEGER,
                PRIMARY KEY (c_personid, c_role_id, c_textid)
            );
            INSERT INTO DYNASTIES VALUES (15, '宋');
            INSERT INTO BIOG_MAIN VALUES (9001, '馬純', 15);
            INSERT INTO TEXT_CODES VALUES (500, '陶朱新錄', NULL);
            INSERT INTO BIOG_TEXT_DATA VALUES (500, 9001, 1);
            """
        )
        if extra_author:
            db.execute("INSERT INTO BIOG_MAIN VALUES (9002, '馬純', 15)")
            db.execute("INSERT INTO BIOG_TEXT_DATA VALUES (500, 9002, 1)")
        db.commit()
        db.close()


if __name__ == "__main__":
    unittest.main()
