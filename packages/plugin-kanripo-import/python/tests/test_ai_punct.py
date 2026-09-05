from kanripo_import.ai_punct import (
    apply_ai_parallel_segments,
    apply_insertions,
    bridge_ai_parallel_apply,
    bridge_apply,
    bridge_list_segments,
    bridge_purge,
    bridge_reflow,
    list_segments,
    purge_punctuation,
    reflow_paragraphs,
    segment_has_punct,
    strip_ai_punct,
    verify_insertions,
    _collect_kanripo_geometry_para_after,
)
from kanripo_import.parallel_punct import assert_well_formed, han_only
from tests.fixtures.ai_punct.gold import (
    BASE_ONLY,
    BASE_WITH_COMM,
    GAIJI_PB,
    GOLD_BASE_INSERTIONS,
    GOLD_COMM_INSERTIONS,
)


def test_segment_has_punct():
    assert segment_has_punct("甲。乙") is True
    assert segment_has_punct("甲乙丙") is False


def test_list_segments_base_and_comm():
    result = list_segments(BASE_WITH_COMM)
    assert len(result["segments"]) == 3
    kinds = [seg["kind"] for seg in result["segments"]]
    assert kinds == ["text", "comm", "text"]
    assert result["has_any_punct"] is False


def test_verify_insertions_good_and_bad():
    han = "學而時習之不亦說乎"
    verified, dropped = verify_insertions(han, GOLD_BASE_INSERTIONS)
    assert dropped == 0
    assert len(verified) == 2
    assert verified[0]["global_han"] == 4

    bad, dropped_bad = verify_insertions(
        han,
        [{"afterHan": 2, "mark": "。", "left": "wrong", "occurrence": 1}],
    )
    assert bad == []
    assert dropped_bad == 1

    invalid_mark, dropped_mark = verify_insertions(
        han,
        [{"afterHan": 2, "mark": "(", "left": "而", "occurrence": 1}],
    )
    assert invalid_mark == []
    assert dropped_mark == 1


def test_apply_insertions_integrity():
    meta = list_segments(BASE_ONLY)["segments"]
    seg_id = meta[0]["id"]
    han = meta[0]["han"]
    verified, _ = verify_insertions(han, GOLD_BASE_INSERTIONS, han_start=meta[0]["han_start"])
    result = apply_insertions(BASE_ONLY, {seg_id: verified}, segment_meta=meta)
    assert result["applied"] is True
    xml = result["body_xml"]
    assert "，" in xml
    assert "。" in xml
    assert han_only(BASE_ONLY) == han_only(xml)
    assert strip_ai_punct(BASE_ONLY) == strip_ai_punct(xml)
    assert_well_formed(xml)


def test_apply_comm_note_insertions():
    meta = list_segments(BASE_WITH_COMM)["segments"]
    comm = next(seg for seg in meta if seg["kind"] == "comm")
    verified, _ = verify_insertions(
        comm["han"],
        GOLD_COMM_INSERTIONS,
        han_start=comm["han_start"],
    )
    result = apply_insertions(BASE_WITH_COMM, {comm["id"]: verified}, segment_meta=meta)
    assert result["applied"] is True
    assert "，" in result["body_xml"]
    assert "<note" in result["body_xml"]


def test_skip_already_punctuated_segment():
    punctuated = '<div type="juan"><p>學而，時習之。</p></div>'
    meta = list_segments(punctuated)["segments"]
    assert meta[0]["has_punct"] is True
    result = list_segments(punctuated)
    assert result["has_any_punct"] is True


def test_purge_punctuation():
    body = '<div type="juan"><p>學而，時習之。</p></div>'
    cleaned = purge_punctuation(body)
    assert "，" not in cleaned
    assert "。" not in cleaned
    assert han_only(body) == han_only(cleaned)
    assert_well_formed(cleaned)


def test_purge_scoped_segments():
    body = BASE_WITH_COMM.replace("學而", "學而，")
    meta = list_segments(body)["segments"]
    comm_id = next(seg["id"] for seg in meta if seg["kind"] == "comm")
    cleaned = purge_punctuation(body, scope="segments", segment_ids=[comm_id])
    assert "，" in cleaned  # base punct kept
    assert han_only(body) == han_only(cleaned)


