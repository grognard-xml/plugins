"""Attach Wikidata/CBDB/Norbert authority ids to Daozang authorship rows."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES_ROOT = _PLUGIN_ROOT.parent


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _skqs_authority_json() -> Path | None:
    return _first_existing(
        [
            _PLUGIN_ROOT / "data" / "metadata" / "krp_skqs_author_wikidata.json",
            _PACKAGES_ROOT / "plugin-kanripo-import" / "data" / "metadata" / "krp_skqs_author_wikidata.json",
        ]
    )


def _wikidata_sidecar_json() -> Path | None:
    return _first_existing(
        [
            _PLUGIN_ROOT / "data" / "metadata" / "krp_wikidata_by_kr_id.json",
            _PACKAGES_ROOT / "plugin-kanripo-import" / "data" / "metadata" / "krp_wikidata_by_kr_id.json",
        ]
    )


@lru_cache(maxsize=1)
def load_skqs_author_authority_index() -> dict[str, dict[str, str]]:
    path = _skqs_authority_json()
    if not path:
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


def _author_wikidata_by_name_json() -> Path | None:
    return _first_existing(
        [
            _PLUGIN_ROOT / "data" / "metadata" / "krp_author_wikidata_by_name.json",
            _PACKAGES_ROOT
            / "plugin-kanripo-import"
            / "data"
            / "metadata"
            / "krp_author_wikidata_by_name.json",
        ]
    )


@lru_cache(maxsize=1)
def load_author_wikidata_by_name() -> dict[str, str]:
    path = _author_wikidata_by_name_json()
    if not path:
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries") or doc
    if not isinstance(entries, dict):
        return {}
    return {str(name).strip(): str(qid).strip() for name, qid in entries.items() if name and qid}


@lru_cache(maxsize=1)
def load_wikidata_by_kr_id() -> dict[str, dict[str, Any]]:
    path = _wikidata_sidecar_json()
    if not path:
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries") or {}
    if not isinstance(entries, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for kr_id, row in entries.items():
        if isinstance(row, dict):
            out[str(kr_id).strip().upper()] = row
    return out


def _ensure_kanripo_import_path() -> None:
    sibling = _PACKAGES_ROOT / "plugin-kanripo-import" / "python"
    if sibling.is_dir():
        path = str(sibling)
        if path not in sys.path:
            sys.path.insert(0, path)


def enrich_authorship_rows(
    authorship: list[dict[str, Any]],
    *,
    kr_id: str = "",
    wikidata_raw: dict[str, Any] | None = None,
) -> int:
    """Fill authority ids on authorship dicts. Returns rows enriched."""
    for row in authorship:
        if not (row.get("norbert_id") or "").strip():
            person_id = (row.get("person_id") or "").strip()
            if person_id:
                row["norbert_id"] = person_id

    wikidata_authors: list[dict[str, Any]] = []
    if wikidata_raw:
        wikidata_authors = list(wikidata_raw.get("wikidata_authors") or [])
    elif kr_id:
        sidecar = load_wikidata_by_kr_id().get(kr_id.strip().upper(), {})
        wikidata_authors = list(sidecar.get("wikidata_authors") or [])

    _ensure_kanripo_import_path()
    try:
        from kanripo_import.authorship_wikidata import enrich_authorship_rows as enrich

        return enrich(
            authorship,
            wikidata_authors=wikidata_authors,
            skqs_authorities=load_skqs_author_authority_index(),
            persons_by_name=load_author_wikidata_by_name(),
        )
    except ImportError:
        pass

    index = load_skqs_author_authority_index()
    by_name = load_author_wikidata_by_name()
    enriched = 0
    for row in authorship:
        name = (row.get("person_name") or "").strip()
        dynasty = (row.get("time_dynasty") or "").strip()
        key = f"{name}|{dynasty}"
        authority = index.get(key) or index.get(f"{name}|") or {}
        changed = False
        for field, source in (
            ("wikidata_qid", "wikidata_qid"),
            ("cbdb_id", "cbdb_id"),
            ("norbert_id", "norbert_id"),
        ):
            if not (row.get(field) or "").strip() and (authority.get(source) or "").strip():
                row[field] = authority[source].strip()
                changed = True
        if not (row.get("wikidata_qid") or "").strip() and name:
            qid = (by_name.get(name) or "").strip()
            if qid:
                row["wikidata_qid"] = qid
                changed = True
        if changed:
            enriched += 1
    return enriched


def clear_authorship_authority_cache() -> None:
    load_skqs_author_authority_index.cache_clear()
    load_wikidata_by_kr_id.cache_clear()
    load_author_wikidata_by_name.cache_clear()
