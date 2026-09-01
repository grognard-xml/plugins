"""Resolve a CBETA work id to its source file(s) and drive the import picker.

Two sources, in priority order:

1. a built ``catalog_index.json`` (bundled ``data/metadata/`` or the cache root)
   — richer: dynasty / 部類 / contributors from ``cbeta-metadata`` +
   ``Authority-Databases`` (produced by ``scripts/build-cbeta-metadata.py``);
2. otherwise, an index scanned straight from the synced ``xml-p5`` checkout —
   work id, title, dynasty (from ``<author>``), juan count, file grouping.
   Cached to ``<cache_root>/catalog_index.json`` and rebuilt when the corpus
   commit changes.

Multi-file works (planning §5.7) are detected from the filename layout:

* same ``<canon><digits>`` across **different volumes**, no letter suffix
  → one continuation work (``L1557`` = ``L130n1557``…``L133n1557``);
* **lowercase** suffix spanning volumes → continuation (``T0220`` =
  ``T05n0220a``…``T07n0220o``);
* **lowercase** suffix within one volume → distinct 異本 (``T0128a``/``T0128b``);
* **uppercase** suffix → distinct Taishō-numbered works (``T0150A``/``T0150B``).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from cbeta_import import _paths

_STEM_RE = re.compile(r"^(?P<canon>[A-Z]{1,2})(?P<volnum>\d{1,3})n(?P<no>[A-Za-z]?\d{1,4}[A-Za-z]?)$")
_NO_RE = re.compile(r"^(?P<lead>[A-Za-z]?)(?P<core>\d{1,4})(?P<trail>[A-Za-z]?)$")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_AUTHOR_RE = re.compile(r"<author[^>]*>(.*?)</author>", re.S)
_NO_PREFIX_RE = re.compile(r"^.*?No\.\s*\S+\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_WS = re.compile(r"[\s　]+")


@dataclass
class CatalogHit:
    work_id: str
    title: str
    canon: str
    dynasty: str = ""
    category: str = ""
    juan_count: int = 0
    files: tuple[str, ...] = ()  # <vol>n<no> stems, volume order
    authors: str = ""

    def paths(self, corpus_root: Path) -> list[Path]:
        out: list[Path] = []
        for stem in self.files:
            m = _STEM_RE.match(stem)
            if not m:
                continue
            vol = f"{m['canon']}{m['volnum']}"
            out.append(corpus_root / m["canon"] / vol / f"{stem}.xml")
        return out


@dataclass
class _RawFile:
    stem: str
    canon: str
    vol: str
    lead: str
    core: str
    trail: str
    volnum: int


def _parse_stem(stem: str) -> _RawFile | None:
    m = _STEM_RE.match(stem)
    if not m:
        return None
    nm = _NO_RE.match(m["no"])
    if not nm:
        return None
    return _RawFile(
        stem=stem,
        canon=m["canon"],
        vol=f"{m['canon']}{m['volnum']}",
        lead=nm["lead"],
        core=nm["core"].zfill(4),
        trail=nm["trail"],
        volnum=int(m["volnum"]),
    )


def clean_title(raw: str) -> str:
    """"Taisho Tripitaka … No. 0001 長阿含經" → "長阿含經"."""
    text = _WS.sub(" ", _TAG_RE.sub("", raw)).strip()
    return _NO_PREFIX_RE.sub("", text).strip() or text


def split_author(raw: str) -> tuple[str, str]:
    """"後秦 佛陀耶舍共竺佛念譯" → ("後秦", "佛陀耶舍共竺佛念譯")."""
    text = _WS.sub(" ", _TAG_RE.sub("", raw)).strip()
    if not text:
        return ("", "")
    parts = text.split(" ", 1)
    if len(parts) == 2 and len(parts[0]) <= 4:
        return (parts[0], parts[1])
    return ("", text)


def _read_header_fields(path: Path) -> tuple[str, str, str, int]:
    """(title, dynasty, authors, juan_count) — byte scan, no XML parse."""
    try:
        data = path.read_bytes()
    except OSError:
        return ("", "", "", 0)
    head = data[:20000].decode("utf-8", "replace")
    title = clean_title(_TITLE_RE.search(head).group(1)) if _TITLE_RE.search(head) else path.stem
    dynasty, authors = (
        split_author(_AUTHOR_RE.search(head).group(1)) if _AUTHOR_RE.search(head) else ("", "")
    )
    text = data.decode("utf-8", "replace")
    juan = max(text.count('fun="open"'), text.count('unit="juan"'))
    return (title, dynasty, authors, juan)


def _group_key(rf: _RawFile) -> tuple[str, str, str]:
    return (rf.canon, rf.lead, rf.core)


def _works_from_group(files: list[_RawFile]) -> list[list[_RawFile]]:
    if len(files) == 1:
        return [files]
    if any(rf.trail.isupper() for rf in files):
        return [[rf] for rf in files]
    if all(rf.trail == "" for rf in files):
        return [sorted(files, key=lambda r: r.volnum)]  # continuation across volumes
    vols = {rf.volnum for rf in files}
    if len(vols) > 1:  # lowercase suffix spanning volumes → continuation
        return [sorted(files, key=lambda r: (r.volnum, r.trail))]
    return [[rf] for rf in sorted(files, key=lambda r: r.trail)]  # 異本 in one volume


def _work_id(files: list[_RawFile]) -> str:
    head = files[0]
    if len(files) == 1:
        return f"{head.canon}{head.lead}{head.core}{head.trail}"
    return f"{head.canon}{head.lead}{head.core}"  # bare — continuation


def group_stems(stems: object) -> dict[str, tuple[str, ...]]:
    """``[…, "T/T05/T05n0220a.xml", "T05n0220b", …]`` → ``{work_id: (stem, …)}``.

    Accepts bare stems or any path ending in ``<stem>.xml``; non-work files are
    ignored. Same grouping rule as ``build_index_from_corpus`` (planning §5.7),
    so it can fill the ``files`` column without a corpus checkout — feed it a
    GitHub tree listing.
    """
    raw: dict[tuple[str, str, str], list[_RawFile]] = {}
    for item in stems:
        stem = str(item).rsplit("/", 1)[-1]
        if stem.endswith(".xml"):
            stem = stem[:-4]
        rf = _parse_stem(stem)
        if rf is not None:
            raw.setdefault(_group_key(rf), []).append(rf)
    out: dict[str, tuple[str, ...]] = {}
    for group in raw.values():
        for work_files in _works_from_group(group):
            ordered = list(work_files)
            out[_work_id(ordered)] = tuple(rf.stem for rf in ordered)
    return out


def build_index_from_corpus(corpus_root: Path) -> list[CatalogHit]:
    corpus_root = Path(corpus_root)
    raw: dict[tuple[str, str, str], list[_RawFile]] = {}
    for xml_path in corpus_root.glob("*/*/*.xml"):
        rf = _parse_stem(xml_path.stem)
        if rf is not None:
            raw.setdefault(_group_key(rf), []).append(rf)

    hits: list[CatalogHit] = []
    for group in raw.values():
        for work_files in _works_from_group(group):
            ordered = list(work_files)
            first = ordered[0]
            path0 = corpus_root / first.canon / first.vol / f"{first.stem}.xml"
            title, dynasty, authors, juan = _read_header_fields(path0)
            if len(ordered) > 1:
                juan = sum(
                    _read_header_fields(corpus_root / rf.canon / rf.vol / f"{rf.stem}.xml")[3]
                    for rf in ordered
                )
            hits.append(
                CatalogHit(
                    work_id=_work_id(ordered),
                    title=title,
                    canon=first.canon,
                    dynasty=dynasty,
                    juan_count=juan,
                    files=tuple(rf.stem for rf in ordered),
                    authors=authors,
                )
            )
    hits.sort(key=lambda h: (h.canon, h.work_id))
    return hits


# --------------------------------------------------------------------------- #
# load / cache


def _corpus_commit(cache_root: Path) -> str:
    mpath = _paths.corpus_manifest_path(cache_root)
    if mpath.is_file():
        try:
            return str(json.loads(mpath.read_text("utf-8")).get("commit") or "")
        except json.JSONDecodeError:
            return ""
    return ""


def _read_index_file(path: Path) -> list[CatalogHit]:
    payload = json.loads(path.read_text("utf-8"))
    rows = payload["works"] if isinstance(payload, dict) else payload
    return [CatalogHit(**{**{"files": ()}, **row, "files": tuple(row.get("files", ()))}) for row in rows]


def load_index(
    *,
    cache_root: Path | None = None,
    corpus_root: Path | None = None,
    rebuild: bool = False,
) -> list[CatalogHit]:
    croot = Path(cache_root) if cache_root is not None else _paths.cache_root()
    corpus = Path(corpus_root) if corpus_root is not None else _paths.corpus_dir(croot)

    bundled = _paths.bundled_catalog_index_path()
    if not rebuild and bundled.is_file() and bundled.stat().st_size > 2:
        try:
            rows = _read_index_file(bundled)
            if rows:
                return rows
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    cached = _paths.cached_catalog_index_path(croot)
    commit = _corpus_commit(croot)
    if not rebuild and cached.is_file():
        try:
            payload = json.loads(cached.read_text("utf-8"))
            if isinstance(payload, dict) and payload.get("corpus_commit") == commit:
                return _read_index_file(cached)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    if not corpus.is_dir():
        raise RuntimeError(
            "CBETA corpus is not synced. Run the Sync corpus action first "
            "(or install_from_source)."
        )
    hits = build_index_from_corpus(corpus)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(
        json.dumps(
            {"corpus_commit": commit, "built_from": str(corpus), "works": [asdict(h) for h in hits]},
            ensure_ascii=False,
        ),
        "utf-8",
    )
    return hits


# --------------------------------------------------------------------------- #
# search / resolve


def _score(hit: CatalogHit, q: str) -> int:
    wid = hit.work_id.lower()
    if wid == q:
        return 0
    if wid.startswith(q):
        return 1
    if q in wid:
        return 2
    if q in hit.title.lower():
        return 3
    return 4


def search(
    query: str,
    *,
    limit: int = 40,
    cache_root: Path | None = None,
    corpus_root: Path | None = None,
) -> list[CatalogHit]:
    q = (query or "").strip().lower()
    index = load_index(cache_root=cache_root, corpus_root=corpus_root)
    if not q:
        return index[:limit]
    hay = [
        h
        for h in index
        if q in h.work_id.lower()
        or q in h.title.lower()
        or q in h.dynasty.lower()
        or q in h.category.lower()
        or q in h.authors.lower()
    ]
    hay.sort(key=lambda h: (_score(h, q), h.canon, h.work_id))
    return hay[:limit]


_NORMALISE_RE = re.compile(r"^(?P<canon>[A-Z]{1,2})(?P<volnum>\d{1,3})n(?P<no>[A-Za-z]?\d{1,4}[A-Za-z]?)$")


def resolve_work_files(
    work_id: str,
    *,
    cache_root: Path | None = None,
    corpus_root: Path | None = None,
) -> list[Path]:
    """Ordered source files for a work id (``T0001``, ``T01n0001``, ``T0220``, ``JA042``)."""
    croot = Path(cache_root) if cache_root is not None else _paths.cache_root()
    corpus = Path(corpus_root) if corpus_root is not None else _paths.corpus_dir(croot)
    wid = (work_id or "").strip()

    # a full filename stem addresses exactly one file
    fm = _NORMALISE_RE.match(wid)
    if fm:
        vol = f"{fm['canon']}{fm['volnum']}"
        path = corpus / fm["canon"] / vol / f"{wid}.xml"
        if path.is_file():
            return [path]

    index = load_index(cache_root=croot, corpus_root=corpus)
    for hit in index:
        if hit.work_id == wid:
            if not hit.files:
                raise FileNotFoundError(
                    f"work {wid} ({hit.title or '?'}) is in the CBETA catalogue but has no "
                    f"TEI/XML source in the synced xml-p5 corpus — it is not digitised in "
                    f"this CBETA release (common for parts of the Jiaxing 嘉興藏)."
                )
            paths = hit.paths(corpus)
            missing = [p for p in paths if not p.is_file()]
            if missing:
                raise FileNotFoundError(f"work {wid}: missing {', '.join(p.name for p in missing)}")
            return paths
    raise KeyError(f"work id not found in catalog: {wid}")
