"""A commentary note that wraps over several ¶-terminated lines must stay in one paragraph."""

from __future__ import annotations

from kanripo_import.kanripo_tei import body_to_tei_div


def test_note_wrapping_over_lines_converts_and_stays_in_one_paragraph():
    body = (
        "殷齊中也注書曰(以殷仲春釋地曰岠齊¶\n"
        "州以南音義)疏(殷齊皆謂正中也注書曰以殷¶\n"
        "仲春者堯典文)¶\n"
        "斯誃離也¶\n"
    )
    xml = body_to_tei_div(body)
    assert xml.count("<p>") == 2
    assert xml.count('<note type="comm">') == 2
    assert xml.count("</note>") == 2
    assert "<p>殷齊中也注書曰<note" in xml
    assert "仲春者堯典文</note></p>" in xml


def test_single_line_notes_still_break_paragraphs_per_line():
    xml = body_to_tei_div("甲乙(丙丁)¶\n戊己(庚辛)¶\n")
    assert xml.count("<p>") == 2
