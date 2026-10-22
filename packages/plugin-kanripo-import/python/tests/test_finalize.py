"""Title block markup, head segments and the deterministic finalize pass."""

from __future__ import annotations

import re

from kanripo_import.ai_punct import coverage_from_punctuation, list_segments
from kanripo_import.finalize import (
    layout_zhushu_paragraphs,
    group_zhushu_entries,
    join_outside_kaozheng,
    join_wrapped_paragraphs,
    wrap_after_trailer,
    wrap_bylines_before_heads,
    finalize_body,
    strip_heading_trailing_punct,
    terminate_comm_notes,
)
from kanripo_import.kanripo_tei import body_to_tei_div
from kanripo_import.parallel_punct import han_only, relocate_leading_comm_notes

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


def test_terminal_mark_goes_after_a_gaiji_that_ends_the_note_not_inside_it():
    g = '<g type="kanripo" n="KR0034"><graphic url="_gaiji/KR0034.png" height="1em"/></g>'
    xml = f'<note type="comm">韭{g}</note>'
    assert terminate_comm_notes(xml) == f'<note type="comm">韭{g}。</note>'
    # a page break after the gaiji still comes after the mark
    xml = f'<note type="comm">韭{g}<pb n="X"/></note>'
    assert terminate_comm_notes(xml) == f'<note type="comm">韭{g}。<pb n="X"/></note>'


def test_join_wrapped_paragraphs_joins_a_sentence_split_at_a_manuscript_line():
    xml = '<div type="juan"><p>惠帝即位尊呂</p><p><pb n="X"/>后為太后。</p><p>元年春正月，詔曰：</p></div>'
    assert join_wrapped_paragraphs(xml) == (
        '<div type="juan"><p>惠帝即位尊呂<pb n="X"/>后為太后。</p><p>元年春正月，詔曰：</p></div>'
    )


def test_join_wrapped_paragraphs_keeps_paragraphs_that_end_a_sentence_or_a_note():
    xml = '<div type="juan"><p>侯者三人。</p><p>惠帝即位。</p><p>注<note type="comm">皆見《詩傳》。</note></p><p>疏<note type="comm">皆。</note></p></div>'
    assert join_wrapped_paragraphs(xml) == xml


def test_join_wrapped_paragraphs_leaves_unpunctuated_text_alone():
    xml = '<div type="juan"><p>前漢書卷一上</p><p>漢蘭臺令史班固撰</p></div>'
    assert join_wrapped_paragraphs(xml) == xml


def test_join_wrapped_paragraphs_chains_several_lines_and_keeps_han():
    xml = '<p>太后立帝姊魯</p><p>元公主女為</p><p>皇后，無子。</p>'
    out = finalize_body(xml)
    assert out == '<p>太后立帝姊魯元公主女為皇后，無子。</p>'


ZHUSHU = (
    '<p>格、懷，來也。</p><p>注<note type="comm">皆求請也。</note></p>'
    '<p>疏<note type="comm">謂招來也。</note></p>'
    '<p>還、復，返也。</p><p>注<note type="comm">今江東呼母為恀，音。</note></p>'
    '<p>義<note type="comm">恀音是怙。</note></p><p>疏<note type="comm">皆依恃也。</note></p>'
    '<p>律、遹，述也。注皆敘述也音義<note type="comm">遹古述字。</note></p>'
    '<p>疏<note type="comm">皆敘述也。</note></p>'
    '<p>俞，然也。</p><p>注<note type="comm">應也。</note></p><p>疏<note type="comm">皆應。</note></p>'
)


