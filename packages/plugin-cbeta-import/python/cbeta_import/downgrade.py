"""CBETA-only markup → plain TEI-ALL (leaf-writer/docs/cbeta-import-planning.md §5.1–5.6).

``phonetic_glosses`` runs for **every** import (§1, §5.2 — we never keep
``cb:yin``/``cb:sg``). The rest run only when importing into a non-CBETA
project (``cross_family``); a CBETA-family project keeps ``cb:tt`` / ``cb:div``
/ ``cb:juan`` verbatim.
"""

from __future__ import annotations

from lxml import etree

from cbeta_import.constants import CB_NS, TEI_NS

_CB = f"{{{CB_NS}}}"
_TEI = f"{{{TEI_NS}}}"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# cb:mulu / cb:div @type (some are CJK) → a latin TEI div @type
_TYPE_MAP = {
    "品": "pin", "分": "fen", "經": "jing", "序": "xu", "會": "hui", "地": "di",
    "處": "chu", "論": "treatise", "跋": "colophon", "科判": "kepan",
    "附文": "appendix", "其他": "other", "廣釋": "commentary", "續補": "supplement",
}


def _norm_type(t: str) -> str:
    return _TYPE_MAP.get(t, t)


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _splice(el: etree._Element, text_prefix: str, elems: list[etree._Element]) -> None:
    """Replace ``el`` in its parent with ``text_prefix`` then ``elems``; keep ``el.tail``."""
    parent = el.getparent()
    if parent is None:
        return
    idx = parent.index(el)
    tail = el.tail or ""
    parent.remove(el)
    if elems:
        for j, e in enumerate(elems):
            parent.insert(idx + j, e)
        elems[-1].tail = tail
        prev = elems[0].getprevious()
        if text_prefix:
            if prev is not None:
                prev.tail = (prev.tail or "") + text_prefix
            else:
                parent.text = (parent.text or "") + text_prefix
    else:
        combined = text_prefix + tail
        prev = parent[idx - 1] if idx > 0 else None
        if prev is not None:
            prev.tail = (prev.tail or "") + combined
        else:
            parent.text = (parent.text or "") + combined


def _gloss_note(text: str, *, fanqie: bool) -> etree._Element:
    note = etree.Element(f"{_TEI}note")
    note.set("type", "gloss")
    if fanqie:
        note.set("subtype", "fanqie")
    note.text = text.strip()
    return note


# --------------------------------------------------------------------------- #
# §5.2 — phonetic gloss (unconditional)


def phonetic_glosses(body: etree._Element) -> int:
    n = 0
    # cb:fan first — it fully contains its own cb:zi + reading
    for el in list(body.iter(f"{_CB}fan")):
        zi = "".join(
            "".join(z.itertext()) for z in el.findall(f"{_CB}zi")
        ) or (el.text or "")
        readings: list[etree._Element] = []
        for sg in el.findall(f".//{_CB}sg"):
            readings.append(_gloss_note("".join(sg.itertext()), fanqie=True))
        for note in el.findall(f".//{_TEI}note"):
            readings.append(_gloss_note("".join(note.itertext()), fanqie=True))
        _splice(el, zi, readings)
        n += 1
    # standalone cb:yin
    for el in list(body.iter(f"{_CB}yin")):
        zi_parts = [("".join(z.itertext())) for z in el.findall(f"{_CB}zi")]
        zi = "".join(zi_parts) or (el.text or "")
        readings = []
        for sg in el.findall(f"{_CB}sg"):
            readings.append(
                _gloss_note("".join(sg.itertext()), fanqie=sg.get("type") == "fangie")
            )
        if not readings:
            for note in el.findall(f".//{_TEI}note"):
                readings.append(_gloss_note("".join(note.itertext()), fanqie=False))
        _splice(el, zi, readings)
        n += 1
    return n


# --------------------------------------------------------------------------- #
# §5.1 — bilingual parallel segments


def translation_terms(body: etree._Element) -> int:
    n = 0
    for el in list(body.iter(f"{_CB}tt", f"{_CB}t")):
        was = _local(el.tag)
        el.tag = f"{_TEI}seg"
        t = el.attrib.pop("type", None)
        el.set("subtype", f"cb:{was}" + (f":{t}" if t else ""))
        n += 1
    return n


# --------------------------------------------------------------------------- #
# §5.4 — juan head/tail blocks


def juan_blocks(body: etree._Element) -> int:
    n = 0
    for el in list(body.iter(f"{_CB}juan")):
        fun = el.get("fun")
        if fun == "close":
            jhead = el.find(f"{_CB}jhead")
            trailer = etree.Element(f"{_TEI}trailer")
            trailer.text = "".join(jhead.itertext()).strip() if jhead is not None else ""
            _splice(el, "", [trailer])
        else:  # open (or unmarked): the title is already on the juan <div>
            _splice(el, "", [])
        n += 1
    return n


# --------------------------------------------------------------------------- #
# §5.3 — cb:div → div, and cb:mulu → <div> nesting / breadcrumb


def _content_mulu(m: etree._Element) -> bool:
    return bool((m.text and m.text.strip()) or m.get("label"))


