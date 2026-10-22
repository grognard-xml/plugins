"""Give a body the paragraphs of a parallel edition, replacing its line-wrap breaks.

Kanripo's print-line texts open a ``<p>`` at every manuscript line, so a sentence is cut in two and
two entries or mountains may share a paragraph. A parallel such as Wikisource sets each entry,
mountain or kingdom as a paragraph of its own (a blank line in the parallel text). The punctuation
transfer (``apply_parallel_aligned``) adds the parallel's breaks but never takes the body's own away;
this does, for the stretches where the two editions agree:

* the base text of the body (notes, heads and markup left out; a gaiji counts as one unknown
  character) is aligned character by character with the base text of the parallel's paragraphs;
* each paragraph start of the parallel is carried over to the body wherever the alignment is sure of
  the characters on both sides of it (exact, or one to one with a differing character, or on one
  side only), and a break goes there, after the notes that follow the paragraph's last character and
  before a page break that precedes the next;
* a body break is removed only if both characters next to it align and lie in one parallel paragraph;
  a break the alignment cannot judge stays; a break that would cut an element (a stamp, a ``<hi>``)
  is not made.

Only ``</p><p>`` boundaries change, never a character or another tag, and nothing is done unless the
parallel has paragraphs, the editions agree over most of the text and the result is well formed.
"""

from __future__ import annotations

import difflib
import re
from typing import TypedDict

HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003ffff]")
GAP = "〓"
MIN_PARAGRAPHS = 3
MIN_AGREEMENT = 0.6
MAX_TAPE = 40_000  # characters on either side: difflib is quadratic in the worst case
_BLANK_RE = re.compile(r"\n\s*\n+")
_COMMENTARY_RE = re.compile(r"（[^（）]*）|\([^()]*\)")
_TOKEN = re.compile(
    r"(?P<block><note\b[^>]*>.*?</note>|<head\b[^>]*>.*?</head>)"
    r"|(?P<g><g\b[^>]*?(?:/>|>.*?</g>))"
    r"|(?P<tag><[^>]+>)|(?P<ch>.)",
    re.DOTALL,
)
_BREAK = re.compile(r"</p>\s*<p\b[^>]*>")


class ReflowResult(TypedDict):
    body_xml: str
    applied: bool
    added: int
    removed: int
    reason: str


def parallel_paragraphs(parallel_text: str) -> list[str]:
    """Han text of each paragraph of the parallel: blank-line blocks, commentary left out."""
    from kanripo_import.parallel_punct import _clean_parallel_for_alignment, _commentary_as_parentheses

    normalized = _commentary_as_parentheses(parallel_text.replace("\r\n", "\n").replace("\r", "\n"))
    out = []
    for block in _BLANK_RE.split(normalized.strip()):
        for _ in range(3):  # nested brackets, innermost first
            block = _COMMENTARY_RE.sub("", block)
        han = "".join(HAN_RE.findall(_clean_parallel_for_alignment(block)))
        if han:
            out.append(han)
    return out


def _tokens(body: str):
    out: list[tuple[str, int, int]] = []
    for m in _TOKEN.finditer(body):
        if m.group("g"):
            out.append((GAP, m.start(), m.end()))
        elif m.group("ch") and HAN_RE.match(m.group("ch")):
            out.append((m.group("ch"), m.start(), m.end()))
    return out


def _balanced(fragment: str) -> bool:
    stack: list[str] = []
    for closing, name, selfclosing in re.findall(r"<(/?)([A-Za-z][\w:.-]*)\b[^>]*?(/?)>", fragment):
        if selfclosing:
            continue
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


def _cut_position(body: str, toks, index: int) -> int:
    """Where in ``body`` a break before base character ``index`` goes: before that character,
    moved back over the page breaks and whitespace that touch it."""
    position = toks[index][1]
    while True:
        m = re.search(r"(?:<pb\b[^>]*/>|\s)+\Z", body[:position])
        if not m or m.start() == position:
            return position
        position = m.start()


