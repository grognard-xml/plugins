"""Build-time CBDB person lookup for SKQS author → Wikidata resolution."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "python"))

from kanripo_import.person_name_normalize import (  # noqa: E402
    clean_skqs_person_name,
    dynasty_lookup_labels,
    normalize_person_name,
    normalize_skqs_dynasty,
    person_name_match_variants,
)

# SKQS placeholder for anonymous authorship — never resolve to an authority record.
SKQS_IGNORED_AUTHOR_NAMES: frozenset[str] = frozenset({"闕名"})

# Honorific/temple prefixes stripped before suffix matching (e.g. 高宗弘曆 → 弘曆).
IMPERIAL_NAME_PREFIXES: tuple[str, ...] = (
    "聖祖",
    "世祖",
    "高宗",
    "世宗",
    "太祖",
    "太宗",
    "中宗",
    "穆宗",
    "德宗",
)

MING_QING_DYNASTIES: frozenset[str] = frozenset({"明", "清"})

# SKQS dynasty labels → compatible CBDB dynasty labels.
DYNASTY_ALIASES: dict[str, tuple[str, ...]] = {
    "周": ("周", "明前"),
    "漢": ("漢", "明前", "西漢", "東漢", "前漢", "後漢"),
    "魏": ("魏", "明前", "三國魏", "曹魏"),
    "晉": ("晉", "明前", "西晉", "東晉"),
    "吳": ("吳", "明前", "三國", "東吳", "三國吳"),
    "隋": ("隋", "明前"),
    "唐": ("唐",),
    "宋": ("宋", "北宋", "南宋"),
    "元": ("元", "明前", "蒙古"),
    "明": ("明",),
    "清": ("清",),
    "北魏": ("北魏", "後魏"),
    "南朝": ("南朝", "宋", "齊", "梁", "陳"),
    "北朝": ("北朝", "北魏", "北齊", "北周"),
    "北齊": ("北齊",),
    "北周": ("北周",),
}


@dataclass(frozen=True)
class CbdbHit:
    cbdb_id: str
    dynasty: str
    primary_name: str
    matched_string: str
    match_kind: str  # exact_primary | exact_string | suffix_primary


def _dynasty_labels(skqs_dynasty: str) -> frozenset[str]:
    dynasty = normalize_skqs_dynasty((skqs_dynasty or "").strip())
    if not dynasty:
        return frozenset()
    labels = set(dynasty_lookup_labels(dynasty))
    labels.update(DYNASTY_ALIASES.get(dynasty, ()))
    return frozenset(labels)


def dynasty_compatible(skqs_dynasty: str, cbdb_dynasty: str) -> bool:
    skqs = normalize_skqs_dynasty((skqs_dynasty or "").strip())
    cbdb = (cbdb_dynasty or "").strip()
    if not skqs:
        return True
    if skqs == cbdb:
        return True
    allowed = _dynasty_labels(skqs)
    return cbdb in allowed


def query_name_variants(person_name: str) -> list[str]:
    name = (person_name or "").strip()
    if not name:
        return []
    variants = person_name_match_variants(name)
    stripped: list[str] = []
    for prefix in IMPERIAL_NAME_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix):
            stripped.append(name[len(prefix) :])
    for piece in stripped:
        norm = normalize_person_name(piece)
        if norm and norm not in variants:
            variants.append(norm)
    if len(name) >= 2:
        tail = name[-2:]
        if tail not in variants:
            variants.append(tail)
    return list(dict.fromkeys(variants))


def suffix_keys(person_name: str) -> list[str]:
    keys: list[str] = []
    for variant in query_name_variants(person_name):
        if len(variant) >= 2:
            keys.append(variant[-2:])
        if len(variant) >= 3:
            keys.append(variant[-3:])
    return list(dict.fromkeys(keys))


def load_cbdb_wikidata_map(
    *,
    concordance_path: Path,
    wikidata_pack_roots: list[Path] | None = None,
) -> dict[str, str]:
    """Map CBDB person id → Wikidata Q-id from concordance + pack crosswalks."""
    out: dict[str, str] = {}
    if concordance_path.is_file():
        with concordance_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                cbdb = str(row.get("cbdb") or "").strip()
                qid = str(row.get("wikidata") or "").strip()
                if cbdb and qid:
                    out[cbdb] = qid if qid.startswith("Q") else f"Q{qid}"

    if wikidata_pack_roots:
        for root in wikidata_pack_roots:
            if not root.is_dir():
                continue
            for path in root.glob("person-*/persons.ndjson"):
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        row = json.loads(line)
                        qid = (row.get("authorityId") or "").strip()
                        crosswalk = (row.get("metadata") or {}).get("crosswalk") or {}
                        cbdb = str(crosswalk.get("cbdb") or "").strip()
                        if cbdb and qid and cbdb not in out:
                            out[cbdb] = qid
    return out


def load_wikidata_by_name_dynasty(pack_roots: list[Path]) -> dict[str, str]:
    """Index normalized ``name|dynasty`` → Wikidata Q-id from person packs."""
    out: dict[str, str] = {}
    for root in pack_roots:
        if not root.is_dir():
            continue
        for path in root.glob("person-*/persons.ndjson"):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    qid = (row.get("authorityId") or "").strip()
                    if not qid:
                        continue
                    dynasty = normalize_skqs_dynasty(
                        ((row.get("metadata") or {}).get("dynasty") or "").strip()
                    )
                    strings = {row.get("primaryName") or "", *(row.get("searchStrings") or [])}
                    for raw in strings:
                        for variant in person_name_match_variants(str(raw).strip()):
                            if not variant:
                                continue
                            for dyn in _dynasty_labels(dynasty) or {dynasty}:
                                key = f"{variant}|{dyn}"
                                if key not in out:
                                    out[key] = qid
    return out


class CbdbPersonIndex:
    def __init__(
        self,
        *,
        by_exact: dict[str, list[CbdbHit]],
        by_suffix: dict[str, list[CbdbHit]],
        by_norm_primary: dict[str, list[CbdbHit]],
        cbdb_to_wikidata: dict[str, str],
        wikidata_by_name_dynasty: dict[str, str],
    ) -> None:
        self._by_exact = by_exact
        self._by_suffix = by_suffix
        self._by_norm_primary = by_norm_primary
        self._cbdb_to_wikidata = cbdb_to_wikidata
        self._wikidata_by_name_dynasty = wikidata_by_name_dynasty

    @classmethod
    def from_ndjson(
        cls,
        path: Path,
        *,
        cbdb_to_wikidata: dict[str, str],
        wikidata_by_name_dynasty: dict[str, str] | None = None,
    ) -> CbdbPersonIndex:
        by_exact: dict[str, list[CbdbHit]] = {}
        by_suffix: dict[str, list[CbdbHit]] = {}
        by_norm_primary: dict[str, list[CbdbHit]] = {}

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                cbdb_id = str(row.get("authorityId") or "").strip()
                primary = (row.get("primaryName") or "").strip()
                dynasty = ((row.get("metadata") or {}).get("dynasty") or "").strip()
                if not cbdb_id or not primary:
                    continue
                norm_primary = normalize_person_name(primary)
                primary_hit = CbdbHit(
                    cbdb_id=cbdb_id,
                    dynasty=dynasty,
                    primary_name=primary,
                    matched_string=primary,
                    match_kind="exact_primary",
                )
                by_norm_primary.setdefault(norm_primary, []).append(primary_hit)

                strings = list(dict.fromkeys([primary, *(row.get("searchStrings") or [])]))
                for text in strings:
                    text = (text or "").strip()
                    if not text:
                        continue
                    for variant in person_name_match_variants(text):
                        if variant == primary:
                            hit = primary_hit
                        else:
                            hit = CbdbHit(
                                cbdb_id=cbdb_id,
                                dynasty=dynasty,
                                primary_name=primary,
                                matched_string=variant,
                                match_kind="exact_string",
                            )
                        by_exact.setdefault(variant, []).append(hit)
                        if len(variant) >= 2:
                            by_suffix.setdefault(variant[-2:], []).append(
                                CbdbHit(
                                    cbdb_id=cbdb_id,
                                    dynasty=dynasty,
                                    primary_name=primary,
                                    matched_string=variant,
                                    match_kind="suffix_primary",
                                )
                            )
        return cls(
            by_exact=by_exact,
            by_suffix=by_suffix,
            by_norm_primary=by_norm_primary,
            cbdb_to_wikidata=cbdb_to_wikidata,
            wikidata_by_name_dynasty=wikidata_by_name_dynasty or {},
        )

    def _wikidata_for_name_dynasty(self, person_name: str, dynasty: str) -> str:
        for variant in person_name_match_variants(person_name):
            for dyn in _dynasty_labels(dynasty) or {normalize_skqs_dynasty(dynasty)}:
                qid = self._wikidata_by_name_dynasty.get(f"{variant}|{dyn}")
                if qid:
                    return qid
        return ""

    def _wikidata_for_cbdb_hit(self, hit: CbdbHit, person_name: str, dynasty: str) -> str:
        qid = self._cbdb_to_wikidata.get(hit.cbdb_id, "")
        if qid:
            return qid
        return self._wikidata_for_name_dynasty(person_name, dynasty)

    def _pick_unique_hit(
        self,
        candidates: dict[str, CbdbHit],
        *,
        person_name: str,
        dynasty: str,
        source_prefix: str,
    ) -> tuple[str, str, str]:
        """Return ``(wikidata_qid, cbdb_id, source_tag)`` or ``("", "", "")``."""
        if not candidates:
            return "", "", ""
        pool = list(candidates.values())
        with_qid = [hit for hit in pool if self._wikidata_for_cbdb_hit(hit, person_name, dynasty)]
        if with_qid:
            pool = with_qid
        norm_name = normalize_person_name(person_name)
        primary_exact = [
            hit
            for hit in pool
            if normalize_person_name(hit.primary_name) == norm_name
            or normalize_person_name(hit.matched_string) == norm_name
        ]
        if len(primary_exact) == 1:
            pool = primary_exact
        elif len(primary_exact) > 1:
            pool = primary_exact
        if len(pool) != 1:
            return "", "", ""
        hit = pool[0]
        qid = self._wikidata_for_cbdb_hit(hit, person_name, dynasty)
        source = source_prefix
        if hit.match_kind == "suffix_primary":
            source = f"{source_prefix}_suffix"
        return qid, hit.cbdb_id, source

    def _ming_qing_unique_hits(self, person_name: str, dynasty: str) -> dict[str, CbdbHit]:
        skqs_dyn = normalize_skqs_dynasty(dynasty)
        if skqs_dyn not in MING_QING_DYNASTIES:
            return {}
        hits: dict[str, CbdbHit] = {}
        for variant in person_name_match_variants(person_name):
            norm = normalize_person_name(variant)
            for hit in self._by_norm_primary.get(norm, []):
                if hit.dynasty not in MING_QING_DYNASTIES:
                    continue
                hits[hit.cbdb_id] = hit
        return hits

    def lookup(self, person_name: str, dynasty: str) -> tuple[str, str, str]:
        """Return ``(wikidata_qid, cbdb_id, source_tag)`` or ``("", "", "")``."""
        name = (person_name or "").strip()
        if not name or name in SKQS_IGNORED_AUTHOR_NAMES:
            return "", "", ""

        candidates: dict[str, CbdbHit] = {}
        for variant in query_name_variants(name):
            for hit in self._by_exact.get(variant, []):
                if not dynasty_compatible(dynasty, hit.dynasty):
                    continue
                if hit.match_kind == "exact_primary":
                    candidates[hit.cbdb_id] = hit
                elif hit.match_kind == "exact_string" and normalize_person_name(hit.primary_name) == normalize_person_name(
                    variant
                ):
                    candidates[hit.cbdb_id] = hit

            for key in suffix_keys(variant):
                for hit in self._by_suffix.get(key, []):
                    if not dynasty_compatible(dynasty, hit.dynasty):
                        continue
                    if hit.primary_name.endswith(variant) and len(hit.primary_name) > len(variant):
                        candidates[hit.cbdb_id] = hit

        qid, cbdb_id, source = self._pick_unique_hit(
            candidates, person_name=name, dynasty=dynasty, source_prefix="cbdb_dynasty"
        )
        if cbdb_id:
            return qid, cbdb_id, source

        ming_qing = self._ming_qing_unique_hits(name, dynasty)
        return self._pick_unique_hit(
            ming_qing, person_name=name, dynasty=dynasty, source_prefix="cbdb_ming_qing"
        )


def default_cbdb_persons_path(plugin_root: Path) -> Path | None:
    import os

    candidates: list[Path] = []
    env_path = os.environ.get("LJB_CBDB_PERSONS_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            plugin_root.parents[2] / "authority extraction" / "packs" / "cbdb" / "persons.ndjson",
            plugin_root.parents[3] / "authority extraction" / "packs" / "cbdb" / "persons.ndjson",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def default_cbdb_concordance_path(plugin_root: Path) -> Path | None:
    candidates = [
        plugin_root.parents[2] / "authority extraction" / "packs" / "wikidata" / "cbdb-wikidata-concordance.ndjson",
        plugin_root.parents[3] / "authority extraction" / "packs" / "wikidata" / "cbdb-wikidata-concordance.ndjson",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def build_cbdb_person_index(
    *,
    plugin_root: Path,
    persons_path: Path | None = None,
    concordance_path: Path | None = None,
    wikidata_pack_roots: list[Path] | None = None,
) -> CbdbPersonIndex | None:
    persons = persons_path or default_cbdb_persons_path(plugin_root)
    concordance = concordance_path or default_cbdb_concordance_path(plugin_root)
    if not persons or not persons.is_file():
        return None
    roots = wikidata_pack_roots or []
    cbdb_to_wikidata = load_cbdb_wikidata_map(
        concordance_path=concordance or Path("/dev/null"),
        wikidata_pack_roots=roots,
    )
    wikidata_by_name_dynasty = load_wikidata_by_name_dynasty(roots) if roots else {}
    return CbdbPersonIndex.from_ndjson(
        persons,
        cbdb_to_wikidata=cbdb_to_wikidata,
        wikidata_by_name_dynasty=wikidata_by_name_dynasty,
    )
