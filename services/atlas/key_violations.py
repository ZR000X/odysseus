"""Detect documents that violate declared key uniqueness."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.atlas.documents import row_to_document
from services.atlas.entities import get_entity
from services.atlas.fields import _sample_key_map
from services.atlas.keys import INNATE_KEY_NAME, get_key
from services.atlas.world_db import open_world_db
from services.atlas.worlds import get_world


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _json_path_for_key(key: str) -> str:
    """SQLite JSON path for an arbitrary document key."""
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return '$."' + escaped + '"'


def load_slug_to_key(conn, table_name: str) -> Dict[str, str]:
    """Map field slug -> original document key from first sample row."""
    row = conn.execute(
        f"SELECT _atlas_row_id, _atlas_created_at, _atlas_updated_at, data "
        f"FROM {_quote_ident(table_name)} ORDER BY _atlas_row_id LIMIT 1"
    ).fetchone()
    sample = row_to_document(dict(row)) if row else None
    return _sample_key_map(sample)


def _json_path(slug: str, slug_to_key: Dict[str, str]) -> str:
    return _json_path_for_key(slug_to_key.get(slug, slug))


def _tuple_expr(slugs: List[str], slug_to_key: Dict[str, str]) -> str:
    """Concatenate key column values; NULL components exclude row from grouping."""
    parts = []
    for slug in slugs:
        path = _json_path(slug, slug_to_key)
        parts.append(
            f"COALESCE(CAST(json_extract(data, '{path}') AS TEXT), '')"
        )
    if len(parts) == 1:
        return parts[0]
    sep = " || char(0) || "
    return f"({sep.join(parts)})"


def _violation_where_sql(
    slugs: List[str], slug_to_key: Dict[str, str]
) -> Tuple[str, List[Any]]:
    """SQL fragment: rows that participate in a duplicate key group."""
    tuple_expr = _tuple_expr(slugs, slug_to_key)
    null_checks = " AND ".join(
        f"json_extract(data, '{_json_path(s, slug_to_key)}') IS NOT NULL" for s in slugs
    )
    dup_sub = f"""
        SELECT {tuple_expr} AS k
        FROM {{table}}
        WHERE {null_checks}
        GROUP BY k
        HAVING COUNT(*) > 1
    """
    where = f"""
        ({null_checks})
        AND {tuple_expr} IN (
            SELECT k FROM ({dup_sub}) AS dup_groups
        )
    """
    return where, []


def compile_key_violation_filter(
    table: str,
    field_slugs: List[str],
    *,
    slug_to_key: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[Any]]:
    if field_slugs == [INNATE_KEY_NAME]:
        return " WHERE 1=0", []
    slug_to_key = slug_to_key or {}
    where_tpl, params = _violation_where_sql(field_slugs, slug_to_key)
    where = where_tpl.replace("{table}", _quote_ident(table))
    return f" WHERE {where}", params


def count_key_violations(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    key_id: str,
) -> int:
    entity = get_entity(owner, world_id, entity_id)
    key = get_key(owner, world_id, entity_id, key_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        slug_to_key = load_slug_to_key(conn, entity["table_name"])
        where_sql, params = compile_key_violation_filter(
            entity["table_name"], key["field_slugs"], slug_to_key=slug_to_key
        )
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {_quote_ident(entity['table_name'])}{where_sql}",
            params,
        ).fetchone()
        return int(row["n"] or 0)


def find_key_violations(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    key_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    key = get_key(owner, world_id, entity_id, key_id)
    world = get_world(owner, world_id)
    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))
    with open_world_db(world["db_path"]) as conn:
        slug_to_key = load_slug_to_key(conn, entity["table_name"])
        where_sql, params = compile_key_violation_filter(
            entity["table_name"], key["field_slugs"], slug_to_key=slug_to_key
        )
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM {_quote_ident(entity['table_name'])}{where_sql}",
            params,
        ).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT _atlas_row_id, _atlas_created_at, _atlas_updated_at, data
                FROM {_quote_ident(entity['table_name'])}{where_sql}
                ORDER BY _atlas_row_id
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
        docs = [row_to_document(dict(r)) for r in rows]
        return {
            "documents": docs,
            "count": int(total),
            "key_id": key_id,
            "key_name": key["name"],
        }
