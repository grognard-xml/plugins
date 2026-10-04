"""Resolve Kanripo ``&KRnnnn;`` references using bundled KR-Gaiji tables."""

from __future__ import annotations

import re
import shutil
from functools import lru_cache
from pathlib import Path

from kanripo_import._paths import gaiji_charlist_path, gaiji_image_path

_KR_REF_RE = re.compile(r"&KR(\d{4});")
_CHARLIST_LINE_RE = re.compile(r"^(KR\d+)\s+\d+\s*(.*?)\s*\[\[file:", re.DOTALL)
_GAIJI_INLINE_TAG_RE = re.compile(r"<gaiji:(KR\d{4})/>")
_GAIJI_GRAPHIC_URL = "_gaiji/{kr_id}.png"


def _parse_charlist_body(body: str) -> list[str]:
    body = body.strip()
    if not body:
        return []
    if not body.startswith("["):
        return body.split()

    depth = 0
    for index, char in enumerate(body):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                while end < len(body) and body[end] not in " \t":
                    end += 1
                first = body[:end]
                rest = body[end:].strip()
                if rest:
                    return [first, *rest.split()]
                return [first]
    return [body]


def replacement_from_charlist_fields(kr_id: str, fields: list[str]) -> str | None:
    """Return a Unicode/IDS replacement, or ``None`` when only the PNG is available."""
    if not fields:
        return None

    first = fields[0]
    if first.startswith("["):
        return first
    if len(first) == 1:
        return first
    return first[0]


def load_gaiji_table(path: Path) -> dict[str, str | None]:
    table: dict[str, str | None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _CHARLIST_LINE_RE.match(line)
        if not match:
            continue
        kr_id, body = match.group(1), match.group(2)
        fields = _parse_charlist_body(body)
        table[kr_id] = replacement_from_charlist_fields(kr_id, fields)
    return table


@lru_cache(maxsize=1)
def default_table() -> dict[str, str | None]:
    return load_gaiji_table(gaiji_charlist_path())


def gaiji_inline_tag(kr_id: str) -> str:
    return f"<gaiji:{kr_id}/>"


def gaiji_graphic_xml(kr_id: str) -> str:
    url = _GAIJI_GRAPHIC_URL.format(kr_id=kr_id)
    return (
        f'<g type="kanripo" n="{kr_id}">'
        f'<graphic url="{url}" height="1em"/>'
        f"</g>"
    )


def expand_gaiji_inline_tags(text: str) -> str:
    return _GAIJI_INLINE_TAG_RE.sub(lambda match: gaiji_graphic_xml(match.group(1)), text)


_KR_ID_RE = re.compile(r"KR\d{4}")


def clean_gaiji_overrides(raw: object) -> dict[str, str]:
    """Keep only well-formed ``KRnnnn -> character`` entries from a project override table.

    A value must be exactly one Unicode code point (or an IDS ``[...]`` string); anything else
    is dropped so a hand-edited file can't inject markup into the document.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _KR_ID_RE.fullmatch(key) or not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) == 1 or (value.startswith("[") and value.endswith("]")):
            if not any(ch in value for ch in "<>&"):
                cleaned[key] = value
    return cleaned


def resolve_kanripo_refs(
    text: str,
    table: dict[str, str | None] | None = None,
    overrides: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Replace ``&KRnnnn;`` references; return text and KR ids that need PNG assets.

    ``overrides`` (the project's own ``KRnnnn -> character`` table) wins over the bundled
    KR-Gaiji charlist, which is blank for most entries and lossy (normalised) for others.
    """
    lookup = default_table() if table is None else table
    overrides = overrides or {}
    image_ids: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        kr_id = f"KR{match.group(1)}"
        replacement = overrides.get(kr_id) or lookup.get(kr_id)
        if replacement:
            return replacement
        if kr_id not in image_ids:
            image_ids.append(kr_id)
        return gaiji_inline_tag(kr_id)

    return _KR_REF_RE.sub(_replace, text), image_ids


def copy_gaiji_assets(kr_ids: list[str], dest_dir: Path) -> list[str]:
    """Copy bundled PNGs for ``kr_ids`` into ``dest_dir``; return ids actually copied."""
    if not kr_ids:
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for kr_id in kr_ids:
        source = gaiji_image_path(kr_id)
        if not source.is_file():
            continue
        shutil.copy2(source, dest_dir / f"{kr_id}.png")
        copied.append(kr_id)
    return copied
