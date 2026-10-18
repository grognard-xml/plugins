"""fast_align.matching_blocks: difflib's answer for small inputs, anchored for large ones."""

import random
import time
from difflib import SequenceMatcher

import pytest

from kanripo_import import fast_align
from kanripo_import.fast_align import matching_blocks

# Han-like alphabet with a skewed frequency, like running text: a few characters (之 也 不 …)
# are very common, which is what makes difflib slow on a long ``b``.
ALPHABET = [chr(0x4E00 + i) for i in range(1500)]
WEIGHTS = [1.0 / (i + 1) for i in range(len(ALPHABET))]


def text(rng: random.Random, n: int) -> str:
    return "".join(rng.choices(ALPHABET, weights=WEIGHTS, k=n))


def difflib_blocks(a: str, b: str):
    return [(m.a, m.b, m.size) for m in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks() if m.size]


def edited(rng: random.Random, s: str, rate: float) -> str:
    """``s`` with substitutions, insertions and deletions at roughly ``rate`` per character."""
    out = []
    for ch in s:
        r = rng.random()
        if r < rate / 3:
            continue  # deletion
        if r < 2 * rate / 3:
            out.append(rng.choice(ALPHABET))  # substitution
            continue
        out.append(ch)
        if r > 1 - rate / 3:
            out.append(rng.choice(ALPHABET))  # insertion
    return "".join(out)


def assert_valid(a: str, b: str, blocks) -> None:
    prev_a = prev_b = 0
    for i, j, size in blocks:
        assert size > 0
        assert a[i : i + size] == b[j : j + size]
        assert i >= prev_a and j >= prev_b  # increasing, non-overlapping in both strings
        prev_a, prev_b = i + size, j + size


def matched(blocks, at_least: int = 1) -> int:
    return sum(size for _, _, size in blocks if size >= at_least)


def test_small_inputs_are_exactly_difflib():
    rng = random.Random(1)
    for _ in range(40):
        a, b = text(rng, rng.randint(0, 300)), text(rng, rng.randint(0, 600))
        assert matching_blocks(a, b) == difflib_blocks(a, b)


def test_empty_and_identical():
    assert matching_blocks("", "abc") == [] and matching_blocks("abc", "") == []
    s = text(random.Random(2), 5000)
    assert matching_blocks(s, s) == [(0, 0, len(s))]


@pytest.fixture
def force_anchored(monkeypatch):
    """Use the anchored path on test-sized inputs."""
    monkeypatch.setattr(fast_align, "DIFFLIB_CELLS", 50_000)


def test_identical_and_embedded_strings_with_anchors(force_anchored):
    rng = random.Random(3)
    s = text(rng, 30_000)
    assert matching_blocks(s, s) == [(0, 0, len(s))]
    b = text(rng, 20_000) + s[5000:9000] + text(rng, 20_000)
    blocks = matching_blocks(s[5000:9000], b)
    assert_valid(s[5000:9000], b, blocks)
    assert matched(blocks, 50) >= 3990  # the embedded copy is found whole, wherever it sits


def test_edited_copy_matches_what_difflib_finds(force_anchored):
    rng = random.Random(4)
    for rate in (0.0, 0.02, 0.08):
        sticker = text(rng, 25_000)
        start = rng.randint(2000, 8000)
        a = edited(rng, sticker[start : start + 1500], rate)
        fast = matching_blocks(a, sticker)
        assert_valid(a, sticker, fast)
        slow = difflib_blocks(a, sticker)
        # difflib has no unique answer either, so compare how much it finds, not the blocks
        assert matched(fast, 4) >= 0.97 * matched(slow, 4), (rate, matched(fast, 4), matched(slow, 4))
        assert matched(fast, 10) >= 0.95 * matched(slow, 10), (rate, matched(fast, 10), matched(slow, 10))


def test_text_with_unrelated_stretches_in_the_middle(force_anchored):
    rng = random.Random(5)
    sticker = text(rng, 25_000)
    a = sticker[3000:3600] + text(rng, 400) + sticker[3600:4200]  # 400 foreign characters
    blocks = matching_blocks(a, sticker)
    assert_valid(a, sticker, blocks)
    assert matched(blocks, 10) >= 1100


def test_unrelated_texts_finish_quickly_and_stay_valid(force_anchored):
    rng = random.Random(6)
    a, b = text(rng, 3000), text(rng, 40_000)
    t0 = time.time()
    blocks = matching_blocks(a, b)
    assert time.time() - t0 < 10
    assert_valid(a, b, blocks)


def test_repetitive_text_without_unique_anchors_does_not_hang(force_anchored):
    a = "之也" * 800
    b = "之也" * 5000
    t0 = time.time()
    blocks = matching_blocks(a, b)
    assert time.time() - t0 < 10
    assert_valid(a, b, blocks)


