"""Split a CBETA P5 work into one slice per juan.

CBETA marks juan boundaries two ways (cbeta-documentation/xml/xml-structure.md):

* ``<milestone unit="juan" n="N"/>`` — the split point, an empty milestone,
  normally a direct child of ``<body>``;
* ``<cb:juan fun="open" n="NNN">…</cb:juan>`` / ``fun="close"`` — the 卷首 /
  卷末 blocks (title line, ``<cb:mulu type="卷">``), which sit *inside* the
  juan they open/close and are kept with it.

Primary strategy: cut ``<body>`` at each ``milestone[@unit='juan']``. Content
before the first juan milestone attaches to juan 1. A juan milestone nested
inside a ``<cb:div>`` (a 品 that straddles a juan boundary — planning §5.4) is
reported as a straddle and, for now, the whole enclosing div is assigned to the
juan it opens in. TODO: split the straddling div with ``@part`` / ``@prev`` /
``@next``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from cbeta_import.constants import CB_NS, JUAN_MILESTONE_UNIT, TEI_NS
from cbeta_import.xml_whitespace import collapse_tree_newlines, normalize_serialized_xml

_TEI = f"{{{TEI_NS}}}"
_CB = f"{{{CB_NS}}}"


class JuanSplitError(RuntimeError):
    """Raised when the work cannot be split (no <body>, unusable markup)."""


@dataclass
class JuanSlice:
    n: str
    """Juan number as CBETA writes it (``@n`` on the milestone/cb:juan)."""
    title: str = ""
    """Text of ``<cb:jhead>`` in the ``fun="open"`` block, if present."""
    elements: list[etree._Element] = field(default_factory=list)
    """Deep-copied top-level nodes belonging to this juan, document order."""
    apparatus: list[etree._Element] = field(default_factory=list)
    """``<back>`` children (``cb:div type="apparatus"`` …) filtered to this juan
    — the ``<app>``/`<note>` entries whose ``@from``/``@to`` point into it (§5.5)."""
    straddles: list[str] = field(default_factory=list)
    """Human-readable notes about content that crosses this juan boundary."""


def _local(tag: object) -> str:
    if not isinstance(tag, str):  # comments, PIs
        return ""
    return tag.rsplit("}", 1)[-1]


def _is_juan_milestone(el: etree._Element) -> bool:
    return el.tag == f"{_TEI}milestone" and el.get("unit") == JUAN_MILESTONE_UNIT


def _juan_open_blocks(body: etree._Element) -> list[etree._Element]:
    return [
        el
        for el in body.iter(f"{_CB}juan")
        if el.get("fun") == "open"
    ]


def _jhead_text(open_block: etree._Element) -> str:
    jhead = open_block.find(f"{_CB}jhead")
    if jhead is None:
        return ""
    return "".join(jhead.itertext()).strip()


def find_body(tree: etree._ElementTree | etree._Element) -> etree._Element:
    root = tree.getroot() if isinstance(tree, etree._ElementTree) else tree
    body = root.find(f".//{_TEI}body")
    if body is None:
        raise JuanSplitError("no <body> in document")
    return body


def find_back(tree: etree._ElementTree | etree._Element) -> etree._Element | None:
    root = tree.getroot() if isinstance(tree, etree._ElementTree) else tree
    return root.find(f".//{_TEI}back")


_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_POINTER_ATTRS = ("from", "to", "target", "corresp", "spanTo", "select")


def _ids_in(elements: list[etree._Element]) -> set[str]:
    out: set[str] = set()
    for el in elements:
        for node in el.iter():
            if isinstance(node.tag, str) and node.get(_XML_ID):
                out.add(node.get(_XML_ID))
    return out


def _refs_an_id(el: etree._Element, ids: set[str]) -> bool:
    for node in el.iter():
        if not isinstance(node.tag, str):
            continue
        for attr in _POINTER_ATTRS:
            v = node.get(attr)
            if v and any(tok.lstrip("#") in ids for tok in v.split()):
                return True
    return False


def collect_ids(root: etree._Element) -> set[str]:
    return {
        node.get(_XML_ID)
        for node in root.iter()
        if isinstance(node.tag, str) and node.get(_XML_ID)
    }


def prefix_ids(root: etree._Element, prefix: str, ids: set[str] | None = None) -> int:
    """Namespace every ``xml:id`` in ``ids`` (default: those defined in ``root``)
    plus the pointers within ``root`` that reference them — so concatenating
    file 2..N of a multi-file work can't collide with file 1's streamed ids
    (``beg_1``, ``fx…``). Pass the whole file's id set when patching a subtree
    (``<back>``) whose pointers target ids defined in a sibling (``<body>``)."""
    local = ids if ids is not None else collect_ids(root)
    if not local:
        return 0
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        cur = node.get(_XML_ID)
        if cur in local:
            node.set(_XML_ID, prefix + cur)
        for attr in _POINTER_ATTRS:
            v = node.get(attr)
            if not v:
                continue
            toks = [
                ("#" + prefix + t.lstrip("#")) if t.lstrip("#") in local else t
                for t in v.split()
            ]
            if toks != v.split():
                node.set(attr, " ".join(toks))
    return len(local)


def _drop_leading_juan_markers(elements: list[etree._Element]) -> list[etree._Element]:
    out = list(elements)
    if out and out[0].tag == f"{_TEI}milestone" and out[0].get("unit") == JUAN_MILESTONE_UNIT:
        out.pop(0)
    for i, el in enumerate(out[:4]):
        if el.tag == f"{_CB}juan" and el.get("fun") == "open":
            out.pop(i)
            break
    return out


def stitch_cross_file_juan(slices: list[JuanSlice]) -> list[str]:
    """Merge adjacent slices that share a juan ``@n`` — a juan whose continuation
    begins with a repeated ``<milestone unit="juan">`` / ``<cb:juan fun="open">``
    in the next source file of a multi-file work (planning §5.7). The naive
    concat+split already folds *unmarked* continuation content into the previous
    juan; this handles the *re-anchored* case."""
    notes: list[str] = []
    out: list[JuanSlice] = []
    for sl in slices:
        if out and sl.n and out[-1].n == sl.n:
            prev = out[-1]
            prev.elements.extend(_drop_leading_juan_markers(sl.elements))
            if not prev.title and sl.title:
                prev.title = sl.title
            prev.straddles.append(
                f"juan {sl.n}: stitched a cross-file continuation "
                f"(re-anchored <milestone>/<cb:juan> in the next source file)"
            )
            notes.append(f"stitched cross-file juan {sl.n}")
        else:
            out.append(sl)
    slices[:] = out
    return notes


def attach_apparatus(slices: list[JuanSlice], back: etree._Element | None) -> None:
    """Give each slice the ``<back>`` subtree pruned to the apparatus entries that
    reference an ``xml:id`` occurring in that juan (planning §5.5)."""
    if back is None:
        return
    for sl in slices:
        juan_ids = _ids_in(sl.elements)
        if not juan_ids:
            continue
        clone = copy.deepcopy(back)
        kept = 0
        for entry in list(clone.iter(f"{_TEI}app", f"{_TEI}note")):
            parent = entry.getparent()
            if parent is None or parent.tag in (f"{_TEI}app",):
                continue  # nested note inside a kept app — leave it
            if _refs_an_id(entry, juan_ids):
                kept += 1
            else:
                _drop(entry)
        if kept:
            sl.apparatus = [clone]


def _drop(el: etree._Element) -> None:
    parent = el.getparent()
    if parent is not None:
        if el.tail:
            prev = el.getprevious()
            if prev is not None:
                prev.tail = (prev.tail or "") + el.tail
            else:
                parent.text = (parent.text or "") + el.tail
        parent.remove(el)


def _rupture_parent_at(pivot: etree._Element) -> None:
    """Lift ``pivot`` and its following siblings out of a nested parent to ``body`` level."""
    parent = pivot.getparent()
    if parent is None or parent.tag == f"{_TEI}body":
        return
    grand = parent.getparent()
    if grand is None:
        return
    children = list(parent)
    try:
        pivot_i = children.index(pivot)
    except ValueError:
        return
    suffix = children[pivot_i:]
    for el in suffix:
        parent.remove(el)
    insert_pos = list(grand).index(parent) + 1
    for offset, el in enumerate(suffix):
        grand.insert(insert_pos + offset, el)
    if len(parent) == 0 and not (parent.text or "").strip() and not (parent.tail or "").strip():
        grand.remove(parent)


def promote_juan_milestones_to_body(body: etree._Element) -> int:
    """Split nested ``<milestone unit="juan">`` boundaries up to top-level ``<body>`` children."""
    promoted = 0
    while True:
        nested = [
            m
            for m in body.iter()
            if _is_juan_milestone(m) and m.getparent() is not body
        ]
        if not nested:
            break
        _rupture_parent_at(nested[0])
        promoted += 1
    return promoted


def split_body_into_juan(tree: etree._ElementTree | etree._Element) -> list[JuanSlice]:
    body = find_body(tree)
    promote_juan_milestones_to_body(body)
    children = [c for c in body if isinstance(c.tag, str)]

    milestone_idx = [i for i, c in enumerate(children) if _is_juan_milestone(c)]

    # No top-level juan milestones: fall back to cb:juan fun="open" positions,
    # else treat the whole body as a single juan.
    if not milestone_idx:
        opens = _juan_open_blocks(body)
        if opens:
            return _split_on_open_blocks(body, children, opens)
        return [JuanSlice(n="1", elements=[copy.deepcopy(c) for c in children])]

    slices: list[JuanSlice] = []
    bounds = milestone_idx + [len(children)]

    # leading content before the first juan milestone → juan of the first milestone
    lead = [copy.deepcopy(c) for c in children[: milestone_idx[0]]]

    for k in range(len(milestone_idx)):
        start = bounds[k]
        end = bounds[k + 1]
        ms = children[start]
        n = ms.get("n") or str(k + 1)
        block = [copy.deepcopy(c) for c in children[start:end]]
        if k == 0:
            block = lead + block
        sl = JuanSlice(n=n, elements=block)
        _attach_open_block_title(sl)
        _note_straddles(body, ms, sl)
        slices.append(sl)
    return slices


def _split_on_open_blocks(
    body: etree._Element,
    children: list[etree._Element],
    opens: list[etree._Element],
) -> list[JuanSlice]:
    # cb:juan fun="open" blocks are the only boundary signal. Cut before each.
    open_positions: list[int] = []
    for op in opens:
        # find the top-level child that contains this open block
        for i, c in enumerate(children):
            if c is op or op in c.iter():
                open_positions.append(i)
                break
    open_positions = sorted(set(open_positions))
    bounds = open_positions + [len(children)]
    slices: list[JuanSlice] = []
    lead = children[: open_positions[0]] if open_positions else children
    for k, op in enumerate(opens):
        seg = children[bounds[k] : bounds[k + 1]]
        if k == 0:
            seg = lead + seg
        sl = JuanSlice(
            n=op.get("n") or str(k + 1),
            title=_jhead_text(op),
            elements=[copy.deepcopy(c) for c in seg],
        )
        slices.append(sl)
    return slices


def _attach_open_block_title(sl: JuanSlice) -> None:
    for el in sl.elements:
        for op in el.iter(f"{_CB}juan"):
            if op.get("fun") == "open":
                sl.title = _jhead_text(op)
                return


def _note_straddles(body: etree._Element, ms: etree._Element, sl: JuanSlice) -> None:
    """Flag a juan milestone that sits inside a <cb:div> rather than at body level."""
    parent = ms.getparent()
    if parent is not None and parent.tag != f"{_TEI}body":
        where = _local(parent.tag) or "element"
        sl.straddles.append(
            f"juan {sl.n} boundary is inside <{where}>; enclosing block kept "
            f"whole (TODO: split with @part/@prev/@next — planning §5.4)"
        )


def serialize_juan_body(sl: JuanSlice) -> str:
    """Wrap a slice in ``<text><body>…</body>[<back>…</back>]</text>`` and serialize."""
    text = etree.Element(f"{_TEI}text", nsmap={None: TEI_NS, "cb": CB_NS})
    body = etree.SubElement(text, f"{_TEI}body")
    for el in sl.elements:
        body.append(el)
    for el in sl.apparatus:
        text.append(el)  # already a <back> element
    collapse_tree_newlines(text)
    return normalize_serialized_xml(etree.tostring(text, encoding="unicode"))


def split_file(path: str | Path) -> list[JuanSlice]:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    tree = etree.parse(str(path), parser)
    return split_body_into_juan(tree)
