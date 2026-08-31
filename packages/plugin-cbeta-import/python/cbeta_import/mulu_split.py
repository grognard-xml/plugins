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
    """One slice per content-bearing ``cb:mulu`` (except ``type="卷"``), numbered 1..N."""
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
        slices.append(JuanSlice(n=str(k + 1), title=title, elements=block))
    return slices


def split_file(path: str | Path) -> list[JuanSlice]:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    tree = etree.parse(str(path), parser)
    return split_body_into_mulu(tree)
