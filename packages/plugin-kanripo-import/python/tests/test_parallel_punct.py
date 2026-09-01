from xml.etree import ElementTree as ET

from kanripo_import.parallel_punct import (
    apply_parallel_punctuation,
    apply_parallel_segmented,
    apply_parallel_sources,
    assert_well_formed,
    coverage_from_stamps,
    find_han_overlap,
    han_only,
    merge_split_comm_notes,
    parse_body_segments,
    parse_reference_segments,
    parse_wikisource_comm_segments,
    strip_wikisource_commentary,
)


def test_superset_parallel_merges_nearby_blocks():
    tape = "".join(chr(0x4e00 + i) for i in range(320))
    sticker_chars = list(tape)
    sticker_chars[50] = "异"
    sticker_chars[150] = "异"
    sticker = "".join(sticker_chars) + "尾部"
    overlap = find_han_overlap(tape, sticker)
    assert overlap == (0, len(tape))


def test_strip_wikisource_commentary():
    from kanripo_import.parallel_punct import strip_wikisource_commentary

    assert strip_wikisource_commentary("君子曰〈注釋〉學") == "君子曰學"


def test_han_only_strips_punct():
    assert han_only("甲、乙。丙") == "甲乙丙"


def test_infix_excerpt_in_middle():
    tape = "甲乙丙丁戊己庚"
    sticker = "丙丁戊"
    assert find_han_overlap(tape, sticker) == (2, 5)


def test_wrong_text_empty():
    assert find_han_overlap("甲乙丙丁戊己庚", "辛壬癸") is None


def test_apply_punct_superset_parallel_with_variants():
    """Punctuation maps correctly when parallel is a long superset with char variants."""
    header = "書名序跋" * 20
    shared = "君子曰學不可以巳青取之於藍而青於藍"
    body = f'<div type="juan"><p>{"序" * 4}{shared}終</p></div>'
    parallel = header + "君子曰學不可以已青出之於藍而青於藍，"
    result = apply_parallel_punctuation(body, parallel)
    assert result["applied"] is True
    assert "，" in result["body_xml"]


def test_apply_punct_middle_and_stamp():
    body = '<div type="juan"><p>甲乙丙丁戊己庚</p></div>'
    parallel = "丙、丁。戊\n\n"
    result = apply_parallel_punctuation(body, parallel)
    assert result["applied"] is True
    xml = result["body_xml"]
    assert 'type="ljb:parallel-punct"' in xml
    assert "丙、丁。" in xml
    assert "戊" in xml
    assert xml.count("<p>") >= 1
    assert xml.startswith("<div")
    cov = result["coverage"]
    assert cov["empty"] is False
    assert 0 < cov["start"] < cov["end"] < 1
    assert "甲乙" in xml
    assert "己庚" in xml
    assert cov["spans"]


def test_wrong_parallel_does_not_punctuate():
    body = '<div type="juan"><p>甲乙丙丁</p></div>'
    result = apply_parallel_punctuation(body, "完全不相關的文字。")
    assert result["applied"] is False
    assert result["coverage"]["empty"] is True
    assert result["body_xml"] == body


def test_pb_and_note_stay_tokens():
    body = '<div type="juan"><p>甲<pb n="1a"/><note type="comm">注</note>乙丙</p></div>'
    result = apply_parallel_punctuation(body, "甲乙。丙")
    assert result["applied"] is True
    assert '<pb n="1a"/>' in result["body_xml"]
    assert '<note type="comm">注</note>' in result["body_xml"]
    assert "乙。" in result["body_xml"]
    assert "丙" in result["body_xml"]


def test_paragraph_split_is_well_formed():
    body = '<div type="juan"><p>甲乙丙丁戊己庚</p></div>'
    result = apply_parallel_punctuation(body, "丙丁\n\n戊")
    xml = result["body_xml"]
    assert result["applied"] is True
    assert xml.count("<p>") == 2
    assert_well_formed(xml)
    ET.fromstring(xml)


def test_merge_kanripo_line_paragraphs_at_sentences():
    body = '<div type="juan"><p>君子曰學</p><p>不可以已</p></div>'
    result = apply_parallel_punctuation(body, "君子曰：學不可以已。")
    xml = result["body_xml"]
    assert result["applied"] is True
    assert xml.count("<p>") == 1
    assert "：" in xml
    assert "。" in xml
    assert_well_formed(xml)


