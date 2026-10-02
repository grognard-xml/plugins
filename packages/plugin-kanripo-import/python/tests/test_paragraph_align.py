from kanripo_import.paragraph_align import (
    align_paragraphs,
    apply_paragraph_scoped_sources,
    bridge_align_folder_sources,
    bridge_apply_paragraph_scoped,
    build_juan_source_map,
    extract_ref_paragraphs,
    extract_source_paragraphs,
    missing_juan_ids,
    normalize_para_key,
    split_paragraphs,
)


def _ref(juan_id, para_idx, text):
    return {"juan_id": juan_id, "para_idx": para_idx, "text": text, "key": normalize_para_key(text)}


def _src(file, para_idx, text):
    return {"file": file, "para_idx": para_idx, "text": text, "key": normalize_para_key(text)}


def test_normalize_para_key_strips_punct_and_markup():
    assert normalize_para_key("甲、乙。<note>注</note>丙") == "甲乙注丙"


def test_split_paragraphs_blank_line():
    assert split_paragraphs("甲乙丙\n\n丁戊己\n\n\n庚辛") == ["甲乙丙", "丁戊己", "庚辛"]


def test_split_paragraphs_further_splits_long_block_on_sentences():
    # A single blank-line block spanning multiple punctuated sentences (as in
    # a ctext-style section dump) should split into one unit per sentence,
    # not stay as one giant paragraph.
    block = "甲乙丙。丁戊己！庚辛壬癸？"
    assert split_paragraphs(block) == ["甲乙丙。", "丁戊己！", "庚辛壬癸？"]


def test_split_paragraphs_keeps_a_closing_quote_with_the_sentence_it_closes():
    # A closing quote/bracket routinely sits right after the sentence-final
    # mark that ends the quoted stretch ("...二年。」郗萌曰..."). Splitting
    # right after 。 alone used to strand 」 as the *next* unit's leading
    # character -- real bug, found by spot-checking a real import: every
    # citation ending in 。」 lost its closing quote in the output.
    block = "石氏曰：「彗星出攝提，期不出二年。」郗萌曰：「彗星出攝提，群下爭起。」"
    assert split_paragraphs(block) == [
        "石氏曰：「彗星出攝提，期不出二年。」",
        "郗萌曰：「彗星出攝提，群下爭起。」",
    ]


def test_split_paragraphs_keeps_up_to_two_stacked_closing_marks():
    # A quote ending right at a title's own close too (「《書》曰：...」) --
    # both closing marks must stay with the sentence that just ended.
    block = "甲曰：「《周易》曰：「乙丙丁。」」戊己庚。"
    assert split_paragraphs(block) == [
        "甲曰：「《周易》曰：「乙丙丁。」」",
        "戊己庚。",
    ]


def test_extract_ref_paragraphs_from_body_xml():
    body = "<div type=\"juan\"><p>甲乙丙</p><p>丁戊己</p></div>"
    paras = extract_ref_paragraphs("0001", body)
    assert [p["text"] for p in paras] == ["甲乙丙", "丁戊己"]
    assert [p["para_idx"] for p in paras] == [0, 1]
    assert all(p["juan_id"] == "0001" for p in paras)


def test_extract_ref_paragraphs_han_positions():
    # Han-index positions must count only Han characters (skip tags/punct),
    # matching _han_tape(_iter_xml_atoms_segmented(...))'s index space, so
    # they can be used directly for scoped insertion.
    body = "<div type=\"juan\"><p>甲乙、丙。</p><p>丁戊己</p></div>"
    paras = extract_ref_paragraphs("0001", body)
    assert (paras[0]["han_start"], paras[0]["han_end"]) == (0, 3)
    assert (paras[1]["han_start"], paras[1]["han_end"]) == (3, 6)


def test_exact_paragraph_match_by_key():
    ref = [_ref("0001", 0, "甲乙丙")]
    src = [_src("f1.txt", 0, "甲、乙。丙")]
    matches = align_paragraphs(ref, src)
    assert len(matches) == 1
    assert matches[0]["match_type"] == "exact"
    assert matches[0]["score"] == 1.0
    assert matches[0]["source_file"] == "f1.txt"
    assert matches[0]["source_para_idx"] == 0


