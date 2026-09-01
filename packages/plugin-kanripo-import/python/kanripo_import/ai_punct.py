"""AI punctuation: list segments, verify JSON insertions, apply without changing Han."""

from __future__ import annotations

from typing import TypedDict
from xml.etree import ElementTree as ET

from kanripo_import.parallel_punct import (
    HAN_RE,
    NOTE_OPEN_COMM_RE,
    PUNCT_CHARS,
    SENTENCE_END_PUNCT,
    MIN_PUNCT_PER_100_HAN,
    Coverage,
    _atoms_han,
    _comm_note_follows,
    _coverage_from_intervals,
    _emit_paragraph_split,
    _empty_coverage,
    _han_tape,
    _is_insignificant_whitespace_atom,
    _is_markup,
    _is_p_open,
    _iter_xml_atoms_segmented,
    _paragraph_open_index,
    _should_skip_line_paragraph_break,
    _skip_natural_break_after_split,
    _stamp_depth_delta,
    apply_parallel_punctuation,
    apply_scoped_parallel_punctuation,
    assert_well_formed,
    han_only,
    merge_split_comm_notes,
    parse_body_segments,
    relocate_leading_comm_notes,
)

AI_PUNCT_CHARS = frozenset("。，、：；？！「」『』·《》")
PURGE_PUNCT_CHARS = AI_PUNCT_CHARS | PUNCT_CHARS
MIN_SEGMENT_HAN = 20


class SegmentInfo(TypedDict):
    id: int
    kind: str
    han: str
    han_start: int
    han_end: int
    has_punct: bool


class SegmentListResult(TypedDict):
    segments: list[SegmentInfo]
    has_any_punct: bool
    body_xml: str


class RawInsertion(TypedDict, total=False):
    afterHan: int
    mark: str
    left: str
    occurrence: int


class VerifiedInsertion(TypedDict):
    afterHan: int
    mark: str
    global_han: int


class ApplyStats(TypedDict):
    applied: int
    dropped_anchor: int
    skipped_punctuated: int
    segments_total: int


class AiParallelApplyStats(TypedDict):
    segments_total: int
    segments_applied: int
    align_failed: int
    marks_added: int
    reflowed: bool


class AiParallelApplyResult(TypedDict):
    body_xml: str
    stats: AiParallelApplyStats
    applied: bool


class ApplyResult(TypedDict):
    body_xml: str
    stats: ApplyStats
    applied: bool


def strip_ai_punct(text: str) -> str:
    return "".join(ch for ch in text if ch not in AI_PUNCT_CHARS)


def strip_all_punct(text: str) -> str:
    return "".join(ch for ch in text if ch not in PURGE_PUNCT_CHARS)


def segment_has_punct(han: str, atoms: list[str] | None = None, atom_indices: list[int] | None = None) -> bool:
    if any(ch in AI_PUNCT_CHARS for ch in han):
        return True
    if atoms is not None and atom_indices is not None:
        for idx in atom_indices:
            if idx < len(atoms) and any(ch in AI_PUNCT_CHARS for ch in atoms[idx]):
                return True
    return False


def _segment_context(
    segments: list, index: int
) -> tuple[str | None, str | None]:
    preceding: str | None = None
    following: str | None = None
    for idx in range(index - 1, -1, -1):
        if segments[idx]["kind"] == "comm":
            preceding = segments[idx]["han"]
            break
    for idx in range(index + 1, len(segments)):
        if segments[idx]["kind"] == "comm":
            following = segments[idx]["han"]
            break
    return preceding, following


def list_segments(body_xml: str) -> SegmentListResult:
    """Export basetext / commentary segments for TS prompts."""
    merged = merge_split_comm_notes(body_xml)
    atoms = _iter_xml_atoms_segmented(merged)
    raw = parse_body_segments(merged)
    segments: list[SegmentInfo] = []
    has_any = False
    cursor = 0
    for seg_id, seg in enumerate(raw):
        han = seg["han"]
        length = len(han)
        has_punct = segment_has_punct(han, atoms, seg["atom_indices"])
        has_any = has_any or has_punct
        info: SegmentInfo = {
            "id": seg_id,
            "kind": seg["kind"],
            "han": han,
            "han_start": cursor,
            "han_end": cursor + length,
            "has_punct": has_punct,
        }
        segments.append(info)
        cursor += length
    result: SegmentListResult = {
        "segments": segments,
        "has_any_punct": has_any,
        "body_xml": merged,
    }
    return result


