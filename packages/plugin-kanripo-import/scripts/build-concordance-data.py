#!/usr/bin/env python3
"""
Build bundled Kanripo ↔ Daozang concordance data for plugin-kanripo-import.

Reads upstream tables from chinese_corpus_metadata (and optional dz_krp curated
index), verifies Daozang corpus rel_paths, and writes:

  data/concordance/krp_dz_collation.csv
  data/concordance/kanripo_org_concordance.csv
  data/concordance/dz_corpus_works.csv
  data/concordance/duren_jing_index.csv
  data/concordance/kanripo_daozang_overrides.csv  (created if missing)
  data/concordance/kanripo_daozang_map.json
  data/concordance/manifest.json

Run from plugin package root::

    python scripts/build-concordance-data.py

Override upstream paths with env vars or flags (see --help).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

_DZ_PREFIX_RE = re.compile(r"^DZ\d+_", re.IGNORECASE)


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_metadata_root() -> Path:
    return _plugin_root().parents[3] / "chinese_corpus_metadata"


def _default_dz_krp_root() -> Path:
    return _plugin_root().parents[3] / "dz_krp"


def _strip_dz_filename_prefix(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    return _DZ_PREFIX_RE.sub("", s)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(f)]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _load_daozang_rel_paths(daozang_index: Path) -> dict[str, dict]:
    entries = json.loads(daozang_index.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for e in entries:
        rel = (e.get("rel_path") or "").strip()
        if rel:
            out[rel] = e
    return out


def _load_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    rows = _read_csv_rows(path)
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        kr_id = (row.get("kr_id") or "").strip()
        rel = (row.get("daozang_rel_path") or "").strip()
        if kr_id and rel:
            out[kr_id] = row
    return out


def _dzid_norm(dz_id: str) -> str:
    s = (dz_id or "").strip().upper()
    if not s:
        return ""
    if s.startswith("DZ"):
        return s
    if s.isdigit():
        return f"DZ{int(s):04d}"
    return s


def build_map(
    *,
    krp_dz_rows: list[dict[str, str]],
    dz_work_rows: list[dict[str, str]],
    duren_rows: list[dict[str, str]],
    daozang_by_rel: dict[str, dict],
    overrides: dict[str, dict[str, str]],
) -> dict[str, dict]:
    dzid_to_file: dict[str, str] = {}
    dzid_to_title: dict[str, str] = {}
    for row in dz_work_rows:
        dzid = _dzid_norm(row.get("dzid") or row.get("DZID") or "")
        fn = (row.get("file_name") or "").strip()
        if dzid and fn:
            dzid_to_file[dzid] = fn
            dzid_to_title[dzid] = (row.get("title") or "").strip()

    entries: dict[str, dict] = {}

    def _add(
        kr_id: str,
        *,
        dz_id: str,
        rel_path: str,
        match_method: str,
        title: str = "",
        note: str = "",
    ) -> None:
        if not kr_id or not rel_path:
            return
        if rel_path not in daozang_by_rel:
            return
        entries[kr_id] = {
            "kr_id": kr_id,
            "dz_id": dz_id,
            "daozang_rel_path": rel_path,
            "daozang_title": (daozang_by_rel[rel_path].get("title") or "").strip(),
            "match_method": match_method,
            "title": title,
            "note": note,
        }

    for row in krp_dz_rows:
        kr_id = (row.get("KR_ID") or "").strip()
        dz_id = _dzid_norm(row.get("DZID") or "")
        rel = dzid_to_file.get(dz_id, "")
        _add(
            kr_id,
            dz_id=dz_id,
            rel_path=rel,
            match_method=(row.get("file_name_match") or "krp_dz_collation").strip(),
            title=(row.get("title") or dzid_to_title.get(dz_id, "")).strip(),
        )

    for row in duren_rows:
        kr_id = (row.get("krp_id") or "").strip()
        dz_id = _dzid_norm(row.get("dz_id") or "")
        raw_path = (row.get("dz_path") or "").strip()
        rel = _strip_dz_filename_prefix(raw_path)
        _add(
            kr_id,
            dz_id=dz_id,
            rel_path=rel,
            match_method="duren_jing_index",
            note="Curated Duren jing corpus (dz_krp/index.csv)",
        )

    for kr_id, row in overrides.items():
        rel = (row.get("daozang_rel_path") or "").strip()
        dz_id = _dzid_norm(row.get("dz_id") or "")
        _add(
            kr_id,
            dz_id=dz_id,
            rel_path=rel,
            match_method="override",
            title=(row.get("title") or "").strip(),
            note=(row.get("note") or "manual override").strip(),
        )

    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata-root",
        type=Path,
        default=_default_metadata_root(),
        help="chinese_corpus_metadata project root",
    )
    parser.add_argument(
        "--dz-krp-root",
        type=Path,
        default=_default_dz_krp_root(),
        help="dz_krp project root (curated Duren jing index)",
    )
    parser.add_argument(
        "--daozang-index",
        type=Path,
        default=_plugin_root().parent / "plugin-daozang-import" / "data" / "corpus" / "index.json",
        help="Bundled Daozang corpus index.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_plugin_root() / "data" / "concordance",
        help="Output directory under plugin data/",
    )
    args = parser.parse_args()

    tables = args.metadata_root / "tables_output"
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    def _input_or_bundled(primary: Path, bundled_name: str, label: str) -> Path:
        if primary.is_file():
            return primary
        bundled = out / bundled_name
        if bundled.is_file():
            print(f"Using bundled {label}: {bundled}")
            return bundled
        raise SystemExit(f"Missing required input: {primary} (no bundled fallback at {bundled})")

    src_krp_dz = _input_or_bundled(tables / "krp_dz_collation.csv", "krp_dz_collation.csv", "krp_dz_collation")
    src_org = _input_or_bundled(
        tables / "kanripo_org_concordance.csv",
        "kanripo_org_concordance.csv",
        "kanripo_org_concordance",
    )
    src_dz_works = _input_or_bundled(
        tables / "dz_metadata_works.csv",
        "dz_corpus_works.csv",
        "dz_corpus_works",
    )
    src_duren = args.dz_krp_root / "index.csv"

    if not args.daozang_index.is_file():
        raise SystemExit(f"Missing required input: {args.daozang_index}")

    overrides_path = out / "kanripo_daozang_overrides.csv"
    if not overrides_path.is_file():
        _write_csv(
            overrides_path,
            ["kr_id", "dz_id", "daozang_rel_path", "title", "note"],
            [],
        )

    def _stage_csv(src: Path, dest: Path) -> None:
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

    _stage_csv(src_krp_dz, out / "krp_dz_collation.csv")
    _stage_csv(src_org, out / "kanripo_org_concordance.csv")

    dz_work_rows = _read_csv_rows(src_dz_works)
    _write_csv(
        out / "dz_corpus_works.csv",
        [
            "dzid",
            "title",
            "file_name",
            "file_name_match",
            "vols",
            "person_name",
            "FUNCTION",
            "dz_txt_cjk_characters",
            "dz_txt_file_bytes",
        ],
        dz_work_rows,
    )

    if src_duren.is_file():
        shutil.copy2(src_duren, out / "duren_jing_index.csv")
        duren_rows = _read_csv_rows(src_duren)
    elif (out / "duren_jing_index.csv").is_file():
        duren_rows = _read_csv_rows(out / "duren_jing_index.csv")
    else:
        duren_rows = []

    daozang_by_rel = _load_daozang_rel_paths(args.daozang_index)
    krp_dz_rows = _read_csv_rows(src_krp_dz)
    overrides = _load_overrides(overrides_path)

    entries = build_map(
        krp_dz_rows=krp_dz_rows,
        dz_work_rows=dz_work_rows,
        duren_rows=duren_rows,
        daozang_by_rel=daozang_by_rel,
        overrides=overrides,
    )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    map_doc = {
        "version": 1,
        "generatedAt": generated_at,
        "entryCount": len(entries),
        "sources": {
            "krp_dz_collation": str(src_krp_dz),
            "kanripo_org_concordance": str(src_org),
            "dz_corpus_works": str(src_dz_works),
            "duren_jing_index": str(src_duren) if src_duren.is_file() else None,
            "daozang_index": str(args.daozang_index),
            "overrides": str(overrides_path),
        },
        "entries": entries,
    }
    (out / "kanripo_daozang_map.json").write_text(
        json.dumps(map_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "packKind": "grognard-kanripo-concordance",
        "generatedAt": generated_at,
        "files": {
            "krp_dz_collation.csv": "KR_ID ↔ DZID work-level collation (~1500 Daoist texts)",
            "kanripo_org_concordance.csv": "Kanripo.org catalogue ↔ CBETA/DZID",
            "dz_corpus_works.csv": "DZID ↔ Fang Tongzi corpus filename (bundled Daozang plugin)",
            "duren_jing_index.csv": "Curated KR ↔ DZ paths for Duren jing commentaries (dz_krp)",
            "kanripo_daozang_map.json": "Runtime KR_ID → bundled Daozang rel_path map",
            "kanripo_daozang_overrides.csv": "Manual KR → Daozang overrides (maintainer-edited)",
        },
        "stats": {
            "krp_dz_rows": len(krp_dz_rows),
            "org_concordance_rows": len(_read_csv_rows(src_org)),
            "dz_work_rows": len(dz_work_rows),
            "daozang_index_entries": len(daozang_by_rel),
            "map_entries": len(entries),
            "override_rows": len(overrides),
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote concordance pack to {out}")
    print(f"  map entries: {len(entries)} / {len(krp_dz_rows)} KR↔DZ rows with bundled Daozang hit")


if __name__ == "__main__":
    main()
