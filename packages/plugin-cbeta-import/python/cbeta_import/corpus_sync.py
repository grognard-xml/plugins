"""Fetch / update the ``cbeta-xml-p5`` checkout under the installed plugin.

Cloned automatically when the plugin is installed or enabled (desktop host);
``install_from_source`` accepts a local git clone, canon-folder directory, or
archive for offline setup. Pinned to ``DATA_VERSION_TAG``; the resolved commit is
recorded in ``data/corpus.json`` for provenance. ``import`` touches no network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cbeta_import import _paths
from cbeta_import.constants import DATA_VERSION_TAG, XML_P5_REPO

_GIT_MISSING = (
    "git is not installed or not on PATH. Install git, or use "
    "'install_from_source' with a local clone / archive."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(*args: str, cwd: Path | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    if not shutil.which("git"):
        raise RuntimeError(_GIT_MISSING)
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        cmd = " ".join(["git", *args])
        raise RuntimeError(f"{cmd} failed (exit {exc.returncode}): {detail}") from exc


def _head_commit(checkout: Path) -> str:
    try:
        return _git("-C", str(checkout), "rev-parse", "HEAD").stdout.strip()
    except (subprocess.CalledProcessError, RuntimeError):
        return ""


def _looks_like_corpus(path: Path) -> bool:
    """A dir that holds canon folders (``T/``, ``X/`` …) — the xml-p5 layout."""
    return _paths.corpus_is_present(path)


def _find_corpus_root(start: Path) -> Path | None:
    if _looks_like_corpus(start):
        return start
    for child in sorted(p for p in start.iterdir() if p.is_dir()):
        if _looks_like_corpus(child):
            return child
    return None


def _data_root(cache_root: Path | None = None) -> Path:
    return Path(cache_root) if cache_root is not None else _paths.data_dir()


def _target_checkout(cache_root: Path | None = None) -> Path:
    return _data_root(cache_root) / "corpus" / "xml-p5"


def _write_manifest(data_root: Path, payload: dict[str, object]) -> None:
    mpath = data_root / "corpus.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def corpus_status(cache_root: Path | None = None) -> dict[str, object]:
    data_root = _data_root(cache_root)
    checkout = _paths.corpus_dir(cache_root)
    is_git = (checkout / ".git").is_dir()
    present = is_git or _looks_like_corpus(checkout)
    manifest: dict[str, object] = {}
    mpath = data_root / "corpus.json"
    if mpath.is_file():
        try:
            manifest = json.loads(mpath.read_text("utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    return {
        "present": present,
        "is_git": is_git,
        "path": str(checkout),
        "pinned_tag": DATA_VERSION_TAG,
        "commit": _head_commit(checkout) if is_git else str(manifest.get("commit") or ""),
        "synced_at": manifest.get("synced_at"),
        "source": manifest.get("source"),
        "checked_at": _now(),
    }


def sync_corpus(cache_root: Path | None = None, *, force: bool = False) -> dict[str, object]:
    """Clone at ``DATA_VERSION_TAG`` on first run; fetch + hard-checkout the tag after."""
    data_root = _data_root(cache_root)
    checkout = _target_checkout(cache_root)

    if (checkout / ".git").is_dir():
        _git("-C", str(checkout), "fetch", "--depth", "1", "--force", "origin", "tag", DATA_VERSION_TAG)
        _git("-C", str(checkout), "checkout", "--force", DATA_VERSION_TAG)
        if force:
            _git("-C", str(checkout), "reset", "--hard", DATA_VERSION_TAG)
            _git("-C", str(checkout), "clean", "-fdx")
        action = "updated"
    else:
        if checkout.exists() and any(checkout.iterdir()):
            if not force:
                raise RuntimeError(
                    f"{checkout} exists and is not a git checkout. Re-run with force=true "
                    f"to replace it, or use install_from_source."
                )
            shutil.rmtree(checkout)
        checkout.parent.mkdir(parents=True, exist_ok=True)
        _git(
            "clone",
            "--depth",
            "1",
            "--branch",
            DATA_VERSION_TAG,
            "--single-branch",
            XML_P5_REPO,
            str(checkout),
        )
        action = "cloned"

    commit = _head_commit(checkout)
    payload = {
        "repo": XML_P5_REPO,
        "tag": DATA_VERSION_TAG,
        "commit": commit,
        "synced_at": _now(),
        "source": "git",
    }
    _write_manifest(data_root, payload)
    _paths.cached_catalog_index_path(cache_root).unlink(missing_ok=True)
    return {"action": action, "path": str(checkout), **payload}


def install_from_source(
    source_path: Path | str, cache_root: Path | None = None
) -> dict[str, object]:
    """Populate the checkout from a local clone, a dir of canon folders, or an archive."""
    src = Path(source_path).expanduser()
    data_root = _data_root(cache_root)
    checkout = _target_checkout(cache_root)
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    if checkout.exists():
        shutil.rmtree(checkout)
    checkout.parent.mkdir(parents=True, exist_ok=True)

    kind: str
    commit = ""
    if src.is_dir() and (src / ".git").is_dir():
        _git("clone", "--local", str(src), str(checkout))
        commit = _head_commit(checkout)
        kind = "local-clone"
    elif src.is_dir():
        corpus_root = _find_corpus_root(src)
        if corpus_root is None:
            raise RuntimeError(f"no canon folders (T/, X/ …) found under {src}")
        shutil.copytree(corpus_root, checkout)
        kind = "directory"
    else:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            if src.suffix == ".zip":
                with zipfile.ZipFile(src) as zf:
                    zf.extractall(tmp_path)
            elif src.name.endswith((".tar", ".tar.gz", ".tgz")):
                with tarfile.open(src) as tf:
                    tf.extractall(tmp_path)  # noqa: S202 — local, user-supplied archive
            else:
                raise RuntimeError(f"unsupported archive: {src.name}")
            corpus_root = _find_corpus_root(tmp_path)
            if corpus_root is None:
                raise RuntimeError(f"no canon folders (T/, X/ …) found in {src.name}")
            shutil.copytree(corpus_root, checkout)
        kind = f"archive:{src.suffix.lstrip('.')}"

    payload = {
        "repo": XML_P5_REPO,
        "tag": DATA_VERSION_TAG,
        "commit": commit,
        "synced_at": _now(),
        "source": f"install_from_source:{kind}",
        "source_path": str(src),
    }
    _write_manifest(data_root, payload)
    _paths.cached_catalog_index_path(cache_root).unlink(missing_ok=True)
    return {"action": "installed", "kind": kind, "path": str(checkout), **payload}