def test_zhushu_entries_are_grouped_typed_and_laid_out_as_entry_then_sub_commentary():
    out = finalize_body(f'<div type="juan">{ZHUSHU}</div>')
    paragraphs = re.findall(r"<p>(.*?)</p>", out, re.S)
    assert len(paragraphs) == 8  # four entries, each followed by its 音義 / 疏
    assert paragraphs[0] == '格、懷，來也。注<note subtype="zhu" type="comm">皆求請也。</note>'
    assert paragraphs[1] == '疏<note subtype="shu" type="comm">謂招來也。</note>'
    # the 音 that a note swallowed goes back to its 義, and plain 注 text becomes a note
    assert paragraphs[2] == '還、復，返也。注<note subtype="zhu" type="comm">今江東呼母為恀。</note>'
    assert paragraphs[3].startswith('音義<note subtype="yinyi"') and paragraphs[3].endswith("</note>")
    assert paragraphs[4] == '律、遹，述也。注<note subtype="zhu" type="comm">皆敘述也。</note>'
    assert paragraphs[5].startswith("音義<note subtype=")
    assert han_only(out) == han_only(ZHUSHU)
    assert finalize_body(out) == out


def test_group_zhushu_entries_ignores_a_juan_without_the_labelled_layout():
    xml = '<div type="juan"><p>爾雅注疏卷二考證</p><p>釋言第二○鄭樵曰音發為言。</p></div>'
    assert group_zhushu_entries(xml) == xml


def test_bylines_followed_by_a_head_go_in_an_opener():
    xml = (
        '<div type="juan"><head type="imprimatur">欽定四庫全書</head><head type="title">前漢書卷三</head>'
        "<byline>漢蘭臺令史班固撰</byline><byline>唐顏師古注</byline><head>高后紀第三</head><p>高皇后呂氏。</p></div>"
    )
    out = wrap_bylines_before_heads(xml)
    assert out == (
        '<div type="juan"><head type="imprimatur">欽定四庫全書</head><head type="title">前漢書卷三</head>'
        "<opener><byline>漢蘭臺令史班固撰</byline><byline>唐顏師古注</byline></opener>"
        "<head>高后紀第三</head><p>高皇后呂氏。</p></div>"
    )
    assert wrap_bylines_before_heads(out) == out


def test_bylines_after_the_last_head_are_left_alone():
    xml = '<div type="juan"><head>山海經卷三</head><byline>晉　郭璞　撰</byline><p>甲。</p></div>'
    assert wrap_bylines_before_heads(xml) == xml
    assert wrap_bylines_before_heads("<div><p>甲</p></div>") == "<div><p>甲</p></div>"


SEG = '<seg type="grognard:parallel-punct">%s</seg>'


def test_join_sees_through_parallel_punct_segs_and_page_breaks():
    # a paragraph that ends 。 inside a <seg> is finished; one that stops inside a <seg> is not
    done = f'<p>{SEG % "武為壺關侯。"}<pb n="X"/></p><p>{SEG % "秋，桃李華。"}</p>'
    assert join_wrapped_paragraphs(done) == done
    wrapped = f'<p>{SEG % "太后立帝姊魯"}</p><p>{SEG % "元公主女為皇后，無子。"}</p>'
    assert join_wrapped_paragraphs(wrapped) == f'<p>{SEG % "太后立帝姊魯"}{SEG % "元公主女為皇后，無子。"}</p>'


def test_join_keeps_title_lines_apart_from_the_text_around_them():
    xml = (
        f'<p>{SEG % "漢王從之。"}<pb n="X"/></p><p>前漢書卷一上</p>'
        f'<p>#+PROPERTY:JUAN卷一上考證<pb n="Y"/>前漢書卷一上考證</p><p>高帝紀第一上○監本刋此六字，非也。</p>'
    )
    assert join_wrapped_paragraphs(xml) == xml
    # a title line is not absorbed into an unfinished paragraph either
    xml = "<p>惠帝即位尊呂</p><p>爾雅注疏卷一考證</p><p>釋言，第二。</p>"
    assert join_wrapped_paragraphs(xml) == xml


