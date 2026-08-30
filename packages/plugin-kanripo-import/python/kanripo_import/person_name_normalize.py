"""Normalize SKQS / catalog person names for authority matching."""

from __future__ import annotations

import re
import unicodedata

# Catalog role prefixes sometimes prepended to Jesuit etc. names in SKQS.
CATALOG_NAME_PREFIXES: tuple[str, ...] = ("西洋", "國朝", "皇朝")

# SKQS dynasty labels → preferred lookup label.
SKQS_DYNASTY_NORMALIZE: dict[str, str] = {
    "南朝宋": "宋",
    "劉宋": "宋",
    "宋(劉)": "宋",
    "北宋": "宋",
    "南宋": "宋",
    "南朝": "南朝",
    "北齊": "北齊",
    "北魏": "北魏",
    "北周": "北周",
}

# Extra dynasty labels to try when matching authority records.
DYNASTY_LOOKUP_ALIASES: dict[str, tuple[str, ...]] = {
    "民國": ("民國", "清"),
    "清": ("清", "明"),
    "明": ("明", "清"),
}

# Explicit character / name variants seen in SKQS (NFKC does not cover all).
CHAR_VARIANTS: tuple[tuple[str, str], ...] = (
    ("齢", "齡"),
    ("頤", "颐"),
    ("㲄", "瑴"),
    ("朴", "樸"),
)

KNOWN_NAME_ALIASES: dict[str, str] = {
    "托克托": "脫脫",
    "荀況": "荀子",
}

# Short temple / reign names that appear without the trailing 帝 in SKQS.
IMPERIAL_SHORT_NAMES: frozenset[str] = frozenset(
    {"雍正", "乾隆", "康熙", "順治", "道光", "咸豐", "同治", "光緒", "宣統"}
)

_CATALOG_SUFFIX_RE = re.compile(r"\s+等$")


def clean_skqs_person_name(name: str) -> str:
    """Strip catalog noise from SKQS ``person_name`` before indexing."""
    text = unicodedata.normalize("NFKC", (name or "").strip())
    text = _CATALOG_SUFFIX_RE.sub("", text).strip()
    return text


def normalize_skqs_dynasty(dynasty: str) -> str:
    text = (dynasty or "").strip()
    return SKQS_DYNASTY_NORMALIZE.get(text, text)


def dynasty_lookup_labels(dynasty: str) -> tuple[str, ...]:
    text = normalize_skqs_dynasty((dynasty or "").strip())
    if not text:
        return ("",)
    labels = (text, *DYNASTY_LOOKUP_ALIASES.get(text, ()))
    return tuple(dict.fromkeys(labels))


def normalize_person_name(name: str) -> str:
    """Canonical form for exact string comparison."""
    text = clean_skqs_person_name(name)
    for prefix in CATALOG_NAME_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix) :]
    for src, dst in CHAR_VARIANTS:
        text = text.replace(src, dst)
    return KNOWN_NAME_ALIASES.get(text, text)


def person_name_match_variants(name: str) -> list[str]:
    """All name strings to try when matching authorities."""
    raw = clean_skqs_person_name(name)
    if not raw:
        return []
    variants: list[str] = [raw]
    normalized = normalize_person_name(raw)
    if normalized and normalized not in variants:
        variants.append(normalized)
    if "傳" in raw:
        fu = normalize_person_name(raw.replace("傳", "傅"))
        if fu and fu not in variants:
            variants.append(fu)
    alias = KNOWN_NAME_ALIASES.get(raw) or KNOWN_NAME_ALIASES.get(normalized)
    if alias and alias not in variants:
        variants.append(alias)
    for base in (normalized, raw):
        if base in IMPERIAL_SHORT_NAMES or any(base.startswith(prefix) for prefix in CATALOG_NAME_PREFIXES):
            imperial = f"{base}帝" if not base.endswith("帝") else base
            if imperial not in variants:
                variants.append(imperial)
    return list(dict.fromkeys(variants))


def names_match(left: str, right: str) -> bool:
    """True when two catalog/authority name strings refer to the same surface form."""
    left_variants = set(person_name_match_variants(left))
    right_variants = set(person_name_match_variants(right))
    return bool(left_variants & right_variants)
