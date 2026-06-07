"""Atlas entity (collection) operations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas.ddl import create_entity_table, drop_entity_table, table_name_for_entity
from services.atlas.fields import load_fields
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


def list_entities(owner: Optional[str], world_id: str) -> List[Dict[str, Any]]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        entities = conn.execute(
            "SELECT * FROM atlas_entities ORDER BY name"
        ).fetchall()
        return [
            _row_to_entity(e, load_fields(conn, e["id"]))
            for e in entities
        ]


def get_entity(owner: Optional[str], world_id: str, entity_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT * FROM atlas_entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Entity not found: {entity_id}")
        return _row_to_entity(row, load_fields(conn, entity_id))


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
        create_entity_table(conn, table_name)
        conn.execute(
            """INSERT INTO atlas_entities
               (id, name, description, table_name, row_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            (entity_id, name.strip() or "Untitled", description, table_name, now, now),
        )

    from services.atlas.worlds import refresh_world_stats
    refresh_world_stats(owner, world_id)
    return get_entity(owner, world_id, entity_id)


def delete_entity(owner: Optional[str], world_id: str, entity_id: str) -> bool:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        drop_entity_table(conn, entity["table_name"])
        conn.execute("DELETE FROM atlas_fields WHERE entity_id = ?", (entity_id,))
        conn.execute("DELETE FROM atlas_canvas_nodes WHERE entity_id = ?", (entity_id,))
        conn.execute(
            "DELETE FROM atlas_relationships WHERE from_entity_id = ? OR to_entity_id = ?",
            (entity_id, entity_id),
        )
        conn.execute("DELETE FROM atlas_entities WHERE id = ?", (entity_id,))
    from services.atlas.worlds import refresh_world_stats
    refresh_world_stats(owner, world_id)
    return True
