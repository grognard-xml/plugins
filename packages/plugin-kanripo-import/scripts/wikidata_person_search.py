"""Wikidata person search + cached label index (build-time only)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from kanripo_import.person_name_normalize import (
    clean_skqs_person_name,
    dynasty_lookup_labels,
    normalize_person_name,
    person_name_match_variants,
)

_USER_AGENT = "Grognard-kanripo-metadata/1.0 (https://github.com/kanripo; metadata build)"
_SEARCH_LANGS = ("zh-hant", "zh", "en")
_ENTITY_LANGS = ("zh-hant", "zh", "en", "lzh")


def _api_get(params: dict[str, str], *, sleep_s: float = 0.05) -> dict[str, Any]:
    query = urllib.parse.urlencode({**params, "format": "json"})
    request = urllib.request.Request(
        f"https://www.wikidata.org/w/api.php?{query}",
        headers={"User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if sleep_s:
        time.sleep(sleep_s)
    return payload


def _strip_label_noise(label: str) -> str:
    return clean_skqs_person_name(label).rstrip(",，")


def _entity_label_strings(entity: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for lang in _ENTITY_LANGS:
        label = ((entity.get("labels") or {}).get(lang) or {}).get("value")
        text = _strip_label_noise(str(label or ""))
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    for items in (entity.get("aliases") or {}).values():
        for item in items:
            text = _strip_label_noise(str((item or {}).get("value") or ""))
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return out


def search_person_qid(name: str, *, dynasty: str = "") -> tuple[str, str]:
    """Search Wikidata for a human-name label. Returns ``(qid, matched_label)``."""
    variants = person_name_match_variants(name)
    if not variants:
        return "", ""

    best_qid = ""
    best_label = ""
    best_score = -1
    for variant in variants:
        for lang in _SEARCH_LANGS:
            try:
                payload = _api_get(
                    {
                        "action": "wbsearchentities",
                        "search": variant,
                        "language": lang,
                        "type": "item",
                        "limit": "8",
                    }
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                continue
            for hit in payload.get("search") or []:
                qid = str(hit.get("id") or "").strip()
                label = _strip_label_noise(str(hit.get("label") or ""))
                if not qid.startswith("Q") or not label:
                    continue
                score = 0
                if label in variants or normalize_person_name(label) in {
                    normalize_person_name(v) for v in variants
                }:
                    score += 10
                if label == variant:
                    score += 5
                desc = str(hit.get("description") or "")
                if dynasty and dynasty in desc:
                    score += 2
                if score > best_score:
                    best_score = score
                    best_qid = qid
                    best_label = label
    if best_score < 10:
        return "", ""
    return best_qid, best_label


def fetch_entity_labels(qids: list[str]) -> dict[str, list[str]]:
    """Return Q-id → label strings from Wikidata."""
    unique = [qid for qid in dict.fromkeys(q.strip() for q in qids if q.strip())]
    out: dict[str, list[str]] = {}
    for offset in range(0, len(unique), 50):
        batch = unique[offset : offset + 50]
        try:
            payload = _api_get(
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|aliases",
                    "languages": "|".join(_ENTITY_LANGS),
                }
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        for qid, entity in (payload.get("entities") or {}).items():
            if not str(qid).startswith("Q"):
                continue
            labels = _entity_label_strings(entity or {})
            if labels:
                out[qid] = labels
    return out


def load_search_cache(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries") or {}
    return {str(k): str(v) for k, v in entries.items() if k and v}


def save_search_cache(path: Path, entries: dict[str, str], *, generated_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generatedAt": generated_at,
        "entryCount": len(entries),
        "entries": dict(sorted(entries.items())),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cache_key(person_name: str, dynasty: str = "") -> str:
    name = normalize_person_name(person_name)
    dynasty = (dynasty or "").strip()
    return f"{name}|{dynasty}" if dynasty else name


def lookup_cached(entries: dict[str, str], person_name: str, dynasty: str = "") -> str:
    for dyn in dynasty_lookup_labels(dynasty) if dynasty else ("",):
        key = cache_key(person_name, dyn)
        qid = (entries.get(key) or "").strip()
        if qid:
            return qid
    for variant in person_name_match_variants(person_name):
        qid = (entries.get(normalize_person_name(variant)) or "").strip()
        if qid:
            return qid
    return ""


def enrich_cache_from_qids(entries: dict[str, str], qids: list[str]) -> int:
    added = 0
    for qid, labels in fetch_entity_labels(qids).items():
        for label in labels:
            for key in {label, normalize_person_name(label)}:
                if key and key not in entries:
                    entries[key] = qid
                    added += 1
    return added


def populate_cache_for_authors(
    authors: list[tuple[str, str]],
    entries: dict[str, str],
    *,
    fetch_missing: bool = False,
) -> int:
    """Fill cache entries for ``(person_name, dynasty)`` pairs. Returns additions."""
    added = 0
    for person_name, dynasty in authors:
        if lookup_cached(entries, person_name, dynasty):
            continue
        if not fetch_missing:
            continue
        qid, label = search_person_qid(person_name, dynasty=dynasty)
        if not qid:
            continue
        keys = {cache_key(person_name, dynasty), cache_key(person_name, "")}
        keys.add(cache_key(label, dynasty))
        keys.add(normalize_person_name(person_name))
        for key in keys:
            if key and key not in entries:
                entries[key] = qid
                added += 1
        added += enrich_cache_from_qids(entries, [qid])
    return added