def test_purge_han_range():
    body = '<div type="juan"><p>甲，乙。丙，丁。戊，己。</p></div>'
    # Han: 0甲 1乙 2丙 3丁 4戊 5己 — purge marks after indices 1 and 2 only
    cleaned = purge_punctuation(body, scope="han_range", han_start=1, han_end=3)
    assert "甲，" in cleaned
    assert "丁。" in cleaned
    assert "戊，" in cleaned
    assert cleaned.count("。") == 2  # after 丁 and 己; not after 乙
    assert cleaned.count("，") == 2  # after 甲 and 戊; not after 丙
    assert han_only(body) == han_only(cleaned)
    assert_well_formed(cleaned)


def test_bridge_purge_han_range():
    body = '<div type="juan"><p>甲，乙。丙，丁。</p></div>'
    purged = bridge_purge({"body_xml": body, "han_start": 0, "han_end": 2})
    assert "甲" in purged["body_xml"]
    assert "，" not in purged["body_xml"][: purged["body_xml"].index("乙")]
    assert "。" in purged["body_xml"]  # after 丁 kept


def test_reflow_paragraphs_splits_at_sentence_end():
    body = '<div type="juan"><p>第一句。第二句</p></div>'
    reflowed = reflow_paragraphs(body)
    assert reflowed.count("<p>") >= 2
    assert han_only(body) == han_only(reflowed)
    assert_well_formed(reflowed)


def test_gaiji_and_pb_preserved():
    meta = list_segments(GAIJI_PB)["segments"]
    seg = meta[0]
    verified, _ = verify_insertions(
        seg["han"],
        [{"afterHan": 3, "mark": "。", "left": "學", "occurrence": 1}],
        han_start=seg["han_start"],
    )
    result = apply_insertions(GAIJI_PB, {seg["id"]: verified}, segment_meta=meta)
    assert "<pb" in result["body_xml"]
    assert han_only(GAIJI_PB) == han_only(result["body_xml"])


def test_bridge_list_segments():
    out = bridge_list_segments({"body_xml": BASE_WITH_COMM})
    assert len(out["segments"]) == 3
    assert any("following_comm" in seg or "preceding_comm" in seg for seg in out["segments"])


def test_bridge_apply():
    meta = list_segments(BASE_ONLY)["segments"]
    seg = meta[0]
    verified, _ = verify_insertions(seg["han"], GOLD_BASE_INSERTIONS, han_start=seg["han_start"])
    out = bridge_apply(
        {
            "body_xml": BASE_ONLY,
            "verified_by_segment": {str(seg["id"]): verified},
            "segment_meta": meta,
        }
    )
    assert out["applied"] is True


def test_bridge_purge_and_reflow():
    body = '<div type="juan"><p>甲。乙</p></div>'
    purged = bridge_purge({"body_xml": body, "scope": "whole_juan"})
    assert "。" not in purged["body_xml"]
    reflowed = bridge_reflow({"body_xml": body})
    assert "<p>" in reflowed["body_xml"]


def test_apply_ai_parallel_segments():
    body = BASE_ONLY
    meta = list_segments(body)["segments"]
    seg = meta[0]
    parallel = "學而時習之，不亦說乎。"
    result = apply_ai_parallel_segments(
        body,
        [{"parallel_text": parallel, "han_start": seg["han_start"], "han_end": seg["han_end"]}],
    )
    assert result["applied"] is True
    xml = result["body_xml"]
    assert "，" in xml
    assert "。" in xml
    assert han_only(BASE_ONLY) == han_only(xml)
    assert_well_formed(xml)
    assert result["stats"]["segments_applied"] == 1


def test_bridge_ai_parallel_apply():
    meta = list_segments(BASE_ONLY)["segments"]
    seg = meta[0]
    out = bridge_ai_parallel_apply(
        {
            "body_xml": BASE_ONLY,
            "segment_parallels": [
                {
                    "parallel_text": "學而時習之，不亦說乎。",
                    "han_start": seg["han_start"],
                    "han_end": seg["han_end"],
                }
            ],
        }
    )
    assert out["applied"] is True
    assert "，" in out["body_xml"]


def test_kanripo_geometry_keeps_line_wrap_paragraph():
    long_line = "甲" * 28
    body = f'<div type="juan"><p>{long_line}</p><p>乙丙。</p></div>'
    from kanripo_import.parallel_punct import _iter_xml_atoms_segmented

    atoms = _iter_xml_atoms_segmented(body)
    para_after = _collect_kanripo_geometry_para_after(atoms)
    assert len(para_after) >= 1
    reflowed = reflow_paragraphs(body)
    assert reflowed.count("<p>") >= 2
    assert han_only(body) == han_only(reflowed)


