"""Build DPM-style metadata XML blocks for Daozang imports."""

from __future__ import annotations

from daozang_import.work_metadata import AuthorshipRecord, WorkMetadata

_XML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})


def _esc(text: str) -> str:
    return (text or "").translate(_XML_ESCAPE)


def _attr(name: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    return f' {name}="{_esc(v)}"'


def _authorship_xml(rec: AuthorshipRecord) -> str:
    attrs = "".join(
        [
            _attr("index", rec.author_index),
            _attr("person_id", rec.person_id),
            _attr("authAct", rec.function),
        ]
    )
    inner = f"<persName>{_esc(rec.person_name)}</persName>" if rec.person_name else ""
    return f"    <authorship{attrs}>\n      {inner}\n    </authorship>"


def _date_xml(work: WorkMetadata) -> str:
    dynasty = work.time_dynasty
    if not dynasty and work.authorship:
        dynasty = work.authorship[0].time_dynasty
    parts: list[str] = []
    if dynasty:
        parts.append(f"    <dyn>{_esc(dynasty)}</dyn>")
    if work.date_not_before or work.date_not_after:
        if work.date_not_before:
            parts.append(f"    <date notBefore=\"{_esc(work.date_not_before)}\"/>")
        if work.date_not_after:
            parts.append(f"    <date notAfter=\"{_esc(work.date_not_after)}\"/>")
    elif work.author_dates:
        parts.append(f"    <date>{_esc(work.author_dates)}</date>")
    if not parts:
        return ""
    return "  <date>\n" + "\n".join(parts) + "\n  </date>"


def build_metadata_xml(work: WorkMetadata) -> str:
    """Return a ``<metadata>`` fragment (DPM corpus convention)."""
    dz_id_attr = work.dz_no or (work.dzid[2:] if work.dzid.startswith("DZ") else work.dzid)
    citation_attrs = "".join(
        [
            _attr("dz_id", dz_id_attr),
            _attr("kr_id", work.kr_id),
            _attr("edition", work.edition),
            _attr("source", work.source),
            _attr("title", work.title),
        ]
    )
    if work.wikidata:
        wd = work.wikidata
        citation_attrs += "".join(
            [
                _attr("work_qid", wd.work_qid),
                _attr("edition_qid", wd.edition_qid),
                _attr("wikidata_work_qid", wd.wikidata_work_qid),
                _attr("ws_page", wd.ws_page),
            ]
        )
    vols_attrs = _attr("n", work.vols)
    authorship_blocks = "\n".join(_authorship_xml(a) for a in work.authorship)
    date_block = _date_xml(work)
    parts = [
        '<metadata xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">',
        f"  <citation{citation_attrs}/>",
        "  <work index=\"0\">",
        f"    <title>{_esc(work.title)}</title>",
    ]
    if work.vols:
        parts.append(f"    <vols{vols_attrs}/>")
    if authorship_blocks:
        parts.append(authorship_blocks)
    parts.append("  </work>")
    if date_block:
        parts.append(date_block)
    if work.wikidata and (work.wikidata.wikidata_work_qid or work.wikidata.ws_page):
        wd = work.wikidata
        parts.append("  <wikidata>")
        if wd.wikidata_work_qid:
            parts.append(f"    <workQid>{_esc(wd.wikidata_work_qid)}</workQid>")
        if wd.edition_qid:
            parts.append(f"    <editionQid>{_esc(wd.edition_qid)}</editionQid>")
        if wd.ws_page:
            parts.append(f"    <wsPage>{_esc(wd.ws_page)}</wsPage>")
        if wd.ws_url:
            parts.append(f"    <wsUrl>{_esc(wd.ws_url)}</wsUrl>")
        if wd.match_tier:
            parts.append(f"    <matchTier>{_esc(wd.match_tier)}</matchTier>")
        parts.append("  </wikidata>")
    parts.append("</metadata>")
    return "\n".join(parts)


def work_metadata_to_dict(work: WorkMetadata) -> dict[str, object]:
    wd: dict[str, object] | None = None
    if work.wikidata:
        wd = {
            "work_qid": work.wikidata.work_qid,
            "edition_qid": work.wikidata.edition_qid,
            "wikidata_work_qid": work.wikidata.wikidata_work_qid,
            "ws_page": work.wikidata.ws_page,
            "ws_url": work.wikidata.ws_url,
            "match_tier": work.wikidata.match_tier,
            "page_exists": work.wikidata.page_exists,
        }
    return {
        "rel_path": work.rel_path,
        "dzid": work.dzid,
        "dz_no": work.dz_no,
        "title": work.title,
        "vols": work.vols,
        "kr_id": work.kr_id,
        "krp_title": work.krp_title,
        "edition": work.edition,
        "variant_class": work.variant_class,
        "source": work.source,
        "time_dynasty": work.time_dynasty,
        "date_not_before": work.date_not_before,
        "date_not_after": work.date_not_after,
        "author_dates": work.author_dates,
        "wikidata": wd,
        "authorship": [
            {
                "author_index": a.author_index,
                "person_name": a.person_name,
                "person_id": a.person_id,
                "wikidata_qid": a.wikidata_qid,
                "cbdb_id": a.cbdb_id,
                "norbert_id": a.norbert_id,
                "function": a.function,
                "time_dynasty": a.time_dynasty,
                "author_dates": a.author_dates,
                "date_not_before": a.date_not_before,
                "date_not_after": a.date_not_after,
            }
            for a in work.authorship
        ],
    }