def test_near_miss_below_threshold_is_unmatched():
    # Shares a real bigram at the start ("甲乙", so the bigram index surfaces
    # it as a candidate) but the rest of the content genuinely diverges --
    # this should score low on overlap and land below threshold, regardless
    # of length. (A short source string that's a pure prefix/substring of a
    # longer ref is a *good* match under containment scoring -- see
    # test_short_ref_fragment_matches_within_longer_source_sentence -- so
    # that scenario belongs there, not here.)
    ref = [_ref("0001", 0, "甲乙丙丁戊己庚辛壬癸")]
    src = [_src("f1.txt", 0, "甲乙子丑寅卯辰巳午未")]
    matches = align_paragraphs(ref, src, similarity_threshold=0.85)
    assert matches[0]["match_type"] == "unmatched"
    assert matches[0]["source_file"] is None


def test_tie_break_prefers_position_after_pointer():
    # Two ref paragraphs, each matching a source paragraph exactly, but the
    # first source paragraph is a repeated stock phrase appearing twice in the
    # same file. The pointer should push the second ref match to the later
    # occurrence rather than re-picking the earlier one.
    ref = [
        _ref("0001", 0, "甲乙丙"),
        _ref("0001", 1, "甲乙丙"),
    ]
    src = [
        _src("f1.txt", 0, "甲乙丙"),
        _src("f1.txt", 1, "甲乙丙"),
    ]
    matches = align_paragraphs(ref, src)
    assert matches[0]["source_para_idx"] == 0
    assert matches[1]["source_para_idx"] == 1


def test_paragraph_spans_multiple_source_files():
    ref = [
        _ref("0001", 0, "甲乙丙"),
        _ref("0001", 1, "丁戊己"),
    ]
    src = [
        _src("f1.txt", 0, "甲乙丙"),
        _src("f2.txt", 0, "丁戊己"),
    ]
    matches = align_paragraphs(ref, src)
    juan_sources = build_juan_source_map(matches, src)
    # Different source files -- not contiguous, so these must stay as two
    # separate source entries rather than being glued into one string that
    # no longer corresponds to any real contiguous excerpt.
    assert len(juan_sources["0001"]) == 2
    assert juan_sources["0001"][0]["text"] == "甲乙丙"
    assert juan_sources["0001"][1]["text"] == "丁戊己"


def test_source_file_spans_multiple_juan():
    ref = [
        _ref("0001", 0, "甲乙丙"),
        _ref("0002", 0, "丁戊己"),
    ]
    src = [
        _src("f1.txt", 0, "甲乙丙"),
        _src("f1.txt", 1, "丁戊己"),
    ]
    matches = align_paragraphs(ref, src)
    by_juan = {(m["ref_juan_id"]): m["source_para_idx"] for m in matches}
    assert by_juan["0001"] == 0
    assert by_juan["0002"] == 1


def test_cross_juan_boilerplate_match_is_allowed_and_punctuates_normally():
    # Deliberately permissive by design: this genre repeats the same
    # sentence verbatim across structurally similar entries in different
    # juan, and borrowing punctuation for a genuinely identical sentence
    # from wherever it's found is correct -- it only ever decorates the
    # target's own, already-present Han characters, never adds new text.
    # Which of two equally-good files supplies it is not asserted here
    # (either is fine); only that the match is not rejected outright.
    boilerplate = "歲星犯庫樓一"
    ref = [_ref("3", 0, boilerplate)]
    src = [
        _src("03.txt", 0, boilerplate),
        _src("08.txt", 0, boilerplate),  # a differently-numbered file, same text
    ]
    matches = align_paragraphs(ref, src)
    assert matches[0]["match_type"] != "unmatched"
    assert matches[0]["source_file"] in ("03.txt", "08.txt")


def test_non_adjacent_same_file_matches_are_reassembled_into_one_block():
    # Two ref paragraphs both match the SAME source file but at non-adjacent
    # positions (an intervening source paragraph wasn't matched by anything).
    # They should still be reassembled into ONE block, in the file's own
    # order -- apply_parallel_sources' overlap search needs a large-enough
    # excerpt to reliably clear its match-quality thresholds; many tiny
    # per-paragraph fragments routinely fail that even when correct.
    ref = [
        _ref("0001", 0, "甲乙丙"),
        _ref("0001", 1, "壬癸子丑"),
    ]
    src = [
        _src("f1.txt", 0, "甲乙丙"),
        _src("f1.txt", 1, "丁戊己庚辛"),  # unrelated, unmatched by any ref paragraph
        _src("f1.txt", 2, "壬癸子丑"),
    ]
    matches = align_paragraphs(ref, src)
    juan_sources = build_juan_source_map(matches, src)
    assert len(juan_sources["0001"]) == 1
    assert juan_sources["0001"][0]["text"] == "甲乙丙 壬癸子丑"


