"""Edition-tolerant sequence alignment: marks cross base-text / commentary roles."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from kanripo_import.parallel_punct import (
    _clean_parallel_for_alignment,
    apply_parallel_aligned,
    apply_parallel_sources,
)

# Siku-style juan: 經 and 注 run together as plain text, 音義 is a note nothing else has, 疏 is a note.
BODY = (
    '<div type="juan"><p>殷齊中也注書曰以殷仲春釋地曰岠齊州以南音義'
    '<note type="comm">中如字又音仲又知衆反</note>疏'
    '<note type="comm">殷齊皆謂正中也注書曰以殷仲春者堯典文案彼云日中星鳥以殷仲春孔安國以殷為正</note>'
    '斯誃離也注齊陳曰斯誃見詩音義<note type="comm">斯私貲所宜二反誃尺氏反</note>疏'
    '<note type="comm">斯析誃張皆分離也孫炎曰斯析之離郭云齊陳曰斯者方言文也</note></p></div>'
)
# Wikisource-style: 注 in （…）, 疏 as a plain paragraph after 【疏】, 音義 absent.
PARALLEL = (
    "殷、齊，中也。\n\n"
    "（《書》曰：「以殷仲春。」《釋地》曰：「岠齊州以南。」○中，如字，又音仲。）\n\n"
    "疏「殷、齊，中也」。○釋曰：殷、齊皆謂正中也。注「《書》曰：以殷仲春」者，《堯典》文。"
    "案彼云：「日中星鳥，以殷仲春。」孔安國以殷為正。\n\n"
    "斯、誃，離也。\n\n（齊、陳曰斯。誃，見《詩》。○斯，私貲反。）\n\n"
    "疏「斯、誃，離也」。○釋曰：斯，析。誃，張。皆分離也。孫炎曰：「斯，析之離。」郭云「齊、陳曰斯」者，《方言》文也。\n\n"
    "疏「天地」。○釋曰：玄黃宇宙洪荒。"
)


def _plain(xml: str) -> str:
    return re.sub(r"</?seg[^>]*>", "", xml)


def _han(xml: str) -> str:
    return re.sub(r"[^一-鿿]", "", re.sub(r"<[^>]+>", "", xml))


def test_clean_parallel_drops_edition_brackets_only():
    assert _clean_parallel_for_alignment("（注文，見《詩》。）︰") == "注文，見《詩》。："


def test_marks_cross_roles_without_changing_text_or_structure():
    result = apply_parallel_aligned(BODY, PARALLEL)
    assert result["applied"] is True
    xml = result["body_xml"]
    ET.fromstring(xml)  # well-formed
    assert _han(xml) == _han(BODY)  # only marks were added
    plain = _plain(xml)
    assert "殷、齊，中也。" in plain  # 經 punctuated from the parallel's 經
    assert "《書》曰：「以殷仲春。」" in plain  # 注 (plain in the body, （…） in the parallel)
    assert "殷、齊皆謂正中也。" in plain  # 疏 note punctuated from a plain paragraph
    assert "孫炎曰：「斯，析之離。」" in plain
    # the two 注 runs became notes; every pre-existing note is still there
    assert plain.count("<note") == BODY.count("<note") + 2


def test_no_edition_brackets_and_no_stranded_mark_runs():
    xml = _plain(apply_parallel_aligned(BODY, PARALLEL)["body_xml"])
    assert "（" not in xml and "）" not in xml
    assert not re.search(r"[，。、；：？！」]{3,}", xml)
    # 疏「殷、齊，中也」。○釋曰： has no counterpart in the body: its marks must not pile onto 疏.
    assert "疏，" not in xml and "疏」" not in xml


def test_unmatched_commentary_is_left_alone():
    unrelated = "<note type=\"comm\">無關之文字甲乙丙丁戊己庚辛壬癸</note>"
    body = BODY.replace("</p></div>", "斯誃" + unrelated + "</p></div>")
    plain = _plain(apply_parallel_aligned(body, PARALLEL)["body_xml"])
    assert unrelated in plain  # nothing in the parallel: untouched, not guessed


def test_already_punctuated_text_is_not_marked_twice():
    once = apply_parallel_aligned(BODY, PARALLEL)["body_xml"]
    twice = apply_parallel_aligned(once, PARALLEL)["body_xml"]
    assert _plain(twice) == _plain(once)


def test_unrelated_parallel_changes_nothing():
    result = apply_parallel_aligned(BODY, "天地玄黃，宇宙洪荒。日月盈昃，辰宿列張。寒來暑往，秋收冬藏。")
    assert result["applied"] is False
    assert result["body_xml"] == BODY


def test_short_coincidental_match_is_not_trusted():
    body = '<div type="juan"><p>甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉</p></div>'
    result = apply_parallel_aligned(body, "天地玄黃，甲乙丙丁戊，宇宙洪荒。")
    assert result["applied"] is False


def test_sources_pipeline_uses_aligned_pass_and_reports_full_tape_coverage():
    sources = [{"id": "ws", "label": "ws", "text": PARALLEL, "chapters": [{"id": "1", "title": "卷01", "text": PARALLEL}]}]
    result = apply_parallel_sources(BODY, sources)
    assert result["applied"] is True
    total = len(_han(BODY))
    assert result["coverage"]["total_chars"] == total  # notes included
    assert result["coverage"]["ratio"] > 0.5
    assert "（" not in result["body_xml"]
    assert _han(result["body_xml"]) == _han(BODY)


def _sources(text: str):
    return [{"id": "ws", "label": "ws", "text": text, "chapters": [{"id": "1", "title": "卷01", "text": text}]}]


def test_shu_citation_is_dropped_so_the_lemma_is_not_quoted():
    from kanripo_import.parallel_punct import strip_shu_citations

    layout = (
        "疏「明明、斤斤，察也」。○釋曰：舍人曰\n\n"
        "疏「卬吾」至「我也」。　○釋曰：我者\n\n"
        "疏釋曰：《說文》曰\n\n"
        "明明、斤斤，察也。"
    )
    assert strip_shu_citations(layout) == "疏舍人曰\n\n疏我者\n\n疏《說文》曰\n\n明明、斤斤，察也。"
    assert strip_shu_citations("疏") == "疏"


def test_base_text_is_not_wrapped_in_the_quotes_of_the_疏_citation():
    plain = _plain(apply_parallel_sources(BODY, _sources(PARALLEL))["body_xml"])
    assert "「殷" not in plain and "中也」" not in plain
    assert "殷、齊，中也。" in plain


def test_paragraph_break_before_疏_lands_after_the_音義_note_not_inside_it():
    plain = _plain(apply_parallel_sources(BODY, _sources(PARALLEL))["body_xml"])
    # ws starts 疏 on its own paragraph; the break goes where the base text 疏 resumes.
    assert "</note></p><p>疏<note" in plain
    assert not re.search(r"<p>\s*<note", plain)  # never a paragraph that opens with a note
    ET.fromstring(plain)  # still well-formed


def test_existing_breaks_are_kept_when_the_parallel_adds_its_own():
    body = BODY.replace("</note>斯誃離也", "</note></p><p>斯誃離也")
    plain = _plain(apply_parallel_sources(body, _sources(PARALLEL))["body_xml"])
    assert plain.count("<p>斯") == 1
    ET.fromstring(plain)


def test_parenthesised_commentary_in_the_parallel_becomes_a_comm_note():
    plain = _plain(apply_parallel_aligned(BODY, PARALLEL)["body_xml"])
    # 注 is plain text in the body; the parallel sets it in （…）. The label stays outside, like
    # 音義 and 疏 do, and the gloss becomes a note with its punctuation inside.
    assert '注<note type="comm">《書》曰：「以殷仲春。」《釋地》曰：「岠齊州以南。」</note>音義' in plain
    assert '注<note type="comm">齊、陳曰斯。誃，見《詩》。</note>音義' in plain
    assert "殷、齊，中也。" in plain.split("<note")[0]  # the 経 itself stays base text


def test_wrapping_never_touches_a_head_and_never_changes_the_text():
    head_text = "書曰以殷仲春釋地曰岠齊州以南"  # aligns to the parallel's （…） 注
    body = BODY.replace("<div type=\"juan\">", f"<div type=\"juan\"><head>{head_text}</head>")
    result = apply_parallel_aligned(body, PARALLEL)
    xml = _plain(result["body_xml"])
    ET.fromstring(xml)
    assert _han(xml) == _han(body)
    head = re.search(r"<head>(.*?)</head>", xml, re.S).group(1)
    assert "<note" not in head


def test_wrapping_is_idempotent():
    once = apply_parallel_aligned(BODY, PARALLEL)["body_xml"]
    twice = apply_parallel_aligned(once, PARALLEL)["body_xml"]
    assert _plain(twice).count("<note") == _plain(once).count("<note")


def test_no_wrap_when_the_parallel_has_no_parentheses():
    plain_parallel = PARALLEL.replace("（", "").replace("）", "")
    plain = _plain(apply_parallel_aligned(BODY, plain_parallel)["body_xml"])
    assert plain.count("<note") == BODY.count("<note")


def test_ascii_parentheses_also_mark_commentary():
    parallel = PARALLEL.replace("（", "(").replace("）", ")")
    plain = _plain(apply_parallel_aligned(BODY, parallel)["body_xml"])
    assert '注<note type="comm">《書》曰' in plain


def test_paragraph_that_opens_with_a_quote_mark_still_gets_its_break():
    body = "<div><p>甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉</p></div>"
    parallel = "甲乙丙丁戊己庚辛。\n\n「壬癸子丑寅卯辰巳午未申酉。」"
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert "</p><p>" in plain and plain.index("</p><p>") < plain.index("壬")


def test_every_shu_header_shape_seen_on_wikisource_is_stripped():
    from kanripo_import.parallel_punct import strip_shu_citations as strip

    cases = {
        "疏「明明、斤斤，察也」。○釋曰：舍人曰": "疏舍人曰",
        "疏「卬吾」至「我也」。　○釋曰：我者": "疏我者",
        "【疏】「初哉」至「始也」。　○釋曰：釋": "疏釋",
        "【疏】釋曰：釋，解也": "疏釋，解也",
        "疏「晉有大陸」。注「今钜鹿北廣河澤是也」。○釋曰：《周禮》": "疏《周禮》",
        "疏「楚有雲夢」。注「今南」至「湖是也」。○釋曰：案": "疏案",
        "疏「沃泉縣出」至注「從上溜下」。○釋曰：沃": "疏沃",
        "注「籩亦禮器」。○釋曰：案鄭注": "疏案鄭注",
        "注「《公羊》」至「得及」。○釋曰：此": "疏此",
        "疏釋曰：《說文》曰": "疏《說文》曰",
    }
    # a real 註疏 chapter has many such headers; the layout guard needs at least a few
    stripped = strip("\n\n".join(cases)).split("\n\n")
    assert stripped == list(cases.values())


def test_ordinary_text_that_merely_starts_with_注_or_疏_is_left_alone():
    from kanripo_import.parallel_punct import strip_shu_citations as strip

    for text in ("注皆聰明鑒察。", "注「籩亦禮器」", "疏", "明明、斤斤，察也。", "○釋曰：此別牛屬也"):
        assert strip(text) == text


def test_a_疏_on_a_注_does_not_quote_the_body_注_or_block_its_note():
    body = (
        '<div type="juan"><p>竹豆謂之籩注籩亦禮器音義<note type="comm">籩音邊</note>疏'
        '<note type="comm">案鄭注籩人及士虞禮云籩以竹為之口有籐緣形制如豆</note></p></div>'
    )
    parallel = (
        "竹豆謂之籩。\n\n（籩亦禮器。○籩，邊。）\n\n"
        "注「籩亦禮器」。○釋曰：案鄭注《籩人》及《士虞禮》云：「籩以竹為之，口有籐緣，形制如豆。」\n\n"
        "疏「瓦豆謂之登」。○釋曰：對文則木曰豆、瓦曰登。\n\n疏「盎謂之缶」。○釋曰：孫炎云：「缶，瓦器。」"
    )
    plain = _plain(apply_parallel_sources(body, _sources(parallel))["body_xml"])
    assert "注「" not in plain  # the citation of the 注 is not a second copy of it
    assert '注<note type="comm">籩亦禮器。</note>音義' in plain


def test_a_注_that_runs_over_a_kanripo_line_wrap_becomes_one_note():
    # Kanripo hard-wraps plain text, so the import gives a <p> per print line.
    # exactly as the import emits it: paragraphs joined by a newline
    body = (
        '<div type="juan">\n<p>麠大麃牛尾一角注漢武帝郊雍得一角獸若麃然謂</p>\n'
        "<p>之麟者此是也音義<note type=\"comm\">麠音京</note></p>\n</div>"
    )
    parallel = "麠，大麃，牛尾，一角。\n\n（漢武帝郊雍，得一角獸，若麃然，謂之麟者，此是也。○麠，音京。）"
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert plain.count('注<note type="comm">') == 1
    assert "</note><note" not in plain  # not split in two
    assert "謂之麟者" in re.sub(r"<[^>]+>", "", plain)
    ET.fromstring(plain)


def test_a_very_short_注_between_anchors_is_still_wrapped():
    body = (
        '<div type="juan"><p>盎謂之缶注盆也音義<note type="comm">盎烏浪反缶方九反</note>疏'
        '<note type="comm">孫炎云缶瓦器郭云盆也詩陳風云坎其擊缶</note></p></div>'
    )
    parallel = (
        "盎謂之缶。\n\n（盆也。○盎，烏浪反，缶，方九反。）\n\n"
        "疏「盎謂之缶」。○釋曰：孫炎云：「缶，瓦器。」郭云：「盆也。」《詩·陳風》云：「坎其擊缶。」"
    )
    plain = _plain(apply_parallel_sources(body, _sources(parallel))["body_xml"])
    assert '注<note type="comm">盆也。</note>音義' in plain


def test_citation_stripping_needs_the_zhushu_layout():
    from kanripo_import.parallel_punct import strip_shu_citations as strip

    lone = "甲乙丙丁。\n\n疏「戊己」。○釋曰：庚辛壬癸。\n\n子丑寅卯。"
    assert strip(lone) == lone  # one such paragraph is not a layout
    layout = "\n\n".join(f"疏「語{i}」。○釋曰：說{i}。" for i in range(3))
    assert strip(layout).count("疏說") == 3


# --- other Wikisource formats: ``〈…〉`` interlinear notes (荀子, 後漢書) ----------------------------
ANGLE_PARALLEL = (
    "君子曰：學不可以已。靑，取之於藍而靑於藍；冰，水爲之而寒於水。〈以喩學則才過其本性也。〉"
    "木直中繩，輮以爲輪，其曲中規，雖有槁暴，不復挺者，輮使之然也。〈輮，屈。槁，枯。暴，乾。挺，直也。〉"
    "故木受繩則直，金就礪則利，君子博學而日參省乎己，則知明而行無過矣。"
)


def _angle_body(flat: bool) -> str:
    notes = ["以喩學則才過其本性也", "輮屈槁枯暴乾挺直也"]
    wrap = (lambda t: t) if flat else (lambda t: f'<note type="comm">{t}</note>')
    return (
        "<div type=\"juan\"><p>君子曰學不可以已靑取之於藍而靑於藍冰水爲之而寒於水" + wrap(notes[0])
        + "木直中繩輮以爲輪其曲中規雖有槁暴不復挺者輮使之然也" + wrap(notes[1])
        + "故木受繩則直金就礪則利君子博學而日參省乎己則知明而行無過矣</p></div>"
    )


def test_angle_bracket_commentary_is_punctuated_inside_existing_notes():
    for chapters in (True, False):
        source = {"id": "ws", "label": "ws", "text": ANGLE_PARALLEL}
        if chapters:
            source["chapters"] = [{"id": "1", "title": "勸學", "text": ANGLE_PARALLEL}]
        plain = _plain(apply_parallel_sources(_angle_body(flat=False), [source])["body_xml"])
        assert "<note type=\"comm\">以喩學則才過其本性也。</note>" in plain
        assert "<note type=\"comm\">輮，屈。槁，枯。暴，乾。挺，直也。</note>" in plain
        assert "君子曰：學不可以已。" in plain
        assert plain.count("<note") == 2


def test_angle_bracket_commentary_that_is_plain_text_in_the_body_becomes_a_note():
    source = {"id": "ws", "label": "ws", "text": ANGLE_PARALLEL,
              "chapters": [{"id": "1", "title": "勸學", "text": ANGLE_PARALLEL}]}
    plain = _plain(apply_parallel_sources(_angle_body(flat=True), [source])["body_xml"])
    assert "<note type=\"comm\">以喩學則才過其本性也。</note>" in plain
    assert "<note type=\"comm\">輮，屈。槁，枯。暴，乾。挺，直也。</note>" in plain
    assert plain.count("<note") == 2  # and nothing else was taken for commentary
    assert _han(plain) == _han(_angle_body(flat=True))


def test_notes_krp_marked_are_never_joined_or_changed_by_the_transfer():
    # Two KRP notes separated by a paragraph break: KRP's structure, so the transfer leaves it.
    body = (
        '<div type="juan">\n<p>甲乙丙丁戊己庚辛<note type="comm">壬癸子丑寅卯</note></p>\n'
        '<p><note type="comm">辰巳午未申酉</note>戌亥</p>\n</div>'
    )
    parallel = "甲乙丙丁戊己庚辛。〈壬癸子丑寅卯。〉\n\n〈辰巳午未申酉。〉戌亥。"
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert plain.count('<note type="comm">') == 2
    assert "data-wrapped" not in plain
    assert "壬癸子丑寅卯。</note>" in plain  # punctuated inside, extent unchanged


def test_a_krp_note_is_not_merged_with_a_note_the_wrapper_creates_next_to_it():
    body = (
        '<div type="juan">\n<p>甲乙丙丁<note type="comm">戊己庚辛</note></p>\n'
        "<p>壬癸子丑寅卯辰巳</p>\n</div>"
    )
    parallel = "甲乙丙丁。〈戊己庚辛。〉\n\n〈壬癸子丑寅卯辰巳。〉"
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert plain.count('<note type="comm">') == 2  # KRP's note + the one created for 壬癸…
    assert "戊己庚辛。</note></p><p>" in plain.replace("\n", "") or "戊己庚辛。</note>" in plain
    assert "data-wrapped" not in plain


def test_a_variant_character_at_the_start_of_a_注_is_pulled_into_its_note():
    # KRP writes 牕, Wikisource 窗: the pair does not align, but it sits where the （…） begins.
    body = (
        '<div type="juan"><p>牖戶之間謂之扆注牕東戶西也禮云斧扆者以其所在處名之音義'
        '<note type="comm">牖羊九反扆於宜反</note></p></div>'
    )
    parallel = "牖戶之間謂之扆，（窗東戶西也。《禮》云斧扆者，以其所在處名之。○牖，羊九反。扆，於宜反。）"
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert '注<note type="comm">牕東戶西也。《禮》云斧扆者，以其所在處名之。</note>音義' in plain


def test_text_after_a_注_run_is_never_absorbed_into_it():
    # The unmatched characters after a run are the next label (音義), not part of the 注.
    body = (
        '<div type="juan"><p>竹豆謂之籩注籩亦禮器音義<note type="comm">籩音邊</note>疏'
        '<note type="comm">案鄭注籩人</note></p></div>'
    )
    parallel = "竹豆謂之籩。\n\n（籩亦禮器。○籩，邊。）\n\n疏「竹豆」。○釋曰：案鄭注《籩人》。\n\n疏「甲」。○釋曰：乙。\n\n疏「丙」。○釋曰：丁。"
    plain = _plain(apply_parallel_sources(body, _sources(parallel))["body_xml"])
    assert '注<note type="comm">籩亦禮器。</note>音義' in plain


def test_the_label_and_unpaired_characters_stay_outside_the_note():
    body = '<div type="juan"><p>牖戶之間謂之扆注東戶西也禮云斧扆者以其所在處名之音義</p></div>'
    parallel = "牖戶之間謂之扆，（東戶西也。《禮》云斧扆者，以其所在處名之。）"
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert '注<note type="comm">東戶西也' in plain and "<note type=\"comm\">注" not in plain  # 注 not absorbed
    assert plain.endswith("音義</p></div>")  # nor is 音義


def _label_body(entries: int = 8) -> tuple[str, str]:
    """A body whose KRP notes are consistently preceded by the label 音義 (so it can be learned)."""
    lemmas = ["甲乙", "丙丁", "戊己", "庚辛", "壬癸", "子丑", "寅卯", "辰巳"][:entries]
    shu = "此言江東之人呼母為{0}其說見於方言所載亦可互證"
    body = '<div type="juan">\n' + "".join(
        f'<p>{lem}之也注今江東呼母為{lem[0]}音義<note type="comm">{lem[0]}音是怙音戶</note>'
        f'疏<note type="comm">{shu.format(lem[0])}</note></p>\n'
        for lem in lemmas
    ) + "</div>"
    parallel = "\n\n".join(
        f"{lem}之也。\n\n（今江東呼母為{lem[0]}，音是。）\n\n"
        f"疏「{lem}之也」。○釋曰：{shu.format(lem[0])}。"
        for lem in lemmas
    )
    return body, parallel


def test_a_label_char_that_happens_to_match_the_parallel_is_not_pulled_into_the_note():
    # The parallel's 注 ends "…為甲，音是": the body's label 音 coincides with that 音.
    body, parallel = _label_body()
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert "音</note>義" not in plain and "音。</note>義" not in plain
    assert '注<note type="comm">今江東呼母為甲，</note>音義<note' in plain


def test_labels_are_learned_from_the_text_not_assumed():
    from kanripo_import.parallel_punct import _iter_xml_atoms_segmented, _learn_note_labels

    body, _ = _label_body()
    assert _learn_note_labels(_iter_xml_atoms_segmented(body)) == ["音義"]
    # a body whose notes follow ordinary, varied prose learns nothing
    varied = "".join(f'<p>天地玄黃{c}<note type="comm">宇宙</note></p>' for c in "甲乙丙丁戊己庚辛")
    assert _learn_note_labels(_iter_xml_atoms_segmented(varied)) == []


def test_a_label_split_by_a_character_that_matches_non_commentary_text_is_not_absorbed():
    # Here the label's 2nd char (義) also happens to occur in the parallel's *non*-parenthetical
    # text right after the 注, so the run ends on that match rather than at the note.
    body, parallel = _label_body()
    parallel = parallel.replace("，音是。）", "，音是。）義", 1)  # a stray non-commentary 義 follows
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert "音</note>義" not in plain and "音。</note>義" not in plain


def test_a_label_cut_from_its_note_by_a_line_wrap_is_not_absorbed():
    body, parallel = _label_body()
    # the print-line wrap falls between the label 音義 and its note, as in the real file
    body = body.replace("音義<note", "音義</p>\n<p><note", 2)
    plain = _plain(apply_parallel_aligned(body, parallel)["body_xml"])
    assert "音</note>義" not in plain and "音。</note>義" not in plain
