"""Resolve bundled data paths for the self-contained Daozang import plugin."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def plugin_root() -> Path:
    env = os.environ.get("GROGNARD_PLUGIN_INSTALL_PATH", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def data_dir() -> Path:
    return plugin_root() / "data"


def corpus_dir() -> Path:
    return data_dir() / "corpus"


def metadata_dir() -> Path:
    return data_dir() / "metadata"
