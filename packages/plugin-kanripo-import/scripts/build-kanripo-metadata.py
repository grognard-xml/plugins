#!/usr/bin/env python3
"""
Build bundled Kanripo work metadata for plugin-kanripo-import.

Reads bundled CSVs under ``data/metadata/sources/`` and ``data/concordance/``.
When a KR_ID maps to a DZID, full Daozang metadata (all authors, vols, dates)
is merged in from ``dz_metadata_*`` tables.

Output: data/metadata/krp_works_by_id.json + manifest.json,
plus data/krp_works.json (the slim index the import window searches)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "python"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

from kanripo_import.authorship_wikidata import enrich_authorship_rows
from kanripo_import.edition import resolve_edition
from wikidata_pack_index import enrich_from_pack, load_persons_by_primary_name, load_works_by_qid
from wikidata_work_authors import authors_for_work_record, fetch_authors_for_work_qids

# Import SKQS author table builder (same scripts/ dir).
from build_skqs_author_wikidata import build_skqs_author_table, write_skqs_author_artifacts

_DATES_RE = re.compile(r"^\s*(-?\d+)\s*-\s*(-?\d+)\s*$")
_EXTENT_RE = re.compile(r"(\d+)")


def _plugin_root() -> Path:
    return _PLUGIN_ROOT


def _sources_dir() -> Path:
    return _plugin_root() / "data" / "metadata" / "sources"


def _concordance_dir() -> Path:
    return _plugin_root() / "data" / "concordance"


def _rel_source(path: Path) -> str:
    try:
        return path.relative_to(_plugin_root()).as_posix()
    except ValueError:
        return path.name


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(f)]


def _parse_extent(extent: str) -> str:
    s = (extent or "").strip()
    if not s:
        return ""
    m = _EXTENT_RE.search(s)
    return m.group(1) if m else s


def _parse_dates(dates: str) -> tuple[str, str, str]:
    s = (dates or "").strip()
    if not s:
        return "", "", ""
    m = _DATES_RE.match(s)
    if m:
        return s, m.group(1), m.group(2)
    return s, "", ""


def _person_id_str(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _dzid_norm(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not s:
        return ""
    if s.startswith("DZ"):
        return s
    if s.replace(".", "", 1).isdigit() or s.isdigit():
        return f"DZ{int(float(s)):04d}"
    return s


def _vols_str(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    return _parse_extent(s) or s


def _load_normalized_hints(path: Path) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    by_dzid: dict[str, dict] = {}
    by_author: dict[tuple[str, str], dict] = {}
    if not path.is_file():
        return by_dzid, by_author
    for row in _read_csv(path):
        raw_dz = (row.get("docclass") or "").strip()
        if not raw_dz.upper().startswith("DZ"):
            continue
        dzid = _dzid_norm(raw_dz)
        author = (row.get("metadata/Name") or row.get("author") or "").strip()
        hint = {
            "time_dynasty": (row.get("time_dynasty") or "").strip(),
            "date_not_before": (row.get("date_not_before") or "").strip(),
            "date_not_after": (row.get("date_not_after") or "").strip(),
            "author_dates": (row.get("metadata/AuthorDates") or "").strip(),
        }
        if dzid and dzid not in by_dzid and any(hint.values()):
            by_dzid[dzid] = hint
        if dzid and author:
            by_author[(dzid, author)] = hint
    return by_dzid, by_author


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


def _attach_wikidata_authors(
    entries: dict[str, dict],
    *,
    authors_by_qid: dict[str, list[dict]],
) -> int:
    """Store P50/P98 author rows on each entry's wikidata block."""
    attached = 0
    for entry in entries.values():
        wd = entry.get("wikidata")
        if not isinstance(wd, dict):
            continue
        authors = authors_for_work_record(
            str(wd.get("work_qid") or ""),
            str(wd.get("edition_qid") or ""),
            authors_by_qid=authors_by_qid,
        )
        if authors:
            wd["wikidata_authors"] = authors
            attached += 1
    return attached


