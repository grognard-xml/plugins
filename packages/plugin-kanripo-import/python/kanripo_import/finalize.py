"""Deterministic last-step clean-up of an imported juan body.

Runs after every punctuation step (as-is, parallel, AI) and never calls a model. It must run
*after* AI punctuation, not at convert time: a note that already ends in 。 would read as
"punctuated" to the AI step and be skipped.

1. No paragraph break directly before inline commentary (see ``relocate_leading_comm_notes``).
2. Every ``<note type="comm">`` ends with a terminal mark: 。！？」』. A trailing weak mark
   (，、；：) becomes 。; anything else gets 。 appended.
3. Headings (``head`` / ``byline`` / ``trailer``) carry no punctuation at their end.
4. 註疏 layout (``注`` / ``音義`` / ``疏`` labels before notes): one ``<p>`` per entry, notes typed
   by label (see ``group_zhushu_entries``).
5. Paragraphs that are only manuscript lines are joined (see ``join_wrapped_paragraphs``), except in
   the 考證 (see ``join_outside_kaozheng``).
6. A ``<byline>`` that a ``<head>`` follows at the top of the juan goes in an ``<opener>`` (see
   ``wrap_bylines_before_heads``).
7. Material that follows the juan's ``<trailer>`` (the 考證 collation notes of the Siku files)
   goes in its own div (see ``wrap_after_trailer``).
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
# Trailing page breaks and closing tags: a mark belongs before them, inside the note. A gaiji's
# closing </g> is not one of them: the gaiji is the note's last character, so the mark goes after it.
_NOTE_TAIL_RE = re.compile(r"(?:\s*(?:<pb\b[^>]*/>|</(?!g>)[A-Za-z][^>]*>))*\s*$")


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


_P_RE = re.compile(r"<p>(.*?)</p>", re.DOTALL)
_P_GAP_RE = re.compile(r"\s*")
_PB_RE = re.compile(r"<pb\b[^>]*/>")
_ANY_NOTE_RE = re.compile(r"<note\b[^>]*>.*?</note>", re.DOTALL | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_ENDS_WITH_NOTE_RE = re.compile(r"</note>\s*$")
_SEG_PB_RE = re.compile(r"<pb\b[^>]*/>|</?seg\b[^>]*>")
_SENTENCE_MARKS = "。，、；：？！「」『』"


_GAIJI_RE = re.compile(r"<g\b[^>]*?(?:/>|>.*?</g>)", re.DOTALL)
# A title line of the juan or of its 考證: 前漢書卷一上, 爾雅注疏卷五考證, #+PROPERTY:JUAN卷一上考證.
_TITLE_LINE_RE = re.compile(r"^[^，。、；：？！「」『』]{0,60}(?:卷[^，。、；：？！「」『』]{1,12}|考證)$")


def _visible(paragraph: str, with_notes: bool = False) -> str:
    """The paragraph's text as read: tags dropped (a gaiji stays, as 〓), notes dropped unless asked."""
    text = paragraph if with_notes else _ANY_NOTE_RE.sub("", paragraph)
    return _TAG_RE.sub("", _GAIJI_RE.sub("〓", text)).rstrip()


def _is_title_line(paragraph: str) -> bool:
    return bool(_TITLE_LINE_RE.match(_visible(paragraph, with_notes=True).strip()))


def _has_mark(paragraph: str) -> bool:
    return any(c in _SENTENCE_MARKS for c in _visible(paragraph))


def _continues(content: str) -> bool:
    """True when a paragraph stops short of a sentence end. Tags (the parallel-punctuation <seg>s,
    page breaks) are not text. A title line never continues. A paragraph closed by a note has ended,
    unless the base text before the note stops on a weak mark: ``稱制，<note>…</note>`` goes on."""
    if _is_title_line(content):
        return False
    tail = _visible(content)
    if not tail:
        return False
    if _ENDS_WITH_NOTE_RE.search(_SEG_PB_RE.sub("", content)):
        return tail[-1] in WEAK_MARKS
    return tail[-1] not in TERMINAL_MARKS


