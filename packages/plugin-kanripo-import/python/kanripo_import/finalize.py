"""Deterministic last-step clean-up of an imported juan body.

Runs after every punctuation step (as-is, parallel, AI) and never calls a model. It must run
*after* AI punctuation, not at convert time: a note that already ends in 。 would read as
"punctuated" to the AI step and be skipped.

1. No paragraph break directly before inline commentary (see ``relocate_leading_comm_notes``).
2. Every ``<note type="comm">`` ends with a terminal mark: 。！？」』. A trailing weak mark
   (，、；：) becomes 。; anything else gets 。 appended.
3. Headings (``head`` / ``byline`` / ``trailer``) carry no punctuation at their end.
4. 註疏 layout (``注`` / ``音義`` / ``疏`` labels before notes): one ``<p>`` per entry, notes typed
   by label (see ``group_zhushu_entries``), then laid out as the entry with its 注 in one paragraph and
   the 音義 / 疏 in the next (see ``layout_zhushu_paragraphs``).
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
    if _is_title_line(content) or _STARTS_SUB_RE.match(content):
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
            and not _STARTS_SUB_RE.match(matches[j + 1].group(1))
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


# --- 註疏 layout: the entry with its 注 in one paragraph, the 音義 / 疏 in the next -----------------

_NOTE_SPLIT_RE = re.compile(r"(<note\b[^>]*>.*?</note>)", re.DOTALL)
_INLINE_SKIP = r"(?:<pb\b[^>]*/>|</?seg\b[^>]*>)*"
# The end of a text run that is a 音義 / 疏 label (音義 may carry its lemma: 音義底畛<note>…).
_SUBLABEL_TAIL_RE = re.compile(
    r"(?:音義(?:<pb\b[^>]*/>)?[^<，。、；：？！「」『』（）]{0,8}|疏)" + _INLINE_SKIP + r"\Z"
)
_ONLY_SUBLABEL_RE = re.compile(rf"\A\s*{_INLINE_SKIP}(?:音義|疏|義){_INLINE_SKIP}\s*\Z")
_STARTS_ZHU_RE = re.compile(
    rf"\A(?:\s|<pb\b[^>]*/>|</?seg\b[^>]*>)*(?:<note\b[^>]*\bsubtype=\"zhu\"|注{_INLINE_SKIP}<note\b)"
)
_STARTS_SUB_RE = re.compile(
    rf"\A(?:\s|<pb\b[^>]*/>|</?seg\b[^>]*>)*(?:音義[^<]{{0,8}}|疏|義){_INLINE_SKIP}<note\b"
)
_ONLY_TAGS_RE = re.compile(rf"\A\s*{_INLINE_SKIP}\s*\Z")
_TRAILING_PBS_RE = re.compile(r"(?:<pb\b[^>]*/>)+\Z")
_OPEN_TAG_RE = re.compile(r"<(/?)([A-Za-z][\w:.-]*)\b[^>]*?(/?)>")


def _balanced(fragment: str) -> bool:
    """True when every element opened in the fragment is closed in it, and none closes unopened."""
    stack: list[str] = []
    for closing, name, selfclosing in _OPEN_TAG_RE.findall(fragment):
        if selfclosing:
            continue
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


def _split_entry_and_subcommentary(content: str) -> list[tuple[str, str]] | None:
    """Cut one paragraph into ``("entry", …)`` and ``("sub", …)`` pieces, in order.

    A piece of kind "sub" starts at a 音義 or 疏 label that is followed by its note and holds
    the labels and notes after it; anything that is not a label after a sub note starts an entry
    again. Returns None when a cut would fall inside an element (so nothing is split).
    """
    parts = _NOTE_SPLIT_RE.split(content)
    pieces: list[list[str]] = []  # [kind, raw]
    kind = "entry"

    def add(piece_kind: str, raw: str) -> None:
        if raw == "":
            return
        if pieces and pieces[-1][0] == piece_kind:
            pieces[-1][1] += raw
        else:
            pieces.append([piece_kind, raw])

    for index, part in enumerate(parts):
        if index % 2 == 1:
            add(kind, part)
            continue
        note_follows = index < len(parts) - 1
        if kind == "sub" and (_ONLY_SUBLABEL_RE.match(part) or not part.strip()):
            add("sub", part)
            continue
        label = _SUBLABEL_TAIL_RE.search(part) if note_follows else None
        if label:
            head, tail = part[: label.start()], part[label.start() :]
            if _ONLY_TAGS_RE.match(head):
                # only page breaks (or whitespace) before the label: they belong with it
                kind = "sub"
                add("sub", head + tail)
                continue
            if head.strip() or kind == "sub":
                kind = "entry"
                add("entry", head)
            elif head:
                add("entry" if pieces else "sub", head)
            kind = "sub"
            add("sub", tail)
        else:
            kind = "entry"
            add("entry", part)
    if all(_balanced(raw) for _, raw in pieces):
        return [(k, raw) for k, raw in pieces]
    return None


def _paragraph_runs(xml: str, matches: list) -> list[list]:
    """The paragraphs split into runs of directly adjacent ones (only whitespace between)."""
    runs: list[list] = []
    for m in matches:
        if runs and _P_GAP_RE.fullmatch(xml[runs[-1][-1].end() : m.start()]):
            runs[-1].append(m)
        else:
            runs.append([m])
    return runs


def _move_page_breaks_to_labels(pieces: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """A page break at the end of an entry piece, right before a sub piece, goes with the sub piece."""
    out = [list(piece) for piece in pieces]
    for i in range(1, len(out)):
        if out[i][0] == "sub" and out[i - 1][0] == "entry":
            tail = _TRAILING_PBS_RE.search(out[i - 1][1])
            if tail and tail.start() > 0:
                out[i - 1][1] = out[i - 1][1][: tail.start()]
                out[i][1] = tail.group(0) + out[i][1]
    return [(k, raw) for k, raw in out]


def _layout_run(run_xml: list[tuple[str, str]]) -> list[list]:
    """[kind, raw, gap] for the pieces of one run, given each paragraph's (content, gap before)."""
    items: list[list] = []
    for content, gap in run_xml:
        pieces = _split_entry_and_subcommentary(content)
        pieces = _move_page_breaks_to_labels(pieces) if pieces else [("entry", content)]
        for piece_kind, raw in pieces:
            items.append([piece_kind, raw, gap])
    merged: list[list] = []
    for piece_kind, raw, gap in items:
        if merged:
            last = merged[-1]
            if piece_kind == "sub" and last[0] == "sub":
                last[1] += raw
                continue
            if piece_kind == "sub" and last[0] == "entry" and _ONLY_TAGS_RE.match(last[1]):
                last[0], last[1] = "sub", last[1] + raw  # a paragraph of just a page break
                continue
            if piece_kind == "entry" and last[0] == "entry" and _STARTS_ZHU_RE.match(raw):
                last[1] += raw
                continue
        merged.append([piece_kind, raw, gap])
    return merged