def test_large_gap_same_file_matches_split_into_separate_blocks():
    # Two matched paragraphs from the same file, far apart (beyond
    # MAX_SOURCE_GAP), must NOT be merged into one excerpt -- that would
    # make find_han_overlap locate one huge, mostly-empty span, silently
    # starving punctuation insertion across most of it even though the
    # span itself gets reported as "covered".
    from kanripo_import.paragraph_align import MAX_SOURCE_GAP

    far_idx = MAX_SOURCE_GAP + 50
    ref = [
        _ref("0001", 0, "甲乙丙"),
        _ref("0001", 1, "壬癸子丑"),
    ]
    src = [_src("f1.txt", 0, "甲乙丙"), _src("f1.txt", far_idx, "壬癸子丑")]
    matches = align_paragraphs(ref, src)
    juan_sources = build_juan_source_map(matches, src)
    assert len(juan_sources["0001"]) == 2
    assert {s["text"] for s in juan_sources["0001"]} == {"甲乙丙", "壬癸子丑"}


def test_fully_unmatched_juan_is_flagged():
    ref = [
        _ref("0001", 0, "甲乙丙"),
        _ref("0002", 0, "辛壬癸"),
    ]
    src = [_src("f1.txt", 0, "甲乙丙")]
    matches = align_paragraphs(ref, src)
    juan_sources = build_juan_source_map(matches, src)
    assert juan_sources["0002"] == []
    assert missing_juan_ids(["0001", "0002"], matches) == ["0002"]


def test_short_ref_fragment_matches_within_longer_source_sentence():
    # Kanripo <p> paragraphs are often page-line fragments, shorter than a
    # full punctuated source sentence. A short fragment fully contained in a
    # much longer candidate should still match confidently (containment,
    # not a symmetric length-penalised ratio), and be labelled "fuzzy" since
    # the keys aren't literally equal.
    ref = [_ref("0001", 0, "丙丁戊")]
    src = [_src("f1.txt", 0, "甲乙丙丁戊己庚辛壬癸")]
    matches = align_paragraphs(ref, src, length_prefilter_ratio=0)
    assert matches[0]["match_type"] == "fuzzy"
    assert matches[0]["score"] == 1.0
    assert matches[0]["source_file"] == "f1.txt"


def test_boundary_straddling_ref_paragraph_matches_via_source_merge():
    # A Kanripo <p> that straddles the boundary between two source sentences
    # (tail of one, head of the next, in the SAME source file) can't fully
    # match either single source paragraph on its own, but merging the
    # source paragraph with its same-file neighbor covers it.
    ref = [_ref("0001", 0, "丙丁戊己")]  # "丙丁" is the tail of sentence 1, "戊己" the head of sentence 2
    src = [
        _src("f1.txt", 0, "甲乙丙丁"),
        _src("f1.txt", 1, "戊己庚辛"),
    ]
    matches = align_paragraphs(ref, src, similarity_threshold=0.85)
    assert matches[0]["match_type"] == "merged"
    assert matches[0]["source_para_idx"] == 0
    assert matches[0]["source_para_end_idx"] == 1


def test_low_coverage_perfect_match_still_extends_to_cover_the_rest():
    # Real bug, found by spot-checking a real import: two whole citations
    # concatenated with no separator in the raw Kanripo text (routine --
    # Kanripo's citation-boundary convention is an ideographic space, not
    # guaranteed present) become ONE ref paragraph. The first citation's own
    # source paragraph is a perfect, 1.0-scoring containment match (wholly
    # found, in order, inside the combined ref key) -- but that only covers
    # the first half, and a perfect score alone never used to trigger the
    # merge-neighbors search the way a sub-threshold score does.
    ref = [_ref("0001", 0, "甲乙丙丁戊己庚辛")]
    src = [
        _src("f1.txt", 0, "甲乙丙丁"),  # perfectly contained, but only half of ref
        _src("f1.txt", 1, "戊己庚辛"),  # the rest
    ]
    matches = align_paragraphs(ref, src)
    assert matches[0]["match_type"] == "merged"
    assert matches[0]["source_para_idx"] == 0
    assert matches[0]["source_para_end_idx"] == 1


def test_high_coverage_single_match_is_not_needlessly_extended():
    # A single candidate that already accounts for (almost) all of the ref
    # key's own length must not be widened into a worse, needlessly-merged
    # match just because a same-file neighbor happens to exist.
    ref = [_ref("0001", 0, "甲乙丙丁")]
    src = [
        _src("f1.txt", 0, "甲乙丙丁"),  # exact, full-length match
        _src("f1.txt", 1, "戊己庚辛"),  # unrelated neighbor
    ]
    matches = align_paragraphs(ref, src)
    assert matches[0]["match_type"] == "exact"
    assert matches[0]["source_para_idx"] == 0
    assert matches[0]["source_para_end_idx"] == 0


