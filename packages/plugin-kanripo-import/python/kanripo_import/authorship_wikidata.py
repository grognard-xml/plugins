"""Resolve authorship rows to Wikidata Q-ids (work P50/P98 first, name index fallback)."""

from __future__ import annotations

from typing import Any

from kanripo_import.person_name_normalize import names_match, normalize_person_name

_EDITOR_MARKERS = ("編", "輯", "纂")


def role_bucket(function: str) -> str:
    """Map catalog authorship function to Wikidata author/editor bucket."""
    fn = (function or "").strip()
    if any(marker in fn for marker in _EDITOR_MARKERS):
        return "editor"
    return "author"


def _author_labels(author: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    primary = (author.get("label") or "").strip()
    if primary:
        labels.append(primary)
    for label in author.get("labels") or []:
        text = str(label).strip()
        if text and text not in labels:
            labels.append(text)
    return labels


def _normalized_labels(author: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for label in _author_labels(author):
        norm = normalize_person_name(label)
        if norm and norm not in out:
            out.append(norm)
    return out


def match_wikidata_author(
    person_name: str,
    function: str,
    wikidata_authors: list[dict[str, Any]],
    *,
    used_qids: set[str],
) -> str:
    """Pick the best Wikidata Q-id for one authorship row."""
    name = (person_name or "").strip()
    if not name or not wikidata_authors:
        return ""

    bucket = role_bucket(function)
    available = [row for row in wikidata_authors if (row.get("qid") or "").strip() not in used_qids]
    if not available:
        return ""

    def name_hit(row: dict[str, Any]) -> bool:
        target = normalize_person_name(name)
        if not target:
            return False
        if target in _normalized_labels(row):
            return True
        return any(names_match(name, label) for label in _author_labels(row))

    for pool in (
        [row for row in available if row.get("role") == bucket],
        available,
    ):
        for row in pool:
            if name_hit(row):
                return str(row["qid"]).strip()
    return ""


def enrich_authorship_rows(
    authorship: list[dict[str, Any]],
    *,
    wikidata_authors: list[dict[str, Any]] | None = None,
    skqs_authors: dict[str, str] | None = None,
    skqs_authorities: dict[str, dict[str, str]] | None = None,
    persons_by_name: dict[str, str] | None = None,
) -> int:
    """Fill ``wikidata_qid`` / ``cbdb_id`` on authorship dicts. Returns rows enriched."""
    skqs_authors = skqs_authors or {}
    skqs_authorities = skqs_authorities or {}
    persons_by_name = persons_by_name or {}
    used: set[str] = set()
    enriched = 0

    for row in authorship:
        existing_qid = (row.get("wikidata_qid") or "").strip()
        existing_cbdb = (row.get("cbdb_id") or "").strip()
        existing_norbert = (row.get("norbert_id") or "").strip()
        if existing_qid:
            used.add(existing_qid)
        if existing_qid and existing_cbdb and existing_norbert:
            continue

        name = (row.get("person_name") or "").strip()
        dynasty = (row.get("time_dynasty") or row.get("DYNASTY") or "").strip()
        function = (row.get("function") or row.get("FUNCTION") or "").strip()
        qid = existing_qid
        cbdb_id = existing_cbdb
        norbert_id = existing_norbert
        authority: dict[str, str] = {}
        if name:
            key = f"{name}|{dynasty}"
            authority = skqs_authorities.get(key) or skqs_authorities.get(f"{name}|") or {}
            if wikidata_authors and not qid:
                qid = match_wikidata_author(name, function, wikidata_authors, used_qids=used)
            if not qid:
                qid = (
                    authority.get("wikidata_qid")
                    or skqs_authors.get(key)
                    or skqs_authors.get(f"{name}|")
                    or ""
                ).strip()
            if not cbdb_id:
                cbdb_id = (authority.get("cbdb_id") or "").strip()
            if not norbert_id:
                norbert_id = (authority.get("norbert_id") or "").strip()
            if not qid:
                qid = (persons_by_name.get(name) or "").strip()
        changed = False
        if qid and not existing_qid:
            row["wikidata_qid"] = qid
            used.add(qid)
            changed = True
        if cbdb_id and not existing_cbdb:
            row["cbdb_id"] = cbdb_id
            changed = True
        if norbert_id and not existing_norbert:
            row["norbert_id"] = norbert_id
            changed = True
        if changed:
            enriched += 1
    return enriched