def layout_zhushu_paragraphs(xml: str) -> str:
    """Lay a 註疏 juan out as: the 経 with its 注 in one ``<p>``, the 音義 and 疏 after it in one.

    Only paragraph boundaries move; no character, tag or attribute changes. A paragraph that opens
    with a 注 (a note typed zhu, or the label 注 and its note) joins the paragraph before it, so
    the 注 is always inline with the 経 it explains; the 音義 / 疏 labels and notes that follow
    an entry are cut into a paragraph of their own, and consecutive such paragraphs become one. A
    page break just before a label goes with the label. A paragraph whose cut would fall inside
    an element is left as it is. Acts only on a juan with at least 3 sub-commentary paragraphs and
    3 注, and not on a 考證 juan.
    """
    if _is_kaozheng_juan(xml):
        return xml
    matches = list(_P_RE.finditer(xml))
    runs = _paragraph_runs(xml, matches)
    layouts = []
    for run in runs:
        run_xml = []
        previous_end = run[0].start()
        for m in run:
            run_xml.append((m.group(1), xml[previous_end : m.start()]))
            previous_end = m.end()
        layouts.append(_layout_run(run_xml))
    subs = sum(1 for layout in layouts for kind, _, _ in layout if kind == "sub")
    zhus = sum(len(re.findall(r'subtype="zhu"', raw)) + len(re.findall(rf"注{_INLINE_SKIP}<note\b", raw)) for layout in layouts for _, raw, _ in layout)
    if subs < 3 or zhus < 3:
        return xml
    out: list[str] = []
    cursor = 0
    for run, layout in zip(runs, layouts):
        out.append(xml[cursor : run[0].start()])
        gaps = [gap for _, _, gap in layout]
        filler = next((g for g in gaps if g), "")
        for index, (_, raw, gap) in enumerate(layout):
            out.append("" if index == 0 else gap or filler)
            out.append(f"<p>{raw}</p>")
        cursor = run[-1].end()
    out.append(xml[cursor:])
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
    xml = layout_zhushu_paragraphs(terminate_comm_notes(group_zhushu_entries(xml)))
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
