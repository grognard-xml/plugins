"""CBDB work-title authorship lookup for SKQS author → Wikidata resolution."""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from cbdb_author_index import (
    CbdbPersonIndex,
    dynasty_compatible,
    query_name_variants,
    suffix_keys,
)
from kanripo_import.person_name_normalize import (
    normalize_person_name,
    person_name_match_variants,
)

# CBDB TEXT_ROLE_CODES: author, editor, compiler, annotator, commentator.
AUTHOR_ROLE_IDS: tuple[int, ...] = (1, 2, 3, 8, 9)


def normalize_work_title(title: str) -> str:
    text = (title or "").strip()
    for ch in "《》":
        text = text.replace(ch, "")
    return text.strip()


def default_cbdb_sqlite_path(plugin_root: Path) -> Path | None:
    env_path = os.environ.get("GROGNARD_CBDB_SQLITE_PATH", "").strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            plugin_root.parents[2] / "authority extraction" / ".upstream" / "cbdb.sqlite3",
            plugin_root.parents[3] / "authority extraction" / ".upstream" / "cbdb.sqlite3",
            plugin_root.parents[2] / "leaf-writer" / "databases" / "cbdb_20260627.sqlite3",
            plugin_root.parents[3] / "leaf-writer" / "databases" / "cbdb_20260627.sqlite3",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


