"""Matching blocks of two long strings, without ``difflib``'s quadratic cost.

``difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()`` finds the longest
common substring of *every* sub-range it recurses into. Each of those searches walks every
character of ``a`` and, for each, every position where that character occurs in ``b``. Aligning one
juan (tens of thousands of Han) against a whole parallel work (about a million) therefore costs
hundreds of millions of dictionary lookups: 80 s for a normal juan and over 5 min when the two
texts match poorly (the recursion keeps the wide ``b`` range while ``a`` shrinks).

``matching_blocks`` keeps the same contract but first pins the alignment with *anchors*: runs of
``k`` characters that occur exactly once in each string, chained by their order in both strings
(longest increasing subsequence), extended to maximal exact runs. Only the gaps between anchors,
which are small, go to ``difflib``. Below ``DIFFLIB_CELLS`` (``len(a) * len(b)``) ``difflib`` is
used directly, so short inputs give exactly what they always did.

The result is a list of ``(a_start, b_start, size)`` blocks, ``size > 0``, increasing and
non-overlapping in both strings. On large inputs the blocks can differ slightly from ``difflib``'s
(it is a greedy longest-match search, so it has no unique answer either); on a real juan against
the whole of 毛詩正義, 99.96% of the characters in runs of four or more agree.
"""

from __future__ import annotations

import bisect
from collections import Counter
from difflib import SequenceMatcher

# Below this many (len(a) * len(b)) cells difflib alone is fast enough and is used unchanged.
DIFFLIB_CELLS = 4_000_000
# Anchor lengths tried in turn on a range that has no unique anchor of the previous length.
ANCHOR_LENGTHS = (12, 8, 5)
# A gap with both sides above this and no anchor of any length is left unmatched rather than
# handed to difflib (which would take minutes for little gain).
GAP_GIVE_UP = 20_000
# How far before the first / after the last anchor to look on the ``b`` side, per ``a`` character.
EDGE_SLACK = 2.0
EDGE_MARGIN = 400

Block = tuple[int, int, int]


def _difflib_blocks(a: str, b: str, a0: int, b0: int) -> list[Block]:
    return [
        (a0 + blk.a, b0 + blk.b, blk.size)
        for blk in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
        if blk.size
    ]


def _anchor_chain(a: str, b: str, a0: int, a1: int, b0: int, b1: int, k: int) -> list[tuple[int, int]]:
    """Positions ``(i, j)`` of k-grams unique in ``a[a0:a1]`` and ``b[b0:b1]``, increasing in both."""
    if a1 - a0 < k or b1 - b0 < k:
        return []
    count_a = Counter(a[i : i + k] for i in range(a0, a1 - k + 1))
    seen_b: dict[str, int] = {}
    dup_b: set[str] = set()
    for j in range(b0, b1 - k + 1):
        gram = b[j : j + k]
        if gram in seen_b:
            dup_b.add(gram)
        else:
            seen_b[gram] = j
    pairs = []
    for i in range(a0, a1 - k + 1):
        gram = a[i : i + k]
        j = seen_b.get(gram)
        if j is not None and gram not in dup_b and count_a[gram] == 1:
            pairs.append((i, j))
    # longest increasing subsequence on j (pairs are already in increasing i)
    tails: list[int] = []
    tail_at: list[int] = []
    prev = [-1] * len(pairs)
    for n, (_, j) in enumerate(pairs):
        pos = bisect.bisect_left(tails, j)
        if pos == len(tails):
            tails.append(j)
            tail_at.append(n)
        else:
            tails[pos] = j
            tail_at[pos] = n
        prev[n] = tail_at[pos - 1] if pos else -1
    chain: list[tuple[int, int]] = []
    n = tail_at[-1] if tail_at else -1
    while n != -1:
        chain.append(pairs[n])
        n = prev[n]
    chain.reverse()
    return chain


def _runs_from_anchors(
    a: str, b: str, a0: int, a1: int, b0: int, b1: int, chain: list[tuple[int, int]], k: int
) -> list[Block]:
    """Merge anchors on one diagonal and grow each run to the longest exact match, inside the range."""
    merged: list[list[int]] = []
    for i, j in chain:
        if merged and merged[-1][0] + merged[-1][2] >= i and merged[-1][1] - merged[-1][0] == j - i:
            merged[-1][2] = max(merged[-1][2], i + k - merged[-1][0])
        else:
            merged.append([i, j, k])
    runs: list[Block] = []
    for i, j, size in merged:
        while i > a0 and j > b0 and a[i - 1] == b[j - 1]:
            i -= 1
            j -= 1
            size += 1
        while i + size < a1 and j + size < b1 and a[i + size] == b[j + size]:
            size += 1
        if runs:
            pi, pj, ps = runs[-1]
            cut = max(pi + ps - i, pj + ps - j)  # growing can make neighbours overlap in a or b
            if cut > 0:
                if cut >= size:
                    continue
                i += cut
                j += cut
                size -= cut
        runs.append((i, j, size))
    return runs


