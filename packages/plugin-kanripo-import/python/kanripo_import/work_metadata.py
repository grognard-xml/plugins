"""Load bundled Kanripo work metadata for import."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from kanripo_import._paths import metadata_dir
from kanripo_import.authorship_wikidata import enrich_authorship_rows
from kanripo_import.edition import clear_edition_cache, resolve_edition
from kanripo_import.skqs_author_wikidata import (
    clear_skqs_author_wikidata_cache,
    load_skqs_author_authority_index,
)

_KR_ID_RE = re.compile(r"^KR[a-z0-9]+$", re.IGNORECASE)


@dataclass(frozen=True)
class WikidataMetadata:
    work_qid: str
    edition_qid: str
    wikidata_work_qid: str
    ws_page: str
    ws_url: str
    match_tier: str
    primary_name: str
    aliases: tuple[str, ...]
    description: str
    start_year: str
    end_year: str


@dataclass(frozen=True)
class AuthorshipRecord:
    author_index: str
    person_name: str
    person_id: str
    wikidata_qid: str
    cbdb_id: str
    norbert_id: str
    function: str
    time_dynasty: str
    author_dates: str
    date_not_before: str
    date_not_after: str


@dataclass(frozen=True)
class WorkMetadata:
    kr_id: str
    title: str
    vols: str
    juan_count: str
    source: str
    edition_profile: str
    edition_label: str
    edition_date: str
    source_locator: str
    cbeta_id: str
    dzid: str
    time_dynasty: str
    date_not_before: str
    date_not_after: str
    author_dates: str
    authorship: tuple[AuthorshipRecord, ...]
    wikidata: WikidataMetadata | None


def _parse_wikidata(raw: dict[str, Any] | None) -> WikidataMetadata | None:
    if not raw or not isinstance(raw, dict):
        return None
    work_qid = (raw.get("work_qid") or "").strip()
    edition_qid = (raw.get("edition_qid") or "").strip()
    primary = (raw.get("wikidata_work_qid") or work_qid or edition_qid).strip()
    if not primary and not (raw.get("ws_page") or "").strip():
        return None
    aliases_raw = raw.get("aliases") or []
    aliases = tuple(str(a).strip() for a in aliases_raw if str(a).strip())
    start = raw.get("start_year")
    end = raw.get("end_year")
    return WikidataMetadata(
        work_qid=work_qid,
        edition_qid=edition_qid,
        wikidata_work_qid=primary,
        ws_page=(raw.get("ws_page") or "").strip(),
        ws_url=(raw.get("ws_url") or "").strip(),
        match_tier=(raw.get("match_tier") or "").strip(),
        primary_name=(raw.get("primary_name") or "").strip(),
        aliases=aliases,
        description=(raw.get("description") or "").strip(),
        start_year="" if start is None else str(start),
        end_year="" if end is None else str(end),
    )


@lru_cache(maxsize=1)
def _load_skqs_author_authority_index() -> dict[str, dict[str, str]]:
    return load_skqs_author_authority_index()


@lru_cache(maxsize=1)
def _load_author_wikidata_index() -> dict[str, str]:
    path = metadata_dir() / "krp_author_wikidata_by_name.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries") or {}
    if not isinstance(entries, dict):
        return {}
    return {str(name).strip(): str(qid).strip() for name, qid in entries.items() if name and qid}


def _parse_authorship(
    raw: list[dict[str, str]] | None,
    *,
    wikidata_raw: dict[str, Any] | None = None,
) -> tuple[AuthorshipRecord, ...]:
    rows = [dict(row) for row in (raw or [])]
    wikidata_authors = (wikidata_raw or {}).get("wikidata_authors") or []
    enrich_authorship_rows(
        rows,
        wikidata_authors=wikidata_authors,
        skqs_authorities=_load_skqs_author_authority_index(),
        persons_by_name=_load_author_wikidata_index(),
    )
    out: list[AuthorshipRecord] = []
    for row in rows:
        out.append(
            AuthorshipRecord(
                author_index=(row.get("author_index") or "").strip(),
                person_name=(row.get("person_name") or "").strip(),
                person_id=(row.get("person_id") or "").strip(),
                wikidata_qid=(row.get("wikidata_qid") or "").strip(),
                cbdb_id=(row.get("cbdb_id") or "").strip(),
                norbert_id=(row.get("norbert_id") or "").strip(),
                function=(row.get("function") or row.get("FUNCTION") or "").strip(),
                time_dynasty=(row.get("time_dynasty") or row.get("DYNASTY") or "").strip(),
                author_dates=(row.get("author_dates") or row.get("DATES") or "").strip(),
                date_not_before=(row.get("date_not_before") or "").strip(),
                date_not_after=(row.get("date_not_after") or "").strip(),
            )
        )
    return tuple(out)


@lru_cache(maxsize=1)
def _load_wikidata_doc() -> dict[str, Any]:
    path = metadata_dir() / "krp_wikidata_by_kr_id.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"entries": {}}


@lru_cache(maxsize=1)
def _load_wikidata_index() -> dict[str, dict[str, Any]]:
    entries = _load_wikidata_doc().get("entries") or {}
    out: dict[str, dict[str, Any]] = {}
    for kr_id, raw in entries.items():
        if isinstance(raw, dict):
            key = _normalize_kr_id(str(kr_id))
            if key:
                out[key] = raw
    return out


def _wikidata_raw_for_record(row: dict[str, Any], kr_id: str) -> dict[str, Any] | None:
    sidecar = _load_wikidata_index().get(kr_id)
    if sidecar:
        return sidecar
    embedded = row.get("wikidata")
    return embedded if isinstance(embedded, dict) else None


def _edition_fields_from_row(row: dict[str, Any], *, source: str) -> tuple[str, str, str, str]:
    profile = (row.get("edition_profile") or "").strip()
    label = (row.get("edition_label") or "").strip()
    date = (row.get("edition_date") or "").strip()
    locator = (row.get("source_locator") or "").strip()
    if profile or label or date or locator:
        return profile, label, date, locator
    info = resolve_edition(source=source)
    return info.edition_profile, info.edition_label, info.edition_date, info.source_locator


def _record_from_raw(row: dict[str, Any], *, kr_id: str = "") -> WorkMetadata:
    key = _normalize_kr_id(kr_id or str(row.get("kr_id") or row.get("KR_ID") or ""))
    wikidata_raw = _wikidata_raw_for_record(row, key)
    source = (row.get("source") or row.get("SOURCE") or "").strip()
    edition_profile, edition_label, edition_date, source_locator = _edition_fields_from_row(
        row, source=source
    )
    return WorkMetadata(
        kr_id=key,
        title=(row.get("title") or row.get("text_title") or "").strip(),
        vols=(row.get("vols") or "").strip(),
        juan_count=(row.get("juan_count") or row.get("files") or "").strip(),
        source=source,
        edition_profile=edition_profile,
        edition_label=edition_label,
        edition_date=edition_date,
        source_locator=source_locator,
        cbeta_id=(row.get("cbeta_id") or "").strip(),
        dzid=(row.get("dzid") or row.get("DZID") or "").strip(),
        time_dynasty=(row.get("time_dynasty") or row.get("DYNASTY") or "").strip(),
        date_not_before=(row.get("date_not_before") or "").strip(),
        date_not_after=(row.get("date_not_after") or "").strip(),
        author_dates=(row.get("author_dates") or "").strip(),
        authorship=_parse_authorship(row.get("authorship"), wikidata_raw=wikidata_raw),
        wikidata=_parse_wikidata(wikidata_raw),
    )


def _normalize_kr_id(kr_id: str) -> str:
    s = (kr_id or "").strip()
    if not s:
        return ""
    return s if _KR_ID_RE.match(s) else s


@lru_cache(maxsize=1)
def _load_doc() -> dict[str, Any]:
    path = metadata_dir() / "krp_works_by_id.json"
    if not path.is_file():
        return {"entries": {}}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_work_metadata_index() -> dict[str, WorkMetadata]:
    entries = _load_doc().get("entries") or {}
    out: dict[str, WorkMetadata] = {}
    for kr_id, raw in entries.items():
        if isinstance(raw, dict):
            key = _normalize_kr_id(str(kr_id))
            if key:
                out[key] = _record_from_raw(raw, kr_id=key)
    return out


def lookup_work_metadata(kr_id: str) -> WorkMetadata | None:
    key = _normalize_kr_id(kr_id)
    if not key:
        return None
    return load_work_metadata_index().get(key)


def clear_work_metadata_cache() -> None:
    _load_doc.cache_clear()
    _load_wikidata_doc.cache_clear()
    _load_wikidata_index.cache_clear()
    _load_author_wikidata_index.cache_clear()
    _load_skqs_author_authority_index.cache_clear()
    clear_skqs_author_wikidata_cache()
    clear_edition_cache()
    load_work_metadata_index.cache_clear()
