"""DDL helpers for Atlas entity data tables."""
from __future__ import annotations

import re

RESERVED_SLUGS = frozenset({
    "_atlas_row_id", "_atlas_created_at", "_atlas_updated_at", "_id", "rowid",
})


def table_name_for_entity(entity_id: str) -> str:
    hex_part = entity_id.replace("-", "")[:8].lower()
    return f"ent_{hex_part}"


def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        raise ValueError("Field name must contain at least one alphanumeric character")
    if s[0].isdigit():
        s = f"col_{s}"
    if s in RESERVED_SLUGS:
        raise ValueError(f"Reserved field name: {s}")
    return s


def validate_slug(slug: str) -> None:
    if slug in RESERVED_SLUGS:
        raise ValueError(f"Reserved field name: {slug}")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_entity_table(conn, table_name: str) -> None:
    sql = f"""CREATE TABLE IF NOT EXISTS {_quote_ident(table_name)} (
        _atlas_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        _atlas_created_at DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        _atlas_updated_at DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        data TEXT NOT NULL DEFAULT '{{}}'
    )"""
    conn.execute(sql)


def drop_entity_table(conn, table_name: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {_quote_ident(table_name)}")
