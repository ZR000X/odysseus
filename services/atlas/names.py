"""Shared Atlas display-name uniqueness (collections + queries per world)."""
from __future__ import annotations

import sqlite3
from typing import Optional


def assert_unique_atlas_name(
    conn: sqlite3.Connection,
    name: str,
    *,
    exclude_entity_id: Optional[str] = None,
    exclude_query_id: Optional[str] = None,
) -> str:
    """Return normalized name or raise ValueError if taken (case-insensitive)."""
    normalized = (name or "").strip() or "Untitled"
    key = normalized.lower()

    ent_row = conn.execute(
        "SELECT id, name FROM atlas_entities WHERE LOWER(name) = ?",
        (key,),
    ).fetchone()
    if ent_row and ent_row["id"] != exclude_entity_id:
        raise ValueError(f"Name already used by collection '{ent_row['name']}'")

    q_row = conn.execute(
        "SELECT id, name FROM atlas_queries WHERE LOWER(name) = ?",
        (key,),
    ).fetchone()
    if q_row and q_row["id"] != exclude_query_id:
        raise ValueError(f"Name already used by query '{q_row['name']}'")

    return normalized


def find_dependent_query_ids(
    conn: sqlite3.Connection,
    source_id: str,
    source_type: str,
) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT query_id FROM atlas_query_deps
           WHERE source_id = ? AND source_type = ?""",
        (source_id, source_type),
    ).fetchall()
    return [r["query_id"] for r in rows]
