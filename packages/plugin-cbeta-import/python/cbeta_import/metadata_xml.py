"""Per-juan work metadata + ``<teiHeader>`` for a CBETA import.

Two input tiers (planning §4, §5.8):

1. **always** — the CBETA file's own ``<teiHeader>``: ``<title>`` (canon + No.
   + 經名), the ``<author>`` byline string (``後秦 佛陀耶舍共竺佛念譯``),
   ``<sourceDesc><bibl>`` (Taishō vol/no), ``<extent>`` (卷數);
2. **when built** — ``data/metadata/work_info.json`` keyed by catalog work id,
   with dynasty, 部類, and **contributors already resolved** to DILA person ids
   (and, via the DILA→Norbert crosswalk, Norbert ids + Wikidata Q-ids) by
   ``scripts/build-cbeta-metadata.py``.

`work_info.json` schema (one entry per catalog work id, e.g. ``"T0001"``):

    {
      "title": "長阿含經",
      "dynasty": "後秦",
      "category": "阿含部",              # 部類
      "juan_count": 22,
      "work_qid": "Q…",                  # optional
      "contributors": [
        {"person_name": "佛陀耶舍", "role": "translator",
         "dila_id": "A012345", "norbert_id": "6789",
         "wikidata_qid": "Q…", "dates": "?–413"},
        {"person_name": "竺佛念", "role": "translator", "dila_id": "A054321"}
      ]
    }

When tier 2 is absent, the byline string is parsed best-effort for dynasty +
names + role; contributors then carry no authority id (plain ``<author>``),
which a later tagging pass can still resolve.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from lxml import etree

from cbeta_import import _paths
from cbeta_import.catalog_index import clean_title, split_author
from cbeta_import.constants import CANON_EDITIONS, CBETA_CANONS, DATA_VERSION_TAG, TEI_NS

_TEI = f"{{{TEI_NS}}}"


def canon_of(work_id: str) -> str:
    """Leading canon code of a work id (``T01n0001`` / ``T0001`` -> ``T``,
    ``ZW01n0001`` -> ``ZW``). Empty when the prefix isn't a known canon."""
    m = re.match(r"^([A-Z]{1,2})", work_id or "")
    if not m:
        return ""
    two, one = work_id[:2], work_id[:1]
    if two in CBETA_CANONS and work_id[2:3].isdigit():
        return two
    return one if one in CBETA_CANONS else ""
_BIBL_VOL_NO = re.compile(r"Vol\.\s*([A-Za-z0-9]+)\s*,\s*No\.\s*([A-Za-z0-9]+)", re.I)
_EXTENT_JUAN = re.compile(r"(\d+)\s*卷")
_ANON = ("失譯", "闕譯", "未詳", "不詳")

# byline role verb → TEI-ish role token
_ROLE_VERBS: tuple[tuple[str, str], ...] = (
    ("譯", "translator"),
    ("撰", "author"),
    ("著", "author"),
    ("作", "author"),
    ("說", "author"),
    ("造", "author"),
    ("集", "compiler"),
    ("輯", "compiler"),
    ("編", "compiler"),
    ("錄", "recorder"),
    ("述", "author"),
    ("疏", "commentator"),
    ("註", "commentator"),
    ("注", "commentator"),
    ("解", "commentator"),
    ("校", "editor"),
    ("勘", "editor"),
    ("定", "editor"),
)
# CBETA <byline cb:type="…"> → role token
_CB_TYPE_ROLE = {
    "author": "author",
    "translator": "translator",
    "editor": "editor",
    "collector": "compiler",
    "commentator": "commentator",
}

_NAME_SEP = re.compile(r"[共、，,・･及與与]|等")
_HONORIFIC = re.compile(r"奉[　\s]*(?:詔|勅|敕|制)[　\s]*$")

# Dynasty tokens seen at the head of CBETA bylines, longest-first for greedy peel.
_DYNASTIES = sorted(
    (
        "後漢", "東漢", "曹魏", "元魏", "北魏", "後魏", "西晉", "東晉", "前秦", "後秦",
        "姚秦", "苻秦", "西秦", "北涼", "前涼", "劉宋", "蕭齊", "高齊", "北齊", "後周",
        "北周", "武周", "李唐", "趙宋", "南宋", "北宋", "五代", "民國",
        "漢", "魏", "吳", "晉", "秦", "涼", "宋", "齊", "梁", "陳", "周", "隋", "唐",
        "遼", "金", "元", "明", "清",
    ),
    key=len,
    reverse=True,
)


@dataclass
class Contributor:
    person_name: str
    role: str = ""
    dila_id: str = ""
    norbert_id: str = ""
    wikidata_qid: str = ""
    dates: str = ""