def test_a_whole_juan_against_a_whole_work_is_fast():
    """The real shape: ~40k characters against ~1M. difflib needs 80 s to several minutes here."""
    rng = random.Random(7)
    work = text(rng, 1_000_000)
    juan = edited(rng, work[400_000:440_000], 0.03)
    t0 = time.time()
    blocks = matching_blocks(juan, work)
    elapsed = time.time() - t0
    assert elapsed < 20, elapsed
    assert_valid(juan, work, blocks)
    assert matched(blocks, 10) >= 0.85 * len(juan)
    assert all(abs((j - i) - 400_000) < 1500 for i, j, size in blocks if size >= 10)


# ---- Haystack / find_han_overlap fast path -------------------------------------------------

from kanripo_import import parallel_punct  # noqa: E402
from kanripo_import.fast_align import Haystack, haystack_for  # noqa: E402


def test_haystack_finds_where_an_edited_needle_sits():
    rng = random.Random(10)
    pool = text(rng, 200_000)
    for _ in range(25):
        start = rng.randint(0, len(pool) - 2000)
        needle = edited(rng, pool[start : start + rng.randint(30, 600)], 0.05)
        window = haystack_for(pool).candidate_window(needle)
        assert window is not None
        w0, w1 = window
        assert w0 <= start and start + len(needle) - 40 <= w1  # the true place is inside the window
        assert w1 - w0 < len(needle) + 700


def test_haystack_gives_up_on_an_unrelated_needle():
    rng = random.Random(11)
    pool = text(rng, 100_000)
    other = "".join(rng.choices([chr(0x6000 + i) for i in range(500)], k=300))  # characters not in the pool
    assert haystack_for(pool).candidate_window(other) is None
    assert haystack_for(pool).candidate_window("短") is None


def test_haystack_is_reused_only_for_the_same_string_object():
    a = text(random.Random(12), 2000)
    assert haystack_for(a) is haystack_for(a)
    assert haystack_for(a) is not haystack_for(a + "x")


def test_find_han_overlap_fast_path_agrees_with_difflib(monkeypatch):
    rng = random.Random(13)
    pool = text(rng, 60_000)
    cases = []
    for rate in (0.0, 0.03, 0.1, 0.4):
        for _ in range(8):
            start = rng.randint(0, len(pool) - 800)
            cases.append(edited(rng, pool[start : start + rng.randint(40, 500)], rate))
    cases.append(text(rng, 200))  # unrelated
    slow = [parallel_punct.find_han_overlap(pool, note) for note in cases]  # default threshold: difflib
    monkeypatch.setattr(parallel_punct, "FUZZY_WINDOW_CELLS", 1000)  # force the windowed path
    fast = [parallel_punct.find_han_overlap(pool, note) for note in cases]
    for note, s, f in zip(cases, slow, fast):
        assert (s is None) == (f is None), (len(note), s, f)
        if s is not None:
            assert abs(s[0] - f[0]) <= 3 and abs(s[1] - f[1]) <= 3, (s, f)


def _original_slice(text, han_start, han_end):
    """``_slice_text_by_han_range`` as it was before the Han positions were cached."""
    han, opening = parallel_punct.HAN_RE, parallel_punct._OPENING_PUNCT_CHARS
    if han_start >= han_end:
        return ""
    count, start_char, end_char = 0, None, len(text)
    for index, char in enumerate(text):
        if han.fullmatch(char):
            if count == han_start:
                start_char = index
            count += 1
            if count == han_end:
                end_char = index + 1
                break
    if start_char is None:
        return ""
    while start_char > 0 and text[start_char - 1] in opening:
        start_char -= 1
    while end_char < len(text) and not han.fullmatch(text[end_char]):
        end_char += 1
    return text[start_char:end_char]


def test_slice_by_han_range_matches_the_original_scan():
    rng = random.Random(21)
    alphabet = list("甲乙丙丁戊己庚辛壬癸𪁺𠀀") + list("，。、「」『』《》（）〔〕 \n<>a1")
    for _ in range(1500):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        for _ in range(5):
            start, end = rng.randint(0, 40), rng.randint(-1, 45)
            assert parallel_punct._slice_text_by_han_range(s, start, end) == _original_slice(s, start, end)


def test_find_han_overlap_with_a_longer_sticker_agrees_with_difflib(monkeypatch):
    """A whole parallel chapter (sticker) against a short body excerpt (tape): indices are in tape."""
    rng = random.Random(14)
    chapter = text(rng, 60_000)
    cases = []
    for rate in (0.0, 0.03, 0.1):
        for _ in range(8):
            start = rng.randint(0, len(chapter) - 800)
            cases.append(edited(rng, chapter[start : start + rng.randint(40, 500)], rate))
    cases.append(text(rng, 200))
    slow = [parallel_punct.find_han_overlap(note, chapter) for note in cases]
    monkeypatch.setattr(parallel_punct, "FUZZY_WINDOW_CELLS", 1000)
    fast = [parallel_punct.find_han_overlap(note, chapter) for note in cases]
    for note, s, f in zip(cases, slow, fast):
        assert (s is None) == (f is None), (len(note), s, f)
        if s is not None:
            assert abs(s[0] - f[0]) <= 3 and abs(s[1] - f[1]) <= 3, (s, f)
