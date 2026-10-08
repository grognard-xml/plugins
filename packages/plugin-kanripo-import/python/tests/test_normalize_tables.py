"""The DPM variant table must never turn ordinary characters into compatibility ideographs."""

from __future__ import annotations

import csv
import unicodedata

from kanripo_import._paths import normalize_csv
from kanripo_import.normalize_tables import Normalizer

_COMPAT = [*range(0xF900, 0xFB00), *range(0x2F800, 0x2FA20)]


def _is_compat(ch: str) -> bool:
    return ord(ch) in (set(_COMPAT))


def test_no_table_row_maps_into_a_compatibility_ideograph_block():
    with open(normalize_csv("dpm_variant_normalisation_table.csv"), encoding="utf-8", newline="") as fh:
        offenders = [
            (row["Variant"], row["Norm"])
            for row in csv.DictReader(fh)
            if len(row["Norm"].strip()) == 1 and _is_compat(row["Norm"].strip())
        ]
    assert offenders == []


def test_ordinary_unified_characters_are_left_alone():
    norm = Normalizer.from_package_data()
    for ch in "請靖晴鬒慎兔":
        assert norm.normalize_text(ch) == ch


def test_no_compatibility_ideograph_survives_normalisation():
    norm = Normalizer.from_package_data()
    for codepoint in _COMPAT:
        ch = chr(codepoint)
        if len(unicodedata.normalize("NFC", ch)) == 1 and unicodedata.normalize("NFC", ch) != ch:
            assert not _is_compat(norm.normalize_text(ch)), f"U+{codepoint:04X}"


def test_the_curated_table_wins_over_the_unicode_fallback():
    # DPM deliberately prefers 館 to the canonical 舘 for the compatibility form U+FA6D.
    assert Normalizer.from_package_data().normalize_text("\uFA6D") == "館"
    # A compatibility ideograph the table lacks falls back to its canonical unified form.
    norm = Normalizer.from_package_data()
    assert norm.normalize_text("\U0002F80F") == "\u5154"
    assert norm.normalize_text("\uFAC8") == "\u9756"


def test_variant_that_looks_like_shen_normalises_to_the_ordinary_character():
    assert Normalizer.from_package_data().normalize_text("愼") == "慎"
