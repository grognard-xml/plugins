"""Load bundled Daozang ↔ Kanripo / Norbert metadata for import."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from daozang_import._paths import metadata_dir
from daozang_import.authorship_authority import (
    clear_authorship_authority_cache,
    enrich_authorship_rows,
)

_DYNASTY_AUTHOR_RE = re.compile(r"-([^-]+)-([^-]+)\.txt$", re.UNICODE)


@dataclass(frozen=True)
class WikidataMetadata:
    work_qid: str
    edition_qid: str
    wikidata_work_qid: str
    ws_page: str
    ws_url: str
    match_tier: str
    page_exists: bool


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
    rel_path: str
    dzid: str
    dz_no: str
    title: str
    vols: str
    kr_id: str
    krp_title: str
    edition: str
    variant_class: str
    source: str
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
    ws_page = (raw.get("ws_page") or "").strip()
    if not primary and not ws_page:
        return None
    exists = raw.get("page_exists")
    if isinstance(exists, bool):
        page_exists = exists
    else:
        page_exists = str(exists or "").strip().lower() in {"1", "true", "yes"}
    return WikidataMetadata(
        work_qid=work_qid or primary,
        edition_qid=edition_qid,
        wikidata_work_qid=primary,
        ws_page=ws_page,
        ws_url=(raw.get("ws_url") or "").strip(),
        match_tier=(raw.get("match_tier") or "").strip(),
        page_exists=page_exists,
    )


def _parse_authorship(
    raw: list[dict[str, str]] | None,
    *,
    kr_id: str = "",
    wikidata_raw: dict[str, Any] | None = None,
) -> tuple[AuthorshipRecord, ...]:
    rows = [dict(row) for row in (raw or [])]
    enrich_authorship_rows(rows, kr_id=kr_id, wikidata_raw=wikidata_raw)
    out: list[AuthorshipRecord] = []
    for row in rows:
        out.append(
            AuthorshipRecord(
                author_index=(row.get("author_index") or "").strip(),
                person_name=(row.get("person_name") or "").strip(),
                person_id=(row.get("person_id") or "").strip(),
                wikidata_qid=(row.get("wikidata_qid") or "").strip(),
                cbdb_id=(row.get("cbdb_id") or "").strip(),
                norbert_id=(row.get("norbert_id") or row.get("person_id") or "").strip(),
                function=(row.get("function") or "").strip(),
                time_dynasty=(row.get("time_dynasty") or "").strip(),
                author_dates=(row.get("author_dates") or "").strip(),
                date_not_before=(row.get("date_not_before") or "").strip(),
                date_not_after=(row.get("date_not_after") or "").strip(),
            )
        )
    return tuple(out)


def _record_from_raw(row: dict[str, Any]) -> WorkMetadata:
    return WorkMetadata(
        rel_path=(row.get("rel_path") or "").strip(),
        dzid=(row.get("dzid") or "").strip(),
        dz_no=(row.get("dz_no") or "").strip(),
        title=(row.get("title") or "").strip(),
        vols=(row.get("vols") or "").strip(),
        kr_id=(row.get("kr_id") or "").strip(),
        krp_title=(row.get("krp_title") or "").strip(),
        edition=(row.get("edition") or "").strip(),
        variant_class=(row.get("variant_class") or "").strip(),
        source=(row.get("source") or "").strip(),
        time_dynasty=(row.get("time_dynasty") or "").strip(),
        date_not_before=(row.get("date_not_before") or "").strip(),
        date_not_after=(row.get("date_not_after") or "").strip(),
        author_dates=(row.get("author_dates") or "").strip(),
        authorship=_parse_authorship(
            row.get("authorship"),
            kr_id=(row.get("kr_id") or "").strip(),
            wikidata_raw=row.get("wikidata") if isinstance(row.get("wikidata"), dict) else None,
        ),
        wikidata=_parse_wikidata(row.get("wikidata")),
    )


@lru_cache(maxsize=1)
def _load_doc() -> dict[str, Any]:
    path = metadata_dir() / "dz_works_by_rel_path.json"
    if not path.is_file():
        return {"entries": {}}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_work_metadata_index() -> dict[str, WorkMetadata]:
    entries = _load_doc().get("entries") or {}
    out: dict[str, WorkMetadata] = {}
    for rel, raw in entries.items():
        if isinstance(raw, dict):
            out[rel] = _record_from_raw(raw)
    return out


def lookup_work_metadata(rel_path: str) -> WorkMetadata | None:
    rel = (rel_path or "").strip().replace("\\", "/")
    return load_work_metadata_index().get(rel)


def clear_work_metadata_cache() -> None:
    _load_doc.cache_clear()
    load_work_metadata_index.cache_clear()
    clear_authorship_authority_cache()