def _consume_mulu_into_structure(k: etree._Element, report: dict[str, int]) -> None:
    """Turn one content ``cb:mulu`` into a ``<head>`` (or drop if redundant)."""
    parent = k.getparent()
    label = (k.text or "").strip() or (k.get("label") or "").strip()
    nxt = k.getnext()
    if nxt is not None and _local(nxt.tag) == "head":
        if label and not (nxt.text or "").strip():
            nxt.text = label
        _splice(k, "", [])
        report["mulu_consumed_into_head"] += 1
        return
    if parent is not None and parent.tag == f"{_TEI}div":
        existing = parent.find(f"{_TEI}head")
        if existing is not None:
            if label and not (existing.text or "").strip():
                existing.text = label
            _splice(k, "", [])
            report["mulu_consumed_into_head"] += 1
            return
        head = etree.Element(f"{_TEI}head")
        parent.insert(parent.index(k), head)
        if label:
            head.text = label
        t = k.get("type")
        if t and t != "卷" and not parent.get("type"):
            parent.set("type", _norm_type(t))
        _splice(k, "", [])
        report["mulu_consumed_into_head"] += 1
        return
    k.tag = f"{_TEI}milestone"
    k.set("unit", "mulu")
    if label:
        k.set("ana", f"cbeta-mulu-label:{label}")
    k.text = None
    report["mulu_to_marker"] += 1


def _normalize_place_attrs(body: etree._Element) -> int:
    """TEI-ALL allows ``@place`` on ``<note>`` but not on ``<p>`` / ``<seg>``."""
    n = 0
    for el in body.iter():
        if not isinstance(el.tag, str) or "place" not in el.attrib:
            continue
        loc = _local(el.tag)
        if loc not in ("p", "seg"):
            continue
        place = el.attrib.pop("place")
        rend = el.get("rend")
        el.set("rend", f"{rend} {place}".strip() if rend else place)
        n += 1
    return n


def mulu_and_divs(body: etree._Element) -> dict[str, int]:
    report = {
        "cb_div_renamed": 0,
        "mulu_dropped": 0,
        "mulu_to_div": 0,
        "mulu_to_marker": 0,
        "mulu_consumed_into_head": 0,
    }

    for el in list(body.iter(f"{_CB}div")):
        el.tag = f"{_TEI}div"
        t = el.get("type")
        if t:
            el.set("type", _norm_type(t))
        report["cb_div_renamed"] += 1

    for k in list(body.iter(f"{_CB}mulu")):
        if k.get("type") == "卷" and not _content_mulu(k):
            k.tag = f"{_TEI}milestone"
            k.set("unit", "mulu")
            report["mulu_to_marker"] += 1

    for k in list(body.iter(f"{_CB}mulu")):
        if k.get("type") != "卷" and not _content_mulu(k):
            _splice(k, "", [])
            report["mulu_dropped"] += 1

    kids = [k for k in body if isinstance(k.tag, str)]
    has_div = any(_local(k.tag) == "div" for k in kids)
    content_mulus = [
        k for k in kids if k.tag == f"{_CB}mulu" and k.get("type") != "卷" and _content_mulu(k)
    ]

    if content_mulus and not has_div:
        ordered = list(kids)
        for k in ordered:
            body.remove(k)
        stack: list[tuple[int, etree._Element]] = [(0, body)]
        for k in ordered:
            if k.tag == f"{_CB}mulu":
                if k.get("type") == "卷" or not _content_mulu(k):
                    continue  # 卷 handled by the split; empty already dropped
                lvl = int(k.get("level") or 1)
                while len(stack) > 1 and stack[-1][0] >= lvl:
                    stack.pop()
                div = etree.SubElement(stack[-1][1], f"{_TEI}div")
                if k.get("type") and k.get("type") != "卷":
                    div.set("type", _norm_type(k.get("type")))
                if k.get("n"):
                    div.set("n", k.get("n"))
                div.set("ana", "cbeta-mulu")
                head_text = (k.text or "").strip() or k.get("label") or ""
                if head_text:
                    etree.SubElement(div, f"{_TEI}head").text = head_text
                stack.append((lvl, div))
                report["mulu_to_div"] += 1
            else:
                if k.tag == f"{_TEI}head":
                    div = stack[-1][1]
                    cur = div.find(f"{_TEI}head")
                    if cur is not None:
                        if not (cur.text or "").strip() and (k.text or "").strip():
                            cur.text = k.text
                        continue
                stack[-1][1].append(k)
        return report

    for k in list(body.iter(f"{_CB}mulu")):
        if k.get("type") == "卷" or not _content_mulu(k):
            continue
        _consume_mulu_into_structure(k, report)
    return report


# --------------------------------------------------------------------------- #
# §5.6 — cb:-namespace attributes + a few structural elements


def structural(body: etree._Element) -> int:
    n = 0
    for el in list(body.iter(f"{_CB}docNumber")):
        el.tag = f"{_TEI}label"
        el.set("type", "docNumber")
        n += 1
    for el in list(body.iter(f"{_CB}dialog")):
        el.tag = f"{_TEI}div"
        el.set("type", "dialog" if not el.get("type") else _norm_type(el.get("type")))
        n += 1

    rename = {
        f"{_CB}resp": "resp",
        f"{_CB}place": "place",
        f"{_CB}from": "from",
        f"{_CB}to": "to",
        f"{_CB}type": "ana",
        f"{_CB}line": "n",
    }
    drop = {
        f"{_CB}word-count",
        f"{_CB}provider",
        f"{_CB}behaviour",
        f"{_CB}cert",
        f"{_CB}id",
        f"{_CB}note_key",
    }
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            if attr in rename and rename[attr] not in el.attrib:
                el.set(rename[attr], el.attrib.pop(attr))
                n += 1
            elif attr in drop:
                del el.attrib[attr]
                n += 1
    return n


# --------------------------------------------------------------------------- #


def apply_cross_family(body: etree._Element) -> dict[str, int]:
    """All of §5.1, §5.3, §5.4, §5.6 (phonetic gloss §5.2 is applied separately)."""
    report = {"tt_to_seg": translation_terms(body), "juan_blocks": juan_blocks(body)}
    report.update(mulu_and_divs(body))
    report["cb_attrs_normalised"] = structural(body)
    report["place_attrs_normalised"] = _normalize_place_attrs(body)
    return report
