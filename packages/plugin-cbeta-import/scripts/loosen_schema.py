#!/usr/bin/env python3
"""Apply the Grognard §4 loosenings to CBETA's published RelaxNG (+ Schematron).

CBETA ships one flat, ODD-generated grammar (`cbeta-p5.rng`, `tei_`-prefixed
pattern names, ~570 `<define>`s) with 3 embedded Schematron rules. We widen it
just enough to hold our tagging apparatus and to serve as a shared target for
the other East Asian corpus importers (Daozang, Kanripo, Wikisource, BDRC):

1. `@ref` / `@key` permitted on `<title>`, `<author>`, `<byline>` and every NE
   element (per-define, guarded so we never double-declare an attribute);
2. the Grognard NE inventory (`persName`, `placeName`, `orgName`, `roleName`, `name`,
   `title`, `date`, `nobleTitle`) added to `tei_model.phrase` — so it may occur
   in `<p>`, `<l>`, `<head>`, `<seg>`, `<note>` …;
3. `<date>` extended with the Sanmiao parse children + resolution attributes
   (leaf-writer/docs/grognard-tei-extensions.md; kept in sync with
   apps/desktop/src/sanmiaoSchemaMerge.ts).

v2 adds three model loosenings so non-CBETA corpora (which emit plain TEI
`<div type="…">`, `<creation><origDate>`, unscoped `<keywords>`) validate
against the same grammar as native CBETA:

4. `tei_div` matches BOTH `<cb:div>` and TEI-namespace `<div>` — every context
   that allows a division (`model.divLike`, nested divs, front/back) now takes
   either;
5. `<creation>` content widened from `macro.phraseSeq.limited` to
   `macro.phraseSeq` (admits `<date>` / names — note CBETA has no `<origDate>`,
   so importers must record composition date as `<date>`);
6. `@scheme` on `<keywords>` made optional;
7. optional `@role` on `<author>` / `<editor>` (CBETA drops `att.naming`).

Interleaving (§4.3 — `<lb/>`/`<pb/>`/`<anchor/>`/`<g>` inside NE elements) is
already satisfied: the NE defines use `tei_macro.phraseSeq`, which pulls
`tei_model.global` (milestones/anchor) and `tei_model.gLike` (`g`).

Schematron: CBETA's only rules require `@spanTo` on `addSpan`/`damageSpan`/
`delSpan` — nothing touches inserted markup — so the `.sch` passes through
unchanged.

Every step is individually idempotent, so re-running on a v1 output upgrades it
to v2 in place.

Usage:  loosen_schema.py IN.rng OUT.rng [IN.sch OUT.sch]
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

RNG = "http://relaxng.org/ns/structure/1.0"
A = "http://relaxng.org/ns/compatibility/annotations/1.0"
_R = f"{{{RNG}}}"
_A = f"{{{A}}}"

MARKER = "ljb-cbeta-loosen v2"

RNG_NS_URI = RNG  # relaxng structure ns (for building <name> patterns)
CBETA_NS_URI = "http://www.cbeta.org/ns/1.0"
TEI_NS_URI = "http://www.tei-c.org/ns/1.0"

# Kept in sync with sanmiaoSchemaMerge.ts (SANMIAO_DATE_PARTS @ v14).
SANMIAO_DATE_PARTS = (
    "dyn", "ruler", "era", "year", "month", "int", "day", "gz", "sexYear",
    "suffix", "lp", "nmdgz", "lp_filler", "filler", "season", "gy",
)
SANMIAO_RES_ATTRS = (
    ("dyn_id", "integer"), ("ruler_id", "integer"), ("era_id", "integer"),
    ("cal_stream", "integer"), ("ind_year", "integer"), ("year", "integer"),
    ("sex_year", "integer"), ("month", "integer"), ("intercalary", "integer"),
    ("day", "integer"), ("gz", "integer"), ("nmd_gz", "integer"),
    ("lp", "integer"), ("jdn", "decimal"), ("jdnEnd", "decimal"), ("dila_id", None),
)

# tei_model.phrase gets these; guarded by "does the target define exist".
NE_PHRASE_REFS = (
    "tei_persName", "tei_placeName", "tei_orgName", "tei_roleName",
    "tei_name", "tei_title", "tei_date", "ljb_nobleTitle",
)
# authority @ref/@key targets (per-define, guarded against an existing decl)
AUTHORITY_TARGETS = (
    "tei_title", "tei_author", "tei_byline", "tei_persName", "tei_placeName",
    "tei_orgName", "tei_roleName", "tei_name", "tei_date", "ljb_nobleTitle",
)


def _defines(root: etree._Element) -> dict[str, etree._Element]:
    return {d.get("name"): d for d in root.iter(f"{_R}define")}


def _attr_class_providers(defs: dict[str, etree._Element], attr: str) -> set[str]:
    """`att.*` defines that (transitively) contribute an attribute named ``attr``."""
    seed = {
        n
        for n, d in defs.items()
        if n.startswith("att.")
        and any(a.get("name") == attr for a in d.iter(f"{_R}attribute"))
    }
    changed = True
    while changed:
        changed = False
        for n, d in defs.items():
            if n in seed or not n.startswith("att."):
                continue
            if any(x.get("name") in seed for x in d.iter(f"{_R}ref")):
                seed.add(n)
                changed = True
    return seed


def _element_att_classes(define: etree._Element) -> set[str]:
    el = define.find(f"{_R}element")
    if el is None:
        return set()
    return {
        r.get("name")
        for r in el.findall(f"{_R}ref")
        if (r.get("name") or "").startswith("att.")
    }


def _el(tag: str, **attrs: str) -> etree._Element:
    e = etree.Element(f"{_R}{tag}")
    for k, v in attrs.items():
        e.set(k, v)
    return e


def _has_direct_attr(define: etree._Element, name: str) -> bool:
    el = define.find(f"{_R}element")
    scope = el if el is not None else define
    return any(a.get("name") == name for a in scope.iter(f"{_R}attribute"))


def _optional_attr(name: str, datatype: str | None = None) -> etree._Element:
    opt = _el("optional")
    attr = etree.SubElement(opt, f"{_R}attribute", name=name)
    if datatype:
        etree.SubElement(attr, f"{_R}data", type=datatype)
    else:
        etree.SubElement(attr, f"{_R}text")
    return opt


# --------------------------------------------------------------------------- #


def _add_authority_attrs(defs: dict[str, etree._Element]) -> int:
    prov = {a: _attr_class_providers(defs, a) for a in ("ref", "key")}
    n = 0
    for name in AUTHORITY_TARGETS:
        d = defs.get(name)
        if d is None:
            continue
        el = d.find(f"{_R}element")
        if el is None:
            continue
        att_classes = _element_att_classes(d)
        for attr in ("ref", "key"):
            if _has_direct_attr(d, attr) or (att_classes & prov[attr]):
                continue
            el.append(_optional_attr(attr))
            n += 1
    return n


def _expand_model_phrase(defs: dict[str, etree._Element]) -> int:
    d = defs.get("tei_model.phrase")
    if d is None:
        return 0
    choice = d.find(f"{_R}choice")
    if choice is None:
        return 0
    present = {r.get("name") for r in choice.findall(f"{_R}ref")}
    n = 0
    for ref in NE_PHRASE_REFS:
        if ref in present:
            continue
        if ref.startswith("tei_") and ref not in defs:
            continue
        choice.append(_el("ref", name=ref))
        n += 1
    return n


def _extend_date(defs: dict[str, etree._Element]) -> int:
    d = defs.get("tei_date")
    if d is None:
        return 0
    el = d.find(f"{_R}element")
    if el is None:
        return 0
    n = 0
    inner_choice = el.find(f"{_R}zeroOrMore/{_R}choice")
    if inner_choice is not None and not any(
        r.get("name") == "ljb_sanmiao_date_parts" for r in inner_choice.findall(f"{_R}ref")
    ):
        inner_choice.append(_el("ref", name="ljb_sanmiao_date_parts"))
        n += 1
    if not any(r.get("name") == "ljb_sanmiao_att_resolution" for r in el.findall(f"{_R}ref")):
        el.append(_el("ref", name="ljb_sanmiao_att_resolution"))
        n += 1
    return n


def _append_ljb_defines(root: etree._Element, defs: dict[str, etree._Element]) -> None:
    if "ljb_nobleTitle" not in defs:
        d = _el("define", name="ljb_nobleTitle")
        el = etree.SubElement(d, f"{_R}element", name="nobleTitle")
        doc = etree.SubElement(el, f"{_A}documentation")
        doc.text = "Grognard: fief/place + rank grouping (grognard-tei-extensions.md)."
        one = etree.SubElement(el, f"{_R}oneOrMore")
        ch = etree.SubElement(one, f"{_R}choice")
        etree.SubElement(ch, f"{_R}text")
        for ref in ("tei_model.global", "tei_placeName", "tei_roleName", "tei_persName"):
            if ref in defs or not ref.startswith("tei_"):
                etree.SubElement(ch, f"{_R}ref", name=ref)
        etree.SubElement(el, f"{_R}ref", name="att.global.attributes")
        el.append(_optional_attr("ref"))
        el.append(_optional_attr("key"))
        root.append(d)

    for part in SANMIAO_DATE_PARTS:
        name = f"ljb_sanmiao_{part}"
        if name in defs:
            continue
        d = _el("define", name=name)
        el = etree.SubElement(d, f"{_R}element", name=part)
        zom = etree.SubElement(el, f"{_R}zeroOrMore")
        ch = etree.SubElement(zom, f"{_R}choice")
        etree.SubElement(ch, f"{_R}text")
        etree.SubElement(ch, f"{_R}ref", name="tei_model.global")
        etree.SubElement(el, f"{_R}ref", name="att.global.attributes")
        root.append(d)

    if "ljb_sanmiao_date_parts" not in defs:
        d = _el("define", name="ljb_sanmiao_date_parts")
        ch = etree.SubElement(d, f"{_R}choice")
        for part in SANMIAO_DATE_PARTS:
            etree.SubElement(ch, f"{_R}ref", name=f"ljb_sanmiao_{part}")
        root.append(d)

    if "ljb_sanmiao_att_resolution" not in defs:
        d = _el("define", name="ljb_sanmiao_att_resolution")
        for attr, dt in SANMIAO_RES_ATTRS:
            d.append(_optional_attr(attr, dt))
        root.append(d)


def _dual_namespace_div(defs: dict[str, etree._Element]) -> int:
    """`tei_div` element matches both `<cb:div>` (ns1) and TEI-namespace `<div>`.

    Non-CBETA importers emit plain `<div type="…">`; CBETA binds `model.divLike`
    to `<cb:div>` only, so their output is rejected in `<body>`. Widening the one
    `tei_div` define reaches every division context (nested divs, front/back).
    """
    d = defs.get("tei_div")
    if d is None:
        return 0
    el = d.find(f"{_R}element")
    if el is None:
        return 0
    # Already dual? (name= attribute dropped in favour of a <choice> of <name>s)
    if el.get("name") is None and el.find(f"{_R}choice/{_R}name") is not None:
        return 0
    del el.attrib["name"]
    choice = etree.Element(f"{_R}choice")
    for ns in (CBETA_NS_URI, TEI_NS_URI):
        name = etree.SubElement(choice, f"{_R}name")
        name.set("ns", ns)
        name.text = "div"
    el.insert(0, choice)
    return 1


def _widen_creation(defs: dict[str, etree._Element]) -> int:
    """`<creation>` content: `macro.phraseSeq.limited` → `macro.phraseSeq`.

    The limited sequence excludes `model.phrase` (so `<date>` / `<origDate>` /
    names are rejected); the corpus importers all record composition dynasty /
    author dates there.
    """
    d = defs.get("tei_creation")
    if d is None:
        return 0
    el = d.find(f"{_R}element")
    if el is None:
        return 0
    changed = 0
    for ref in el.findall(f"{_R}ref"):
        if ref.get("name") == "tei_macro.phraseSeq.limited":
            ref.set("name", "tei_macro.phraseSeq")
            changed = 1
    return changed


def _add_role_attr(defs: dict[str, etree._Element]) -> int:
    """Optional `@role` on `<author>` / `<editor>` (CBETA drops `att.naming`).

    The corpus importers carry a responsibility function ("editor", "translator",
    "commentator", …) on the bibliographic name; stock TEI allows it via
    `att.naming`, CBETA's flattened `tei_author` / `tei_editor` do not.
    """
    n = 0
    for name in ("tei_author", "tei_editor"):
        d = defs.get(name)
        if d is None:
            continue
        el = d.find(f"{_R}element")
        if el is None or _has_direct_attr(d, "role"):
            continue
        el.append(_optional_attr("role"))
        n += 1
    return n


def _optional_keywords_scheme(defs: dict[str, etree._Element]) -> int:
    """`@scheme` on `<keywords>` made optional (CBETA marks it required)."""
    d = defs.get("tei_keywords")
    if d is None:
        return 0
    el = d.find(f"{_R}element")
    if el is None:
        return 0
    for attr in el.findall(f"{_R}attribute"):
        if attr.get("name") != "scheme":
            continue
        parent = attr.getparent()
        if parent.tag == f"{_R}optional":
            return 0
        idx = list(el).index(attr)
        opt = etree.Element(f"{_R}optional")
        el.remove(attr)
        opt.append(attr)
        el.insert(idx, opt)
        return 1
    return 0


def loosen_rng(text: str) -> str:
    if MARKER in text:
        return text  # already at this version — idempotent

    root = etree.fromstring(text.encode("utf-8"))

    defs = _defines(root)
    report = {
        "authority_attrs": _add_authority_attrs(defs),
        "phrase_refs": _expand_model_phrase(defs),
        "date_extended": _extend_date(defs),
        "dual_ns_div": _dual_namespace_div(defs),
        "creation_widened": _widen_creation(defs),
        "keywords_scheme_optional": _optional_keywords_scheme(defs),
        "role_attr": _add_role_attr(defs),
    }
    _append_ljb_defines(root, defs)

    # Replace any prior loosen note rather than stacking one per run.
    # (Also matches the pre-rename "LJB tagging loosenings" note for a clean
    # one-time transition when cbeta_p5.rng is regenerated after the rename.)
    for node in root.findall(f"{_A}documentation"):
        if node.text and (
            "Grognard tagging loosenings" in node.text
            or "LJB tagging loosenings" in node.text
        ):
            root.remove(node)
    doc = etree.Element(f"{_A}documentation")
    doc.text = (
        f"Grognard: CBETA P5 + Grognard tagging loosenings ({MARKER}) — "
        f"{report}"
    )
    root.insert(0, doc)

    out = etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
    sys.stderr.write(f"[loosen_schema] rng: {report}\n")
    return out


def loosen_sch(text: str) -> str:
    # CBETA's Schematron only requires @spanTo on addSpan/damageSpan/delSpan.
    sys.stderr.write("[loosen_schema] sch: no rule affects inserted markup — passthrough\n")
    return text


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 4):
        sys.stderr.write(__doc__ or "")
        return 2
    in_rng, out_rng = Path(argv[0]), Path(argv[1])
    Path(out_rng).write_text(loosen_rng(in_rng.read_text("utf-8")), "utf-8")
    if len(argv) == 4:
        in_sch, out_sch = Path(argv[2]), Path(argv[3])
        Path(out_sch).write_text(loosen_sch(in_sch.read_text("utf-8")), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
