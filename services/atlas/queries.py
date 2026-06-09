"""Atlas SQL queries — virtual collections."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas import sql_engine
from services.atlas.keys import innate_key
from services.atlas.names import assert_unique_atlas_name, find_dependent_query_ids
from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _row_to_query(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "sql_text": row["sql_text"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _save_deps(conn, query_id: str, deps: List[Dict[str, str]]) -> None:
    conn.execute("DELETE FROM atlas_query_deps WHERE query_id = ?", (query_id,))
    now = _utcnow_iso()
    for d in deps:
        conn.execute(
            """INSERT INTO atlas_query_deps (id, query_id, source_type, source_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), query_id, d["source_type"], d["source_id"], now),
        )


def _propagate_source_rename(
    conn,
    owner: Optional[str],
    world_id: str,
    source_id: str,
    source_type: str,
    old_name: str,
    new_name: str,
) -> None:
    if old_name == new_name:
        return
    now = _utcnow_iso()
    for dep_id in find_dependent_query_ids(conn, source_id, source_type):
        row = conn.execute(
            "SELECT sql_text FROM atlas_queries WHERE id = ?", (dep_id,),
        ).fetchone()
        if not row:
            continue
        new_sql = sql_engine.rewrite_source_references(
            row["sql_text"], old_name, new_name,
        )
        validation = sql_engine.validate_sql(
            owner, world_id, new_sql, self_query_id=dep_id,
        )
        if not validation.get("valid"):
            raise ValueError(
                f"Renaming would break dependent query: {validation.get('error')}"
            )
        conn.execute(
            "UPDATE atlas_queries SET sql_text = ?, updated_at = ? WHERE id = ?",
            (new_sql, now, dep_id),
        )
        _save_deps(conn, dep_id, validation["dependencies"])


def _load_deps(conn, query_id: str) -> List[Dict[str, str]]:
    rows = conn.execute(
        "SELECT source_type, source_id FROM atlas_query_deps WHERE query_id = ?",
        (query_id,),
    ).fetchall()
    return [{"source_type": r["source_type"], "source_id": r["source_id"]} for r in rows]


def list_queries(owner: Optional[str], world_id: str) -> List[Dict[str, Any]]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute("SELECT * FROM atlas_queries ORDER BY name").fetchall()
        result = []
        for r in rows:
            q = _row_to_query(r)
            q["dependencies"] = _load_deps(conn, r["id"])
            result.append(q)
        return result


