from kanripo_import.kanripo_tei import body_to_tei_div


def test_tls_comment_lines_and_numbers_are_not_text():
    xml = body_to_tei_div(
        "<pb:KR1c0001_tls_008-1a>¶\n** 8 國風齊風第八\n\n# src: SHI 096.1\n# dating: 11011\n"
        "96《雞鳴》\n<pb:KR1c0001_tls_008-2a>¶\n\n《雞鳴》、¶\n思賢妃也。\n"
    )
    assert "#" not in xml and "src" not in xml and "dating" not in xml
    assert "<head><pb n=\"KR1c0001_tls_008-1a\"/>國風齊風第八</head>" in xml
    assert "<p>《雞鳴》" in xml
    assert "96" not in xml and "8" not in xml.replace("008", "")