def _cut_is_whole(body: str, cut: int) -> bool:
    """True when a break at ``cut`` leaves whole elements on both sides within its paragraph."""
    opens = list(re.finditer(r"<p\b[^>]*>", body[:cut]))
    if not opens or "</p>" in body[opens[-1].end() : cut]:
        return False  # not inside a paragraph
    return _balanced(body[opens[-1].end() : cut])


def reflow_to_parallel(body_xml: str, parallel_text: str) -> ReflowResult:
    """``body_xml`` with its paragraph breaks replaced by the parallel's where they align."""
    def unchanged(reason: str) -> ReflowResult:
        return {"body_xml": body_xml, "applied": False, "added": 0, "removed": 0, "reason": reason}

    entries = parallel_paragraphs(parallel_text)
    if len(entries) < MIN_PARAGRAPHS:
        return unchanged("the parallel has no paragraphs")
    toks = _tokens(body_xml)
    ours = "".join(c for c, _, _ in toks)
    ct = "".join(entries)
    if not ours or len(ours) > MAX_TAPE or len(ct) > MAX_TAPE:
        return unchanged("nothing to align or too long")
    matcher = difflib.SequenceMatcher(None, ours, ct, autojunk=False)
    exact: dict[int, int] = {}
    loose: dict[int, int] = {}
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(b2 - b1):
                exact[b1 + k] = loose[b1 + k] = a1 + k
        elif tag == "replace" and a2 - a1 == b2 - b1:
            for k in range(b2 - b1):
                loose[b1 + k] = a1 + k
    if len(exact) / max(1, min(len(ours), len(ct))) < MIN_AGREEMENT:
        return unchanged("the two editions agree over too little of the text")
    to_parallel = {a: b for b, a in loose.items()}

    starts: list[int] = []
    position = 0
    for entry in entries:
        starts.append(position)
        position += len(entry)
    start_set = set(starts)

    cuts: set[int] = set()
    for s in starts:
        if s == 0:  # the first paragraph: a break before it only if our text has a title block ahead
            index = loose.get(0)
        elif s in loose and s - 1 in loose and loose[s] == loose[s - 1] + 1:
            index = loose[s]
        elif s in loose:
            index = loose[s]
        elif s - 1 in loose:
            index = loose[s - 1] + 1
        else:
            continue
        if index is not None and 0 < index < len(toks):
            cuts.add(_cut_position(body_xml, toks, index))

    edits: list[tuple[int, int, str]] = []
    removed = 0
    kept_at_cut: set[int] = set()
    for m in _BREAK.finditer(body_xml):
        near = [c for c in cuts if m.start() <= c <= m.end()]
        if near:
            kept_at_cut.update(near)
            continue
        before = sum(1 for _, s, _ in toks if s < m.start())  # base characters before the break
        left, right = before - 1, before
        if left in to_parallel and right in to_parallel:
            a, b = to_parallel[left], to_parallel[right]
            if b == a + 1 and b not in start_set:  # inside one parallel paragraph: a line wrap
                edits.append((m.start(), m.end(), ""))
                removed += 1
    indent = "\n" + m.group(1) if (m := re.search(r"\n([ \t]*)<p\b", body_xml)) else ""
    added = 0
    for cut in sorted(cuts - kept_at_cut):
        if _cut_is_whole(body_xml, cut):
            edits.append((cut, cut, "</p>" + indent + "<p>"))
            added += 1
    if not edits:
        return unchanged("already as the parallel has it")

    out: list[str] = []
    cursor = 0
    for start, end, text in sorted(edits):
        out.append(body_xml[cursor:start])
        out.append(text)
        cursor = end
    out.append(body_xml[cursor:])
    result = "".join(out)
    if not all(_balanced(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", result, re.DOTALL)):
        return unchanged("a break would cut an element")
    strip = lambda x: re.sub(r"\s+", "", re.sub(r"</?p\b[^>]*>", "", x))  # noqa: E731
    if strip(result) != strip(body_xml):
        return unchanged("text or tags other than <p> would change")
    return {"body_xml": result, "applied": True, "added": added, "removed": removed, "reason": ""}
