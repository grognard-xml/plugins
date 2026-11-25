#!/usr/bin/env python3
"""Mend a CBETA mulu-split import made before the gaiji and section-context fixes.

DRY RUN by default: reads the imported files and the CBETA source, reports what would change,
writes nothing. With ``--write-dir DIR`` the *changed* files are written there (same names) so
they can be diffed against the project and copied back by hand. Project files are never
modified by this script.

What it mends (all by string edits, so tagging done since import — ``<persName key=…>`` and
the rest — is left exactly as it is):

1. Gaiji.  A private-use code point in running text (CBETA's stand-in for a character Unicode
   lacks, shown as a tofu/hexagram) becomes ``<g ref="#CBnnnnn">網</g>`` (normalised form, else
   〓), and the file's header gets a ``<charDecl>`` entry for it.
2. Section context.  A joined head ``<head>正法念經 — 第一卷</head>`` becomes
   ``<head type="context" n="2">正法念經</head><head>第一卷</head>``, and every section also gets
   the headings still in force above it (the cited work's title), worked out from the source's
   ``cb:mulu`` ``@level`` hierarchy.
3. Juan opening.  ``<milestone unit="juan">`` … byline left at the end of the previous section's
   file moves to the start of the file of the section that follows it (only when nothing but
   the opening is there), and the source note gains ``(in CBETA 卷N)``.

Sections are matched to the source by their own title and their first ``<lb n>``; a file that
can't be matched confidently is reported and left alone.

    mend_imported_sections.py --source C056n1163.xml "…/imported/cbeta/一切經音義 C1163"
    mend_imported_sections.py --source C056n1163.xml DIR --write-dir /tmp/mended
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cbeta_import import gaiji  # noqa: E402
from cbeta_import.constants import CB_NS, DROP_ED, TEI_NS  # noqa: E402
from cbeta_import.mulu_split import _plain  # noqa: E402

_TEI = f"{{{TEI_NS}}}"
_CB = f"{{{CB_NS}}}"
SEP = " — "

_PUA_RE = re.compile("[-\U000f0000-\U0010fffd]")
_TEXT_RE = re.compile(r"(?<=>)[^<>]+")  # text between tags (never inside a tag or attribute)
_LB_RE = re.compile(r'<lb\b[^>]*?\bn="([^"]+)"')
_SECTION_HEAD_RE = re.compile(r'(<div type="section" n="\d+">)<head>([^<]*)</head>')
_OPENER_RE = re.compile(r'<milestone\b[^>]*\bunit="juan"[^>]*/>')
_CONTENT_RE = re.compile(r"<(?:entry|p|list|item|lg|l|ab)\b")


@dataclass
class Mulu:
    lb: int  # index of the nearest preceding <lb> in the source
    level: int
    title: str
    ancestors: list[tuple[int, str]]
    juan: str


@dataclass
class Source:
    lb_index: dict[str, int]
    mulu: list[Mulu]
    pua_to_info: dict[str, gaiji.GaijiInfo]


def _level(el: etree._Element) -> int:
    try:
        return max(1, int(el.get("level") or 1))
    except ValueError:
        return 1


def load_source(paths: list[Path]) -> Source:
    """One or more source files read as a single document (a work can span volumes)."""
    lb_index: dict[str, int] = {}
    mulu: list[Mulu] = []
    pua_to_info: dict[str, gaiji.GaijiInfo] = {}
    stack: list[tuple[int, str]] = []
    juan = pending_juan = ""
    cur = -1
    for path in paths:
        tree = etree.parse(str(path), etree.XMLParser(resolve_entities=False))
        root = tree.getroot()
        char_map = gaiji.load_char_decl(tree)
        char_info = gaiji.load_char_info(tree)
        body = root.find(f".//{_TEI}body")
        for el in body.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag == f"{_TEI}lb":
                if el.get("ed") in DROP_ED or not el.get("n"):
                    continue
                cur += 1
                lb_index.setdefault(el.get("n"), cur)
                if pending_juan:
                    juan, pending_juan = pending_juan, ""
            elif el.tag == f"{_TEI}milestone" and el.get("unit") == "juan":
                pending_juan = el.get("n") or ""
            elif el.tag == f"{_CB}mulu" and el.get("type") != "卷":
                title = _plain(el, char_map, char_info) or (el.get("label") or "").strip()
                if not title:
                    continue
                level = _level(el)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                mulu.append(Mulu(max(cur, 0), level, title, list(stack), juan))
                stack.append((level, title))
        for char in root.iter(f"{_TEI}char"):
            info = char_info.get(char.get("{http://www.w3.org/XML/1998/namespace}id", ""))
            m = re.fullmatch(r"U\+([0-9A-Fa-f]{4,6})", info.pua) if info and info.pua else None
            if m:
                pua_to_info[chr(int(m.group(1), 16))] = info
    return Source(lb_index, mulu, pua_to_info)


def _first_lb(text: str) -> str | None:
    for m in _LB_RE.finditer(text):
        tag = m.group(0)
        ed = re.search(r'\bed="([^"]+)"', text[m.start() : m.start() + 120])
        if ed and ed.group(1) in DROP_ED:
            continue
        return m.group(1)
    return None


def match_mulu(
    src: Source, keys: list[str], first_lb: str | None, cursor: int, window: int = 4, ahead: int = 12
) -> Mulu | None:
    """The source mulu for a section: by title + nearest line, else the next one in order."""
    if first_lb in src.lb_index:
        at = src.lb_index[first_lb]
        best, best_d = None, window + 1
        for m in src.mulu:
            if m.title in keys and abs(m.lb - at) < best_d:
                best, best_d = m, abs(m.lb - at)
        if best is not None:
            return best
    for m in src.mulu[cursor + 1 : cursor + 1 + ahead]:  # sections come in source order
        if m.title in keys:
            return m
    return None


def _g_markup(info: gaiji.GaijiInfo) -> str:
    shown = info.normalized or gaiji.PLACEHOLDER
    return f'<g ref="#{info.id}">{shown}</g>'


def _char_decl(infos: list[gaiji.GaijiInfo]) -> str:
    def prop(name: str, value: str) -> str:
        return (
            f"\n        <charProp><localName>{name}</localName><value>{value}</value></charProp>"
            if value
            else ""
        )

    rows = [
        f'      <char xml:id="{i.id}">{prop("composition", i.composition)}'
        f'{prop("normalized form", i.normalized)}'
        + (f'\n        <mapping type="PUA">{i.pua}</mapping>' if i.pua else "")
        + "\n      </char>"
        for i in infos
    ]
    return "  <encodingDesc>\n    <charDecl>\n" + "\n".join(rows) + "\n    </charDecl>\n  </encodingDesc>\n"


def mend_gaiji(text: str, src: Source, report: Counter, unknown: Counter) -> str:
    used: dict[str, gaiji.GaijiInfo] = {}

    def fix(m: re.Match[str]) -> str:
        def one(c: re.Match[str]) -> str:
            info = src.pua_to_info.get(c.group(0))
            if info is None:
                unknown[f"U+{ord(c.group(0)):X}"] += 1
                return c.group(0)
            used[info.id] = info
            report["gaiji_chars"] += 1
            return _g_markup(info)

        return _PUA_RE.sub(one, m.group(0))

    out = _TEXT_RE.sub(fix, text)
    if not used:
        return text
    report["gaiji_files"] += 1
    decl = _char_decl([used[k] for k in sorted(used)])
    if "<charDecl>" in out:
        rows = decl[decl.index("<char ") : decl.rindex("</char>") + len("</char>")]
        return out.replace("</charDecl>", rows + "\n    </charDecl>", 1)
    return re.sub(r"(\s*)(<profileDesc>|<revisionDesc>)", lambda m: "\n" + decl + m.group(1) + m.group(2), out, count=1)


def _split_head(raw: str) -> tuple[list[str], str]:
    parts = [p.strip() for p in raw.split(SEP)]
    return parts[:-1], parts[-1]


def _plain_key(s: str, src: Source) -> str:
    """Head text with CBETA private-use characters read as their normalised form."""
    return _PUA_RE.sub(lambda c: (src.pua_to_info[c.group(0)].normalized or gaiji.PLACEHOLDER) if c.group(0) in src.pua_to_info else c.group(0), re.sub(r"<[^>]+>", "", s))


_DUP_HEAD_RE = re.compile(r'<head(?: xmlns="[^"]*")?>(.*?)</head>', re.S)


def mend_heads(
    text: str, src: Source, state: dict, report: Counter, notes: list[str], name: str
) -> tuple[str, Mulu | None]:
    m = _SECTION_HEAD_RE.search(text)
    if not m:
        report["heads_no_plain_head"] += 1
        return text, None
    _folded, leaf = _split_head(m.group(2))
    # Old layout: a generated <head> (the mulu title, cut at its first <g> when it had one) and,
    # when the source's own <head> said more than the mulu, that head right after it. The new
    # layout keeps the source head alone, so the generated one goes.
    dup = _DUP_HEAD_RE.match(text, m.end())
    keys = [_plain_key(leaf, src)]
    if dup:
        keys.append(_plain_key(dup.group(1), src))
    mu = match_mulu(src, keys, _first_lb(text), state["cursor"])
    body_rest = text[dup.end() if dup else m.end() : text.find("</div>", m.end())]
    if mu is None:
        if not _CONTENT_RE.search(body_rest) and "<lb" not in body_rest:
            report["head_only_files"] += 1  # the new layout makes these context, not files
        else:
            report["heads_unmatched"] += 1
            notes.append(f"unmatched: {name}  head={m.group(2)!r}")
        return text, None
    state["cursor"] = src.mulu.index(mu)
    heads = "".join(f'<head type="context" n="{lv}">{t}</head>' for lv, t in mu.ancestors)
    if dup:
        full = _plain_key(dup.group(1), src)
        if full == mu.title and len(full) > len(_plain_key(leaf, src)) and full.startswith(_plain_key(leaf, src)):
            report["truncated_titles_repaired"] += 1
        report["generated_head_replaced_by_source_head"] += 1
        leaf_markup, end = dup.group(0), dup.end()
    else:
        leaf_markup, end = f"<head>{leaf}</head>", m.end()
    new = f"{m.group(1)}{heads}{leaf_markup}"
    if new == text[m.start() : end]:
        report["heads_already_ok"] += 1
        return text, mu
    report["heads_files_changed"] += 1
    report["context_heads_added"] += len(mu.ancestors)
    if SEP in m.group(2):
        report["joined_heads_split"] += 1
    return text[: m.start()] + new + text[end:], mu


def take_opener(text: str) -> tuple[str, str]:
    """Cut a trailing juan opening (nothing but the opening after the milestone) out of a file."""
    end = text.rfind("</div>")
    if end < 0:
        return text, ""
    ms = list(_OPENER_RE.finditer(text[:end]))
    if not ms:
        return text, ""
    start = ms[-1].start()
    seg = text[start:end]
    if _CONTENT_RE.search(seg):
        return text, ""  # the juan opens mid-section: leave it
    return text[:start] + text[end:], seg


def run(source: list[Path], folder: Path, write_dir: Path | None) -> int:
    src = load_source(source)
    files = sorted(folder.glob("*.xml"), key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p.stem)])
    report: Counter = Counter()
    unknown: Counter = Counter()
    notes: list[str] = []
    texts = {f: f.read_text("utf-8") for f in files}
    mended: dict[Path, str] = {}
    mulus: dict[Path, Mulu | None] = {}

    state = {"cursor": -1}
    for f in files:
        t = texts[f]
        t = mend_gaiji(t, src, report, unknown)
        t, mu = mend_heads(t, src, state, report, notes, f.name)
        mended[f], mulus[f] = t, mu

    # juan openings: move from the end of one file to the start of the next
    for prev, nxt in zip(files, files[1:]):
        t_prev, seg = take_opener(mended[prev])
        if not seg:
            continue
        m = _SECTION_HEAD_RE.search(mended[nxt]) or re.search(r'<div type="section" n="\d+">', mended[nxt])
        if not m:
            continue
        at = m.start() + len(re.match(r'<div type="section" n="\d+">', mended[nxt][m.start() :]).group(0))
        mended[prev] = t_prev
        mended[nxt] = mended[nxt][:at] + seg + mended[nxt][at:]
        report["juan_openings_moved"] += 1

    for f in files:
        mu = mulus[f]
        if mu and mu.juan:
            t = re.sub(r"(CBETA work \S+ section (\d+))(?! \(in CBETA)", rf"\1 (in CBETA 卷{mu.juan})", mended[f], count=1)
            if t != mended[f]:
                report["source_notes_with_juan"] += 1
                mended[f] = t

    changed = [f for f in files if mended[f] != texts[f]]
    print(f"{folder}\n  source: {', '.join(str(x) for x in source)}\n  {len(files)} files, {len(changed)} would change\n")
    for key in sorted(report):
        print(f"  {key:28} {report[key]}")
    if unknown:
        print(f"\n  private-use characters with no CBETA declaration: {dict(unknown.most_common(8))}")
    if notes:
        print(f"\n  {len(notes)} file(s) left alone (first 8):")
        for n in notes[:8]:
            print("   ", n)
    for f in changed[:2]:
        print(f"\n  example {f.name} (first section markup):")
        i = mended[f].find('<div type="section"')
        print("   ", mended[f][i : i + 420].replace("\n", "⏎"))
    if write_dir:
        write_dir.mkdir(parents=True, exist_ok=True)
        for f in changed:
            (write_dir / f.name).write_text(mended[f], "utf-8")
        print(f"\n  wrote {len(changed)} mended copies to {write_dir} (project files untouched)")
    else:
        print("\n  dry run: nothing written (use --write-dir DIR for mended copies)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="folder of imported section files (…/imported/cbeta/<work>)")
    ap.add_argument(
        "--source", type=Path, action="append", required=True,
        help="the CBETA P5 source file, e.g. C056n1163.xml; repeat for a work spanning volumes, in order",
    )
    ap.add_argument("--write-dir", type=Path, help="write mended copies of changed files here")
    a = ap.parse_args()
    if a.write_dir and a.write_dir.resolve() == a.folder.resolve():
        ap.error("--write-dir must differ from the imported folder")
    return run(a.source, a.folder, a.write_dir)


if __name__ == "__main__":
    raise SystemExit(main())
