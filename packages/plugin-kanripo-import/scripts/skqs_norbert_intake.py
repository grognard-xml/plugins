#!/usr/bin/env python3
"""
Insert unresolved SKQS authors directly into Norbert and write override CSV.

Uses ``sql_norbert.py`` at the plugins repo root (gitignored) for DB access.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_ROOT = _PLUGIN_ROOT.parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "python"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(_PLUGINS_ROOT))

from kanripo_import.chinese_name_split import segment_person_name
from kanripo_import.norbert_dynasty_map import norbert_court_id
from kanripo_import.person_name_normalize import clean_skqs_person_name

CREATED_BY = "LJB_SKQS"
NAME_TYPE_FAMILY = 0
NAME_TYPE_GIVEN = 1


def _author_key(person_name: str, dynasty: str) -> str:
    return f"{person_name.strip()}|{dynasty.strip()}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(handle)]


def _sources_dir() -> Path:
    return _PLUGIN_ROOT / "data" / "metadata" / "sources"


def _metadata_dir() -> Path:
    return _PLUGIN_ROOT / "data" / "metadata"


def _load_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        name = clean_skqs_person_name(row.get("person_name") or "")
        dynasty = (row.get("dynasty") or "").strip()
        norbert_id = (row.get("norbert_id") or "").strip()
        if name and norbert_id:
            out[_author_key(name, dynasty)] = {
                "norbert_id": norbert_id,
                "note": (row.get("note") or "").strip(),
            }
    return out


def _load_unresolved_rows() -> list[dict[str, Any]]:
    path = _metadata_dir() / "krp_skqs_author_wikidata.json"
    if not path.is_file():
        raise SystemExit(f"Missing {path}; run build:skqs-authors first.")
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries") or {}
    resolved_keys = set(entries.keys())
    csv_path = _metadata_dir() / "krp_skqs_author_wikidata_unresolved.csv"
    rows: list[dict[str, Any]] = []
    for row in _read_csv(csv_path):
        name = clean_skqs_person_name(row.get("person_name") or "")
        dynasty = (row.get("dynasty") or "").strip()
        key = _author_key(name, dynasty)
        if key in resolved_keys:
            continue
        rows.append(
            {
                "person_name": name,
                "dynasty": dynasty,
                "sample_kr_id": (row.get("sample_kr_id") or "").strip(),
                "work_count": int(row.get("work_count") or "0"),
            }
        )
    return rows


def _get_connection():
    try:
        from sql_norbert import norbert  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "Could not import sql_norbert.py from plugins root. "
            "Create plugins/sql_norbert.py with your Norbert credentials."
        ) from exc
    try:
        engine = norbert()
        return engine.connect()
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Norbert intake needs sqlalchemy and pymysql installed in your Python env."
        ) from exc


def _find_existing_person_id(conn, can_name: str) -> str:
    from sqlalchemy import text

    rows = conn.execute(
        text("SELECT id FROM person WHERE can_name = :name ORDER BY id"),
        {"name": can_name},
    ).fetchall()
    if len(rows) == 1:
        return str(rows[0][0])
    return ""


def _insert_person(
    conn,
    *,
    can_name: str,
    dynasty: str,
    sample_kr_id: str,
    family: str,
    given: str,
    court_id: int | None,
    court_label: str,
) -> str:
    from sqlalchemy import text

    existing = _find_existing_person_id(conn, can_name)
    if existing:
        return existing

    description = f"SKQS author ({dynasty})"
    if sample_kr_id:
        description += f"; {sample_kr_id}"

    result = conn.execute(
        text(
            """
            INSERT INTO person (can_name, description, created_by)
            VALUES (:can_name, :description, :created_by)
            """
        ),
        {"can_name": can_name, "description": description, "created_by": CREATED_BY},
    )
    person_id = str(result.lastrowid)

    if family:
        conn.execute(
            text(
                """
                INSERT INTO person_names (person_id, name, name_type_id, created_by)
                VALUES (:person_id, :name, :name_type_id, :created_by)
                """
            ),
            {
                "person_id": person_id,
                "name": family,
                "name_type_id": NAME_TYPE_FAMILY,
                "created_by": CREATED_BY,
            },
        )
    if given:
        conn.execute(
            text(
                """
                INSERT INTO person_names (person_id, name, name_type_id, created_by)
                VALUES (:person_id, :name, :name_type_id, :created_by)
                """
            ),
            {
                "person_id": person_id,
                "name": given,
                "name_type_id": NAME_TYPE_GIVEN,
                "created_by": CREATED_BY,
            },
        )

    if court_id is not None:
        conn.execute(
            text(
                """
                INSERT INTO nat_raw (string, person_id, court_id, created_by)
                VALUES (:string, :person_id, :court_id, :created_by)
                """
            ),
            {
                "string": court_label or dynasty,
                "person_id": person_id,
                "court_id": court_id,
                "created_by": CREATED_BY,
            },
        )
    return person_id


def run_intake(*, dry_run: bool) -> None:
    overrides_path = _sources_dir() / "skqs_author_norbert_overrides.csv"
    existing = _load_overrides(overrides_path)
    pending = _load_unresolved_rows()
    if not pending:
        print("No unresolved SKQS authors to intake.")
        return

    planned: list[dict[str, str]] = []
    skipped = 0

    for row in pending:
        name = row["person_name"]
        dynasty = row["dynasty"]
        key = _author_key(name, dynasty)
        if key in existing:
            skipped += 1
            continue

        split = segment_person_name(name)
        family, given = split if split else ("", "")
        court_id, court_label = norbert_court_id(dynasty)
        planned.append(
            {
                "person_name": name,
                "dynasty": dynasty,
                "norbert_id": "",
                "note": row.get("sample_kr_id") or "",
                "sample_kr_id": row.get("sample_kr_id") or "",
                "court_id": "" if court_id is None else str(court_id),
                "family": family,
                "given": given,
            }
        )

    if dry_run:
        print(f"Dry run: would intake {len(planned)} authors ({skipped} already in overrides).")
        for item in planned[:10]:
            print(
                f"  {item['person_name']}|{item['dynasty']} "
                f"姓={item['family'] or '?'} 名={item['given'] or '?'} "
                f"court={item['court_id'] or '?'}"
            )
        if len(planned) > 10:
            print(f"  ... and {len(planned) - 10} more")
        return

    conn = _get_connection()
    written: list[dict[str, str]] = []
    try:
        with conn.begin():
            for item in planned:
                person_id = _insert_person(
                    conn,
                    can_name=item["person_name"],
                    dynasty=item["dynasty"],
                    sample_kr_id=item["sample_kr_id"],
                    family=item["family"],
                    given=item["given"],
                    court_id=int(item["court_id"]) if item["court_id"] else None,
                    court_label=norbert_court_id(item["dynasty"])[1],
                )
                item["norbert_id"] = person_id
                written.append(item)
    finally:
        conn.close()

    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["person_name", "dynasty", "norbert_id", "note", "sample_kr_id"]
    existing_rows = _read_csv(overrides_path) if overrides_path.is_file() else []
    merged_rows = {_author_key(r["person_name"], r["dynasty"]): r for r in existing_rows}
    for item in written:
        key = _author_key(item["person_name"], item["dynasty"])
        merged_rows[key] = {field: item.get(field, "") for field in fieldnames}
    with overrides_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(merged_rows.keys()):
            writer.writerow({field: merged_rows[key].get(field, "") for field in fieldnames})
    print(f"Inserted {len(written)} Norbert persons → {overrides_path}")
    if skipped:
        print(f"Skipped {skipped} already listed in overrides.")


_DYNASTY_RE = re.compile(r"^SKQS author \((.+?)\)")


def recover_overrides() -> None:
    """Rebuild overrides CSV from Norbert persons created by this intake."""
    from sqlalchemy import text

    conn = _get_connection()
    overrides_path = _sources_dir() / "skqs_author_norbert_overrides.csv"
    pending = _load_unresolved_rows()
    pending_by_key: dict[str, dict[str, Any]] = {}
    for row in pending:
        pending_by_key[_author_key(row["person_name"], row["dynasty"])] = row

    try:
        rows = conn.execute(
            text(
                """
                SELECT id, can_name, description
                FROM person
                WHERE created_by = :created_by
                ORDER BY id
                """
            ),
            {"created_by": CREATED_BY},
        ).fetchall()
    finally:
        conn.close()

    recovered: list[dict[str, str]] = []
    unmatched: list[str] = []
    for person_id, can_name, description in rows:
        dynasty = ""
        match = _DYNASTY_RE.match((description or "").strip())
        if match:
            dynasty = match.group(1).strip()
        key = _author_key(str(can_name), dynasty)
        pending_row = pending_by_key.get(key)
        if not pending_row:
            unmatched.append(f"{can_name}|{dynasty} (id={person_id})")
            continue
        recovered.append(
            {
                "person_name": pending_row["person_name"],
                "dynasty": pending_row["dynasty"],
                "norbert_id": str(person_id),
                "note": pending_row.get("sample_kr_id") or "",
                "sample_kr_id": pending_row.get("sample_kr_id") or "",
            }
        )

    if not recovered:
        raise SystemExit("No LJB_SKQS persons matched pending unresolved authors.")

    fieldnames = ["person_name", "dynasty", "norbert_id", "note", "sample_kr_id"]
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    with overrides_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(recovered, key=lambda item: _author_key(item["person_name"], item["dynasty"])):
            writer.writerow(row)
    print(f"Recovered {len(recovered)} Norbert overrides → {overrides_path}")
    if unmatched:
        print(f"Warning: {len(unmatched)} LJB_SKQS persons did not match unresolved list:")
        for item in unmatched[:5]:
            print(f"  {item}")
        if len(unmatched) > 5:
            print(f"  ... and {len(unmatched) - 5} more")


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert unresolved SKQS authors into Norbert.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to Norbert and save overrides (default is dry-run)",
    )
    parser.add_argument(
        "--recover-overrides",
        action="store_true",
        help="Rebuild overrides CSV from Norbert (created_by=LJB_SKQS)",
    )
    args = parser.parse_args()
    if args.recover_overrides:
        recover_overrides()
        return
    run_intake(dry_run=not args.apply)


if __name__ == "__main__":
    main()
