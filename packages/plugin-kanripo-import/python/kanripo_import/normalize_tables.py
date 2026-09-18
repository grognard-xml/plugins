"""Bundled character normalisation tables.

The DPM variant table (``Normalizer``) is applied to transcription text
itself during Kanripo import.

The simp/trad "hard replacements" table (``hard_replacements_table`` /
``apply_hard_replacements``) collapses characters with no functional
difference for this corpus (e.g. 乎/於 -> 于, 炁 -> 氣) so they compare equal
for n-gram/paragraph parallel-matching. It is comparison-only: never apply
it to a transcription's actual output text, only to a text's derived
matching/comparison key.
"""

from __future__ import annotations

import csv
import unicodedata
from functools import lru_cache

from kanripo_import._paths import normalize_csv


class Normalizer:
    __slots__ = ("_trans",)

    def __init__(self, variant_to_norm: dict[str, str]) -> None:
        mapping: dict[int, str] = {}
        for variant, norm in variant_to_norm.items():
            if len(variant) == 1 and len(norm) == 1:
                mapping[ord(variant)] = norm
        self._trans = str.maketrans(mapping)

    @classmethod
    def from_csv(cls, csv_path) -> Normalizer:
        with open(csv_path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            variant_to_norm: dict[str, str] = {}
            for row in reader:
                variant = (row.get("Variant") or "").strip()
                norm = (row.get("Norm") or "").strip()
                if len(variant) == 1 and len(norm) == 1:
                    variant_to_norm[variant] = norm
        return cls(variant_to_norm)

    @classmethod
    @lru_cache(maxsize=1)
    def from_package_data(cls) -> Normalizer:
        return cls.from_csv(normalize_csv("dpm_variant_normalisation_table.csv"))

    def normalize_text(self, text: str | None) -> str:
        if not text:
            return "" if text is None else text
        return text.translate(self._trans)


def _load_simp_trad_from_file(handle) -> dict[str, str]:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None or "simp" not in reader.fieldnames or "trad" not in reader.fieldnames:
        raise ValueError("CSV must have columns simp, trad")
    out: dict[str, str] = {}
    for row in reader:
        simp = unicodedata.normalize("NFC", str(row.get("simp", "")).strip())
        trad = unicodedata.normalize("NFC", str(row.get("trad", "")).strip())
        if len(simp) != 1 or len(trad) < 1:
            continue
        out[simp] = trad
    return out


@lru_cache(maxsize=1)
def hard_replacements_table() -> dict[str, str]:
    with open(normalize_csv("hard_replacements.csv"), encoding="utf-8-sig", newline="") as handle:
        out = _load_simp_trad_from_file(handle)
    with open(normalize_csv("hard_hard_replacements.csv"), encoding="utf-8-sig", newline="") as handle:
        out.update(_load_simp_trad_from_file(handle))
    return out


def apply_hard_replacements(text: str, mapping: dict[str, str] | None = None) -> str:
    table = hard_replacements_table() if mapping is None else mapping
    if not table:
        return text
    return "".join(table.get(ch, ch) for ch in text)
