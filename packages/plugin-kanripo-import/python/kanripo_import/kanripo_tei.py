"""Convert a Kanripo Mandoku ``.txt`` juan to a TEI body (self-contained plugin path)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from kanripo_import.commentary import extract_commentary_from_text
from kanripo_import.edition import resolve_edition
from kanripo_import.kanripo_gaiji import copy_gaiji_assets, gaiji_graphic_xml, resolve_kanripo_refs
from kanripo_import.kanripo_io import extract_kanripo_metadata, load_kanripo_text
from kanripo_import.metadata_xml import build_metadata_xml, work_metadata_to_dict
from kanripo_import.normalize_tables import Normalizer, apply_hard_replacements
from kanripo_import.work_metadata import lookup_work_metadata

NormalizeMode = Literal["off", "dpm", "hard_replacements"]

_PB_TAG_RE = re.compile(r"<pb:([^>]+)>")
_PB_LINE_RE = re.compile(r"^\s*<pb:([^>]+)>\s*(¶)?\s*$")
_JOIN_NOTE_RE = re.compile(
    r"\)[ \t]*¶?[ \t]*\n(?:[ \t]*<pb:([^>\n]+)>[ \t]*¶?[ \t]*\n)?[ \t]*\("
)
_GAIJI_BRACKET_RE = re.compile(r"\[[^\]\n]*\]")
_GAIJI_INLINE_RE = re.compile(r"<gaiji:(KR\d{4})/>")
_PROPERTY_RE = re.compile(r"^#\+PROPERTY:\s+(\S+)\s+(.*)$", re.IGNORECASE)
_TITLE_RE = re.compile(r"^#\+TITLE:\s*(.*)$", re.IGNORECASE)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _protect_parens_inside_gaiji(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        return match.group(0).replace("(", "（").replace(")", "）")

    return _GAIJI_BRACKET_RE.sub(_repl, text)


def parse_mandoku_header(raw: str) -> dict[str, str]:
    title = kanripo_id = juan = source = dzid = ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "":
            continue
        if not stripped.startswith("#"):
            break
        title_match = _TITLE_RE.match(stripped)
        if title_match:
            title = title_match.group(1).strip()
            continue
        prop_match = _PROPERTY_RE.match(stripped)
        if not prop_match:
            continue
        key = prop_match.group(1).rstrip(":").upper()
        value = prop_match.group(2).strip()
        if key in {"ID", "KRID", "KANRIPO_ID"}:
            kanripo_id = value
        elif key == "JUAN":
            juan = value
        elif key == "SOURCE":
            source = value
        elif key == "DZID":
            dzid = value
    return {
        "title": title,
        "kanripo_id": kanripo_id,
        "juan": juan,
        "source": source,
        "dzid": dzid,
    }


def merge_continued_commentary(text: str) -> str:
    protected = _protect_parens_inside_gaiji(text)
    previous = None
    while previous != protected:
        previous = protected
        protected = _JOIN_NOTE_RE.sub(
            lambda match: f"<pb:{match.group(1)}>" if match.group(1) else "",
            protected,
        )
    return protected


def _apply_normalize_outside_pb(text: str, mode: NormalizeMode) -> str:
    if mode == "off":
        return text
    if mode == "dpm":
        mapper = Normalizer.from_package_data().normalize_text
    elif mode == "hard_replacements":
        mapper = apply_hard_replacements
    else:
        raise ValueError(f"Unknown normalize mode: {mode}")

    parts = re.split(r"(<pb:[^>]+>)", text)
    return "".join(part if part.startswith("<pb:") else mapper(part) for part in parts)


def _inline_to_xml(text: str) -> str:
    out: list[str] = []
    buf: list[str] = []
    in_note = False
    square = 0
    index = 0
    length = len(text)

    def flush() -> None:
        if buf:
            out.append(_xml_escape("".join(buf)))
            buf.clear()

    while index < length:
        gaiji_match = _GAIJI_INLINE_RE.match(text, index)
        if gaiji_match:
            flush()
            out.append(gaiji_graphic_xml(gaiji_match.group(1)))
            index = gaiji_match.end()
            continue
        if text.startswith("<pb:", index):
            end = text.find(">", index)
            if end != -1:
                flush()
                out.append(f'<pb n="{_xml_escape(text[index + 4 : end])}"/>')
                index = end + 1
                continue
        ch = text[index]
        if ch == "[":
            square += 1
            buf.append(ch)
            index += 1
            continue
        if ch == "]" and square:
            square -= 1
            buf.append(ch)
            index += 1
            continue
        if square == 0 and ch == "(" and not in_note:
            flush()
            out.append('<note type="comm">')
            in_note = True
            index += 1
            continue
        if square == 0 and ch == ")" and in_note:
            flush()
            out.append("</note>")
            in_note = False
            index += 1
            continue
        if ch == "¶" and in_note:
            index += 1
            continue
        if ch == "/" and in_note:
            index += 1
            continue
        buf.append(ch)
        index += 1
    flush()
    if in_note:
        raise ValueError("Unclosed '(' in Kanripo commentary")
    return "".join(out)


def _is_heading_blob(blob: str) -> bool:
    stripped = _PB_TAG_RE.sub("", blob).strip()
    return stripped.startswith("**")


def body_to_tei_div(body: str) -> str:
    paragraphs: list[str] = []
    current: list[str] = []

    def flush_current() -> None:
        if not current:
            return
        blob = "".join(current)
        current.clear()
        if not blob.strip() and "<pb:" not in blob:
            return
        if _is_heading_blob(blob):
            inner = _inline_to_xml(blob.replace("**", ""))
            paragraphs.append(f"<head>{inner}</head>")
        else:
            paragraphs.append(f"<p>{_inline_to_xml(blob)}</p>")

    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "":
            continue
        pb_line = _PB_LINE_RE.match(stripped)
        if pb_line:
            current.append(f"<pb:{pb_line.group(1)}>")
            continue
        ends = stripped.endswith("¶")
        piece = stripped[:-1].rstrip() if ends else stripped
        if _is_heading_blob(piece):
            if current and not all(part.startswith("<pb:") for part in current):
                flush_current()
            current.append(piece)
            flush_current()
            continue
        current.append(piece)
        if ends:
            flush_current()

    flush_current()
    inner = "\n".join(paragraphs)
    return f'<div type="juan">\n{inner}\n</div>'


def convert_kanripo_txt(
    path: Path,
    *,
    normalize: NormalizeMode = "off",
    gaiji_dest_dir: Path | None = None,
) -> dict:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    header = parse_mandoku_header(raw)
    pb_meta = extract_kanripo_metadata(path)

    kanripo_id = header["kanripo_id"] or (pb_meta.kanripo_id if pb_meta else "")
    juan = header["juan"] or (str(pb_meta.juan) if pb_meta else "")
    title = header["title"] or kanripo_id or path.stem

    body, gaiji_ids = resolve_kanripo_refs(load_kanripo_text(path))
    body = _apply_normalize_outside_pb(body, normalize)
    body = merge_continued_commentary(body)
    extract_commentary_from_text(body)

    copied_gaiji: list[str] = []
    if gaiji_dest_dir is not None and gaiji_ids:
        copied_gaiji = copy_gaiji_assets(gaiji_ids, Path(gaiji_dest_dir))

    body_xml = body_to_tei_div(body)

    meta = {
        "title": title,
        "kanripo_id": kanripo_id,
        "juan": str(juan),
        "source": header["source"],
        "dzid": header["dzid"],
        "normalize": normalize,
        "stem": path.stem,
        "gaiji_ids": gaiji_ids,
        "gaiji_copied": copied_gaiji,
    }

    work = lookup_work_metadata(kanripo_id)
    entities = None
    metadata_xml = ""
    if work:
        edition_profile = work.edition_profile
        edition_label = work.edition_label
        edition_date = work.edition_date
        source_locator = work.source_locator
        if not edition_label:
            fallback = resolve_edition(source=work.source, witness_code=header["source"])
            edition_profile = fallback.edition_profile
            edition_label = fallback.edition_label
            edition_date = fallback.edition_date
            if not source_locator:
                source_locator = fallback.source_locator
        meta.update(
            {
                "title": work.title or meta["title"],
                "vols": work.vols,
                "juan_count": work.juan_count,
                "catalog_source": work.source,
                "edition_profile": edition_profile,
                "edition_label": edition_label,
                "edition_date": edition_date,
                "source_locator": source_locator,
                "cbeta_id": work.cbeta_id,
                "dzid": work.dzid or meta["dzid"],
                "time_dynasty": work.time_dynasty,
                "date_not_before": work.date_not_before,
                "date_not_after": work.date_not_after,
                "author_dates": work.author_dates,
            }
        )
        entities = work_metadata_to_dict(work)
        meta["authorship"] = entities.get("authorship", [])
        if work.wikidata:
            meta.update(
                {
                    "work_qid": work.wikidata.wikidata_work_qid,
                    "edition_qid": work.wikidata.edition_qid,
                    "ws_page": work.wikidata.ws_page,
                    "ws_url": work.wikidata.ws_url,
                    "wikidata_primary_name": work.wikidata.primary_name,
                    "wikidata_aliases": list(work.wikidata.aliases),
                }
            )
        metadata_xml = build_metadata_xml(work, juan=str(juan))

    return {
        "meta": meta,
        "body_xml": body_xml,
        "entities": entities,
        "metadata_xml": metadata_xml,
    }
