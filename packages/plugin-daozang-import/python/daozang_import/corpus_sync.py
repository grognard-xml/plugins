"""Download, extract, and normalise the Fang Tongzi Daozang archive."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from daozang_import.constants import (
    CORPUS_ARCHIVE_NAME,
    CORPUS_INDEX_NAME,
    CORPUS_MANIFEST_NAME,
    CORPUS_SOURCE_URL,
    RAW_DIR_NAME,
    UTF8_DIR_NAME,
)
from daozang_import.corpus_index import write_index
from daozang_import.encoding import decode_legacy_text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_command(archive_path: Path, dest_dir: Path) -> list[str] | None:
    archive = str(archive_path)
    dest = str(dest_dir)
    for candidate in (
        ["unar", "-force-overwrite", "-output-directory", dest, archive],
        ["7z", "x", "-y", f"-o{dest}", archive],
        ["unrar", "x", "-o+", archive, dest],
        ["bsdtar", "-xf", archive, "-C", dest],
    ):
        if shutil.which(candidate[0]):
            return candidate
    return None


def extract_archive(archive_path: Path, raw_root: Path) -> None:
    if raw_root.exists():
        shutil.rmtree(raw_root)
    raw_root.mkdir(parents=True, exist_ok=True)
    command = _extract_command(archive_path, raw_root)
    if not command:
        raise RuntimeError(
            "No RAR extractor found. Install unar (recommended), 7z, unrar, or bsdtar."
        )
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(message or f"Archive extraction failed: {' '.join(command)}")


def convert_tree_to_utf8(raw_root: Path, utf8_root: Path) -> int:
    if utf8_root.exists():
        shutil.rmtree(utf8_root)
    utf8_root.mkdir(parents=True, exist_ok=True)
    converted = 0
    for source in sorted(raw_root.rglob("*")):
        if not source.is_file():
            continue
        if source.suffix.lower() not in {".txt"}:
            continue
        rel = source.relative_to(raw_root)
        target = utf8_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        raw_bytes = source.read_bytes()
        target.write_text(decode_legacy_text(raw_bytes), encoding="utf-8")
        converted += 1
    return converted


def write_manifest(
    cache_root: Path,
    *,
    text_count: int,
    source_kind: str,
    source_path: str = "",
    archive_sha256: str = "",
) -> None:
    payload = {
        "sourceKind": source_kind,
        "sourcePath": source_path,
        "upstreamUrl": CORPUS_SOURCE_URL,
        "archiveName": CORPUS_ARCHIVE_NAME,
        "archiveSha256": archive_sha256,
        "syncedAt": datetime.now(timezone.utc).isoformat(),
        "textCount": text_count,
        "transcriber": "方瞳子源 (Fang Tongzi)",
    }
    (cache_root / CORPUS_MANIFEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _finalize_cache(
    cache_root: Path,
    *,
    source_kind: str,
    source_path: str = "",
    archive_sha256: str = "",
) -> dict[str, object]:
    utf8_root = cache_root / UTF8_DIR_NAME
    entries = write_index(utf8_root, cache_root / CORPUS_INDEX_NAME)
    write_manifest(
        cache_root,
        text_count=len(entries),
        source_kind=source_kind,
        source_path=source_path,
        archive_sha256=archive_sha256,
    )
    manifest = json.loads((cache_root / CORPUS_MANIFEST_NAME).read_text(encoding="utf-8"))
    return {
        "textCount": len(entries),
        "manifest": manifest,
    }


def process_local_rar(cache_root: Path, rar_path: Path) -> dict[str, object]:
    cache_root = Path(cache_root)
    rar_path = Path(rar_path)
    if not rar_path.is_file():
        raise FileNotFoundError(f"RAR not found: {rar_path}")

    cache_root.mkdir(parents=True, exist_ok=True)
    archive_path = cache_root / CORPUS_ARCHIVE_NAME
    shutil.copy2(rar_path, archive_path)

    raw_root = cache_root / RAW_DIR_NAME
    utf8_root = cache_root / UTF8_DIR_NAME
    extract_archive(archive_path, raw_root)
    converted = convert_tree_to_utf8(raw_root, utf8_root)
    archive_sha256 = _sha256_file(archive_path)
    result = _finalize_cache(
        cache_root,
        source_kind="local-rar",
        source_path=str(rar_path),
        archive_sha256=archive_sha256,
    )
    result["converted"] = converted
    result["reused"] = False
    return result


def install_utf8_tree(cache_root: Path, utf8_source: Path, *, source_path: str) -> dict[str, object]:
    cache_root = Path(cache_root)
    utf8_source = Path(utf8_source)
    if not utf8_source.is_dir():
        raise NotADirectoryError(f"UTF-8 corpus folder not found: {utf8_source}")

    cache_root.mkdir(parents=True, exist_ok=True)
    utf8_root = cache_root / UTF8_DIR_NAME
    if utf8_root.exists():
        shutil.rmtree(utf8_root)
    shutil.copytree(utf8_source, utf8_root)

    result = _finalize_cache(cache_root, source_kind="pack", source_path=source_path)
    result["reused"] = False
    return result


def install_corpus_pack(cache_root: Path, pack_path: Path) -> dict[str, object]:
    pack_path = Path(pack_path)
    if not pack_path.is_file():
        raise FileNotFoundError(f"Corpus pack not found: {pack_path}")

    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    staging = cache_root / ".pack-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    with tarfile.open(pack_path, "r:*") as archive:
        archive.extractall(staging)

    roots = [staging]
    entries = list(staging.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        roots = [entries[0]]

    pack_root = roots[0]
    utf8_dir = pack_root / UTF8_DIR_NAME
    if not utf8_dir.is_dir():
        raise RuntimeError(f"Corpus pack is missing {UTF8_DIR_NAME}/: {pack_path}")

    manifest_src = pack_root / CORPUS_MANIFEST_NAME
    utf8_root = cache_root / UTF8_DIR_NAME
    if utf8_root.exists():
        shutil.rmtree(utf8_root)
    shutil.copytree(utf8_dir, utf8_root)
    if manifest_src.is_file():
        shutil.copy2(manifest_src, cache_root / CORPUS_MANIFEST_NAME)

    index_src = pack_root / CORPUS_INDEX_NAME
    if index_src.is_file():
        shutil.copy2(index_src, cache_root / CORPUS_INDEX_NAME)
        manifest = json.loads((cache_root / CORPUS_MANIFEST_NAME).read_text(encoding="utf-8"))
        if not manifest:
            write_manifest(
                cache_root,
                text_count=len(json.loads(index_src.read_text(encoding="utf-8"))),
                source_kind="pack",
                source_path=str(pack_path),
            )
        return {
            "reused": False,
            "textCount": len(json.loads(index_src.read_text(encoding="utf-8"))),
            "manifest": json.loads((cache_root / CORPUS_MANIFEST_NAME).read_text(encoding="utf-8")),
        }

    result = _finalize_cache(cache_root, source_kind="pack", source_path=str(pack_path))
    result["reused"] = False
    return result


def install_from_source(cache_root: Path, source_path: Path) -> dict[str, object]:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Corpus source not found: {source}")

    if source.is_file() and source.suffix.lower() == ".rar":
        return process_local_rar(cache_root, source)

    if source.is_file() and (source.name.endswith(".tar.gz") or source.name.endswith(".tgz")):
        return install_corpus_pack(cache_root, source)

    if source.is_dir():
        utf8_dir = source / UTF8_DIR_NAME
        if utf8_dir.is_dir():
            return install_utf8_tree(cache_root, utf8_dir, source_path=str(source))
        if any(source.rglob("*.txt")):
            cache_root = Path(cache_root)
            cache_root.mkdir(parents=True, exist_ok=True)
            raw_root = cache_root / RAW_DIR_NAME
            utf8_root = cache_root / UTF8_DIR_NAME
            if raw_root.exists():
                shutil.rmtree(raw_root)
            shutil.copytree(source, raw_root)
            converted = convert_tree_to_utf8(raw_root, utf8_root)
            result = _finalize_cache(cache_root, source_kind="local-folder", source_path=str(source))
            result["converted"] = converted
            result["reused"] = False
            return result

    raise RuntimeError(
        "Unsupported corpus source. Choose the Fang Tongzi .rar, an extracted folder of .txt files, "
        "or an Grognard corpus pack (.tar.gz with utf8/)."
    )


def rebuild_from_cached_archive(cache_root: Path) -> dict[str, object]:
    cache_root = Path(cache_root)
    archive_path = cache_root / CORPUS_ARCHIVE_NAME
    if not archive_path.is_file():
        raise FileNotFoundError(
            f"No cached {CORPUS_ARCHIVE_NAME} found. Install the corpus from a local file first."
        )
    return process_local_rar(cache_root, archive_path)


def sync_corpus(cache_root: Path, *, force: bool = False) -> dict[str, object]:
    """Rebuild the searchable cache from an already-installed local corpus."""
    cache_root = Path(cache_root)
    manifest_path = cache_root / CORPUS_MANIFEST_NAME
    utf8_root = cache_root / UTF8_DIR_NAME

    if not force and manifest_path.is_file() and utf8_root.is_dir():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = write_index(utf8_root, cache_root / CORPUS_INDEX_NAME)
        return {
            "reused": True,
            "textCount": len(entries),
            "manifest": manifest,
        }

    return rebuild_from_cached_archive(cache_root)


def corpus_status(cache_root: Path) -> dict[str, object]:
    cache_root = Path(cache_root)
    manifest_path = cache_root / CORPUS_MANIFEST_NAME
    index_path = cache_root / CORPUS_INDEX_NAME
    utf8_root = cache_root / UTF8_DIR_NAME
    ready = manifest_path.is_file() and index_path.is_file() and utf8_root.is_dir()
    manifest = {}
    text_count = 0
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        text_count = int(manifest.get("textCount") or 0)
    if ready and text_count == 0 and index_path.is_file():
        text_count = len(json.loads(index_path.read_text(encoding="utf-8")))
    return {
        "ready": ready,
        "textCount": text_count,
        "manifest": manifest,
        "cacheRoot": str(cache_root),
    }
