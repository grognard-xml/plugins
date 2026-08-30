"""Map SKQS dynasty labels to Norbert ``court_id`` (dynasty id)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from kanripo_import.person_name_normalize import normalize_skqs_dynasty

# Prefer imperial / period labels over homonymous pre-Qin states.
SKQS_DYNASTY_NORBERT_ID: dict[str, int] = {
    "宋": 119,
    "南朝宋": 83,
    "劉宋": 83,
    "北宋": 132,
    "南宋": 119,
    "明": 125,
    "清": 127,
    "元": 124,
    "唐": 97,
    "漢": 42,
    "西漢": 43,
    "東漢": 44,
    "隋": 96,
    "魏": 156,
    "晉": 224,
    "東晉": 225,
    "西晉": 226,
    "吳": 510,
    "南朝": 81,
    "北朝": 80,
    "北魏": 438,
    "北齊": 468,
    "北周": 474,
    "梁": 430,
    "陳": 432,
    "齊": 84,
    "秦": 166,
    "周": 5,
    "金": 630,
    "遼": 600,
    "民國": 678,
    "中華民國": 678,
}


def _default_labels_path() -> Path | None:
    root = Path(__file__).resolve().parents[3]
    candidates = [
        root.parent / "authority extraction" / "norbert_public" / "dynasty-labels.json",
        root.parents[1] / "authority extraction" / "norbert_public" / "dynasty-labels.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=1)
def _labels_by_zh() -> dict[str, int]:
    path = _default_labels_path()
    if not path:
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for dyn_id, row in (doc.get("dynasties") or {}).items():
        zh = str((row or {}).get("zh") or "").strip()
        if zh:
            out.setdefault(zh, int(dyn_id))
    return out


def norbert_court_id(skqs_dynasty: str) -> tuple[int | None, str]:
    """Return ``(court_id, label)`` for a SKQS dynasty string."""
    dynasty = normalize_skqs_dynasty((skqs_dynasty or "").strip())
    if not dynasty:
        return None, ""
    if dynasty in SKQS_DYNASTY_NORBERT_ID:
        court_id = SKQS_DYNASTY_NORBERT_ID[dynasty]
        labels = _labels_by_zh()
        return court_id, labels.get(dynasty, dynasty)
    labels = _labels_by_zh()
    if dynasty in labels:
        return labels[dynasty], dynasty
    stripped = dynasty.replace("朝", "").replace("代", "")
    if stripped in SKQS_DYNASTY_NORBERT_ID:
        court_id = SKQS_DYNASTY_NORBERT_ID[stripped]
        return court_id, labels.get(stripped, stripped)
    if stripped in labels:
        return labels[stripped], stripped
    return None, dynasty
