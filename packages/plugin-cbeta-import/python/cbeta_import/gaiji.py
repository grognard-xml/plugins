"""Resolve ``<g ref="#CB…">`` gaiji (planning §5.9, decided).

Policy: replace ``<g>`` with a Unicode character when the file's own
``<charDecl>`` (or the bundled ``cb_gaiji.json``) supplies one within the
target Unicode support; otherwise keep the ``<g>`` element and ship the glyph
image. Siddhaṃ (``#SD-…``) and Rañjana (``#RJ-…``) never resolve — kept as
``<g>`` + bundled glyph.
"""

from __future__ import annotations

import re

from lxml import etree

from cbeta_import.constants import TEI_NS

_TEI = f"{{{TEI_NS}}}"

# CBETA <charDecl> mappings carry codepoints in "U+XXXX" notation
# (e.g. <mapping type="unicode">U+478B</mapping>), sometimes several
# separated by whitespace or commas for a composed sequence.
_CODEPOINT_RE = re.compile(r"^(?:[Uu]\+[0-9A-Fa-f]{4,6}[\s,]*)+$")


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
            if decoded is None:
                continue
            if mtype == "unicode":
                best = decoded
                break
            best = best or decoded
        if best is not None:
            out[cid] = best
    return out


def resolve(g_el: etree._Element, char_map: dict[str, str]) -> str | None:
    """Return the Unicode replacement for a ``<g>`` element, or None to keep it."""
    ref = (g_el.get("ref") or "").lstrip("#")
    if ref.startswith(("SD-", "RJ-")):
        return None  # non-Han script — always keep <g> + glyph
    hit = char_map.get(ref)
    if hit:
        return hit
    # some <g> carry the character as their own text content
    if g_el.text and g_el.text.strip():
        return _decode_mapping(g_el.text)
    return None  # TODO: consult bundled cb_gaiji.json; PUA fallback


def apply(body: etree._Element, char_map: dict[str, str]) -> int:
    """Resolve every ``<g>`` in place. Returns the count resolved."""
    resolved = 0
    for g_el in list(body.iter(f"{_TEI}g")):
        repl = resolve(g_el, char_map)
        if repl is None:
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
