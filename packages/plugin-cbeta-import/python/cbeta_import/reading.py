"""Optional reading-edition reductions for CBETA import."""

from __future__ import annotations

from lxml import etree

from cbeta_import.constants import TEI_NS

_TEI = f"{{{TEI_NS}}}"


def _unwrap_empty(el: etree._Element) -> None:
    parent = el.getparent()
    if parent is None:
        return
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def strip_collation_anchors(root: etree._Element) -> int:
    """Remove inline apparatus anchor milestones from the body."""
    removed = 0
    for el in list(root.iter(f"{_TEI}anchor")):
        _unwrap_empty(el)
        removed += 1
    return removed


def strip_line_breaks(root: etree._Element) -> int:
    """Drop Taishō ``<lb>`` milestones; keep ``<pb>`` page breaks."""
    removed = 0
    for el in list(root.iter(f"{_TEI}lb")):
        _unwrap_empty(el)
        removed += 1
    return removed


def apply_reading_options(
    holder: etree._Element,
    *,
    clean: bool,
    strip_lb: bool,
) -> dict[str, int]:
    report: dict[str, int] = {}
    if clean:
        report["collation_anchors_removed"] = strip_collation_anchors(holder)
    if strip_lb:
        report["line_breaks_removed"] = strip_line_breaks(holder)
    return report
