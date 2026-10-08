"""Infix / superset overlap: copy punctuation from a parallel onto Kanripo TEI.

The Kanripo ``body_xml`` is the tape. The parallel is often a shorter sticker.
Unmatched prefix/suffix stay as-is. Wrong text → no overlap (empty coverage).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from difflib import SequenceMatcher
from typing import TypedDict
from xml.etree import ElementTree as ET

# Han: Ext A, the main block, CJK compatibility ideographs, and planes 2-3 (Ext B through H). The
# astral part matters: Kanripo texts use Ext B+ characters directly (e.g. 𪁺 U+2A07A), and a Han
# test that stops at the BMP drops them from the tape and shifts every index after them.
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323AF]")
# Marks copied from a parallel onto the Kanripo body. Keep in sync with
# ``AI_PUNCT_CHARS`` in ai_punct.py for the shared CJK set (《》· included).
# Title marks 《》 were missing here and were silently dropped on every transfer.
PUNCT_CHARS = set("。，、：；？！「」『』·《》（）〔〕.,;:!?")
# The subset of PUNCT_CHARS that opens a bracketed/quoted stretch rather than
# closing or ending one — see _slice_text_by_han_range, which only ever
# extends its start boundary backward through characters in this set.
_OPENING_PUNCT_CHARS = set("「『《（〔")
# Two independently-matched ref paragraphs can each legitimately claim the
# same opening mark from the source: one as an "after" mark trailing its own
# last Han character (e.g. an attribution "...曰：「" ending one paragraph),
# the other as a "before" mark leading its own first Han character (the
# quoted content that paragraph itself begins with, "「...」"), when the
# source text the two paragraphs matched against actually has only one such
# mark sitting right at the seam between them. Each insertion is correct in
# isolation -- the duplication only exists across the pair. Collapse a run of
# 1-2 opening marks that lands identically on both sides of a `<seg>`
# boundary, keeping the first (closing side) copy and dropping the second
# (opening side) one, since a quote-open mark reads naturally as closing out
# the attribution that precedes it.
_OPENING_PUNCT_RUN = "[" + re.escape("".join(sorted(_OPENING_PUNCT_CHARS))) + "]{1,2}"
_SEG_BOUNDARY_DUP_MARK_RE = re.compile(
    rf"(?P<mark>{_OPENING_PUNCT_RUN})</seg>(?P<opentag><seg\b[^>]*>)(?P=mark)"
)


def _dedupe_seg_boundary_marks(xml: str) -> str:
    return _SEG_BOUNDARY_DUP_MARK_RE.sub(
        lambda m: m.group("mark") + "</seg>" + m.group("opentag"), xml
    )


# Marker for a stretch whose punctuation was copied from a parallel witness.
# Carried on `<seg type="…">`, not `@ana`: the CBETA P5 customization drops
# `att.global.analytic` entirely (no `@ana` on any element), and even in
# TEI-all `@ana` is `data.pointer` — a bare token like this is not a valid
# value there. `type` is `data.name`, which `grognard:parallel-punct` satisfies,
# and it is allowed on `<seg>` in both schemas.
SEG_MARK = "grognard:parallel-punct"
SEG_OPEN = f'<seg type="{SEG_MARK}">'
NOTE_RE = re.compile(r"<note\b[^>]*>.*?</note>", re.DOTALL)
NOTE_OPEN_COMM_RE = re.compile(r'<note\b[^>]*\btype="comm"[^>]*>', re.I)
NOTE_CLOSE_RE = re.compile(r"</note>")
# Paratext that is never punctuated and never joins base text: title block, section
# headings, colophon. Segments for these carry kind "head" so Han indices stay in step.
HEAD_OPEN_RE = re.compile(r"<(?:head|byline|trailer)\b[^>]*>", re.I)
HEAD_CLOSE_RE = re.compile(r"</(?:head|byline|trailer)>", re.I)
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
# Max tape/sticker offset change between neighbouring matching blocks that
# still counts as the same aligned stretch (variant chars, dropped words).
MAX_DIAGONAL_DRIFT = 24
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
    text: str  # same span as `han`, but keeping punctuation/other visible chars


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
        # Join only blocks that sit on one consistent diagonal. Stray short
        # matches elsewhere in a long tape (a licence line, boilerplate, a
        # repeated phrase) otherwise stretch the span across unrelated text.
        best_cluster: list = []
        cluster: list = []
        for block in all_blocks:
            if cluster:
                prev = cluster[-1]
                drift = (block.a - prev.a) - (block.b - prev.b)
                if abs(drift) > MAX_DIAGONAL_DRIFT:
                    cluster = []
            cluster.append(block)
            if sum(b.size for b in cluster) > sum(b.size for b in best_cluster):
                best_cluster = list(cluster)
        sticker_intervals = [(block.b, block.b + block.size) for block in best_cluster]
        if _union_covered(sticker_intervals) / len(sticker) >= MIN_STICKER_COVER:
            tape_intervals = [(block.a, block.a + block.size) for block in best_cluster]
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


def _atoms_text(atoms: list[str], indices: list[int]) -> str:
    """Like ``_atoms_han`` but keeps every visible (non-markup) character,
    punctuation included -- for punctuation-density checks, which need the
    marks that ``_atoms_han``'s Han-only filter deliberately excludes."""
    return "".join(atom for idx in indices for atom in [atoms[idx]] if not _is_markup(atom))


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
            segments.append(
                {
                    "kind": kind,
                    "atom_indices": indices.copy(),
                    "han": han,
                    "text": _atoms_text(atoms, indices),
                }
            )
        indices = []

    in_head = False
    for idx, atom in enumerate(atoms):
        if not in_comm and not in_head and HEAD_OPEN_RE.fullmatch(atom):
            flush()
            kind = "head"
            in_head = True
            indices = [idx]
            continue
        if in_head:
            indices.append(idx)
            if HEAD_CLOSE_RE.fullmatch(atom):
                flush()
                in_head = False
                kind = "text"
            continue
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


def _sticker_to_tape_map(
    sticker_han: str, tape: str, tape_start: int, tape_end: int, *, strict: bool = False
) -> dict[int, int]:
    """Map sticker han index → local index in ``tape[tape_start:tape_end]``.

    Uses equal runs plus 1:1 pairing inside replace blocks so variant normalization
    in the parallel (e.g. 庻→庶) still transfers punctuation.
    """
    sub = tape[tape_start:tape_end]
    if not sticker_han or not sub:
        return {}
    mapping: dict[int, int] = {}
    if strict:
        # Only characters that agree (after the 1:1 variant fold) carry marks: pairing unlike
        # characters 1:1 would lend a note marker like 音義 the marks of unrelated parallel text.
        matcher = SequenceMatcher(
            a=_fold_han_variants(sticker_han), b=_fold_han_variants(sub), autojunk=False
        )
        for op, a0, a1, b0, b1 in matcher.get_opcodes():
            if op == "equal":
                for offset in range(a1 - a0):
                    mapping[a0 + offset] = b0 + offset
        return mapping
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