def get_query(owner: Optional[str], world_id: str, query_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT * FROM atlas_queries WHERE id = ?", (query_id,)
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Query not found: {query_id}")
        q = _row_to_query(row)
        q["dependencies"] = _load_deps(conn, query_id)
        return q


def create_query(
    owner: Optional[str],
    world_id: str,
    name: str,
    sql_text: str,
    description: str = "",
) -> Dict[str, Any]:
    sql_text = (sql_text or "").strip()
    if not sql_text:
        raise ValueError("sql_text is required")
    validation = sql_engine.validate_sql(owner, world_id, sql_text)
    if not validation.get("valid"):
        raise ValueError(validation.get("error") or "Invalid SQL")
    query_id = str(uuid.uuid4())
    now = _utcnow_iso()
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        name = assert_unique_atlas_name(conn, name or "Untitled Query")
        conn.execute(
            """INSERT INTO atlas_queries (id, name, description, sql_text, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (query_id, name, description, sql_text, now, now),
        )
        _save_deps(conn, query_id, validation["dependencies"])
    return get_query(owner, world_id, query_id)


def update_query(
    owner: Optional[str],
    world_id: str,
    query_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    sql_text: Optional[str] = None,
) -> Dict[str, Any]:
    existing = get_query(owner, world_id, query_id)
    world = get_world(owner, world_id)
    updates = []
    params: List[Any] = []
    deps = None
    new_name: Optional[str] = None
    old_name = existing["name"]
    if name is not None:
        new_name = (name or "").strip() or "Untitled Query"
        updates.append("name = ?")
        params.append(new_name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if sql_text is not None:
        sql_text = sql_text.strip()
        if not sql_text:
            raise ValueError("sql_text cannot be empty")
        validation = sql_engine.validate_sql(
            owner, world_id, sql_text, self_query_id=query_id,
        )
        if not validation.get("valid"):
            raise ValueError(validation.get("error") or "Invalid SQL")
        deps = validation["dependencies"]
        updates.append("sql_text = ?")
        params.append(sql_text)
    if not updates:
        return existing
    updates.append("updated_at = ?")
    params.append(_utcnow_iso())
    params.append(query_id)
    with open_world_db(world["db_path"]) as conn:
        if new_name is not None:
            assert_unique_atlas_name(conn, new_name, exclude_query_id=query_id)
        conn.execute(
            f"UPDATE atlas_queries SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        if deps is not None:
            _save_deps(conn, query_id, deps)
        rename_pair = (
            (old_name, new_name)
            if new_name is not None and new_name != old_name
            else None
        )
        conn.commit()
    if rename_pair:
        old, new = rename_pair
        with open_world_db(world["db_path"]) as conn:
            _propagate_source_rename(
                conn, owner, world_id, query_id, "query", old, new,
            )
    return get_query(owner, world_id, query_id)


def delete_query(owner: Optional[str], world_id: str, query_id: str) -> bool:
    get_query(owner, world_id, query_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        conn.execute("DELETE FROM atlas_canvas_query_nodes WHERE query_id = ?", (query_id,))
        cur = conn.execute("DELETE FROM atlas_queries WHERE id = ?", (query_id,))
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Query not found: {query_id}")
    return True


def execute_query(
    owner: Optional[str],
    world_id: str,
    query_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    q = get_query(owner, world_id, query_id)
    return sql_engine.execute_sql(
        owner, world_id, q["sql_text"],
        limit=limit, offset=offset, self_query_id=query_id,
    )


def get_query_schema(owner: Optional[str], world_id: str, query_id: str) -> Dict[str, Any]:
    q = get_query(owner, world_id, query_id)
    try:
        result = sql_engine.execute_sql(
            owner, world_id, q["sql_text"],
            limit=0, offset=0, self_query_id=query_id, columns_only=True,
        )
        fields = [
            {"slug": c["name"], "inferred_type": c.get("type", "text"), "sample_key": c["name"]}
            for c in result.get("columns", [])
        ]
        count_result = sql_engine.execute_sql(
            owner, world_id, q["sql_text"],
            limit=1, offset=0, self_query_id=query_id,
        )
        sample = count_result["documents"][0] if count_result["documents"] else None
        total = count_result.get("total", 0)
    except Exception:
        fields = []
        sample = None
        total = 0
    return {
        "entity_id": query_id,
        "entity_name": q["name"],
        "query_id": query_id,
        "query_name": q["name"],
        "kind": "query",
        "document_count": total,
        "fields": fields,
        "keys": [innate_key(query_id)],
        "sample_document": sample,
        "sql_text": q["sql_text"],
        "dependencies": q.get("dependencies", []),
    }


def validate_sql_text(
    owner: Optional[str],
    world_id: str,
    sql_text: str,
    *,
    query_id: Optional[str] = None,
    preview_limit: int = 25,
) -> Dict[str, Any]:
    validation = sql_engine.validate_sql(
        owner, world_id, sql_text, self_query_id=query_id,
    )
    if not validation.get("valid"):
        return validation
    try:
        preview = sql_engine.execute_sql(
            owner, world_id, sql_text,
            limit=preview_limit, offset=0, self_query_id=query_id,
        )
    except ValueError as e:
        validation["valid"] = False
        validation["error"] = str(e)
        validation.pop("preview", None)
        return validation
    validation["preview"] = preview
    return validation
