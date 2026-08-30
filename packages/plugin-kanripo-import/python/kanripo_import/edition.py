"""Resolve edition profiles and parse SKQS SOURCE / witness codes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from kanripo_import._paths import metadata_dir


@dataclass(frozen=True)
class EditionInfo:
    edition_profile: str
    edition_label: str
    edition_date: str
    source_locator: str


_EMPTY = EditionInfo("", "", "", "")


@lru_cache(maxsize=1)
def load_edition_profiles() -> dict[str, dict[str, Any]]:
    path = metadata_dir() / "edition_profiles.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def _profile_by_prefix(source: str, profiles: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any], str]:
    text = (source or "").strip()
    if not text:
        return "", {}, ""
    best_id = ""
    best_profile: dict[str, Any] = {}
    best_prefix = ""
    best_len = -1
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        for prefix in profile.get("source_prefixes") or []:
            prefix_text = str(prefix).strip()
            if not prefix_text:
                continue
            if text.startswith(prefix_text) and len(prefix_text) > best_len:
                best_id = profile_id
                best_profile = profile
                best_prefix = prefix_text
                best_len = len(prefix_text)
    if not best_id:
        return "", {}, ""
    remainder = text[len(best_prefix) :].lstrip()
    if remainder.startswith(","):
        remainder = remainder[1:].lstrip()
    else:
        remainder = ""
    return best_id, best_profile, remainder


def _profile_by_witness(witness_code: str, profiles: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    code = (witness_code or "").strip()
    if not code:
        return "", {}
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        for witness in profile.get("witness_codes") or []:
            if str(witness).strip().upper() == code.upper():
                return profile_id, profile
    return "", {}


def resolve_edition(*, source: str = "", witness_code: str = "") -> EditionInfo:
    profiles = load_edition_profiles()
    profile_id, profile, locator = _profile_by_prefix(source, profiles)
    if not profile_id:
        profile_id, profile = _profile_by_witness(witness_code, profiles)
        locator = ""
    if not profile_id:
        return _EMPTY
    return EditionInfo(
        edition_profile=profile_id,
        edition_label=str(profile.get("label_zh") or "").strip(),
        edition_date=str(profile.get("edition_date") or "").strip(),
        source_locator=locator.strip(),
    )


def clear_edition_cache() -> None:
    load_edition_profiles.cache_clear()
