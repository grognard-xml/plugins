#!/usr/bin/env python3
"""Patch ``krp_wikidata_by_kr_id.json`` with P50/P98 ``wikidata_authors`` (no full metadata rebuild)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "python"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

from wikidata_work_authors import authors_for_work_record, fetch_authors_for_work_qids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sidecar",
        type=Path,
        default=_PLUGIN_ROOT / "data" / "metadata" / "krp_wikidata_by_kr_id.json",
    )
    args = parser.parse_args()

    doc = json.loads(args.sidecar.read_text(encoding="utf-8"))
    entries = doc.get("entries") or {}
    work_qids: list[str] = []
    for row in entries.values():
        if not isinstance(row, dict):
            continue
        for key in ("work_qid", "edition_qid", "wikidata_work_qid"):
            qid = (row.get(key) or "").strip()
            if qid:
                work_qids.append(qid)

    authors_by_qid = fetch_authors_for_work_qids(work_qids)
    attached = 0
    for row in entries.values():
        if not isinstance(row, dict):
            continue
        authors = authors_for_work_record(
            str(row.get("work_qid") or row.get("wikidata_work_qid") or ""),
            str(row.get("edition_qid") or ""),
            authors_by_qid=authors_by_qid,
        )
        if authors:
            row["wikidata_authors"] = authors
            attached += 1

    doc["generatedAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    args.sidecar.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {args.sidecar} ({attached} works with wikidata_authors)")


if __name__ == "__main__":
    main()