def join_wrapped_paragraphs(xml: str) -> str:
    """Join ``<p>`` elements that were split at a manuscript line, not at a paragraph end.

    Kanripo's SKQS files end every physical line with ``¶``, so the importer opens a new ``<p>``
    mid-sentence. A run of directly adjacent paragraphs, each stopping short of a sentence end (no
    terminal mark; a closed note ends its paragraph, as the 注 / 疏 labels each open one), is joined
    with the paragraph that ends it, provided the run carries punctuation somewhere, i.e. the text
    is punctuated there. Wholly unpunctuated stretches keep their paragraphs: nothing says where
    their sentences end.
    """
    matches = list(_P_RE.finditer(xml))
    out: list[str] = []
    pos = 0
    i = 0
    while i < len(matches):
        j = i
        while (
            j + 1 < len(matches)
            and _continues(matches[j].group(1))
            and not _is_title_line(matches[j + 1].group(1))
            and _P_GAP_RE.fullmatch(xml[matches[j].end() : matches[j + 1].start()])
        ):
            j += 1
        if j > i and any(_has_mark(m.group(1)) for m in matches[i : j + 1]):
            out.append(xml[pos : matches[i].start()])
            out.append("<p>" + "".join(m.group(1) for m in matches[i : j + 1]) + "</p>")
            pos = matches[j].end()
        i = j + 1
    out.append(xml[pos:])
    return "".join(out)


# Page breaks and the parallel-punctuation <seg> tags may sit between a label and its note.
_SKIP = r"(?:<pb\b[^>]*/>|</?seg\b[^>]*>)*"
_NOTE_OPEN = r"<note\b[^>]*\btype=\"comm\"[^>]*>"
_NOT_NOTE = r"(?:(?!<note\b)[\s\S])+?"
# A paragraph that opens with a label: the label is followed by its note, or (注 only) by plain 注
# text that runs up to 音義 and its note.
_LABEL_START_RE = re.compile(
    rf"^{_SKIP}(?:注{_SKIP}(?:{_NOTE_OPEN}|{_NOT_NOTE}音義{_SKIP}{_NOTE_OPEN})"
    rf"|音義{_SKIP}{_NOTE_OPEN}|疏{_SKIP}{_NOTE_OPEN})"
)
_ORPHAN_YI_RE = re.compile(rf"^{_SKIP}義{_SKIP}{_NOTE_OPEN}")
_ENDS_YIN_RE = re.compile(r"音[。，、；：]?(?:</seg>)*</note>\s*$")
# 注 text that was left outside a note, up to the 音義 label that follows it.
_PLAIN_ZHU_RE = re.compile(
    rf"(^|[。！？」』]|</note>)({_SKIP})注({_SKIP})((?:(?!<note\b|</?p>)[^<])+?)音義(?={_SKIP}{_NOTE_OPEN})"
)
# A note that swallowed the 音 of 音義 whose 義 starts the next element.
_SPLIT_YIN_RE = re.compile(
    rf"({_NOTE_OPEN})((?:(?!</note>)[\s\S])*?[^>音])音([。，、；：]?)((?:</seg>)*)</note>({_SKIP})義"
    rf"(?={_SKIP}{_NOTE_OPEN})"
)
# A label opens its note after the 経 (which ends in a mark), after another note, or at the start;
# 音義 may carry its lemma as plain text before the note.
_LABEL_NOTE_RE = re.compile(
    rf"(^|</note>|[。！？」』])({_SKIP})(注|音義|疏)({_SKIP}(?:(?<=義){_SKIP}[^<]{{1,8}}{_SKIP})?)(<note\b)(?![^>]*\bsubtype=)"
)
_LABEL_SUBTYPE = {"注": "zhu", "音義": "yinyi", "疏": "shu"}
_MIN_LABELLED = 3


