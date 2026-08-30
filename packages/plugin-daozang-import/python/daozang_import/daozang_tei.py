"""Convert a cached UTF-8 Daozang text file to TEI body div(s), splitting on juan boundaries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from daozang_import.constants import SIMP_MARKERS, TRAD_MARKERS
from daozang_import.corpus_index import parse_dz_no, title_from_filename
from daozang_import.encoding import decode_legacy_text
from daozang_import.metadata_xml import build_metadata_xml, work_metadata_to_dict
from daozang_import.work_metadata import lookup_work_metadata

_XML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})
_SENTENCE_PUNCT = re.compile(r"[。；！？，、]")
_MAX_JUAN_LINE = 120
_CN_NUM = r"[一二三四五六七八九十百零〇两兩]+"

_BARE_JUAN_START = re.compile(rf"^卷({_CN_NUM}|[0-9]+|[上中下])\s*$")
_JUAN_END = re.compile(r"卷.*[竟訖尽盡]\s*$")

_JUAN_START_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"^(.{{0,80}})卷([上中下])\s*$"),
    re.compile(rf"^(.{{0,80}})卷之({_CN_NUM})\s*$"),
    re.compile(rf"^(.{{0,80}})卷第({_CN_NUM})(?:之([上中下]))?\s*$"),
    re.compile(rf"^(.{{0,80}})第({_CN_NUM})卷\s*(.*)?$"),
    re.compile(rf"^(.{{0,80}})卷({_CN_NUM})([上中下])\s*$"),
    _BARE_JUAN_START,
)

_JUAN_LABEL = re.compile(
    rf"卷(?:之({_CN_NUM})|第({_CN_NUM})(?:之([上中下]))?|({_CN_NUM})([上中下])|([上中下])|[0-9]+)$"
)


class JuanFile(TypedDict):
    juan_n: str
    juan_title: str
    subtitle: str
    body_xml: str


def variant_from_relpath(rel_path: str) -> str:
    """Traditional vs simplified tree, recorded in the TEI source note."""
    lowered = rel_path.lower()
    for marker in TRAD_MARKERS:
        if marker.lower() in lowered:
            return "trad"
    for marker in SIMP_MARKERS:
        if marker.lower() in lowered:
            return "simp"
    return "trad"


def _xml_escape(text: str) -> str:
    return text.translate(_XML_ESCAPE)


def _is_juan_end(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_JUAN_LINE:
        return False
    if _SENTENCE_PUNCT.search(stripped):
        return False
    return bool(_JUAN_END.search(stripped))


def _is_juan_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_JUAN_LINE:
        return False
    if _SENTENCE_PUNCT.search(stripped):
        return False
    return any(pattern.match(stripped) for pattern in _JUAN_START_PATTERNS)


def _is_bare_juan_start(line: str) -> bool:
    return bool(_BARE_JUAN_START.match(line.strip()))


def _juan_label_from_title(title: str) -> str:
    match = _JUAN_LABEL.search(title.strip())
    if not match:
        bare = _BARE_JUAN_START.match(title.strip())
        if bare:
            return bare.group(1)
        return title.strip()[-8:] or "1"
    if match.group(1):
        return f"之{match.group(1)}"
    if match.group(2):
        part = match.group(3)
        return f"第{match.group(2)}{part or ''}"
    if match.group(4):
        suffix = match.group(5) or ""
        return f"{match.group(4)}{suffix}"
    if match.group(6):
        return match.group(6)
    return title.strip()[-8:] or "1"


def _collect_juan_start_indices(lines: list[str]) -> list[tuple[int, str]]:
    stripped = [line.strip() for line in lines]
    candidates = [(index, text) for index, text in enumerate(stripped) if text and _is_juan_start(text)]
    if not candidates:
        return []

    has_full_title = any(not _is_bare_juan_start(title) for _, title in candidates)
    if has_full_title:
        candidates = [(index, text) for index, text in candidates if not _is_bare_juan_start(text)]

    filtered: list[tuple[int, str]] = []
    for index, title in candidates:
        if filtered and index - filtered[-1][0] < 5:
            previous_index, previous_title = filtered[-1]
            if len(title) > len(previous_title):
                filtered[-1] = (index, title)
            continue
        if filtered and _juan_label_from_title(title) == _juan_label_from_title(filtered[-1][1]):
            continue
        filtered.append((index, title))
    return filtered


def _collect_juan_end_indices(lines: list[str]) -> list[int]:
    return [index for index, line in enumerate(lines) if _is_juan_end(line.strip())]


def _subtitle_after(lines: list[str], start_index: int) -> str:
    if start_index + 1 >= len(lines):
        return ""
    nxt = lines[start_index + 1].strip()
    if not nxt or _is_juan_start(nxt) or _is_juan_end(nxt):
        return ""
    if len(nxt) > 40 or _SENTENCE_PUNCT.search(nxt):
        return ""
    return nxt


def _join_paragraph_lines(chunk_lines: list[str]) -> str:
    if all(len(line) <= 2 for line in chunk_lines):
        return "".join(chunk_lines)
    return "\n".join(chunk_lines)


def _paragraphs_from_text(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    chunks = re.split(r"\n\s*\n+", normalized)
    paragraphs: list[str] = []
    for chunk in chunks:
        chunk_lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if not chunk_lines:
            continue
        paragraphs.append(_join_paragraph_lines(chunk_lines))
    return paragraphs or [normalized]


def _paragraphs_from_line_range(lines: list[str], start: int, end: int) -> list[str]:
    paragraphs: list[str] = []
    chunk: list[str] = []
    for line in lines[start:end]:
        stripped = line.strip()
        if not stripped:
            if chunk:
                paragraphs.append(_join_paragraph_lines(chunk))
                chunk = []
            continue
        chunk.append(stripped)
    if chunk:
        paragraphs.append(_join_paragraph_lines(chunk))
    return paragraphs


def _build_juan_div(*, juan_n: str, heads: list[str], paragraphs: list[str]) -> str:
    parts = [f'<div type="juan" n="{_xml_escape(juan_n)}">']
    for head in heads:
        if head.strip():
            parts.append(f"  <head>{_xml_escape(head.strip())}</head>")
    for paragraph in paragraphs:
        parts.append(f"  <p>{_xml_escape(paragraph)}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def _build_text_div(*, dz_no: str | None, stem: str, title: str, paragraphs: list[str]) -> str:
    parts = [
        f'<div type="text" n="{_xml_escape(dz_no or stem)}">',
        f"  <head>{_xml_escape(title)}</head>",
    ]
    for paragraph in paragraphs:
        parts.append(f"  <p>{_xml_escape(paragraph)}</p>")
    parts.append("</div>")
    return "\n".join(parts)


def _split_juan_segments(lines: list[str]) -> list[tuple[str, str, str, int, int]]:
    """Return (juan_n, juan_title, subtitle, body_start, body_end) for each juan."""
    starts = _collect_juan_start_indices(lines)
    if len(starts) >= 2:
        segments: list[tuple[str, str, str, int, int]] = []
        for index, (start_index, juan_title) in enumerate(starts):
            subtitle = _subtitle_after(lines, start_index)
            body_start = start_index + 1 + (1 if subtitle else 0)
            body_end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
            segments.append(
                (
                    _juan_label_from_title(juan_title),
                    juan_title,
                    subtitle,
                    body_start,
                    body_end,
                )
            )
        return segments

    ends = _collect_juan_end_indices(lines)
    if len(ends) >= 2 and not starts:
        segments = []
        cursor = 0
        for end_index in ends:
            end_line = lines[end_index].strip()
            segments.append(
                (
                    _juan_label_from_title(end_line),
                    end_line,
                    "",
                    cursor,
                    end_index + 1,
                )
            )
            cursor = end_index + 1
        if cursor < len(lines):
            tail = lines[cursor].strip()
            segments.append((_juan_label_from_title(tail or "续"), tail, "", cursor, len(lines)))
        return segments

    return []


def convert_daozang_txt(path: Path, *, rel_path: str = "") -> dict[str, object]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Daozang text not found: {path}")

    rel = rel_path or path.name
    stem = path.stem
    dz_no = parse_dz_no(stem)
    title = title_from_filename(stem, dz_no)
    variant = variant_from_relpath(rel)
    text = decode_legacy_text(path.read_bytes())
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    meta = {
        "title": title,
        "dz_no": dz_no,
        "variant": variant,
        "rel_path": rel,
        "stem": stem,
        "source": "方瞳子源 Fang Tongzi transcription (homeinmists.com)",
    }

    work = lookup_work_metadata(rel)
    if work:
        meta.update(
            {
                "dzid": work.dzid,
                "dz_no": work.dz_no or meta["dz_no"],
                "title": work.title or meta["title"],
                "vols": work.vols,
                "kr_id": work.kr_id,
                "krp_title": work.krp_title,
                "edition": work.edition,
                "variant_class": work.variant_class,
                "time_dynasty": work.time_dynasty,
                "date_not_before": work.date_not_before,
                "date_not_after": work.date_not_after,
                "author_dates": work.author_dates,
            }
        )
        if work.wikidata:
            wd = work.wikidata
            meta.update(
                {
                    "work_qid": wd.work_qid,
                    "edition_qid": wd.edition_qid,
                    "ws_page": wd.ws_page,
                    "ws_url": wd.ws_url,
                    "match_tier": wd.match_tier,
                }
            )
        entities = work_metadata_to_dict(work)
        metadata_xml = build_metadata_xml(work)
        meta["authorship"] = entities.get("authorship", [])
    else:
        entities = None
        metadata_xml = ""

    segments = _split_juan_segments(lines)
    if len(segments) >= 2:
        juan_files: list[JuanFile] = []
        for juan_n, juan_title, subtitle, body_start, body_end in segments:
            heads = [juan_title]
            if subtitle:
                heads.append(subtitle)
            paragraphs = _paragraphs_from_line_range(lines, body_start, body_end)
            if not paragraphs:
                continue
            juan_files.append(
                {
                    "juan_n": juan_n,
                    "juan_title": juan_title,
                    "subtitle": subtitle,
                    "body_xml": _build_juan_div(juan_n=juan_n, heads=heads, paragraphs=paragraphs),
                }
            )
        if len(juan_files) >= 2:
            return {
                "body_xml": juan_files[0]["body_xml"],
                "juan_files": juan_files,
                "split": True,
                "meta": meta,
                "entities": entities,
                "metadata_xml": metadata_xml,
            }

    paragraphs = _paragraphs_from_text(normalized)
    body_xml = _build_text_div(dz_no=dz_no, stem=stem, title=title, paragraphs=paragraphs)
    return {
        "body_xml": body_xml,
        "split": False,
        "meta": meta,
        "entities": entities,
        "metadata_xml": metadata_xml,
    }
