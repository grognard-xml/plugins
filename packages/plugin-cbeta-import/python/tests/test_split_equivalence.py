"""The splitting helpers were rewritten to be linear instead of quadratic (a 100-juan work split
by section took over nine minutes and hit the host's 300 s limit). These tests check that the
new code gives exactly what the original, slower code gave, on randomly generated inputs.

The ``_reference_*`` functions below are the original implementations, kept only here."""

import copy
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree

from cbeta_import import juan_split, mulu_split
from cbeta_import.juan_split import JuanSlice, _drop, _ids_in, _refs_an_id

TEI = "http://www.tei-c.org/ns/1.0"
CB = "http://www.cbeta.org/ns/1.0"
T = f"{{{TEI}}}"
XID = "{http://www.w3.org/XML/1998/namespace}id"


# ---- original implementations ------------------------------------------------------------


def _reference_attach_apparatus(slices, back):
    if back is None:
        return
    for sl in slices:
        juan_ids = _ids_in(sl.elements)
        if not juan_ids:
            continue
        clone = copy.deepcopy(back)
        kept = 0
        for entry in list(clone.iter(f"{T}app", f"{T}note")):
            parent = entry.getparent()
            if parent is None or parent.tag in (f"{T}app",):
                continue
            if _refs_an_id(entry, juan_ids):
                kept += 1
            else:
                _drop(entry)
        if kept:
            sl.apparatus = [clone]


def _reference_rupture(pivot):
    parent = pivot.getparent()
    if parent is None or parent.tag == f"{T}body":
        return
    grand = parent.getparent()
    if grand is None:
        return
    children = list(parent)
    try:
        pivot_i = children.index(pivot)
    except ValueError:
        return
    suffix = children[pivot_i:]
    for el in suffix:
        parent.remove(el)
    insert_pos = list(grand).index(parent) + 1
    for offset, el in enumerate(suffix):
        grand.insert(insert_pos + offset, el)
    if len(parent) == 0 and not (parent.text or "").strip() and not (parent.tail or "").strip():
        grand.remove(parent)


def _reference_promote(body, is_marker):
    promoted = 0
    while True:
        nested = [m for m in body.iter() if is_marker(m) and m.getparent() is not body]
        if not nested:
            break
        _reference_rupture(nested[0])
        promoted += 1
    return promoted


# ---- random inputs -------------------------------------------------------------------------


def _random_back(rng, n_ids):
    back = etree.Element(f"{T}back", nsmap={None: TEI, "cb": CB})
    back.text = "\n "
    div = etree.SubElement(back, f"{{{CB}}}div", type="apparatus")
    div.text = "\n  "

    def pointer(el):
        for attr in rng.sample(["from", "to", "target"], rng.randint(0, 2)):
            el.set(attr, " ".join(f"#id{rng.randrange(n_ids)}" for _ in range(rng.randint(1, 2))))

    for _ in range(rng.randint(8, 40)):
        kind = rng.choice(["app", "note", "app", "comment"])
        if kind == "comment":
            div.append(etree.Comment("c"))
        else:
            el = etree.SubElement(div, f"{T}{kind}")
            pointer(el)
            if kind == "app":
                lem = etree.SubElement(el, f"{T}lem")
                lem.text = "x"
                for _ in range(rng.randint(0, 2)):
                    rdg = etree.SubElement(el, f"{T}rdg")
                    rdg.text = "y"
                    if rng.random() < 0.4:  # a note nested below an app's child
                        inner = etree.SubElement(rdg, f"{T}note")
                        pointer(inner)
                    if rng.random() < 0.3:  # a note that is a direct child of the app
                        inner = etree.SubElement(el, f"{T}note")
                        pointer(inner)
            elif rng.random() < 0.3:
                inner = etree.SubElement(el, f"{T}note")
                pointer(inner)
        div[-1].tail = rng.choice([None, "\n  ", "\n", " "])
    return back


def _random_slices(rng, n_ids, n_slices):
    out = []
    for k in range(n_slices):
        els = []
        for _ in range(rng.randint(0, 4)):
            p = etree.Element(f"{T}p")
            for _ in range(rng.randint(0, 3)):
                a = etree.SubElement(p, f"{T}anchor")
                a.set(XID, f"id{rng.randrange(n_ids)}")
            els.append(p)
        out.append(JuanSlice(n=str(k + 1), elements=els))
    return out


def _ser(slices):
    return [
        "".join(etree.tostring(a, encoding="unicode") for a in sl.apparatus) for sl in slices
    ]


