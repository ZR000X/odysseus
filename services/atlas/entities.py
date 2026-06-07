"""Atlas entity schema operations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas.ddl import (
    add_column,
    create_entity_table,
    drop_entity_table,
    slugify,
    table_name_for_entity,
)
from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _row_to_attr(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "entity_id": row["entity_id"],
        "name": row["name"],
        "slug": row["slug"],
        "attr_type": row["attr_type"],
        "nullable": bool(row["nullable"]),
        "is_primary_key": bool(row["is_primary_key"]),
        "is_unique": bool(row["is_unique"]),
        "sort_order": row["sort_order"],
    }


def _row_to_entity(row, attributes: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "table_name": row["table_name"],
        "row_count": row["row_count"] or 0,
        "attributes": attributes,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _load_attributes(conn, entity_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM atlas_attributes WHERE entity_id = ? ORDER BY sort_order, name",
        (entity_id,),
    ).fetchall()
    return [_row_to_attr(r) for r in rows]


def list_entities(owner: Optional[str], world_id: str) -> List[Dict[str, Any]]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        entities = conn.execute(
            "SELECT * FROM atlas_entities ORDER BY name"
        ).fetchall()
        return [
            _row_to_entity(e, _load_attributes(conn, e["id"]))
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
        return _row_to_entity(row, _load_attributes(conn, entity_id))


def create_entity(
    owner: Optional[str],
    world_id: str,
    name: str,
    attributes: Optional[List[Dict[str, Any]]] = None,
    description: str = "",
) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    entity_id = str(uuid.uuid4())
    table_name = table_name_for_entity(entity_id)
    now = _utcnow_iso()
    attr_rows: List[Dict[str, Any]] = []
    attrs_in = attributes or []
    for i, a in enumerate(attrs_in):
        slug = slugify(a.get("name") or a.get("slug") or "")
        attr_rows.append({
            "id": str(uuid.uuid4()),
            "entity_id": entity_id,
            "name": (a.get("name") or slug).strip(),
            "slug": slug,
            "attr_type": (a.get("type") or a.get("attr_type") or "text").lower(),
            "nullable": not a.get("primary_key") and a.get("nullable", True),
            "is_primary_key": bool(a.get("primary_key") or a.get("is_primary_key")),
            "is_unique": bool(a.get("unique") or a.get("is_unique")),
            "sort_order": a.get("sort_order", i),
        })

    with open_world_db(world["db_path"]) as conn:
        create_entity_table(conn, table_name, attr_rows)
        conn.execute(
            """INSERT INTO atlas_entities
               (id, name, description, table_name, row_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            (entity_id, name.strip() or "Untitled", description, table_name, now, now),
        )
        for ar in attr_rows:
            conn.execute(
                """INSERT INTO atlas_attributes
                   (id, entity_id, name, slug, attr_type, nullable,
                    is_primary_key, is_unique, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ar["id"], entity_id, ar["name"], ar["slug"], ar["attr_type"],
                    1 if ar["nullable"] else 0,
                    1 if ar["is_primary_key"] else 0,
                    1 if ar["is_unique"] else 0,
                    ar["sort_order"], now, now,
                ),
            )

    from services.atlas.worlds import refresh_world_stats
    refresh_world_stats(owner, world_id)
    return get_entity(owner, world_id, entity_id)


def add_attribute(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    name: str,
    attr_type: str = "text",
    nullable: bool = True,
    is_primary_key: bool = False,
    is_unique: bool = False,
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    slug = slugify(name)
    attr_id = str(uuid.uuid4())
    now = _utcnow_iso()
    attr = {
        "slug": slug,
        "attr_type": attr_type.lower(),
        "nullable": nullable and not is_primary_key,
        "is_primary_key": is_primary_key,
        "is_unique": is_unique,
    }
    with open_world_db(world["db_path"]) as conn:
        add_column(conn, entity["table_name"], attr)
        conn.execute(
            """INSERT INTO atlas_attributes
               (id, entity_id, name, slug, attr_type, nullable,
                is_primary_key, is_unique, sort_order, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attr_id, entity_id, name.strip(), slug, attr_type.lower(),
                1 if attr["nullable"] else 0,
                1 if is_primary_key else 0,
                1 if is_unique else 0,
                len(entity["attributes"]), now, now,
            ),
        )
    return get_entity(owner, world_id, entity_id)


def delete_entity(owner: Optional[str], world_id: str, entity_id: str) -> bool:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        drop_entity_table(conn, entity["table_name"])
        conn.execute("DELETE FROM atlas_entities WHERE id = ?", (entity_id,))
    from services.atlas.worlds import refresh_world_stats
    refresh_world_stats(owner, world_id)
    return True
