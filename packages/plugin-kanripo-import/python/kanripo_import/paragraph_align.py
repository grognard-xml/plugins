"""Paragraph-level cross-file/cross-juan alignment for folder-based reference sources.

Sits one level above ``parallel_punct``'s tape/segment machinery: given a whole
Kanripo work (many juan) and a folder of reference-source files whose boundaries
don't line up with juan boundaries, decides which reference paragraph goes with
which juan (``align_paragraphs``). Application then inserts each match's
punctuation directly at its own paragraph's known Han position
(``apply_paragraph_scoped_sources``, via ``parallel_punct.apply_scoped_parallel_punctuation``)
rather than through the global fuzzy tape/sticker search — see that
function's docstring for why per-paragraph scoping matters, not just reuse.
``build_juan_source_map`` still reassembles a readable excerpt per juan for
display purposes, but is no longer what application is based on.

Source-agnostic: nothing here is specific to ctext or any other single provider.
A "reference folder" is just a list of {file, text} plain-text files.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TypedDict

from kanripo_import.normalize_tables import apply_hard_replacements
from kanripo_import.parallel_punct import (
    HAN_RE,
    _is_p_open,
    _iter_xml_atoms_segmented,
    han_only,
)

_BLANK_LINE_RE = re.compile(r"\n\s*\n+")
# Reference-source text is typically already punctuated but not reliably
# blank-line-per-paragraph (a blank-line block can be an entire multi-thousand
# character section). Split further on sentence-ending punctuation so source
# units are comparable in size to Kanripo's line-level <p> paragraphs — a
# no-op when the source is already fine-grained.
#
# A closing quote/bracket (「...」, 《...》, etc.) routinely sits right after
# the sentence-final mark that ends the quoted/titled stretch ("...二年。」
# 郗萌曰...") -- splitting right after 。 alone strands that closing mark as
# the *next* unit's leading character instead of the end of the one that
# just closed, and it then has no Han content before it to attach to at
# all. Each alternative below is its own fixed-width lookbehind (Python's
# `re` rejects a variable-width one), consuming 0, 1, or 2 stacked closing
# marks (e.g. a quote ending right at a title's own close too) so the split
# point lands after all of them, never between the sentence end and the
# first one.
_CLOSING_PUNCT = "」』》）〕"
_SENTENCE_SPLIT_RE = re.compile(
    rf"(?<=[。！？])(?![{_CLOSING_PUNCT}])"
    rf"|(?<=[。！？][{_CLOSING_PUNCT}])(?![{_CLOSING_PUNCT}])"
    rf"|(?<=[。！？][{_CLOSING_PUNCT}][{_CLOSING_PUNCT}])"
)

# A reference-source paragraph block prefixed with a run of 1 or 2 asterisks
# is a structural heading, not running text: `*…` for a section, `**…` for a
# subsection — an un-closed *prefix*, not a wrapped `**…**` pair. This
# mirrors the convention already partially in use across the ctext corpus
# itself (grep confirms zero closing asterisks and no run longer than 2 in
# the whole corpus): reuse it rather than invent a new one that would force
# rewriting the files that already have it. A file's very first paragraph
# block is always its (always-unmarked) chapter/juan title — see
# `extract_source_paragraphs`, not this regex, which only ever matches
# `heading in {"section", "subsection"}`. A lone `*` immediately followed by
# a third asterisk never matches here (`(?!\*)`), so it can't be confused
# with a deeper level by accident.
_HEADING_RE = re.compile(r"^(\*{1,2})(?!\*)(.+)$", re.DOTALL)
_HEADING_LEVELS = {1: "section", 2: "subsection"}
# A block with no sentence-ending punctuation at all is title-shaped — real
# running text in this genre is citation-heavy and always ends a block in
# one of these (the same signal `_SENTENCE_SPLIT_RE` already cuts blocks on).
_SENTENCE_END_CHARS_RE = re.compile(r"[。！？]")

DEFAULT_SIMILARITY_THRESHOLD = 0.85
# Containment scoring (see `_containment_ratio`) is specifically designed to
# handle large length mismatches -- a short Kanripo <p> fragment fully inside
# a much longer reference-source sentence is exactly the common, correct
# case, not noise. A length-based prefilter actively excludes those valid
# matches; the bigram index + candidate cap already bound the search space,
# so the length filter is disabled by default (0 = no filtering).
DEFAULT_LENGTH_PREFILTER_RATIO = 0.0


class SourceParagraph(TypedDict):
    file: str
    para_idx: int
    text: str
    key: str
    # "chapter" | "section" | "subsection" | None. Set when this paragraph
    # was a file's first block, or a `*…`/`**…`-prefixed block — `text`/
    # `key` hold the marker-stripped title in that case, never matched
    # against target body text (see `_BigramIndex`), only used to place a
    # `<head>` via its neighbors (see `_resolve_heading_insertions`).
    heading: str | None


class RefParagraph(TypedDict):
    juan_id: str
    para_idx: int
    text: str
    key: str
    han_start: int  # index into _han_tape(_iter_xml_atoms_segmented(body_xml))
    han_end: int  # exclusive


class ParagraphMatch(TypedDict):
    ref_juan_id: str
    ref_para_idx: int
    source_file: str | None
    source_para_idx: int | None
    source_para_end_idx: int | None  # inclusive; == source_para_idx unless "merged"
    score: float
    match_type: str  # "exact" | "fuzzy" | "merged" | "unmatched"


def normalize_para_key(text: str) -> str:
    """Comparison key: Han characters only, with simp/trad variants collapsed
    (``hard_replacements_table``) so punctuation/whitespace/markup/script
    variants never matter for matching. This table is comparison-only — it
    must never be applied to the transcription text itself, only to the key
    used to find parallels.
    """
    return apply_hard_replacements(han_only(text))


def split_paragraphs(text: str) -> list[str]:
    """Blank-line block split, then sentence-level split within each block."""
    blocks = [b.strip() for b in _BLANK_LINE_RE.split(text.strip()) if b.strip()]
    units: list[str] = []
    for block in blocks:
        for sentence in _SENTENCE_SPLIT_RE.split(block):
            sentence = sentence.strip()
            if sentence:
                units.append(sentence)
    return units


_IDEOGRAPHIC_SPACE = "　"


def extract_ref_paragraphs(juan_id: str, body_xml: str) -> list[RefParagraph]:
    """Extract each ``<p>``'s citation-level sub-units plus their Han-index
    ranges in the juan's tape.

    Kanripo's ``<p>`` breaks are page-line based, not citation based: a
    single ``<p>`` routinely concatenates several distinct citations
    ("X曰...　Y曰...　Z曰..."), separated internally by an ideographic
    space (U+3000) -- the OCR/transcription convention this Mandoku-derived
    text uses at those boundaries. Treating a whole such ``<p>`` as one
    alignment unit means only the single citation that happens to score
    best gets matched (and punctuated), silently leaving the others in the
    same ``<p>`` untouched even though the paragraph itself "matched".
    Splitting further at those internal boundaries gives each citation its
    own precise scope.

    The range is computed by walking ``_iter_xml_atoms_segmented`` (the same
    atom stream ``apply_scoped_parallel_punctuation`` expects Han indices
    from) rather than a plain regex over ``body_xml``, so ``han_start``/
    ``han_end`` can be used directly for precise, per-unit scoped insertion
    instead of a global fuzzy search over a reassembled excerpt.
    """
    atoms = _iter_xml_atoms_segmented(body_xml)
    paragraphs: list[RefParagraph] = []
    han_count = 0
    para_idx = 0
    in_p = False
    unit_start = 0
    unit_text_parts: list[str] = []

    def flush_unit() -> None:
        nonlocal para_idx
        text = "".join(unit_text_parts)
        key = normalize_para_key(text)
        if key:
            paragraphs.append(
                {
                    "juan_id": juan_id,
                    "para_idx": para_idx,
                    "text": text,
                    "key": key,
                    "han_start": unit_start,
                    "han_end": han_count,
                }
            )
            para_idx += 1

    for atom in atoms:
        if _is_p_open(atom):
            in_p = True
            unit_start = han_count
            unit_text_parts = []
            continue
        if atom == "</p>":
            if in_p:
                flush_unit()
            in_p = False
            continue
        if atom.startswith("<"):
            continue
        if in_p:
            if atom == _IDEOGRAPHIC_SPACE:
                flush_unit()
                unit_start = han_count
                unit_text_parts = []
                continue
            unit_text_parts.append(atom)
        if HAN_RE.fullmatch(atom):
            han_count += 1

    return paragraphs


def extract_source_paragraphs(file_label: str, text: str) -> list[SourceParagraph]:
    """Split ``text`` into paragraph units, tagging headings along the way.

    Explicit ``*``/``**`` markers (see ``_HEADING_RE``) always win, at any
    position in the file. Only block 0 -- the file's very first paragraph --
    is unconditionally the chapter title. Checked against the ctext corpus's
    own already-marked files: in the large majority of them the *second*
    block (the first thing after the chapter line) is already the first
    section; only a couple stack a second unmarked chapter-level line first
    (e.g. a separate work-title and chapter-title line), with no textual
    signal distinguishing that case from an ordinary first section. So every
    title-shaped block from index 1 onward defaults to being a heading
    (section, unless a marker says otherwise) -- matching the common case,
    at the cost of occasionally over-eagerly promoting a rare stacked
    second title line.

    A block with sentence-ending punctuation is never a heading candidate
    at all, marker or no -- real running text in this genre is
    citation-heavy and always ends a block in one (the same signal
    ``_SENTENCE_SPLIT_RE`` already cuts blocks on).
    """
    paragraphs: list[SourceParagraph] = []
    for idx, para_text in enumerate(split_paragraphs(text)):
        heading: str | None = None
        if _SENTENCE_END_CHARS_RE.search(para_text):
            pass  # real running text -- never a heading, marker or no
        elif idx == 0:
            heading = "chapter"
        else:
            heading_match = _HEADING_RE.match(para_text)
            if heading_match:
                heading = _HEADING_LEVELS[len(heading_match.group(1))]
                para_text = heading_match.group(2).strip()
            else:
                heading = "section"
        key = normalize_para_key(para_text)
        if not key:
            continue
        paragraphs.append(
            {
                "file": file_label,
                "para_idx": idx,
                "text": para_text,
                "key": key,
                "heading": heading,
            }
        )
    return paragraphs


_MAX_CANDIDATES = 25


def _bigrams(key: str) -> set[str]:
    if len(key) < 2:
        return {key} if key else set()
    return {key[i : i + 2] for i in range(len(key) - 1)}


class _BigramIndex:
    """Inverted bigram index over source paragraphs.

    A full O(n_ref * n_source) length-prefiltered scan is still too slow for
    real corpora (tens of thousands of short paragraphs on both sides): most
    candidate pairs share no characters at all and don't need a
    SequenceMatcher call. This index narrows each ref paragraph's candidates
    to source paragraphs that actually share Han bigrams with it, ranked by
    overlap count, before any string-similarity scoring happens.
    """

    def __init__(self, source_paragraphs: list[SourceParagraph]):
        self._paragraphs = source_paragraphs
        self._index: dict[str, list[int]] = {}
        for i, para in enumerate(source_paragraphs):
            # Headings are short, generic titles ("天地名體") that would
            # false-match somewhere unrelated in a long juan under ordinary
            # body-text fuzzy matching. They never enter the bigram index —
            # `source_paragraphs` still keeps their slot (so `by_file`/
            # `text_by_key` para_idx lookups stay intact), they're just never
            # returned as a matching candidate. See `_resolve_heading_insertions`
            # for how they're placed instead.
            if para.get("heading"):
                continue
            for bg in _bigrams(para["key"]):
                self._index.setdefault(bg, []).append(i)

    def candidates(
        self, ref_key: str, length_prefilter_ratio: float, max_candidates: int = _MAX_CANDIDATES
    ) -> list[SourceParagraph]:
        counts: dict[int, int] = {}
        for bg in _bigrams(ref_key):
            for idx in self._index.get(bg, ()):
                counts[idx] = counts.get(idx, 0) + 1
        if not counts:
            return []

        ref_len = len(ref_key)
        if length_prefilter_ratio and ref_len:
            lo, hi = ref_len * length_prefilter_ratio, ref_len / length_prefilter_ratio
        else:
            lo, hi = 0, float("inf")

        ranked = sorted(counts.items(), key=lambda kv: -kv[1])
        result: list[SourceParagraph] = []
        for idx, _ in ranked:
            para = self._paragraphs[idx]
            if lo <= len(para["key"]) <= hi:
                result.append(para)
            if len(result) >= max_candidates:
                break
        return result


def _coverage_count(key_a: str, key_b: str) -> int:
    """Count of ``key_a`` characters found, in order, somewhere in ``key_b``.

    The building block both ``_containment_ratio`` and the merge-window
    growth in ``align_paragraphs`` are built on. Unlike a ratio, this stays a
    meaningful, strictly-comparable signal even once ``key_b`` grows past
    ``key_a``'s own length — it can never exceed ``len(key_a)`` no matter how
    much unrelated extra content ``key_b`` picks up beyond what actually
    explains ``key_a``, which is exactly what makes it safe to use as a
    "did growing the merge window actually help" stopping signal: a ratio or
    raw length alone cannot tell that apart from genuine improvement, since
    both keep climbing even once growth has stopped covering anything new.
    """
    if not key_a or not key_b:
        return 0
    matcher = SequenceMatcher(a=key_a, b=key_b, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks())


def _containment_ratio(key_a: str, key_b: str) -> float:
    """Fraction of the shorter key's characters found, in order, in the longer one.

    Kanripo's ``<p>`` paragraphs are page-line fragments and are often much
    shorter than one full reference-source sentence (or occasionally the
    reverse). A symmetric ``SequenceMatcher.ratio()`` unfairly penalises that
    length mismatch even for a perfect fragment-within-sentence match, so we
    score by containment relative to the shorter side instead.
    """
    denom = min(len(key_a), len(key_b))
    if denom == 0:
        return 0.0
    return _coverage_count(key_a, key_b) / denom


# Below this fraction of the ref key's own length, a single candidate's
# perfect containment score is trusted far less -- it's covering the start
# of a longer concatenated-citations ref paragraph, not the whole thing, and
# align_paragraphs tries extending it with neighbors even though its own
# score already cleared similarity_threshold. 0.9 rather than something
# looser: a single citation's own sentence-internal padding (an opening
# "...曰：" before its quote, etc.) can legitimately leave single-candidate
# coverage a little under 1.0 without another citation actually following.
_MIN_SINGLE_CANDIDATE_COVERAGE = 0.9

# A single Kanripo <p> can concatenate well over a hundred short citations
# with no separator at all between them (seen for real: 135 <seg> stamps
# inside one <p>) -- this needs to be large enough that a long run like that
# can still be reached, not tuned to a "typical" case. Safe to set
# generously because align_paragraphs' merge-window growth (see
# _grow_merge_window) is linear in the window size, not quadratic: it grows
# the match one source paragraph at a time, backward or forward, only while
# that still covers more of the ref key than the window already does, so an
# oversized cap costs nothing when a short run stops growing well before it.
DEFAULT_MAX_MERGE_WINDOW = 200
# Tolerance, in source paragraphs, for gaps between matched paragraphs from
# the same file before build_juan_source_map starts a new excerpt. See that
# function's docstring for why this bound matters for correctness, not just
# block count.
MAX_SOURCE_GAP = 20


def _best_candidate(
    key: str,
    index: "_BigramIndex",
    length_prefilter_ratio: float,
    expected_position: dict[str, int],
) -> tuple[float, SourceParagraph, bool] | None:
    """Best-scoring candidate for ``key``, with position-based tie-break.

    Returns (score, chosen, unambiguous) for the single best-scoring bigram
    candidate, regardless of threshold (callers apply the threshold
    themselves) — or None if the bigram index found no candidates at all.
    ``unambiguous`` is True only when the tie-break resolved to a single
    winner, which is what gates whether the position pointer advances.

    Deliberately unrestricted across source files, including ones whose
    number doesn't match the target juan's own: this genre repeats the same
    sentence verbatim across several juan routinely (boilerplate omens for
    structurally similar entries), and borrowing *punctuation* for a
    genuinely identical sentence from wherever it's found is correct and
    desirable — this only ever decorates the target's own, already-present
    Han characters with punctuation, never adds new text (see
    ``parallel_punct.apply_scoped_parallel_punctuation``). Text actually
    moving between files is a real risk, but only for heading insertion
    (``_resolve_heading_insertions``), which is gated separately there.
    """
    candidates = index.candidates(key, length_prefilter_ratio)
    if not candidates:
        return None
    scored = [(_containment_ratio(key, c["key"]), c) for c in candidates]

    best_score = max(s for s, _ in scored)
    near_best = [c for s, c in scored if s >= best_score - 1e-9]

    def tie_key(cand: SourceParagraph) -> tuple[int, int]:
        pointer = expected_position.get(cand["file"], 0)
        after_pointer = 0 if cand["para_idx"] >= pointer else 1
        distance = abs(cand["para_idx"] - pointer)
        return (after_pointer, distance)

    keyed = [(tie_key(c), c) for c in near_best]
    best_key = min(k for k, _ in keyed)
    winners = [c for k, c in keyed if k == best_key]
    return best_score, winners[0], len(winners) == 1


_TRAILING_JUAN_DIGITS_RE = re.compile(r"(\d+)\D*$")
_LEADING_FILE_DIGITS_RE = re.compile(r"^(\d+)")
_CN_JUAN_LOCATOR_RE = re.compile(r"卷([〇一二三四五六七八九十百千]+)")
_CN_DIGIT_VALUE = {c: i for i, c in enumerate("〇一二三四五六七八九")}
_CN_UNIT_VALUE = {"十": 10, "百": 100, "千": 1000}
# Kanripo's own pb-marker numbering (<pb n="KR..._000-...">) puts front
# matter before juan 1 as juan 0 -- confirmed directly against this plugin's
# own test corpus, whose table-of-contents juan is numbered KR..._000.
_FRONT_MATTER_JUAN_IDS = {"目錄", "目次", "序", "前言", "凡例"}


def _cn_numeral_to_int(s: str) -> int | None:
    """Parse a run of Han numeral characters (e.g. ``"一百二十"`` -> 120).
    ``None`` if ``s`` is empty or contains anything that isn't a recognized
    digit/unit character."""
    if not s or any(ch not in _CN_DIGIT_VALUE and ch not in _CN_UNIT_VALUE for ch in s):
        return None
    total = 0
    section = 0
    for ch in s:
        if ch in _CN_DIGIT_VALUE:
            section = _CN_DIGIT_VALUE[ch]
        else:
            total += (section or 1) * _CN_UNIT_VALUE[ch]
            section = 0
    return total + section


def _numeric_juan_key(juan_id: str) -> int | None:
    """Best-effort juan number for a ``RefParagraph.juan_id``.

    The Kanripo plugin's own ``meta.juan`` is a human-readable locator
    (``"卷三"``), not the clean integer its pb markers actually encode
    (``header["juan"]`` wins over ``pb_meta.juan`` in ``kanripo_tei.py``
    whenever the source has its own header field) -- so this has to parse
    that locator, not just look for plain digits. Recognizes, in order:
    plain trailing digits (``"KR3g0018_003"``, or the bare ``"3"`` a caller
    might pass directly); a ``"卷<Han numeral>"`` locator (``"卷三"`` ->
    3, up to ``"卷一百二十"`` -> 120); and a handful of recognized
    front-matter labels mapped to juan 0 (see ``_FRONT_MATTER_JUAN_IDS``).
    ``None`` for anything else, which simply leaves heading-anchor matching
    unrestricted for that juan (see ``_resolve_heading_insertions``), same
    as if this parsing didn't exist at all.
    """
    if juan_id in _FRONT_MATTER_JUAN_IDS:
        return 0
    match = _TRAILING_JUAN_DIGITS_RE.search(juan_id)
    if match:
        return int(match.group(1))
    locator = _CN_JUAN_LOCATOR_RE.search(juan_id)
    if locator:
        return _cn_numeral_to_int(locator.group(1))
    return None


def _numeric_file_key(file_label: str) -> int | None:
    """The number a reference-source filename leads with, e.g. the ``3`` in
    ``"03.txt"`` — ``None`` for a filename with no leading digits."""
    match = _LEADING_FILE_DIGITS_RE.match(file_label)
    return int(match.group(1)) if match else None


def _merged_source_key(
    by_file: dict[str, list[SourceParagraph]], file: str, start_idx: int, end_idx: int
) -> str | None:
    """Concatenated key of source paragraphs [start_idx, end_idx] (inclusive) in ``file``."""
    paras = by_file.get(file)
    if not paras or start_idx < 0 or end_idx >= len(paras):
        return None
    return "".join(paras[i]["key"] for i in range(start_idx, end_idx + 1))


# How many consecutive non-improving growth steps _grow_merge_window
# tolerates before giving up on a direction, rather than stopping at the
# very first one. A single paragraph along the way whose wording has
# drifted from this witness (real edition variance between two citations'
# transmission, not a bug — e.g. one paragraph's ending borrowed from an
# adjacent citation's wording) adds nothing to coverage on its own, but the
# *next* paragraph after it usually resumes covering real content; stopping
# at the first flat step would abandon a long, genuinely-needed run right
# at that one bad paragraph instead of growing past it.
_MERGE_GROWTH_PATIENCE = 3


def _grow_merge_window(
    ref_key: str,
    by_file: dict[str, list[SourceParagraph]],
    file: str,
    anchor_idx: int,
    similarity_threshold: float,
    max_merge_window: int,
) -> tuple[int, int, float] | None:
    """Greedily extend a same-file source-paragraph window around
    ``anchor_idx``, one paragraph at a time, to cover as much of ``ref_key``
    as a run of this file's consecutive paragraphs actually explains.

    Linear in the window size, not quadratic: at each step, tries adding one
    more paragraph on whichever side — backward or forward — and keeps
    growing on whichever side covers more of ``ref_key`` (see
    ``_coverage_count``'s docstring for why this, not a ratio or raw length,
    is the signal that can actually tell "still finding more of ref_key"
    apart from "just adding unrelated bulk"). Tolerates up to
    ``_MERGE_GROWTH_PATIENCE`` consecutive non-improving steps before giving
    up a direction (see that constant), reverting to the best window
    actually found rather than wherever patience happened to run out. This
    is what makes a generous ``max_merge_window`` cheap: a run that stops
    covering more of ref_key stops growing there (plus a short, bounded
    patience probe), regardless of how high the cap is, and a run that
    genuinely needs a hundred-plus short citations (seen for real in this
    corpus) can still reach that without an O(window²) search.

    Returns ``(start_idx, end_idx, score)`` for the best window found, or
    ``None`` if even the full window never reaches ``similarity_threshold``.
    """
    start = end = anchor_idx
    best_key = _merged_source_key(by_file, file, start, end) or ""
    best_coverage = _coverage_count(ref_key, best_key)
    best_start, best_end = start, end

    stall = 0
    while (end - start + 1) < max_merge_window and stall <= _MERGE_GROWTH_PATIENCE:
        back_key = _merged_source_key(by_file, file, start - 1, end)
        back_coverage = _coverage_count(ref_key, back_key) if back_key is not None else -1
        fwd_key = _merged_source_key(by_file, file, start, end + 1)
        fwd_coverage = _coverage_count(ref_key, fwd_key) if fwd_key is not None else -1

        if back_coverage < 0 and fwd_coverage < 0:
            break  # both directions exhausted this file's paragraphs

        if fwd_coverage >= back_coverage:
            end += 1
            current_coverage = fwd_coverage
        else:
            start -= 1
            current_coverage = back_coverage

        if current_coverage > best_coverage:
            best_coverage = current_coverage
            best_start, best_end = start, end
            stall = 0
        else:
            stall += 1

    start, end = best_start, best_end
    best_key = _merged_source_key(by_file, file, start, end) or ""

    score = _containment_ratio(ref_key, best_key)
    if score < similarity_threshold:
        return None
    return start, end, score


def align_paragraphs(
    ref_paragraphs: list[RefParagraph],
    source_paragraphs: list[SourceParagraph],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    length_prefilter_ratio: float = DEFAULT_LENGTH_PREFILTER_RATIO,
    max_merge_window: int = DEFAULT_MAX_MERGE_WINDOW,
) -> list[ParagraphMatch]:
    """Match each ref paragraph to its best-scoring source paragraph, if any.

    Kanripo ``<p>`` breaks are page-line based and routinely straddle two
    reference-source sentence/quotation-unit boundaries — a single ref
    paragraph can be "end of sentence A" + "start of sentence B", or even
    several whole citations concatenated with no separator at all between
    them (no ideographic space, Kanripo's own citation-boundary convention,
    always guaranteed). No single source paragraph can fully contain that,
    capping its best single-candidate score short of the threshold even when
    the content is genuinely correct.

    When a ref paragraph's single best candidate falls short — or scores a
    perfect containment but only accounts for a small fraction of the ref
    key's own length (the concatenated-citations case: the first citation's
    source paragraph is perfectly, wholly contained in the combined ref key,
    which says nothing about whether anything of the ref key remains
    uncovered after it) — this retries against a merged window of that
    candidate plus its immediate neighbors *in the same source file*
    (extending backward, forward, or both, up to ``max_merge_window`` source
    paragraphs) before giving up — this targets the boundary-straddling case
    directly instead of just lowering the threshold (which would admit false
    matches from this genre's formulaic, repeated phrasing).

    Ties/near-ties are broken by a monotonic per-file position pointer: among
    candidates within ``similarity_threshold`` of the best score, prefer the one
    at or after that file's last confirmed match, closest to it. The pointer only
    advances on confident (non-ambiguous) matches, so one bad match can't derail
    everything downstream.

    Deliberately pools every reference file against every juan with no
    file-to-juan restriction, including this genre's routine case of the
    same boilerplate sentence appearing verbatim across several juan — see
    ``_best_candidate``'s docstring for why that's fine (punctuation only,
    never new text). The real risk of a false cross-juan match — a source
    file's own heading landing on the wrong juan — is gated in
    ``_resolve_heading_insertions`` instead, which is the only place text
    actually moves between files.
    """
    by_file: dict[str, list[SourceParagraph]] = {}
    for src in source_paragraphs:
        by_file.setdefault(src["file"], []).append(src)

    expected_position: dict[str, int] = {f: 0 for f in by_file}
    index = _BigramIndex(source_paragraphs)

    matches: list[ParagraphMatch] = []

    for ref in ref_paragraphs:
        anchor = _best_candidate(ref["key"], index, length_prefilter_ratio, expected_position)
        if anchor is None:
            matches.append(
                {
                    "ref_juan_id": ref["juan_id"],
                    "ref_para_idx": ref["para_idx"],
                    "source_file": None,
                    "source_para_idx": None,
                    "source_para_end_idx": None,
                    "score": 0.0,
                    "match_type": "unmatched",
                }
            )
            continue

        score, chosen, unambiguous = anchor
        start_idx = end_idx = chosen["para_idx"]
        match_type = "exact" if ref["key"] == chosen["key"] else "fuzzy"
        # A perfect containment score only says chosen["key"] is wholly found
        # in ref["key"] in order -- nothing about whether ref["key"] has more
        # content *after* it that chosen alone doesn't cover (the
        # concatenated-citations case). Worth trying to extend whenever the
        # single candidate accounts for well under all of the ref key's own
        # length, regardless of its score.
        low_coverage = len(chosen["key"]) < len(ref["key"]) * _MIN_SINGLE_CANDIDATE_COVERAGE

        if score < similarity_threshold or low_coverage:
            grown = _grow_merge_window(
                ref["key"],
                by_file,
                chosen["file"],
                chosen["para_idx"],
                similarity_threshold,
                max_merge_window,
            )
            if grown is not None and grown[1] > grown[0]:
                # Genuine growth past the single anchor; a (start, end) with
                # no growth at all and score already below threshold would
                # make _grow_merge_window's own containment check (same
                # formula as the anchor's own score) return None too, so
                # there's no case here where growth "succeeded" without
                # actually widening the window.
                start_idx, end_idx, score = grown
                match_type = "merged"

        if score < similarity_threshold:
            matches.append(
                {
                    "ref_juan_id": ref["juan_id"],
                    "ref_para_idx": ref["para_idx"],
                    "source_file": None,
                    "source_para_idx": None,
                    "source_para_end_idx": None,
                    "score": 0.0,
                    "match_type": "unmatched",
                }
            )
            continue

        matches.append(
            {
                "ref_juan_id": ref["juan_id"],
                "ref_para_idx": ref["para_idx"],
                "source_file": chosen["file"],
                "source_para_idx": start_idx,
                "source_para_end_idx": end_idx,
                "score": score,
                "match_type": match_type,
            }
        )
        # Only advance the pointer once the position-based tie-break resolved
        # to a single winner — a genuine remaining tie shouldn't lock in a
        # possibly-wrong position for later lookups.
        if unambiguous:
            expected_position[chosen["file"]] = end_idx + 1

    return matches


def build_juan_source_map(
    matches: list[ParagraphMatch],
    source_paragraphs: list[SourceParagraph],
) -> dict[str, list[dict]]:
    """Group matched source paragraph text by juan, in ref-paragraph order.

    Returns a dict of juan_id -> sources list, directly usable as the ``sources``
    argument to ``apply_parallel_sources``. A juan with no matches maps to ``[]``.

    Matches are grouped into one source-list entry per gap-bounded run within
    a (juan, source file): consecutive matched paragraphs from the same file
    are reassembled, in that file's own order, into one excerpt, tolerating
    small gaps (a handful of unmatched/low-score paragraphs in between --
    normal editorial noise) up to ``MAX_SOURCE_GAP``, but starting a new
    block once matched paragraphs are too far apart.

    This bound matters for more than block count: ``find_han_overlap``
    (the tape/sticker search) locates one span in the juan's text covering
    everywhere the excerpt's Han text is found, and ``_sticker_to_tape_map``
    only maps the excerpt's own characters onto that span -- it has no
    notion of "gap" for content the excerpt is missing. If matched
    paragraphs from one file are scattered arbitrarily far apart, the
    located span can end up spanning nearly the whole juan while the actual
    excerpt text only covers a sparse fraction of it, so punctuation only
    lands in the few positions that do map, even though ``apply_parallel_sources``
    reports the whole wide span as "covered" (it measures span width, not
    inserted-punctuation density) -- silently leaving most of that span
    unpunctuated. Bounding the gap keeps each excerpt's span reasonably
    dense, while still merging real, mostly-contiguous same-file matches
    (which is what ``MIN_BLOCK``/``MIN_STICKER_COVER`` expect) rather than
    reverting to one tiny entry per paragraph.
    """
    text_by_key: dict[tuple[str, int], str] = {
        (src["file"], src["para_idx"]): src["text"] for src in source_paragraphs
    }

    juan_ids = sorted({m["ref_juan_id"] for m in matches})
    result: dict[str, list[dict]] = {juan_id: [] for juan_id in juan_ids}

    # Collect the set of matched (file, idx) source paragraphs per (juan, file).
    idx_by_juan_file: dict[tuple[str, str], set[int]] = {}
    for match in matches:
        if match["match_type"] == "unmatched":
            continue
        key = (match["ref_juan_id"], match["source_file"])
        idx_by_juan_file.setdefault(key, set()).update(
            range(match["source_para_idx"], match["source_para_end_idx"] + 1)
        )

    blocks_by_juan: dict[str, list[tuple[str, str]]] = {juan_id: [] for juan_id in juan_ids}
    for (juan_id, file), indices in idx_by_juan_file.items():
        ordered = sorted(indices)
        runs: list[list[int]] = []
        for idx in ordered:
            if runs and idx - runs[-1][-1] <= MAX_SOURCE_GAP + 1:
                runs[-1].append(idx)
            else:
                runs.append([idx])
        for run in runs:
            texts = [text_by_key[(file, idx)] for idx in run if (file, idx) in text_by_key]
            if texts:
                blocks_by_juan[juan_id].append((file, " ".join(texts)))

    for juan_id, blocks in blocks_by_juan.items():
        entries = []
        for i, (file, text) in enumerate(blocks):
            if len(blocks) == 1:
                entry_id, label = f"aligned:{juan_id}", f"{juan_id} (aligned)"
            else:
                entry_id, label = f"aligned:{juan_id}:{i + 1}", f"{juan_id} (aligned, {file})"
            entries.append({"id": entry_id, "label": label, "text": text})
        result[juan_id] = entries

    return result


def missing_juan_ids(ref_juan_ids: list[str], matches: list[ParagraphMatch]) -> list[str]:
    matched_juan = {
        m["ref_juan_id"] for m in matches if m["match_type"] != "unmatched"
    }
    return [juan_id for juan_id in ref_juan_ids if juan_id not in matched_juan]


def bridge_align_folder_sources(payload: dict) -> dict:
    juan_payload = payload.get("juan") or []
    sources_payload = payload.get("sources") or []
    similarity_threshold = float(
        payload.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD)
    )
    length_prefilter_ratio = float(
        payload.get("length_prefilter_ratio", DEFAULT_LENGTH_PREFILTER_RATIO)
    )
    max_merge_window = int(payload.get("max_merge_window", DEFAULT_MAX_MERGE_WINDOW))

    ref_paragraphs: list[RefParagraph] = []
    ref_juan_ids: list[str] = []
    for entry in juan_payload:
        juan_id = str(entry.get("juan_id") or "")
        body_xml = str(entry.get("body_xml") or "")
        ref_juan_ids.append(juan_id)
        ref_paragraphs.extend(extract_ref_paragraphs(juan_id, body_xml))

    source_paragraphs: list[SourceParagraph] = []
    for entry in sources_payload:
        label = str(entry.get("label") or entry.get("id") or "source")
        text = str(entry.get("text") or "")
        source_paragraphs.extend(extract_source_paragraphs(label, text))

    matches = align_paragraphs(
        ref_paragraphs,
        source_paragraphs,
        similarity_threshold=similarity_threshold,
        length_prefilter_ratio=length_prefilter_ratio,
        max_merge_window=max_merge_window,
    )
    juan_sources = build_juan_source_map(matches, source_paragraphs)
    for juan_id in ref_juan_ids:
        juan_sources.setdefault(juan_id, [])

    return {
        "matches": matches,
        # Kept for display/review purposes (a human-readable excerpt per
        # juan); actual application uses apply_paragraph_scoped_sources,
        # which inserts each match at its own precise paragraph position
        # rather than via this reassembled text.
        "juan_sources": juan_sources,
        "missing_juan_ids": missing_juan_ids(ref_juan_ids, matches),
    }


def _trim_source_text_to_target(target_han: str, source_text: str) -> str:
    """Trim ``source_text`` (with punctuation) to the portion whose Han content
    best matches ``target_han``, when the source is meaningfully longer.

    ``apply_scoped_parallel_punctuation`` has its own internal trim step, but
    it delegates to ``find_han_overlap``, which requires an 8+ character
    contiguous matching block covering 80% of the shorter side -- thresholds
    already established (earlier in this alignment feature's development) to
    routinely reject short, genuinely-correct fragments with even one
    differing character. Since ``align_paragraphs`` already validated this
    match via its own more permissive containment scoring, trimming here
    with the same style of unrestricted ``SequenceMatcher`` comparison (no
    minimum block size) keeps that validation meaningful instead of
    re-failing it against a stricter gate one step later.
    """
    from kanripo_import.parallel_punct import _slice_text_by_han_range

    source_han = han_only(source_text)
    if not target_han or not source_han:
        return source_text
    if len(source_han) <= len(target_han) * 1.2:
        return source_text
    matcher = SequenceMatcher(a=target_han, b=source_han, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size > 0]
    if not blocks:
        return source_text
    start = min(b.b for b in blocks)
    end = max(b.b + b.size for b in blocks)
    trimmed = _slice_text_by_han_range(source_text, start, end)
    return trimmed or source_text


def _resolve_heading_insertions(
    ref_paragraphs: list[RefParagraph],
    matches: list[ParagraphMatch],
    source_paragraphs: list[SourceParagraph],
) -> list[tuple[int, str, str]]:
    """Where each ``**…**``/``***…***`` heading in the reference source(s)
    should land in the target's Han tape.

    A heading's own text is excluded from matching (see ``_BigramIndex``) —
    it usually doesn't appear verbatim in the Kanripo source at all, since
    chapter/section titles are routinely dropped in transcription. Instead,
    each heading anchors on the *next* source paragraph in the same file
    that did successfully match something: whatever position that
    paragraph landed at is where the heading goes, right before it. A
    trailing heading with nothing matched after it in its file is dropped —
    there's no target position to anchor it to.

    A heading is the one place in this pipeline where real text — not just
    punctuation — moves from a reference file into the target: it's inserted
    verbatim as new ``<head>`` content, not decorated onto characters already
    in the target the way ordinary punctuation transfer is (see
    ``align_paragraphs``, deliberately unrestricted). ``align_paragraphs``
    itself may have matched one of this file's *ordinary* paragraphs into a
    differently-numbered juan — fine for that paragraph's own punctuation,
    since the target's text there is unchanged either way, but not a safe
    basis for anchoring this file's *heading* there too: that would inject
    one juan's title into another's. So a match only counts as a heading
    anchor when the source file's own number corresponds to this juan's
    (same convention as the module docstring; unrestricted when either side
    has no parseable number, same as today for non-numeric filenames).
    """
    if not ref_paragraphs:
        return []
    juan_id = ref_paragraphs[0]["juan_id"]
    juan_numeric_key = _numeric_juan_key(juan_id)
    ref_by_key = {(r["juan_id"], r["para_idx"]): r for r in ref_paragraphs}

    matched_by_source: dict[tuple[str, int], int] = {}
    for m in matches:
        if m["match_type"] == "unmatched" or m["ref_juan_id"] != juan_id:
            continue
        file_numeric_key = _numeric_file_key(m["source_file"])
        if (
            juan_numeric_key is not None
            and file_numeric_key is not None
            and file_numeric_key != juan_numeric_key
        ):
            continue
        ref = ref_by_key.get((m["ref_juan_id"], m["ref_para_idx"]))
        if ref is None:
            continue
        for idx in range(m["source_para_idx"], m["source_para_end_idx"] + 1):
            matched_by_source.setdefault((m["source_file"], idx), ref["han_start"])

    by_file: dict[str, list[SourceParagraph]] = {}
    for src in source_paragraphs:
        by_file.setdefault(src["file"], []).append(src)

    insertions: list[tuple[int, str, str]] = []
    for file, paras in by_file.items():
        ordered = sorted(paras, key=lambda p: p["para_idx"])
        for pos, src in enumerate(ordered):
            level = src.get("heading")
            if not level:
                continue
            for later in ordered[pos + 1 :]:
                han_start = matched_by_source.get((file, later["para_idx"]))
                if han_start is not None:
                    insertions.append((han_start, level, src["text"]))
                    break
    return insertions


def apply_paragraph_scoped_sources(
    body_xml: str,
    ref_paragraphs: list[RefParagraph],
    matches: list[ParagraphMatch],
    source_paragraphs: list[SourceParagraph],
):
    """Insert punctuation match-by-match, each scoped to its own paragraph's
    known Han range, instead of via one reassembled multi-paragraph excerpt.

    ``apply_parallel_sources``'s global fuzzy search (via ``build_juan_source_map``)
    requires feeding it one excerpt per source file; but ``_sticker_to_tape_map``
    only maps ``equal``/``replace`` diff opcodes between that excerpt and the
    tape span it's found in -- it has no notion of a "gap" for content the
    excerpt is missing (an unmatched sentence between two matched ones, which
    is normal editorial variance). On a long, repetitive text like this
    genre, one such gap can throw off the rest of that excerpt's character
    alignment, so most of a "covered" span's punctuation silently fails to
    insert even though the span itself gets reported as covered.

    Applying each match at its own already-known ``han_start``/``han_end``
    (via ``apply_scoped_parallel_punctuation``) sidesteps this entirely: each
    scope corresponds to exactly one short, gap-free source fragment, so
    there's nothing for a "gap" to throw off.
    """
    from kanripo_import.parallel_punct import (
        Coverage,
        CoverageSpan,
        ParallelPunctResult,
        _coverage_from_intervals,
        _dedupe_seg_boundary_marks,
        _han_tape,
        apply_scoped_parallel_punctuation,
        insert_heads,
    )

    text_by_key: dict[tuple[str, int], str] = {
        (src["file"], src["para_idx"]): src["text"] for src in source_paragraphs
    }
    ref_by_key: dict[tuple[str, int], RefParagraph] = {
        (ref["juan_id"], ref["para_idx"]): ref for ref in ref_paragraphs
    }

    xml = body_xml
    # Han positions and content are stable across insertions (only non-Han
    # punctuation is ever added), so the tape can be computed once upfront
    # rather than recomputed from scratch on every match.
    tape, _ = _han_tape(_iter_xml_atoms_segmented(body_xml))
    total = len(tape)
    applied_any = False
    intervals: list[tuple[int, int]] = []
    spans: list[CoverageSpan] = []

    for match in sorted(matches, key=lambda m: m["ref_para_idx"]):
        if match["match_type"] == "unmatched":
            continue
        ref = ref_by_key.get((match["ref_juan_id"], match["ref_para_idx"]))
        if ref is None or ref["han_end"] <= ref["han_start"]:
            continue
        texts = [
            text_by_key[(match["source_file"], idx)]
            for idx in range(match["source_para_idx"], match["source_para_end_idx"] + 1)
            if (match["source_file"], idx) in text_by_key
        ]
        if not texts:
            continue
        parallel_text = " ".join(texts)
        target_han = tape[ref["han_start"] : ref["han_end"]]
        parallel_text = _trim_source_text_to_target(target_han, parallel_text)

        result = apply_scoped_parallel_punctuation(
            xml, parallel_text, ref["han_start"], ref["han_end"]
        )
        if not result["applied"]:
            continue
        xml = result["body_xml"]
        applied_any = True
        for span in result["coverage"].get("spans") or []:
            start = int(round(float(span["start"]) * total))
            end = int(round(float(span["end"]) * total))
            intervals.append((start, end))
            spans.append(span)

    if applied_any:
        xml = _dedupe_seg_boundary_marks(xml)

    # Han positions are stable across the punctuation insertions above (only
    # non-Han marks are ever added), so the head positions resolved from the
    # original ref_paragraphs still apply to the now-punctuated `xml`.
    head_insertions = _resolve_heading_insertions(ref_paragraphs, matches, source_paragraphs)
    if head_insertions:
        xml = insert_heads(xml, head_insertions)
        applied_any = True

    coverage: Coverage = _coverage_from_intervals(total, intervals, spans)
    result_payload: ParallelPunctResult = {
        "body_xml": xml,
        "coverage": coverage,
        "applied": applied_any,
    }
    return result_payload


def bridge_apply_paragraph_scoped(payload: dict) -> dict:
    body_xml = str(payload.get("body_xml") or "")
    juan_id = str(payload.get("juan_id") or "")
    matches_payload = payload.get("matches") or []
    sources_payload = payload.get("sources") or []

    ref_paragraphs = extract_ref_paragraphs(juan_id, body_xml)

    source_paragraphs: list[SourceParagraph] = []
    for entry in sources_payload:
        label = str(entry.get("label") or entry.get("id") or "source")
        text = str(entry.get("text") or "")
        source_paragraphs.extend(extract_source_paragraphs(label, text))

    juan_matches: list[ParagraphMatch] = [
        m for m in matches_payload if str(m.get("ref_juan_id") or "") == juan_id
    ]

    return apply_paragraph_scoped_sources(body_xml, ref_paragraphs, juan_matches, source_paragraphs)