def segment_is_adequately_punctuated(han: str, has_punct: bool) -> bool:
    """Match TS ``segmentNeedsAiGap`` — adequate marks for coverage bar green."""
    if len(han) < MIN_SEGMENT_HAN:
        return has_punct
    if not has_punct:
        return False
    han_count = len(han_only(han))
    if han_count == 0:
        return False
    punct_count = sum(1 for ch in han if ch in AI_PUNCT_CHARS)
    return (punct_count / han_count) * 100 >= MIN_PUNCT_PER_100_HAN


def coverage_from_punctuation(body_xml: str) -> Coverage:
    """1-D bar: green = adequately punctuated Han segments (parallel or AI)."""
    result = list_segments(body_xml)
    segments = result["segments"]
    if not segments:
        merged = merge_split_comm_notes(body_xml)
        atoms = _iter_xml_atoms_segmented(merged)
        tape, _ = _han_tape(atoms)
        return _empty_coverage(len(tape))

    total = segments[-1]["han_end"]
    intervals: list[tuple[int, int]] = []
    spans: list[dict[str, object]] = []
    for seg in segments:
        if not segment_is_adequately_punctuated(seg["han"], seg["has_punct"]):
            continue
        start, end = seg["han_start"], seg["han_end"]
        if end <= start:
            continue
        intervals.append((start, end))
        spans.append(
            {
                "start": start / total if total else 0.0,
                "end": end / total if total else 0.0,
                "covered_chars": end - start,
                "source": "punctuated",
                "preview": seg["han"][:40],
            }
        )
    return _coverage_from_intervals(total, intervals, spans)  # type: ignore[arg-type]


def bridge_punct_coverage(payload: dict) -> dict:
    body_xml = str(payload.get("body_xml") or "")
    if payload.get("merge_comm", True):
        body_xml = merge_split_comm_notes(body_xml)
    return {"coverage": coverage_from_punctuation(body_xml)}


def _find_left_occurrence(haystack: str, needle: str, occurrence: int) -> int | None:
    if not needle:
        return None
    start = 0
    count = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return None
        count += 1
        if count == occurrence:
            return idx + len(needle) - 1
        start = idx + 1


def verify_insertions(
    segment_han: str,
    items: list[RawInsertion],
    *,
    han_start: int = 0,
) -> tuple[list[VerifiedInsertion], int]:
    """Resolve ``left`` + ``occurrence``; compute ``afterHan`` internally."""
    verified: list[VerifiedInsertion] = []
    dropped = 0
    for item in items:
        mark = str(item.get("mark") or "")
        if mark not in AI_PUNCT_CHARS:
            dropped += 1
            continue
        left = str(item.get("left") or "").strip()
        if not left or len(left) > 3:
            dropped += 1
            continue
        if not all(HAN_RE.fullmatch(ch) for ch in left):
            dropped += 1
            continue
        occurrence = item.get("occurrence")
        if not isinstance(occurrence, int) or occurrence < 1:
            occurrence = 1
        resolved = _find_left_occurrence(segment_han, left, occurrence)
        if resolved is None:
            dropped += 1
            continue
        after_han = resolved
        verified.append(
            {
                "afterHan": after_han,
                "mark": mark,
                "global_han": han_start + after_han,
            }
        )
    return verified, dropped


def _build_insertions(
    verified_by_segment: dict[int, list[VerifiedInsertion]],
) -> dict[int, str]:
    insertions: dict[int, str] = {}
    for items in verified_by_segment.values():
        for item in items:
            key = item["global_han"]
            insertions[key] = insertions.get(key, "") + item["mark"]
    return insertions


def _apply_insertions_to_xml(body_xml: str, insertions: dict[int, str]) -> str:
    """Insert punctuation at global Han tape indices without stamps or reflow."""
    if not insertions:
        return body_xml
    atoms = _iter_xml_atoms_segmented(body_xml)
    out: list[str] = []
    han_seen = -1
    for atom_index, atom in enumerate(atoms):
        is_han = (not _is_markup(atom)) and bool(HAN_RE.fullmatch(atom))
        out.append(atom)
        if is_han:
            han_seen += 1
            extra = insertions.get(han_seen, "")
            if extra:
                out.append(extra)
    return "".join(out)


def _assert_integrity(before: str, after: str) -> None:
    if han_only(before) != han_only(after):
        raise ValueError("Han characters changed during punctuation apply")
    if strip_ai_punct(before) != strip_ai_punct(after):
        raise ValueError("Base text changed when stripping AI punctuation")