def test_scoped_parallel_on_known_range():
    from kanripo_import.parallel_punct import apply_scoped_parallel_punctuation

    body = '<div type="juan"><p>甲乙丙丁</p></div>'
    meta = list_segments(body)["segments"][0]
    result = apply_scoped_parallel_punctuation(
        body,
        "甲，乙。丙丁。",
        meta["han_start"],
        meta["han_end"],
    )
    assert result["applied"] is True
    assert "，" in result["body_xml"]


def test_scoped_parallel_tolerates_variant_normalization():
    from kanripo_import.parallel_punct import apply_scoped_parallel_punctuation

    body = '<div type="juan"><p>甲乙庻丁</p></div>'
    meta = list_segments(body)["segments"][0]
    result = apply_scoped_parallel_punctuation(
        body,
        "甲，乙。庶丁。",
        meta["han_start"],
        meta["han_end"],
    )
    assert result["applied"] is True
    assert "，" in result["body_xml"]
    assert "庻" in result["body_xml"]


def test_scoped_parallel_trims_full_llm_output_to_selection_range():
    """Regression: LLM returns the whole passage while apply is scoped to a sub-range."""
    from kanripo_import.parallel_punct import apply_scoped_parallel_punctuation

    body = (
        '<div type="juan"><p>鄭康成則直曰河圖有九篇洛書有六篇說者謂其本</p>'
        "<p>諸緯書緯書者哀平間實始有之非古也不可據也而</p>"
        "<p>其誤有可以理證者典籍之字生于卦畫卦畫之智發</p>"
        '<p><pb n="KR1a0029_WYG_001-3a"/>于圖書易謂書契取夬為象是八卦已重而文字始生</p>'
        "<p>也</p></div>"
    )
    meta = list_segments(body)["segments"][0]
    full_parallel = (
        "鄭康成則直曰：「河圖有九篇，洛書有六篇。」說者謂其本諸緯書，緯書者，"
        "哀平間實始有之，非古也，不可據也。而其誤有可以理證者，典籍之字生於卦畫，"
        "卦畫之智發於圖書。易謂「書契取夬為象」，是八卦已重，而文字始生。"
    )
    # Selection from the second Kanripo line onward (global Han index 22).
    result = apply_scoped_parallel_punctuation(
        body,
        full_parallel,
        22,
        meta["han_end"],
    )
    assert result["applied"] is True
    xml = result["body_xml"]
    assert "緯書，" in xml
    assert "，" in xml
    assert han_only(body) == han_only(xml)
    assert_well_formed(xml)


def test_ai_parallel_scoped_failure_falls_back_to_global_overlap():
    """When scoped align fails, apply_ai_parallel_segments retries with global infix search."""
    body = (
        '<div type="juan"><p>鄭康成則直曰河圖有九篇洛書有六篇說者謂其本</p>'
        "<p>諸緯書緯書者哀平間實始有之非古也不可據也而</p>"
        "<p>其誤有可以理證者典籍之字生于卦畫卦畫之智發</p>"
        '<p><pb n="KR1a0029_WYG_001-3a"/>于圖書易謂書契取夬為象是八卦已重而文字始生</p>'
        "<p>也</p></div>"
    )
    meta = list_segments(body)["segments"][0]
    full_parallel = (
        "鄭康成則直曰：「河圖有九篇，洛書有六篇。」說者謂其本諸緯書，緯書者，"
        "哀平間實始有之，非古也，不可據也。而其誤有可以理證者，典籍之字生於卦畫，"
        "卦畫之智發於圖書。易謂「書契取夬為象」，是八卦已重，而文字始生。"
    )
    # Simulate old scoped-only failure: sub-range with full model output.
    result = apply_ai_parallel_segments(
        body,
        [
            {
                "parallel_text": full_parallel,
                "han_start": 22,
                "han_end": meta["han_end"],
            }
        ],
        reflow=False,
    )
    assert result["applied"] is True
    assert result["stats"]["align_failed"] == 0
    assert "，" in result["body_xml"]


def test_ai_parallel_on_cbeta_prefixed_body_fragment():
    """CBETA ``body`` extracts keep ``cb:`` prefixes without ``xmlns:cb`` on the fragment."""
    text = (
        "鄭康成則直曰河圖有九篇洛書有六篇說者謂其本諸緯書緯書者哀平間實始有之非古也不可據也而"
        "其誤有可以理證者典籍之字生于卦画卦画之智發于圖書易謂書契取夬為象是八卦已重而文字始生也"
    )
    body = f"<cb:div><p>{text}</p></cb:div>"
    parallel = (
        "鄭康成則直曰：「河圖有九篇，洛書有六篇。」說者謂其本諸緯書。緯書者，"
        "哀平間實始有之，非古也，不可據也。而其誤有可以理證者，典籍之字生于卦畫，"
        "卦畫之智發于圖書。易謂書契取夬為象，是八卦已重而文字始生也。"
    )
    meta = list_segments(body)["segments"][0]
    result = apply_ai_parallel_segments(
        body,
        [{"parallel_text": parallel, "han_start": 0, "han_end": meta["han_end"]}],
        reflow=False,
    )
    assert result["applied"] is True
    assert "，" in result["body_xml"]
    assert han_only(body) == han_only(result["body_xml"])
    assert_well_formed(result["body_xml"])


