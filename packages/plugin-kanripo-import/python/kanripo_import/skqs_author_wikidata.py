"""Bundled SKQS author → authority lookup (Wikidata, CBDB, Norbert)."""

from __future__ import annotations

import json
from functools import lru_cache

from kanripo_import._paths import metadata_dir


def author_key(person_name: str, dynasty: str) -> str:
    return f"{person_name.strip()}|{dynasty.strip()}"


@lru_cache(maxsize=1)
def load_skqs_author_authority_index() -> dict[str, dict[str, str]]:
    """Map ``person_name|dynasty`` → ``{wikidata_qid, cbdb_id, norbert_id}``."""
    path = metadata_dir() / "krp_skqs_author_wikidata.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries") or {}
    if not isinstance(entries, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, row in entries.items():
        if not isinstance(row, dict):
            continue
        qid = (row.get("wikidata_qid") or "").strip()
        cbdb_id = (row.get("cbdb_id") or "").strip()
        norbert_id = (row.get("norbert_id") or "").strip()
        if not qid and not cbdb_id and not norbert_id:
            continue
        out[str(key).strip()] = {
            "wikidata_qid": qid,
            "cbdb_id": cbdb_id,
            "norbert_id": norbert_id,
        }
    return out


@lru_cache(maxsize=1)
def load_skqs_author_wikidata_index() -> dict[str, str]:
    """Map ``person_name|dynasty`` → Wikidata Q-id."""
    return {
        key: row["wikidata_qid"]
        for key, row in load_skqs_author_authority_index().items()
        if row.get("wikidata_qid")
    }


@lru_cache(maxsize=1)
def load_skqs_author_cbdb_index() -> dict[str, str]:
    """Map ``person_name|dynasty`` → CBDB person id."""
    return {
        key: row["cbdb_id"]
        for key, row in load_skqs_author_authority_index().items()
        if row.get("cbdb_id")
    }


@lru_cache(maxsize=1)
def load_skqs_author_norbert_index() -> dict[str, str]:
    """Map ``person_name|dynasty`` → Norbert person id."""
    return {
        key: row["norbert_id"]
        for key, row in load_skqs_author_authority_index().items()
        if row.get("norbert_id")
    }


def _lookup_row(
    person_name: str,
    dynasty: str,
    *,
    index: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    table = index if index is not None else load_skqs_author_authority_index()
    name = (person_name or "").strip()
    dyn = (dynasty or "").strip()
    if not name:
        return {}
    return table.get(author_key(name, dyn)) or table.get(author_key(name, "")) or {}


def lookup_skqs_author_qid(
    person_name: str,
    dynasty: str,
    *,
    index: dict[str, str] | None = None,
) -> str:
    if index is not None:
        name = (person_name or "").strip()
        dyn = (dynasty or "").strip()
        if not name:
            return ""
        return (index.get(author_key(name, dyn)) or index.get(author_key(name, "")) or "").strip()
    return (_lookup_row(person_name, dynasty).get("wikidata_qid") or "").strip()


def lookup_skqs_author_cbdb_id(
    person_name: str,
    dynasty: str,
    *,
    index: dict[str, dict[str, str]] | None = None,
) -> str:
    return (_lookup_row(person_name, dynasty, index=index).get("cbdb_id") or "").strip()


def lookup_skqs_author_norbert_id(
    person_name: str,
    dynasty: str,
    *,
    index: dict[str, str] | None = None,
) -> str:
    if index is not None:
        name = (person_name or "").strip()
        dyn = (dynasty or "").strip()
        if not name:
            return ""
        return (index.get(author_key(name, dyn)) or index.get(author_key(name, "")) or "").strip()
    return (_lookup_row(person_name, dynasty).get("norbert_id") or "").strip()


def clear_skqs_author_wikidata_cache() -> None:
    load_skqs_author_authority_index.cache_clear()
    load_skqs_author_wikidata_index.cache_clear()
    load_skqs_author_cbdb_index.cache_clear()
    load_skqs_author_norbert_index.cache_clear()
