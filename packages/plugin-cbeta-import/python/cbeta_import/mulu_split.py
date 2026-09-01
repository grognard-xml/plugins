"""Split a CBETA work at ``cb:mulu`` section headings (document order)."""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from cbeta_import.constants import CB_NS, TEI_NS
from cbeta_import.juan_split import JuanSlice, find_body, _rupture_parent_at

_CB = f"{{{CB_NS}}}"
_TEI = f"{{{TEI_NS}}}"


def _content_mulu(m: etree._Element) -> bool:
    return bool((m.text and m.text.strip()) or m.get("label"))


def _is_section_mulu(el: etree._Element) -> bool:
    return el.tag == f"{_CB}mulu" and el.get("type") != "卷" and _content_mulu(el)


def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


# Milestone-like anchors carry no reading content on their own; a block made up
# only of these (with no text on them or in their tails) is not a real section.
_ANCHOR_LOCALS = {"milestone", "lb", "pb"}


def _has_reading_content(block: list[etree._Element]) -> bool:
    """True if ``block`` holds anything a section ``<body>`` needs — i.e. more
    than bare ``<milestone>``/``<lb>``/``<pb>`` anchors with empty text/tails."""
    for el in block:
        if _local(el.tag) not in _ANCHOR_LOCALS:
            return True
        if (el.text or "").strip() or (el.tail or "").strip():
            return True
    return False


def _strip_redundant_head(block: list[etree._Element], title: str) -> list[etree._Element]:
    """Drop a ``<head>`` that only repeats the section title already in ``JuanSlice.title``."""
    if not block or not title.strip():
        return block
    first = block[0]
    if _local(first.tag) != "head":
        return block
    if ((first.text or "").strip()) != title.strip():
        return block
    return block[1:]


def _promote_mulu_markers_to_body(body: etree._Element) -> int:
    promoted = 0
    while True:
        nested = [
            m
            for m in body.iter(f"{_CB}mulu")
            if _is_section_mulu(m) and m.getparent() is not body
        ]
        if not nested:
            break
        _rupture_parent_at(nested[0])
        promoted += 1
    return promoted


def split_body_into_mulu(tree: etree._ElementTree | etree._Element) -> list[JuanSlice]:
    """One slice per content-bearing ``cb:mulu`` (except ``type="卷"``), numbered 1..N.

    A heading with no body content of its own — two ``cb:mulu`` markers in a row
    (typically a 篇/科 group heading immediately followed by its first child
    heading), or a heading whose only child is a ``<head>`` repeating its title
    (stripped by :func:`_strip_redundant_head`) — is *not* emitted as its own
    slice. Its title is folded into the next slice as ancestor context
    (``"譯經篇 — 攝摩騰"``) so no heading text is lost and the host never has to
    wrap an empty ``<body>`` (which it rejects outright).
    """
    body = find_body(tree)
    markers = [m for m in body.iter(f"{_CB}mulu") if _is_section_mulu(m)]
    if not markers:
        return []

    _promote_mulu_markers_to_body(body)
    children = [c for c in body if isinstance(c.tag, str)]
    marker_idx = [i for i, c in enumerate(children) if _is_section_mulu(c)]
    if not marker_idx:
        return []

    slices: list[JuanSlice] = []
    bounds = marker_idx + [len(children)]
    lead = [copy.deepcopy(c) for c in children[: marker_idx[0]]]
    pending: list[str] = []  # titles of content-less headings awaiting a host slice
    carry: list[etree._Element] = []  # their anchor-only nodes, prepended to the next slice

    for k, start in enumerate(marker_idx):
        end = bounds[k + 1]
        ms = children[start]
        title = (ms.text or "").strip() or (ms.get("label") or "").strip()
        # The split marker's label is carried in ``title`` for the host section
        # ``<head>``; keep only this slice's body content in ``elements``.
        block = [copy.deepcopy(c) for c in children[start + 1 : end]]
        block = _strip_redundant_head(block, title)
        if k == 0 and lead:
            block = lead + block
        if not _has_reading_content(block):
            # A group heading (譯經篇 …) with no reading content of its own: fold
            # its title into the next real section and keep any bare anchors.
            if title:
                pending.append(title)
            carry.extend(block)
            continue
        full_title = " — ".join([*pending, title]) if pending else title
        sl = JuanSlice(n=str(len(slices) + 1), title=full_title, elements=carry + block)
        if pending:
            sl.straddles.append(
                f"section {sl.n}: folded in {len(pending)} content-less "
                f"heading(s) ({', '.join(pending)})"
            )
        pending, carry = [], []
        slices.append(sl)

    if pending and slices:
        slices[-1].elements.extend(carry)
        slices[-1].straddles.append(
            f"section {slices[-1].n}: dropped {len(pending)} trailing content-less "
            f"heading(s) ({', '.join(pending)})"
        )
    return slices


def split_file(path: str | Path) -> list[JuanSlice]:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    tree = etree.parse(str(path), parser)
    return split_body_into_mulu(tree)
