"""A parallel's paragraphs replace a print-line body's line-wrap breaks."""

from __future__ import annotations

import re

from kanripo_import.paragraph_reflow import parallel_paragraphs, reflow_to_parallel
from kanripo_import.parallel_punct import apply_parallel_aligned, han_only

PARALLEL = (
    "西山經之首，曰錢來之山，其上多松，其下多洗石（澡洗可以磢體）。有獸焉，名曰羬羊（今大月氐國有大羊）。\n\n"
    "西四十五里，曰松果之山。濩水出焉，北流注于渭，其中多銅。\n\n"
    "又西六十里，曰太華之山，削成而四方，其高五千仞，鳥獸莫居。\n\n"
    "又西八十里，曰小華之山，其木多荊杞，其獸多㸲牛。"
)
N = '<note type="comm">%s</note>'


def paragraphs(xml: str) -> list[str]:
    return re.findall(r"<p>(.*?)</p>", xml, re.S)


def base(p: str) -> str:
    return re.sub(r"<[^>]+>", "", re.sub(r"<note\b.*?</note>", "", p, flags=re.S))


def line_wrapped_body(extra_wrap: str = "") -> str:
    """Four paragraphs of the parallel, cut at the print lines (mid-sentence) and run together."""
    return (
        '<div type="juan">\n  <p>西山經之首曰錢來之山其上多松其下多洗石' + (N % "澡洗") + "</p>\n"
        "  <p>有獸焉名曰羬羊" + (N % "大羊") + "</p>\n"
        "  <p>西四十五里曰松果之山濩水出焉北流注于渭其中多銅又西六十里曰太華之山削成而四方</p>\n"
        "  <p>其高五千仞鳥獸莫居又西八十里曰小華之山其木多荊杞其獸多㸲牛" + extra_wrap + "</p>\n</div>"
    )


def test_parallel_paragraphs_are_blank_line_blocks_without_commentary() -> None:
    out = parallel_paragraphs(PARALLEL)
    assert len(out) == 4
    assert out[0] == "西山經之首曰錢來之山其上多松其下多洗石有獸焉名曰羬羊"
    assert "澡洗" not in "".join(out)


def test_line_wraps_are_replaced_by_the_parallels_paragraphs() -> None:
    result = reflow_to_parallel(line_wrapped_body(), PARALLEL)
    assert result["applied"], result["reason"]
    ps = paragraphs(result["body_xml"])
    assert [base(p)[:6] for p in ps] == ["西山經之首曰", "西四十五里曰", "又西六十里曰", "又西八十里曰"]
    assert (result["added"], result["removed"]) == (2, 2)  # two line wraps joined, two new paragraph starts
    # the gloss that follows an entry's last character stays with that entry
    assert ps[0].count("<note") == 2 and "羬羊" in ps[0]
    assert han_only(result["body_xml"]) == han_only(line_wrapped_body())


def test_only_p_boundaries_change_and_a_second_run_changes_nothing() -> None:
    first = reflow_to_parallel(line_wrapped_body(), PARALLEL)["body_xml"]
    strip = lambda x: re.sub(r"\s+", "", re.sub(r"</?p\b[^>]*>", "", x))  # noqa: E731
    assert strip(first) == strip(line_wrapped_body())
    again = reflow_to_parallel(first, PARALLEL)
    assert (again["applied"], again["body_xml"]) == (False, first)


def test_a_page_break_before_the_next_paragraph_goes_with_it_and_a_title_block_is_cut_off() -> None:
    pb = '<pb n="1b"/>'
    body = (
        '<div type="juan"><p>欽定四庫全書山海經卷二，晉郭璞撰。西山經。西山經之首曰錢來之山其上多松其下多洗石有獸焉名曰羬羊' + pb + "西四十五里曰松果之山濩水出焉北流注于渭其中多銅又西六十里曰太華之山削成而四方其高五千仞鳥獸莫居</p>"
        "<p>又西八十里曰小華之山其木多荊杞其獸多㸲牛</p></div>"
    )
    result = reflow_to_parallel(body, PARALLEL)
    assert result["applied"], result["reason"]
    ps = paragraphs(result["body_xml"])
    assert base(ps[0]) == "欽定四庫全書山海經卷二，晉郭璞撰。西山經。"  # title block apart from the first entry
    assert ps[2].startswith(pb + "西四十五里")  # the page break goes with the paragraph it opens
    assert len(ps) == 5 and base(ps[3]).startswith("又西六十里")


