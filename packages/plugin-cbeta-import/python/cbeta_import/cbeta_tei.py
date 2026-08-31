"""CBETA P5 → project TEI, one file per juan.

Pipeline (leaf-writer/docs/cbeta-import-planning.md §5–7):

  parse → split_body_into_juan → per juan:
      resolve <g>                              (gaiji.apply)           [done]
      drop @style                              (§7)                   [done]
      drop <lb>/<pb> @ed in DROP_ED            (§7)                   [done]
      drop <note type="orig">                  (§7)                   [done]
      <cb:yin>/<cb:fan>/<cb:sg> → <note gloss> (§5.2, unconditional)  [done]
      cross-family only (downgrade.apply_cross_family):
        <cb:tt>/<cb:t>   → <seg subtype="cb:t…">   (§5.1)             [done]
        <cb:juan>        → drop open / <trailer>    (§5.4)             [done]
        <cb:div>         → <div>; <cb:mulu> → <div> nesting / marker  (§5.3) [done]
        cb:* attrs       → plain TEI attrs / drop   (§5.6)             [done]
      → host wraps in project skeleton + teiHeader (cbetaImportXml / metadata_xml)
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from cbeta_import import _paths, catalog_index, downgrade, gaiji, metadata_xml
from cbeta_import.constants import DATA_VERSION_TAG, DROP_ED, DROP_NOTE_TYPES, TEI_NS
from cbeta_import.juan_split import (
    JuanSlice,
    attach_apparatus,
    collect_ids,
    find_back,
    find_body,
    prefix_ids,
    serialize_juan_body,
    split_body_into_juan,
    stitch_cross_file_juan,
)
from cbeta_import.mulu_split import split_body_into_mulu
from cbeta_import.reading import apply_reading_options

_TEI = f"{{{TEI_NS}}}"
_WORK_ID_RE = re.compile(r"^(?P<canon>[A-Z]{1,2})(?P<vol>[A-Za-z]?\d{2,3})n(?P<no>[A-Za-z]?\d{2,4}[A-Za-z]?)$")


@dataclass
class JuanResult:
    n: str
    title: str
    body_xml: str
    straddles: list[str] = field(default_factory=list)
    report: dict[str, int] = field(default_factory=dict)


@dataclass
class ConvertResult:
    work_id: str
    canon: str
    vol: str
    no: str
    data_version: str
    git_commit: str = ""
    juan: list[JuanResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "work_id": self.work_id,
            "canon": self.canon,
            "vol": self.vol,
            "no": self.no,
            "data_version": self.data_version,
            "git_commit": self.git_commit,
            # title / dynasty / category / taisho_vol / taisho_no / work_qid / authorship
            **self.meta,
            "juan": [
                {
                    "n": j.n,
                    "title": j.title,
                    "body_xml": j.body_xml,
                    "straddles": j.straddles,
                    "report": j.report,
                }
                for j in self.juan
            ],
            "warnings": self.warnings,
        }


def _parse_work_id(stem: str) -> tuple[str, str, str]:
    m = _WORK_ID_RE.match(stem)
    if not m:
        return ("", "", "")
    return (m.group("canon"), m.group("vol"), m.group("no"))


def _catalog_work_id(stem: str) -> str:
    canon, _vol, no = _parse_work_id(stem)
    return f"{canon}{no}" if canon else stem


def _corpus_commit(cache_root: Path | None) -> str:
    try:
        mpath = _paths.corpus_manifest_path(Path(cache_root) if cache_root else None)
        if mpath.is_file():
            import json

            return str(json.loads(mpath.read_text("utf-8")).get("commit") or "")
    except Exception:  # noqa: BLE001 — provenance is best-effort
        pass
    return ""


def _drop_style(body: etree._Element) -> int:
    n = 0
    for el in body.iter():
        if "style" in el.attrib:
            del el.attrib["style"]
            n += 1
    return n


def _drop_reprint_lines(body: etree._Element) -> int:
    n = 0
    for tag in (f"{_TEI}lb", f"{_TEI}pb"):
        for el in list(body.iter(tag)):
            if el.get("ed") in DROP_ED:
                _unwrap_empty(el)
                n += 1
    return n


def _drop_orig_notes(body: etree._Element) -> int:
    n = 0
    for el in list(body.iter(f"{_TEI}note")):
        if el.get("type") in DROP_NOTE_TYPES:
            _unwrap_empty(el, keep_tail=True)
            n += 1
    return n


def _unwrap_empty(el: etree._Element, *, keep_tail: bool = True) -> None:
    parent = el.getparent()
    if parent is None:
        return
    if keep_tail and el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def transform_juan(
    sl: JuanSlice,
    char_map: dict[str, str],
    *,
    cross_family: bool,
    clean: bool = False,
    strip_lb: bool = False,
) -> JuanResult:
    """Apply the decided in-place reductions to one juan slice."""
    holder = etree.Element(f"{_TEI}body")
    for el in sl.elements:
        holder.append(el)

    report = {
        "gaiji_resolved": gaiji.apply(holder, char_map),
        "style_dropped": _drop_style(holder),
        "reprint_lines_dropped": _drop_reprint_lines(holder),
        "orig_notes_dropped": _drop_orig_notes(holder),
        "phonetic_gloss_downgraded": downgrade.phonetic_glosses(holder),
    }

    if cross_family:
        for k, v in downgrade.apply_cross_family(holder).items():
            report[k] = v

    if clean or strip_lb:
        report.update(apply_reading_options(holder, clean=clean, strip_lb=strip_lb))

    sl.elements = list(holder)

    if clean:
        sl.apparatus = []
    elif sl.apparatus:
        back = sl.apparatus[0]
        report["apparatus_apps"] = len(back.findall(f".//{_TEI}app"))
        gaiji.apply(back, char_map)
        _drop_orig_notes(back)
        downgrade.phonetic_glosses(back)
        if cross_family:
            downgrade.translation_terms(back)
            downgrade.mulu_and_divs(back)
            downgrade.structural(back)

    return JuanResult(
        n=sl.n,
        title=sl.title,
        body_xml=serialize_juan_body(sl),
        straddles=sl.straddles,
        report=report,
    )


def _parse(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    return etree.parse(str(path), parser)


def convert_cbeta_xml(
    path: str | Path,
    *,
    rel_path: str = "",
    cross_family: bool = True,
    clean: bool = False,
    strip_lb: bool = False,
    split_unit: str = "mulu",
) -> dict[str, object]:
    """Split one CBETA XML file by juan and apply the reductions."""
    return _convert(
        [Path(path)],
        work_id="",
        cross_family=cross_family,
        clean=clean,
        strip_lb=strip_lb,
        split_unit=split_unit,
        cache_root=None,
    )


def convert_cbeta_work(
    *,
    work_id: str | None = None,
    path: str | None = None,
    cache_root: str | Path | None = None,
    cross_family: bool = True,
    clean: bool = False,
    strip_lb: bool = False,
    split_unit: str = "mulu",
) -> dict[str, object]:
    """Entry point. Resolve a work id (or take an explicit file), concatenate a
    multi-file work's ``<body>`` in volume order, then split by juan (planning §5.7).

    ``cross_family=True`` when importing into a non-CBETA project (TEI-ALL etc.),
    which additionally triggers the structural downgrades (still TODO).
    """
    croot = Path(cache_root) if cache_root else None
    if work_id:
        files = catalog_index.resolve_work_files(work_id, cache_root=croot)
    elif path:
        files = [Path(path)]
    else:
        raise ValueError("convert_cbeta_work needs work_id or path")
    return _convert(
        files,
        work_id=work_id or "",
        cross_family=cross_family,
        clean=clean,
        strip_lb=strip_lb,
        split_unit=split_unit,
        cache_root=croot,
    )


def _split_work_body(
    tree: etree._ElementTree, *, split_unit: str, warnings: list[str]
) -> list[JuanSlice]:
    unit = (split_unit or "mulu").lower()
    if unit == "mulu":
        slices = split_body_into_mulu(tree)
        if slices:
            return slices
        warnings.append("no mulu section headings found; fell back to juan split")
    return split_body_into_juan(tree)


def _convert(
    files: list[Path],
    *,
    work_id: str,
    cross_family: bool,
    clean: bool = False,
    strip_lb: bool = False,
    split_unit: str = "mulu",
    cache_root: Path | None,
) -> dict[str, object]:
    missing = [f for f in files if not f.is_file()]
    if missing:
        raise FileNotFoundError(f"CBETA XML not found: {', '.join(str(m) for m in missing)}")

    trees = [_parse(f) for f in files]
    char_map: dict[str, str] = {}
    for t in trees:
        char_map.update(gaiji.load_char_decl(t))

    base_tree = trees[0]
    stem = files[0].stem
    wm = metadata_xml.resolve_work_meta(base_tree, work_id or _catalog_work_id(stem))

    if len(trees) > 1:
        base_body = find_body(base_tree)
        base_back = find_back(base_tree)
        for extra, extra_path in zip(trees[1:], files[1:]):
            pfx = f"{extra_path.stem}__"
            eb = find_body(extra)
            ek = find_back(extra)
            file_ids = collect_ids(eb) | (collect_ids(ek) if ek is not None else set())
            prefix_ids(eb, pfx, file_ids)
            for child in list(eb):
                base_body.append(copy.deepcopy(child))
            if ek is not None:
                prefix_ids(ek, pfx, file_ids)
                if base_back is None:
                    base_back = copy.deepcopy(ek)
                    base_tree.getroot().find(f".//{_TEI}text").append(base_back)
                else:
                    for child in list(ek):
                        base_back.append(copy.deepcopy(child))

    canon, vol, no = _parse_work_id(stem)
    result = ConvertResult(
        work_id=work_id or _catalog_work_id(stem),
        canon=canon,
        vol=vol,
        no=no,
        data_version=DATA_VERSION_TAG,
        git_commit=_corpus_commit(cache_root),
        meta=wm.payload(),
    )
    if len(files) > 1:
        result.warnings.append(
            f"multi-file work: concatenated {len(files)} files "
            f"({', '.join(f.stem for f in files)}) before juan split"
        )

    slices = _split_work_body(base_tree, split_unit=split_unit, warnings=result.warnings)
    if split_unit.lower() == "juan" and len(files) > 1:
        result.warnings.extend(stitch_cross_file_juan(slices))
    attach_apparatus(slices, find_back(base_tree))
    for sl in slices:
        result.juan.append(
            transform_juan(
                sl,
                char_map,
                cross_family=cross_family,
                clean=clean,
                strip_lb=strip_lb,
            )
        )
        result.warnings.extend(sl.straddles)
    return result.to_dict()