def _solve(a: str, b: str, a0: int, a1: int, b0: int, b1: int, out: list[Block]) -> None:
    na, nb = a1 - a0, b1 - b0
    if na <= 0 or nb <= 0:
        return
    if na * nb <= DIFFLIB_CELLS:
        out.extend(_difflib_blocks(a[a0:a1], b[b0:b1], a0, b0))
        return
    runs: list[Block] = []
    for k in ANCHOR_LENGTHS:
        chain = _anchor_chain(a, b, a0, a1, b0, b1, k)
        if chain:
            runs = _runs_from_anchors(a, b, a0, a1, b0, b1, chain, k)
            break
    if not runs:
        if na <= GAP_GIVE_UP or nb <= GAP_GIVE_UP:
            out.extend(_difflib_blocks(a[a0:a1], b[b0:b1], a0, b0))
        return
    # leading edge: the ``b`` side is bounded by how much ``a`` precedes the first anchor
    first_i, first_j, _ = runs[0]
    lead = first_i - a0
    _solve(a, b, a0, first_i, max(b0, first_j - int(lead * EDGE_SLACK) - EDGE_MARGIN), first_j, out)
    for (i1, j1, s1), (i2, j2, _s2) in zip(runs, runs[1:]):
        out.append((i1, j1, s1))
        _solve(a, b, i1 + s1, i2, j1 + s1, j2, out)
    last_i, last_j, last_s = runs[-1]
    out.append((last_i, last_j, last_s))
    tail = a1 - (last_i + last_s)
    _solve(a, b, last_i + last_s, a1, last_j + last_s,
           min(b1, last_j + last_s + int(tail * EDGE_SLACK) + EDGE_MARGIN), out)


def matching_blocks(a: str, b: str) -> list[Block]:
    """Blocks ``(a_start, b_start, size)`` of common substrings, in order, like difflib's."""
    if not a or not b:
        return []
    out: list[Block] = []
    _solve(a, b, 0, len(a), 0, len(b), out)
    out.sort()
    merged: list[Block] = []
    for i, j, size in out:
        if merged:
            pi, pj, ps = merged[-1]
            if pi + ps == i and pj + ps == j:
                merged[-1] = (pi, pj, ps + size)
                continue
            if i < pi + ps or j < pj + ps:  # never overlap: drop what a neighbour already covers
                cut = max(pi + ps - i, pj + ps - j)
                if cut >= size:
                    continue
                i += cut
                j += cut
                size -= cut
        merged.append((i, j, size))
    return merged


class Haystack:
    """k-gram index of one long text, built once, to locate many short needles in it.

    ``find_han_overlap(pool, note)`` is called once per commentary note against the same pool of
    several hundred thousand characters; difflib walks the whole pool every time (about a second per
    note). ``candidate_window`` finds, from the k-grams the note shares with the pool, the stretch
    where it sits, so only that stretch needs the exact (difflib) comparison.
    """

    K = 5
    MAX_POSITIONS = 8  # a k-gram found at more places than this carries no information
    BIN = 128  # diagonals (pool position minus needle position) are grouped in bins this wide
    MARGIN = 96
    MIN_VOTES = 3

    def __init__(self, text: str) -> None:
        self.text = text
        k = self.K
        index: dict[str, int | tuple[int, ...] | None] = {}
        for pos in range(len(text) - k + 1):
            gram = text[pos : pos + k]
            seen = index.get(gram, 0)
            if seen == 0:
                index[gram] = pos
            elif seen is None:
                continue
            elif isinstance(seen, int):
                index[gram] = (seen, pos)
            elif len(seen) >= self.MAX_POSITIONS:
                index[gram] = None
            else:
                index[gram] = (*seen, pos)
        self._index = index

    def candidate_window(self, needle: str) -> tuple[int, int] | None:
        """``(start, end)`` of the stretch of the text most likely to hold ``needle``, or None."""
        k = self.K
        if len(needle) < k:
            return None
        votes: dict[int, int] = {}
        index = self._index
        for i in range(len(needle) - k + 1):
            hit = index.get(needle[i : i + k])
            if hit is None:
                continue
            for pos in (hit,) if isinstance(hit, int) else hit:
                bin_ = (pos - i) // self.BIN
                votes[bin_] = votes.get(bin_, 0) + 1
        if not votes:
            return None
        best_bin = max(votes, key=lambda b: (votes[b] + votes.get(b - 1, 0) + votes.get(b + 1, 0), -b))
        best = votes[best_bin] + votes.get(best_bin - 1, 0) + votes.get(best_bin + 1, 0)
        if best < self.MIN_VOTES:
            return None
        start = max(0, (best_bin - 1) * self.BIN - self.MARGIN)
        end = min(len(self.text), (best_bin + 2) * self.BIN + len(needle) + self.MARGIN)
        return start, end


_haystack_cache: list = [None, None]  # [text, Haystack]: one entry, kept while the same string is used


def haystack_for(text: str) -> Haystack:
    """The index of ``text``, reused while the very same string object keeps being queried."""
    if _haystack_cache[0] is not text:
        _haystack_cache[0], _haystack_cache[1] = text, Haystack(text)
    return _haystack_cache[1]
