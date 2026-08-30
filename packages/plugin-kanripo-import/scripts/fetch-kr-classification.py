#!/usr/bin/env python3
"""Fetch the Kanripo 部/類 classification from the upstream KR-Catalog.

The catalogue's KR<n>.txt files are the authoritative source for the section
labels shown in the import window. Writes data/metadata/kr_classification.json.

Usage:
    python3 scripts/fetch-kr-classification.py
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CATALOG_RAW = "https://raw.githubusercontent.com/kanripo/KR-Catalog/master/KR"
PARTS = ("KR1", "KR2", "KR3", "KR4", "KR5", "KR6")

_PART_RE = re.compile(r"^\*\s+(KR\d)\s+(\S+)\s*$")
_CLASS_RE = re.compile(r"^\*\*\s+\[\[file:KR\d[a-z]\.txt\]\[(KR\d[a-z])\s+(\S+)\]\]\s*$")


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_part(text: str) -> tuple[str, str, dict[str, str]]:
    """-> (part id, part label, {class id: class label})."""
    part_id = part_label = ""
    classes: dict[str, str] = {}
    for line in text.splitlines():
        part = _PART_RE.match(line)
        if part:
            part_id, part_label = part.group(1), part.group(2)
            continue
        klass = _CLASS_RE.match(line)
        if klass:
            classes[klass.group(1)] = klass.group(2)
    if not part_id:
        raise RuntimeError("no part heading found")
    return part_id, part_label, classes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "metadata"
        / "sources"
        / "kr_classification.json",
    )
    args = parser.parse_args()

    parts: dict[str, str] = {}
    classes: dict[str, str] = {}
    for name in PARTS:
        part_id, part_label, part_classes = parse_part(_fetch(f"{CATALOG_RAW}/{name}.txt"))
        parts[part_id] = part_label
        classes.update(part_classes)
        print(f"[kr-classification] {part_id} {part_label}: {len(part_classes)} classes")

    payload = {
        "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "https://github.com/kanripo/KR-Catalog (KR/KR<n>.txt)",
        "parts": parts,
        "classes": classes,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[kr-classification] wrote {args.out} ({len(classes)} classes)")


if __name__ == "__main__":
    main()