def _enrich_authorship_wikidata(
    entries: dict[str, dict],
    *,
    persons_by_name: dict[str, str],
    skqs_authors: dict[str, str] | None = None,
    skqs_authorities: dict[str, dict[str, str]] | None = None,
) -> int:
    """Attach ``wikidata_qid`` / ``cbdb_id`` via work P50/P98, SKQS table, then person-pack lookup."""
    enriched = 0
    skqs_authors = skqs_authors or {}
    skqs_authorities = skqs_authorities or {}
    for entry in entries.values():
        wd = entry.get("wikidata") if isinstance(entry.get("wikidata"), dict) else {}
        enriched += enrich_authorship_rows(
            entry.get("authorship") or [],
            wikidata_authors=wd.get("wikidata_authors") or [],
            skqs_authors=skqs_authors,
            skqs_authorities=skqs_authorities,
            persons_by_name=persons_by_name,
        )
    return enriched


def _default_wikidata_pack_path() -> Path | None:
    """Locate work-zh-hant authority pack when building inside the LJB monorepo."""
    root = _plugin_root()
    candidates = [
        root.parents[2] / "authoritypacks" / "packs" / "wikidata" / "work-zh-hant" / "works.ndjson",
        root.parents[3] / "authoritypacks" / "packs" / "wikidata" / "work-zh-hant" / "works.ndjson",
    ]
    env = os.environ.get("LJB_WIKIDATA_WORK_PACK", "").strip()
    if env:
        candidates.insert(0, Path(env))
    for path in candidates:
        if path.is_file():
            return path
    return None


def _ws_page_url(page: str) -> str:
    title = (page or "").strip().replace(" ", "_")
    return f"https://zh.wikisource.org/wiki/{quote(title, safe='')}"