def test_join_continues_past_a_note_that_follows_a_weak_mark():
    xml = '<p>太后臨朝稱制，<note type="comm">師古曰天子之言。</note></p><p>大赦天下。</p><p>元年春。<note type="comm">注。</note></p><p>二年。</p>'
    assert join_wrapped_paragraphs(xml) == (
        '<p>太后臨朝稱制，<note type="comm">師古曰天子之言。</note>大赦天下。</p>'
        '<p>元年春。<note type="comm">注。</note></p><p>二年。</p>'
    )


def test_kaozheng_after_the_trailer_gets_its_own_div():
    xml = '<div type="juan"><head>前漢書卷三</head><p>高皇后呂氏。</p><trailer>前漢書卷三</trailer><p>前漢書卷三考證</p><p>高后紀○監本。</p></div>'
    out = wrap_after_trailer(xml)
    assert out == (
        '<div type="juan"><div type="text"><head>前漢書卷三</head><p>高皇后呂氏。</p><trailer>前漢書卷三</trailer></div>'
        '<div type="kaozheng"><p>前漢書卷三考證</p><p>高后紀○監本。</p></div></div>'
    )
    assert wrap_after_trailer(out) == out


def test_nothing_to_wrap_when_the_trailer_ends_the_juan_or_is_missing():
    for xml in (
        '<div type="juan"><p>甲。</p><trailer>卷三</trailer></div>',
        '<div type="juan"><p>甲。</p><p>乙。</p></div>',
    ):
        assert wrap_after_trailer(xml) == xml


def test_kaozheng_keep_their_source_lines():
    # a whole 考證 juan (爾雅注疏): nothing is joined, though a mark would otherwise start a run
    juan = '<div type="juan"><p>爾雅注疏卷九考證</p><p>釋木第十四栲山樗注亦類漆樹○陸本漆作桼</p><p>鄭樵曰似樗而葉</p><p>差狹，樗木。</p></div>'
    assert join_outside_kaozheng(juan) == juan
    assert finalize_body(juan) == juan
    # the 考證 after a trailer (前漢書): the text before it is joined, the 考證 are not
    xml = (
        '<div type="juan"><p>惠帝即位尊呂</p><p>后為太后。</p><trailer>前漢書卷二</trailer>'
        '<p>前漢書卷二考證</p><p>惠帝紀○臣召南按史記於</p><p>高祖，本紀後。</p></div>'
    )
    out = finalize_body(xml)
    assert "<p>惠帝即位尊呂后為太后。</p>" in out
    assert '<div type="kaozheng"><p>前漢書卷二考證</p><p>惠帝紀○臣召南按史記於</p><p>高祖，本紀後。</p></div>' in out


# --- layout: the entry with its 注 in one paragraph, the 音義 / 疏 in the next -------------------

Z = '<note type="comm" subtype="zhu">%s</note>'
Y = '<note type="comm" subtype="yinyi">%s</note>'
SH = '<note type="comm" subtype="shu">%s</note>'


def _juan(*paragraphs: str, gap: str = "\n  ") -> str:
    return '<div type="juan">' + "".join(f"{gap}<p>{p}</p>" for p in paragraphs) + "\n</div>"


def _three_entries() -> list[str]:
    return [f"甲、乙，始也。{Z % '注一。'}音義{Y % '音一。'}疏{SH % '疏一。'}",
            f"丙，大也。{Z % '注二。'}音義{Y % '音二。'}疏{SH % '疏二。'}",
            f"丁，小也。{Z % '注三。'}疏{SH % '疏三。'}"]


def test_layout_cuts_each_entry_into_the_entry_with_its_zhu_and_one_sub_paragraph():
    xml = _juan(*_three_entries())
    out = layout_zhushu_paragraphs(xml)
    paragraphs = re.findall(r"<p>(.*?)</p>", out, re.S)
    assert paragraphs == [
        f"甲、乙，始也。{Z % '注一。'}", f"音義{Y % '音一。'}疏{SH % '疏一。'}",
        f"丙，大也。{Z % '注二。'}", f"音義{Y % '音二。'}疏{SH % '疏二。'}",
        f"丁，小也。{Z % '注三。'}", f"疏{SH % '疏三。'}",
    ]
    assert out.count("\n  <p>") == 6  # the indentation between paragraphs is kept
    assert re.sub(r"</?p>|\s", "", out) == re.sub(r"</?p>|\s", "", xml)  # nothing else changed
    assert layout_zhushu_paragraphs(out) == out