def test_comm_note_stays_with_preceding_sentence():
    body = (
        '<div type="juan"><p>冰水爲之而寒於水</p>'
        '<p><note type="comm">過其本性也</note>木直中繩</p></div>'
    )
    parallel = "冰，水爲之而寒於水。木直中繩，"
    result = apply_parallel_punctuation(body, parallel)
    xml = result["body_xml"]
    assert result["applied"] is True
    assert "冰，水爲之而寒於水。" in xml
    assert '<note type="comm">過其本性也</note>' in xml
    assert "木直中繩，" in xml
    assert_well_formed(xml)


def test_source_comm_first_mixed_paragraph_preserved():
    body = '<div type="juan"><p><note type="comm">蚓同</note>蟹六跪</p></div>'
    result = apply_parallel_punctuation(body, "蟹六跪，")
    xml = result["body_xml"]
    assert '<note type="comm">蚓同</note>' in xml
    assert "蟹六跪" in xml
    assert_well_formed(xml)


def test_two_sources_two_spans():
    body = '<div type="juan"><p>甲乙丙丁戊己庚</p></div>'
    result = apply_parallel_sources(
        body,
        [
            {"id": "a", "label": "Head", "text": "甲、乙"},
            {"id": "b", "label": "Tail", "text": "己。庚"},
        ],
    )
    assert result["applied"] is True
    assert len(result["coverage"]["spans"]) == 2
    assert result["coverage"]["spans"][0]["source"] == "Head"
    assert result["coverage"]["spans"][1]["source"] == "Tail"
    assert "甲、乙" in result["body_xml"]
    assert "己。" in result["body_xml"]
    assert "庚" in result["body_xml"]
    assert_well_formed(result["body_xml"])


def test_second_source_does_not_nest_seg():
    body = '<div type="juan"><p>甲乙丙丁戊己庚</p></div>'
    once = apply_parallel_punctuation(body, "丙丁戊")
    twice = apply_parallel_punctuation(once["body_xml"], "丙丁戊")
    assert twice["body_xml"].count('<seg type="ljb:parallel-punct">') == 1
    assert_well_formed(twice["body_xml"])


def test_coverage_from_stamps():
    body = '<div type="juan"><p>甲乙丙丁戊己庚</p></div>'
    applied = apply_parallel_punctuation(body, "丙、丁。戊")
    stamped = coverage_from_stamps(applied["body_xml"])
    assert stamped["empty"] is False
    assert stamped["covered_chars"] > 0
    assert stamped["spans"]


def test_coverage_from_legacy_ana_stamps():
    # Files imported before the switch to `type` carry `ana="…"` — still read.
    legacy = (
        '<div type="juan"><p>甲乙<seg ana="ljb:parallel-punct">丙、丁。</seg>戊己庚</p></div>'
    )
    stamped = coverage_from_stamps(legacy)
    assert stamped["empty"] is False
    assert stamped["covered_chars"] > 0


def test_unrelated_source_in_list_is_ignored():
    body = '<div type="juan"><p>甲乙丙丁戊己庚</p></div>'
    result = apply_parallel_sources(
        body,
        [
            {"id": "bad", "label": "Wrong", "text": "完全不相關的文字。"},
            {"id": "ok", "label": "Ok", "text": "丁戊己"},
        ],
    )
    assert result["applied"] is True
    assert len(result["coverage"]["spans"]) == 1
    assert result["coverage"]["spans"][0]["source"] == "Ok"
    assert "完全" not in result["body_xml"]


def test_merge_split_comm_notes():
    body = (
        '<p>甲<note type="comm">注一</note></p>'
        '<p><note type="comm">注二</note>乙</p>'
    )
    merged = merge_split_comm_notes(body)
    assert merged == '<p>甲<note type="comm">注一注二</note>乙</p>'


def test_parse_reference_segments_inlinecomment():
    ref = '或曰：賦者。<span class="inlinecomment">毛詩序曰。</span>昔成康。'
    segments = parse_reference_segments(ref)
    assert [seg["kind"] for seg in segments] == ["text", "comm", "text"]
    assert "或曰" in segments[0]["text"]
    assert "毛詩序" in segments[1]["text"]