INLINE_COMM_BODY = (
    '<div type="juan"><p>甲乙丙丁戊'
    '<note type="comm">己庚辛</note>'
    "壬癸子丑寅卯辰巳午未</p></div>"
)


def test_scoped_parallel_after_inline_comm_note_not_shifted():
    """Regression: a text segment that follows an inline ``<note type="comm">``.

    ``list_segments`` counts the comm note's Han (``己庚辛``) in its index space,
    so ``apply_scoped_parallel_punctuation`` must build its tape the same way.
    With the note-collapsed tokenizer the range slid left by 3 and the segment
    was dropped at the ``min_map_ratio`` gate (``applied`` False).
    """
    from kanripo_import.parallel_punct import apply_scoped_parallel_punctuation

    segments = list_segments(INLINE_COMM_BODY)["segments"]
    assert [s["kind"] for s in segments] == ["text", "comm", "text"]
    post_note = segments[2]
    assert post_note["han"] == "壬癸子丑寅卯辰巳午未"

    result = apply_scoped_parallel_punctuation(
        INLINE_COMM_BODY,
        "壬癸。子丑，寅卯辰巳午未。",
        post_note["han_start"],
        post_note["han_end"],
    )
    assert result["applied"] is True
    xml = result["body_xml"]
    # Marks land on the intended characters, not shifted by the note length:
    # the whole segment is punctuated contiguously and nothing leaks into the
    # preceding run or the note itself.
    assert "壬癸。子丑，寅卯辰巳午未。" in xml
    assert "甲乙丙丁戊" in xml
    assert '<note type="comm">己庚辛</note>' in xml
    assert han_only(INLINE_COMM_BODY) == han_only(xml)
    assert_well_formed(xml)


def test_ai_parallel_punctuates_inside_comm_note_without_stamp():
    """Comm segments are punctuated *inside* the note — never wrapped or reflowed."""
    segments = list_segments(INLINE_COMM_BODY)["segments"]
    comm_seg = segments[1]
    post_note = segments[2]

    result = apply_ai_parallel_segments(
        INLINE_COMM_BODY,
        [
            {
                "parallel_text": "己，庚\n\n辛。",
                "han_start": comm_seg["han_start"],
                "han_end": comm_seg["han_end"],
            },
            {
                "parallel_text": "壬癸。子丑，寅卯辰巳午未。",
                "han_start": post_note["han_start"],
                "han_end": post_note["han_end"],
            },
        ],
        reflow=True,
    )
    xml = result["body_xml"]

    assert result["stats"]["segments_applied"] == 2
    assert result["stats"]["align_failed"] == 0
    # Marks inside the note; no <seg> stamp and no </p><p> split within it.
    assert '<note type="comm">己，庚辛。</note>' in xml
    assert "grognard:parallel-punct\">己" not in xml
    assert xml.count("<note") == 1 and xml.count("</note>") == 1
    # Post-note text segment still stamped as parallel-punct.
    assert '<seg type="grognard:parallel-punct">壬癸。' in xml
    assert han_only(INLINE_COMM_BODY) == han_only(xml)
    assert_well_formed(xml)


def test_coverage_from_punctuation_empty():
    from kanripo_import.ai_punct import coverage_from_punctuation

    body = '<div type="juan"><p>甲乙丙丁戊己庚辛壬癸</p></div>'
    cov = coverage_from_punctuation(body)
    assert cov["empty"] is True
    assert cov["ratio"] == 0.0


def test_coverage_from_punctuation_grows_after_marks():
    from kanripo_import.ai_punct import coverage_from_punctuation

    body = '<div type="juan"><p>甲乙丙丁戊己庚辛壬癸</p></div>'
    punct = '<div type="juan"><p>甲，乙。丙丁戊己庚辛壬癸</p></div>'
    before = coverage_from_punctuation(body)
    after = coverage_from_punctuation(punct)
    assert before["ratio"] == 0.0
    assert after["ratio"] > before["ratio"]
    assert after["covered_chars"] > 0
