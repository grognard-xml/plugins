"""Filling Kanripo □ placeholders from a reference text."""

from __future__ import annotations

from kanripo_import.fill_placeholders import fill_placeholders
from kanripo_import.parallel_punct import han_only

REF = ["士節儉也旭旭蹻蹻憍也皆小人得志憍蹇之貌也郭氏讀旭旭為好好"]


def test_fills_a_run_from_unique_context():
    xml = '<p>士節儉也<seg type="x">旭旭、□□憍也。</seg>皆小人得志憍蹇之貌也</p>'
    out, fills, skipped = fill_placeholders(xml, REF)
    assert out == '<p>士節儉也<seg type="x">旭旭、蹻蹻憍也。</seg>皆小人得志憍蹇之貌也</p>'
    assert [(f["fill"], f["run"]) for f in fills] == [("蹻蹻", 2)] and not skipped
    assert han_only(out) == han_only(xml.replace("□", "蹻"))


def test_context_may_cross_markup_and_notes():
    xml = '<p>旭旭<note type="comm">、</note>□□<pb n="1"/>憍也皆小人得志</p>'
    assert fill_placeholders(xml, REF)[0] == '<p>旭旭<note type="comm">、</note>蹻蹻<pb n="1"/>憍也皆小人得志</p>'


def test_left_alone_when_the_reference_is_ambiguous_or_silent():
    ambiguous = ["旭旭蹻蹻憍也皆小人得志", "旭旭驕驕憍也皆小人得志"]
    xml = "<p>旭旭□□憍也皆小人得志</p>"
    out, fills, skipped = fill_placeholders(xml, ambiguous)
    assert out == xml and not fills and skipped[0]["reason"].startswith("the reference reads differently")
    out, fills, skipped = fill_placeholders("<p>甲乙丙□丁戊己庚</p>", REF)
    assert out == "<p>甲乙丙□丁戊己庚</p>" and skipped[0]["reason"] == "no match in the reference"


def test_run_length_must_match_and_short_context_is_refused():
    assert fill_placeholders("<p>旭旭□憍也皆小人得志</p>", REF)[1] == []  # one box, two characters
    assert fill_placeholders("<p>旭□憍</p>", REF)[1] == []  # too little context


def test_other_boxes_and_gaiji_in_the_context_match_any_character():
    xml = '<p>旭旭<g type="kanripo" n="KR1"><graphic url="x.png"/></g>□憍也皆小人得志</p>'
    out, fills, _ = fill_placeholders(xml, REF)
    # the gaiji stands for one of 蹻蹻, the □ for the other: only the box is filled
    assert fills and fills[0]["fill"] == "蹻" and out.count("□") == 0 and "<g " in out


def test_punctuation_between_boxes_makes_two_runs_and_attributes_are_untouched():
    xml = '<p rend="□">旭旭、□□憍也皆小人得志憍蹇之貌也</p>'
    out, fills, _ = fill_placeholders(xml, REF)
    assert out.startswith('<p rend="□">') and fills[0]["run"] == 2


def test_the_parallel_import_fills_placeholders_and_reports_them():
    from kanripo_import.parallel_punct import apply_parallel_sources

    ref = "士節儉也。旭旭，蹻蹻，憍也。皆小人得志憍蹇之貌也。郭氏讀旭旭為好好。"
    body = '<div type="juan"><p>士節儉也旭旭□□憍也皆小人得志憍蹇之貌也郭氏讀旭旭為好好</p></div>'
    result = apply_parallel_sources(body, [{"id": "p", "label": "ref", "text": ref}])
    assert "□" not in result["body_xml"] and "蹻蹻" in result["body_xml"]
    assert result["placeholders_filled"] == 1 and result["placeholders_left"] == 0
