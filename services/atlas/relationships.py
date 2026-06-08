"""Atlas typed relationships between entities."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world

REL_TYPES = frozenset({"one_to_one", "one_to_many", "many_to_many"})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _row_to_rel(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "from_entity_id": row["from_entity_id"],
        "to_entity_id": row["to_entity_id"],
        "rel_type": row["rel_type"],
        "from_field": row["from_field"],
        "to_field": row["to_field"],
        "label": row["label"] or "",
        "from_anchor": row["from_anchor"] or "right",
        "to_anchor": row["to_anchor"] or "left",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_relationships(owner: Optional[str], world_id: str) -> List[Dict[str, Any]]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute(
            "SELECT * FROM atlas_relationships ORDER BY created_at"
        ).fetchall()
        return [_row_to_rel(r) for r in rows]


def get_relationship(owner: Optional[str], world_id: str, rel_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT * FROM atlas_relationships WHERE id = ?", (rel_id,)
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Relationship not found: {rel_id}")
        return _row_to_rel(row)


def create_relationship(
    owner: Optional[str],
    world_id: str,
    from_entity_id: str,
    to_entity_id: str,
    rel_type: str,
    from_field: str,
    to_field: str,
    label: str = "",
    from_anchor: str = "right",
    to_anchor: str = "left",
) -> Dict[str, Any]:
    rel_type = (rel_type or "one_to_many").lower().replace("-", "_")
    if rel_type not in REL_TYPES:
        raise ValueError(f"rel_type must be one of: {', '.join(sorted(REL_TYPES))}")
    from_field = from_field or ""
    to_field = to_field or ""
    rel_id = str(uuid.uuid4())
    now = _utcnow_iso()
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        conn.execute(
            """INSERT INTO atlas_relationships
               (id, from_entity_id, to_entity_id, rel_type, from_field, to_field,
                label, from_anchor, to_anchor, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rel_id, from_entity_id, to_entity_id, rel_type,
                from_field, to_field, label, from_anchor, to_anchor, now, now,
            ),
        )
    return get_relationship(owner, world_id, rel_id)


def _entity_exists(conn, entity_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM atlas_entities WHERE id = ?", (entity_id,)
    ).fetchone()
    return row is not None


def update_relationship(
    owner: Optional[str],
    world_id: str,
    rel_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    now = _utcnow_iso()
    allowed = {
        "rel_type", "from_field", "to_field", "label",
        "from_anchor", "to_anchor",
        "from_entity_id", "to_entity_id",
    }
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_relationship(owner, world_id, rel_id)

    with open_world_db(world["db_path"]) as conn:
        current = conn.execute(
            "SELECT * FROM atlas_relationships WHERE id = ?", (rel_id,)
        ).fetchone()
        if not current:
            raise AtlasNotFoundError(f"Relationship not found: {rel_id}")

        new_from = kwargs.get("from_entity_id", current["from_entity_id"])
        new_to = kwargs.get("to_entity_id", current["to_entity_id"])
        if new_from == new_to:
            raise ValueError("from_entity_id and to_entity_id must differ")
        for eid in (new_from, new_to):
            if not _entity_exists(conn, eid):
                raise ValueError(f"Entity not found: {eid}")

        sets.append("updated_at = ?")
        vals.append(now)
        vals.append(rel_id)
        cur = conn.execute(
            f"UPDATE atlas_relationships SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Relationship not found: {rel_id}")
    return get_relationship(owner, world_id, rel_id)


def delete_relationship(owner: Optional[str], world_id: str, rel_id: str) -> bool:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        cur = conn.execute("DELETE FROM atlas_relationships WHERE id = ?", (rel_id,))
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Relationship not found: {rel_id}")
    return True
