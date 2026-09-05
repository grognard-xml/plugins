"""Tests for bundled Kanripo gaiji resolution."""

import os
from pathlib import Path

import pytest

from kanripo_import.kanripo_gaiji import (
    default_table,
    gaiji_graphic_xml,
    load_gaiji_table,
    resolve_kanripo_refs,
)
from kanripo_import.kanripo_tei import convert_kanripo_txt

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("GROGNARD_PLUGIN_INSTALL_PATH", str(PACKAGE_ROOT))


def test_bundled_table_resolves_unicode_gaiji() -> None:
    table = default_table()
    assert table.get("KR0003") == "說"
    text, image_ids = resolve_kanripo_refs("說&KR0003;文", table)
    assert text == "說說文"
    assert image_ids == []


def test_image_only_gaiji_becomes_inline_tag() -> None:
    table = {"KR0954": None}
    text, image_ids = resolve_kanripo_refs("漭&KR0954;浪", table)
    assert text == "漭<gaiji:KR0954/>浪"
    assert image_ids == ["KR0954"]


def test_gaiji_graphic_xml_uses_project_relative_url() -> None:
    xml = gaiji_graphic_xml("KR0954")
    assert 'url="_gaiji/KR0954.png"' in xml
    assert 'height="1em"' in xml
    assert 'type="kanripo"' in xml


def test_convert_minimal_fixture(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "minimal_kanripo.txt"
    result = convert_kanripo_txt(fixture, normalize="off")
    xml = result["body_xml"]
    assert '<pb n="KRTEST1_tls_001-1a"/>' in xml
    assert "Heading one" in xml
    assert "&KR" not in xml


def test_convert_copies_bundled_gaiji_png(tmp_path: Path) -> None:
    os.environ["GROGNARD_PLUGIN_INSTALL_PATH"] = str(PACKAGE_ROOT)
    from kanripo_import import kanripo_gaiji as gaiji_mod

    gaiji_mod.default_table.cache_clear()

    source = tmp_path / "sample.txt"
    source.write_text("#+TITLE: X\n甲&KR0954;乙¶\n", encoding="utf-8")
    dest = tmp_path / "out"
    result = convert_kanripo_txt(source, gaiji_dest_dir=dest)
    assert result["meta"]["gaiji_ids"] == ["KR0954"]
    assert (dest / "KR0954.png").is_file()
    assert gaiji_graphic_xml("KR0954") in result["body_xml"]

    gaiji_mod.default_table.cache_clear()


def test_commentary_slash_join_removed() -> None:
    from kanripo_import.kanripo_tei import body_to_tei_div

    div = body_to_tei_div("甲(過其本性也/以喻學則才)乙")
    assert "過其本性也以喻學則才" in div
    assert "也/以" not in div
    assert '<note type="comm">' in div
