#!/usr/bin/env python3
"""
Build a bundled SKQS author → Wikidata Q-id table for plugin-kanripo-import.

Scans ``skqs_org_authorship.csv``, resolves Q-ids via:
  1. P50/P98 on linked work items (``krp_wikidata_by_kr_id.json``)
  2. Person authority packs (name + dynasty, then name only)
  3. CBDB persons (name + dynasty, Ming/Qing unique-primary rule) → Wikidata
  4. CBDB work authorship (SKQS title ↔ TEXT_CODES + BIOG_TEXT_DATA) → Wikidata
  5. Wikidata person-pack labels (all ``searchStrings``) + shipped search cache
  6. Curated Q-ids in ``krp_skqs_author_wikidata_resolved.csv`` / ``..._unresolved.csv``

Anonymous SKQS authors (``闕名``) are excluded from the table.

Writes:
  - data/metadata/krp_skqs_author_wikidata.json   (shipped lookup)
  - data/metadata/krp_skqs_author_wikidata_unresolved.csv (curation report)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "python"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

from kanripo_import.authorship_wikidata import match_wikidata_author
from kanripo_import.person_name_normalize import (
    clean_skqs_person_name,
    dynasty_lookup_labels,
    normalize_person_name,
    normalize_skqs_dynasty,
    person_name_match_variants,
)
from cbdb_author_index import (
    SKQS_IGNORED_AUTHOR_NAMES,
    build_cbdb_person_index,
    load_wikidata_by_name_dynasty,
)
from cbdb_text_author_index import build_cbdb_text_author_index
from wikidata_pack_index import _person_pack_priority, load_persons_by_primary_name
from wikidata_person_search import (
    enrich_cache_from_qids,
    load_search_cache,
    lookup_cached,
    populate_cache_for_authors,
    save_search_cache,
)

# Dynasty labels in SKQS vs person packs (e.g. 吳/魏/晉 → 明前 for pack lookup).
_DYNASTY_ALIASES: dict[str, tuple[str, ...]] = {
    "周": ("周", "明前"),
    "漢": ("漢", "明前"),
    "魏": ("魏", "明前"),
    "晉": ("晉", "明前"),
    "吳": ("吳", "明前", "三國"),
    "隋": ("隋", "明前"),
    "唐": ("唐",),
    "宋": ("宋", "北宋", "南宋"),
    "南朝宋": ("宋", "南朝宋"),
    "劉宋": ("宋", "劉宋"),
    "元": ("元", "明前"),
    "明": ("明",),
    "清": ("清",),
}


def _plugin_root() -> Path:
    return _PLUGIN_ROOT


def _sources_dir() -> Path:
    return _plugin_root() / "data" / "metadata" / "sources"


def _default_person_pack_roots() -> list[Path]:
    root = _plugin_root()
    candidates = [
        root.parents[2] / "authority extraction" / "packs" / "wikidata",
        root.parents[2] / "authoritypacks" / "packs" / "wikidata",
        root.parents[3] / "authority extraction" / "packs" / "wikidata",
        root.parents[3] / "authoritypacks" / "packs" / "wikidata",
    ]
    env = os.environ.get("LJB_WIKIDATA_PERSON_PACK_ROOT", "").strip()
    if env:
        candidates.insert(0, Path(env))
    return [path for path in candidates if path.is_dir()]


def _author_key(person_name: str, dynasty: str) -> str:
    return f"{person_name.strip()}|{dynasty.strip()}"


def _has_authority(rec: dict[str, Any]) -> bool:
    return bool(
        (rec.get("wikidata_qid") or "").strip()
        or (rec.get("cbdb_id") or "").strip()
        or (rec.get("norbert_id") or "").strip()
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(handle)]


def _parse_wikidata_qid(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("Q") and text[1:].isdigit():
        return text
    if "wikidata.org/wiki/Q" in text:
        tail = text.split("/wiki/Q", 1)[-1].split("?")[0].split("#")[0]
        return f"Q{tail}" if tail.isdigit() else ""
    return ""


def _load_norbert_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        name = clean_skqs_person_name(row.get("person_name") or "")
        dynasty = (row.get("dynasty") or "").strip()
        norbert_id = (row.get("norbert_id") or "").strip()
        if not name or not norbert_id:
            continue
        out[_author_key(name, dynasty)] = {
            "norbert_id": norbert_id,
            "source": "norbert",
            "note": (row.get("note") or row.get("sample_kr_id") or "").strip(),
        }
    return out


def _load_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        name = clean_skqs_person_name(row.get("person_name") or "")
        dynasty = (row.get("dynasty") or row.get("DYNASTY") or "").strip()
        qid = _parse_wikidata_qid(row.get("wikidata_qid") or row.get("qid") or "")
        if name and qid:
            out[_author_key(name, dynasty)] = {
                "wikidata_qid": qid,
                "source": "manual",
                "note": (row.get("note") or "").strip(),
            }
    return out


def _row_curated_qid(row: dict[str, str]) -> tuple[str, str]:
    """Return ``(raw_qid, parsed_qid)`` from a curation CSV row."""
    for key in ("qid", "wikidata_qid", ""):
        raw = (row.get(key) or "").strip()
        if raw:
            return raw, _parse_wikidata_qid(raw)
    return "", ""


def _load_curated_qids(path: Path, *, source: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Load Q-ids from a curation CSV (``resolved`` or ``unresolved`` worksheet)."""
    if not path.is_file():
        return {}, []
    out: dict[str, dict[str, str]] = {}
    skipped: list[str] = []
    for row in _read_csv(path):
        raw_qid, qid = _row_curated_qid(row)
        if not raw_qid:
            continue
        name = clean_skqs_person_name(row.get("person_name") or "")
        dynasty = (row.get("dynasty") or "").strip()
        if not name:
            continue
        if not qid:
            skipped.append(f"{name}|{dynasty}: {raw_qid}")
            continue
        kr_id = (row.get("sample_kr_id") or "").strip()
        out[_author_key(name, dynasty)] = {
            "wikidata_qid": qid,
            "source": source,
            "note": kr_id,
        }
    return out, skipped