def _is_zhushu_juan(contents: list[str]) -> bool:
    return (
        sum(1 for c in contents if re.match(rf"^{_SKIP}注{_SKIP}{_NOTE_OPEN}", c)) >= _MIN_LABELLED
        and sum(1 for c in contents if re.match(rf"^{_SKIP}疏{_SKIP}{_NOTE_OPEN}", c)) >= _MIN_LABELLED
    )


def _fix_split_yin(match: re.Match[str]) -> str:
    opening, body, closing, skipped = match.group(1, 2, 4, 5)
    body = body.rstrip(WEAK_MARKS)
    if body[-1] not in TERMINAL_MARKS:
        body += "。"
    return f"{opening}{body}{closing}</note>{skipped}音義"


def group_zhushu_entries(xml: str) -> str:
    """Make each 註疏 entry one ``<p>``: the 経 followed by its 注 / 音義 / 疏 notes.

    The Siku 爾雅注疏 breaks lines wherever the column ended, so a label and its note, or the 注,
    音義 and 疏 of one entry, land in separate paragraphs, and 音義 is sometimes cut in two. A
    paragraph that opens with a label joins the paragraph before it; a 義 note left behind by an
    off-by-one 音 is rejoined with its label; plain 注 text before 音義 becomes a note; and each
    label's note is typed (``subtype`` zhu / yinyi / shu). Acts only on a juan with at least 3
    paragraphs opening with 注 and 3 with 疏, so other works are left alone.
    """
    matches = list(_P_RE.finditer(xml))
    if not _is_zhushu_juan([m.group(1) for m in matches]):
        return xml
    out: list[str] = []
    pos = 0
    group: list[str] = []
    group_start = group_end = 0

    def flush() -> None:
        nonlocal pos
        if not group:
            return
        content = "".join(group)
        content = _PLAIN_ZHU_RE.sub(
            lambda m: f'{m.group(1)}{m.group(2)}注{m.group(3)}<note type="comm">{m.group(4)}</note>音義',
            content
        )
        content = _SPLIT_YIN_RE.sub(_fix_split_yin, content)
        content = _LABEL_NOTE_RE.sub(
            lambda m: f'{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)} subtype="{_LABEL_SUBTYPE[m.group(3)]}"',
            content,
        )
        out.append(xml[pos:group_start])
        out.append(f"<p>{content}</p>")
        pos = group_end
        group.clear()

    for m in matches:
        content = m.group(1)
        adjacent = bool(group) and _P_GAP_RE.fullmatch(xml[group_end : m.start()])
        joins = adjacent and (
            _LABEL_START_RE.match(content)
            or (_ORPHAN_YI_RE.match(content) and _ENDS_YIN_RE.search(group[-1]))
        )
        if joins:
            group.append(content)
            group_end = m.end()
            continue
        flush()
        group.append(content)
        group_start, group_end = m.start(), m.end()
    flush()
    out.append(xml[pos:])
    return "".join(out)


_TOP_RUN_RE = re.compile(
    r"(<div\b[^>]*>)((?:\s*<(?:head|byline)\b[^>]*>.*?</(?:head|byline)>)+)", re.DOTALL
)
_TOP_ITEM_RE = re.compile(r"\s*<(head|byline)\b[^>]*>.*?</\1>", re.DOTALL)


def wrap_bylines_before_heads(xml: str) -> str:
    """Put each run of ``<byline>`` in an ``<opener>`` when a ``<head>`` comes after it.

    TEI lets a div open with heads and openers in any order but a byline only after all its heads,
    while a Siku juan reads: 欽定四庫全書, title, author, commentator, 本紀 title. Wrapping the
    bylines in ``<opener>``, which may hold them and sits among the heads, keeps the reading order
    and makes the juan valid. A juan whose bylines follow its last head is left as it is.
    """
    match = _TOP_RUN_RE.search(xml)
    if not match:
        return xml
    items = [(m.group(1), m.group(0)) for m in _TOP_ITEM_RE.finditer(match.group(2))]
    kinds = [kind for kind, _ in items]
    if "byline" not in kinds or "head" not in kinds[kinds.index("byline") :]:
        return xml
    out: list[str] = []
    run: list[str] = []
    for kind, text in items:
        if kind == "byline":
            run.append(text.strip())
            continue
        if run:
            out.append("<opener>" + "".join(run) + "</opener>")
            run = []
        out.append(text)
    if run:
        out.append("<opener>" + "".join(run) + "</opener>")
    return xml[: match.start(2)] + "".join(out) + xml[match.end(2) :]