def _load_krp_wikidata_qids(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    by_kr = doc.get("by_kr_id") or doc
    if not isinstance(by_kr, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for kr_id, row in by_kr.items():
        if isinstance(row, dict):
            out[str(kr_id).strip()] = row
    return out


def _merge_wikidata_crossref(
    entries: dict[str, dict],
    *,
    qids_by_kr: dict[str, dict[str, str]],
    pack_by_qid: dict[str, dict],
) -> int:
    merged = 0
    for kr_id, qrow in qids_by_kr.items():
        entry = entries.get(kr_id)
        if not entry:
            continue
        work_qid = (qrow.get("work_qid") or "").strip()
        edition_qid = (qrow.get("edition_qid") or "").strip()
        ws_page = (qrow.get("ws_page") or "").strip()
        wd = {
            "work_qid": work_qid,
            "edition_qid": edition_qid,
            "wikidata_work_qid": (qrow.get("wikidata_work_qid") or work_qid or edition_qid).strip(),
            "ws_page": ws_page,
            "ws_url": _ws_page_url(ws_page) if ws_page else "",
            "match_tier": (qrow.get("match_tier") or "").strip(),
            "corpus_title": (qrow.get("corpus_title") or "").strip(),
        }
        pack_row = pack_by_qid.get(work_qid) or pack_by_qid.get(edition_qid)
        if pack_row:
            enrich_from_pack(entry, pack_row=pack_row)
            meta = pack_row.get("metadata") or {}
            if pack_row.get("primaryName"):
                wd["primary_name"] = pack_row["primaryName"]
            if pack_row.get("searchStrings"):
                wd["aliases"] = list(pack_row["searchStrings"])
            if meta.get("startYear") is not None:
                wd["start_year"] = meta["startYear"]
            if meta.get("endYear") is not None:
                wd["end_year"] = meta["endYear"]
            if meta.get("description"):
                wd["description"] = meta["description"]
        entry["wikidata"] = wd
        merged += 1
    return merged


def _extract_wikidata_sidecar(entries: dict[str, dict]) -> dict[str, dict]:
    """Move wikidata blocks out of work entries into a separate runtime lookup."""
    sidecar: dict[str, dict] = {}
    for kr_id, entry in entries.items():
        wd = entry.pop("wikidata", None)
        if isinstance(wd, dict) and wd.get("wikidata_work_qid"):
            sidecar[kr_id] = wd
    return sidecar


def _build_parallel_sources(
    entries: dict[str, dict],
    *,
    daozang_map: dict[str, dict],
) -> dict[str, dict]:
    """KRP → bundled Daozang punctuation paths only (Wikisource comes from wikidata sidecar at runtime)."""
    out: dict[str, dict] = {}
    for kr_id, entry in entries.items():
        dz = daozang_map.get(kr_id) or {}
        rel = (dz.get("daozang_rel_path") or "").strip()
        if not rel:
            continue
        out[kr_id] = {
            "kr_id": kr_id,
            "sources": [
                {
                    "kind": "daozang",
                    "label": (dz.get("daozang_title") or dz.get("title") or rel).strip(),
                    "rel_path": rel,
                    "dz_id": (dz.get("dz_id") or entry.get("dzid") or "").strip(),
                }
            ],
        }
    return out


def sync_sources(*, metadata_root: Path, sources: Path) -> None:
    tables = metadata_root / "tables_output"
    copies = {
        "krp_works.csv": tables / "krp_works.csv",
        "skqs_org_authorship.csv": tables / "skqs_org_authorship.csv",
        "dz_metadata_works.csv": tables / "dz_metadata_works.csv",
        "dz_metadata_authors.csv": tables / "dz_metadata_authors.csv",
    }
    sources.mkdir(parents=True, exist_ok=True)
    for dest_name, src in copies.items():
        if not src.is_file():
            raise SystemExit(f"Missing upstream table: {src}")
        shutil.copy2(src, sources / dest_name)
        print(f"Synced {_rel_source(sources / dest_name)}")
    norm_src = metadata_root.parent / "Corpora" / "DaoCanon_txt_chm" / "DZ_metadata_normalized.csv"
    if not norm_src.is_file():
        norm_src = tables / "DZ_metadata_normalized.csv"
    if norm_src.is_file():
        shutil.copy2(norm_src, sources / "DZ_metadata_normalized.csv")
        print(f"Synced {_rel_source(sources / 'DZ_metadata_normalized.csv')}")
    qid_src = metadata_root / "tables_output" / "wikidata_explore" / "krp_wikidata_qids.json"
    if qid_src.is_file():
        shutil.copy2(qid_src, sources / "krp_wikidata_qids.json")
        print(f"Synced {_rel_source(sources / 'krp_wikidata_qids.json')}")


def _load_org_by_kr(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        kr_id = (row.get("KR_ID") or "").strip()
        if not kr_id:
            continue
        cbeta = (row.get("CBETA_ID") or "").strip()
        dzid = _dzid_norm(row.get("DZID") or "")
        if kr_id not in out:
            out[kr_id] = {"cbeta_id": cbeta, "dzid": dzid}
        elif cbeta and not out[kr_id]["cbeta_id"]:
            out[kr_id]["cbeta_id"] = cbeta
        if dzid and not out[kr_id]["dzid"]:
            out[kr_id]["dzid"] = dzid
    return out


def _load_dz_authors_by_dz(
    rows: list[dict[str, str]],
    *,
    norm_by_author: dict[tuple[str, str], dict],
) -> dict[str, list[dict[str, str]]]:
    by_dz: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        dzid = _dzid_norm(row.get("dzid") or "")
        if not dzid:
            continue
        name = (row.get("person_name") or "").strip()
        ah = norm_by_author.get((dzid, name), {})
        by_dz[dzid].append(
            {
                "author_index": (row.get("author_index") or "").strip(),
                "person_name": name,
                "person_id": _person_id_str(row.get("person_id") or ""),
                "function": (row.get("FUNCTION") or "").strip(),
                "time_dynasty": ah.get("time_dynasty", ""),
                "author_dates": ah.get("author_dates", ""),
                "date_not_before": ah.get("date_not_before", ""),
                "date_not_after": ah.get("date_not_after", ""),
            }
        )
    for dzid in by_dz:
        by_dz[dzid].sort(key=lambda r: int(r.get("author_index") or "0"))
    return by_dz


def _load_dz_works_by_dz(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        dzid = _dzid_norm(row.get("dzid") or "")
        if dzid and dzid not in out:
            out[dzid] = row
    return out


def _authorship_from_skqs(rows: list[dict[str, str]], kr_id: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for a in rows:
        dates, nb, na = _parse_dates(a.get("DATES") or "")
        out.append(
            {
                "author_index": (a.get("author_index") or "").strip(),
                "person_name": (a.get("person_name") or "").strip(),
                "person_id": "",
                "function": (a.get("FUNCTION") or "").strip(),
                "time_dynasty": (a.get("DYNASTY") or "").strip(),
                "author_dates": dates,
                "date_not_before": nb,
                "date_not_after": na,
                "source": "skqs",
            }
        )
    return out


def _merge_authorship(
    skqs_auth: list[dict[str, str]],
    dz_auth: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not skqs_auth:
        return [{k: v for k, v in a.items() if k != "source"} for a in dz_auth]
    if not dz_auth:
        return [{k: v for k, v in a.items() if k != "source"} for a in skqs_auth]

    dz_by_name = {a["person_name"]: a for a in dz_auth if a.get("person_name")}
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in skqs_auth:
        name = a.get("person_name") or ""
        dz = dz_by_name.get(name, {})
        merged.append(
            {
                "author_index": a.get("author_index") or dz.get("author_index") or "",
                "person_name": name,
                "person_id": a.get("person_id") or dz.get("person_id") or "",
                "function": a.get("function") or dz.get("function") or "",
                "time_dynasty": a.get("time_dynasty") or dz.get("time_dynasty") or "",
                "author_dates": a.get("author_dates") or dz.get("author_dates") or "",
                "date_not_before": a.get("date_not_before") or dz.get("date_not_before") or "",
                "date_not_after": a.get("date_not_after") or dz.get("date_not_after") or "",
            }
        )
        if name:
            seen.add(name)

    for a in dz_auth:
        name = a.get("person_name") or ""
        if name and name not in seen:
            merged.append({k: v for k, v in a.items() if k != "source"})
            seen.add(name)

    merged.sort(key=lambda r: int(r.get("author_index") or "0") or 999)
    for i, row in enumerate(merged, start=1):
        if not row.get("author_index"):
            row["author_index"] = str(i)
    return merged


def build_entries(
    *,
    works: list[dict[str, str]],
    skqs: list[dict[str, str]],
    org_by_kr: dict[str, dict[str, str]],
    kr_to_dz: dict[str, str],
    dz_authors_by_dz: dict[str, list[dict[str, str]]],
    dz_works_by_dz: dict[str, dict[str, str]],
    norm_by_dzid: dict[str, dict],
) -> dict[str, dict]:
    skqs_by_kr: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in skqs:
        kr_id = (row.get("KR_ID") or "").strip()
        if kr_id:
            skqs_by_kr[kr_id].append(row)
    for kr_id in skqs_by_kr:
        skqs_by_kr[kr_id].sort(key=lambda r: int(r.get("author_index") or "0"))

    out: dict[str, dict] = {}
    for row in works:
        kr_id = (row.get("KR_ID") or "").strip()
        if not kr_id:
            continue
        title = (row.get("text_title") or "").strip()
        juan_count = str(row.get("files") or "").strip()
        if juan_count.endswith(".0"):
            juan_count = juan_count[:-2]

        skqs_rows = skqs_by_kr.get(kr_id, [])
        org = org_by_kr.get(kr_id, {})
        dzid = org.get("dzid") or kr_to_dz.get(kr_id, "")
        dzid = _dzid_norm(dzid)
        dz_auth = dz_authors_by_dz.get(dzid, []) if dzid else []
        dz_work = dz_works_by_dz.get(dzid, {}) if dzid else {}
        dz_hint = norm_by_dzid.get(dzid, {}) if dzid else {}

        skqs_auth = _authorship_from_skqs(skqs_rows, kr_id)
        authorship = _merge_authorship(skqs_auth, dz_auth)

        source = (skqs_rows[0].get("SOURCE") or "").strip() if skqs_rows else ""
        if not source and dzid:
            source = "正統道藏 Zhengtong Daozang"

        extent = ""
        if skqs_rows:
            extent = _parse_extent(skqs_rows[0].get("EXTENT") or "")
            if not title:
                title = (skqs_rows[0].get("title") or "").strip()
        if not extent and dz_work:
            extent = _vols_str(dz_work.get("vols") or "")
        if not extent and juan_count:
            extent = juan_count
        if not title and dz_work:
            title = (dz_work.get("title") or "").strip()

        dynasty = (row.get("DYNASTY") or "").strip()
        if not dynasty and authorship:
            dynasty = authorship[0].get("time_dynasty") or ""
        if not dynasty:
            dynasty = dz_hint.get("time_dynasty") or ""

        work_dates = dz_hint.get("author_dates") or ""
        work_nb = dz_hint.get("date_not_before") or ""
        work_na = dz_hint.get("date_not_after") or ""
        for a in authorship:
            if a.get("author_dates"):
                work_dates = a["author_dates"]
                work_nb = a.get("date_not_before") or ""
                work_na = a.get("date_not_after") or ""
                break

        edition = resolve_edition(source=source)

        out[kr_id] = {
            "kr_id": kr_id,
            "title": title,
            "vols": extent,
            "juan_count": juan_count,
            "source": source,
            "edition_profile": edition.edition_profile,
            "edition_label": edition.edition_label,
            "edition_date": edition.edition_date,
            "source_locator": edition.source_locator,
            "cbeta_id": org.get("cbeta_id") or "",
            "dzid": dzid,
            "time_dynasty": dynasty,
            "date_not_before": work_nb,
            "date_not_after": work_na,
            "author_dates": work_dates,
            "authorship": authorship,
            "metadata_sources": {
                "skqs": bool(skqs_rows),
                "daozang": bool(dzid),
            },
        }
    return out



def _load_kr_classification() -> tuple[dict[str, str], dict[str, str]]:
    """Part and class labels from the upstream KR-Catalog.

    Refresh with ``scripts/fetch-kr-classification.py``.
    """
    path = _sources_dir() / "kr_classification.json"
    if not path.is_file():
        raise SystemExit(
            f"Missing {path.name}. Run: python3 scripts/fetch-kr-classification.py"
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get("parts") or {}, doc.get("classes") or {}


def kr_section(kr_id: str, parts: dict[str, str], classes: dict[str, str]) -> str:
    """e.g. KR1a0030 -> 經部・易類. Falls back to the part alone when the class is
    not in the catalogue (KR2p has works here but no upstream heading)."""
    part = parts.get(kr_id[:3], "")
    klass = classes.get(kr_id[:4], "")
    if part and klass:
        return f"{part}・{klass}"
    return part or klass


def format_authors(entry: dict) -> str:
    parts = []
    for record in entry.get("authorship") or []:
        name = (record.get("person_name") or "").strip()
        if not name:
            continue
        function = (record.get("function") or "").strip()
        parts.append(f"{name}（{function}）" if function else name)
    return "、".join(parts)


def entry_dynasty(entry: dict) -> str:
    dynasty = (entry.get("time_dynasty") or "").strip()
    if dynasty:
        return dynasty
    for record in entry.get("authorship") or []:
        if (record.get("time_dynasty") or "").strip():
            return record["time_dynasty"].strip()
    return ""


def write_search_index(entries: dict[str, dict]) -> list[dict[str, str]]:
    """The slim, pre-joined index read by the desktop search."""
    parts, classes = _load_kr_classification()
    rows = [
        {
            "id": kr_id,
            "section": kr_section(kr_id, parts, classes),
            "title": (entry.get("title") or "").strip(),
            "dynasty": entry_dynasty(entry),
            "authors": format_authors(entry),
            "dzid": (entry.get("dzid") or "").strip(),
        }
        for kr_id, entry in entries.items()
    ]
    rows.sort(key=lambda row: row["id"])
    (_plugin_root() / "data" / "krp_works.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-dir", type=Path, default=_sources_dir())
    parser.add_argument(
        "--sync-from",
        type=Path,
        metavar="METADATA_ROOT",
        help="Copy tables from chinese_corpus_metadata before build (maintainers only)",
    )
    parser.add_argument(
        "--wikidata-pack",
        type=Path,
        default=None,
        help="Path to wikidata/work-zh-hant/works.ndjson (optional enrichment)",
    )
    parser.add_argument("--out-dir", type=Path, default=_plugin_root() / "data" / "metadata")
    parser.add_argument(
        "--skip-wikidata-fetch",
        action="store_true",
        help="Skip live Wikidata API fetch for work P50/P98 (offline rebuild)",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Rewrite data/krp_works.json from the existing metadata, without rebuilding it "
        "(the full build needs the optional Wikidata pack to preserve its enrichment)",
    )
    args = parser.parse_args()

    if args.index_only:
        entries = json.loads(
            (args.out_dir / "krp_works_by_id.json").read_text(encoding="utf-8")
        )["entries"]
        rows = write_search_index(entries)
        print(f"Wrote {len(rows)} search index rows to data/krp_works.json")
        return

    if args.sync_from:
        sync_sources(metadata_root=args.sync_from, sources=args.sources_dir)

    works_csv = args.sources_dir / "krp_works.csv"
    skqs_csv = args.sources_dir / "skqs_org_authorship.csv"
    dz_works_csv = args.sources_dir / "dz_metadata_works.csv"
    dz_authors_csv = args.sources_dir / "dz_metadata_authors.csv"
    normalized_csv = args.sources_dir / "DZ_metadata_normalized.csv"
    org_csv = _concordance_dir() / "kanripo_org_concordance.csv"
    dz_collation_csv = _concordance_dir() / "krp_dz_collation.csv"
    required = (works_csv, skqs_csv, dz_works_csv, dz_authors_csv, org_csv, dz_collation_csv)
    for p in required:
        if not p.is_file():
            raise SystemExit(
                f"Missing bundled source: {_rel_source(p)}. "
                "Run --sync-from and build:concordance first."
            )

    norm_by_dzid, norm_by_author = _load_normalized_hints(normalized_csv)
    kr_to_dz = {
        (row.get("KR_ID") or "").strip(): _dzid_norm(row.get("DZID") or "")
        for row in _read_csv(dz_collation_csv)
        if (row.get("KR_ID") or "").strip()
    }

    entries = build_entries(
        works=_read_csv(works_csv),
        skqs=_read_csv(skqs_csv),
        org_by_kr=_load_org_by_kr(_read_csv(org_csv)),
        kr_to_dz=kr_to_dz,
        dz_authors_by_dz=_load_dz_authors_by_dz(
            _read_csv(dz_authors_csv), norm_by_author=norm_by_author
        ),
        dz_works_by_dz=_load_dz_works_by_dz(_read_csv(dz_works_csv)),
        norm_by_dzid=norm_by_dzid,
    )

    person_roots = _default_person_pack_roots()
    persons_by_name = load_persons_by_primary_name(person_roots)

    qids_path = args.sources_dir / "krp_wikidata_qids.json"
    qids_by_kr = _load_krp_wikidata_qids(qids_path)
    pack_path = args.wikidata_pack or _default_wikidata_pack_path()
    wanted_qids: set[str] = set()
    for row in qids_by_kr.values():
        for key in ("work_qid", "edition_qid", "wikidata_work_qid"):
            q = (row.get(key) or "").strip()
            if q:
                wanted_qids.add(q)
    pack_by_qid = load_works_by_qid(pack_path, wanted_qids=wanted_qids) if pack_path else {}
    wd_merged = _merge_wikidata_crossref(entries, qids_by_kr=qids_by_kr, pack_by_qid=pack_by_qid)
    if pack_path:
        print(f"Wikidata authority pack: {_rel_source(pack_path)} ({len(pack_by_qid)} Q-ids loaded)")
    else:
        print("Wikidata authority pack: not found (skip --wikidata-pack or set LJB_WIKIDATA_WORK_PACK)")

    work_qids: list[str] = []
    for entry in entries.values():
        wd = entry.get("wikidata") if isinstance(entry.get("wikidata"), dict) else {}
        for key in ("work_qid", "edition_qid", "wikidata_work_qid"):
            qid = (wd.get(key) or "").strip()
            if qid:
                work_qids.append(qid)
    authors_by_qid: dict[str, list[dict]] = {}
    if not args.skip_wikidata_fetch and work_qids:
        authors_by_qid = fetch_authors_for_work_qids(work_qids)
        print(f"Wikidata work authors: fetched P50/P98 for {len(authors_by_qid)} work/edition Q-ids")
    elif args.skip_wikidata_fetch:
        print("Wikidata work authors: skipped (--skip-wikidata-fetch)")
    wd_authors_attached = _attach_wikidata_authors(entries, authors_by_qid=authors_by_qid)

    wikidata_sidecar_preview = {
        kr_id: entry["wikidata"]
        for kr_id, entry in entries.items()
        if isinstance(entry.get("wikidata"), dict) and entry["wikidata"].get("wikidata_work_qid")
    }
    overrides_path = args.sources_dir / "skqs_author_wikidata_overrides.csv"
    overrides: dict[str, dict[str, str]] = {}
    if overrides_path.is_file():
        from build_skqs_author_wikidata import _load_overrides

        overrides = _load_overrides(overrides_path)
    skqs_entries, skqs_stats, skqs_authors_full, _skqs_cache = build_skqs_author_table(
        _read_csv(skqs_csv),
        wikidata_sidecar=wikidata_sidecar_preview,
        overrides=overrides,
        person_pack_roots=person_roots,
    )
    skqs_index = {key: row["wikidata_qid"] for key, row in skqs_entries.items() if row.get("wikidata_qid")}
    skqs_authorities = {
        key: {
            "wikidata_qid": row.get("wikidata_qid", ""),
            "cbdb_id": row.get("cbdb_id", ""),
            "norbert_id": row.get("norbert_id", ""),
        }
        for key, row in skqs_entries.items()
    }

    auth_wd_enriched = _enrich_authorship_wikidata(
        entries,
        persons_by_name=persons_by_name,
        skqs_authors=skqs_index,
        skqs_authorities=skqs_authorities,
    )
    if person_roots:
        print(
            f"Wikidata person packs: {len(person_roots)} root(s), "
            f"{len(persons_by_name)} names indexed"
        )
    else:
        print("Wikidata person packs: not found (name fallback only if index bundled)")
    print(
        f"Authorship Wikidata links: {auth_wd_enriched} rows enriched "
        f"({wd_authors_attached} works with wikidata_authors from P50/P98)"
    )
    print(
        f"SKQS author table: {skqs_stats['resolved']}/{skqs_stats['unique_authors']} resolved "
        f"({skqs_stats['by_source']})"
    )

    daozang_map_path = _concordance_dir() / "kanripo_daozang_map.json"
    daozang_raw: dict[str, dict] = {}
    if daozang_map_path.is_file():
        daozang_raw = json.loads(daozang_map_path.read_text(encoding="utf-8")).get("entries") or {}
    parallel_sources = _build_parallel_sources(entries, daozang_map=daozang_raw)
    concordance_out = _concordance_dir() / "krp_parallel_sources.json"
    concordance_out.parent.mkdir(parents=True, exist_ok=True)
    parallel_payload = {
        "version": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "entryCount": len(parallel_sources),
        "entries": parallel_sources,
    }
    concordance_out.write_text(
        json.dumps(parallel_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    write_skqs_author_artifacts(
        skqs_entries,
        skqs_stats,
        authors_full=skqs_authors_full,
        out_dir=out,
        generated_at=generated_at,
    )

    with_auth = sum(1 for e in entries.values() if e.get("authorship"))
    multi_auth = sum(1 for e in entries.values() if len(e.get("authorship") or []) > 1)
    with_dz = sum(1 for e in entries.values() if e.get("dzid"))
    with_dynasty = sum(1 for e in entries.values() if e.get("time_dynasty"))
    with_dates = sum(
        1
        for e in entries.values()
        if e.get("author_dates") or e.get("date_not_before")
    )
    with_pid = sum(
        1
        for e in entries.values()
        for a in e.get("authorship") or []
        if a.get("person_id")
    )
    with_auth_wd = sum(
        1
        for e in entries.values()
        for a in e.get("authorship") or []
        if a.get("wikidata_qid")
    )
    with_wd = sum(1 for e in entries.values() if (e.get("wikidata") or {}).get("wikidata_work_qid"))
    with_wd_primary = sum(1 for e in entries.values() if (e.get("wikidata") or {}).get("primary_name"))
    with_wd_aliases = sum(
        1 for e in entries.values() if (e.get("wikidata") or {}).get("aliases")
    )
    with_wd_desc = sum(1 for e in entries.values() if (e.get("wikidata") or {}).get("description"))
    with_edition_label = sum(1 for e in entries.values() if (e.get("edition_label") or "").strip())

    wikidata_by_kr = _extract_wikidata_sidecar(entries)

    payload = {
        "version": 1,
        "generatedAt": generated_at,
        "entryCount": len(entries),
        "sources": {
            "krp_works": _rel_source(works_csv),
            "skqs_org_authorship": _rel_source(skqs_csv),
            "dz_metadata_works": _rel_source(dz_works_csv),
            "dz_metadata_authors": _rel_source(dz_authors_csv),
            "dz_metadata_normalized": _rel_source(normalized_csv)
            if normalized_csv.is_file()
            else None,
            "kanripo_org_concordance": _rel_source(org_csv),
            "krp_dz_collation": _rel_source(dz_collation_csv),
            "krp_wikidata_qids": _rel_source(qids_path) if qids_path.is_file() else None,
            "wikidata_work_pack": str(pack_path) if pack_path else None,
        },
        "entries": entries,
    }
    (out / "krp_works_by_id.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    wikidata_payload = {
        "version": 1,
        "generatedAt": generated_at,
        "entryCount": len(wikidata_by_kr),
        "entries": wikidata_by_kr,
    }
    (out / "krp_wikidata_by_kr_id.json").write_text(
        json.dumps(wikidata_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    author_wikidata_payload = {
        "version": 1,
        "generatedAt": generated_at,
        "entryCount": len(persons_by_name),
        "entries": persons_by_name,
        "note": "Legacy name-only fallback for non-SKQS authors; prefer krp_skqs_author_wikidata.json",
    }
    (out / "krp_author_wikidata_by_name.json").write_text(
        json.dumps(author_wikidata_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "packKind": "ljb-kanripo-metadata",
        "generatedAt": generated_at,
        "stats": {
            "works": len(entries),
            "with_dzid": with_dz,
            "with_authorship": with_auth,
            "multi_author_works": multi_auth,
            "with_time_dynasty": with_dynasty,
            "with_author_dates": with_dates,
            "with_edition_label": with_edition_label,
            "authorship_with_person_id": with_pid,
            "authorship_with_wikidata_qid": with_auth_wd,
            "with_wikidata_qid": with_wd,
            "wikidata_crossref_merged": wd_merged,
            "wikidata_pack_qids_loaded": len(pack_by_qid),
            "wikidata_with_primary_name": with_wd_primary,
            "wikidata_with_aliases": with_wd_aliases,
            "wikidata_with_description": with_wd_desc,
            "parallel_daozang_bundled": len(parallel_sources),
            "parallel_wikisource_from_wikidata": sum(
                1
                for wd in wikidata_by_kr.values()
                if (wd.get("ws_url") or "").strip() and (wd.get("ws_page") or "").strip()
            ),
            "skqs_authors_resolved": skqs_stats.get("resolved"),
            "skqs_authors_unresolved": skqs_stats.get("unresolved"),
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    search_index = write_search_index(entries)

    print(f"Wrote {len(entries)} work metadata entries to {out}")
    print(
        f"  search index: {len(search_index)} rows; "
        f"with section: {sum(1 for row in search_index if row['section'])}"
    )
    print(
        f"  with DZID: {with_dz}; multi-author: {multi_auth}; "
        f"dynasty: {with_dynasty}; person_id rows: {with_pid}; "
        f"wikidata Q-id: {with_wd}; pack enriched: primary={with_wd_primary}, "
        f"aliases={with_wd_aliases}, description={with_wd_desc}; "
        f"parallel: daozang bundled={len(parallel_sources)}, "
        f"wikisource via wikidata={sum(1 for wd in wikidata_by_kr.values() if (wd.get('ws_url') or '').strip())}"
    )


if __name__ == "__main__":
    main()