@dataclass
class WorkMeta:
    work_id: str
    title: str = ""
    canon: str = ""
    taisho_vol: str = ""
    taisho_no: str = ""
    dynasty: str = ""
    category: str = ""
    juan_count: int = 0
    work_qid: str = ""
    work_dila_id: str = ""  # DILA catalog-authority id (CA…), when no Wikidata QID
    contributors: list[Contributor] = field(default_factory=list)
    byline_raw: str = ""

    def payload(self) -> dict[str, object]:
        """Fields the host `cbetaImportXml.wrapCbetaTeiDocument` consumes."""
        return {
            "title": self.title,
            "canon": self.canon,
            "dynasty": self.dynasty,
            "category": self.category,
            "taisho_vol": self.taisho_vol,
            "taisho_no": self.taisho_no,
            "work_qid": self.work_qid,
            "work_dila_id": self.work_dila_id,
            "authorship": [
                {k: v for k, v in asdict(c).items() if v} for c in self.contributors
            ],
        }


# --------------------------------------------------------------------------- #
# byline parsing


def parse_byline(raw: str, *, cb_type: str = "") -> tuple[str, list[Contributor]]:
    """``後秦 龜茲國三藏鳩摩羅什奉　詔譯`` → (``後秦``, [Contributor(鳩摩羅什, translator)]).

    Best-effort: strip a leading dynasty token, an ``奉詔`` honorific, and the
    trailing role verb; split the remainder into names. Titles/monastery
    prefixes (``龜茲國三藏``…) are left on the name — a later authority pass
    is expected to normalise.
    """
    dynasty, rest = split_author(raw)
    rest = rest.strip()
    if not dynasty:
        # no separating space (common in body <byline>): peel a known dynasty token
        for d in _DYNASTIES:
            if rest.startswith(d) and len(rest) > len(d):
                dynasty, rest = d, rest[len(d) :].strip()
                break
    if not rest:
        return (dynasty, [])

    if any(rest.startswith(a) or rest == a for a in _ANON):
        role = _CB_TYPE_ROLE.get(cb_type.lower(), "translator")
        return (dynasty, [Contributor(person_name=rest or "失譯", role=role)])

    role = _CB_TYPE_ROLE.get(cb_type.lower(), "")
    body = rest
    for verb, verb_role in _ROLE_VERBS:
        if body.endswith(verb):
            body = body[: -len(verb)]
            role = role or verb_role
            break
    body = _HONORIFIC.sub("", body).strip()
    if not role:
        role = _CB_TYPE_ROLE.get(cb_type.lower(), "author")

    names = [n.strip() for n in _NAME_SEP.split(body) if n.strip()]
    if not names:
        names = [body] if body else []
    return (dynasty, [Contributor(person_name=n, role=role) for n in names])


# --------------------------------------------------------------------------- #
# extraction from the CBETA file


