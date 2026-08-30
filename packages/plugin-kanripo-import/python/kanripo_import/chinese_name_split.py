"""Split Chinese personal names using the Norbert surname list."""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

from kanripo_import._paths import plugin_root


def normalize_person_surface(name: str) -> str:
    return unicodedata.normalize("NFC", (name or "").strip())


@lru_cache(maxsize=1)
def load_surnames() -> tuple[str, ...]:
    candidates = [
        plugin_root().parent / "plugin-norbert" / "data" / "surnames.json",
        plugin_root().parents[1] / "plugin-norbert" / "data" / "surnames.json",
    ]
    for path in candidates:
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            rows = doc.get("surnames") or []
            cleaned = [str(row).strip() for row in rows if str(row).strip()]
            return tuple(sorted(cleaned, key=len, reverse=True))
    return tuple()


def segment_person_name(full_name: str) -> tuple[str, str] | None:
    """Return ``(family, given)`` or ``None`` when split is not possible."""
    name = normalize_person_surface(full_name)
    if not name or not all("\u4e00" <= ch <= "\u9fff" for ch in name):
        return None
    if len(name) < 2:
        return None
    for surname in load_surnames():
        if not surname or len(name) <= len(surname):
            continue
        if name.startswith(surname):
            given = name[len(surname) :]
            if given:
                return surname, given
    if len(name) == 2:
        return name[0], name[1]
    return None