def test_merged_match_source_text_not_duplicated_in_juan_map():
    ref = [
        _ref("0001", 0, "丙丁戊己"),
        _ref("0001", 1, "壬癸"),
    ]
    src = [
        _src("f1.txt", 0, "甲乙丙丁"),
        _src("f1.txt", 1, "戊己庚辛"),
        _src("f1.txt", 2, "壬癸子丑"),
    ]
    matches = align_paragraphs(ref, src, similarity_threshold=0.85)
    juan_sources = build_juan_source_map(matches, src)
    # The merged span (paragraphs 0-1) and the following single match
    # (paragraph 2) are all contiguous in the same source file, so they
    # merge into one block -- and the merged span's text isn't duplicated.
    assert juan_sources["0001"] == [
        {
            "id": "aligned:0001",
            "label": "0001 (aligned)",
            "text": "甲乙丙丁 戊己庚辛 壬癸子丑",
        }
    ]


def test_single_paragraph_match_still_preferred_over_merge():
    # If the single ref paragraph already matches well on its own, no merge
    # should be attempted (source_para_idx == source_para_end_idx).
    ref = [_ref("0001", 0, "甲乙丙")]
    src = [_src("f1.txt", 0, "甲乙丙")]
    matches = align_paragraphs(ref, src)
    assert matches[0]["match_type"] == "exact"
    assert matches[0]["source_para_idx"] == matches[0]["source_para_end_idx"] == 0


def test_merge_window_grows_past_a_long_run_of_short_citations():
    # Real case found by spot-checking a real import: a single Kanripo <p>
    # can concatenate well over a hundred short citations with no separator
    # at all between them (observed for real: 135 <seg> stamps in one <p>).
    # The old O(window^2) search, capped at a small window, could only ever
    # match the first few before giving up -- the greedy, linear-growth
    # search must reach the whole run regardless of its length.
    n = 30
    units = [f"甲{i}乙{i}丙{i}" for i in range(n)]
    ref = [_ref("0001", 0, "".join(units))]
    src = [_src("f1.txt", i, unit) for i, unit in enumerate(units)]
    matches = align_paragraphs(ref, src)
    assert matches[0]["match_type"] == "merged"
    assert matches[0]["source_para_idx"] == 0
    assert matches[0]["source_para_end_idx"] == n - 1


def test_merge_window_growth_tolerates_a_non_improving_paragraph():
    # Real case: one paragraph along a long run whose wording has drifted
    # from this witness (routine edition variance) adds nothing to coverage
    # on its own -- growth must not give up right there when the paragraph
    # after it resumes covering real content, or it would silently truncate
    # a long citation run at the first bit of noise.
    units = ["甲一乙一丙一", "甲二乙二丙二", "完全不相關的文字無關", "甲四乙四丙四", "甲五乙五丙五"]
    ref = [_ref("0001", 0, "".join(u for i, u in enumerate(units) if i != 2))]
    src = [_src("f1.txt", i, unit) for i, unit in enumerate(units)]
    matches = align_paragraphs(ref, src)
    assert matches[0]["match_type"] == "merged"
    assert matches[0]["source_para_idx"] == 0
    assert matches[0]["source_para_end_idx"] == 4


def test_length_prefilter_excludes_dissimilar_lengths_but_keeps_valid_match():
    ref = [_ref("0001", 0, "甲乙丙丁戊")]
    src = [
        _src("f1.txt", 0, "甲乙丙丁戊"),  # same length, should match
        _src("f1.txt", 1, "甲"),  # very short, should be prefiltered out
    ]
    matches = align_paragraphs(ref, src, length_prefilter_ratio=0.5)
    assert matches[0]["source_para_idx"] == 0
    assert matches[0]["match_type"] == "exact"


def test_bridge_align_folder_sources_shape():
    payload = {
        "juan": [
            {"juan_id": "0001", "body_xml": "<div type=\"juan\"><p>甲乙丙</p></div>"},
            {"juan_id": "0002", "body_xml": "<div type=\"juan\"><p>辛壬癸</p></div>"},
        ],
        "sources": [
            {"id": "f1", "label": "0007.txt", "text": "甲、乙、丙。"},
        ],
    }
    result = bridge_align_folder_sources(payload)
    assert set(result.keys()) == {"matches", "juan_sources", "missing_juan_ids"}
    assert result["missing_juan_ids"] == ["0002"]
    assert result["juan_sources"]["0002"] == []
    assert len(result["juan_sources"]["0001"]) == 1
    assert result["juan_sources"]["0001"][0]["text"] == "甲、乙、丙。"