# How far (in sticker-Han-index positions) an "after"/"before" lookup may
# bridge across an unmapped alignment gap before giving up. A handful of
# unmapped characters between one edition's digitization and another's
# (a dropped duplicate character, an OCR slip, a resolved variant the
# `replace` pairing couldn't line up) is routine; beyond this the two
# witnesses have likely diverged for real, and guessing a placement would do
# more harm than dropping the mark.
_MAX_GAP_BRIDGE = 6
_WIKISOURCE_MAX_GAP_BRIDGE = 0


def _nearest_mapped(
    mapping: dict[int, int],
    sorted_keys: list[int],
    idx: int,
    *,
    direction: str,
    max_gap: int = _MAX_GAP_BRIDGE,
) -> int | None:
    """Nearest mapped sticker-Han index to ``idx``, within ``max_gap``.

    ``_sticker_to_tape_map`` only has entries for "equal"/"replace" opcode
    runs — a Han character present in one witness but not the other falls in
    a gap with no entry at all. A punctuation mark anchored exactly on such a
    gap used to be silently discarded rather than merely landing one
    character off; this walks outward to the nearest character the fuzzy
    alignment *did* resolve (backward for marks that sit after a character,
    forward for marks that sit before one).
    """
    if idx in mapping:
        return mapping[idx]
    if direction == "back":
        pos = bisect_right(sorted_keys, idx) - 1
    else:
        pos = bisect_left(sorted_keys, idx)
    if pos < 0 or pos >= len(sorted_keys):
        return None
    key = sorted_keys[pos]
    if abs(key - idx) > max_gap:
        return None
    return mapping[key]


def _collect_insertions(
    parallel_text: str,
    tape: str,
    tape_start: int,
    tape_end: int,
    sticker_han: str,
    *,
    split_sentences: bool = True,
    max_gap: int = _MAX_GAP_BRIDGE,
) -> tuple[dict[int, str], dict[int, str], set[int]]:
    """Map parallel punctuation onto tape Han indices.

    ``max_gap=0`` copies a mark only when the Han it follows (or precedes) itself aligned;
    marks anchored on unmatched parallel text are dropped instead of bridged.

    Returns ``(after, before, para_after)``. Most marks (。、「, closing 》) sit
    after the preceding Han character. Marks that open a stretch before any
    Han is seen (typical for a paragraph-initial 《title》) go in ``before`` for
    the next mapped Han character — otherwise leading 《 was silently dropped.
    """
    after: dict[int, str] = {}
    before: dict[int, str] = {}
    para_after: set[int] = set()
    sticker_to_sub = _sticker_to_tape_map(
        sticker_han, tape, tape_start, tape_end, strict=max_gap == 0
    )
    sorted_keys = sorted(sticker_to_sub)
    span = tape_end - tape_start
    han_in_sticker = 0
    pending_nl = 0
    pending_before = ""
    for char in parallel_text.replace("\r\n", "\n").replace("\r", "\n"):
        if HAN_RE.fullmatch(char):
            if pending_nl >= 2:
                local = _nearest_mapped(
                    sticker_to_sub, sorted_keys, han_in_sticker - 1, direction="back", max_gap=max_gap
                )
                if local is not None and 0 <= local < span:
                    para_after.add(tape_start + local)
            pending_nl = 0
            if pending_before:
                local = _nearest_mapped(
                    sticker_to_sub, sorted_keys, han_in_sticker, direction="forward", max_gap=max_gap
                )
                if local is not None and 0 <= local < span:
                    at = tape_start + local
                    before[at] = before.get(at, "") + pending_before
                pending_before = ""
            han_in_sticker += 1
            continue
        if char == "\n":
            pending_nl += 1
            continue
        # An opening mark (《 「 （) belongs to the paragraph it starts, so it must not erase the
        # blank line before it: the break is still owed to the first Han that follows.
        if char not in _OPENING_PUNCT_CHARS:
            pending_nl = 0
        if char in PUNCT_CHARS:
            # An opening mark (「『《（〔) always belongs to whatever Han
            # character comes *next*, not to the one before it -- gluing it
            # onto the preceding character is harmless when both sit in the
            # same stamped span, but wrong whenever a structural boundary
            # (a comm note closing, two independently-matched paragraphs,
            # etc.) falls between them: the mark would render on the wrong
            # side of that boundary. Buffer it the same way a mark seen
            # before any Han at all is already buffered, rather than only
            # doing that at the very start of the text.
            if han_in_sticker == 0 or char in _OPENING_PUNCT_CHARS:
                pending_before += char
                continue
            local = _nearest_mapped(
                sticker_to_sub, sorted_keys, han_in_sticker - 1, direction="back", max_gap=max_gap
            )
            if local is not None and 0 <= local < span:
                at = tape_start + local
                after[at] = after.get(at, "") + char
                if split_sentences and char in SENTENCE_END_PUNCT:
                    para_after.add(at)
    return after, before, para_after


def _base_text_follows(atoms: list[str], index: int) -> bool:
    """True when base-text Han (not a note, not a paragraph end) comes next after ``atoms[index]``."""
    for atom in atoms[index + 1 :]:
        if _is_insignificant_whitespace_atom(atom):
            continue
        if _is_markup(atom):
            if _comm_note_atom(atom) or atom == "</p>" or _is_p_open(atom):
                return False
            continue
        return bool(HAN_RE.fullmatch(atom))
    return False


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


_LEADING_NOTE_RUN_RE = re.compile(
    r"</p>\s*(<p(?:\s[^>]*)?>)"
    r"((?:\s*(?:<pb\b[^>]*/>|<note\b[^>]*\btype=\"comm\"[^>]*>.*?</note>))+)",
    re.DOTALL | re.I,
)
_NOTE_ANY_RE = re.compile(r"<note\b.*?</note>", re.DOTALL | re.I)


def _paragraph_has_base_text(paragraph_xml: str) -> bool:
    """True when a ``<p>`` carries Han outside its commentary notes."""
    without_notes = _NOTE_ANY_RE.sub("", paragraph_xml)
    return bool(HAN_RE.search(re.sub(r"<[^>]+>", "", without_notes)))


