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
        if not readings:
            # real 一切經音義 shape: <cb:fan><cb:zi>字</cb:zi><cb:yin>某某反</cb:yin>
            # — the fanqie sits as bare text on <cb:yin> (no <cb:sg>, no <note>);
            # itertext drops any interrupting <lb/>, split() collapses its newline.
            for yin in el.findall(f"{_CB}yin"):
                txt = "".join("".join(yin.itertext()).split())
                if txt:
                    readings.append(_gloss_note(txt, fanqie=True))
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
            jhead = el.find(f"{_CB}jhead")
            if jhead is not None and any(c.tag == f"{_TEI}note" for c in jhead):
                # ...but a note in the juan heading (一切經音義 files the juan under a category
                # there: ``卷第一<note place="inline">大乘單本</note>``) would be lost with it.
                head = etree.Element(f"{_TEI}head", type="juan")
                head.text = jhead.text
                for child in list(jhead):
                    head.append(child)
                _splice(el, "", [head])
            else:
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
    """TEI-ALL allows ``@place`` on ``<note>`` but not on ``<p>`` / ``<seg>`` / ``<entry>``."""
    n = 0
    for el in body.iter():
        if not isinstance(el.tag, str) or "place" not in el.attrib:
            continue
        loc = _local(el.tag)
        if loc not in ("p", "seg", "entry"):
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
# dictionary entries: <cb:def> → <def>


def _inline_rend(rend: str | None) -> str | None:
    """``rend`` without the ``inline`` token (a ``<def>`` is inline by nature)."""
    toks = [tok for tok in (rend or "").split() if tok != "inline"]
    return " ".join(toks) or None


def dictionary_defs(body: etree._Element) -> int:
    """``<cb:def>`` (the definition of a dictionary ``<entry>``, e.g. 一切經音義) → TEI ``<def>``.

    ``cb:def`` is not part of TEI, so a project on the TEI-ALL schema does not know the element.
    TEI ``<def>`` takes phrase-level content only, so each ``<p>`` inside a ``cb:def`` becomes
    its own ``<def>`` (a ``cb:def`` with two paragraphs gives two ``<def>``s). Anything else inside
    (loose text, ``<lb/>``, ``<note>``, …) is kept, in order, inside the ``<def>`` it follows, or in
    a new one if there is none yet. Attributes of the ``<p>`` (``xml:id``, ``rend`` without
    ``inline``) move to its ``<def>``. Returns the number of ``<def>`` elements created.
    """
    created = 0
    for old in list(body.iter(f"{_CB}def")):
        parent = old.getparent()
        if parent is None:
            continue
        defs: list[etree._Element] = []

        def new_def() -> etree._Element:
            d = etree.Element(f"{_TEI}def")
            defs.append(d)
            return d

        if old.text and old.text.strip():
            new_def().text = old.text
        for child in list(old):
            if isinstance(child.tag, str) and child.tag == f"{_TEI}p":
                cur = new_def()
                for attr, value in child.attrib.items():
                    if attr == "rend":
                        value = _inline_rend(value)
                        if value is None:
                            continue
                    cur.set(attr, value)
                cur.text = child.text
                for grand in list(child):
                    cur.append(grand)
                if child.tail and child.tail.strip():  # loose text after the <p> stays with it
                    if len(cur):
                        cur[-1].tail = (cur[-1].tail or "") + child.tail
                    else:
                        cur.text = (cur.text or "") + child.tail
            else:
                cur = defs[-1] if defs else new_def()
                cur.append(child)  # anything else follows the <def> it comes after
        if not defs:
            new_def()
        defs[-1].tail = old.tail
        index = parent.index(old)
        parent.remove(old)
        for offset, d in enumerate(defs):
            parent.insert(index + offset, d)
        created += len(defs)
    return created


def remaining_cb_elements(body: etree._Element) -> dict[str, int]:
    """CBETA-namespace elements still present (the project schema will not know them)."""
    left: dict[str, int] = {}
    for el in body.iter():
        if isinstance(el.tag, str) and el.tag.startswith(_CB):
            name = _local(el.tag)
            left[name] = left.get(name, 0) + 1
    return left


# --------------------------------------------------------------------------- #


def apply_cross_family(body: etree._Element) -> dict[str, int]:
    """All of §5.1, §5.3, §5.4, §5.6 (phonetic gloss §5.2 is applied separately)."""
    report = {"tt_to_seg": translation_terms(body), "juan_blocks": juan_blocks(body)}
    report.update(mulu_and_divs(body))
    report["cb_attrs_normalised"] = structural(body)
    report["place_attrs_normalised"] = _normalize_place_attrs(body)
    report["defs_to_tei"] = dictionary_defs(body)
    for name, count in remaining_cb_elements(body).items():
        report[f"cb_left:{name}"] = count
    return report
