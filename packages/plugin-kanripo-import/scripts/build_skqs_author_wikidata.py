"""Import shim for ``build-skqs-author-wikidata.py`` (hyphenated filename)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_impl_path = Path(__file__).with_name('build-skqs-author-wikidata.py')
_spec = importlib.util.spec_from_file_location('build_skqs_author_wikidata_impl', _impl_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f'Cannot load {_impl_path}')
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

build_skqs_author_table = _mod.build_skqs_author_table
write_skqs_author_artifacts = _mod.write_skqs_author_artifacts
_load_overrides = _mod._load_overrides
