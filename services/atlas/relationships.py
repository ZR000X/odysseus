"""Atlas typed relationships between entities."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.atlas.keys import get_key_by_id
from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world

CARDINALITIES = frozenset({"one", "many", "one_or_zero"})
LEGACY_REL_TYPES = frozenset({"one_to_one", "one_to_many", "many_to_one", "many_to_many"})
REL_TYPES = LEGACY_REL_TYPES  # backward-compat alias

_LEGACY_REL_TO_CARDINALITIES: Dict[str, Tuple[str, str]] = {
    "one_to_one": ("one", "one"),
    "one_to_many": ("one", "many"),
    "many_to_one": ("many", "one"),
    "many_to_many": ("many", "many"),
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _normalize_cardinality(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    c = str(val).lower().replace("-", "_")
    return c if c in CARDINALITIES else None


def parse_cardinalities(rel_type: str) -> Tuple[str, str]:
    t = (rel_type or "one_to_many").lower().replace("-", "_")
    if t in _LEGACY_REL_TO_CARDINALITIES:
        return _LEGACY_REL_TO_CARDINALITIES[t]
    if "_to_" in t:
        from_part, to_part = t.split("_to_", 1)
        from_c = _normalize_cardinality(from_part)
        to_c = _normalize_cardinality(to_part)
        if from_c and to_c:
            return from_c, to_c
    return "one", "many"


def compose_rel_type(from_c: str, to_c: str) -> str:
    from_n = _normalize_cardinality(from_c)
    to_n = _normalize_cardinality(to_c)
    if not from_n or not to_n:
        raise ValueError(
            f"cardinality must be one of: {', '.join(sorted(CARDINALITIES))}"
        )
    return f"{from_n}_to_{to_n}"


def normalize_rel_type(
    rel_type: Optional[str] = None,
    from_cardinality: Optional[str] = None,
    to_cardinality: Optional[str] = None,
) -> str:
    if from_cardinality is not None and to_cardinality is not None:
        return compose_rel_type(from_cardinality, to_cardinality)
    t = (rel_type or "one_to_many").lower().replace("-", "_")
    if t in LEGACY_REL_TYPES:
        return t
    if "_to_" in t:
        from_part, to_part = t.split("_to_", 1)
        from_c = _normalize_cardinality(from_part)
        to_c = _normalize_cardinality(to_part)
        if from_c and to_c:
            return f"{from_c}_to_{to_c}"
    raise ValueError(
        f"rel_type must be a legacy type ({', '.join(sorted(LEGACY_REL_TYPES))}) "
        f"or a composite of cardinalities ({', '.join(sorted(CARDINALITIES))})"
    )


def _slugs_display(slugs: List[str]) -> str:
    return " + ".join(slugs) if slugs else ""


def _enrich_key(conn, key_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not key_id:
        return None
    key = get_key_by_id(conn, key_id)
    if not key:
        return None
    return {
        "id": key["id"],
        "name": key["name"],
        "field_slugs": key["field_slugs"],
        "display": _slugs_display(key["field_slugs"]),
    }


def _row_to_rel(row, conn=None) -> Dict[str, Any]:
    from_c, to_c = parse_cardinalities(row["rel_type"])
    from_key_id = row["from_key_id"] if "from_key_id" in row.keys() else None
    to_key_id = row["to_key_id"] if "to_key_id" in row.keys() else None
    from_key = _enrich_key(conn, from_key_id) if conn else None
    to_key = _enrich_key(conn, to_key_id) if conn else None
    return {
        "id": row["id"],
        "from_entity_id": row["from_entity_id"],
        "to_entity_id": row["to_entity_id"],
        "rel_type": row["rel_type"],
        "from_cardinality": from_c,
        "to_cardinality": to_c,
        "from_field": row["from_field"],
        "to_field": row["to_field"],
        "from_key_id": from_key_id,
        "to_key_id": to_key_id,
        "from_key": from_key,
        "to_key": to_key,
        "label": row["label"] or "",
        "from_anchor": row["from_anchor"] or "right",
        "to_anchor": row["to_anchor"] or "left",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_keys(
    conn,
    from_entity_id: str,
    to_entity_id: str,
    from_key_id: str,
    to_key_id: str,
) -> Tuple[str, str]:
    from_key = get_key_by_id(conn, from_key_id)
    to_key = get_key_by_id(conn, to_key_id)
    if not from_key:
        raise ValueError(f"from_key_id not found: {from_key_id}")
    if not to_key:
        raise ValueError(f"to_key_id not found: {to_key_id}")
    if from_key["entity_id"] != from_entity_id:
        raise ValueError("from_key_id does not belong to from_entity")
    if to_key["entity_id"] != to_entity_id:
        raise ValueError("to_key_id does not belong to to_entity")
    if len(from_key["field_slugs"]) != len(to_key["field_slugs"]):
        raise ValueError(
            "Composite keys must have the same number of columns on both sides"
        )
    return _slugs_display(from_key["field_slugs"]), _slugs_display(to_key["field_slugs"])


def list_relationships(owner: Optional[str], world_id: str) -> List[Dict[str, Any]]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute(
            "SELECT * FROM atlas_relationships ORDER BY created_at"
        ).fetchall()
        return [_row_to_rel(r, conn) for r in rows]


def get_relationship(owner: Optional[str], world_id: str, rel_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT * FROM atlas_relationships WHERE id = ?", (rel_id,)
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Relationship not found: {rel_id}")
        return _row_to_rel(row, conn)


def create_relationship(
    owner: Optional[str],
    world_id: str,
    from_entity_id: str,
    to_entity_id: str,
    rel_type: str,
    from_field: str = "",
    to_field: str = "",
    label: str = "",
    from_anchor: str = "right",
    to_anchor: str = "left",
    from_cardinality: Optional[str] = None,
    to_cardinality: Optional[str] = None,
    from_key_id: Optional[str] = None,
    to_key_id: Optional[str] = None,
) -> Dict[str, Any]:
    rel_type = normalize_rel_type(rel_type, from_cardinality, to_cardinality)
    rel_id = str(uuid.uuid4())
    now = _utcnow_iso()
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        if from_key_id and to_key_id:
            from_field, to_field = _validate_keys(
                conn, from_entity_id, to_entity_id, from_key_id, to_key_id,
            )
        else:
            from_field = from_field or ""
            to_field = to_field or ""
        conn.execute(
            """INSERT INTO atlas_relationships
               (id, from_entity_id, to_entity_id, rel_type, from_field, to_field,
                from_key_id, to_key_id, label, from_anchor, to_anchor,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rel_id, from_entity_id, to_entity_id, rel_type,
                from_field, to_field, from_key_id, to_key_id,
                label, from_anchor, to_anchor, now, now,
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
        "from_cardinality", "to_cardinality",
        "from_key_id", "to_key_id",
    }
    sets = []
    vals = []

    from_c = kwargs.get("from_cardinality")
    to_c = kwargs.get("to_cardinality")
    rel_type_kw = None
    if from_c is not None or to_c is not None:
        if from_c is None or to_c is None:
            raise ValueError("from_cardinality and to_cardinality must both be provided")
        rel_type_kw = normalize_rel_type(from_cardinality=from_c, to_cardinality=to_c)
    elif kwargs.get("rel_type") is not None:
        rel_type_kw = normalize_rel_type(rel_type=kwargs["rel_type"])

    for k, v in kwargs.items():
        if k in ("from_cardinality", "to_cardinality", "rel_type"):
            continue
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            vals.append(v)

    if rel_type_kw is not None:
        sets.append("rel_type = ?")
        vals.append(rel_type_kw)

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

        from_key_id = kwargs.get("from_key_id", current["from_key_id"] if "from_key_id" in current.keys() else None)
        to_key_id = kwargs.get("to_key_id", current["to_key_id"] if "to_key_id" in current.keys() else None)
        if from_key_id and to_key_id:
            from_field, to_field = _validate_keys(conn, new_from, new_to, from_key_id, to_key_id)
            if "from_field" not in kwargs:
                sets.append("from_field = ?")
                vals.append(from_field)
            if "to_field" not in kwargs:
                sets.append("to_field = ?")
                vals.append(to_field)

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