class AttachApparatusEquivalenceTest(unittest.TestCase):
    def test_same_apparatus_as_the_original_on_random_inputs(self):
        for seed in range(60):
            rng = random.Random(seed)
            n_ids = rng.randint(3, 25)
            back = _random_back(rng, n_ids)
            slices_a = _random_slices(random.Random(seed + 1000), n_ids, rng.randint(1, 12))
            slices_b = copy.deepcopy(slices_a)
            _reference_attach_apparatus(slices_a, copy.deepcopy(back))
            juan_split.attach_apparatus(slices_b, copy.deepcopy(back))
            self.assertEqual(_ser(slices_a), _ser(slices_b), f"seed {seed}")
            self.assertEqual(
                [bool(s.apparatus) for s in slices_a], [bool(s.apparatus) for s in slices_b]
            )

    def test_back_is_not_modified(self):
        rng = random.Random(7)
        back = _random_back(rng, 10)
        before = etree.tostring(back)
        juan_split.attach_apparatus(_random_slices(rng, 10, 5), back)
        self.assertEqual(etree.tostring(back), before)


def _random_body(rng):
    """A ``<body>`` with section markers nested at random depths inside divs."""
    body = etree.Element(f"{T}body", nsmap={None: TEI, "cb": CB})

    def fill(parent, depth):
        for _ in range(rng.randint(1, 5)):
            r = rng.random()
            if r < 0.3:
                m = etree.SubElement(parent, f"{{{CB}}}mulu")
                m.text = "t" + str(rng.randrange(100))
                m.set("level", "1")
            elif r < 0.45:
                etree.SubElement(parent, f"{T}milestone", unit="juan", n=str(rng.randrange(9)))
            elif r < 0.7 and depth < 4:
                div = etree.SubElement(parent, f"{T}div")
                div.text = rng.choice([None, " ", "text"])
                fill(div, depth + 1)
                div.tail = rng.choice([None, "\n", "tail"])
            else:
                p = etree.SubElement(parent, f"{T}p")
                p.text = "p" + str(rng.randrange(100))
                p.tail = rng.choice([None, "\n"])

    fill(body, 0)
    return body


class PromoteEquivalenceTest(unittest.TestCase):
    def test_promote_milestones_matches_the_rescanning_loop(self):
        for seed in range(120):
            body_a = _random_body(random.Random(seed))
            body_b = copy.deepcopy(body_a)
            n_a = _reference_promote(body_a, juan_split._is_juan_milestone)
            n_b = juan_split.promote_juan_milestones_to_body(body_b)
            self.assertEqual(etree.tostring(body_a), etree.tostring(body_b), f"seed {seed}")
            self.assertEqual(n_a, n_b, f"seed {seed}")

    def test_promote_mulu_matches_the_rescanning_loop(self):
        for seed in range(120):
            body_a = _random_body(random.Random(seed + 500))
            body_b = copy.deepcopy(body_a)
            n_a = _reference_promote(body_a, mulu_split._is_section_mulu)
            n_b = mulu_split._promote_mulu_markers_to_body(body_b)
            self.assertEqual(etree.tostring(body_a), etree.tostring(body_b), f"seed {seed}")
            self.assertEqual(n_a, n_b, f"seed {seed}")


class ScaleTest(unittest.TestCase):
    def test_many_sections_finish_quickly(self):
        """Thousands of nested section markers and thousands of apparatus entries (the shape of
        T2128) used to take minutes. The bound is generous; the old code missed it by orders of
        magnitude."""
        import time

        root = etree.Element(f"{T}TEI", nsmap={None: TEI, "cb": CB})
        body = etree.SubElement(etree.SubElement(root, f"{T}text"), f"{T}body")
        for j in range(40):
            div = etree.SubElement(body, f"{T}div")
            for i in range(150):
                m = etree.SubElement(div, f"{{{CB}}}mulu")
                m.text = f"s{j}-{i}"
                m.set("level", "1")
                p = etree.SubElement(div, f"{T}p")
                p.text = "text"
                a = etree.SubElement(p, f"{T}anchor")
                a.set(XID, f"id{j}_{i}")
        back = etree.Element(f"{T}back", nsmap={None: TEI})
        for j in range(40):
            for i in range(150):
                app = etree.SubElement(back, f"{T}app", target=f"#id{j}_{i}")
                etree.SubElement(app, f"{T}lem").text = "x"
        t0 = time.time()
        slices = mulu_split.split_body_into_mulu(root)
        juan_split.attach_apparatus(slices, back)
        elapsed = time.time() - t0
        self.assertGreaterEqual(len(slices), 5000)
        self.assertLess(elapsed, 30, f"took {elapsed:.1f}s")
        self.assertTrue(all(s.apparatus for s in slices))