def _load_curated_resolved(path: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Load Q-ids from ``krp_skqs_author_wikidata_resolved.csv`` (curation worksheet)."""
    return _load_curated_qids(path, source="curated")


def load_persons_by_name_dynasty(pack_roots: list[Path]) -> dict[str, dict[str, str]]:
    """Index ``name|dynasty`` → Q-id from person packs (later packs override on clash)."""
    by_label = load_wikidata_by_name_dynasty(pack_roots)
    return {key: {"wikidata_qid": qid, "pack_dynasty": key.split("|", 1)[-1]} for key, qid in by_label.items()}


def _scan_skqs_authors(skqs_rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    authors: dict[str, dict[str, Any]] = {}
    for row in skqs_rows:
        name = clean_skqs_person_name(row.get("person_name") or "")
        if not name or name in SKQS_IGNORED_AUTHOR_NAMES:
            continue
        dynasty = (row.get("DYNASTY") or "").strip()
        key = _author_key(name, dynasty)
        if key not in authors:
            authors[key] = {
                "person_name": name,
                "dynasty": dynasty,
                "functions": set(),
                "work_ids": set(),
                "work_titles": set(),
                "occurrences": 0,
            }
        rec = authors[key]
        rec["occurrences"] += 1
        fn = (row.get("FUNCTION") or "").strip()
        if fn:
            rec["functions"].add(fn)
        kr_id = (row.get("KR_ID") or "").strip()
        if kr_id:
            rec["work_ids"].add(kr_id)
        title = (row.get("title") or "").strip()
        if title:
            rec["work_titles"].add(title)
    for rec in authors.values():
        rec["functions"] = sorted(rec["functions"])
        rec["work_ids"] = sorted(rec["work_ids"])
        rec["work_titles"] = sorted(rec["work_titles"])
        rec["work_count"] = len(rec["work_ids"])
    return authors


def _skqs_rows_by_kr(skqs_rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in skqs_rows:
        kr_id = (row.get("KR_ID") or "").strip()
        if kr_id:
            out[kr_id].append(row)
    for kr_id in out:
        out[kr_id].sort(key=lambda r: int(r.get("author_index") or "0"))
    return out


def _resolve_from_work_p50(
    authors: dict[str, dict[str, Any]],
    *,
    skqs_by_kr: dict[str, list[dict[str, str]]],
    wikidata_sidecar: dict[str, dict[str, Any]],
) -> int:
    resolved = 0
    for kr_id, skqs_auth in skqs_by_kr.items():
        wd = wikidata_sidecar.get(kr_id) or {}
        wikidata_authors = wd.get("wikidata_authors") or []
        if not wikidata_authors:
            continue
        used: set[str] = set()
        for row in skqs_auth:
            name = (row.get("person_name") or "").strip()
            dynasty = (row.get("DYNASTY") or "").strip()
            fn = (row.get("FUNCTION") or "").strip()
            key = _author_key(name, dynasty)
            if key not in authors or authors[key].get("wikidata_qid"):
                continue
            qid = match_wikidata_author(name, fn, wikidata_authors, used_qids=used)
            if not qid:
                continue
            authors[key]["wikidata_qid"] = qid
            authors[key]["source"] = "work_p50"
            authors[key]["source_kr_id"] = kr_id
            used.add(qid)
            resolved += 1
    return resolved


def _lookup_person_pack(
    name: str,
    dynasty: str,
    *,
    by_name_dynasty: dict[str, dict[str, str]],
    by_name: dict[str, str],
) -> tuple[str, str]:
    for variant in person_name_match_variants(name):
        for alias in dynasty_lookup_labels(dynasty):
            hit = by_name_dynasty.get(_author_key(variant, alias))
            if hit:
                return hit["wikidata_qid"], "person_pack_dynasty"
        qid = (by_name.get(variant) or by_name.get(normalize_person_name(variant)) or "").strip()
        if qid:
            return qid, "person_pack_name"
    return "", ""


def _load_name_only_index(metadata_dir: Path) -> dict[str, str]:
    path = metadata_dir / "krp_author_wikidata_by_name.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (doc.get("entries") or {}).items() if k and v}


def _resolve_from_label_index(
    authors: dict[str, dict[str, Any]],
    *,
    by_name_dynasty: dict[str, dict[str, str]],
    by_name_only: dict[str, str],
    search_cache: dict[str, str],
) -> int:
    resolved = 0
    for rec in authors.values():
        if rec.get("wikidata_qid"):
            continue
        name = rec["person_name"]
        dynasty = rec["dynasty"]
        qid, source = _lookup_person_pack(
            name,
            dynasty,
            by_name_dynasty=by_name_dynasty,
            by_name=by_name_only,
        )
        if not qid:
            qid = lookup_cached(search_cache, name, dynasty)
            source = "wikidata_cache" if qid else ""
        if not qid:
            for variant in person_name_match_variants(name):
                qid = (by_name_only.get(variant) or by_name_only.get(normalize_person_name(variant)) or "").strip()
                if qid:
                    source = "wikidata_name_index"
                    break
        if qid:
            rec["wikidata_qid"] = qid
            rec["source"] = source
            resolved += 1
    return resolved


def _resolve_from_person_packs(
    authors: dict[str, dict[str, Any]],
    *,
    by_name_dynasty: dict[str, dict[str, str]],
    by_name: dict[str, str],
) -> int:
    resolved = 0
    for rec in authors.values():
        if rec.get("wikidata_qid"):
            continue
        qid, source = _lookup_person_pack(
            rec["person_name"],
            rec["dynasty"],
            by_name_dynasty=by_name_dynasty,
            by_name=by_name,
        )
        if qid:
            rec["wikidata_qid"] = qid
            rec["source"] = source
            resolved += 1
    return resolved


def _resolve_from_cbdb(
    authors: dict[str, dict[str, Any]],
    *,
    cbdb_index,
) -> int:
    if cbdb_index is None:
        return 0
    resolved = 0
    for rec in authors.values():
        if _has_authority(rec):
            continue
        qid, cbdb_id, source = cbdb_index.lookup(rec["person_name"], rec["dynasty"])
        if not cbdb_id:
            continue
        rec["wikidata_qid"] = qid
        rec["cbdb_id"] = cbdb_id
        rec["source"] = source
        resolved += 1
    return resolved


def _resolve_from_cbdb_text_authorship(
    authors: dict[str, dict[str, Any]],
    *,
    text_index,
) -> int:
    if text_index is None:
        return 0
    resolved = 0
    for rec in authors.values():
        if _has_authority(rec):
            continue
        titles = rec.get("work_titles") or []
        if not titles:
            continue
        qid, cbdb_id, source, note = text_index.lookup(rec["person_name"], rec["dynasty"], titles)
        if not cbdb_id:
            continue
        rec["wikidata_qid"] = qid
        rec["cbdb_id"] = cbdb_id
        rec["source"] = source
        if note:
            rec["note"] = note
        resolved += 1
    return resolved


def build_skqs_author_table(
    skqs_rows: list[dict[str, str]],
    *,
    wikidata_sidecar: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, str]] | None = None,
    person_pack_roots: list[Path] | None = None,
    metadata_dir: Path | None = None,
    search_cache: dict[str, str] | None = None,
    fetch_wikidata_labels: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    """Return resolved entries, stats, and full author scan (for unresolved report)."""
    authors = _scan_skqs_authors(skqs_rows)
    overrides = overrides or {}
    for key, override in overrides.items():
        if key not in authors:
            continue
        rec = authors[key]
        if override.get("wikidata_qid"):
            rec["wikidata_qid"] = override["wikidata_qid"]
        if override.get("cbdb_id"):
            rec["cbdb_id"] = override["cbdb_id"]
        if override.get("norbert_id"):
            rec["norbert_id"] = override["norbert_id"]
        if override.get("source"):
            rec["source"] = override["source"]
        if override.get("note"):
            rec["note"] = override["note"]

    skqs_by_kr = _skqs_rows_by_kr(skqs_rows)
    from_work = _resolve_from_work_p50(
        authors, skqs_by_kr=skqs_by_kr, wikidata_sidecar=wikidata_sidecar
    )

    roots = person_pack_roots if person_pack_roots is not None else _default_person_pack_roots()
    by_name_dynasty = load_persons_by_name_dynasty(roots)

    meta_dir = metadata_dir or (_plugin_root() / "data" / "metadata")
    cache = dict(search_cache or load_search_cache(meta_dir / "wikidata_person_search_cache.json"))
    # Seed cache from manual override Q-ids so aliases (e.g. 赵爽 for 趙君卿) resolve offline.
    override_qids = sorted({row["wikidata_qid"] for row in overrides.values() if row.get("wikidata_qid")})
    enrich_cache_from_qids(cache, override_qids)

    pack_by_name = load_persons_by_primary_name(roots)
    expanded_by_name = dict(pack_by_name)
    for name, qid in pack_by_name.items():
        for variant in person_name_match_variants(name):
            expanded_by_name.setdefault(variant, qid)
    by_name_only = _load_name_only_index(meta_dir)
    for name, qid in by_name_only.items():
        expanded_by_name.setdefault(name, qid)
        for variant in person_name_match_variants(name):
            expanded_by_name.setdefault(variant, qid)

    if fetch_wikidata_labels:
        unresolved_pairs = [
            (rec["person_name"], rec["dynasty"])
            for rec in authors.values()
            if not rec.get("wikidata_qid")
        ]
        populate_cache_for_authors(unresolved_pairs, cache, fetch_missing=True)

    from_labels = _resolve_from_label_index(
        authors,
        by_name_dynasty=by_name_dynasty,
        by_name_only=expanded_by_name,
        search_cache=cache,
    )

    cbdb_index = build_cbdb_person_index(
        plugin_root=_plugin_root(),
        wikidata_pack_roots=roots,
    )
    from_cbdb = _resolve_from_cbdb(authors, cbdb_index=cbdb_index)
    text_index = build_cbdb_text_author_index(
        plugin_root=_plugin_root(),
        person_index=cbdb_index,
    )
    from_cbdb_text = _resolve_from_cbdb_text_authorship(authors, text_index=text_index)

    if text_index is not None:
        for rec in authors.values():
            if _has_authority(rec):
                continue
            hints = text_index.suggest_authors_for_titles(
                rec.get("work_titles") or [],
                dynasty=rec["dynasty"],
                limit=3,
            )
            if hints:
                rec["cbdb_hint"] = "; ".join(
                    f"{h['title']}→{h['name']}(cbdb:{h['cbdb_id']})" for h in hints
                )

    resolved = [rec for rec in authors.values() if _has_authority(rec)]
    unresolved = [rec for rec in authors.values() if not _has_authority(rec)]
    by_source: dict[str, int] = defaultdict(int)
    for rec in resolved:
        by_source[str(rec.get("source") or "unknown")] += 1

    entries = {
        key: {
            "person_name": rec["person_name"],
            "dynasty": rec["dynasty"],
            "wikidata_qid": rec.get("wikidata_qid", ""),
            "cbdb_id": rec.get("cbdb_id", ""),
            "norbert_id": rec.get("norbert_id", ""),
            "source": rec.get("source", ""),
            "work_count": rec["work_count"],
            "functions": rec["functions"],
        }
        for key, rec in sorted(authors.items())
        if _has_authority(rec)
    }
    stats = {
        "skqs_rows": len(skqs_rows),
        "unique_authors": len(authors),
        "resolved": len(resolved),
        "unresolved": len(unresolved),
        "resolved_with_wikidata": sum(1 for rec in resolved if rec.get("wikidata_qid")),
        "resolved_with_cbdb_only": sum(
            1 for rec in resolved if rec.get("cbdb_id") and not rec.get("wikidata_qid")
        ),
        "resolved_with_norbert_only": sum(
            1
            for rec in resolved
            if rec.get("norbert_id") and not rec.get("wikidata_qid") and not rec.get("cbdb_id")
        ),
        "resolved_from_work_p50": from_work,
        "resolved_from_wikidata_labels": from_labels,
        "resolved_from_cbdb": from_cbdb,
        "resolved_from_cbdb_text": from_cbdb_text,
        "wikidata_search_cache_entries": len(cache),
        "ignored_author_names": sorted(SKQS_IGNORED_AUTHOR_NAMES),
        "manual_overrides": len(overrides),
        "by_source": dict(by_source),
    }
    return entries, stats, authors, cache


def write_skqs_author_artifacts(
    entries: dict[str, dict[str, Any]],
    stats: dict[str, Any],
    *,
    authors_full: dict[str, dict[str, Any]],
    out_dir: Path,
    generated_at: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generatedAt": generated_at,
        "stats": stats,
        "entries": entries,
    }
    out_json = out_dir / "krp_skqs_author_wikidata.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    unresolved = [rec for rec in authors_full.values() if not _has_authority(rec)]
    unresolved_csv = out_dir / "krp_skqs_author_wikidata_unresolved.csv"
    with unresolved_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "person_name",
                "dynasty",
                "work_count",
                "functions",
                "sample_kr_id",
                "qid",
                "cbdb_id",
                "norbert_id",
                "cbdb_hint",
            ],
        )
        writer.writeheader()
        for rec in sorted(unresolved, key=lambda r: (-r["work_count"], r["person_name"])):
            writer.writerow(
                {
                    "person_name": rec["person_name"],
                    "dynasty": rec["dynasty"],
                    "work_count": rec["work_count"],
                    "functions": ";".join(rec["functions"]),
                    "sample_kr_id": rec["work_ids"][0] if rec["work_ids"] else "",
                    "qid": "",
                    "cbdb_id": "",
                    "norbert_id": "",
                    "cbdb_hint": rec.get("cbdb_hint", ""),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-dir", type=Path, default=_sources_dir())
    parser.add_argument("--out-dir", type=Path, default=_plugin_root() / "data" / "metadata")
    parser.add_argument(
        "--sidecar",
        type=Path,
        default=None,
        help="krp_wikidata_by_kr_id.json (default: out-dir/krp_wikidata_by_kr_id.json)",
    )
    parser.add_argument(
        "--fetch-wikidata-labels",
        action="store_true",
        help="Query Wikidata search API for still-unresolved authors (needs network)",
    )
    args = parser.parse_args()

    skqs_csv = args.sources_dir / "skqs_org_authorship.csv"
    overrides_csv = args.sources_dir / "skqs_author_wikidata_overrides.csv"
    sidecar_path = args.sidecar or (args.out_dir / "krp_wikidata_by_kr_id.json")

    skqs_rows = _read_csv(skqs_csv)
    overrides = _load_overrides(overrides_csv)
    curated_csv = args.out_dir / "krp_skqs_author_wikidata_resolved.csv"
    unresolved_csv = args.out_dir / "krp_skqs_author_wikidata_unresolved.csv"
    curated, skipped_curated = _load_curated_resolved(curated_csv)
    curated_unresolved, skipped_unresolved = _load_curated_qids(
        unresolved_csv, source="curated"
    )
    norbert_csv = args.sources_dir / "skqs_author_norbert_overrides.csv"
    norbert_overrides = _load_norbert_overrides(norbert_csv)
    combined_overrides = {**overrides, **curated, **curated_unresolved}
    for key, row in norbert_overrides.items():
        if key in combined_overrides:
            combined_overrides[key].update(row)
        else:
            combined_overrides[key] = row
    skipped_curated = skipped_curated + skipped_unresolved

    wikidata_sidecar: dict[str, dict[str, Any]] = {}
    if sidecar_path.is_file():
        doc = json.loads(sidecar_path.read_text(encoding="utf-8"))
        wikidata_sidecar = doc.get("entries") or {}

    entries, stats, authors_full, cache = build_skqs_author_table(
        skqs_rows,
        wikidata_sidecar=wikidata_sidecar,
        overrides=combined_overrides,
        fetch_wikidata_labels=args.fetch_wikidata_labels,
    )
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    save_search_cache(
        args.out_dir / "wikidata_person_search_cache.json",
        cache,
        generated_at=generated_at,
    )
    write_skqs_author_artifacts(
        entries,
        stats,
        authors_full=authors_full,
        out_dir=args.out_dir,
        generated_at=generated_at,
    )

    print(f"SKQS authors: {stats['unique_authors']} unique name|dynasty rows")
    print(f"Resolved: {stats['resolved']} ({stats['by_source']})")
    print(f"Unresolved: {stats['unresolved']} → krp_skqs_author_wikidata_unresolved.csv")
    if curated or curated_unresolved:
        print(
            f"Curated Q-ids: {len(curated)} from {curated_csv.name}, "
            f"{len(curated_unresolved)} from {unresolved_csv.name}"
        )
    if skipped_curated:
        print(f"Skipped {len(skipped_curated)} curated rows (not valid Q-ids):")
        for line in skipped_curated[:5]:
            print(f"  - {line}")
    print(f"Wrote {args.out_dir / 'krp_skqs_author_wikidata.json'}")


if __name__ == "__main__":
    main()
