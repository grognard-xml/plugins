"""Infix / superset overlap: copy punctuation from a parallel onto Kanripo TEI.

The Kanripo ``body_xml`` is the tape. The parallel is often a shorter sticker.
Unmatched prefix/suffix stay as-is. Wrong text → no overlap (empty coverage).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TypedDict
from xml.etree import ElementTree as ET

HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
PUNCT_CHARS = set("。，、：；？！「」『』（）〔〕.,;:!?")
# Marker for a stretch whose punctuation was copied from a parallel witness.
# Carried on `<seg type="…">`, not `@ana`: the CBETA P5 customization drops
# `att.global.analytic` entirely (no `@ana` on any element), and even in
# TEI-all `@ana` is `data.pointer` — a bare token like this is not a valid
# value there. `type` is `data.name`, which `ljb:parallel-punct` satisfies,
# and it is allowed on `<seg>` in both schemas.
SEG_MARK = "ljb:parallel-punct"
SEG_OPEN = f'<seg type="{SEG_MARK}">'
NOTE_RE = re.compile(r"<note\b[^>]*>.*?</note>", re.DOTALL)
NOTE_OPEN_COMM_RE = re.compile(r'<note\b[^>]*\btype="comm"[^>]*>', re.I)
NOTE_CLOSE_RE = re.compile(r"</note>")
SPLIT_COMM_RE = re.compile(r"</note></p><p><note\b[^>]*\btype=\"comm\"[^>]*>", re.I)
INLINE_COMM_RE = re.compile(r'<span\b[^>]*\bclass="inlinecomment"[^>]*>(.*?)</span>', re.DOTALL | re.I)
WIKISOURCE_COMM_RE = re.compile(r"〈[^〉]*〉")
PB_RE = re.compile(r"<pb\b[^>]*/>")
TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
# Accept legacy `ana="…"` too, so coverage can still be rebuilt from files
# imported before the switch to `type`.
SEG_OPEN_RE = re.compile(r'<seg\b[^>]*\b(?:type|ana)="[^"]*\bljb:parallel-punct[^"]*"[^>]*>')
MIN_BLOCK = 8
MIN_STICKER_COVER = 0.8
MAX_TAPE_GAP = 20
SENTENCE_END_PUNCT = frozenset("。！？")
LOW_OVERLAP_RATIO = 0.30
MIN_HAN_FOR_PUNCT_CHECK = 40
MIN_PUNCT_PER_100_HAN = 0.75


class CoverageSpan(TypedDict):
    start: float
    end: float
    covered_chars: int
    source: str
    preview: str


class Coverage(TypedDict):
    start: float
    end: float
    covered_chars: int
    total_chars: int
    ratio: float
    empty: bool
    spans: list[CoverageSpan]


class ParallelPunctResult(TypedDict):
    body_xml: str
    coverage: Coverage
    applied: bool


class ParallelQualityWarning(TypedDict):
    code: str
    severity: str
    message: str


class BodySegment(TypedDict):
    kind: str
    atom_indices: list[int]
    han: str


class RefSegment(TypedDict):
    kind: str
    text: str


def han_only(text: str) -> str:
    return "".join(HAN_RE.findall(text))


def _empty_coverage(total: int) -> Coverage:
    return {
        "start": 0.0,
        "end": 0.0,
        "covered_chars": 0,
        "total_chars": total,
        "ratio": 0.0,
        "empty": True,
        "spans": [],
    }


def _union_covered(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    merged: list[list[int]] = [list(ordered[0])]
    for start, end in ordered[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def _coverage_from_intervals(
    total: int, intervals: list[tuple[int, int]], spans: list[CoverageSpan]
) -> Coverage:
    covered = _union_covered(intervals)
    if not intervals or not total:
        return _empty_coverage(total)
    start = min(item[0] for item in intervals)
    end = max(item[1] for item in intervals)
    return {
        "start": start / total,
        "end": end / total,
        "covered_chars": covered,
        "total_chars": total,
        "ratio": covered / total,
        "empty": covered == 0,
        "spans": spans,
    }


def merge_split_comm_notes(body_xml: str) -> str:
    """Join commentary notes split across ``</p><p>`` (no breaks inside interlinear comm)."""
    return SPLIT_COMM_RE.sub("", body_xml)


def strip_wikisource_commentary(parallel_text: str) -> str:
    """Drop Wikisource interlinear notes in corner brackets for main-text matching."""
    return WIKISOURCE_COMM_RE.sub("", parallel_text)


def _merged_tape_span(blocks: list, tape_len: int) -> tuple[int, int, int] | None:
    """Merge nearby match blocks on the tape axis; return best (start, end, matched_chars)."""
    if not blocks:
        return None
    ordered = sorted(blocks, key=lambda block: block.b)
    spans: list[tuple[int, int, int]] = []
    start = ordered[0].b
    end = ordered[0].b + ordered[0].size
    matched = ordered[0].size
    for block in ordered[1:]:
        gap = block.b - end
        if gap <= MAX_TAPE_GAP:
            end = max(end, block.b + block.size)
            matched += block.size
            continue
        spans.append((start, end, matched))
        start = block.b
        end = block.b + block.size
        matched = block.size
    spans.append((start, end, matched))
    return max(spans, key=lambda item: item[2])


def find_han_overlap_from(tape: str, sticker: str, start: int = 0) -> tuple[int, int] | None:
    """Like ``find_han_overlap`` but search ``tape[start:]`` and return absolute indices."""
    if start < 0 or start >= len(tape):
        return None
    overlap = find_han_overlap(tape[start:], sticker)
    if overlap is None:
        return None
    rel_start, rel_end = overlap
    return start + rel_start, start + rel_end


def find_han_overlap(tape: str, sticker: str) -> tuple[int, int] | None:
    """Return ``(tape_start, tape_end)`` han indices, or None."""
    if not tape or not sticker:
        return None
    if len(sticker) <= len(tape):
        exact = tape.find(sticker)
        if exact >= 0:
            return exact, exact + len(sticker)
        matcher = SequenceMatcher(a=tape, b=sticker, autojunk=False)
        all_blocks = [block for block in matcher.get_matching_blocks() if block.size > 0]
        if not all_blocks:
            return None
        blocks = [block for block in all_blocks if block.size >= MIN_BLOCK]
        if blocks:
            best = max(blocks, key=lambda block: block.size)
            if best.size / len(sticker) >= MIN_STICKER_COVER:
                return best.a, best.a + best.size
        sticker_intervals = [(block.b, block.b + block.size) for block in all_blocks]
        if _union_covered(sticker_intervals) / len(sticker) >= MIN_STICKER_COVER:
            tape_intervals = [(block.a, block.a + block.size) for block in all_blocks]
            return min(item[0] for item in tape_intervals), max(item[1] for item in tape_intervals)
        return None
    exact = sticker.find(tape)
    if exact >= 0:
        return 0, len(tape)
    matcher = SequenceMatcher(a=sticker, b=tape, autojunk=False)
    all_blocks = [block for block in matcher.get_matching_blocks() if block.size > 0]
    blocks = [block for block in all_blocks if block.size >= MIN_BLOCK]
    if not blocks:
        blocks = [block for block in all_blocks if block.size >= 6]
    if not all_blocks:
        return None
    merged = _merged_tape_span(blocks, len(tape)) if blocks else None
    if merged is not None:
        tape_start, tape_end, matched = merged
        if matched / len(tape) >= MIN_STICKER_COVER:
            return tape_start, tape_end
    intervals = [(block.b, block.b + block.size) for block in all_blocks]
    covered = _union_covered(intervals)
    if covered / len(tape) >= MIN_STICKER_COVER:
        return min(item[0] for item in intervals), max(item[1] for item in intervals)
    return None


def find_han_overlap_flexible(tape: str, sticker: str) -> tuple[int, int] | None:
    """Like ``find_han_overlap`` but retry after each chapter head marker in the tape."""
    overlap = find_han_overlap(tape, sticker)
    if overlap is not None:
        return overlap
    search_at = 0
    markers = "篇紀傳志卷"
    while search_at < len(tape):
        next_at = len(tape)
        for marker in markers:
            index = tape.find(marker, search_at)
            if index >= 0:
                next_at = min(next_at, index + 1)
        if next_at >= len(tape):
            break
        start = next_at
        search_at = start
        overlap = find_han_overlap(tape[start:], sticker)
        if overlap is not None:
            rel_start, rel_end = overlap
            return start + rel_start, start + rel_end
    return None


def _append_xml_atom(xml: str, i: int, atoms: list[str]) -> int:
    if xml.startswith("<", i):
        pb = PB_RE.match(xml, i)
        if pb:
            atoms.append(pb.group(0))
            return pb.end()
        tag = TAG_RE.match(xml, i)
        if tag:
            atoms.append(tag.group(0))
            return tag.end()
    atoms.append(xml[i])
    return i + 1


def _iter_xml_atoms_segmented(xml: str) -> list[str]:
    """Like ``_iter_xml_atoms`` but expand ``<note type="comm">`` innards for segment Han."""
    atoms: list[str] = []
    i = 0
    n = len(xml)
    while i < n:
        if xml.startswith("<", i):
            comm_open = NOTE_OPEN_COMM_RE.match(xml, i)
            if comm_open:
                atoms.append(comm_open.group(0))
                i = comm_open.end()
                while i < n:
                    close = NOTE_CLOSE_RE.match(xml, i)
                    if close:
                        atoms.append(close.group(0))
                        i = close.end()
                        break
                    i = _append_xml_atom(xml, i, atoms)
                continue
            note = NOTE_RE.match(xml, i)
            if note:
                atoms.append(note.group(0))
                i = note.end()
                continue
            i = _append_xml_atom(xml, i, atoms)
            continue
        atoms.append(xml[i])
        i += 1
    return atoms


def _iter_xml_atoms(xml: str) -> list[str]:
    """Split XML into notes, pb milestones, other tags, and single characters."""
    atoms: list[str] = []
    i = 0
    n = len(xml)
    while i < n:
        if xml.startswith("<", i):
            note = NOTE_RE.match(xml, i)
            if note:
                atoms.append(note.group(0))
                i = note.end()
                continue
            pb = PB_RE.match(xml, i)
            if pb:
                atoms.append(pb.group(0))
                i = pb.end()
                continue
            tag = TAG_RE.match(xml, i)
            if tag:
                atoms.append(tag.group(0))
                i = tag.end()
                continue
        atoms.append(xml[i])
        i += 1
    return atoms


def _is_markup(atom: str) -> bool:
    return atom.startswith("<")


def _is_stamp_open(atom: str) -> bool:
    return bool(SEG_OPEN_RE.fullmatch(atom) or atom == SEG_OPEN)


def _stamp_depth_delta(atom: str, stamp_depth: int, other_seg_depth: int) -> tuple[int, int]:
    """Track our stamped ``<seg>`` separately from any other ``<seg>``."""
    if _is_stamp_open(atom):
        return stamp_depth + 1, other_seg_depth
    if atom.startswith("<seg") and not atom.startswith("</"):
        return stamp_depth, other_seg_depth + 1
    if atom == "</seg>":
        if other_seg_depth > 0:
            return stamp_depth, other_seg_depth - 1
        if stamp_depth > 0:
            return stamp_depth - 1, other_seg_depth
    return stamp_depth, other_seg_depth


def _han_tape(atoms: list[str]) -> tuple[str, list[int]]:
    han_atom_index: list[int] = []
    for idx, atom in enumerate(atoms):
        if not _is_markup(atom) and HAN_RE.fullmatch(atom):
            han_atom_index.append(idx)
    tape = "".join(atoms[i] for i in han_atom_index)
    return tape, han_atom_index


def _atoms_han(atoms: list[str], indices: list[int]) -> str:
    return "".join(atom for idx in indices for atom in [atoms[idx]] if HAN_RE.fullmatch(atom))


def parse_body_segments(body_xml: str) -> list[BodySegment]:
    """Alternating basetext / commentary runs in document order."""
    atoms = _iter_xml_atoms_segmented(body_xml)
    segments: list[BodySegment] = []
    kind = "text"
    indices: list[int] = []
    in_comm = False

    def flush() -> None:
        nonlocal indices, kind
        if not indices:
            return
        han = _atoms_han(atoms, indices)
        if han:
            segments.append({"kind": kind, "atom_indices": indices.copy(), "han": han})
        indices = []

    for idx, atom in enumerate(atoms):
        if NOTE_OPEN_COMM_RE.fullmatch(atom):
            flush()
            kind = "comm"
            in_comm = True
            indices = [idx]
            continue
        if atom == "</note>" and in_comm:
            indices.append(idx)
            flush()
            in_comm = False
            kind = "text"
            continue
        indices.append(idx)
    flush()
    return segments


def _parse_paren_reference_segments(text: str) -> list[RefSegment]:
    segments: list[RefSegment] = []
    buf: list[str] = []
    in_comm = False
    square = 0
    comm_buf: list[str] = []

    def flush_text() -> None:
        chunk = "".join(buf)
        if chunk.strip():
            segments.append({"kind": "text", "text": chunk})
        buf.clear()

    for ch in text:
        if in_comm:
            if ch == "[":
                square += 1
                comm_buf.append(ch)
                continue
            if ch == "]" and square:
                square -= 1
                comm_buf.append(ch)
                continue
            if ch == ")" and square == 0:
                segments.append({"kind": "comm", "text": "".join(comm_buf)})
                comm_buf.clear()
                in_comm = False
                continue
            comm_buf.append(ch)
            continue
        if ch == "(" and square == 0:
            flush_text()
            in_comm = True
            continue
        buf.append(ch)
    flush_text()
    if comm_buf:
        segments.append({"kind": "comm", "text": "".join(comm_buf)})
    return segments


def parse_reference_segments(parallel_text: str) -> list[RefSegment]:
    """Split ctext-style inline commentary or Kanripo ``(…)`` runs."""
    if INLINE_COMM_RE.search(parallel_text):
        segments: list[RefSegment] = []
        pos = 0
        for match in INLINE_COMM_RE.finditer(parallel_text):
            if match.start() > pos:
                segments.append({"kind": "text", "text": parallel_text[pos : match.start()]})
            segments.append({"kind": "comm", "text": match.group(1)})
            pos = match.end()
        if pos < len(parallel_text):
            segments.append({"kind": "text", "text": parallel_text[pos:]})
        return [seg for seg in segments if seg["text"].strip() or han_only(seg["text"])]
    return _parse_paren_reference_segments(parallel_text)


def parse_wikisource_comm_segments(parallel_text: str) -> list[RefSegment]:
    """Extract each Wikisource ``〈…〉`` interlinear note as one comm segment."""
    segments: list[RefSegment] = []
    for match in WIKISOURCE_COMM_RE.finditer(parallel_text):
        inner = match.group(0)[1:-1]
        if inner.strip() or han_only(inner):
            segments.append({"kind": "comm", "text": inner})
    return segments


class CommPoolSpan(TypedDict):
    start: int
    end: int
    text: str


def _build_wikisource_comm_pool(parallel_text: str) -> tuple[str, list[CommPoolSpan]]:
    """Concatenate all ``〈…〉`` Han into one searchable pool with span metadata."""
    pool_parts: list[str] = []
    spans: list[CommPoolSpan] = []
    pos = 0
    for segment in parse_wikisource_comm_segments(parallel_text):
        ref_text = segment["text"]
        ref_han = han_only(ref_text)
        if not ref_han:
            continue
        spans.append({"start": pos, "end": pos + len(ref_han), "text": ref_text})
        pool_parts.append(ref_han)
        pos += len(ref_han)
    return "".join(pool_parts), spans


def _ref_text_for_pool_overlap(
    spans: list[CommPoolSpan],
    pool_start: int,
    pool_end: int,
) -> str:
    """Pick the bracket whose Han span best overlaps the pool match."""
    best: CommPoolSpan | None = None
    best_size = 0
    for span in spans:
        overlap_start = max(span["start"], pool_start)
        overlap_end = min(span["end"], pool_end)
        size = max(0, overlap_end - overlap_start)
        if size > best_size:
            best_size = size
            best = span
    return best["text"] if best is not None else ""


def _find_comm_pool_overlap(pool_han: str, sticker: str) -> tuple[int, int] | None:
    """Locate ``sticker`` anywhere in the commentary Han pool."""
    if not pool_han or not sticker:
        return None
    overlap = find_han_overlap(pool_han, sticker)
    if overlap is not None:
        return overlap
    if len(sticker) <= len(pool_han):
        exact = pool_han.find(sticker)
        if exact >= 0:
            return exact, exact + len(sticker)
    if len(pool_han) <= len(sticker):
        exact = sticker.find(pool_han)
        if exact >= 0:
            return 0, len(pool_han)
    return None


def _comm_note_han_jobs(
    body_xml: str,
    parallel_text: str,
) -> list[tuple[tuple[int, int], str, str]]:
    """Pair each comm note with the best-matching ``〈…〉`` via the comm Han pool."""
    merged = merge_split_comm_notes(body_xml)
    pool_han, pool_spans = _build_wikisource_comm_pool(parallel_text)
    if not pool_han or not pool_spans:
        return []

    body_segments = parse_body_segments(merged)
    han_cursor = 0
    jobs: list[tuple[tuple[int, int], str, str]] = []

    for seg in body_segments:
        han_start = han_cursor
        han_end = han_cursor + len(seg["han"])
        han_cursor = han_end
        if seg["kind"] != "comm" or not seg["han"]:
            continue
        sticker = seg["han"]
        overlap = _find_comm_pool_overlap(pool_han, sticker)
        if overlap is None:
            continue
        pool_start, pool_end = overlap
        ref_text = _ref_text_for_pool_overlap(pool_spans, pool_start, pool_end)
        if not ref_text.strip() and not han_only(ref_text):
            continue
        jobs.append(((han_start, han_end), ref_text, "comm"))
    return jobs


def apply_comm_parallel_punctuation(
    body_xml: str,
    parallel_text: str,
    *,
    source_label: str = "comm",
) -> ParallelPunctResult:
    """Second pass: punctuate comm notes via infix search in the ``〈…〉`` Han pool."""
    merged = merge_split_comm_notes(body_xml)
    atoms = _iter_xml_atoms_segmented(merged)
    tape, _ = _han_tape(atoms)
    total = len(tape)
    jobs = _comm_note_han_jobs(merged, parallel_text)
    if not jobs:
        return {
            "body_xml": body_xml,
            "coverage": _empty_coverage(total),
            "applied": False,
        }

    xml, intervals, spans = _apply_han_jobs(merged, jobs, reflow_paragraphs=False)
    for span in spans:
        span["source"] = source_label
    xml = _finalize_parallel_xml(merged, xml)
    if xml == merged and intervals:
        intervals, spans = [], []
    coverage = _coverage_from_intervals(total, intervals, spans)
    return {
        "body_xml": xml,
        "coverage": coverage,
        "applied": bool(intervals),
    }


def _sticker_to_tape_map(sticker_han: str, tape: str, tape_start: int, tape_end: int) -> dict[int, int]:
    """Map sticker han index → local index in ``tape[tape_start:tape_end]``.

    Uses equal runs plus 1:1 pairing inside replace blocks so variant normalization
    in the parallel (e.g. 庻→庶) still transfers punctuation.
    """
    sub = tape[tape_start:tape_end]
    if not sticker_han or not sub:
        return {}
    mapping: dict[int, int] = {}
    matcher = SequenceMatcher(a=sticker_han, b=sub, autojunk=False)
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == "equal":
            for offset in range(a1 - a0):
                mapping[a0 + offset] = b0 + offset
        elif op == "replace":
            pair_len = min(a1 - a0, b1 - b0)
            for offset in range(pair_len):
                mapping[a0 + offset] = b0 + offset
    return mapping


def _collect_insertions(
    parallel_text: str,
    tape: str,
    tape_start: int,
    tape_end: int,
    sticker_han: str,
    *,
    split_sentences: bool = True,
) -> tuple[dict[int, str], set[int]]:
    insertions: dict[int, str] = {}
    para_after: set[int] = set()
    sticker_to_sub = _sticker_to_tape_map(sticker_han, tape, tape_start, tape_end)
    span = tape_end - tape_start
    han_in_sticker = 0
    pending_nl = 0
    for char in parallel_text.replace("\r\n", "\n").replace("\r", "\n"):
        if HAN_RE.fullmatch(char):
            if pending_nl >= 2:
                local = sticker_to_sub.get(han_in_sticker - 1)
                if local is not None and 0 <= local < span:
                    para_after.add(tape_start + local)
            pending_nl = 0
            han_in_sticker += 1
            continue
        if char == "\n":
            pending_nl += 1
            continue
        pending_nl = 0
        if char in PUNCT_CHARS:
            local = sticker_to_sub.get(han_in_sticker - 1)
            if local is not None and 0 <= local < span:
                at = tape_start + local
                insertions[at] = insertions.get(at, "") + char
                if split_sentences and char in SENTENCE_END_PUNCT:
                    para_after.add(at)
    return insertions, para_after


def _comm_note_atom(atom: str) -> bool:
    return atom.startswith("<note") and 'type="comm"' in atom


def _comm_note_follows(atoms: list[str], index: int) -> bool:
    """True when a comm note immediately follows this atom (ignoring whitespace)."""
    cursor = index + 1
    while cursor < len(atoms):
        atom = atoms[cursor]
        if _is_insignificant_whitespace_atom(atom):
            cursor += 1
            continue
        if _comm_note_atom(atom):
            return True
        if atom == "</p>" or _is_p_open(atom):
            return False
        if atom.startswith("<"):
            cursor += 1
            continue
        return False
    return False


def _ends_with_sentence_end(prefix: str) -> bool:
    """Whether the last paragraph in ``prefix`` ends a sentence (or stamped stretch)."""
    trimmed = prefix.rstrip()
    if trimmed.endswith("</seg></p>") or trimmed.endswith("</seg>"):
        return True
    start = trimmed.rfind("<p>")
    if start < 0:
        return False
    tail = trimmed[start + 3 :]
    visible = re.sub(r"<[^>]+>", "", tail).strip()
    return bool(visible) and visible[-1] in SENTENCE_END_PUNCT


def relocate_leading_comm_notes(xml: str) -> str:
    """Attach comm notes stranded at a ``<p>`` start to the preceding sentence."""
    pattern = re.compile(
        r"</p>\s*<p>\s*(<note\b[^>]*\btype=\"comm\"[^>]*>.*?</note>)",
        re.DOTALL | re.I,
    )
    pos = 0
    while True:
        match = pattern.search(xml, pos)
        if match is None:
            return xml
        before = xml[: match.start()]
        if not _ends_with_sentence_end(before):
            pos = match.end()
            continue
        note = match.group(1)
        after = xml[match.end() :]
        close_idx = before.rfind("</p>")
        if close_idx < 0:
            pos = match.end()
            continue
        xml = before[:close_idx] + note + before[close_idx:] + "<p>" + after
        pos = close_idx + len(note) + 3


def _is_p_open(atom: str) -> bool:
    return atom == "<p>" or (atom.startswith("<p ") and atom.endswith(">"))


def _is_insignificant_whitespace_atom(atom: str) -> bool:
    """True for atoms that only carry formatting between XML tags."""
    return atom in ("\n", "\r", "\t") or (len(atom) > 0 and atom.strip() == "")


def _paragraph_open_index(atoms: list[str], index: int) -> int | None:
    cursor = index + 1
    while cursor < len(atoms) and _is_insignificant_whitespace_atom(atoms[cursor]):
        cursor += 1
    if cursor < len(atoms) and _is_p_open(atoms[cursor]):
        return cursor
    return None


def _should_skip_line_paragraph_break(
    atom: str,
    atoms: list[str],
    index: int,
    han_seen: int,
    reflow_start: int,
    reflow_end: int,
    para_after: set[int],
) -> bool:
    """Drop Kanripo ``</p><p>`` wraps inside a reflow zone unless parallel marks a break."""
    if atom != "</p>":
        return False
    if han_seen < reflow_start or han_seen >= reflow_end:
        return False
    if han_seen in para_after:
        return False
    return _paragraph_open_index(atoms, index) is not None


def _emit_paragraph_split(
    out: list[str],
    opened_here: int,
    stamp_depth: int,
    atoms: list[str],
    index: int,
) -> tuple[int, int]:
    """Insert ``</p><p>`` unless the source already breaks here."""
    cursor = index + 1
    while cursor < len(atoms) and _is_insignificant_whitespace_atom(atoms[cursor]):
        cursor += 1
    if cursor < len(atoms) and atoms[cursor] == "</p>":
        return opened_here, stamp_depth
    if opened_here > 0:
        opened_here, stamp_depth = _close_stamp_if_open(out, opened_here, stamp_depth)
    out.append("</p><p>")
    return opened_here, stamp_depth


def _skip_natural_break_after_split(atoms: list[str], index: int) -> int:
    """Skip source ``</p><p>`` that duplicates a split we just inserted."""
    cursor = index + 1
    while cursor < len(atoms) and _is_insignificant_whitespace_atom(atoms[cursor]):
        cursor += 1
    if cursor < len(atoms) and atoms[cursor] == "</p>":
        p_open = _paragraph_open_index(atoms, cursor)
        if p_open is not None:
            return p_open
    return index


def _close_stamp_if_open(out: list[str], opened_here: int, stamp_depth: int) -> tuple[int, int]:
    if opened_here > 0:
        out.append("</seg>")
        return opened_here - 1, max(0, stamp_depth - 1)
    return opened_here, stamp_depth


def _open_stamp_if_needed(
    out: list[str],
    han_index: int,
    opened_here: int,
    stamp_depth: int,
    in_stamp,
) -> tuple[int, int]:
    if in_stamp(han_index) and stamp_depth == 0 and opened_here == 0:
        out.append(SEG_OPEN)
        return opened_here + 1, stamp_depth + 1
    return opened_here, stamp_depth


def _apply_han_jobs(
    body_xml: str,
    jobs: list[tuple[tuple[int, int], str, str]],
    *,
    reflow_paragraphs: bool = True,
) -> tuple[str, list[tuple[int, int]], list[CoverageSpan]]:
    """Apply punctuation for several Han ranges in one pass."""
    if not jobs:
        return body_xml, [], []
    atoms = _iter_xml_atoms_segmented(body_xml)
    tape, _ = _han_tape(atoms)
    insertions: dict[int, str] = {}
    para_after: set[int] = set()
    stamp_ranges: list[tuple[int, int]] = []
    spans: list[CoverageSpan] = []
    total = len(tape)

    for han_range, parallel_text, label in jobs:
        tape_start, tape_end = han_range
        if tape_start >= tape_end or tape_end > len(tape):
            continue
        sticker = han_only(parallel_text)
        if not sticker:
            continue
        sub_overlap = find_han_overlap(tape[tape_start:tape_end], sticker)
        if sub_overlap is None:
            continue
        abs_start = tape_start + sub_overlap[0]
        abs_end = tape_start + sub_overlap[1]
        stamp_ranges.append((abs_start, abs_end))
        seg_ins, seg_para = _collect_insertions(
            parallel_text,
            tape,
            abs_start,
            abs_end,
            sticker,
            split_sentences=label != "comm",
        )
        for key, value in seg_ins.items():
            insertions[key] = insertions.get(key, "") + value
        para_after.update(seg_para)
        preview = tape[abs_start:abs_end][:40]
        spans.append(
            {
                "start": abs_start / total if total else 0.0,
                "end": abs_end / total if total else 0.0,
                "covered_chars": abs_end - abs_start,
                "source": label,
                "preview": preview,
            }
        )

    if not stamp_ranges:
        return body_xml, [], []

    reflow_start = min(start for start, _ in stamp_ranges)
    reflow_end = max(end for _, end in stamp_ranges)
    if not reflow_paragraphs:
        reflow_start = reflow_end = -1
        para_after = set()
    out: list[str] = []
    han_seen = -1
    opened_here = 0
    stamp_depth = 0
    other_seg_depth = 0
    skip_until = -1
    in_comm_note = False

    def in_stamp(han_index: int) -> bool:
        for start, end in stamp_ranges:
            if start <= han_index < end:
                return True
        return False

    def close_stamp_at_boundary(atom: str) -> bool:
        return (
            atom in ("</p>", "</note>")
            or NOTE_OPEN_COMM_RE.fullmatch(atom) is not None
        )

    for atom_index, atom in enumerate(atoms):
        if atom_index <= skip_until:
            continue
        if _should_skip_line_paragraph_break(
            atom, atoms, atom_index, han_seen, reflow_start, reflow_end, para_after
        ):
            p_open = _paragraph_open_index(atoms, atom_index)
            if p_open is not None:
                skip_until = p_open
            continue

        if close_stamp_at_boundary(atom) and opened_here > 0:
            opened_here, stamp_depth = _close_stamp_if_open(out, opened_here, stamp_depth)

        if NOTE_OPEN_COMM_RE.fullmatch(atom):
            in_comm_note = True
        elif atom == "</note>":
            in_comm_note = False

        is_han = (not _is_markup(atom)) and HAN_RE.fullmatch(atom)
        stamp_depth, other_seg_depth = _stamp_depth_delta(atom, stamp_depth, other_seg_depth)
        if is_han:
            han_seen += 1
            opened_here, stamp_depth = _open_stamp_if_needed(
                out, han_seen, opened_here, stamp_depth, in_stamp
            )
        out.append(atom)
        if is_han:
            extra = insertions.get(han_seen, "")
            if extra:
                out.append(extra)
            if (
                han_seen in para_after
                and not in_comm_note
                and not _comm_note_follows(atoms, atom_index)
            ):
                before_len = len(out)
                opened_here, stamp_depth = _emit_paragraph_split(
                    out, opened_here, stamp_depth, atoms, atom_index
                )
                if len(out) > before_len:
                    skip_until = max(
                        skip_until, _skip_natural_break_after_split(atoms, atom_index)
                    )
            if opened_here > 0 and not in_stamp(han_seen + 1):
                opened_here, stamp_depth = _close_stamp_if_open(out, opened_here, stamp_depth)
    while opened_here > 0:
        out.append("</seg>")
        opened_here -= 1

    return "".join(out), stamp_ranges, spans


def _slice_text_by_han_range(text: str, han_start: int, han_end: int) -> str:
    """Extract a substring covering Han indices ``[han_start, han_end)`` plus trailing punct."""
    if han_start >= han_end:
        return ""
    han_count = 0
    start_char: int | None = None
    end_char = len(text)
    for index, char in enumerate(text):
        if HAN_RE.fullmatch(char):
            if han_count == han_start:
                start_char = index
            han_count += 1
            if han_count == han_end:
                end_char = index + 1
                break
    if start_char is None:
        return ""
    while end_char < len(text) and not HAN_RE.fullmatch(text[end_char]):
        end_char += 1
    return text[start_char:end_char]


def _align_body_to_reference(
    body_segments: list[BodySegment],
    parallel_text: str,
) -> list[tuple[int, RefSegment]]:
    """Map each body segment to a reference slice by forward fuzzy Han search.

    Skips body prefix (e.g. Kanripo header material) that is absent from the
    parallel. Does not require segment-kind alignment at the same index.
    """
    ref_han_tape = han_only(parallel_text)
    ref_cursor = 0
    pairs: list[tuple[int, RefSegment]] = []
    for index, body_seg in enumerate(body_segments):
        sticker = body_seg["han"]
        if not sticker:
            continue
        overlap = find_han_overlap_from(ref_han_tape, sticker, ref_cursor)
        if overlap is None:
            continue
        ref_start, ref_end = overlap
        pairs.append(
            (
                index,
                {
                    "kind": body_seg["kind"],
                    "text": _slice_text_by_han_range(parallel_text, ref_start, ref_end),
                },
            )
        )
        ref_cursor = ref_end
    return pairs


def _finalize_parallel_xml(body_xml: str, xml: str) -> str:
    """Return punctuated ``xml`` when well-formed, else fail closed with the original body."""
    try:
        assert_well_formed(xml)
    except ET.ParseError:
        return body_xml
    relocated = relocate_leading_comm_notes(xml)
    try:
        assert_well_formed(relocated)
    except ET.ParseError:
        return xml
    return relocated


def apply_parallel_segmented(body_xml: str, parallel_text: str) -> ParallelPunctResult:
    """Match basetext and commentary segments separately against a ctext-style parallel."""
    merged = merge_split_comm_notes(body_xml)
    body_segments = parse_body_segments(merged)
    if not body_segments or not han_only(parallel_text):
        atoms = _iter_xml_atoms_segmented(merged)
        tape, _ = _han_tape(atoms)
        return {
            "body_xml": merged,
            "coverage": _empty_coverage(len(tape)),
            "applied": False,
        }

    atoms = _iter_xml_atoms_segmented(merged)
    tape, _ = _han_tape(atoms)
    total = len(tape)
    aligned = _align_body_to_reference(body_segments, parallel_text)
    ref_by_index = {index: ref_seg for index, ref_seg in aligned}

    jobs: list[tuple[tuple[int, int], str, str]] = []
    han_cursor = 0
    for index, body_seg in enumerate(body_segments):
        han_start = han_cursor
        han_end = han_cursor + len(body_seg["han"])
        han_cursor = han_end
        ref_seg = ref_by_index.get(index)
        if ref_seg is None:
            continue
        if find_han_overlap(tape[han_start:han_end], han_only(ref_seg["text"])) is None:
            continue
        label = "comm" if body_seg["kind"] == "comm" else "text"
        jobs.append(((han_start, han_end), ref_seg["text"], label))

    xml, intervals, spans = _apply_han_jobs(merged, jobs, reflow_paragraphs=False)
    xml = _finalize_parallel_xml(merged, xml)
    if xml == merged and intervals:
        intervals, spans = [], []
    coverage = _coverage_from_intervals(total, intervals, spans)
    return {"body_xml": xml, "coverage": coverage, "applied": bool(intervals)}


def apply_parallel_segmented_sources(
    body_xml: str, sources: list[dict[str, str]]
) -> ParallelPunctResult:
    """Apply segmented punctuation from named sources in order."""
    xml = merge_split_comm_notes(body_xml)
    atoms = _iter_xml_atoms_segmented(xml)
    tape, _ = _han_tape(atoms)
    total = len(tape)
    all_intervals: list[tuple[int, int]] = []
    all_spans: list[CoverageSpan] = []
    applied_any = False

    for source in sources:
        text = str(source.get("text") or "")
        label = str(source.get("label") or source.get("id") or "source")
        if not text.strip():
            continue
        result = apply_parallel_segmented(xml, text)
        xml = result["body_xml"]
        if not result["applied"]:
            continue
        applied_any = True
        for span in result["coverage"]["spans"]:
            start = int(span["start"] * total)
            end = int(span["end"] * total)
            all_intervals.append((start, end))
            all_spans.append({**span, "source": label})

    coverage = _coverage_from_intervals(total, all_intervals, all_spans)
    return {"body_xml": xml, "coverage": coverage, "applied": applied_any}


def coverage_from_stamps(body_xml: str) -> Coverage:
    """Rebuild coverage from existing ``type="ljb:parallel-punct"`` stretches
    (legacy ``ana="…"`` stamps are still recognised)."""
    atoms = _iter_xml_atoms(body_xml)
    tape, _ = _han_tape(atoms)
    total = len(tape)
    intervals: list[tuple[int, int]] = []
    spans: list[CoverageSpan] = []
    stamp_depth = 0
    other_seg_depth = 0
    run_start: int | None = None
    han_seen = -1
    for atom in atoms:
        prev = stamp_depth
        stamp_depth, other_seg_depth = _stamp_depth_delta(atom, stamp_depth, other_seg_depth)
        if stamp_depth > prev:
            if prev == 0:
                run_start = han_seen + 1
            continue
        if stamp_depth < prev:
            if stamp_depth == 0 and run_start is not None and han_seen >= run_start:
                start, end = run_start, han_seen + 1
                intervals.append((start, end))
                preview = tape[start:end][:40]
                spans.append(
                    {
                        "start": start / total if total else 0.0,
                        "end": end / total if total else 0.0,
                        "covered_chars": end - start,
                        "source": "stamped",
                        "preview": preview,
                    }
                )
            run_start = None
            continue
        if not _is_markup(atom) and HAN_RE.fullmatch(atom):
            han_seen += 1
    return _coverage_from_intervals(total, intervals, spans)


MIN_AI_HAN_MAP_RATIO = 0.75


def _align_parallel_to_scoped_sub(
    parallel_text: str,
    tape: str,
    tape_start: int,
    tape_end: int,
    *,
    min_map_ratio: float = MIN_AI_HAN_MAP_RATIO,
) -> tuple[str, str]:
    """Trim LLM parallel text when it includes context outside a scoped Han range.

    AI models often return the full punctuated passage even when the prompt
    covered only a selection. Without trimming, ``_sticker_to_tape_map`` maps
    from sticker index 0 and the ``min_map_ratio`` gate rejects the transfer.
    """
    sub = tape[tape_start:tape_end]
    sticker = han_only(parallel_text)
    if not sticker or not sub:
        return parallel_text, sticker
    mapping = _sticker_to_tape_map(sticker, tape, tape_start, tape_end)
    if len(mapping) / len(sticker) >= min_map_ratio:
        return parallel_text, sticker
    overlap = find_han_overlap(sticker, sub)
    if overlap is None:
        return parallel_text, sticker
    off_start, off_end = overlap
    if off_end - off_start < len(sub) * min_map_ratio:
        return parallel_text, sticker
    trimmed_parallel = _slice_text_by_han_range(parallel_text, off_start, off_end)
    trimmed_sticker = han_only(trimmed_parallel)
    if not trimmed_sticker:
        return parallel_text, sticker
    return trimmed_parallel, trimmed_sticker


def _normalize_parallel_match_text(parallel_text: str) -> str:
    match_text = parallel_text
    if INLINE_COMM_RE.search(parallel_text):
        match_text = strip_inline_commentary(parallel_text)
    elif WIKISOURCE_COMM_RE.search(parallel_text):
        match_text = strip_wikisource_commentary(parallel_text)
    return match_text


def _apply_parallel_at_range(
    body_xml: str,
    match_text: str,
    sticker: str,
    tape: str,
    tape_start: int,
    tape_end: int,
    *,
    segmented: bool = False,
) -> tuple[str, tuple[int, int] | None, str]:
    """Copy ``match_text`` punctuation onto ``body_xml`` over Han range ``[tape_start, tape_end)``.

    ``segmented=True`` walks the body with :func:`_iter_xml_atoms_segmented` so the
    Han index space matches ``list_segments`` (``<note type="comm">`` innards are
    counted). In that mode marks may land *inside* a comm note, but the
    ``<seg type="ljb:parallel-punct">`` stamp and ``</p><p>`` reflow splits are
    suppressed there — commentary is punctuated, never wrapped or reflowed.
    """
    insertions, para_after = _collect_insertions(
        match_text,
        tape,
        tape_start,
        tape_end,
        sticker,
        split_sentences=False,
    )
    atoms = _iter_xml_atoms_segmented(body_xml) if segmented else _iter_xml_atoms(body_xml)
    out: list[str] = []
    han_seen = -1
    opened_here = 0
    stamp_depth = 0
    other_seg_depth = 0
    skip_until = -1
    reflow_start = tape_start
    reflow_end = tape_end
    comm_note_depth = 0

    def close_stamp_at_boundary(atom: str) -> bool:
        return (
            atom in ("</p>", "</note>")
            or NOTE_OPEN_COMM_RE.fullmatch(atom) is not None
        )

    for atom_index, atom in enumerate(atoms):
        if atom_index <= skip_until:
            continue
        if _should_skip_line_paragraph_break(
            atom, atoms, atom_index, han_seen, reflow_start, reflow_end, para_after
        ):
            p_open = _paragraph_open_index(atoms, atom_index)
            if p_open is not None:
                skip_until = p_open
            continue

        if close_stamp_at_boundary(atom) and opened_here > 0:
            opened_here, stamp_depth = _close_stamp_if_open(out, opened_here, stamp_depth)

        if segmented:
            if NOTE_OPEN_COMM_RE.fullmatch(atom):
                comm_note_depth += 1
            elif atom == "</note>" and comm_note_depth > 0:
                comm_note_depth -= 1
        in_comm_note = comm_note_depth > 0

        is_han = (not _is_markup(atom)) and HAN_RE.fullmatch(atom)
        stamp_depth, other_seg_depth = _stamp_depth_delta(atom, stamp_depth, other_seg_depth)
        if is_han:
            han_seen += 1
            if (
                han_seen == tape_start
                and stamp_depth == 0
                and opened_here == 0
                and not in_comm_note
            ):
                out.append(SEG_OPEN)
                opened_here += 1
                stamp_depth += 1
        out.append(atom)
        if is_han:
            extra = insertions.get(han_seen, "")
            if extra:
                out.append(extra)
            if (
                han_seen in para_after
                and not in_comm_note
                and not _comm_note_follows(atoms, atom_index)
            ):
                before_len = len(out)
                opened_here, stamp_depth = _emit_paragraph_split(
                    out, opened_here, stamp_depth, atoms, atom_index
                )
                if len(out) > before_len:
                    skip_until = max(
                        skip_until, _skip_natural_break_after_split(atoms, atom_index)
                    )
            if han_seen == tape_end - 1 and opened_here > 0:
                opened_here, stamp_depth = _close_stamp_if_open(out, opened_here, stamp_depth)
    while opened_here > 0:
        out.append("</seg>")
        opened_here -= 1

    result_xml = "".join(out)
    final_xml = _finalize_parallel_xml(body_xml, result_xml)
    if final_xml == body_xml and result_xml != body_xml:
        return body_xml, None, ""
    preview = tape[tape_start:tape_end][:40]
    return final_xml, (tape_start, tape_end), preview


def apply_scoped_parallel_punctuation(
    body_xml: str,
    parallel_text: str,
    tape_start: int,
    tape_end: int,
    *,
    min_map_ratio: float = MIN_AI_HAN_MAP_RATIO,
) -> ParallelPunctResult:
    """Apply parallel punct on a known Han range (AI segments — skip global overlap search).

    ``tape_start`` / ``tape_end`` come from ``list_segments``, whose Han index
    space counts ``<note type="comm">`` innards — so the tape here is built the
    same way (:func:`_iter_xml_atoms_segmented`). Using the note-collapsed
    :func:`_iter_xml_atoms` here shifts every segment that follows an inline comm
    note and drops it at the ``min_map_ratio`` gate.
    """
    atoms = _iter_xml_atoms_segmented(body_xml)
    tape, _ = _han_tape(atoms)
    total = len(tape)
    empty: ParallelPunctResult = {
        "body_xml": body_xml,
        "coverage": _empty_coverage(total),
        "applied": False,
    }
    if tape_start < 0 or tape_end > total or tape_start >= tape_end:
        return empty
    match_text = _normalize_parallel_match_text(parallel_text)
    match_text, sticker = _align_parallel_to_scoped_sub(
        match_text, tape, tape_start, tape_end, min_map_ratio=min_map_ratio
    )
    if not sticker:
        return empty
    mapping = _sticker_to_tape_map(sticker, tape, tape_start, tape_end)
    if len(mapping) / len(sticker) < min_map_ratio:
        return empty
    final_xml, overlap, preview = _apply_parallel_at_range(
        body_xml, match_text, sticker, tape, tape_start, tape_end, segmented=True
    )
    if overlap is None:
        return empty
    start, end = overlap
    coverage = _coverage_from_intervals(
        total,
        [(start, end)],
        [
            {
                "start": start / total if total else 0.0,
                "end": end / total if total else 0.0,
                "covered_chars": end - start,
                "source": "ai",
                "preview": preview,
            }
        ],
    )
    return {"body_xml": final_xml, "coverage": coverage, "applied": True}


def _apply_one(body_xml: str, parallel_text: str) -> tuple[str, tuple[int, int] | None, str]:
    atoms = _iter_xml_atoms(body_xml)
    tape, _ = _han_tape(atoms)
    match_text = _normalize_parallel_match_text(parallel_text)
    sticker = han_only(match_text)
    overlap = find_han_overlap_flexible(tape, sticker)
    if overlap is None:
        return body_xml, None, ""

    tape_start, tape_end = overlap
    return _apply_parallel_at_range(body_xml, match_text, sticker, tape, tape_start, tape_end)


def strip_inline_commentary(parallel_text: str) -> str:
    """Remove ctext-style inline commentary spans for main-text-only tape matching."""
    return INLINE_COMM_RE.sub("", parallel_text)


def apply_parallel_punctuation(body_xml: str, parallel_text: str) -> ParallelPunctResult:
    """Insert parallel punctuation/paragraphs onto the overlapping Han range."""
    return apply_parallel_sources(body_xml, [{"id": "paste", "label": "Paste", "text": parallel_text}])


def apply_parallel_sources(
    body_xml: str,
    sources: list[dict[str, str]],
    *,
    used_chapter_ids: list[str] | None = None,
) -> ParallelPunctResult:
    """Apply named sources in order. Fail closed per source. Union coverage."""
    from kanripo_import.wikisource_catalog import resolve_wikisource_parallel

    atoms = _iter_xml_atoms(body_xml)
    tape, _ = _han_tape(atoms)
    total = len(tape)
    xml = body_xml
    intervals: list[tuple[int, int]] = []
    spans: list[CoverageSpan] = []
    applied_any = False
    matched_chapter_ids: list[str] = []
    used_chapters = set(str(item) for item in (used_chapter_ids or []))
    resolved_sources: list[tuple[str, str]] = []

    for source in sources:
        parallel_text = str(source.get("text") or "")
        label = str(source.get("label") or source.get("id") or "source")
        catalog_match = None
        if source.get("chapters"):
            parallel_text, catalog_match = resolve_wikisource_parallel(
                body_xml,
                source,
                used_ids=used_chapters,
            )
            if catalog_match:
                matched_chapter_ids.extend(catalog_match["chapter_ids"])
                if catalog_match["labels"]:
                    label = (
                        f"{label}: {', '.join(catalog_match['labels'])} "
                        f"({catalog_match['method']})"
                    )
        if not parallel_text.strip():
            continue
        resolved_sources.append((label, parallel_text))
        xml, overlap, preview = _apply_one(xml, parallel_text)
        if overlap is None:
            continue
        start, end = overlap
        applied_any = True
        intervals.append((start, end))
        spans.append(
            {
                "start": start / total if total else 0.0,
                "end": end / total if total else 0.0,
                "covered_chars": end - start,
                "source": label,
                "preview": preview,
            }
        )

    for label, parallel_text in resolved_sources:
        if not WIKISOURCE_COMM_RE.search(parallel_text):
            continue
        comm_result = apply_comm_parallel_punctuation(
            xml,
            parallel_text,
            source_label=f"{label}:comm",
        )
        if not comm_result["applied"]:
            continue
        xml = comm_result["body_xml"]
        applied_any = True
        comm_cov = comm_result["coverage"]
        for span in comm_cov.get("spans") or []:
            start = int(float(span["start"]) * total)
            end = int(float(span["end"]) * total)
            intervals.append((start, end))
            spans.append(span)

    coverage = _coverage_from_intervals(total, intervals, spans)
    result: ParallelPunctResult = {
        "body_xml": xml,
        "coverage": coverage,
        "applied": applied_any,
    }
    if matched_chapter_ids:
        result["matched_chapter_ids"] = matched_chapter_ids
    return result


def _text_inside_stamps(body_xml: str) -> str:
    """Concatenate visible text inside ``ljb:parallel-punct`` segs."""
    parts: list[str] = []
    stamp_depth = 0
    other_seg_depth = 0
    buf: list[str] = []
    for atom in _iter_xml_atoms(body_xml):
        prev = stamp_depth
        stamp_depth, other_seg_depth = _stamp_depth_delta(atom, stamp_depth, other_seg_depth)
        if stamp_depth > prev:
            continue
        if stamp_depth < prev:
            if prev > 0 and buf:
                parts.append("".join(buf))
                buf = []
            continue
        if stamp_depth > 0 and not _is_markup(atom):
            buf.append(atom)
    if buf:
        parts.append("".join(buf))
    return "".join(parts)


def _count_han_punct(text: str) -> tuple[int, int]:
    han = len(HAN_RE.findall(text))
    punct = sum(1 for ch in text if ch in PUNCT_CHARS)
    return han, punct


def assess_parallel_quality(
    body_xml: str,
    coverage: Coverage,
    *,
    had_sources: bool = True,
    source_kinds: list[str] | None = None,
) -> list[ParallelQualityWarning]:
    """Heuristic warnings after parallel punctuation (overlap vs punctuation copied)."""
    warnings: list[ParallelQualityWarning] = []
    if not had_sources:
        return warnings

    kinds = [kind for kind in (source_kinds or []) if kind]
    has_daozang = "daozang" in kinds

    if coverage.get("empty") or float(coverage.get("ratio") or 0) == 0:
        if has_daozang:
            warnings.append(
                {
                    "code": "daozang_no_align",
                    "severity": "warning",
                    "message": (
                        "Bundled Daozang text did not align with this juan — "
                        "wrong edition, commentary mismatch, or juan spans only part of the work."
                    ),
                }
            )
        else:
            warnings.append(
                {
                    "code": "no_overlap",
                    "severity": "warning",
                    "message": "Parallel source did not align with this juan (0% overlap).",
                }
            )
        return warnings

    ratio = float(coverage.get("ratio") or 0)
    pct = int(round(ratio * 100))

    if ratio < LOW_OVERLAP_RATIO:
        warnings.append(
            {
                "code": "low_overlap",
                "severity": "warning",
                "message": (
                    f"Low parallel overlap ({pct}%) — most of this juan stays unpunctuated."
                ),
            }
        )

    stamped = _text_inside_stamps(body_xml)
    han, punct = _count_han_punct(stamped)
    if han >= MIN_HAN_FOR_PUNCT_CHECK:
        per_100 = (punct / han) * 100
        if per_100 < MIN_PUNCT_PER_100_HAN and ratio >= LOW_OVERLAP_RATIO:
            warnings.append(
                {
                    "code": "low_punctuation",
                    "severity": "warning",
                    "message": (
                        f"Overlap is {pct}% but few punctuation marks were copied "
                        f"({punct} in {han} characters in matched stretches). "
                        "The parallel may be unpunctuated or the wrong edition."
                    ),
                }
            )
    return warnings


def enrich_parallel_result(
    result: dict[str, object],
    sources: list[dict[str, str]],
) -> dict[str, object]:
    kinds = [str(source.get("kind") or "") for source in sources]
    had_sources = any(str(source.get("text") or "").strip() for source in sources)
    coverage = result.get("coverage")
    if not isinstance(coverage, dict):
        coverage = _empty_coverage(0)
    warnings = assess_parallel_quality(
        str(result.get("body_xml") or ""),
        coverage,  # type: ignore[arg-type]
        had_sources=had_sources,
        source_kinds=kinds,
    )
    result["quality"] = {"warnings": warnings}
    return result


# CBETA body fragments extracted from a full TEI file keep ``cb:`` prefixes on
# elements but drop the ``xmlns:cb`` declaration (it lives on ``<TEI>``).  A
# naive wrap-for-parse then rejects otherwise valid punctuation output.
_CBETA_NS = "http://www.cbeta.org/ns/1.0"
_TEI_NS = "http://www.tei-c.org/ns/1.0"


def _parse_fragment(xml: str) -> ET.Element:
    """Parse a body fragment, declaring namespaces the fragment still uses."""
    attrs: list[str] = []
    if "cb:" in xml:
        attrs.append(f'xmlns:cb="{_CBETA_NS}"')
    if "cb:" in xml and re.search(r"<(?:p|div|note|milestone|lb|pb|seg|g|anchor)\b", xml):
        attrs.append(f'xmlns="{_TEI_NS}"')
    attr = f" {' '.join(attrs)}" if attrs else ""
    return ET.fromstring(f"<root{attr}>{xml}</root>")


def assert_well_formed(xml: str) -> None:
    """Raise if ``xml`` is not a well-formed fragment (wrapped for parse)."""
    _parse_fragment(xml)
