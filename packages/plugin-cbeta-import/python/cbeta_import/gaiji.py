"""Resolve ``<g ref="#CB…">`` gaiji (planning §5.9, decided).

Policy: replace ``<g>`` with a Unicode character when the file's own
``<charDecl>`` (or the bundled ``cb_gaiji.json``) supplies one within the
target Unicode support; otherwise keep the ``<g>`` element and ship the glyph
image. Siddhaṃ (``#SD-…``) and Rañjana (``#RJ-…``) never resolve — kept as
``<g>`` + bundled glyph.
"""

from __future__ import annotations

from lxml import etree

from cbeta_import.constants import TEI_NS

_TEI = f"{{{TEI_NS}}}"


def load_char_decl(tree: etree._ElementTree | etree._Element) -> dict[str, str]:
    """Map ``xml:id`` → Unicode string from ``<charDecl><char>``.

    Reads ``<mapping type="unicode">`` / ``<unicode>`` / codepoint children.
    TODO: honour ``<charProp>`` composition and normalization hints.
    """
    root = tree.getroot() if isinstance(tree, etree._ElementTree) else tree
    out: dict[str, str] = {}
    for char in root.iter(f"{_TEI}char"):
        cid = char.get(f"{{{'http://www.w3.org/XML/1998/namespace'}}}id")
        if not cid:
            continue
        for mapping in char.iter(f"{_TEI}mapping"):
            if mapping.get("type") in {"unicode", "normal_unicode"} and mapping.text:
                out[cid] = mapping.text.strip()
                break
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
        return g_el.text.strip()
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
