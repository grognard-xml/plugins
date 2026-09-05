"""Tests for bundled concordance tables."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _plugin_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROGNARD_PLUGIN_INSTALL_PATH", str(PLUGIN_ROOT))
    from kanripo_import import concordance

    concordance.clear_concordance_cache()


def test_concordance_files_exist() -> None:
    concordance_dir = PLUGIN_ROOT / "data" / "concordance"
    required = [
        "manifest.json",
        "krp_dz_collation.csv",
        "kanripo_org_concordance.csv",
        "dz_corpus_works.csv",
        "kanripo_daozang_map.json",
        "kanripo_daozang_overrides.csv",
    ]
    for name in required:
        assert (concordance_dir / name).is_file(), name


def test_duren_jing_index_maps_to_daozang() -> None:
    from kanripo_import.concordance import load_duren_jing_index, lookup_daozang_rel_path

    rows = load_duren_jing_index()
    assert rows, "expected bundled duren_jing_index.csv"
    kr5a0087 = lookup_daozang_rel_path("KR5a0087")
    assert kr5a0087 is not None
    assert kr5a0087.dz_id == "DZ0087"
    assert kr5a0087.daozang_rel_path.endswith(".txt")
    assert "四注" in kr5a0087.daozang_rel_path or "四注" in kr5a0087.daozang_title


def test_krp_dz_collation_lookup() -> None:
    from kanripo_import.concordance import load_krp_dz_collation, lookup_dz_id

    rows = load_krp_dz_collation()
    assert len(rows) > 1000
    assert lookup_dz_id("KR5a0001") == "DZ0001"


def test_daozang_map_has_kr5_entries() -> None:
    from kanripo_import.concordance import load_daozang_map

    m = load_daozang_map()
    kr5 = [k for k in m if k.startswith("KR5")]
    assert len(kr5) > 100
