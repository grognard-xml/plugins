"""JSON stdin/stdout bridge for CBETA corpus sync and TEI conversion.

ops (all optional ``cache_root`` overrides ``GROGNARD_PLUGIN_CACHE_PATH``):
  status              → corpus_sync.corpus_status()
  sync                → corpus_sync.sync_corpus(force?)
  install_from_source → corpus_sync.install_from_source(source_path)
  search              → catalog_index.search(query, limit)
  resolve             → [str(path), …] for a work id
  convert (default)   → cbeta_tei.convert_cbeta_work(work_id | path, cross_family?)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cbeta_import import catalog_index, corpus_sync
from cbeta_import.cbeta_tei import convert_cbeta_work


def _ensure_plugin_install_path() -> None:
    if os.environ.get("GROGNARD_PLUGIN_INSTALL_PATH", "").strip():
        return
    inferred = Path(__file__).resolve().parents[2]
    if (inferred / "data" / "metadata").is_dir():
        os.environ["GROGNARD_PLUGIN_INSTALL_PATH"] = str(inferred)


def _cache_root(payload: dict) -> Path | None:
    raw = str(payload.get("cache_root") or "").strip()
    return Path(raw) if raw else None


def _emit(obj: object) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def cli_main() -> None:
    payload = json.load(sys.stdin)
    _ensure_plugin_install_path()
    op = payload.get("op") or "convert"
    croot = _cache_root(payload)

    if op == "status":
        _emit(corpus_sync.corpus_status(croot))
        return

    if op == "sync":
        _emit(corpus_sync.sync_corpus(croot, force=bool(payload.get("force"))))
        return

    if op == "install_from_source":
        _emit(corpus_sync.install_from_source(str(payload.get("source_path") or ""), croot))
        return

    if op == "search":
        hits = catalog_index.search(
            str(payload.get("query") or ""),
            limit=int(payload.get("limit") or 40),
            cache_root=croot,
        )
        _emit([h.__dict__ | {"files": list(h.files)} for h in hits])
        return

    if op == "resolve":
        paths = catalog_index.resolve_work_files(
            str(payload.get("work_id") or ""), cache_root=croot
        )
        _emit([str(p) for p in paths])
        return

    result = convert_cbeta_work(
        work_id=str(payload.get("work_id") or "") or None,
        path=str(payload.get("path") or "") or None,
        cache_root=croot,
        cross_family=bool(payload.get("cross_family", True)),
        clean=bool(payload.get("clean", False)),
        strip_lb=bool(payload.get("strip_lb", False)),
        split_unit=str(payload.get("split_unit") or "mulu"),
    )
    _emit(result)


if __name__ == "__main__":
    cli_main()