def test_extract_ref_paragraphs_splits_on_internal_ideographic_space():
    # A single <p> can concatenate several distinct citations separated by
    # an ideographic space (U+3000) -- this Mandoku-derived corpus's
    # convention for citation boundaries within one page-line paragraph.
    # Each must become its own alignment unit with its own Han range, or a
    # match against only one citation silently leaves the others unpunctuated.
    body = "<div type=\"juan\"><p>甲乙丙　丁戊己　庚辛壬</p></div>"
    paras = extract_ref_paragraphs("0001", body)
    assert [p["text"] for p in paras] == ["甲乙丙", "丁戊己", "庚辛壬"]
    assert (paras[0]["han_start"], paras[0]["han_end"]) == (0, 3)
    assert (paras[1]["han_start"], paras[1]["han_end"]) == (3, 6)
    assert (paras[2]["han_start"], paras[2]["han_end"]) == (6, 9)


def test_apply_paragraph_scoped_sources_inserts_punctuation_per_paragraph():
    body = "<div type=\"juan\"><p>甲乙丙</p><p>丁戊己</p></div>"
    ref_paragraphs = extract_ref_paragraphs("0001", body)
    src = [
        _src("f1.txt", 0, "甲、乙、丙。"),
        _src("f1.txt", 1, "丁、戊、己。"),
    ]
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert result["applied"] is True
    assert "甲、乙、丙。" in result["body_xml"]
    assert "丁、戊、己。" in result["body_xml"]
    assert result["coverage"]["ratio"] > 0.9


def test_apply_paragraph_scoped_sources_unaffected_by_gap_between_matched_paragraphs():
    # The bug this design fixes: an unmatched paragraph between two matched
    # ones must not degrade insertion for either of the matched ones -- each
    # is applied at its own known position, independent of the others.
    body = "<div type=\"juan\"><p>甲乙丙</p><p>庚辛壬</p><p>丁戊己</p></div>"
    ref_paragraphs = extract_ref_paragraphs("0001", body)
    src = [
        _src("f1.txt", 0, "甲、乙、丙。"),
        # no source paragraph matches "庚辛壬" at all
        _src("f1.txt", 1, "丁、戊、己。"),
    ]
    matches = align_paragraphs(ref_paragraphs, src)
    assert matches[1]["match_type"] == "unmatched"  # the middle paragraph

    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert "甲、乙、丙。" in result["body_xml"]
    assert "丁、戊、己。" in result["body_xml"]


def test_apply_paragraph_scoped_sources_trims_much_longer_source_sentence():
    # The common real-world case: a short Kanripo <p> fragment (containment-
    # matched, per align_paragraphs' own scoring) inside a MUCH longer ctext
    # sentence. apply_scoped_parallel_punctuation's own internal trim step
    # (via find_han_overlap) can reject this for short fragments with even
    # minor noise; the module's own trim must not depend on that.
    body = "<div type=\"juan\"><p>丙丁戊</p></div>"
    ref_paragraphs = extract_ref_paragraphs("0001", body)
    long_source = "甲乙、丙丁戊、己庚辛、壬癸子丑、寅卯辰巳、午未申酉、戌亥。"
    src = [_src("f1.txt", 0, long_source)]
    matches = align_paragraphs(ref_paragraphs, src, length_prefilter_ratio=0)
    assert matches[0]["match_type"] != "unmatched"

    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert result["applied"] is True
    # Should have inserted the punctuation immediately around 丙丁戊 (the
    # comma after it), not failed outright because the source is much longer
    # than the one-paragraph target scope.
    assert "丙丁戊、" in result["body_xml"]


def test_apply_paragraph_scoped_sources_keeps_opening_bracket_when_trimming():
    # A paragraph-scoped match whose source excerpt is much longer than the
    # target <p> gets trimmed down to its own Han window (see the previous
    # test) -- when that window starts right after a title-opening mark like
    # 《, the trim must not silently drop it.
    body = '<div type="juan"><p>廣雅曰夜光者月也</p></div>'
    ref_paragraphs = extract_ref_paragraphs("0001", body)
    long_source = "前文結束。《廣雅》曰：「夜光者，月也。」"
    src = [_src("f1.txt", 0, long_source)]
    matches = align_paragraphs(ref_paragraphs, src, length_prefilter_ratio=0)
    assert matches[0]["match_type"] != "unmatched"

    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert result["applied"] is True
    assert "《廣雅》" in result["body_xml"]


