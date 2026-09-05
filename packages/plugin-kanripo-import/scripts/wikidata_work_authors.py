"""Fetch Wikidata P50/P98 authors for work Q-ids (metadata build-time)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_LABEL_LANGS = ("zh", "zh-hant", "zh-hans", "lzh", "mul", "en")
_USER_AGENT = "Grognard-kanripo-metadata/1.0 (https://github.com/kanripo; metadata build)"
_BATCH_SIZE = 50


def _entity_id(claim: dict[str, Any]) -> str:
    try:
        value = claim["mainsnak"]["datavalue"]["value"]
        if isinstance(value, dict):
            return str(value.get("id") or "").strip()
    except (KeyError, TypeError):
        return ""
    return ""


def _claim_entity_ids(entity: dict[str, Any], property_id: str) -> list[str]:
    claims = entity.get("claims") or {}
    out: list[str] = []
    seen: set[str] = set()
    for claim in claims.get(property_id) or []:
        qid = _entity_id(claim)
        if qid and qid not in seen:
            seen.add(qid)
            out.append(qid)
    return out


def _pick_labels(entity: dict[str, Any]) -> list[str]:
    labels = entity.get("labels") or {}
    out: list[str] = []
    seen: set[str] = set()
    for lang in _LABEL_LANGS:
        value = (labels.get(lang) or {}).get("value", "")
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def parse_work_authors(entity: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract P50 (author) and P98 (editor) from a Wikidata work entity."""
    if not entity:
        return []
    authors: list[dict[str, Any]] = []
    for qid in _claim_entity_ids(entity, "P50"):
        authors.append({"qid": qid, "role": "author", "labels": []})
    for qid in _claim_entity_ids(entity, "P98"):
        authors.append({"qid": qid, "role": "editor", "labels": []})
    return authors


def fetch_entities(
    qids: list[str],
    *,
    sleep_s: float = 0.05,
) -> dict[str, dict[str, Any]]:
    """Batch-fetch Wikidata entities (labels + claims)."""
    unique = [qid for qid in dict.fromkeys(qid.strip() for qid in qids if (qid or "").strip())]
    out: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(unique), _BATCH_SIZE):
        batch = unique[offset : offset + _BATCH_SIZE]
        params = urllib.parse.urlencode(
            {
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "props": "labels|claims",
                "languages": "|".join(_LABEL_LANGS),
                "format": "json",
            }
        )
        url = f"https://www.wikidata.org/w/api.php?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            continue
        entities = payload.get("entities") or {}
        if isinstance(entities, dict):
            out.update(entities)
        if sleep_s:
            time.sleep(sleep_s)
    return out


def _attach_person_labels(
    authors: list[dict[str, Any]],
    entities: dict[str, dict[str, Any]],
) -> None:
    for author in authors:
        entity = entities.get(author.get("qid") or "", {})
        labels = _pick_labels(entity)
        author["labels"] = labels
        if labels:
            author["label"] = labels[0]


def fetch_authors_for_work_qids(qids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Map work Q-id → author/editor rows with resolved labels."""
    work_entities = fetch_entities(qids)
    authors_by_work: dict[str, list[dict[str, Any]]] = {}
    person_qids: list[str] = []
    for qid, entity in work_entities.items():
        if qid.startswith("-") or entity.get("missing"):
            continue
        authors = parse_work_authors(entity)
        authors_by_work[qid] = authors
        person_qids.extend(author["qid"] for author in authors)
    if person_qids:
        person_entities = fetch_entities(person_qids)
        work_entities.update(person_entities)
    for authors in authors_by_work.values():
        _attach_person_labels(authors, work_entities)
    return authors_by_work


def authors_for_work_record(
    work_qid: str,
    edition_qid: str,
    *,
    authors_by_qid: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Prefer work-item P50/P98; fall back to edition item when work has none."""
    work_qid = (work_qid or "").strip()
    edition_qid = (edition_qid or "").strip()
    authors = authors_by_qid.get(work_qid) or []
    if not authors and edition_qid:
        authors = authors_by_qid.get(edition_qid) or []
    return [dict(row) for row in authors]