def apply_insertions(
    body_xml: str,
    verified_by_segment: dict[int, list[VerifiedInsertion]],
    *,
    segment_meta: list[SegmentInfo] | None = None,
) -> ApplyResult:
    """Apply verified insertions; fail closed on integrity violation."""
    merged = merge_split_comm_notes(body_xml)
    before = merged
    meta = segment_meta or list_segments(merged)["segments"]
    skipped = sum(1 for seg in meta if seg["has_punct"])
    insertions = _build_insertions(verified_by_segment)
    xml = _apply_insertions_to_xml(merged, insertions)
    try:
        assert_well_formed(xml)
    except ET.ParseError:
        xml = merged
        insertions = {}
    if xml != merged:
        _assert_integrity(before, xml)
    applied_count = sum(len(v) for v in verified_by_segment.values())
    stats: ApplyStats = {
        "applied": applied_count if xml != merged else 0,
        "dropped_anchor": 0,
        "skipped_punctuated": skipped,
        "segments_total": len(meta),
    }
    return {
        "body_xml": xml,
        "stats": stats,
        "applied": bool(insertions) and xml != merged,
    }


def _purge_atoms(atoms: list[str], atom_indices: set[int] | None) -> list[str]:
    out: list[str] = []
    for idx, atom in enumerate(atoms):
        if atom_indices is not None and idx not in atom_indices:
            out.append(atom)
            continue
        if _is_markup(atom):
            out.append(atom)
            continue
        cleaned = "".join(ch for ch in atom if ch not in PURGE_PUNCT_CHARS)
        if cleaned:
            out.append(cleaned)
    return out


def _purge_atoms_by_han_range(atoms: list[str], han_start: int, han_end: int) -> list[str]:
    """Strip punctuation after Han indices in ``[han_start, han_end)``."""
    if han_start >= han_end:
        return list(atoms)
    out: list[str] = []
    han_seen = -1
    purge_following = False
    for atom in atoms:
        if _is_markup(atom):
            out.append(atom)
            continue
        if HAN_RE.fullmatch(atom):
            han_seen += 1
            out.append(atom)
            purge_following = han_start <= han_seen < han_end
            continue
        if purge_following:
            cleaned = "".join(ch for ch in atom if ch not in PURGE_PUNCT_CHARS)
            if cleaned:
                out.append(cleaned)
        else:
            out.append(atom)
    return out


def purge_punctuation(
    body_xml: str,
    *,
    scope: str = "whole_juan",
    segment_ids: list[int] | None = None,
    han_start: int | None = None,
    han_end: int | None = None,
) -> str:
    """Strip punctuation marks from body XML."""
    merged = merge_split_comm_notes(body_xml)
    atoms = _iter_xml_atoms_segmented(merged)
    if scope == "han_range":
        if han_start is None or han_end is None:
            raise ValueError("han_range scope requires han_start and han_end")
        cleaned_atoms = _purge_atoms_by_han_range(atoms, han_start, han_end)
    elif scope == "segments" and segment_ids is not None:
        raw = parse_body_segments(merged)
        atom_indices: set[int] = set()
        for seg_id in segment_ids:
            if 0 <= seg_id < len(raw):
                atom_indices.update(raw[seg_id]["atom_indices"])
        cleaned_atoms = _purge_atoms(atoms, atom_indices)
    elif scope == "whole_juan":
        cleaned_atoms = _purge_atoms(atoms, None)
    else:
        raise ValueError(f"Unknown purge scope: {scope}")
    xml = "".join(cleaned_atoms)
    try:
        assert_well_formed(xml)
    except ET.ParseError:
        return merged
    return xml


def _count_punct_marks(text: str) -> int:
    return sum(text.count(ch) for ch in AI_PUNCT_CHARS)


