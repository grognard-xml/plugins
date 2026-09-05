"""JSON stdin/stdout bridge for Daozang corpus sync and TEI conversion."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from daozang_import.corpus_index import load_index, search_index
from daozang_import.corpus_sync import corpus_status, install_from_source, sync_corpus
from daozang_import.daozang_tei import convert_daozang_txt


def _ensure_plugin_install_path() -> None:
    import os

    if os.environ.get("GROGNARD_PLUGIN_INSTALL_PATH", "").strip():
        return
    inferred = Path(__file__).resolve().parents[2]
    if (inferred / "data" / "corpus" / "index.json").is_file():
        os.environ["GROGNARD_PLUGIN_INSTALL_PATH"] = str(inferred)


def cli_main() -> None:
    payload = json.load(sys.stdin)
    _ensure_plugin_install_path()
    op = payload.get("op") or "convert"

    if op == "status":
        cache_root = Path(str(payload.get("cache_root") or ""))
        json.dump(corpus_status(cache_root), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "install_from_source":
        cache_root = Path(str(payload.get("cache_root") or ""))
        source_path = Path(str(payload.get("source_path") or ""))
        result = install_from_source(cache_root, source_path)
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "sync":
        cache_root = Path(str(payload.get("cache_root") or ""))
        force = bool(payload.get("force"))
        result = sync_corpus(cache_root, force=force)
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "search":
        cache_root = Path(str(payload.get("cache_root") or ""))
        query = str(payload.get("query") or "")
        limit = int(payload.get("limit") or 40)
        entries = load_index(cache_root / "index.json")
        hits = search_index(entries, query, limit=limit)
        json.dump([hit.__dict__ for hit in hits], sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    path = Path(str(payload.get("path") or ""))
    rel_path = str(payload.get("rel_path") or path.name)
    result = convert_daozang_txt(path, rel_path=rel_path)
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    cli_main()