class CbdbTextAuthorIndex:
    """Resolve authors via CBDB ``TEXT_CODES`` + ``BIOG_TEXT_DATA``."""

    def __init__(
        self,
        db: sqlite3.Connection,
        *,
        person_index: CbdbPersonIndex,
    ) -> None:
        self._db = db
        self._person_index = person_index
        self._title_to_textids = self._load_title_index()
        self._person_names = self._load_person_names()
        self._person_dynasty = self._load_person_dynasty()

    @classmethod
    def open(
        cls,
        sqlite_path: Path,
        *,
        person_index: CbdbPersonIndex,
    ) -> CbdbTextAuthorIndex | None:
        if not sqlite_path.is_file():
            return None
        db = sqlite3.connect(str(sqlite_path))
        db.row_factory = sqlite3.Row
        required = ("TEXT_CODES", "BIOG_TEXT_DATA", "BIOG_MAIN", "DYNASTIES")
        if not all(_table_exists(db, table) for table in required):
            db.close()
            return None
        return cls(db, person_index=person_index)

    def _load_title_index(self) -> dict[str, set[int]]:
        out: dict[str, set[int]] = defaultdict(set)
        for row in self._db.execute(
            "SELECT c_textid, c_title_chn, c_title_alt_chn FROM TEXT_CODES"
        ):
            text_id = int(row["c_textid"])
            for field in ("c_title_chn", "c_title_alt_chn"):
                title = normalize_work_title(row[field] or "")
                if len(title) >= 2:
                    out[title].add(text_id)
        return out

    def _load_person_names(self) -> dict[int, set[str]]:
        names: dict[int, set[str]] = defaultdict(set)
        for row in self._db.execute(
            "SELECT c_personid, c_name_chn FROM BIOG_MAIN WHERE c_name_chn IS NOT NULL"
        ):
            pid = int(row["c_personid"])
            names[pid].add(str(row["c_name_chn"]).strip())
        if _table_exists(self._db, "ALTNAME_DATA"):
            for row in self._db.execute(
                """
                SELECT c_personid, c_alt_name_chn
                FROM ALTNAME_DATA
                WHERE c_alt_name_chn IS NOT NULL AND TRIM(c_alt_name_chn) != ''
                """
            ):
                pid = int(row["c_personid"])
                names[pid].add(str(row["c_alt_name_chn"]).strip())
        return names

    def _load_person_dynasty(self) -> dict[int, str]:
        out: dict[int, str] = {}
        for row in self._db.execute(
            """
            SELECT m.c_personid, d.c_dynasty_chn
            FROM BIOG_MAIN m
            LEFT JOIN DYNASTIES d ON d.c_dy = m.c_dy
            """
        ):
            out[int(row["c_personid"])] = str(row["c_dynasty_chn"] or "").strip()
        return out

    def _text_ids_for_titles(self, work_titles: set[str] | list[str]) -> dict[str, set[int]]:
        matched: dict[str, set[int]] = {}
        for raw in work_titles:
            title = normalize_work_title(raw)
            if not title:
                continue
            text_ids = self._title_to_textids.get(title)
            if text_ids:
                matched[title] = set(text_ids)
        return matched

    def _author_person_ids(self, text_ids: set[int]) -> set[int]:
        if not text_ids:
            return set()
        placeholders = ",".join("?" * len(text_ids))
        role_placeholders = ",".join("?" * len(AUTHOR_ROLE_IDS))
        rows = self._db.execute(
            f"""
            SELECT DISTINCT c_personid
            FROM BIOG_TEXT_DATA
            WHERE c_textid IN ({placeholders})
              AND c_role_id IN ({role_placeholders})
            """,
            (*text_ids, *AUTHOR_ROLE_IDS),
        ).fetchall()
        return {int(row["c_personid"]) for row in rows}

    def _name_matches_person(self, person_name: str, person_id: int) -> bool:
        names = self._person_names.get(person_id, set())
        if not names:
            return False
        norm_target = normalize_person_name(person_name)
        normalized_names = {normalize_person_name(name) for name in names}
        if norm_target in normalized_names:
            return True
        for variant in query_name_variants(person_name):
            norm_variant = normalize_person_name(variant)
            if norm_variant in normalized_names:
                return True
            for name in names:
                if name.endswith(variant) and len(name) > len(variant):
                    return True
                for alt in person_name_match_variants(name):
                    if normalize_person_name(alt) == norm_variant:
                        return True
        for key in suffix_keys(person_name):
            for name in names:
                if name.endswith(key) and len(name) > len(key):
                    return True
        return False

    def _wikidata_for_person(self, person_id: int, person_name: str, dynasty: str) -> str:
        hit_qid = self._person_index._wikidata_for_cbdb_hit(  # noqa: SLF001
            _CbdbHitShim(
                cbdb_id=str(person_id),
                dynasty=self._person_dynasty.get(person_id, ""),
                primary_name=next(iter(self._person_names.get(person_id, {person_name}))),
            ),
            person_name,
            dynasty,
        )
        return hit_qid

    def lookup(
        self,
        person_name: str,
        dynasty: str,
        work_titles: set[str] | list[str],
    ) -> tuple[str, str, str, str]:
        """Return ``(wikidata_qid, cbdb_id, source_tag, note)`` or ``("", "", "", "")``."""
        title_map = self._text_ids_for_titles(work_titles)
        if not title_map:
            return "", "", "", ""

        candidates: dict[int, str] = {}
        for title, text_ids in title_map.items():
            for person_id in self._author_person_ids(text_ids):
                cbdb_dynasty = self._person_dynasty.get(person_id, "")
                if not dynasty_compatible(dynasty, cbdb_dynasty):
                    continue
                if not self._name_matches_person(person_name, person_id):
                    continue
                candidates[person_id] = title

        if len(candidates) != 1:
            return "", "", "", ""
        person_id, matched_title = next(iter(candidates.items()))
        qid = self._wikidata_for_person(person_id, person_name, dynasty)
        cbdb_id = str(person_id)
        note = f"text:{matched_title}"
        return qid, cbdb_id, "cbdb_text_author", note

    def suggest_authors_for_titles(
        self,
        work_titles: set[str] | list[str],
        *,
        dynasty: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """CBDB author candidates for SKQS work titles (curation hints)."""
        title_map = self._text_ids_for_titles(work_titles)
        suggestions: list[dict[str, Any]] = []
        for title, text_ids in title_map.items():
            for person_id in sorted(self._author_person_ids(text_ids)):
                cbdb_dynasty = self._person_dynasty.get(person_id, "")
                if dynasty and not dynasty_compatible(dynasty, cbdb_dynasty):
                    continue
                primary = next(iter(self._person_names.get(person_id, {""})))
                suggestions.append(
                    {
                        "title": title,
                        "cbdb_id": str(person_id),
                        "name": primary,
                        "dynasty": cbdb_dynasty,
                    }
                )
                if len(suggestions) >= limit:
                    return suggestions
        return suggestions


class _CbdbHitShim:
    def __init__(self, *, cbdb_id: str, dynasty: str, primary_name: str) -> None:
        self.cbdb_id = cbdb_id
        self.dynasty = dynasty
        self.primary_name = primary_name
        self.matched_string = primary_name
        self.match_kind = "exact_primary"


def build_cbdb_text_author_index(
    *,
    plugin_root: Path,
    person_index: CbdbPersonIndex | None,
    sqlite_path: Path | None = None,
) -> CbdbTextAuthorIndex | None:
    if person_index is None:
        return None
    path = sqlite_path or default_cbdb_sqlite_path(plugin_root)
    if not path:
        return None
    return CbdbTextAuthorIndex.open(path, person_index=person_index)
