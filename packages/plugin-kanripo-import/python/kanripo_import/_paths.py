"""Resolve bundled data paths for the self-contained Kanripo import plugin."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def plugin_root() -> Path:
    env = os.environ.get("GROGNARD_PLUGIN_INSTALL_PATH", "").strip()
    if env:
        return Path(env)
    # …/python/kanripo_import/_paths.py → plugin package root
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def data_dir() -> Path:
    return plugin_root() / "data"


def gaiji_charlist_path() -> Path:
    return data_dir() / "gaiji" / "charlist.org.txt"


def gaiji_image_path(kr_id: str) -> Path:
    return data_dir() / "gaiji" / "images" / f"{kr_id}.png"


def normalize_csv(name: str) -> Path:
    return data_dir() / "normalize" / name


def concordance_dir() -> Path:
    return data_dir() / "concordance"


def metadata_dir() -> Path:
    return data_dir() / "metadata"
