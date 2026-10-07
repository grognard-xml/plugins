"""Convert a Kanripo Mandoku ``.txt`` juan to a TEI body (self-contained plugin path)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from kanripo_import.commentary import extract_commentary_from_text
from kanripo_import.edition import resolve_edition
from kanripo_import.kanripo_gaiji import (
    clean_gaiji_overrides,
    copy_gaiji_assets,
    gaiji_graphic_xml,
    resolve_kanripo_refs,
)
from kanripo_import.kanripo_io import extract_kanripo_metadata, load_kanripo_text
from kanripo_import.metadata_xml import build_metadata_xml, work_metadata_to_dict
from kanripo_import.normalize_tables import Normalizer
from kanripo_import.work_metadata import lookup_work_metadata

NormalizeMode = Literal["off", "dpm"]

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


# --- Siku quanshu (WYG) title block --------------------------------------------------
#
# These editions open every juan with a fixed block that is paratext, not the work's own
# text, and mark it by indentation (a leading U+3000) rather than the ``**`` the importer
# otherwise understands:
#
#     欽定四庫全書            imprimatur formula      -> <head type="imprimatur">
#     　山海經卷二            title + juan number     -> <head type="title">
#     　　　　晉　郭璞　撰    attribution             -> <byline>
#     　　西山經              the work's own section  -> <head>
#     ...
#     　山海經卷二            colophon repeating the title -> <trailer>
#
# Left as ``<p>``, the AI punctuation step joins them to the first body sentence.

_IMPRIMATUR = "欽定四庫全書"
_TITLE_LINE_RE = re.compile(r"^.{1,30}[卷巻][〇零一二三四五六七八九十百廿卅\d]+$")
_BYLINE_RE = re.compile(r"^.{0,16}[撰著譯注校輯編]$")
_BLOCK_LINE_MAX = 20
_INDENT_CHARS = "　"


def _compact_line(raw_line: str) -> str:
    """Line content with page-break tags, pilcrow and every kind of whitespace removed."""
    text = _PB_TAG_RE.sub("", raw_line).replace("¶", "").replace("巻", "卷")
    return "".join(ch for ch in text if not ch.isspace())


def _is_indented(raw_line: str) -> bool:
    return _PB_TAG_RE.sub("", raw_line).lstrip(" \t").startswith(_INDENT_CHARS)


def _title_block_roles(lines: list[str]) -> dict[int, str]:
    """Map line index -> role (imprimatur, title, byline, head, trailer) for a WYG title block."""
    roles: dict[int, str] = {}
    title = ""
    block_open = True
    seen_content = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "" or _PB_LINE_RE.match(stripped):
            continue
        compact = _compact_line(stripped)
        if not block_open:
            break
        if not compact:
            continue
        if not seen_content and compact == _IMPRIMATUR:
            roles[index] = "imprimatur"
            seen_content = True
            continue
        seen_content = True
        plain = not any(ch in compact for ch in "()[]*")
        if not (_is_indented(line) and plain and len(compact) <= _BLOCK_LINE_MAX):
            block_open = False
            continue
        if "title" not in roles.values() and _TITLE_LINE_RE.match(compact):
            roles[index] = "title"
            title = compact
        elif "byline" not in roles.values() and _BYLINE_RE.match(compact):
            roles[index] = "byline"
        elif "title" in roles.values():
            roles[index] = "head"
        else:
            block_open = False
    if title:
        opening_end = max(roles) if roles else -1
        for index, line in enumerate(lines):
            if index <= opening_end or index in roles:
                continue
            if _is_indented(line) and _compact_line(line) == title:
                roles[index] = "trailer"
    return roles


_ROLE_TAGS = {
    "imprimatur": ('<head type="imprimatur">', "</head>"),
    "title": ('<head type="title">', "</head>"),
    "byline": ("<byline>", "</byline>"),
    "head": ("<head>", "</head>"),
    "trailer": ("<trailer>", "</trailer>"),
}


def body_to_tei_div(body: str) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    lines = body.splitlines()
    roles = _title_block_roles(lines)

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

    for line_index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "":
            continue
        pb_line = _PB_LINE_RE.match(stripped)
        if pb_line:
            current.append(f"<pb:{pb_line.group(1)}>")
            continue
        ends = stripped.endswith("¶")
        piece = stripped[:-1].rstrip() if ends else stripped
        role = roles.get(line_index)
        if role:
            if current and not all(part.startswith("<pb:") for part in current):
                flush_current()
            opening, closing = _ROLE_TAGS[role]
            paragraphs.append(f"{opening}{_inline_to_xml(''.join(current) + piece)}{closing}")
            current.clear()
            continue
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
    gaiji_overrides: dict[str, str] | None = None,
) -> dict:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    header = parse_mandoku_header(raw)
    pb_meta = extract_kanripo_metadata(path)

    kanripo_id = header["kanripo_id"] or (pb_meta.kanripo_id if pb_meta else "")
    juan = header["juan"] or (str(pb_meta.juan) if pb_meta else "")
    title = header["title"] or kanripo_id or path.stem

    body, gaiji_ids = resolve_kanripo_refs(
        load_kanripo_text(path), overrides=clean_gaiji_overrides(gaiji_overrides)
    )
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
