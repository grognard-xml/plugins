"""Resolve bundled + cached data paths for the CBETA import plugin.

Bundled (ships in the installed plugin, committed): ``data/metadata`` (work-info,
gaiji table, catalog index) and ``data/schema`` (CBETA `_p5.rng` / `_p5.sch`
with the Grognard loosenings — see cbeta-import-planning.md §4).

The xml-p5 checkout lives under ``data/corpus/xml-p5`` inside the installed plugin
(same pattern as Daozang's ``data/corpus/``). The desktop host clones it on plugin
install / enable when missing. A legacy copy under ``GROGNARD_PLUGIN_CACHE_PATH`` is
still read if present. ``import`` itself hits no network (kanripo discipline).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from cbeta_import.constants import CANON_ORDER


def plugin_root() -> Path:
    env = os.environ.get("GROGNARD_PLUGIN_INSTALL_PATH", "").strip()
    if env:
        return Path(env)
    # …/python/cbeta_import/_paths.py → plugin package root
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def data_dir() -> Path:
    return plugin_root() / "data"


def metadata_dir() -> Path:
    return data_dir() / "metadata"


def schema_dir() -> Path:
    return data_dir() / "schema"


def work_info_path() -> Path:
    return metadata_dir() / "work_info.json"


def bundled_catalog_index_path() -> Path:
    return metadata_dir() / "catalog_index.json"


def gaiji_table_path() -> Path:
    return metadata_dir() / "gaiji" / "cb_gaiji.json"


def cache_root() -> Path:
    """Writable scratch dir (built catalog index cache). Falls back to ``data/``."""
    env = os.environ.get("GROGNARD_PLUGIN_CACHE_PATH", "").strip()
    return Path(env) if env else data_dir()


def bundled_corpus_dir() -> Path:
    """Primary xml-p5 location — copied with the plugin or cloned here on install."""
    return data_dir() / "corpus" / "xml-p5"


def legacy_cache_corpus_dir() -> Path:
    env = os.environ.get("GROGNARD_PLUGIN_CACHE_PATH", "").strip()
    if not env:
        return bundled_corpus_dir()
    return Path(env) / "corpus" / "xml-p5"


def corpus_is_present(path: Path) -> bool:
    return path.is_dir() and any((path / c).is_dir() for c in CANON_ORDER)


def corpus_dir(root: Path | None = None) -> Path:
    """The active xml-p5 tree: bundled install path, else legacy cache, else target for sync."""
    if root is not None:
        return Path(root) / "corpus" / "xml-p5"
    bundled = bundled_corpus_dir()
    if corpus_is_present(bundled):
        return bundled
    legacy = legacy_cache_corpus_dir()
    if legacy != bundled and corpus_is_present(legacy):
        return legacy
    return bundled


def cached_catalog_index_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else cache_root()) / "catalog_index.json"


def corpus_manifest_path(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root) / "corpus.json"
    return data_dir() / "corpus.json"