def test_parse_body_segments_text_and_comm():
    body = '<p>甲乙<note type="comm">丙丁</note>戊</p>'
    segments = parse_body_segments(body)
    assert [seg["kind"] for seg in segments] == ["text", "comm", "text"]
    assert segments[0]["han"] == "甲乙"
    assert segments[1]["han"] == "丙丁"
    assert segments[2]["han"] == "戊"


def test_segmented_punct_main_and_comm():
    body = (
        '<div type="juan"><p>甲乙<note type="comm">丙丁</note>戊</p></div>'
    )
    parallel = '甲、乙。<span class="inlinecomment">丙，丁。</span>戊。'
    result = apply_parallel_segmented(body, parallel)
    assert result["applied"] is True
    xml = result["body_xml"]
    assert "甲、乙" in xml
    assert "丙，丁" in xml
    assert "戊。" in xml
    assert 'type="ljb:parallel-punct"' in xml
    assert result["coverage"]["empty"] is False
    assert_well_formed(xml)


def test_segmented_after_merge_split_comm():
    body = (
        '<div type="juan"><p>甲<note type="comm">乙</note></p>'
        '<p><note type="comm">丙</note>丁</p></div>'
    )
    parallel = '甲。<span class="inlinecomment">乙丙。</span>丁。'
    result = apply_parallel_segmented(body, parallel)
    assert result["applied"] is True
    assert "乙丙" in result["body_xml"]
    assert "</p><p><note" not in result["body_xml"]
    assert_well_formed(result["body_xml"])


def test_segmented_skips_prefix_not_in_reference():
    body = (
        '<div type="juan"><p>欽定四庫全書'
        '<note type="comm">注</note>甲乙</p></div>'
    )
    parallel = '甲、乙。'
    result = apply_parallel_segmented(body, parallel)
    assert result["applied"] is True
    assert "甲、乙" in result["body_xml"]
    assert "欽定" in result["body_xml"]
    assert_well_formed(result["body_xml"])


def test_segmented_stamp_reopens_after_paragraph():
    body = (
        '<div type="juan"><p>甲乙丙</p><p>丁戊</p></div>'
    )
    parallel = "甲、乙。丙丁。戊。"
    result = apply_parallel_segmented(body, parallel)
    assert result["applied"] is True
    xml = result["body_xml"]
    assert "</seg></p><p><seg" in xml
    assert_well_formed(xml)


def test_segmented_stamp_splits_around_note():
    body = (
        '<div type="juan"><p>甲乙<note type="comm">丙</note>丁</p></div>'
    )
    parallel = '甲、乙。<span class="inlinecomment">丙。</span>丁。'
    result = apply_parallel_segmented(body, parallel)
    assert result["applied"] is True
    xml = result["body_xml"]
    assert "甲、乙" in xml
    assert "丙。" in xml
    assert "丁。" in xml
    assert "<note type=\"comm\"><seg" in xml
    assert_well_formed(xml)


def test_reflow_merges_indented_kanripo_line_paragraphs():
    body = (
        '<div type="juan">\n'
        '        <p>漢承戰國餘烈</p>\n'
        '        <p>多豪猾之民</p>\n'
        '        </div>'
    )
    parallel = "漢承戰國餘烈，多豪猾之民。"
    result = apply_parallel_punctuation(body, parallel)
    xml = result["body_xml"]
    assert result["applied"] is True
    assert xml.count("<p>") == 1
    assert "漢承戰國餘烈，多豪猾之民。" in xml
    assert_well_formed(xml)


def test_tape_mode_splits_at_wikisource_blank_lines_only():
    body = (
        '<div type="juan"><p>杜篤字季雅京兆杜陵人也</p>'
        '<p>高祖延年宣帝時為御史大夫</p>'
        '<p>篤少博學不修小節</p></div>'
    )
    parallel = "杜篤字季雅，京兆杜陵人也。高祖延年，宣帝時為御史大夫。\n\n篤少博學，不修小節。"
    result = apply_parallel_punctuation(body, parallel)
    xml = result["body_xml"]
    assert result["applied"] is True
    assert xml.count("<p>") == 2
    assert "杜篤字季雅，京兆杜陵人也。高祖延年，宣帝時為御史大夫。" in xml
    assert "篤少博學，不修小節。" in xml
    assert_well_formed(xml)


