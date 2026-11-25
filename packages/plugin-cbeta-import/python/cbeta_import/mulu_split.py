"""Split a CBETA work at ``cb:mulu`` section headings (document order)."""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from cbeta_import import gaiji
from cbeta_import.constants import CB_NS, TEI_NS
from cbeta_import.juan_split import JuanSlice, find_body, promote_to_body

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


def _promote_mulu_markers_to_body(body: etree._Element) -> int:
    nested = [
        m
        for m in body.iter(f"{_CB}mulu")
        if _is_section_mulu(m) and m.getparent() is not body
    ]
    return promote_to_body(body, nested)


def _level(ms: etree._Element) -> int:
    """``@level`` of a section ``cb:mulu`` (1 when absent or not a number)."""
    try:
        return max(1, int(ms.get("level") or 1))
    except ValueError:
        return 1


def _is_juan_milestone(el: etree._Element) -> bool:
    return _local(el.tag) == "milestone" and el.get("unit") == "juan"


def _split_off_juan_opener(
    block: list[etree._Element],
) -> tuple[list[etree._Element], list[etree._Element]]:
    """Cut ``block`` where the next juan opens: ``(this section's content, the opener onward)``.

    A juan's opening (``<milestone unit="juan">``, its ``<pb/>``/``<lb/>``, the ``卷`` mulu, the
    ``<cb:jhead>`` and the byline) sits *before* the first section heading of that juan, so
    cutting at section headings leaves it on the end of the previous section. It belongs with
    the juan it opens, i.e. the next section.
    """
    for i in range(len(block) - 1, -1, -1):
        if _is_juan_milestone(block[i]):
            return block[:i], block[i:]
    return block, []


def _plain(
    el: etree._Element,
    char_map: dict[str, str] | None,
    char_info: dict[str, gaiji.GaijiInfo] | None,
) -> str:
    """Text of a heading *including* what is inside child elements.

    ``el.text`` alone stops at the first child, so a title like 大集賢護菩<g>薩</g>經 came out as
    "大集賢護菩". A ``<g>`` is read as the character it resolves to, else its normalised form.
    """
    out = [el.text or ""]
    for child in el:
        if not isinstance(child.tag, str):
            pass
        elif _local(child.tag) == "g":
            hit = gaiji.resolve(child, char_map or {})
            if hit is None:
                info = (char_info or {}).get((child.get("ref") or "").lstrip("#"))
                hit = (info.normalized if info else "") or gaiji.PLACEHOLDER
            out.append(hit)
        else:
            out.append(_plain(child, char_map, char_info))
        out.append(child.tail or "")
    return "".join(out).strip()


def _head_from_mulu(ms: etree._Element, **attrs: str) -> etree._Element:
    """A ``<head>`` carrying the mulu's own content (``<g>`` and all, so gaiji resolve later)."""
    head = etree.Element(f"{_TEI}head", **attrs)
    head.text = ms.text or ms.get("label") or ""
    for child in ms:
        head.append(copy.deepcopy(child))
    head.tail = "\n"
    return head


def split_body_into_mulu(
    tree: etree._ElementTree | etree._Element,
    char_map: dict[str, str] | None = None,
    char_info: dict[str, gaiji.GaijiInfo] | None = None,
) -> list[JuanSlice]:
    """One slice per content-bearing ``cb:mulu`` (except ``type="卷"``), numbered 1..N.

    Every slice keeps its place in the work's heading hierarchy, so a section never loses the
    title of the thing it belongs to (in 玄應's 一切經音義: the cited sūtra whose terms follow,
    as distinct from the juan of the sūtra, which is only "第二卷"):

    * ``title`` is the section's *own* heading only.
    * The headings above it (a lower ``@level`` still in force) are written into the slice as
      ``<head type="context" n="LEVEL">`` before its own ``<head>`` — carried into every
      following section until a heading of the same or a higher level replaces them.
    * A heading with no body content of its own (a 篇/科 group heading directly followed by a
      child, or one whose only child is a ``<head>`` repeating its title) is not emitted as an
      empty slice; it shows up as context on the section that follows, so no heading text is
      lost and the host never has to wrap an empty ``<body>`` (which it rejects outright).
    * A juan's opening (milestone, ``卷`` mulu, ``<cb:jhead>``, byline) moves to the start of
      the first section of *that* juan, and ``in_juan`` records which CBETA juan each section
      is in, so the source work's juan is never mistaken for a cited work's "第N卷".
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

    # (level, title, mulu) of the headings in force / of content-less ones awaiting a host slice
    stack: list[tuple[int, str, etree._Element]] = []
    pending: list[tuple[int, str, etree._Element]] = []
    carry: list[etree._Element] = []  # their anchor-only nodes, prepended to the next slice
    opener: list[etree._Element] = list(lead)  # juan opening carried onto the next slice
    juan_n = ""
    for el in lead:
        if _is_juan_milestone(el):
            juan_n = el.get("n") or ""

    for k, start in enumerate(marker_idx):
        end = bounds[k + 1]
        ms = children[start]
        title = _plain(ms, char_map, char_info) or (ms.get("label") or "").strip()
        level = _level(ms)
        while stack and stack[-1][0] >= level:
            stack.pop()
        context = list(stack)
        stack.append((level, title, ms))

        # The split marker's label is carried in ``title``; keep only this slice's body
        # content in ``elements``.
        block = [copy.deepcopy(c) for c in children[start + 1 : end]]
        block, next_opener = _split_off_juan_opener(block)
        # A leading ``<head>`` that only repeats the mulu is not reading content: on its own it
        # does not make a section (the heading becomes context for the next one).
        repeats = bool(
            block
            and _local(block[0].tag) == "head"
            and _plain(block[0], char_map, char_info) == title
        )
        if not _has_reading_content(block[1:] if repeats else block):
            if repeats:
                block = block[1:]
            # A group heading (譯經篇 …) with no reading content of its own: it becomes context
            # for the next real section, whose own juan opening (if any) is still carried.
            if title:
                pending.append((level, title, ms))
            carry.extend(block)
            opener.extend(next_opener)
            continue

        in_force = {t for _, t, _ in context}
        extra = [p for p in pending if p[1] not in in_force]
        context = [*extra, *context] if extra else context
        if opener:
            for el in opener:
                if _is_juan_milestone(el):
                    juan_n = el.get("n") or juan_n
        head_nodes = [_head_from_mulu(m, type="context", n=str(lv)) for lv, _, m in context]
        # The section's own head is the source's ``<head>`` when it opens the block (it repeats the
        # mulu, or says something of its own); otherwise it is made from the mulu itself.
        if not (block and _local(block[0].tag) == "head"):
            head_nodes.append(_head_from_mulu(ms))
        sl = JuanSlice(
            n=str(len(slices) + 1),
            title=title,
            elements=[*opener, *head_nodes, *carry, *block],
            in_juan=juan_n,
            heads_included=True,
        )
        if extra:
            sl.straddles.append(
                f"section {sl.n}: carried {len(extra)} content-less heading(s) "
                f"as context ({', '.join(t for _, t, _ in extra)})"
            )
        pending, carry = [], []
        opener = next_opener
        slices.append(sl)

    if pending and slices:
        slices[-1].elements.extend(carry)
        slices[-1].straddles.append(
            f"section {slices[-1].n}: dropped {len(pending)} trailing content-less "
            f"heading(s) ({', '.join(t for _, t, _ in pending)})"
        )
    if opener and slices:
        slices[-1].elements.extend(opener)
    return slices


def split_file(path: str | Path) -> list[JuanSlice]:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    tree = etree.parse(str(path), parser)
    return split_body_into_mulu(tree)