def test_bridge_apply_paragraph_scoped_end_to_end():
    body = "<div type=\"juan\"><p>甲乙丙</p></div>"
    matches = [
        {
            "ref_juan_id": "0001",
            "ref_para_idx": 0,
            "source_file": "0007.txt",
            "source_para_idx": 0,
            "source_para_end_idx": 0,
            "score": 1.0,
            "match_type": "exact",
        }
    ]
    payload = {
        "body_xml": body,
        "juan_id": "0001",
        "matches": matches,
        "sources": [{"id": "f1", "label": "0007.txt", "text": "甲、乙、丙。"}],
    }
    result = bridge_apply_paragraph_scoped(payload)
    assert result["applied"] is True
    assert "甲、乙、丙。" in result["body_xml"]


def test_extract_source_paragraphs_tags_heading_levels_and_strips_markers():
    # Modeled on the real ctext corpus's 01.txt, which stacks a work-title-
    # plus-juan-number line and a separate chapter-title line, both unmarked,
    # before the first `*`-marked section -- one of the rare files (2 of 118)
    # where the general "block 1 defaults to section" rule (validated as the
    # better default against the corpus's other 24 already-marked files)
    # over-promotes that second unmarked line. Accepted trade-off; see
    # extract_source_paragraphs's docstring.
    text = "開元占經 卷一\n\n天地名體\n\n*天體渾宗\n\n甲乙丙。"
    paras = extract_source_paragraphs("f1.txt", text)
    assert [(p["text"], p["heading"]) for p in paras] == [
        ("開元占經 卷一", "chapter"),
        ("天地名體", "section"),
        ("天體渾宗", "section"),
        ("甲乙丙。", None),
    ]


def test_subsection_marker_and_leading_run_stops_at_first_marker():
    # Modeled on 28.txt: chapter (unmarked) -> one `*` section -> several
    # `**` subsections, each still recognized even though the leading-titles
    # run already ended at the first marker.
    text = "歲星占六\n\n*歲星犯石氏中官\n\n**歲星犯攝提一\n\n甲乙。\n\n**歲星犯大角二\n\n丙丁。"
    paras = extract_source_paragraphs("f1.txt", text)
    assert [(p["text"], p["heading"]) for p in paras] == [
        ("歲星占六", "chapter"),
        ("歲星犯石氏中官", "section"),
        ("歲星犯攝提一", "subsection"),
        ("甲乙。", None),
        ("歲星犯大角二", "subsection"),
        ("丙丁。", None),
    ]


def test_unmarked_file_gets_chapter_then_section_defaults():
    # Modeled on 90.txt/50.txt: no `*`/`**` markup anywhere beyond the
    # chapter line. Block 0 is the chapter; every other title-shaped block
    # defaults to "section" (this can't tell "彗孛犯攝提一" apart from a true
    # subsection the way a numbered-run-aware tool like the corpus's
    # mark_headings.py script can -- it only has two buckets to work with:
    # explicit marker, or this default). A block with real sentence
    # punctuation is never a heading candidate at all, position or marker
    # notwithstanding.
    text = "彗星占下\n\n彗孛犯石氏中官一\n\n彗孛犯攝提一\n\n甲乙丙丁戊。\n\n己庚"
    paras = extract_source_paragraphs("f1.txt", text)
    assert [(p["text"], p["heading"]) for p in paras] == [
        ("彗星占下", "chapter"),
        ("彗孛犯石氏中官一", "section"),
        ("彗孛犯攝提一", "section"),
        ("甲乙丙丁戊。", None),
        ("己庚", "section"),
    ]


def test_three_or_more_asterisks_do_not_match_a_marker_level():
    # Not part of the convention (corpus-wide grep found only `*`/`**`), so
    # `_HEADING_RE` doesn't match this at all -- it falls through to the
    # ordinary "unmarked title-shaped block past index 0" default (section),
    # asterisks and all, rather than being misread as some deeper level.
    paras = extract_source_paragraphs("f1.txt", "甲乙。\n\n***丙丁")
    assert paras[1]["heading"] == "section"
    assert paras[1]["text"] == "***丙丁"


def test_heading_paragraph_is_never_a_match_candidate():
    # A short, generic title like "天地名體" would false-match somewhere
    # unrelated in a long juan under ordinary fuzzy body-text matching --
    # headings must be excluded from candidacy entirely.
    ref = [_ref("0001", 0, "天地名體")]
    src = extract_source_paragraphs("f1.txt", "天地名體")
    matches = align_paragraphs(ref, src)
    assert matches[0]["match_type"] == "unmatched"