def test_a_break_the_alignment_cannot_judge_stays() -> None:
    # a stretch the parallel does not have between two lines: neither side aligns, so the break stays
    body = (
        '<div type="juan"><p>西四十五里曰松果之山濩水出焉北流注于渭其中多銅</p><p>某某某某某某某某某某</p>'
        "<p>又西六十里曰太華之山削成而四方其高五千仞鳥獸莫居</p></div>"
    )
    result = reflow_to_parallel(body, PARALLEL)
    assert len(paragraphs(result["body_xml"])) == 3


def test_nothing_is_done_without_paragraphs_or_agreement() -> None:
    body = line_wrapped_body()
    assert reflow_to_parallel(body, "只有一段文字，沒有分段。")["reason"] == "the parallel has no paragraphs"
    other = "\n\n".join(["天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往"] * 4)
    result = reflow_to_parallel(body, other)
    assert not result["applied"] and result["body_xml"] == body


def test_a_break_that_would_cut_an_element_is_not_made_but_the_others_are() -> None:
    seg_body = line_wrapped_body().replace("西四十五里曰松果", '<seg type="x">西四十五里曰松果').replace(
        "太華之山削成", "太華之山削成</seg>"
    )
    result = reflow_to_parallel(seg_body, PARALLEL)
    ps = paragraphs(result["body_xml"])
    assert all(p.count("<seg") == p.count("</seg>") for p in ps)
    starts = [han_only(base(p))[:5] for p in ps]
    assert "又西六十里" not in starts  # that start falls inside the <seg>, so no break there
    assert "又西八十里" in starts and "西四十五里" in starts  # the other paragraph starts are made


def test_the_aligned_transfer_reflows_when_asked_and_keeps_line_breaks_otherwise() -> None:
    punctuated = PARALLEL.replace("（澡洗可以磢體）", "").replace("（今大月氐國有大羊）", "")
    body = line_wrapped_body()
    kept = apply_parallel_aligned(body, punctuated)
    assert len(paragraphs(kept["body_xml"])) >= 4 and "paragraphs_reflowed" not in kept
    reflowed = apply_parallel_aligned(body, punctuated, reflow=True)
    ps = paragraphs(reflowed["body_xml"])
    assert [han_only(base(p))[:5] for p in ps] == ["西山經之首", "西四十五里", "又西六十里", "又西八十里"]
    assert reflowed["paragraphs_reflowed"]["removed"] >= 1
    assert "，" in reflowed["body_xml"]  # the punctuation was transferred as well
    assert han_only(reflowed["body_xml"]) == han_only(body)


def test_a_wikisource_source_reflows_through_apply_parallel_sources() -> None:
    from kanripo_import.parallel_punct import apply_parallel_sources

    punctuated = PARALLEL.replace("（澡洗可以磢體）", "").replace("（今大月氐國有大羊）", "")
    sources = [{"id": "ws", "label": "ws", "text": punctuated, "chapters": [{"id": "1", "title": "西山經", "text": punctuated}]}]
    result = apply_parallel_sources(line_wrapped_body(), sources)
    ps = paragraphs(result["body_xml"])
    assert [han_only(base(re.sub(r"<seg\b[^>]*>|</seg>", "", p)))[:5] for p in ps] == ["西山經之首", "西四十五里", "又西六十里", "又西八十里"]
    assert result["paragraphs_reflowed"]["removed"] >= 1
    # a source that is not a Wikisource edition (no chapters) keeps the body's own breaks
    plain = apply_parallel_sources(line_wrapped_body(), [{"id": "p", "label": "p", "text": punctuated}])
    assert "paragraphs_reflowed" not in plain
