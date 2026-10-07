"""Title block markup, head segments and the deterministic finalize pass."""

from __future__ import annotations

import re

from kanripo_import.ai_punct import coverage_from_punctuation, list_segments
from kanripo_import.finalize import (
    finalize_body,
    strip_heading_trailing_punct,
    terminate_comm_notes,
)
from kanripo_import.kanripo_tei import body_to_tei_div
from kanripo_import.parallel_punct import relocate_leading_comm_notes

SIKU_JUAN = """<pb:KR3l0090_WYG_003-1a>¶
欽定四庫全書¶
　山海經卷三¶
　　　　　　　　　　　　　晉　郭璞　撰¶
　　北山經¶
北山經之首曰單狐之山多机木(机木似榆可燒)¶
其上多華草漨水出焉(音/逢)而西流注于泑水¶
<pb:KR3l0090_WYG_003-1b>¶
石文石¶
　右北經之山志凡八十七山¶
　山海經卷三¶
"""


def _heads(xml: str) -> list[str]:
    return [
        re.sub(r"<pb[^>]*/>", "", m)
        for m in re.findall(r"<(?:head|byline|trailer)\b.*?</(?:head|byline|trailer)>", xml)
    ]


def test_siku_title_block_becomes_head_byline_trailer():
    div = body_to_tei_div(SIKU_JUAN)
    assert _heads(div) == [
        '<head type="imprimatur">欽定四庫全書</head>',
        '<head type="title">山海經卷三</head>',
        "<byline>晉　郭璞　撰</byline>",
        "<head>北山經</head>",
        "<trailer>山海經卷三</trailer>",
    ]
    # the body line right after the block stays an ordinary paragraph
    assert "<p>北山經之首曰單狐之山多机木" in div
    # a closing note that is not the title stays content
    assert "<p>右北經之山志凡八十七山</p>" in div.replace("　", "")


def test_title_variant_still_matches_colophon():
    raw = SIKU_JUAN.replace("　山海經卷三¶\n　　　　", "　山海經巻三¶\n　　　　", 1)
    assert "<trailer>山海經卷三</trailer>" in body_to_tei_div(raw)


def test_prose_indentation_is_not_a_title_block():
    """A 提要-style juan indents running prose; long or commented lines end the block."""
    raw = "　山海經　　小說家𩔖二(異聞)¶\n　　提要¶\n　　　臣等謹案山海經十八卷晉郭璞注首¶\n"
    assert _heads(body_to_tei_div(raw)) == []


def test_head_segments_stay_separate_and_keep_han_indices_in_step():
    div = body_to_tei_div(SIKU_JUAN)
    segments = list_segments(div)["segments"]
    assert [s["kind"] for s in segments[:5]] == ["head", "head", "head", "head", "text"]
    assert segments[4]["han"].startswith("北山經之首曰")
    # contiguous Han index space across every segment kind
    for before, after in zip(segments, segments[1:]):
        assert before["han_end"] == after["han_start"]
    assert segments[-1]["kind"] == "head"


def test_headings_count_as_covered_in_the_coverage_bar():
    div = body_to_tei_div(SIKU_JUAN)
    segments = list_segments(div)["segments"]
    coverage = coverage_from_punctuation(div)
    head_han = sum(len(s["han"]) for s in segments if s["kind"] == "head")
    assert coverage["covered_chars"] >= head_han


def test_note_at_paragraph_start_moves_back_even_without_a_sentence_end():
    xml = "<p>多桂</p><p><note type=\"comm\">甲注</note>多金玉</p>"
    assert relocate_leading_comm_notes(xml) == (
        '<p>多桂<note type="comm">甲注</note></p><p>多金玉</p>'
    )


def test_note_only_paragraph_is_absorbed_and_not_left_empty():
    xml = '<p>是生珠玉。</p><p><note type="comm">亦珠母蚌類</note></p><p>西南三百六十里</p>'
    assert relocate_leading_comm_notes(xml) == (
        '<p>是生珠玉。<note type="comm">亦珠母蚌類</note></p><p>西南三百六十里</p>'
    )


def test_consecutive_note_paragraphs_chain_back_and_page_breaks_travel_with_them():
    xml = (
        '<p>基</p><p><pb n="a"/><note type="comm">一</note></p>'
        '<p><note type="comm">二</note>文</p>'
    )
    assert relocate_leading_comm_notes(xml) == (
        '<p>基<pb n="a"/><note type="comm">一</note><note type="comm">二</note></p><p>文</p>'
    )


def test_pure_commentary_paragraphs_are_not_merged():
    xml = '<p><note type="comm">甲</note></p><p><note type="comm">乙</note></p>'
    assert relocate_leading_comm_notes(xml) == xml


def test_page_break_without_a_note_is_left_in_place():
    xml = '<p>多桂</p><p><pb n="b"/>多金玉</p>'
    assert relocate_leading_comm_notes(xml) == xml


def test_notes_get_a_terminal_mark():
    xml = (
        '<p>基<note type="comm">無標點</note>'
        '<note type="comm">已有。</note>'
        '<note type="comm">問？</note>'
        '<note type="comm">引「曰」</note>'
        '<note type="comm">弱，</note>'
        '<note type="comm">書名《山海經》</note>'
        '<note type="comm">末尾<pb n="x"/></note>'
        '<note type="comm">末字<g ref="#g1"/></note></p>'
    )
    assert terminate_comm_notes(xml) == (
        '<p>基<note type="comm">無標點。</note>'
        '<note type="comm">已有。</note>'
        '<note type="comm">問？</note>'
        '<note type="comm">引「曰」</note>'
        '<note type="comm">弱。</note>'
        '<note type="comm">書名《山海經》。</note>'
        '<note type="comm">末尾。<pb n="x"/></note>'
        '<note type="comm">末字<g ref="#g1"/>。</note></p>'
    )


def test_headings_lose_trailing_punctuation_only_at_the_end():
    xml = (
        "<head>南山經。</head><byline>晉　郭璞　撰，</byline><trailer>山海經卷三。</trailer>"
        '<head type="title">「甲」曰：乙</head>'
    )
    assert strip_heading_trailing_punct(xml) == (
        "<head>南山經</head><byline>晉　郭璞　撰</byline><trailer>山海經卷三</trailer>"
        '<head type="title">「甲」曰：乙</head>'
    )


def test_finalize_runs_all_three_rules_without_touching_han():
    xml = (
        '<div type="juan"><head>北山經。</head><p>多機木。</p>'
        '<p><note type="comm">机木似榆</note>其上多華草</p></div>'
    )
    assert finalize_body(xml) == (
        '<div type="juan"><head>北山經</head>'
        '<p>多機木。<note type="comm">机木似榆。</note></p><p>其上多華草</p></div>'
    )


def test_finalize_fails_closed_on_malformed_input():
    broken = '<div type="juan"><p>多機木<note type="comm">注</p></div>'
    assert finalize_body(broken) == broken