def relocate_leading_comm_notes(xml: str) -> str:
    """Never break a paragraph right before inline commentary.

    A comm note (with any page breaks around it) that opens a ``<p>`` glosses the base text
    before it, so it moves back to the end of the preceding paragraph and the break stays where
    the base text resumes. A paragraph left empty by the move is dropped. A preceding paragraph
    that is itself pure commentary is left alone: there the note is not mixed with base text.
    """
    pos = 0
    while True:
        match = _LEADING_NOTE_RUN_RE.search(xml, pos)
        if match is None:
            return xml
        run = match.group(2).strip()
        before = xml[: match.start()]
        p_open = max(before.rfind("<p>"), before.rfind("<p "))
        if (
            not NOTE_OPEN_COMM_RE.search(run)
            or p_open < 0
            or not _paragraph_has_base_text(before[p_open:])
        ):
            pos = match.end()
            continue
        after = xml[match.end() :]
        empty = re.match(r"\s*</p>", after)
        if empty:
            xml = before + run + "</p>" + after[empty.end() :]
        else:
            xml = before + run + "</p>" + match.group(1) + after
        pos = len(before) + len(run)


def _is_p_open(atom: str) -> bool:
    return atom == "<p>" or (atom.startswith("<p ") and atom.endswith(">"))


def _is_insignificant_whitespace_atom(atom: str) -> bool:
    """True for atoms that only carry layout between characters or tags.

    Includes ordinary spaces/tabs/newlines and the ideographic space U+3000
    that Mandoku/Kanripo uses between citations. Chinese text does not use
    inter-character space, so these must be dropped when rewriting the body
    (see ``_emit_atom``), not only skipped when looking ahead for notes.
    """
    return atom in ("\n", "\r", "\t", "　") or (len(atom) > 0 and atom.strip() == "")


def _emit_atom(out: list[str], atom: str) -> None:
    """Append ``atom`` unless it is insignificant whitespace."""
    if not _is_insignificant_whitespace_atom(atom):
        out.append(atom)


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
    keep_end_boundary: bool = False,
) -> bool:
    """Drop Kanripo ``</p><p>`` wraps inside a reflow zone unless parallel marks a break."""
    if atom != "</p>":
        return False
    if han_seen < reflow_start:
        return False
    # `han_seen` is the index of the last Han char already emitted. The break
    # right after the last matched char (han_seen == reflow_end - 1) normally
    # goes too, so two adjacent per-paragraph matches rejoin into one citation.
    # For a whole-text (single tape) match it is the end of the matched text:
    # the next paragraph (e.g. the following poem's title) is not part of it
    # and must not be absorbed.
    last_inside = reflow_end - 1 if keep_end_boundary else reflow_end
    if han_seen >= last_inside:
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


def _opening_mark_precedes(atoms: list[str], index: int) -> bool:
    """True when the visible character just before ``atoms[index]`` is already an opening mark."""
    for atom in reversed(atoms[:index]):
        if _is_markup(atom):
            continue
        return atom in _OPENING_PUNCT_CHARS
    return False


def _punct_follows(atoms: list[str], index: int) -> bool:
    """True when the next visible character after ``atoms[index]`` is already a mark."""
    for atom in atoms[index + 1 :]:
        if _is_markup(atom):
            continue
        return atom in PUNCT_CHARS
    return False