def test_heading_anchors_on_next_matched_paragraph_and_becomes_typed_head():
    # The heading text never appears in the Kanripo body at all -- routine,
    # since chapter/section titles are often dropped in transcription. It
    # must still land correctly by anchoring on the next reference
    # paragraph that *does* match ("甲乙丙").
    body = '<div type="juan"><p>甲乙丙</p></div>'
    ref_paragraphs = extract_ref_paragraphs("0001", body)
    src = extract_source_paragraphs(
        "f1.txt", "開元占經 卷一\n\n天地名體\n\n*天體渾宗\n\n甲、乙、丙。"
    )
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert result["applied"] is True
    xml = result["body_xml"]
    assert '<head type="chapter">開元占經 卷一</head>' in xml
    assert '<head type="section">天地名體</head>' in xml
    assert '<head type="section">天體渾宗</head>' in xml
    assert (
        xml.index("開元占經 卷一")
        < xml.index("天地名體")
        < xml.index("天體渾宗")
        < xml.index("<p>")
    )
    assert "甲、乙、丙。" in xml


def test_trailing_heading_with_nothing_matched_after_it_is_dropped():
    body = '<div type="juan"><p>甲乙丙</p></div>'
    ref_paragraphs = extract_ref_paragraphs("0001", body)
    src = extract_source_paragraphs("f1.txt", "甲、乙、丙。\n\n*附錄")
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert "<head" not in result["body_xml"]


def test_heading_from_a_differently_numbered_file_does_not_cross_into_this_juan():
    # The real bug this guards against (KR3g0018_003 picking up a "太白占二"
    # heading from an unrelated file): align_paragraphs may still cross-match
    # one of 08.txt's *ordinary* paragraphs into juan "3" -- fine, see
    # test_cross_juan_boilerplate_match_is_allowed_and_punctuates_normally,
    # since that only ever decorates juan 3's own existing text. But 08.txt's
    # own heading must never ride along into a juan it doesn't correspond to
    # -- that would inject real foreign text, not just punctuation.
    body = '<div type="juan"><p>甲乙丙</p></div>'
    ref_paragraphs = extract_ref_paragraphs("3", body)
    src = extract_source_paragraphs("08.txt", "太白占二\n\n甲、乙、丙。")
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert "<head" not in result["body_xml"]
    assert "甲、乙、丙。" in result["body_xml"]


def test_heading_lands_normally_when_file_number_matches_juan_number():
    # Positive control for the test above: the same shape, but the file's
    # number genuinely corresponds to the target juan -- the heading must
    # still land exactly as it did before this gate existed.
    body = '<div type="juan"><p>甲乙丙</p></div>'
    ref_paragraphs = extract_ref_paragraphs("8", body)
    src = extract_source_paragraphs("08.txt", "太白占二\n\n甲、乙、丙。")
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert '<head type="chapter">太白占二</head>' in result["body_xml"]


def test_heading_gate_works_against_the_real_chinese_locator_juan_id():
    # The gate above used a plain "8"/"3" juan_id as a simplification -- the
    # Kanripo plugin's own meta.juan is actually a human-readable locator
    # ("卷三"), never a bare digit, and an earlier version of this gate
    # silently never engaged against real data because of exactly that gap
    # (see _numeric_juan_key). Same shape as the two tests above, but with
    # the real juan_id format this plugin actually produces.
    body = '<div type="juan"><p>甲乙丙</p></div>'
    ref_paragraphs = extract_ref_paragraphs("卷三", body)
    src = extract_source_paragraphs("08.txt", "太白占二\n\n甲、乙、丙。")
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert "<head" not in result["body_xml"]
    assert "甲、乙、丙。" in result["body_xml"]


def test_heading_gate_recognizes_front_matter_juan_ids_as_juan_zero():
    # The table-of-contents juan's own juan_id is "目錄" (no numeral at all)
    # but its pb markers (and this corpus's own ctext file "00.txt") number
    # it as juan 0 by Kanripo's own front-matter convention.
    body = '<div type="juan"><p>甲乙丙</p></div>'
    ref_paragraphs = extract_ref_paragraphs("目錄", body)
    src = extract_source_paragraphs("08.txt", "太白占二\n\n甲、乙、丙。")
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert "<head" not in result["body_xml"]

    src_own = extract_source_paragraphs("00.txt", "太白占二\n\n甲、乙、丙。")
    matches_own = align_paragraphs(ref_paragraphs, src_own)
    result_own = apply_paragraph_scoped_sources(body, ref_paragraphs, matches_own, src_own)
    assert '<head type="chapter">太白占二</head>' in result_own["body_xml"]


