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