def _apply_han_jobs(
    body_xml: str,
    jobs: list[tuple[tuple[int, int], str, str]],
    *,
    reflow_paragraphs: bool = True,
    keep_existing_marks: bool = False,
    strict_marks: bool = False,
    add_breaks_only: bool = False,
    sentence_breaks: bool = True,
    exact_ranges: bool = False,
) -> tuple[str, list[tuple[int, int]], list[CoverageSpan]]:
    """Apply punctuation for several Han ranges in one pass.

    ``keep_existing_marks`` drops an inserted mark when the body already has a mark right there.
    ``strict_marks`` copies only marks anchored on a Han that aligned (see ``_collect_insertions``).
    ``add_breaks_only`` (with ``reflow_paragraphs``) adds the parallel's paragraph breaks but never
    removes a break the body already has. ``exact_ranges`` takes each job's range as already
    aligned instead of re-searching it with the fuzzy overlap finder (which can trim a stretch's
    first or last words).
    """
    if not jobs:
        return body_xml, [], []
    atoms = _iter_xml_atoms_segmented(body_xml)
    tape, _ = _han_tape(atoms)
    insertions_after: dict[int, str] = {}
    insertions_before: dict[int, str] = {}
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
        if exact_ranges:
            abs_start, abs_end = tape_start, tape_end
        else:
            sub_overlap = find_han_overlap(tape[tape_start:tape_end], sticker)
            if sub_overlap is None:
                continue
            abs_start = tape_start + sub_overlap[0]
            abs_end = tape_start + sub_overlap[1]
        stamp_ranges.append((abs_start, abs_end))
        seg_after, seg_before, seg_para = _collect_insertions(
            parallel_text,
            tape,
            abs_start,
            abs_end,
            sticker,
            split_sentences=sentence_breaks and label != "comm",
            max_gap=0 if strict_marks else _MAX_GAP_BRIDGE,
        )
        for key, value in seg_after.items():
            insertions_after[key] = insertions_after.get(key, "") + value
        for key, value in seg_before.items():
            insertions_before[key] = insertions_before.get(key, "") + value
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
    elif add_breaks_only:
        reflow_start = reflow_end = -1
    pending_split = False
    break_after_marks = False
    out: list[str] = []
    han_seen = -1
    opened_here = 0
    stamp_depth = 0
    other_seg_depth = 0
    skip_until = -1
    in_comm_note = False

    stamped_han = bytearray(total + 1)
    for start, end in stamp_ranges:
        stamped_han[max(0, start) : min(total, end)] = b"\x01" * max(0, min(total, end) - max(0, start))

    def in_stamp(han_index: int) -> bool:
        return 0 <= han_index < total and stamped_han[han_index] == 1

    def close_stamp_at_boundary(atom: str) -> bool:
        return (
            atom in ("</p>", "</note>")
            or NOTE_OPEN_COMM_RE.fullmatch(atom) is not None
        )

    for atom_index, atom in enumerate(atoms):
        if atom_index <= skip_until:
            continue
        if _should_skip_line_paragraph_break(
            atom,
            atoms,
            atom_index,
            han_seen,
            reflow_start,
            reflow_end,
            para_after,
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
            prefix = insertions_before.get(han_seen, "")
            if prefix and keep_existing_marks and _opening_mark_precedes(atoms, atom_index):
                prefix = ""
            if prefix:
                out.append(prefix)
        _emit_atom(out, atom)
        if atom == "</note>" and pending_split:
            # A break the parallel puts after the note's last character (e.g. before a new 疏
            # paragraph) cannot fall inside the note: it goes where the base text resumes.
            pending_split = False
            if _base_text_follows(atoms, atom_index):
                before_len = len(out)
                opened_here, stamp_depth = _emit_paragraph_split(
                    out, opened_here, stamp_depth, atoms, atom_index
                )
                if len(out) > before_len:
                    skip_until = max(skip_until, _skip_natural_break_after_split(atoms, atom_index))
        elif atom == "</p>":
            pending_split = False
            break_after_marks = False
        if break_after_marks and not is_han and not _is_markup(atom) and atom in PUNCT_CHARS:
            # The anchor already carries marks (e.g. a 。 from an earlier pass): the break goes
            # after the last of them, not between the character and its mark.
            if not _punct_follows(atoms, atom_index):
                break_after_marks = False
                before_len = len(out)
                opened_here, stamp_depth = _emit_paragraph_split(
                    out, opened_here, stamp_depth, atoms, atom_index
                )
                if len(out) > before_len:
                    skip_until = max(skip_until, _skip_natural_break_after_split(atoms, atom_index))
        if is_han:
            extra = insertions_after.get(han_seen, "")
            if extra and keep_existing_marks and _punct_follows(atoms, atom_index):
                extra = ""
            if extra:
                out.append(extra)
            if han_seen in para_after and in_comm_note:
                pending_split = True
            elif (
                han_seen in para_after
                and not in_comm_note
                and not _comm_note_follows(atoms, atom_index)
                and keep_existing_marks
                and _punct_follows(atoms, atom_index)
            ):
                break_after_marks = True
            elif (
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
    """Extract a substring covering Han indices ``[han_start, han_end)``, plus
    trailing punctuation after the last kept Han character and opening
    punctuation (``「『《（〔``) immediately before the first one.

    Trimming a citation down to a Han-index window (e.g. one paragraph's
    matched slice of a longer, merged parallel excerpt) routinely starts
    right after a title/quote-opening mark like ``《`` — the mark itself
    isn't Han, so it was never part of the kept range, and without this it
    was silently dropped from every trim rather than merely landing outside
    ``[han_start, han_end)``. Only *opening* marks are pulled in: the
    character right before ``start_char`` could just as easily be the
    sentence-final punctuation of the *excluded* preceding content (a
    dropped ``。`` or ``，``), which must stay dropped.
    """
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
    while start_char > 0 and text[start_char - 1] in _OPENING_PUNCT_CHARS:
        start_char -= 1
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
        if not sticker or body_seg["kind"] == "head":
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


def coverage_from_stamps(body_xml: str, *, segmented: bool = False) -> Coverage:
    """Rebuild coverage from existing ``type="grognard:parallel-punct"`` stretches
    (legacy ``ana="…"`` stamps are still recognised).

    ``segmented=True`` counts the Han inside ``<note type="comm">`` too, so indices and the
    total match :func:`list_segments` and the coverage bars.
    """
    atoms = _iter_xml_atoms_segmented(body_xml) if segmented else _iter_xml_atoms(body_xml)
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
    keep_end_boundary: bool = False,
    max_gap: int = _MAX_GAP_BRIDGE,
) -> tuple[str, tuple[int, int] | None, str]:
    """Copy ``match_text`` punctuation onto ``body_xml`` over Han range ``[tape_start, tape_end)``.

    ``segmented=True`` walks the body with :func:`_iter_xml_atoms_segmented` so the
    Han index space matches ``list_segments`` (``<note type="comm">`` innards are
    counted). In that mode marks may land *inside* a comm note, but the
    ``<seg type="grognard:parallel-punct">`` stamp and ``</p><p>`` reflow splits are
    suppressed there — commentary is punctuated, never wrapped or reflowed.
    """
    insertions_after, insertions_before, para_after = _collect_insertions(
        match_text,
        tape,
        tape_start,
        tape_end,
        sticker,
        split_sentences=False,
        max_gap=max_gap,
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
    head_depth = 0

    def close_stamp_at_boundary(atom: str) -> bool:
        return (
            atom in ("</p>", "</head>", "</note>")
            or NOTE_OPEN_COMM_RE.fullmatch(atom) is not None
        )

    for atom_index, atom in enumerate(atoms):
        if atom_index <= skip_until:
            continue
        if _should_skip_line_paragraph_break(
            atom,
            atoms,
            atom_index,
            han_seen,
            reflow_start,
            reflow_end,
            para_after,
            keep_end_boundary,
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

        if atom.startswith("<head") and not atom.startswith("<header"):
            head_depth += 1
        elif atom == "</head>" and head_depth > 0:
            head_depth -= 1

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
            prefix = insertions_before.get(han_seen, "")
            if prefix:
                out.append(prefix)
        _emit_atom(out, atom)
        if is_han:
            extra = insertions_after.get(han_seen, "")
            if extra:
                out.append(extra)
            if (
                han_seen in para_after
                and head_depth == 0  # a `</p><p>` inside <head> is not well-formed
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
    keep_end_boundary: bool = False,
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
    # keep_end_boundary=True (AI selections): the </p> right after the scoped range ends a
    # paragraph that is not part of this match and must not be absorbed. Default False lets
    # adjacent per-paragraph matches (paragraph-aligned import) rejoin into one citation.
    final_xml, overlap, preview = _apply_parallel_at_range(
        body_xml,
        match_text,
        sticker,
        tape,
        tape_start,
        tape_end,
        segmented=True,
        keep_end_boundary=keep_end_boundary,
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


def _fold_han_variants(text: str) -> str:
    """Length-preserving variant fold for *comparison only* (never for output)."""
    from kanripo_import.normalize_tables import Normalizer, hard_replacements_table

    folded = Normalizer.from_package_data().normalize_text(text)
    table = hard_replacements_table()
    return "".join(
        table[ch] if ch in table and len(table[ch]) == 1 else ch for ch in folded
    )


def _apply_one(
    body_xml: str, parallel_text: str, *, max_gap: int = _MAX_GAP_BRIDGE
) -> tuple[str, tuple[int, int] | None, str]:
    atoms = _iter_xml_atoms(body_xml)
    tape, _ = _han_tape(atoms)
    match_text = _normalize_parallel_match_text(parallel_text)
    sticker = han_only(match_text)
    # Locate on a variant-folded comparison key (於/于, 兹/茲, 濳/潛 …). The fold
    # is strictly 1:1, so indices into the folded strings are indices into the
    # real tape/sticker, which everything after this point still uses.
    overlap = find_han_overlap_flexible(_fold_han_variants(tape), _fold_han_variants(sticker))
    if overlap is None:
        return body_xml, None, ""

    tape_start, tape_end = overlap
    return _apply_parallel_at_range(
        body_xml,
        match_text,
        sticker,
        tape,
        tape_start,
        tape_end,
        keep_end_boundary=True,
        max_gap=max_gap,
    )


def strip_inline_commentary(parallel_text: str) -> str:
    """Remove ctext-style inline commentary spans for main-text-only tape matching."""
    return INLINE_COMM_RE.sub("", parallel_text)


def apply_parallel_punctuation(body_xml: str, parallel_text: str) -> ParallelPunctResult:
    """Insert parallel punctuation/paragraphs onto the overlapping Han range."""
    return apply_parallel_sources(body_xml, [{"id": "paste", "label": "Paste", "text": parallel_text}])


# --- Edition-tolerant sequence alignment -------------------------------------------------
#
# Two editions of one work rarely agree on what is base text and what is commentary: the Siku
# 爾雅注疏 runs 經 and 郭璞注 together as plain text and keeps 疏 in ``<note type="comm">``,
# while Wikisource's 爾雅註疏 sets 注 in （…） and 疏 as plain paragraphs. Matching base text
# only with base text and commentary only with commentary leaves most of such a juan untouched.
# This pass ignores those roles: it aligns the whole juan's Han against the whole parallel as one
# ordered sequence and copies marks across every stretch that lines up well, whatever either
# edition calls that stretch. Stretches that do not line up (音義 notes absent from the other
# edition, genuinely different readings) are left alone rather than guessed.

ALIGN_MIN_BLOCK = 3  # shortest exact run (Han) kept; a stretch still needs ALIGN_MIN_STRETCH
ALIGN_MAX_GAP = 12  # most unmatched Han (either side) bridged inside one stretch
ALIGN_MAX_GAP_SKEW = 8  # most the two sides' gaps may differ (insertion vs substitution)
ALIGN_MIN_STRETCH = 10  # fewest matched Han for a stretch to be trusted
ALIGN_MIN_DENSITY = 0.7  # matched / spanned Han inside a stretch

_ALIGN_MARK_MAP = str.maketrans({"︰": "：", "﹔": "；"})


# 十三經註疏 layout (zh.wikisource): every 疏 paragraph opens by *citing* the lemma it explains --
# ``疏「明明、斤斤，察也」。○釋曰：…`` or ``疏「卬吾」至「我也」。○釋曰：…`` -- which the Siku 疏 note does
# not carry. Left in, the citation is a second copy of the 經 text (now inside quotation marks) and
# the 經 in the body can anchor to it, taking the quotes with it.
_SHU_CITATION = r"[疏注]?[「『“][^」』”\n]*[」』”]"
_SHU_HEADER_RE = re.compile(
    r"^(?:【疏】|疏|注)"
    rf"(?:[\s　]*{_SHU_CITATION}(?:[\s　]*至[\s　]*{_SHU_CITATION})?[。，、]?)*"
    r"[\s　]*(?:[○〇][\s　]*)?"
    r"(?:釋曰|正義曰|疏曰)?[：:︰]?[\s　]*",
    re.M,
)
_SHU_MARKER_RE = re.compile(r"釋曰|正義曰|疏曰")
SHU_LAYOUT_MIN_HEADERS = 3  # citation headers a text needs before it counts as 註疏 layout


def strip_shu_citations(parallel_text: str) -> str:
    """Drop the lemma citation(s) and 釋曰 that open a 十三經註疏 疏 paragraph, keeping a 疏 label.

    Shapes seen on zh.wikisource: ``疏「…」。○釋曰：``, ``疏「…」至「…」。○釋曰：``,
    ``【疏】「…」至「…」。○釋曰：``, ``疏「…」。注「…」。○釋曰：`` (a 疏 on a lemma *and* its 注) and
    ``注「…」。○釋曰：`` (a 疏 on a 注). A paragraph that merely starts with 注 is only a header when it
    also carries 釋曰, so ordinary 注 text is never touched.
    """

    def rewrite(match: re.Match[str]) -> str:
        header = match.group(0)
        cites = len(re.findall(_SHU_CITATION, header))
        has_marker = bool(_SHU_MARKER_RE.search(header))
        if header.startswith("注"):
            real = cites >= 1 and has_marker
        else:
            real = len(header) > 1 and (cites >= 1 or has_marker)
        return "疏" if real else header

    # Only a text that really uses this layout is touched: a lone paragraph that happens to begin
    # ``疏「…」`` in some other work is ordinary text, not a citation header.
    headers = sum(1 for m in _SHU_HEADER_RE.finditer(parallel_text) if rewrite(m) == "疏" and len(m.group(0)) > 1)
    if headers < SHU_LAYOUT_MIN_HEADERS:
        return parallel_text
    return _SHU_HEADER_RE.sub(rewrite, parallel_text)


def prepare_wikisource_parallel(parallel_text: str) -> str:
    """Wikisource edition markup that must not reach the matcher or the body."""
    return strip_shu_citations(_clean_parallel_for_alignment(parallel_text))


def _clean_parallel_for_alignment(parallel_text: str) -> str:
    """Parallel text with edition-specific markup that must not be copied removed.

    ``（…）`` brackets mark 注 in Wikisource's 註疏 but are plain text in a Siku body, so the
    brackets themselves are dropped (their contents stay and still match). Compatibility
    colons are mapped to the marks the importer knows.
    """
    text = parallel_text.translate(_ALIGN_MARK_MAP)
    return text.replace("（", "").replace("）", "")


def _aligned_stretches(
    tape: str,
    sticker: str,
    covered: list[tuple[int, int]],
) -> list[tuple[int, int, int, int, int, list[tuple[int, int, int]]]]:
    """Stretches ``(tape_start, tape_end, ref_start, ref_end, matched, blocks)`` outside ``covered``.

    ``blocks`` are the exact ``(tape, ref, size)`` runs inside the stretch (including 2-Han runs
    that sit between its anchors), for callers that need to know which tape Han really aligned to
    which parallel Han. Only the anchors of at least ``ALIGN_MIN_BLOCK`` count toward the stretch.
    """
    if not tape or not sticker:
        return []
    folded_tape = _fold_han_variants(tape)
    folded_sticker = _fold_han_variants(sticker)
    covered_flags = bytearray(len(tape) + 1)
    for start, end in covered:
        lo, hi = max(0, start), min(len(tape), end)
        if hi > lo:
            covered_flags[lo:hi] = b"\x01" * (hi - lo)

    blocks: list[tuple[int, int, int]] = []
    small: list[tuple[int, int, int]] = []  # 2-Han blocks: too weak to anchor, fine inside a stretch
    matcher = SequenceMatcher(None, folded_tape, folded_sticker, autojunk=False)
    for block in matcher.get_matching_blocks():
        if block.size < ALIGN_MIN_BLOCK:
            if block.size >= 2 and not any(covered_flags[block.a : block.a + block.size]):
                small.append((block.a, block.b, block.size))
            continue
        run_start: int | None = None
        for offset in range(block.size + 1):
            free = offset < block.size and not covered_flags[block.a + offset]
            if free and run_start is None:
                run_start = offset
            elif not free and run_start is not None:
                if offset - run_start >= ALIGN_MIN_BLOCK:
                    blocks.append((block.a + run_start, block.b + run_start, offset - run_start))
                run_start = None

    stretches: list[tuple[int, int, int, int, int, list[tuple[int, int, int]]]] = []
    current: list[tuple[int, int, int]] = []

    def close() -> None:
        if not current:
            return
        matched = sum(size for _, _, size in current)
        t_start, r_start = current[0][0], current[0][1]
        t_end = current[-1][0] + current[-1][2]
        r_end = current[-1][1] + current[-1][2]
        span = max(t_end - t_start, r_end - r_start)
        if matched >= ALIGN_MIN_STRETCH and matched / max(1, span) >= ALIGN_MIN_DENSITY:
            inside = [
                blk
                for blk in small
                if t_start <= blk[0] and blk[0] + blk[2] <= t_end
                and r_start <= blk[1] and blk[1] + blk[2] <= r_end
            ]
            stretches.append(
                (t_start, t_end, r_start, r_end, matched, sorted([*current, *inside]))
            )
        current.clear()

    for a, b, size in blocks:
        if current:
            prev_a, prev_b, prev_size = current[-1]
            gap_a = a - (prev_a + prev_size)
            gap_b = b - (prev_b + prev_size)
            if not (
                gap_a <= ALIGN_MAX_GAP
                and gap_b <= ALIGN_MAX_GAP
                and abs(gap_a - gap_b) <= ALIGN_MAX_GAP_SKEW
            ):
                close()
        current.append((a, b, size))
    close()
    return stretches


WRAP_MAX_SUBSTITUTION = 4  # longest differing stretch (either side) still read as a variant


def _flag_substituted_boundary_chars(
    blocks: list[tuple[int, int, int]],
    paren_flags: list[bool],
    flagged: set[int],
) -> None:
    """Pull a variant character at the *start* of a parenthesised run into the run.

    Where two editions write different characters for the same word (窗 / 牕), the pair does not
    align, so the body character would be left outside the note that begins right after it.
    Between two consecutive aligned blocks, the unmatched body characters and the unmatched
    parallel characters are paired from the right (the side that touches the parenthesised
    text); a body character is flagged only when the parallel character it is paired with is
    itself parenthesised. Unpaired body characters (a label such as 注) stay outside, as KRP has
    them.

    Only the start boundary is read this way. After a run, the unmatched body characters are
    usually the *next* label (音義, 疏), which must never be absorbed.
    """
    for (a, b, size), (a2, _b2, _size2) in zip(blocks, blocks[1:]):
        w0, w1 = b + size, _b2
        t0, t1 = a + size, a2
        n_tape, n_ws = t1 - t0, w1 - w0
        if n_tape <= 0 or n_ws <= 0 or max(n_tape, n_ws) > WRAP_MAX_SUBSTITUTION:
            continue
        if not paren_flags[w1] or paren_flags[w0 - 1]:
            continue  # the next block must open a parenthesised run, the previous one must not be in it
        for k in range(min(n_tape, n_ws)):
            if paren_flags[w1 - 1 - k]:
                flagged.add(t1 - 1 - k)


def _commentary_as_parentheses(parallel_text: str) -> str:
    """Express every commentary convention the parallel may use as ``（…）``.

    Wikisource's ``〈…〉`` interlinear notes and ctext's inline-comment spans are commentary
    *text* that the body has too, so it must stay in the aligned sequence (the older passes
    removed it to match base text only). It is flagged as commentary the same way ``（…）`` is.
    """
    text = INLINE_COMM_RE.sub(lambda m: "（" + m.group(1) + "）", parallel_text)
    return WIKISOURCE_COMM_RE.sub(lambda m: "（" + m.group(0)[1:-1] + "）", text)


def _paren_han_flags(text: str) -> list[bool]:
    """For each Han of ``text`` (in order): is it inside parentheses ``（…）`` / ``(…)``?

    Parentheses are how most punctuated editions mark interlinear commentary (注, 音義).
    """
    flags: list[bool] = []
    depth = 0
    for ch in text:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        elif HAN_RE.fullmatch(ch):
            flags.append(depth > 0)
    return flags


_WRAP_BLOCK_TAG_RE = re.compile(r"</?(?:p|div|head|byline|trailer|lg|l|list|item|table|row|cell)\b", re.I)
WRAP_MIN_RUN = 2  # fewest Han in a run worth turning into a note
LABEL_MIN_COUNT = 5  # a 2-Han string seen this often right before KRP's own notes is a label
LABEL_MIN_SHARE = 0.03  # ...and before at least this share of them
WRAP_MAX_GAP = 3  # unmatched body Han bridged inside one run


# ``</note></p>\n<p><note>``: one gloss cut by a Kanripo line wrap. The real body has a newline between
# paragraphs, which ``SPLIT_COMM_RE`` (written for the compact form) does not match.
# Only notes the wrapper created carry this temporary marker, so a note KRP itself marked is never
# merged, retyped or resized (see docs/kanripo-commentary-principles.md).
_WRAP_MARK = ' data-wrapped="1"'
_WRAPPED_OPEN = f'<note type="comm"{_WRAP_MARK}>'
_WRAPPED_SPLIT_NOTE_RE = re.compile(
    re.escape(_WRAPPED_OPEN)
    + r"((?:(?!</note>).)*)</note>\s*</p>\s*<p(?:\s[^>]*)?>\s*(<pb\b[^>]*/>\s*)?"
    + re.escape(_WRAPPED_OPEN),
    re.I | re.S,
)


def _join_split_notes(xml: str) -> str:
    """Join wrapper-created notes that a paragraph break (any whitespace / page break) cut in two.

    Both halves must be wrapper-created: a note KRP marked is never merged, on either side.
    """
    previous = None
    while previous != xml:
        previous = xml
        xml = _WRAPPED_SPLIT_NOTE_RE.sub(
            lambda m: _WRAPPED_OPEN + m.group(1) + (m.group(2) or "").strip(), xml
        )
    return xml


def _learn_note_labels(atoms: list[str]) -> list[str]:
    """Two-Han labels this body writes right before its own (KRP-marked) notes, e.g. 音義.

    Learned from the text, not assumed: a string counts only if it precedes KRP's notes often
    (``LABEL_MIN_COUNT`` times and ``LABEL_MIN_SHARE`` of all of them), so a text whose notes
    follow ordinary prose learns none and nothing changes for it.
    """
    counts: dict[str, int] = {}
    total = 0
    history: list[str] = []
    in_note = False
    for atom in atoms:
        if _is_markup(atom):
            if NOTE_OPEN_COMM_RE.fullmatch(atom):
                total += 1
                if len(history) >= 2:
                    key = "".join(history[-2:])
                    counts[key] = counts.get(key, 0) + 1
                history.clear()
                in_note = True
            elif atom == "</note>":
                history.clear()  # what follows a note starts a new stretch of base text
                in_note = False
            elif _WRAP_BLOCK_TAG_RE.match(atom):
                history.clear()
            continue
        if in_note:
            continue
        if HAN_RE.fullmatch(atom):
            history.append(atom)
        else:
            history.clear()  # a mark between them: not one label
    return [
        key
        for key, n in counts.items()
        if n >= LABEL_MIN_COUNT and total and n / total >= LABEL_MIN_SHARE
    ]


def _wrap_paren_commentary(
    body_xml: str,
    flagged: set[int],
    matched: set[int],
) -> str:
    """Wrap runs of base-text Han that aligned to parenthesised parallel text in a comm note.

    ``flagged`` are full-tape Han indices that aligned to a Han inside ``（…）``; ``matched`` is
    every aligned index (so a Han that aligned to *non*-parenthetical text ends a run). Han that
    already sit in a note, a head, or across a paragraph boundary are never touched, and the
    literal 注 / 音義 / 疏 label chars that precede a gloss stay outside, like the existing notes.
    """
    atoms = _iter_xml_atoms_segmented(body_xml)
    labels = _learn_note_labels(atoms)
    open_at: dict[int, int] = {}
    close_after: set[int] = set()
    han = -1
    in_note = False
    in_head = False
    run: list[int] | None = None  # [first atom, last flagged atom, flagged count, gap]
    run_atoms: list[int] = []  # atom index of each flagged Han in the run
    gap_text: list[str] = []  # unmatched Han seen since the last flagged one

    def end_run() -> None:
        nonlocal run
        if run is not None and run[2] >= WRAP_MIN_RUN:
            open_at[run[0]] = run[1]
            close_after.add(run[1])
        run = None
        run_atoms.clear()
        gap_text.clear()

    def trim_label_from_run(next_char: str = "") -> None:
        """A run must not end inside the label KRP writes before its own next note.

        ``next_char`` is the character that ended the run, when one did (a body character that
        aligned to non-parenthetical text), so a label split between the run and that character
        is recognised too.
        """
        if run is None or not labels:
            return
        after = "".join(gap_text) + next_char
        if not after:
            return
        tail = "".join(atoms[i] for i in run_atoms[-2:]) + after
        for label in labels:
            if len(label) > len(after) and tail.endswith(label):
                cut = len(label) - len(after)
                del run_atoms[-cut:]
                if not run_atoms:
                    run[2] = 0
                else:
                    run[1] = run_atoms[-1]
                    run[2] -= cut
                break

    for index, atom in enumerate(atoms):
        if _is_markup(atom):
            if NOTE_OPEN_COMM_RE.fullmatch(atom) or atom.startswith("<note"):
                trim_label_from_run()
                end_run()
                in_note = True
            elif atom == "</note>":
                end_run()
                in_note = False
            elif HEAD_OPEN_RE.fullmatch(atom):
                trim_label_from_run()
                end_run()
                in_head = True
            elif HEAD_CLOSE_RE.fullmatch(atom):
                trim_label_from_run()
                end_run()
                in_head = False
            elif _WRAP_BLOCK_TAG_RE.match(atom):
                # Kanripo's line wrap can fall between a label and its note (…音義</p><p><note>),
                # so a paragraph boundary ends a run just as a note does.
                trim_label_from_run()
                end_run()
            continue
        if not HAN_RE.fullmatch(atom):
            continue
        han += 1
        if in_note or in_head:
            continue
        if han in flagged:
            if run is None:
                run = [index, index, 0, 0]
            run[1] = index
            run[2] += 1
            run[3] = 0
            run_atoms.append(index)
            gap_text.clear()
        elif run is not None:
            if han in matched:
                trim_label_from_run(atom)
                end_run()  # aligned to non-parenthetical parallel text: the gloss ended
            else:
                run[3] += 1
                gap_text.append(atom)
                if run[3] > WRAP_MAX_GAP:
                    end_run()
    end_run()
    if not open_at:
        return body_xml
    out: list[str] = []
    for index, atom in enumerate(atoms):
        if index in open_at:
            out.append(_WRAPPED_OPEN)
        out.append(atom)
        if index in close_after:
            out.append("</note>")
    return "".join(out)


def apply_parallel_aligned(
    body_xml: str,
    parallel_text: str,
    *,
    covered: list[tuple[int, int]] | None = None,
    source_label: str = "aligned",
    wrap_commentary: bool = True,
) -> ParallelPunctResult:
    """Copy punctuation across every well-aligned stretch, ignoring base/commentary roles.

    When the parallel marks commentary with parentheses, the body text aligned to it is first
    wrapped in ``<note type="comm">`` (only on a body no earlier pass has stamped).

    ``covered`` is Han ranges (full tape, notes included) to leave alone; by default whatever
    ``body_xml`` already carries parallel-punct stamps for.
    """
    merged = merge_split_comm_notes(body_xml)
    atoms = _iter_xml_atoms_segmented(merged)
    tape, _ = _han_tape(atoms)
    total = len(tape)
    normalized = _commentary_as_parentheses(parallel_text)
    paren_flags = _paren_han_flags(normalized)
    cleaned = _clean_parallel_for_alignment(normalized)
    sticker = han_only(cleaned)
    if covered is None:
        covered = [
            (int(round(span["start"] * total)), int(round(span["end"] * total)))
            for span in (coverage_from_stamps(merged, segmented=True).get("spans") or [])
        ]
    stretches = _aligned_stretches(tape, sticker, covered)
    if wrap_commentary and not covered and any(paren_flags) and len(paren_flags) == len(sticker):
        flagged: set[int] = set()
        matched_idx: set[int] = set()
        for *_bounds, blocks in stretches:
            for a, b, size in blocks:
                for offset in range(size):
                    matched_idx.add(a + offset)
                    if paren_flags[b + offset]:
                        flagged.add(a + offset)
            _flag_substituted_boundary_chars(blocks, paren_flags, flagged)
        wrapped = _wrap_paren_commentary(merged, flagged, matched_idx)
        # Kanripo hard-wraps plain text into one <p> per print line, so a gloss that runs over
        # a line break was wrapped once per line: join those back into one note.
        wrapped = _join_split_notes(wrapped).replace(_WRAP_MARK, "")
        if wrapped != merged:
            try:
                assert_well_formed(wrapped)
                same_tape = _han_tape(_iter_xml_atoms_segmented(wrapped))[0] == tape
            except ET.ParseError:
                same_tape = False
            if same_tape:
                merged = wrapped
    jobs = [
        ((t_start, t_end), _slice_text_by_han_range(cleaned, r_start, r_end), source_label)
        for t_start, t_end, r_start, r_end, _matched, _blocks in stretches
    ]
    if not jobs:
        return {"body_xml": body_xml, "coverage": _empty_coverage(total), "applied": False}

    xml, intervals, spans = _apply_han_jobs(
        merged,
        jobs,
        reflow_paragraphs=True,
        add_breaks_only=True,
        keep_existing_marks=True,
        strict_marks=True,
        sentence_breaks=False,
        exact_ranges=True,
    )
    xml = _finalize_parallel_xml(merged, xml)
    if xml == merged and intervals:
        intervals, spans = [], []
    coverage = _coverage_from_intervals(total, intervals, spans)
    return {"body_xml": xml, "coverage": coverage, "applied": bool(intervals)}


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
    aligned_labels: set[str] = set()  # sources transferred by the aligned pass already
    raw_by_label: dict[str, str] = {}  # parallel text with its （…） commentary brackets intact
    aligned_any = False

    for source in sources:
        parallel_text = str(source.get("text") or "")
        raw_text = parallel_text
        label = str(source.get("label") or source.get("id") or "source")
        catalog_match = None
        if source.get("chapters"):
            parallel_text, catalog_match = resolve_wikisource_parallel(
                body_xml,
                source,
                used_ids=used_chapters,
            )
            # Keep the （…） that mark 注 until the aligned pass has read them; the older passes
            # get the bracket-free text (brackets are never copied into the body).
            parallel_text = strip_shu_citations(parallel_text)
            raw_text = parallel_text
            parallel_text = _clean_parallel_for_alignment(parallel_text)
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
        raw_by_label[label] = raw_text
        if source.get("chapters"):
            # A Wikisource edition is transferred by whole-juan alignment: it follows the
            # parallel's own structure (lemma / 注 / 疏 paragraphs) instead of guessing which
            # stretch of the juan a phrase belongs to. When it covers little of the juan (front
            # matter, a single contiguous block) the older tape and comm passes below take over,
            # and the aligned pass then only fills what they leave.
            aligned = apply_parallel_aligned(xml, raw_text, source_label=f"{label}:aligned")
            if aligned["applied"] and float(aligned["coverage"].get("ratio") or 0) >= LOW_OVERLAP_RATIO:
                xml = aligned["body_xml"]
                applied_any = aligned_any = True
                aligned_labels.add(label)
                continue
        # Two editions of a Wikisource work differ at phrase level (注/疏 wording, absent 音義),
        # so a mark anchored on unmatched text is more likely stranded than a lost-char slip:
        # bridge only a character or two there, instead of the usual handful.
        xml, overlap, preview = _apply_one(
            xml,
            parallel_text,
            max_gap=_WIKISOURCE_MAX_GAP_BRIDGE if source.get("chapters") else _MAX_GAP_BRIDGE,
        )
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
        if label in aligned_labels or not WIKISOURCE_COMM_RE.search(parallel_text):
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

    for label, parallel_text in resolved_sources:
        if label in aligned_labels:
            continue
        aligned = apply_parallel_aligned(
            xml, raw_by_label.get(label, parallel_text), source_label=f"{label}:aligned"
        )
        if not aligned["applied"]:
            continue
        xml = aligned["body_xml"]
        applied_any = aligned_any = True

    if aligned_any:
        # The aligned pass works on the full tape (comm-note Han included); report coverage on
        # that same tape, from the stamps, so the ratio, the quality warnings and the coverage
        # bars all agree.
        coverage = coverage_from_stamps(xml, segmented=True)
    else:
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
    """Concatenate visible text inside ``grognard:parallel-punct`` segs."""
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


def _strip_duplicate_heading_tail(out: list[str], heading_text: str) -> None:
    """Remove a plain-text run right before ``out``'s current end (skipping
    over a trailing ``</p>``, if any) whose Han content exactly matches
    ``heading_text``.

    The Kanripo raw source sometimes keeps a section's own label as
    unstamped trailing text inside the *previous* ``<p>``, with no
    structural separation from it — inserting a proper ``<head>`` for that
    same label (from the reference witness, via the position it anchors on)
    would otherwise leave it duplicated: once as stray plain text, once as
    the new element. Exact-match only, over the whole trailing run — this
    never risks eating unrelated content the way a suffix match could.
    """
    heading_han = han_only(heading_text)
    if not heading_han:
        return
    end = len(out)
    if end > 0 and out[end - 1] == "</p>":
        end -= 1
    start = end
    while start > 0 and HAN_RE.fullmatch(out[start - 1]):
        start -= 1
    if han_only("".join(out[start:end])) == heading_han:
        del out[start:end]


_HEAD_LEVEL_RANK = {"chapter": 0, "section": 1, "subsection": 2}


def insert_heads(body_xml: str, insertions: list[tuple[int, str, str]]) -> str:
    """Wrap ``<div type="…"><head type="…">text</head>…</div>`` around each
    stretch starting at a given Han-tape position.

    ``insertions`` is a list of ``(han_start, level, text)`` triples — the
    same ``han_start`` a ``RefParagraph`` (see paragraph_align.py) carries
    for the paragraph a heading should precede; ``level`` is ``"chapter"``,
    ``"section"`` or ``"subsection"``. A ``han_start`` that isn't itself the
    start of a fresh ``<p>`` (e.g. a mid-paragraph, ideographic-space-
    separated citation unit) is silently skipped — a heading can only start
    at a ``<p>`` boundary, and guessing a mid-paragraph placement would be
    worse than omitting it.

    TEI's content model only allows ``<head>`` *before* any ``<p>`` at a
    given div level — one appearing after content has already started there
    needs a genuinely new nested ``<div>``, not a sibling ``<head>``. Every
    insertion therefore closes any currently open div at its own level or
    deeper (so a same-or-shallower heading properly ends a previous
    section/subsection) before opening its own, keeping the nesting valid
    regardless of how many headings land in a juan or in what order —
    including the rare case of a second "chapter"-level heading landing
    mid-document (multiple reference-source files can each contribute their
    own file-opening line), which becomes a new top-level sibling div rather
    than an invalid second top-level ``<head>``.
    """
    pending: dict[int, list[tuple[str, str]]] = {}
    for han_start, level, text in insertions:
        pending.setdefault(han_start, []).append((level, text))
    if not pending:
        return body_xml

    out: list[str] = []
    han_count = 0
    open_levels: list[str] = []

    def close_same_or_deeper(level: str) -> None:
        rank = _HEAD_LEVEL_RANK.get(level, 1)
        while open_levels and _HEAD_LEVEL_RANK.get(open_levels[-1], 1) >= rank:
            open_levels.pop()
            out.append("</div>")

    for atom in _iter_xml_atoms_segmented(body_xml):
        if atom == "</div>":
            while open_levels:
                open_levels.pop()
                out.append("</div>")
        if _is_p_open(atom) and han_count in pending:
            for level, text in pending.pop(han_count):
                _strip_duplicate_heading_tail(out, text)
                close_same_or_deeper(level)
                out.append(f'<div type="{level}"><head type="{level}">{text}</head>')
                open_levels.append(level)
        out.append(atom)
        if HAN_RE.fullmatch(atom):
            han_count += 1
    return "".join(out)
