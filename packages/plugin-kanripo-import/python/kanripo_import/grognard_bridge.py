"""JSON stdin/stdout bridge for Kanripo convert + parallel punctuation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _ensure_plugin_install_path() -> None:
    if os.environ.get("GROGNARD_PLUGIN_INSTALL_PATH", "").strip():
        return
    inferred = Path(__file__).resolve().parents[2]
    if (inferred / "data" / "gaiji" / "charlist.org.txt").is_file():
        os.environ["GROGNARD_PLUGIN_INSTALL_PATH"] = str(inferred)


def cli_main() -> None:
    payload = json.load(sys.stdin)
    _ensure_plugin_install_path()

    op = payload.get("op") or "convert"

    if op == "fetch_juan":
        from kanripo_import.kanripo_fetch import fetch_juan_to_cache, resolve_juan_loc

        kr_id = str(payload.get("kr_id") or "").strip()
        juan = str(payload.get("juan") or "").strip()
        cache_root = str(payload.get("cache_root") or "").strip()
        if not cache_root:
            raise SystemExit("fetch_juan requires cache_root")
        path = fetch_juan_to_cache(kr_id=kr_id, juan=juan, cache_root=cache_root)
        loc = resolve_juan_loc(kr_id, juan)
        result = {
            "kr_id": kr_id,
            "loc": loc,
            "path": str(path),
            "files": [str(path)],
        }
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "concordance_lookup":
        from dataclasses import asdict

        from kanripo_import.concordance import lookup_daozang_rel_path, lookup_dz_id
        from kanripo_import.crosswalk import lookup_parallel_crosswalk

        kr_id = str(payload.get("kr_id") or "").strip()
        entry = lookup_daozang_rel_path(kr_id)
        crosswalk = lookup_parallel_crosswalk(kr_id)
        result = {
            "kr_id": kr_id,
            "dz_id": lookup_dz_id(kr_id),
            "daozang": asdict(entry) if entry else None,
            "parallel_crosswalk": asdict(crosswalk) if crosswalk else None,
        }
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "parallel_punct":
        from kanripo_import.parallel_punct import (
            apply_parallel_segmented_sources,
            apply_parallel_sources,
            coverage_from_stamps,
            enrich_parallel_result,
            merge_split_comm_notes,
        )

        body_xml = str(payload.get("body_xml") or "")
        mode = str(payload.get("mode") or "tape")
        if payload.get("merge_comm", True):
            body_xml = merge_split_comm_notes(body_xml)
        if payload.get("stamps_only"):
            result = {
                "body_xml": body_xml,
                "coverage": coverage_from_stamps(body_xml),
                "applied": False,
            }
            json.dump(result, sys.stdout, ensure_ascii=False)
            sys.stdout.write("\n")
            return

        sources = payload.get("sources")
        if not isinstance(sources, list):
            sources = [
                {
                    "id": "paste",
                    "label": "Paste",
                    "text": str(payload.get("parallel_text") or ""),
                }
            ]
        if mode == "segmented":
            result = apply_parallel_segmented_sources(body_xml, sources)
        else:
            used_chapter_ids = payload.get("used_chapter_ids")
            if not isinstance(used_chapter_ids, list):
                used_chapter_ids = []
            result = apply_parallel_sources(
                body_xml,
                sources,
                used_chapter_ids=[str(item) for item in used_chapter_ids],
            )
        enrich_parallel_result(result, sources)
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "ai_punct_list_segments":
        from kanripo_import.ai_punct import bridge_list_segments

        json.dump(bridge_list_segments(payload), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "ai_punct_apply":
        from kanripo_import.ai_punct import bridge_apply

        json.dump(bridge_apply(payload), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "purge_punct":
        from kanripo_import.ai_punct import bridge_purge

        json.dump(bridge_purge(payload), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "reflow_paragraphs":
        from kanripo_import.ai_punct import bridge_reflow

        json.dump(bridge_reflow(payload), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "ai_punct_parallel_apply":
        from kanripo_import.ai_punct import bridge_ai_parallel_apply

        json.dump(bridge_ai_parallel_apply(payload), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if op == "punct_coverage":
        from kanripo_import.ai_punct import bridge_punct_coverage

        json.dump(bridge_punct_coverage(payload), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    from kanripo_import.kanripo_tei import convert_kanripo_txt

    path = Path(str(payload.get("path") or ""))
    if not path.is_file():
        raise SystemExit(f"Kanripo file not found: {path}")
    normalize = payload.get("normalize") or "off"
    if normalize not in ("off", "dpm", "hard_replacements"):
        raise SystemExit(f"Unknown normalize mode: {normalize}")

    gaiji_dest = payload.get("gaiji_dest_dir")
    result = convert_kanripo_txt(
        path,
        normalize=normalize,
        gaiji_dest_dir=Path(gaiji_dest) if gaiji_dest else None,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    cli_main()