def _text(el: etree._Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def extract_from_header(tree: etree._ElementTree | etree._Element, work_id: str) -> WorkMeta:
    root = tree.getroot() if isinstance(tree, etree._ElementTree) else tree
    header = root.find(f".//{_TEI}teiHeader")
    meta = WorkMeta(work_id=work_id, canon=canon_of(work_id))
    if header is None:
        return meta

    title_el = header.find(f".//{_TEI}titleStmt/{_TEI}title")
    meta.title = clean_title(_text(title_el))

    author_el = header.find(f".//{_TEI}titleStmt/{_TEI}author")
    meta.byline_raw = _text(author_el)
    if meta.byline_raw:
        dynasty, contributors = parse_byline(meta.byline_raw)
        meta.dynasty = dynasty
        meta.contributors = contributors

    bibl = _text(header.find(f".//{_TEI}sourceDesc/{_TEI}bibl"))
    m = _BIBL_VOL_NO.search(bibl)
    if m:
        meta.taisho_vol, meta.taisho_no = m.group(1), m.group(2)

    extent = _text(header.find(f".//{_TEI}extent"))
    em = _EXTENT_JUAN.search(extent)
    if em:
        meta.juan_count = int(em.group(1))
    return meta


# --------------------------------------------------------------------------- #
# work_info.json


def lookup_work_info(work_id: str) -> dict | None:
    path = _paths.work_info_path()
    if not path.is_file() or path.stat().st_size <= 2:
        return None
    try:
        table = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return None
    return table.get(work_id) or table.get(work_id.replace("n", "").lstrip("0"))


def resolve_work_meta(
    tree: etree._ElementTree | etree._Element, work_id: str
) -> WorkMeta:
    """CBETA-header extraction, enriched by ``work_info.json`` where present."""
    meta = extract_from_header(tree, work_id)
    info = lookup_work_info(work_id)
    if not info:
        return meta

    meta.title = info.get("title") or meta.title
    meta.dynasty = info.get("dynasty") or meta.dynasty
    meta.category = info.get("category") or meta.category
    meta.work_qid = info.get("work_qid") or meta.work_qid
    meta.work_dila_id = info.get("work_dila_id") or meta.work_dila_id
    if info.get("juan_count"):
        meta.juan_count = int(info["juan_count"])

    rows = info.get("contributors") or []
    if rows:
        meta.contributors = [
            Contributor(
                person_name=r.get("person_name", ""),
                role=r.get("role", ""),
                dila_id=r.get("dila_id", ""),
                norbert_id=str(r.get("norbert_id", "") or ""),
                wikidata_qid=r.get("wikidata_qid", ""),
                dates=r.get("dates", ""),
            )
            for r in rows
            if r.get("person_name")
        ]
    return meta


# --------------------------------------------------------------------------- #
# <teiHeader> emission (all-Python path; the host wrapper is the primary one)


def _authority_ref(c: Contributor) -> str:
    if c.wikidata_qid:
        return f"https://www.wikidata.org/entity/{c.wikidata_qid}"
    if c.norbert_id:
        return f"NORBERT:person-{c.norbert_id}"
    if c.dila_id:
        return f"DILA:{c.dila_id}"
    return ""


def _work_ref(meta: WorkMeta) -> str:
    """Best authority ref for the work title: Wikidata QID if present, else the
    DILA catalog-authority id (``DILA:CA…``), else empty (re-checkable later)."""
    if meta.work_qid:
        return f"https://www.wikidata.org/entity/{meta.work_qid}"
    if meta.work_dila_id:
        return f"DILA:{meta.work_dila_id}"
    return ""


def build_tei_header(
    meta: WorkMeta, *, juan_n: str = "", source_files: list[str] | None = None, git_commit: str = ""
) -> etree._Element:
    """A complete ``<teiHeader>`` element for one imported juan."""
    H = etree.Element(f"{_TEI}teiHeader")
    file_desc = etree.SubElement(H, f"{_TEI}fileDesc")

    work_ref = _work_ref(meta)

    title_stmt = etree.SubElement(file_desc, f"{_TEI}titleStmt")
    t = etree.SubElement(title_stmt, f"{_TEI}title")
    t.text = meta.title + (f" 卷{juan_n}" if juan_n else "")
    if work_ref:
        t.set("ref", work_ref)
    for c in meta.contributors:
        a = etree.SubElement(title_stmt, f"{_TEI}author")
        if c.role:
            a.set("role", c.role)
        ref = _authority_ref(c)
        if ref:
            a.set("ref", ref)
        a.text = c.person_name

    if meta.juan_count:
        etree.SubElement(file_desc, f"{_TEI}extent").text = f"{meta.juan_count} 卷"

    pub = etree.SubElement(file_desc, f"{_TEI}publicationStmt")
    etree.SubElement(pub, f"{_TEI}p").text = (
        "Imported from CBETA; distribute with this header intact (non-commercial)."
    )

    source_desc = etree.SubElement(file_desc, f"{_TEI}sourceDesc")
    bs = etree.SubElement(source_desc, f"{_TEI}biblStruct")
    monogr = etree.SubElement(bs, f"{_TEI}monogr")
    mt = etree.SubElement(monogr, f"{_TEI}title")
    mt.text = meta.title
    if work_ref:
        mt.set("ref", work_ref)
    _idno(monogr, "CBETA", meta.work_id)
    if meta.work_dila_id:
        _idno(monogr, "DILA", meta.work_dila_id)
    if meta.taisho_vol and meta.taisho_no:
        _idno(monogr, "Taisho", f"{meta.taisho_vol}.{meta.taisho_no}")

    # <edition> + dated <imprint> from the canon code (must precede <imprint>
    # in the TEI monogr content model).
    canon_ed = CANON_EDITIONS.get(meta.canon or canon_of(meta.work_id))
    if canon_ed:
        label, y0, y1 = canon_ed
        etree.SubElement(monogr, f"{_TEI}edition").text = label
    imprint = etree.SubElement(monogr, f"{_TEI}imprint")
    date = etree.SubElement(imprint, f"{_TEI}date")
    if canon_ed:
        if y0 == y1:
            date.set("when", y0)
            date.text = y0
        else:
            date.set("from", y0)
            date.set("to", y1)
            date.text = f"{y0}–{y1}"

    if meta.dynasty or meta.category:
        prof = etree.SubElement(H, f"{_TEI}profileDesc")
        if meta.dynasty:
            creation = etree.SubElement(prof, f"{_TEI}creation")
            etree.SubElement(creation, f"{_TEI}origDate").text = meta.dynasty
        if meta.category:
            # 部類 is a classification, not a note — put it in <textClass>
            # (a <note> in <creation> trips some TEI-All customisations).
            text_class = etree.SubElement(prof, f"{_TEI}textClass")
            keywords = etree.SubElement(text_class, f"{_TEI}keywords")
            keywords.set("scheme", "https://cbeta.org/format/#buleik")
            etree.SubElement(keywords, f"{_TEI}term").text = meta.category

    rev = etree.SubElement(H, f"{_TEI}revisionDesc")
    change = etree.SubElement(rev, f"{_TEI}change")
    src = ", ".join(source_files or [meta.work_id])
    commit = f" @ {git_commit[:12]}" if git_commit else ""
    change.text = (
        f"Imported from CBETA ({src}; data {DATA_VERSION_TAG}{commit}) "
        f"with plugin cbeta-import."
    )
    return H


def _idno(parent: etree._Element, kind: str, value: str) -> None:
    el = etree.SubElement(parent, f"{_TEI}idno")
    el.set("type", kind)
    el.text = value
