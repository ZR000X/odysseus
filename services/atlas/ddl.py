"""DDL helpers for Atlas entity data tables."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

RESERVED_SLUGS = frozenset({
    "_atlas_row_id", "_atlas_created_at", "_atlas_updated_at", "rowid",
})

ATTR_TYPES = frozenset({"text", "integer", "real", "boolean"})


def table_name_for_entity(entity_id: str) -> str:
    hex_part = entity_id.replace("-", "")[:8].lower()
    return f"ent_{hex_part}"


def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        raise ValueError("Attribute name must contain at least one alphanumeric character")
    if s[0].isdigit():
        s = f"col_{s}"
    if s in RESERVED_SLUGS:
        raise ValueError(f"Reserved attribute name: {s}")
    return s


def validate_slug(slug: str) -> None:
    if slug in RESERVED_SLUGS:
        raise ValueError(f"Reserved attribute name: {slug}")


def sqlite_type(attr_type: str) -> str:
    mapping = {
        "text": "TEXT",
        "integer": "INTEGER",
        "real": "REAL",
        "boolean": "INTEGER",
    }
    t = (attr_type or "text").lower()
    if t not in ATTR_TYPES:
        raise ValueError(f"Unsupported attribute type: {attr_type}")
    return mapping[t]


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_entity_table(
    conn,
    table_name: str,
    attributes: Optional[List[Dict[str, Any]]] = None,
) -> None:
    attrs = attributes or []
    cols = [
        "_atlas_row_id INTEGER PRIMARY KEY AUTOINCREMENT",
        "_atlas_created_at DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        "_atlas_updated_at DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
    ]
    for a in attrs:
        slug = a["slug"]
        st = sqlite_type(a["attr_type"])
        null = "" if a.get("nullable", True) else " NOT NULL"
        cols.append(f"{_quote_ident(slug)} {st}{null}")
    sql = f"CREATE TABLE IF NOT EXISTS {_quote_ident(table_name)} ({', '.join(cols)})"
    conn.execute(sql)
    _ensure_indexes(conn, table_name, attrs)


def add_column(conn, table_name: str, attr: Dict[str, Any]) -> None:
    slug = attr["slug"]
    st = sqlite_type(attr["attr_type"])
    null = "" if attr.get("nullable", True) else " NOT NULL"
    conn.execute(
        f"ALTER TABLE {_quote_ident(table_name)} ADD COLUMN {_quote_ident(slug)} {st}{null}"
    )
    _ensure_indexes(conn, table_name, [attr])


def _ensure_indexes(conn, table_name: str, attributes: List[Dict[str, Any]]) -> None:
    for a in attributes:
        slug = a["slug"]
        if a.get("is_primary_key") or a.get("is_unique"):
            idx = f"idx_{table_name}_{slug}"[:64]
            unique = "UNIQUE " if (a.get("is_primary_key") or a.get("is_unique")) else ""
            conn.execute(
                f"CREATE {unique}INDEX IF NOT EXISTS {_quote_ident(idx)} "
                f"ON {_quote_ident(table_name)} ({_quote_ident(slug)})"
            )


def drop_entity_table(conn, table_name: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {_quote_ident(table_name)}")