def wrap_after_trailer(xml: str) -> str:
    """Move what follows the juan's ``<trailer>`` into a ``<div type="kaozheng">``.

    TEI ends a div at its trailer: a ``<p>`` after it is invalid. The Siku files append the
    考證 (collation notes) after the trailer, so the juan's own content goes in a
    ``<div type="text">`` and the appended notes in a sibling ``<div type="kaozheng">``, both
    inside the juan div. Reading order is unchanged. Acts once: not if the juan already holds divs.
    """
    open_end = xml.find(">") + 1
    close_start = xml.rfind("</div>")
    if not xml.startswith("<div") or close_start < open_end or "<div" in xml[open_end:close_start]:
        return xml
    inner = xml[open_end:close_start]
    trailer = list(re.finditer(r"</trailer>", inner))
    if not trailer:
        return xml
    cut = trailer[-1].end()
    before, after = inner[:cut], inner[cut:]
    if "<p" not in after:
        return xml
    return (
        xml[:open_end]
        + f'<div type="text">{before}</div><div type="kaozheng">{after.lstrip()}</div>'
        + xml[close_start:]
    )


_KAOZHENG_TITLE_RE = re.compile(r"考證$")


def _is_kaozheng_juan(xml: str) -> bool:
    """True for a juan file that is wholly 考證 (collation notes), as in 爾雅注疏: its first line, a
    title, ends in 考證."""
    first = _P_RE.search(xml)
    return bool(first) and bool(_KAOZHENG_TITLE_RE.search(_visible(first.group(1), with_notes=True).strip()))


def join_outside_kaozheng(xml: str) -> str:
    """``join_wrapped_paragraphs`` for the juan's own text only.

    The 考證 are lists of lemma ○ comment, mostly unpunctuated, one source line per paragraph.
    A mark inside one comment would make the join run on through the lemmas around it into
    blobs of thousands of characters, so a 考證 juan, and the ``<div type="kaozheng">`` that follows
    a trailer, keep their paragraphs as the source lines gave them.
    """
    if _is_kaozheng_juan(xml):
        return xml
    cut = xml.find('<div type="kaozheng">')
    if cut < 0:
        return join_wrapped_paragraphs(xml)
    return join_wrapped_paragraphs(xml[:cut]) + xml[cut:]


def _finalize_once(xml: str) -> str:
    xml = relocate_leading_comm_notes(merge_split_comm_notes(xml))
    xml = terminate_comm_notes(xml)
    xml = strip_heading_trailing_punct(xml)
    xml = terminate_comm_notes(group_zhushu_entries(xml))
    xml = wrap_after_trailer(xml)
    xml = join_outside_kaozheng(xml)
    return wrap_bylines_before_heads(xml)


def finalize_body(body_xml: str) -> str:
    """Apply the rules until they settle (a join can complete a run's punctuation, letting its
    neighbour join on the next pass); return the input unchanged if the result is not well-formed
    or would alter any Han character."""
    merged = merge_split_comm_notes(body_xml)
    xml = merged
    for _ in range(100):
        following = _finalize_once(xml)
        if following == xml:
            break
        xml = following
    try:
        assert_well_formed(xml)
    except ET.ParseError:
        return body_xml
    if han_only(xml) != han_only(merged):
        return body_xml
    return xml


def bridge_finalize_body(payload: dict) -> dict:
    return {"body_xml": finalize_body(str(payload.get("body_xml") or ""))}
