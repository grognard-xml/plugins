"""Build and search the local UTF-8 corpus index.

The index carries the bundled work metadata (DZ section, number, title, dynasty,
authorship) so that the desktop search does not have to join anything at runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from daozang_import.work_metadata import WorkMetadata, lookup_work_metadata

_DZ_RE = re.compile(r"(?:^|[^0-9])(DZ|dz)?(\d{1,4})(?:[^0-9]|$)")
_TITLE_FROM_NAME_RE = re.compile(
    r"^(?:DZ|dz)?\d{1,4}[\s._\-—–]*(.+?)(?:\.txt)?$",
    re.UNICODE,
)

# Front-matter catalogues of the canon, not works in it.
CATALOGUE_DIR = "目錄"


@dataclass(frozen=True)
class CorpusEntry:
    id: str
    dz_no: str
    title: str
    section: str
    dynasty: str
    authors: str
    file_title: str
    rel_path: str
    bytes: int


def parse_dz_no(stem: str) -> str:
    match = _DZ_RE.search(stem)
    if not match:
        return ""
    return match.group(2).lstrip("0") or "0"


def title_from_filename(stem: str, dz_no: str) -> str:
    cleaned = stem.strip()
    if dz_no:
        cleaned = re.sub(rf"^(?:DZ|dz)?0*{re.escape(dz_no)}\s*[\._\-—–]*", "", cleaned)
    match = _TITLE_FROM_NAME_RE.match(stem)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return cleaned or stem


def entry_id(dz_no: str, rel_path: str) -> str:
    """Stable, unique id for index rows (Chinese filenames have no ASCII slug)."""
    dz = (dz_no or "0").zfill(4)
    digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:12]
    return f"dz{dz}-{digest}"


def format_authors(work: WorkMetadata) -> str:
    parts = []
    for record in work.authorship:
        name = record.person_name
        if not name:
            continue
        parts.append(f"{name}（{record.function}）" if record.function else name)
    return "、".join(parts)


def dynasty_of(work: WorkMetadata) -> str:
    if work.time_dynasty:
        return work.time_dynasty
    for record in work.authorship:
        if record.time_dynasty:
            return record.time_dynasty
    return ""


def parse_filename(rel_path: str) -> tuple[str, str, str, str]:
    """Filenames read 〈section〉-〈title〉[-〈dynasty〉-〈author〉].txt; the fallback for
    the handful of files the metadata does not cover."""
    stem = rel_path.replace("\\", "/").split("/")[-1]
    if stem.lower().endswith(".txt"):
        stem = stem[: -len(".txt")]
    parts = [part for part in stem.split("-") if part]
    if len(parts) < 2:
        return "", stem, "", ""
    section, rest = parts[0], parts[1:]
    dynasty = authors = ""
    if len(rest) >= 3 and len(rest[-2]) <= 3:
        authors = rest.pop()
        dynasty = rest.pop()
    return section, "-".join(rest), dynasty, authors


def is_catalogue(rel_path: str) -> bool:
    return rel_path.replace("\\", "/").split("/")[0] == CATALOGUE_DIR


def _entry_for(path: Path, rel_path: str) -> CorpusEntry:
    file_section, file_title, file_dynasty, file_authors = parse_filename(rel_path)
    work = lookup_work_metadata(rel_path)
    if work:
        title = work.title or file_title
        return CorpusEntry(
            id=entry_id(work.dz_no, rel_path),
            dz_no=work.dz_no or parse_dz_no(path.stem),
            title=title,
            section=work.edition,
            dynasty=dynasty_of(work),
            authors=format_authors(work),
            file_title=file_title if file_title and file_title != title else "",
            rel_path=rel_path,
            bytes=path.stat().st_size,
        )
    dz_no = parse_dz_no(path.stem)
    return CorpusEntry(
        id=entry_id(dz_no, rel_path),
        dz_no=dz_no,
        title=file_title or title_from_filename(path.stem, dz_no),
        section=file_section,
        dynasty=file_dynasty,
        authors=file_authors,
        file_title="",
        rel_path=rel_path,
        bytes=path.stat().st_size,
    )


def build_index(utf8_root: Path) -> list[CorpusEntry]:
    entries: list[CorpusEntry] = []
    if not utf8_root.is_dir():
        return entries
    for path in sorted(utf8_root.rglob("*.txt")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(utf8_root).as_posix()
        if is_catalogue(rel_path):
            continue
        entries.append(_entry_for(path, rel_path))

    # A few DZ numbers cover several files (早/午/晚朝 and the like); only those keep the
    # filed title alongside the canonical one.
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.dz_no] = counts.get(entry.dz_no, 0) + 1
    shared = {dz for dz, count in counts.items() if dz and count > 1}
    entries = [
        entry if entry.dz_no in shared else CorpusEntry(**{**asdict(entry), "file_title": ""})
        for entry in entries
    ]

    entries.sort(key=lambda item: (item.dz_no.zfill(5) if item.dz_no else "99999", item.title))
    return entries


def write_index(utf8_root: Path, index_path: Path) -> list[CorpusEntry]:
    entries = build_index(utf8_root)
    payload = [asdict(entry) for entry in entries]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entries


def load_index(index_path: Path) -> list[CorpusEntry]:
    if not index_path.is_file():
        return []
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    return [CorpusEntry(**item) for item in raw]


def search_index(entries: list[CorpusEntry], query: str, limit: int = 40) -> list[CorpusEntry]:
    q = query.strip()
    if not q:
        return entries[: min(30, len(entries))]
    lower = q.lower()
    matched = [
        entry
        for entry in entries
        if lower in entry.id.lower()
        or q in entry.title
        or q in entry.file_title
        or q in entry.dz_no
        or q in entry.section
        or q in entry.dynasty
        or q in entry.authors
        or lower in entry.rel_path.lower()
    ]
    matched.sort(
        key=lambda entry: (
            0 if entry.dz_no == q.lstrip("0") or entry.dz_no == q else 1,
            0 if entry.title.startswith(q) else 1,
            entry.dz_no.zfill(5) if entry.dz_no else "99999",
            entry.title,
        )
    )
    return matched[:limit]