def test_adjacent_quote_open_is_not_duplicated_across_a_seg_boundary():
    # Real case (KR3g0018_006): the Kanripo raw text splits one citation into
    # two separate <p> units right at the seam between an attribution and its
    # quoted content ("京氏曰" | "日出于夕..."), so each half is matched
    # independently. Before the _collect_insertions fix (see
    # test_opening_mark_lands_before_the_next_han_not_after_the_previous_one),
    # both halves claimed the source's "「" -- the first as its own trailing
    # mark, the second (independently) as its own leading mark -- producing a
    # visually doubled "「「". The opening-mark-always-leads-forward fix makes
    # the first half stop claiming it at all, so there is nothing left to
    # deduplicate: the mark lands once, on the paragraph it actually opens.
    body = '<div type="juan"><p>京氏曰</p><p>日出于夕人君不祥社稷亡</p></div>'
    ref_paragraphs = extract_ref_paragraphs("1", body)
    source_text = "又曰：「日暮而出，是謂陰重，天下見兵。」京氏曰：「日出于夕，人君不祥，社稷亡。」"
    src = extract_source_paragraphs("06.txt", source_text)
    matches = align_paragraphs(ref_paragraphs, src)
    result = apply_paragraph_scoped_sources(body, ref_paragraphs, matches, src)
    assert "「「" not in result["body_xml"]
    assert "京氏曰：</seg><seg" in result["body_xml"]
    assert "「日出于夕，人君不祥，社稷亡。」" in result["body_xml"]


def test_ref_missing_its_first_char_retries_even_when_chosen_source_is_longer():
    # The chosen source paragraph can be longer than the ref (it also holds
    # the next citation's tail) while still lacking the ref's first character,
    # which lives in the previous source paragraph with its "。」". A length
    # comparison misses that; an in-order coverage count doesn't.
    body = '<div type="juan"><p>甲乙丙丁三　年戊己庚辛壬癸　又曰子丑寅卯</p></div>'
    refs = extract_ref_paragraphs("卷一", body)
    src = extract_source_paragraphs(
        "01.txt", "《甲乙》曰：「丙丁，三年。」《戊己》曰：「庚辛，壬癸；又曰：子丑寅卯。」"
    )
    matches = align_paragraphs(refs, src)
    result = apply_paragraph_scoped_sources(body, refs, matches, src)
    assert "年。」《戊己》" in result["body_xml"]


def test_tiny_unmatched_orphan_paragraph_is_folded_into_the_preceding_match():
    # A one-character ref paragraph ("死") is too short to match alone, which
    # used to strand the "。」" that follows it.
    body = (
        '<div type="juan"><p>巫咸曰月與填星同光以其月月蝕且有以徭徙亡者'
        "京房易傳曰月與太白會宿太子　死　荊州占曰月與太白聚合宿其國</p></div>"
    )
    refs = extract_ref_paragraphs("卷一", body)
    src = extract_source_paragraphs(
        "01.txt",
        "巫咸曰：「月與填星同光，以其月月蝕，且有以徭徙亡者。」京房《易傳》曰：「月與太白會宿，太子死。」"
        "《荊州占》曰：「月與太白聚合，宿其國。」",
    )
    matches = align_paragraphs(refs, src)
    result = apply_paragraph_scoped_sources(body, refs, matches, src)
    assert "太子死。」" in result["body_xml"]


def test_tiny_orphan_before_a_match_is_claimed_by_the_following_citation():
    # A title's first character ("洪") stranded as its own ref paragraph at
    # the end of the previous <p> belongs to the *next* citation's source.
    body = (
        '<div type="juan"><p>甲乙丙丁戊己　洪</p><p>範傳曰庚辛壬癸子丑寅卯　孝</p>'
        "<p>經圖曰辰巳午未申酉</p></div>"
    )
    refs = extract_ref_paragraphs("卷一", body)
    src = extract_source_paragraphs(
        "01.txt", "甲乙丙丁戊己。」《洪範傳》曰：「庚辛壬癸，子丑寅卯。」《孝經圖》曰：「辰巳午未申酉。」"
    )
    matches = align_paragraphs(refs, src)
    xml = apply_paragraph_scoped_sources(body, refs, matches, src)["body_xml"]
    assert "《洪" in xml and "《孝" in xml
