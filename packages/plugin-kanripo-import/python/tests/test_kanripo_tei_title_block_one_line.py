"""Siku title block where the title and the attribution share one line (穆天子傳)."""

from __future__ import annotations

from kanripo_import.kanripo_tei import body_to_tei_div

GAP = "　" * 6  # a run of ideographic spaces between the two halves


def _juan(title_line: str, tail: str = "") -> str:
    return (
        "<pb:KR3l0092_WYG_001-1a>¶\n"
        "欽定四庫全書¶\n"
        f"{title_line}¶\n"
        "　　古文¶\n"
        "飲天子蠲(音/涓)山之上戊寅天子北征乃絶漳水¶\n"
        "之下癸未雨雪¶\n"
        "　¶\n" + tail
    )


def test_title_and_attribution_on_one_line_become_a_title_head_and_a_byline():
    xml = body_to_tei_div(_juan(f"　穆天子傳卷一{GAP}晉　郭璞　註"))
    assert '<head type="imprimatur"><pb n="KR3l0092_WYG_001-1a"/>欽定四庫全書</head>' in xml
    assert '<head type="title">穆天子傳卷一</head>' in xml
    assert "<byline>晉　郭璞　註</byline>" in xml
    assert "<head>古文</head>" in xml
    # none of them is left to be punctuated as running text with the first sentence
    assert "<p>穆天子傳" not in xml and "<p>古文" not in xml
    assert xml.index("</byline>") < xml.index("<head>古文</head>") < xml.index("<p>飲天子蠲")


def test_the_variant_juan_character_and_the_colophon_still_work():
    xml = body_to_tei_div(_juan(f"　穆天子傳巻六{GAP}晉　郭璞　註", tail="　穆天子傳卷六¶\n"))
    assert '<head type="title">穆天子傳巻六</head>' in xml
    assert "<trailer>穆天子傳卷六</trailer>" in xml


def test_a_zhu_attribution_is_recognised_on_its_own_line_too():
    xml = body_to_tei_div(
        "欽定四庫全書¶\n　穆天子傳卷二¶\n　　　　晉　郭璞　註¶\n　　古文¶\n飲天子蠲山之上戊寅¶\n"
    )
    assert '<head type="title">穆天子傳卷二</head>' in xml
    assert "<byline>晉　郭璞　註</byline>" in xml


def test_an_ordinary_indented_line_is_never_split():
    # second half is not an attribution, so this is not a title+byline line: the block just closes
    xml = body_to_tei_div(f"欽定四庫全書¶\n　穆天子傳卷一{GAP}之後而已¶\n飲天子蠲山之上¶\n")
    assert "<byline>" not in xml
    assert '<head type="title">' not in xml


def test_a_gap_that_is_a_single_space_does_not_split():
    xml = body_to_tei_div("欽定四庫全書¶\n　穆天子傳卷一　晉　郭璞　註¶\n飲天子蠲山之上¶\n")
    assert "<byline>" not in xml


def test_a_body_line_with_a_wide_gap_after_the_block_is_untouched():
    xml = body_to_tei_div(
        _juan(f"　穆天子傳卷一{GAP}晉　郭璞　註", tail=f"　天子{GAP}晉　郭璞　註¶\n")
    )
    assert xml.count("<byline>") == 1  # only the one in the title block
