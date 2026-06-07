"""Atlas entity row CRUD."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.atlas.entities import get_entity
from services.atlas.worlds import AtlasNotFoundError, get_world, refresh_world_stats
from services.atlas.world_db import open_world_db


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _coerce_value(attr_type: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    t = (attr_type or "text").lower()
    if t == "integer":
        return int(value)
    if t == "real":
        return float(value)
    if t == "boolean":
        if isinstance(value, bool):
            return 1 if value else 0
        s = str(value).lower()
        return 1 if s in ("1", "true", "yes", "on") else 0
    return str(value)


def _entity_row_to_dict(row, attributes: List[Dict[str, Any]]) -> Dict[str, Any]:
    d = {"_atlas_row_id": row["_atlas_row_id"]}
    for a in attributes:
        d[a["slug"]] = row[a["slug"]]
    return d


def list_rows(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    limit: int = 20,
    offset: int = 0,
    filter_col: Optional[str] = None,
    filter_val: Optional[str] = None,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    slugs = [a["slug"] for a in entity["attributes"]]
    cols = ["_atlas_row_id"] + slugs
    col_list = ", ".join(_quote_ident(c) for c in cols)
    where = ""
    params: List[Any] = []
    if filter_col and filter_val is not None:
        if filter_col not in slugs and filter_col != "_atlas_row_id":
            raise ValueError(f"Unknown filter column: {filter_col}")
        where = f" WHERE {_quote_ident(filter_col)} = ?"
        params.append(filter_val)
    sql = f"SELECT {col_list} FROM {_quote_ident(table)}{where} ORDER BY _atlas_row_id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM {_quote_ident(table)}{where}",
            params[:-2] if where else [],
        ).fetchone()[0]
    return {
        "rows": [_entity_row_to_dict(dict(r), entity["attributes"]) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def count_rows(owner: Optional[str], world_id: str, entity_id: str) -> int:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM {_quote_ident(entity['table_name'])}"
        ).fetchone()[0]


def add_row(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    row: Dict[str, Any],
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    attrs = entity["attributes"]
    cols = []
    vals = []
    for a in attrs:
        if a["slug"] in row:
            cols.append(_quote_ident(a["slug"]))
            vals.append(_coerce_value(a["attr_type"], row[a["slug"]]))
    if not cols:
        raise ValueError("No valid columns in row data")
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    with open_world_db(world["db_path"]) as conn:
        cur = conn.execute(
            f"INSERT INTO {_quote_ident(table)} ({col_names}) VALUES ({placeholders})",
            vals,
        )
        row_id = cur.lastrowid
        conn.execute(
            "UPDATE atlas_entities SET row_count = row_count + 1, updated_at = datetime('now') WHERE id = ?",
            (entity_id,),
        )
    refresh_world_stats(owner, world_id)
    result = list_rows(owner, world_id, entity_id, limit=1, offset=0)
    for r in result["rows"]:
        if r["_atlas_row_id"] == row_id:
            return {"row_id": row_id, "row": r}
    return {"row_id": row_id, "row": {"_atlas_row_id": row_id}}


def update_row(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    row_id: int,
    row: Dict[str, Any],
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    sets = []
    vals = []
    for a in entity["attributes"]:
        if a["slug"] in row:
            sets.append(f"{_quote_ident(a['slug'])} = ?")
            vals.append(_coerce_value(a["attr_type"], row[a["slug"]]))
    if not sets:
        raise ValueError("No valid columns to update")
    sets.append("_atlas_updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    vals.extend([row_id])
    with open_world_db(world["db_path"]) as conn:
        cur = conn.execute(
            f"UPDATE {_quote_ident(table)} SET {', '.join(sets)} WHERE _atlas_row_id = ?",
            vals,
        )
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Row not found: {row_id}")
        updated = conn.execute(
            f"SELECT * FROM {_quote_ident(table)} WHERE _atlas_row_id = ?",
            (row_id,),
        ).fetchone()
    if updated:
        return {"row_id": row_id, "row": _entity_row_to_dict(dict(updated), entity["attributes"])}
    return {"row_id": row_id}


def delete_row(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    row_id: int,
) -> bool:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    with open_world_db(world["db_path"]) as conn:
        cur = conn.execute(
            f"DELETE FROM {_quote_ident(table)} WHERE _atlas_row_id = ?",
            (row_id,),
        )
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Row not found: {row_id}")
        conn.execute(
            "UPDATE atlas_entities SET row_count = MAX(0, row_count - 1), updated_at = datetime('now') WHERE id = ?",
            (entity_id,),
        )
    refresh_world_stats(owner, world_id)
    return True