def _basetext_paragraph_blocks(
    atoms: list[str],
) -> list[tuple[int, int, bool]]:
    """Per basetext ``<p>`` block: (last_han_index, han_count, ends_with_sentence_punct)."""
    blocks: list[tuple[int, int, bool]] = []
    in_comm = False
    in_p = False
    p_han_count = 0
    p_last_han = -1
    p_ends_sentence = False

    def flush_p() -> None:
        nonlocal p_han_count, p_last_han, p_ends_sentence
        if in_p and not in_comm and p_han_count > 0 and p_last_han >= 0:
            blocks.append((p_last_han, p_han_count, p_ends_sentence))
        p_han_count = 0
        p_last_han = -1
        p_ends_sentence = False

    han_seen = -1
    for atom in atoms:
        if NOTE_OPEN_COMM_RE.fullmatch(atom):
            in_comm = True
            continue
        if atom == "</note>":
            in_comm = False
            continue
        if _is_p_open(atom):
            flush_p()
            in_p = not in_comm
            continue
        if atom == "</p>":
            flush_p()
            in_p = False
            continue
        if in_comm or not in_p:
            continue
        is_han = (not _is_markup(atom)) and bool(HAN_RE.fullmatch(atom))
        if is_han:
            han_seen += 1
            p_last_han = han_seen
            p_han_count += 1
            p_ends_sentence = False
            continue
        if not _is_markup(atom):
            for ch in atom:
                if ch in SENTENCE_END_PUNCT:
                    p_ends_sentence = True
    return blocks


def _collect_kanripo_geometry_para_after(atoms: list[str]) -> set[int]:
    """Long Kanripo line wrap + short completing line ending in 。！？ → keep paragraph break."""
    blocks = _basetext_paragraph_blocks(atoms)
    if len(blocks) < 2:
        return set()
    lengths = sorted(block[1] for block in blocks)
    long_threshold = lengths[min(len(lengths) - 1, int(len(lengths) * 0.9))]
    short_threshold = max(int(long_threshold * 0.55), 12)
    para_after: set[int] = set()
    for index in range(len(blocks) - 1):
        _, len_long, _ = blocks[index]
        last_han_short, len_short, ends_short = blocks[index + 1]
        if len_long >= long_threshold and len_short <= short_threshold and ends_short:
            para_after.add(last_han_short)
    return para_after


def _collect_sentence_para_after(atoms: list[str]) -> set[int]:
    """Han indices after which basetext sentence-end punctuation appears."""
    para_after: set[int] = set()
    han_seen = -1
    in_comm = False
    for atom in atoms:
        if NOTE_OPEN_COMM_RE.fullmatch(atom):
            in_comm = True
            continue
        if atom == "</note>":
            in_comm = False
            continue
        is_han = (not _is_markup(atom)) and bool(HAN_RE.fullmatch(atom))
        if is_han:
            han_seen += 1
            continue
        if in_comm or han_seen < 0:
            continue
        for ch in atom:
            if ch in SENTENCE_END_PUNCT:
                para_after.add(han_seen)
                break
    para_after |= _collect_kanripo_geometry_para_after(atoms)
    return para_after


def reflow_paragraphs(body_xml: str) -> str:
    """Split basetext ``<p>`` at sentence ends; skip inside comm notes."""
    merged = merge_split_comm_notes(body_xml)
    atoms = _iter_xml_atoms_segmented(merged)
    tape, _ = _han_tape(atoms)
    if not tape:
        return merged
    para_after = _collect_sentence_para_after(atoms)
    if not para_after:
        return merged
    reflow_start = 0
    reflow_end = len(tape)
    out: list[str] = []
    han_seen = -1
    skip_until = -1
    in_comm_note = False
    stamp_depth = 0
    other_seg_depth = 0

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
        if NOTE_OPEN_COMM_RE.fullmatch(atom):
            in_comm_note = True
        elif atom == "</note>":
            in_comm_note = False
        is_han = (not _is_markup(atom)) and bool(HAN_RE.fullmatch(atom))
        stamp_depth, other_seg_depth = _stamp_depth_delta(atom, stamp_depth, other_seg_depth)
        out.append(atom)
        if is_han:
            han_seen += 1
            if (
                han_seen in para_after
                and not in_comm_note
                and not _comm_note_follows(atoms, atom_index)
            ):
                out.append("</p><p>")
                skip_until = max(skip_until, _skip_natural_break_after_split(atoms, atom_index))
    xml = relocate_leading_comm_notes("".join(out))
    try:
        assert_well_formed(xml)
    except ET.ParseError:
        return merged
    if han_only(merged) != han_only(xml):
        return merged
    return xml


def bridge_list_segments(payload: dict) -> dict:
    body_xml = str(payload.get("body_xml") or "")
    result = list_segments(body_xml)
    segments_out = []
    merged = result["body_xml"]
    raw = parse_body_segments(merged)
    for seg in result["segments"]:
        preceding, following = _segment_context(raw, seg["id"])
        entry = dict(seg)
        if preceding:
            entry["preceding_comm"] = preceding
        if following:
            entry["following_comm"] = following
        segments_out.append(entry)
    return {
        "segments": segments_out,
        "has_any_punct": result["has_any_punct"],
        "body_xml": merged,
    }


