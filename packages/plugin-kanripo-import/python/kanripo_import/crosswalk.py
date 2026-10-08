"""KRP parallel punctuation source crosswalk (Wikisource + Daozang)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from kanripo_import._paths import concordance_dir
from kanripo_import.work_metadata import _load_wikidata_index, lookup_work_metadata


@dataclass(frozen=True)
class ParallelSource:
    kind: str
    label: str
    url: str = ""
    ws_page: str = ""
    rel_path: str = ""
    dz_id: str = ""


@dataclass(frozen=True)
class ParallelCrosswalk:
    kr_id: str
    title: str
    dz_id: str
    cbeta_id: str
    wikidata_work_qid: str
    sources: tuple[ParallelSource, ...]


def _parse_source(raw: dict[str, str]) -> ParallelSource | None:
    kind = (raw.get("kind") or "").strip()
    label = (raw.get("label") or "").strip()
    if not kind or not label:
        return None
    return ParallelSource(
        kind=kind,
        label=label,
        url=(raw.get("url") or "").strip(),
        ws_page=(raw.get("ws_page") or "").strip(),
        rel_path=(raw.get("rel_path") or "").strip(),
        dz_id=(raw.get("dz_id") or "").strip(),
    )


# Wikisource's 四庫全書本 trees are raw scan transcriptions; punctuation is
# explicitly out of scope there, so they are useless as punctuation parallels.
_UNPUNCTUATED_EDITION_MARKER = "四庫全書本"


def _wikisource_from_wikidata(wd: dict[str, Any]) -> ParallelSource | None:
    ws_url = (wd.get("ws_url") or "").strip()
    ws_page = (wd.get("ws_page") or "").strip()
    if not ws_url or not ws_page:
        return None
    if _UNPUNCTUATED_EDITION_MARKER in ws_page:
        return None
    return ParallelSource(
        kind="wikisource",
        label=ws_page,
        url=ws_url,
        ws_page=ws_page,
    )


@lru_cache(maxsize=1)
def _load_wikisource_overrides() -> dict[str, Any]:
    """Hand-maintained punctuated Wikisource trees (``wikisource_punctuated_overrides.json``)."""
    path = concordance_dir() / "wikisource_punctuated_overrides.json"
    if not path.is_file():
        return {}
    entries = json.loads(path.read_text(encoding="utf-8")).get("entries") or {}
    return entries if isinstance(entries, dict) else {}


def _wikisource_from_override(kr_id: str) -> ParallelSource | None:
    raw = _load_wikisource_overrides().get(kr_id)
    if not isinstance(raw, dict):
        return None
    url = (raw.get("url") or "").strip()
    label = (raw.get("label") or "").strip()
    if not url or not label:
        return None
    return ParallelSource(kind="wikisource", label=label, url=url)


def _build_crosswalk(
    kr_id: str,
    *,
    bundled: dict[str, Any] | None,
    wd: dict[str, Any] | None,
) -> ParallelCrosswalk | None:
    sources: list[ParallelSource] = []
    ws = _wikisource_from_override(kr_id) or _wikisource_from_wikidata(wd or {})
    if ws:
        sources.append(ws)
    for item in (bundled or {}).get("sources") or []:
        if not isinstance(item, dict):
            continue
        parsed = _parse_source(item)
        if parsed and parsed.kind != "wikisource":
            sources.append(parsed)
    if not sources:
        return None

    work = lookup_work_metadata(kr_id)
    wd = wd or {}
    return ParallelCrosswalk(
        kr_id=kr_id,
        title=work.title if work else (bundled or {}).get("title", ""),
        dz_id=work.dzid if work else (bundled or {}).get("dz_id", ""),
        cbeta_id=work.cbeta_id if work else (bundled or {}).get("cbeta_id", ""),
        wikidata_work_qid=(wd.get("wikidata_work_qid") or "").strip(),
        sources=tuple(sources),
    )


@lru_cache(maxsize=1)
def _load_doc() -> dict[str, Any]:
    path = concordance_dir() / "krp_parallel_sources.json"
    if not path.is_file():
        return {"entries": {}}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_parallel_crosswalk_index() -> dict[str, ParallelCrosswalk]:
    bundled_entries = _load_doc().get("entries") or {}
    wd_index = _load_wikidata_index()
    keys = (
        set(bundled_entries)
        | set(_load_wikisource_overrides())
        | {
            kr_id
            for kr_id, row in wd_index.items()
            if (row.get("ws_url") or "").strip() and (row.get("ws_page") or "").strip()
        }
    )
    out: dict[str, ParallelCrosswalk] = {}
    for kr_id in keys:
        bundled = bundled_entries.get(kr_id)
        crosswalk = _build_crosswalk(
            kr_id,
            bundled=bundled if isinstance(bundled, dict) else None,
            wd=wd_index.get(kr_id),
        )
        if crosswalk:
            out[kr_id] = crosswalk
    return out


def lookup_parallel_crosswalk(kr_id: str) -> ParallelCrosswalk | None:
    key = (kr_id or "").strip()
    if not key:
        return None
    bundled_entries = _load_doc().get("entries") or {}
    bundled = bundled_entries.get(key)
    return _build_crosswalk(
        key,
        bundled=bundled if isinstance(bundled, dict) else None,
        wd=_load_wikidata_index().get(key),
    )


def clear_parallel_crosswalk_cache() -> None:
    _load_doc.cache_clear()
    _load_wikisource_overrides.cache_clear()
    load_parallel_crosswalk_index.cache_clear()
