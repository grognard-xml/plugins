"""Resolve ``<g ref="#CB…">`` gaiji (planning §5.9, decided).

Policy: replace ``<g>`` with a Unicode character when the file's own
``<charDecl>`` (or the bundled ``cb_gaiji.json``) supplies one within the
target Unicode support; otherwise keep the ``<g>`` element and ship the glyph
image. Siddhaṃ (``#SD-…``) and Rañjana (``#RJ-…``) never resolve — kept as
``<g>`` + bundled glyph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from cbeta_import.constants import TEI_NS

_TEI = f"{{{TEI_NS}}}"

# CBETA <charDecl> mappings carry codepoints in "U+XXXX" notation
# (e.g. <mapping type="unicode">U+478B</mapping>), sometimes several
# separated by whitespace or commas for a composed sequence.
_CODEPOINT_RE = re.compile(r"^(?:[Uu]\+[0-9A-Fa-f]{4,6}[\s,]*)+$")


def has_pua(text: str) -> bool:
    """True if ``text`` holds a private-use code point (BMP, plane 15 or plane 16).

    A PUA character has no meaning outside the file that defines it and no font has a
    glyph for it — it shows as tofu or a fallback symbol (often a Yijing hexagram).
    """
    return any(
        0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) <= 0x10FFFD for c in text
    )


@dataclass(frozen=True)
class GaijiInfo:
    """What a CBETA ``<char>`` declaration says about a character that has no Unicode value."""

    id: str
    composition: str = ""
    normalized: str = ""
    pua: str = ""  # "U+F1D88"

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "composition": self.composition,
            "normalized": self.normalized,
            "pua": self.pua,
        }


def _decode_mapping(text: str) -> str | None:
    """Turn a ``<mapping>`` payload into an actual Unicode string.

    ``"U+478B"`` → ``"䞋"``; ``"U+3401 U+4E00"`` → the two-char sequence.
    A payload that is already literal characters is returned as-is. Returns
    ``None`` when nothing usable is left (e.g. an empty mapping).
    """
    text = text.strip()
    if not text:
        return None
    if _CODEPOINT_RE.match(text):
        try:
            chars = [
                chr(int(cp[2:], 16))
                for cp in re.split(r"[\s,]+", text)
                if cp
            ]
        except (ValueError, OverflowError):
            return None
        return "".join(chars) or None
    return text


def load_char_decl(tree: etree._ElementTree | etree._Element) -> dict[str, str]:
    """Map ``xml:id`` → Unicode string from ``<charDecl><char>``.

    Reads ``<mapping type="unicode">`` (preferred) or ``type="normal_unicode">``,
    decoding CBETA's ``U+XXXX`` codepoint notation into real characters.
    TODO: honour ``<charProp>`` composition and normalization hints.
    """
    root = tree.getroot() if isinstance(tree, etree._ElementTree) else tree
    out: dict[str, str] = {}
    for char in root.iter(f"{_TEI}char"):
        cid = char.get(f"{{{'http://www.w3.org/XML/1998/namespace'}}}id")
        if not cid:
            continue
        best: str | None = None
        for mapping in char.iter(f"{_TEI}mapping"):
            mtype = mapping.get("type")
            if mtype not in {"unicode", "normal_unicode"} or not mapping.text:
                continue
            decoded = _decode_mapping(mapping.text)
            if decoded is None or has_pua(decoded):
                continue
            if mtype == "unicode":
                best = decoded
                break
            best = best or decoded
        if best is not None:
            out[cid] = best
    return out


def load_char_info(tree: etree._ElementTree | etree._Element) -> dict[str, GaijiInfo]:
    """Map ``xml:id`` → :class:`GaijiInfo` for every ``<charDecl><char>``.

    Used for the characters :func:`load_char_decl` cannot resolve (no Unicode mapping, or
    only a private-use one), so the import can keep ``<g>`` and say what it stands for.
    """
    root = tree.getroot() if isinstance(tree, etree._ElementTree) else tree
    xml_id = f"{{{'http://www.w3.org/XML/1998/namespace'}}}id"
    out: dict[str, GaijiInfo] = {}
    for char in root.iter(f"{_TEI}char"):
        cid = char.get(xml_id)
        if not cid:
            continue
        props: dict[str, str] = {}
        for prop in char.iter(f"{_TEI}charProp"):
            name = (prop.findtext(f"{_TEI}localName") or "").strip()
            value = (prop.findtext(f"{_TEI}value") or "").strip()
            if name and value:
                props.setdefault(name, value)
        pua = ""
        for mapping in char.iter(f"{_TEI}mapping"):
            if mapping.get("type") == "PUA" and (mapping.text or "").strip():
                pua = mapping.text.strip()
                break
        out[cid] = GaijiInfo(
            id=cid,
            composition=props.get("composition", ""),
            normalized=props.get("normalized form", ""),
            pua=pua,
        )
    return out


# Shown in place of a character that has neither a Unicode value nor a normalised form
# (〓, the typesetter's "missing character" mark) — never a bare private-use code point.
PLACEHOLDER = "〓"


def resolve(g_el: etree._Element, char_map: dict[str, str]) -> str | None:
    """Return the Unicode replacement for a ``<g>`` element, or None to keep it."""
    ref = (g_el.get("ref") or "").lstrip("#")
    if ref.startswith(("SD-", "RJ-")):
        return None  # non-Han script — always keep <g> + glyph
    hit = char_map.get(ref)
    if hit:
        return hit
    # some <g> carry the character as their own text content — but a private-use code
    # point there is CBETA's stand-in for a character Unicode lacks, not a resolution
    if g_el.text and g_el.text.strip():
        decoded = _decode_mapping(g_el.text)
        return None if decoded is None or has_pua(decoded) else decoded
    return None  # TODO: consult bundled cb_gaiji.json


def apply(
    body: etree._Element,
    char_map: dict[str, str],
    char_info: dict[str, GaijiInfo] | None = None,
    kept: dict[str, GaijiInfo] | None = None,
) -> int:
    """Resolve every ``<g>`` in place. Returns the count resolved.

    A ``<g>`` with no Unicode value stays a ``<g ref="#CB…">``, but its text is made
    readable: the character's normalised form (網 for CB07560), else 〓 — never the private-use
    code point. Each such character is recorded in ``kept`` (id → info) so the host can write
    its ``<charDecl>`` entry.
    """
    resolved = 0
    for g_el in list(body.iter(f"{_TEI}g")):
        repl = resolve(g_el, char_map)
        if repl is None:
            ref = (g_el.get("ref") or "").lstrip("#")
            if ref.startswith(("SD-", "RJ-")):
                continue
            info = (char_info or {}).get(ref) or GaijiInfo(id=ref)
            if not g_el.text or not g_el.text.strip() or has_pua(g_el.text):
                g_el.text = info.normalized or PLACEHOLDER
            if kept is not None and ref:
                kept.setdefault(ref, info)
            continue
        parent = g_el.getparent()
        if parent is None:
            continue
        _replace_with_text(parent, g_el, repl)
        resolved += 1
    return resolved


def _replace_with_text(parent: etree._Element, el: etree._Element, text: str) -> None:
    prev = el.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + text + (el.tail or "")
    else:
        parent.text = (parent.text or "") + text + (el.tail or "")
    parent.remove(el)
