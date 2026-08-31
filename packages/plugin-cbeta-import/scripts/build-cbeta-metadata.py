#!/usr/bin/env python3
"""Build the bundled metadata + schema under ``data/`` from the CBETA repos.

All inputs are optional; each missing source just drops its enrichment.

  --authority-catalog DIR   Authority-Databases/authority_catalog/json/
                            (primary: title, byline, dynasty, category, juans,
                            vol, contributors[{id,name}])
  --authority-person FILE   Authority-Databases/authority_person/
                            Buddhist_Studies_Person_Authority.xml
                            (per DILA id: dates, Wikidata ref)
  --creators DIR            cbeta-metadata/creators/creators-by-canon/
                            (fallback contributor ids when a work is missing
                            from the authority catalog)
  --crosswalk FILE          DILA id → Norbert / Wikidata id. CSV (columns
                            containing "dila" + "norbert"/"wikidata") or JSON
                            ({dila_id: norbert_id} or {dila_id: {...}}).
  --gaiji DIR               cbeta-metadata/gaiji/  (best-effort cb_gaiji.json;
                            per-file <charDecl> is the primary source at import)
  --schema DIR              checkout of the CBETA published RNG/SCH
  --corpus DIR              synced xml-p5 checkout (file grouping for the
                            catalog index + a fallback header scan)
  --file-list FILE          newline-delimited xml-p5 paths (e.g.
                            `gh api repos/cbeta-org/xml-p5/git/trees/master?recursive=1`)
                            — file grouping for multi-volume works without a checkout

Outputs (under --out, default <pkg>/data):
  metadata/work_info.json      {work_id: {title, dynasty, category, juan_count,
                                work_qid?, contributors:[{person_name, role,
                                dila_id, norbert_id?, wikidata_qid?, dates?}]}}
  metadata/catalog_index.json  {"works": [CatalogHit dicts]}
  metadata/gaiji/cb_gaiji.json {CB_id: {unicode?}}
  schema/cbeta_p5.rng / .sch   CBETA's grammar + the LJB §4 loosenings
                               (loosen_schema.py); .sch passes through
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT / "python"))

from cbeta_import.catalog_index import (  # noqa: E402
    CatalogHit,
    build_index_from_corpus,
    group_stems,
)
from cbeta_import.metadata_xml import parse_byline  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loosen_schema import loosen_rng, loosen_sch  # noqa: E402

_PERSON_RE = re.compile(r'<person\b[^>]*\bxml:id="(?P<id>[^"]+)"[^>]*>(?P<body>.*?)</person>', re.S)
_YEAR_RE = re.compile(r"(-?\d{1,4})")
_WD_RE = re.compile(r"(?:wikidata\.org/(?:wiki|entity)/|Wikidata[\"'>\s:]+)(Q\d+)", re.I)


def _log(msg: str) -> None:
    print(f"[build-cbeta-metadata] {msg}")


# --------------------------------------------------------------------------- #
# sources


def load_authority_catalog(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for jf in sorted(root.glob("*.json")):
        if jf.name.lower() == "readme.json":
            continue
        try:
            data = json.loads(jf.read_text("utf-8"))
        except json.JSONDecodeError:
            _log(f"skip unreadable {jf.name}")
            continue
        if isinstance(data, dict):
            out.update(data)
    _log(f"authority catalog: {len(out)} works")
    return out


def load_crosswalk(path: Path) -> dict[str, dict]:
    text = path.read_text("utf-8")
    xw: dict[str, dict] = {}
    if path.suffix.lower() == ".json":
        raw = json.loads(text)
        for k, v in raw.items():
            xw[k] = v if isinstance(v, dict) else {"norbert_id": str(v)}
    else:
        reader = csv.DictReader(text.splitlines())
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        dila_c = next((cols[c] for c in cols if "dila" in c), None)
        nb_c = next((cols[c] for c in cols if "norbert" in c), None)
        wd_c = next((cols[c] for c in cols if "wikidata" in c or c in {"qid", "wd"}), None)
        if not dila_c:
            _log(f"crosswalk {path.name}: no DILA column — ignored")
            return {}
        for row in reader:
            did = (row.get(dila_c) or "").strip()
            if not did:
                continue
            entry: dict = {}
            if nb_c and row.get(nb_c, "").strip():
                entry["norbert_id"] = row[nb_c].strip()
            if wd_c and row.get(wd_c, "").strip():
                entry["wikidata_qid"] = row[wd_c].strip()
            if entry:
                xw[did] = entry
    _log(f"crosswalk: {len(xw)} DILA ids mapped")
    return xw


def load_person_meta(xml_path: Path) -> dict[str, dict]:
    text = xml_path.read_text("utf-8", "replace")
    out: dict[str, dict] = {}
    for m in _PERSON_RE.finditer(text):
        body = m.group("body")
        entry: dict = {}
        birth = re.search(r"<birth\b[^>]*>(.*?)</birth>", body, re.S)
        death = re.search(r"<death\b[^>]*>(.*?)</death>", body, re.S)
        by = _YEAR_RE.search(birth.group(1)) if birth else None
        dy = _YEAR_RE.search(death.group(1)) if death else None
        if by or dy:
            entry["dates"] = f"{by.group(1) if by else '?'}–{dy.group(1) if dy else '?'}"
        wd = _WD_RE.search(body)
        if wd:
            entry["wikidata_qid"] = wd.group(1)
        if entry:
            out[m.group("id")] = entry
    _log(f"person authority: dates/qid for {len(out)} ids")
    return out


def load_creators(root: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for jf in sorted(root.glob("*.json")):
        try:
            data = json.loads(jf.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        for wid, rec in (data.items() if isinstance(data, dict) else []):
            pairs = re.findall(r"([^(;,]+)\(([A-Z]\d+)\)", rec.get("creators_with_id", ""))
            if pairs:
                out[wid] = [{"name": n.strip(), "id": i} for n, i in pairs]
    _log(f"creators fallback: {len(out)} works")
    return out


# --------------------------------------------------------------------------- #
# assembly


def _contributors(entry: dict, xw: dict[str, dict], person: dict[str, dict]) -> list[dict]:
    byline = entry.get("byline", "")
    _dyn, parsed = parse_byline(byline)
    default_role = parsed[0].role if parsed else "author"
    role_by_name = {c.person_name: c.role for c in parsed}

    rows: list[dict] = []
    for c in entry.get("contributors", []):
        name, did = c.get("name", ""), c.get("id", "")
        if not name:
            continue
        role = next(
            (r for n, r in role_by_name.items() if n and (n in name or name in n)),
            default_role,
        )
        row = {"person_name": name, "role": role}
        if did:
            row["dila_id"] = did
            row.update(xw.get(did, {}))
            row.update(person.get(did, {}))
        rows.append({k: v for k, v in row.items() if v})
    return rows


def build_work_info(
    catalog: dict[str, dict],
    creators: dict[str, list[dict]],
    xw: dict[str, dict],
    person: dict[str, dict],
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for wid, entry in catalog.items():
        if entry.get("type") not in (None, "textbody"):
            continue
        contribs = _contributors(entry, xw, person)
        if not contribs and wid in creators:
            contribs = _contributors({**entry, "contributors": creators[wid]}, xw, person)
        rec: dict = {
            "title": entry.get("title", ""),
            "dynasty": entry.get("dynasty", ""),
            "category": entry.get("orig_category") or entry.get("category", ""),
            "juan_count": int(entry.get("juans") or 0),
            "contributors": contribs,
        }
        aid = entry.get("authorityID")
        if aid and str(aid).startswith("Q"):
            rec["work_qid"] = aid
        out[wid] = rec
    return out


def _vol_stems(wid: str, vol: str) -> list[str]:
    """Single-volume: reconstruct the file stem. Ranges (``T05..T07``) → []."""
    if not vol or ".." in vol:
        return []
    m = re.match(r"^([A-Z]{1,2})(\d{1,3})$", vol)
    n = re.match(r"^([A-Z]{1,2})([A-Za-z]?\d{1,4}[A-Za-z]?)$", wid)
    return [f"{vol}n{n.group(2)}"] if m and n else []


def build_catalog_index(
    catalog: dict[str, dict], corpus: Path | None, file_list: Path | None
) -> dict:
    grouped: dict[str, tuple[str, ...]] = {}
    src = "vol"
    if corpus and corpus.is_dir():
        for hit in build_index_from_corpus(corpus):
            grouped[hit.work_id] = hit.files
        _log(f"corpus scan: {len(grouped)} works for file grouping")
        src = "corpus"
    elif file_list and file_list.is_file():
        stems = [ln.strip() for ln in file_list.read_text("utf-8").splitlines() if ln.strip()]
        grouped = group_stems(stems)
        _log(f"file list: {len(grouped)} works grouped from {len(stems)} paths")
        src = "file-list"

    works: list[dict] = []
    for wid, entry in catalog.items():
        if entry.get("type") not in (None, "textbody"):
            continue
        files = grouped.get(wid) or tuple(_vol_stems(wid, str(entry.get("vol", ""))))
        works.append(
            asdict(
                CatalogHit(
                    work_id=wid,
                    title=entry.get("title", ""),
                    canon=re.match(r"^[A-Z]{1,2}", wid).group(0) if re.match(r"^[A-Z]{1,2}", wid) else "",
                    dynasty=entry.get("dynasty", ""),
                    category=entry.get("orig_category") or entry.get("category", ""),
                    juan_count=int(entry.get("juans") or 0),
                    files=files,
                    authors=",".join(c.get("name", "") for c in entry.get("contributors", [])),
                )
            )
        )
    works.sort(key=lambda w: (w["canon"], w["work_id"]))
    with_files = sum(1 for w in works if w["files"])
    _log(f"catalog index: {with_files}/{len(works)} works have a file list ({src})")
    return {"built_from": f"authority_catalog + {src}", "works": works}


def build_gaiji(root: Path) -> dict:
    for name in ("gaiji.json", "cb-gaiji.json", "gaiji_unicode.json"):
        p = root / name
        if p.is_file():
            try:
                return json.loads(p.read_text("utf-8"))
            except json.JSONDecodeError:
                pass
    _log("gaiji: no recognised table — per-file <charDecl> remains the source")
    return {}


def copy_schema(src: Path, out_schema: Path) -> None:
    rng = next(iter(src.glob("**/*.rng")), None)
    sch = next(iter(src.glob("**/*.sch")), None)
    if rng:
        (out_schema / "cbeta_p5.rng").write_text(
            loosen_rng(rng.read_text("utf-8")), "utf-8"
        )
        _log(f"schema: {rng.name} + LJB §4 loosenings → cbeta_p5.rng")
    if sch:
        (out_schema / "cbeta_p5.sch").write_text(
            loosen_sch(sch.read_text("utf-8")), "utf-8"
        )
        _log(f"schema: {sch.name} → cbeta_p5.sch")


# --------------------------------------------------------------------------- #


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--authority-catalog", type=Path)
    ap.add_argument("--authority-person", type=Path)
    ap.add_argument("--creators", type=Path)
    ap.add_argument("--crosswalk", type=Path)
    ap.add_argument("--gaiji", type=Path)
    ap.add_argument("--schema", type=Path)
    ap.add_argument("--corpus", type=Path)
    ap.add_argument("--file-list", type=Path, help="newline-delimited xml-p5 paths (no checkout)")
    ap.add_argument("--out", type=Path, default=PKG_ROOT / "data")
    args = ap.parse_args(argv)

    meta_dir = args.out / "metadata"
    (meta_dir / "gaiji").mkdir(parents=True, exist_ok=True)
    (args.out / "schema").mkdir(parents=True, exist_ok=True)

    # Non-destructive: with no data source, keep whatever is already bundled
    # (the release pipeline runs this with no args — it must not clobber a real
    # build with placeholders). Only seed empty files if none exist yet.
    if not args.authority_catalog:
        seeded = 0
        for rel, empty in {
            "metadata/work_info.json": "{}\n",
            "metadata/catalog_index.json": '{"works": []}\n',
            "metadata/gaiji/cb_gaiji.json": "{}\n",
        }.items():
            target = args.out / rel
            if not target.exists() or target.stat().st_size <= 2:
                target.write_text(empty, "utf-8")
                seeded += 1
        _log(
            f"no --authority-catalog → left existing bundled data untouched"
            f"{f' (seeded {seeded} placeholder(s))' if seeded else ''}"
        )
        if args.schema and args.schema.is_dir():
            copy_schema(args.schema, args.out / "schema")
        return 0

    catalog = load_authority_catalog(args.authority_catalog) if args.authority_catalog else {}
    creators = load_creators(args.creators) if args.creators else {}
    xw = load_crosswalk(args.crosswalk) if args.crosswalk and args.crosswalk.is_file() else {}
    person = (
        load_person_meta(args.authority_person)
        if args.authority_person and args.authority_person.is_file()
        else {}
    )

    work_info = build_work_info(catalog, creators, xw, person) if catalog else {}
    catalog_index = build_catalog_index(catalog, args.corpus, args.file_list) if catalog else {"works": []}
    gaiji = build_gaiji(args.gaiji) if args.gaiji and args.gaiji.is_dir() else {}

    (meta_dir / "work_info.json").write_text(
        json.dumps(work_info, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )
    (meta_dir / "catalog_index.json").write_text(
        json.dumps(catalog_index, ensure_ascii=False), "utf-8"
    )
    (meta_dir / "gaiji" / "cb_gaiji.json").write_text(
        json.dumps(gaiji, ensure_ascii=False), "utf-8"
    )
    if args.schema and args.schema.is_dir():
        copy_schema(args.schema, args.out / "schema")

    _log(
        f"wrote work_info.json ({len(work_info)}), catalog_index.json "
        f"({len(catalog_index['works'])}), cb_gaiji.json ({len(gaiji)})"
    )
    if not catalog:
        _log("no --authority-catalog given → placeholder outputs only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
