"""Atlas entity (collection) operations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas.ddl import create_entity_table, drop_entity_table, table_name_for_entity
from services.atlas.fields import load_fields
from services.atlas.names import assert_unique_atlas_name
from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _row_to_entity(row, fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "table_name": row["table_name"],
        "row_count": row["row_count"] or 0,
        "fields": fields,
        "attributes": fields,  # legacy alias
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def entity_summary(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": entity["id"],
        "name": entity["name"],
        "description": entity.get("description") or "",
        "row_count": entity.get("row_count") or 0,
    }


def list_entities(
    owner: Optional[str],
    world_id: str,
    *,
    include_fields: bool = False,
) -> List[Dict[str, Any]]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        entities = conn.execute(
            "SELECT * FROM atlas_entities ORDER BY name"
        ).fetchall()
        result = []
        for e in entities:
            fields = load_fields(conn, e["id"]) if include_fields else []
            result.append(_row_to_entity(e, fields))
        return result


def get_entity(owner: Optional[str], world_id: str, entity_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT * FROM atlas_entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Entity not found: {entity_id}")
        return _row_to_entity(row, load_fields(conn, entity_id))


def get_entity_table(owner: Optional[str], world_id: str, entity_id: str) -> Dict[str, Any]:
    """Lightweight entity lookup for bulk import (no field registry load)."""
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT id, name, table_name, row_count FROM atlas_entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Entity not found: {entity_id}")
        return {
            "id": row["id"],
            "name": row["name"],
            "table_name": row["table_name"],
            "row_count": row["row_count"] or 0,
            "db_path": world["db_path"],
        }


def create_entity(
    owner: Optional[str],
    world_id: str,
    name: str,
    attributes: Optional[List[Dict[str, Any]]] = None,
    description: str = "",
) -> Dict[str, Any]:
    del attributes  # schemaless — attributes ignored
    world = get_world(owner, world_id)
    entity_id = str(uuid.uuid4())
    table_name = table_name_for_entity(entity_id)
    now = _utcnow_iso()

    with open_world_db(world["db_path"]) as conn:
        display_name = assert_unique_atlas_name(conn, name or "Untitled")
        create_entity_table(conn, table_name)
        conn.execute(
            """INSERT INTO atlas_entities
               (id, name, description, table_name, row_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            (entity_id, display_name, description, table_name, now, now),
        )
        from services.atlas.keys import ensure_innate_key
        ensure_innate_key(conn, entity_id)

    from services.atlas.worlds import refresh_world_stats
    refresh_world_stats(owner, world_id)
    return get_entity(owner, world_id, entity_id)


def update_entity(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    existing = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    updates = []
    params: List[Any] = []
    new_name: Optional[str] = None
    old_name = existing["name"]
    if name is not None:
        new_name = (name or "").strip() or "Untitled"
        updates.append("name = ?")
        params.append(new_name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if not updates:
        return existing
    updates.append("updated_at = ?")
    params.append(_utcnow_iso())
    params.append(entity_id)
    with open_world_db(world["db_path"]) as conn:
        if new_name is not None:
            assert_unique_atlas_name(conn, new_name, exclude_entity_id=entity_id)
        conn.execute(
            f"UPDATE atlas_entities SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        rename_pair = (
            (old_name, new_name)
            if new_name is not None and new_name != old_name
            else None
        )
        conn.commit()
    if rename_pair:
        from services.atlas.queries import _propagate_source_rename
        old, new = rename_pair
        with open_world_db(world["db_path"]) as conn:
            _propagate_source_rename(
                conn, owner, world_id, entity_id, "entity", old, new,
            )
    from services.atlas.worlds import refresh_world_stats
    refresh_world_stats(owner, world_id)
    return get_entity(owner, world_id, entity_id)


def resolve_entity(
    owner: Optional[str],
    world_id: str,
    *,
    entity_id: Optional[str] = None,
    entity_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve by full UUID, UUID prefix, or case-insensitive exact name."""
    eid = (entity_id or "").strip() or None
    ename = (entity_name or "").strip() or None

    if eid:
        entities = list_entities(owner, world_id)
        for e in entities:
            if e["id"] == eid:
                return e
        matches = [e for e in entities if e["id"].startswith(eid)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(f'{e["name"]} ({e["id"][:8]})' for e in matches[:5])
            raise AtlasNotFoundError(
                f'Ambiguous entity_id prefix "{eid}": {names}. Use full UUID or entity name.'
            )
        if not ename:
            for e in entities:
                if e["name"].lower() == eid.lower():
                    return e
        raise AtlasNotFoundError(
            f'Entity not found: "{eid}". Try find_entity or list_entities.'
        )

    if ename:
        entities = list_entities(owner, world_id)
        for e in entities:
            if e["name"].lower() == ename.lower():
                return e
        suggestions = find_entities(owner, world_id, ename, limit=3)
        msg = f'Entity not found: "{ename}". Try find_entity or list_entities.'
        if suggestions:
            hints = ", ".join(f'"{s["name"]}" (entity_id: {s["id"][:8]})' for s in suggestions)
            msg += f" Did you mean: {hints}?"
        raise AtlasNotFoundError(msg)

    raise AtlasNotFoundError("entity_id or entity_name required")


def find_entities(
    owner: Optional[str],
    world_id: str,
    query: str,
    *,
    limit: int = 20,
    include_fields: bool = False,
) -> List[Dict[str, Any]]:
    """Case-insensitive substring match on entity name; exact matches ranked first."""
    q = (query or "").strip().lower()
    if not q:
        return []
    entities = list_entities(owner, world_id, include_fields=include_fields)
    exact = [e for e in entities if e["name"].lower() == q]
    partial = [e for e in entities if q in e["name"].lower() and e not in exact]
    ranked = exact + partial
    return ranked[: max(1, min(int(limit or 20), 50))]


def delete_entity(owner: Optional[str], world_id: str, entity_id: str) -> bool:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        drop_entity_table(conn, entity["table_name"])
        conn.execute("DELETE FROM atlas_fields WHERE entity_id = ?", (entity_id,))
        conn.execute("DELETE FROM atlas_entity_keys WHERE entity_id = ?", (entity_id,))
        conn.execute("DELETE FROM atlas_canvas_nodes WHERE entity_id = ?", (entity_id,))
        conn.execute(
            "DELETE FROM atlas_relationships WHERE from_entity_id = ? OR to_entity_id = ?",
            (entity_id, entity_id),
        )
        conn.execute("DELETE FROM atlas_entities WHERE id = ?", (entity_id,))
    from services.atlas.worlds import refresh_world_stats
    refresh_world_stats(owner, world_id)
    return True
