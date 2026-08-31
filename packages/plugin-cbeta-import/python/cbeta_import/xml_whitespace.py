"""Normalize excessive vertical whitespace in imported TEI.

CBETA apparatus paragraphs sometimes carry thousands of blank lines in the
source. Cap consecutive newlines so imported files stay usable in source mode.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lxml import etree

_MAX_CONSECUTIVE_NEWLINES = 2
_NL_RUN = re.compile(r"\n{3,}")


def collapse_excess_newlines(text: str, *, max_run: int = _MAX_CONSECUTIVE_NEWLINES) -> str:
    """Replace runs of more than ``max_run`` consecutive newlines with ``max_run``."""
    if max_run < 1:
        max_run = 1
    cap = "\n" * max_run
    return _NL_RUN.sub(cap, text)


def collapse_tree_newlines(root: etree._Element, *, max_run: int = _MAX_CONSECUTIVE_NEWLINES) -> int:
    """Collapse newline runs in every ``.text`` and ``.tail`` under ``root``."""
    changed = 0
    for el in root.iter():
        if el.text:
            next_text = collapse_excess_newlines(el.text, max_run=max_run)
            if next_text != el.text:
                el.text = next_text
                changed += 1
        if el.tail:
            next_tail = collapse_excess_newlines(el.tail, max_run=max_run)
            if next_tail != el.tail:
                el.tail = next_tail
                changed += 1
    return changed


def normalize_serialized_xml(xml: str, *, max_run: int = _MAX_CONSECUTIVE_NEWLINES) -> str:
    """Safety pass on serialized markup (inter-tag formatting as well as text)."""
    return collapse_excess_newlines(xml, max_run=max_run)
