"""Deterministic last-step clean-up of an imported juan body.

Runs after every punctuation step (as-is, parallel, AI) and never calls a model. It must run
*after* AI punctuation, not at convert time: a note that already ends in 。 would read as
"punctuated" to the AI step and be skipped.

1. No paragraph break directly before inline commentary (see ``relocate_leading_comm_notes``).
2. Every ``<note type="comm">`` ends with a terminal mark: 。！？」』. A trailing weak mark
   (，、；：) becomes 。; anything else gets 。 appended.
3. Headings (``head`` / ``byline`` / ``trailer``) carry no punctuation at their end.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from kanripo_import.parallel_punct import (
    HAN_RE,
    assert_well_formed,
    han_only,
    merge_split_comm_notes,
    relocate_leading_comm_notes,
)

TERMINAL_MARKS = "。！？」』”’"
WEAK_MARKS = "，、；：,;:"
_HEADING_TRAILING_RE = re.compile(r"[。，、；：？！·.,;:?!\s　]+$")
_HEADING_RE = re.compile(r"(<(head|byline|trailer)\b[^>]*>)(.*?)(</\2>)", re.DOTALL | re.I)
_COMM_NOTE_RE = re.compile(r"(<note\b[^>]*\btype=\"comm\"[^>]*>)(.*?)(</note>)", re.DOTALL | re.I)
# Trailing page breaks and closing tags: a mark belongs before them, inside the note.
_NOTE_TAIL_RE = re.compile(r"(?:\s*(?:<pb\b[^>]*/>|</[A-Za-z][^>]*>))*\s*$")


def _terminate_note_content(content: str) -> str:
    tail = _NOTE_TAIL_RE.search(content)
    cut = tail.start() if tail else len(content)
    body = content[:cut]
    if not HAN_RE.search(re.sub(r"<[^>]+>", "", body)):
        return content
    if body.endswith(">"):
        # An element (gaiji, graphic) ends the note: the visible last character is not text.
        return body + "。" + content[cut:]
    last = body[-1]
    if last in TERMINAL_MARKS:
        return content
    if last in WEAK_MARKS:
        return body[:-1] + "。" + content[cut:]
    return body + "。" + content[cut:]


def terminate_comm_notes(xml: str) -> str:
    return _COMM_NOTE_RE.sub(
        lambda m: m.group(1) + _terminate_note_content(m.group(2)) + m.group(3), xml
    )


def strip_heading_trailing_punct(xml: str) -> str:
    return _HEADING_RE.sub(
        lambda m: m.group(1) + _HEADING_TRAILING_RE.sub("", m.group(3)) + m.group(4), xml
    )


def finalize_body(body_xml: str) -> str:
    """Apply the three rules; return the input unchanged if the result is not well-formed
    or would alter any Han character."""
    merged = merge_split_comm_notes(body_xml)
    xml = relocate_leading_comm_notes(merged)
    xml = terminate_comm_notes(xml)
    xml = strip_heading_trailing_punct(xml)
    try:
        assert_well_formed(xml)
    except ET.ParseError:
        return body_xml
    if han_only(xml) != han_only(merged):
        return body_xml
    return xml


def bridge_finalize_body(payload: dict) -> dict:
    return {"body_xml": finalize_body(str(payload.get("body_xml") or ""))}