def bridge_apply(payload: dict) -> dict:
    body_xml = str(payload.get("body_xml") or "")
    verified_raw = payload.get("verified_by_segment")
    if not isinstance(verified_raw, dict):
        verified_raw = {}
    verified: dict[int, list[VerifiedInsertion]] = {}
    for key, items in verified_raw.items():
        seg_id = int(key)
        if not isinstance(items, list):
            continue
        verified[seg_id] = [item for item in items if isinstance(item, dict)]
    meta_raw = payload.get("segment_meta")
    meta = meta_raw if isinstance(meta_raw, list) else None
    result = apply_insertions(body_xml, verified, segment_meta=meta)
    return result


def bridge_purge(payload: dict) -> dict:
    body_xml = str(payload.get("body_xml") or "")
    scope = str(payload.get("scope") or "whole_juan")
    segment_ids_raw = payload.get("segment_ids")
    segment_ids = (
        [int(item) for item in segment_ids_raw]
        if isinstance(segment_ids_raw, list)
        else None
    )
    han_start = payload.get("han_start")
    han_end = payload.get("han_end")
    if isinstance(han_start, int) and isinstance(han_end, int):
        scope = "han_range"
    return {
        "body_xml": purge_punctuation(
            body_xml,
            scope=scope,
            segment_ids=segment_ids,
            han_start=han_start if isinstance(han_start, int) else None,
            han_end=han_end if isinstance(han_end, int) else None,
        )
    }


def apply_ai_parallel_segments(
    body_xml: str,
    segment_parallels: list[dict[str, str]],
    *,
    reflow: bool = True,
) -> AiParallelApplyResult:
    """Apply LLM-punctuated plain text per segment via parallel tape transfer."""
    xml = merge_split_comm_notes(body_xml)
    marks_before = _count_punct_marks(xml)
    segments_total = len(segment_parallels)
    segments_applied = 0
    align_failed = 0

    for item in segment_parallels:
        parallel_text = str(item.get("parallel_text") or "").strip()
        if not parallel_text:
            align_failed += 1
            continue
        han_start = item.get("han_start")
        han_end = item.get("han_end")
        if isinstance(han_start, int) and isinstance(han_end, int):
            result = apply_scoped_parallel_punctuation(xml, parallel_text, han_start, han_end)
            if not result.get("applied"):
                # Scoped range can disagree with model output; retry global infix search.
                result = apply_parallel_punctuation(xml, parallel_text)
        else:
            result = apply_parallel_punctuation(xml, parallel_text)
        if result.get("applied"):
            xml = result["body_xml"]
            segments_applied += 1
        else:
            align_failed += 1

    reflowed = False
    if reflow and segments_applied > 0:
        reflowed_xml = reflow_paragraphs(xml)
        if reflowed_xml != xml:
            reflowed = True
        xml = reflowed_xml

    marks_after = _count_punct_marks(xml)
    stats: AiParallelApplyStats = {
        "segments_total": segments_total,
        "segments_applied": segments_applied,
        "align_failed": align_failed,
        "marks_added": max(0, marks_after - marks_before),
        "reflowed": reflowed,
    }
    return {
        "body_xml": xml,
        "stats": stats,
        "applied": segments_applied > 0,
    }


def _coerce_han_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def bridge_ai_parallel_apply(payload: dict) -> dict:
    body_xml = str(payload.get("body_xml") or "")
    parallels_raw = payload.get("segment_parallels")
    if not isinstance(parallels_raw, list):
        parallels_raw = []
    segment_parallels = []
    for item in parallels_raw:
        if not isinstance(item, dict):
            continue
        entry: dict[str, object] = {
            "parallel_text": str(item.get("parallel_text") or ""),
        }
        han_start = _coerce_han_index(item.get("han_start"))
        han_end = _coerce_han_index(item.get("han_end"))
        if han_start is not None and han_end is not None:
            entry["han_start"] = han_start
            entry["han_end"] = han_end
        segment_parallels.append(entry)
    reflow = payload.get("reflow", True) is not False
    return apply_ai_parallel_segments(body_xml, segment_parallels, reflow=reflow)


def bridge_reflow(payload: dict) -> dict:
    body_xml = str(payload.get("body_xml") or "")
    return {"body_xml": reflow_paragraphs(body_xml)}
