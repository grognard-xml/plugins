"""Fill Kanripo's ``□`` placeholders from a reference text.

A Kanripo source writes ``□`` where its own text had a character it could not encode, as in
``旭旭、□□憍也``. When a parallel edition is at hand, the characters it has at that place are
usually the answer (蹻蹻). Each run of ``□`` is looked up as ``context before + n characters +
context after`` in the parallel's Han text, and filled only when every match gives the same
characters.

Cautious by design: the context must be at least ``MIN_CONTEXT_HAN`` Han characters, at least 2 on
each side (the text's own start or end excepted), another ``□`` or a gaiji ``<g>``
in the context matches any character, and a run whose context matches nothing, or matches with
different characters in different places, is left as it is. Only the ``□`` characters change.
"""

from __future__ import annotations

import re
from typing import TypedDict

from kanripo_import.parallel_punct import HAN_RE

PLACEHOLDER = "□"
MAX_CONTEXT = 6
MIN_CONTEXT_HAN = 7  # Han characters of context, before and after together, that must agree
MAX_RUN = 8
_SEPARATOR = "\x00"
_TOKEN_RE = re.compile(r"(?P<g><g\b[^>]*?(?:/>|>.*?</g>))|(?P<tag><[^>]+>)|(?P<ch>.)", re.DOTALL)


class Fill(TypedDict):
    before: str
    after: str
    run: int
    fill: str
    context: int
    start: int  # index of the first □ in the XML string


class Skipped(TypedDict):
    before: str
    after: str
    run: int
    reason: str


def _tokens(xml: str) -> list[tuple[str, str, int, bool]]:
    """(kind, char, index, after_other_text) for every Han character (h), □ (b) and gaiji (w);
    the last flag is true when other visible text (punctuation) came just before it."""
    out: list[tuple[str, str, int, bool]] = []
    broken = False
    for m in _TOKEN_RE.finditer(xml):
        if m.group("tag"):
            continue
        if m.group("g"):
            out.append(("w", "", m.start(), broken))
            broken = False
            continue
        ch = m.group("ch")
        if HAN_RE.fullmatch(ch):
            out.append(("h", ch, m.start(), broken))
        elif ch == PLACEHOLDER:
            out.append(("b", ch, m.start(), broken))
        else:
            if not ch.isspace():
                broken = True
            continue
        broken = False
    return out


def parallel_corpus(texts: list[str]) -> str:
    """The Han characters of each reference text, kept apart by a separator."""
    return _SEPARATOR.join("".join(HAN_RE.findall(text)) for text in texts if text)


def _lookup(corpus: str, before: list, after: list, run: int) -> set[str]:
    def part(tokens):
        return "".join(re.escape(t[1]) if t[0] == "h" else f"[^{_SEPARATOR}]" for t in tokens)

    regex = re.compile(f"(?={part(before)}(?P<fill>[^{_SEPARATOR}]{{{run}}}){part(after)})")
    return {m.group("fill") for m in regex.finditer(corpus)}


def _context_sizes(available_before: int, available_after: int) -> list[tuple[int, int]]:
    """(characters before, characters after) to try, longest context first. Each side needs 2,
    unless the text ends there (then 0, and the other side carries the match)."""
    sides_before = [k for k in range(MAX_CONTEXT, -1, -1) if k <= available_before and (k >= 2 or available_before < 2 and k == 0)]
    sides_after = [k for k in range(MAX_CONTEXT, -1, -1) if k <= available_after and (k >= 2 or available_after < 2 and k == 0)]
    return sorted(((b, a) for b in sides_before for a in sides_after), key=lambda ba: (-(ba[0] + ba[1]), abs(ba[0] - ba[1])))


def fill_placeholders(xml: str, texts: list[str]) -> tuple[str, list[Fill], list[Skipped]]:
    """Fill the ``□`` runs of ``xml`` that the reference ``texts`` settle.

    Returns the new XML, the fills made and the runs left alone with the reason.
    """
    if PLACEHOLDER not in xml or not any(HAN_RE.search(t) for t in texts):
        return xml, [], []
    corpus = parallel_corpus(texts)
    tokens = _tokens(xml)
    fills: list[Fill] = []
    skipped: list[Skipped] = []
    replacements: dict[int, str] = {}

    i = 0
    while i < len(tokens):
        if tokens[i][0] != "b":
            i += 1
            continue
        j = i
        while j + 1 < len(tokens) and tokens[j + 1][0] == "b" and not tokens[j + 1][3]:
            j += 1
        run = j - i + 1
        before_all, after_all = tokens[max(0, i - MAX_CONTEXT) : i], tokens[j + 1 : j + 1 + MAX_CONTEXT]
        # A context stops at the start of the text; never reaches across the other run's boxes
        # as anything but a wildcard.
        label_before = "".join(t[1] or "〓" for t in before_all[-MAX_CONTEXT:])
        label_after = "".join(t[1] or "〓" for t in after_all)
        result: tuple[str, int] | None = None
        reason = "no match in the reference"
        if run > MAX_RUN:
            reason = "run too long"
        else:
            for kb, ka in _context_sizes(len(before_all), len(after_all)):
                before, after = before_all[len(before_all) - kb :] if kb else [], after_all[:ka]
                if sum(1 for t in before + after if t[0] == "h") < MIN_CONTEXT_HAN:
                    continue
                found = _lookup(corpus, before, after, run)
                if len(found) == 1:
                    result = (next(iter(found)), kb + ka)
                    break
                if len(found) > 1:
                    reason = "the reference reads differently in different places"
                    break
        if result and PLACEHOLDER not in result[0]:
            fill, k = result
            for offset, char in enumerate(fill):
                replacements[tokens[i + offset][2]] = char
            fills.append({"before": label_before, "after": label_after, "run": run, "fill": fill,
                          "context": k, "start": tokens[i][2]})
        else:
            skipped.append({"before": label_before, "after": label_after, "run": run, "reason": reason})
        i = j + 1

    if not replacements:
        return xml, fills, skipped
    chars = list(xml)
    for index, char in replacements.items():
        chars[index] = char
    return "".join(chars), fills, skipped