def test_layout_joins_a_zhu_that_starts_a_paragraph_and_merges_split_sub_paragraphs():
    e = _three_entries()
    xml = _juan(
        "甲、乙，始也。", Z % "注一。", f"音義{Y % '音一。'}", f"疏{SH % '疏一。'}",
        "丙，大也。注" + (Z % "注二。"), f"音義{Y % '音二。'}疏{SH % '疏二。'}",
        e[2],
    )
    out = layout_zhushu_paragraphs(xml)
    paragraphs = re.findall(r"<p>(.*?)</p>", out, re.S)
    assert paragraphs[0] == f"甲、乙，始也。{Z % '注一。'}"
    assert paragraphs[1] == f"音義{Y % '音一。'}疏{SH % '疏一。'}"
    assert paragraphs[2] == f"丙，大也。注{Z % '注二。'}"
    assert len(paragraphs) == 6 and not any(p.startswith("<note") for p in paragraphs)


def test_layout_starts_a_new_entry_after_sub_commentary_and_keeps_page_breaks_in_order():
    pb = '<pb n="P2"/>'
    xml = _juan(f"甲，始也。{Z % '注一。'}{pb}音義{Y % '音一。'}疏{SH % '疏一。'}乙，大也。{Z % '注二。'}音義{Y % '音二。'}", *_three_entries()[1:])
    out = layout_zhushu_paragraphs(xml)
    paragraphs = re.findall(r"<p>(.*?)</p>", out, re.S)
    assert paragraphs[1].startswith(pb + "音義")  # the page break goes with the label it precedes
    assert paragraphs[2] == f"乙，大也。{Z % '注二。'}"
    assert re.findall(r"<pb\b[^>]*/>", out) == [pb]


def test_layout_leaves_a_paragraph_alone_when_a_cut_would_fall_inside_an_element():
    unbalanced = f'<hi>甲，始也。{Z % "注一。"}音義</hi>{Y % "音一。"}'
    xml = _juan(unbalanced, *_three_entries())
    assert re.findall(r"<p>(.*?)</p>", layout_zhushu_paragraphs(xml), re.S)[0] == unbalanced


def test_layout_needs_three_of_each_and_ignores_kaozheng_juan():
    few = _juan(*_three_entries()[:2])
    assert layout_zhushu_paragraphs(few) == few
    kaozheng = _juan("爾雅注疏卷九考證", *_three_entries())
    assert layout_zhushu_paragraphs(kaozheng) == kaozheng


def test_layout_keeps_a_page_break_with_the_label_that_opens_a_paragraph():
    pb = '<pb n="P9"/>'
    e = _three_entries()
    # a sub paragraph that opens with a page break, after an entry: the break stays with its label
    xml = _juan(e[0].split("音義")[0], f"{pb}音義{Y % '音一。'}疏{SH % '疏一。'}", *e[1:])
    paragraphs = re.findall(r"<p>(.*?)</p>", layout_zhushu_paragraphs(xml), re.S)
    assert paragraphs[1] == f"{pb}音義{Y % '音一。'}疏{SH % '疏一。'}"
    # a paragraph of only a page break, left by an earlier run, is merged into the sub paragraph after it
    stray = _juan(e[0].split("音義")[0], pb, f"音義{Y % '音一。'}疏{SH % '疏一。'}", *e[1:])
    paragraphs = re.findall(r"<p>(.*?)</p>", layout_zhushu_paragraphs(stray), re.S)
    assert paragraphs[1] == f"{pb}音義{Y % '音一。'}疏{SH % '疏一。'}" and f"<p>{pb}</p>" not in "".join(paragraphs)
