"""Load Wikidata authority pack entries by Q-id or person name (build-time only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_works_by_qid(
    pack_path: Path,
    *,
    wanted_qids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Stream ``works.ndjson`` and index ``authorityId`` → record."""
    if not pack_path.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with pack_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            qid = (row.get("authorityId") or "").strip()
            if not qid:
                continue
            if wanted_qids is not None and qid not in wanted_qids:
                continue
            out[qid] = row
    return out


def _person_pack_priority(path: Path) -> int:
    """Lower number = preferred when the same ``primaryName`` appears in multiple packs."""
    order = {
        "person-zh-hant-pre-ming": 0,
        "person-zh-hant-ming": 1,
        "person-zh-hant-qing": 2,
        "person-zh-hant-tang": 3,
        "person-ja-japan": 4,
        "person-bo": 5,
    }
    return order.get(path.parent.name, 50)


def load_persons_by_primary_name(pack_roots: list[Path]) -> dict[str, str]:
    """Index ``primaryName`` → Wikidata Q-id from ``person-*/persons.ndjson`` packs."""
    paths: list[Path] = []
    for root in pack_roots:
        if root.is_dir():
            paths.extend(root.glob("person-*/persons.ndjson"))
    # Process lower-priority packs first so preferred dynasties win on name clashes.
    paths.sort(key=lambda path: (_person_pack_priority(path), path.as_posix()), reverse=True)

    out: dict[str, str] = {}
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                name = (row.get("primaryName") or "").strip()
                qid = (row.get("authorityId") or "").strip()
                if name and qid:
                    out[name] = qid
    return out


def enrich_from_pack(
    entry: dict[str, Any],
    *,
    pack_row: dict[str, Any] | None,
) -> None:
    """Fill gaps in a metadata entry from a Wikidata work pack row."""
    if not pack_row:
        return
    meta = pack_row.get("metadata") or {}
    wd = entry.setdefault("wikidata", {})
    if not wd.get("primary_name"):
        wd["primary_name"] = (pack_row.get("primaryName") or "").strip()
    aliases = [s for s in (pack_row.get("searchStrings") or []) if s]
    if aliases and not wd.get("aliases"):
        wd["aliases"] = aliases
    if meta.get("startYear") is not None and not entry.get("date_not_before"):
        year = str(meta["startYear"])
        entry["date_not_before"] = year
        if not entry.get("author_dates"):
            entry["author_dates"] = year
    if meta.get("endYear") is not None and not entry.get("date_not_after"):
        entry["date_not_after"] = str(meta["endYear"])
    if meta.get("description") and not wd.get("description"):
        wd["description"] = str(meta["description"])