def test_tape_mode_does_not_split_every_sentence():
    """Wikisource periods add punctuation; Kanripo line wraps merge; WS blank lines split."""
    body = (
        '<div type="juan"><p>劉焉字君郎江夏竟陵人也</p>'
        '<p>魯恭王後也</p><p>肅宗時徙竟陵</p></div>'
    )
    parallel = "劉焉字君郎，江夏竟陵人也。魯恭王後也。肅宗時，徙竟陵。"
    result = apply_parallel_punctuation(body, parallel)
    xml = result["body_xml"]
    assert result["applied"] is True
    assert "，" in xml and "。" in xml
    assert xml.count("<p>") == 1
    assert_well_formed(xml)
    body = '<div type="juan"><p>或曰賦者古詩之流也昔成康沒</p></div>'
    parallel = (
        '或曰：賦者，古詩之流也。'
        '<span class="inlinecomment">注釋。</span>'
        '昔成康沒而頌聲寢。'
    )
    result = apply_parallel_punctuation(body, parallel)
    assert result["applied"] is True
    assert "或曰" in result["body_xml"]
    assert "。" in result["body_xml"]


def test_parse_wikisource_comm_segments():
    ref = "甲〈過其本性也，〉乙〈楊倞曰：〉丙"
    segments = parse_wikisource_comm_segments(ref)
    assert len(segments) == 2
    assert segments[0]["text"] == "過其本性也，"
    assert "楊倞" in segments[1]["text"]


def test_tape_then_wikisource_comm_pass():
    body = (
        '<div type="juan"><p>甲<note type="comm">過其本性也</note>乙</p></div>'
    )
    parallel = "甲〈過其本性也，〉乙。"
    result = apply_parallel_sources(
        body,
        [{"id": "ws", "label": "Wikisource", "text": parallel, "kind": "wikisource"}],
    )
    assert result["applied"] is True
    xml = result["body_xml"]
    assert "甲" in xml
    assert "，" in xml
    assert "乙。" in xml or "。" in xml
    assert_well_formed(xml)
    comm_spans = [
        span for span in result["coverage"]["spans"] if str(span.get("source", "")).endswith(":comm")
    ]
    assert comm_spans


def test_comm_pass_one_note_per_bracket():
    body = (
        '<div type="juan"><p>甲'
        '<note type="comm">丙</note>丁'
        '<note type="comm">戊</note>乙</p></div>'
    )
    parallel = "甲〈丙，〉丁〈戊。〉乙。"
    result = apply_parallel_sources(body, [{"id": "ws", "label": "WS", "text": parallel}])
    xml = result["body_xml"]
    assert "丙，" in xml
    assert "戊。" in xml
    assert_well_formed(xml)


def test_comm_pool_matches_out_of_order_brackets():
    body = (
        '<div type="juan"><p>甲'
        '<note type="comm">戊</note>丁'
        '<note type="comm">丙</note>乙</p></div>'
    )
    parallel = "甲〈丙，〉丁〈戊。〉乙。"
    result = apply_parallel_sources(body, [{"id": "ws", "label": "WS", "text": parallel}])
    xml = result["body_xml"]
    assert "戊。" in xml
    assert "丙，" in xml
    assert_well_formed(xml)


def test_comm_pool_finds_bracket_anywhere_in_chapter():
    header = "序跋" * 30
    body = '<div type="juan"><p>甲<note type="comm">過其本性也</note>乙</p></div>'
    parallel = header + "君子曰〈過其本性也，〉學。"
    result = apply_parallel_punctuation(body, parallel)
    assert result["applied"] is True
    assert "，" in result["body_xml"]


def test_build_wikisource_comm_pool():
    from kanripo_import.parallel_punct import _build_wikisource_comm_pool, han_only

    pool, spans = _build_wikisource_comm_pool("甲〈乙，丙。〉丁〈戊。〉")
    assert pool == han_only("乙，丙。戊。")
    assert len(spans) == 2
    assert spans[0]["text"] == "乙，丙。"
    assert spans[1]["text"] == "戊。"


def test_finalize_skips_relocate_when_it_breaks_wellformedness(monkeypatch):
    from kanripo_import import parallel_punct as pp

    body = '<div type="juan"><p>甲。</p></div>'
    punctuated = '<div type="juan"><p>甲，。</p></div>'

    def break_relocate(xml: str) -> str:
        return xml + "</p>"

    monkeypatch.setattr(pp, "relocate_leading_comm_notes", break_relocate)
    assert pp._finalize_parallel_xml(body, punctuated) == punctuated
