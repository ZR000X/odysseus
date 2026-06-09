"""Atlas collection keys — declared uniqueness (composite supported)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas.entities import get_entity
from services.atlas.fields import load_fields
from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world


class KeyInUseError(ValueError):
    """Raised when deleting a key referenced by relationships."""


INNATE_KEY_NAME = "_id"
INNATE_KEY_ID_PREFIX = "innate-id:"


def innate_key_id(source_id: str) -> str:
    return f"{INNATE_KEY_ID_PREFIX}{source_id}"


def is_innate_key_id(key_id: str) -> bool:
    return (key_id or "").startswith(INNATE_KEY_ID_PREFIX)


def innate_source_id_from_key_id(key_id: str) -> Optional[str]:
    if not is_innate_key_id(key_id):
        return None
    return key_id[len(INNATE_KEY_ID_PREFIX):] or None


def innate_key(source_id: str) -> Dict[str, Any]:
    """Virtual row-id key available on every collection and query."""
    return {
        "id": innate_key_id(source_id),
        "entity_id": source_id,
        "name": INNATE_KEY_NAME,
        "field_slugs": [INNATE_KEY_NAME],
        "innate": True,
        "created_at": None,
        "updated_at": None,
    }


def ensure_innate_key(conn, entity_id: str) -> str:
    """Persist the built-in _id key for a collection (idempotent)."""
    key_id = innate_key_id(entity_id)
    now = _utcnow_iso()
    conn.execute(
        """INSERT OR IGNORE INTO atlas_entity_keys
           (id, entity_id, name, field_slugs, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (key_id, entity_id, INNATE_KEY_NAME, json.dumps([INNATE_KEY_NAME]), now, now),
    )
    return key_id


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _row_to_key(row) -> Dict[str, Any]:
    slugs = json.loads(row["field_slugs"] or "[]")
    key = {
        "id": row["id"],
        "entity_id": row["entity_id"],
        "name": row["name"],
        "field_slugs": slugs,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if is_innate_key_id(row["id"]):
        key["innate"] = True
    return key


def _validate_field_slugs(conn, entity_id: str, field_slugs: List[str]) -> List[str]:
    if not field_slugs:
        raise ValueError("field_slugs must contain at least one field")
    known = {f["slug"] for f in load_fields(conn, entity_id)}
    known.add(INNATE_KEY_NAME)
    missing = [s for s in field_slugs if s not in known]
    if missing:
        raise ValueError(f"Unknown field slugs: {', '.join(missing)}")
    return list(field_slugs)


def list_keys(owner: Optional[str], world_id: str, entity_id: str) -> List[Dict[str, Any]]:
    get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        ensure_innate_key(conn, entity_id)
        rows = conn.execute(
            "SELECT * FROM atlas_entity_keys WHERE entity_id = ? ORDER BY name",
            (entity_id,),
        ).fetchall()
        return [_row_to_key(r) for r in rows]


def get_key(owner: Optional[str], world_id: str, entity_id: str, key_id: str) -> Dict[str, Any]:
    get_entity(owner, world_id, entity_id)
    if is_innate_key_id(key_id):
        if innate_source_id_from_key_id(key_id) != entity_id:
            raise AtlasNotFoundError(f"Key not found: {key_id}")
        return innate_key(entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT * FROM atlas_entity_keys WHERE id = ? AND entity_id = ?",
            (key_id, entity_id),
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Key not found: {key_id}")
        return _row_to_key(row)


def create_key(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    name: str,
    field_slugs: List[str],
) -> Dict[str, Any]:
    get_entity(owner, world_id, entity_id)
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    key_id = str(uuid.uuid4())
    now = _utcnow_iso()
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        _validate_field_slugs(conn, entity_id, field_slugs)
        conn.execute(
            """INSERT INTO atlas_entity_keys
               (id, entity_id, name, field_slugs, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key_id, entity_id, name, json.dumps(field_slugs), now, now),
        )
    return get_key(owner, world_id, entity_id, key_id)


def update_key(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    key_id: str,
    *,
    name: Optional[str] = None,
    field_slugs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if is_innate_key_id(key_id):
        raise ValueError("Innate keys cannot be modified")
    get_key(owner, world_id, entity_id, key_id)
    world = get_world(owner, world_id)
    updates = []
    params: List[Any] = []
    with open_world_db(world["db_path"]) as conn:
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("name cannot be empty")
            updates.append("name = ?")
            params.append(name)
        if field_slugs is not None:
            _validate_field_slugs(conn, entity_id, field_slugs)
            updates.append("field_slugs = ?")
            params.append(json.dumps(field_slugs))
        if not updates:
            return get_key(owner, world_id, entity_id, key_id)
        updates.append("updated_at = ?")
        params.append(_utcnow_iso())
        params.extend([key_id, entity_id])
        conn.execute(
            f"UPDATE atlas_entity_keys SET {', '.join(updates)} WHERE id = ? AND entity_id = ?",
            params,
        )
    return get_key(owner, world_id, entity_id, key_id)


def _key_relationship_refs(conn, key_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, from_entity_id, to_entity_id, label
           FROM atlas_relationships
           WHERE from_key_id = ? OR to_key_id = ?""",
        (key_id, key_id),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_key(owner: Optional[str], world_id: str, entity_id: str, key_id: str) -> bool:
    if is_innate_key_id(key_id):
        raise ValueError("Innate keys cannot be deleted")
    get_key(owner, world_id, entity_id, key_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        refs = _key_relationship_refs(conn, key_id)
        if refs:
            raise KeyInUseError(
                f"Key is referenced by {len(refs)} relationship(s)"
            )
        cur = conn.execute(
            "DELETE FROM atlas_entity_keys WHERE id = ? AND entity_id = ?",
            (key_id, entity_id),
        )
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Key not found: {key_id}")
    return True


def load_keys_for_entity(conn, entity_id: str) -> List[Dict[str, Any]]:
    ensure_innate_key(conn, entity_id)
    rows = conn.execute(
        "SELECT * FROM atlas_entity_keys WHERE entity_id = ? ORDER BY name",
        (entity_id,),
    ).fetchall()
    return [_row_to_key(r) for r in rows]


def get_key_by_id(conn, key_id: str) -> Optional[Dict[str, Any]]:
    source_id = innate_source_id_from_key_id(key_id)
    if source_id:
        ensure_innate_key(conn, source_id)
    row = conn.execute(
        "SELECT * FROM atlas_entity_keys WHERE id = ?", (key_id,)
    ).fetchone()
    return _row_to_key(row) if row else None
