"""Inferred field registry for Atlas entities."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas.ddl import slugify, validate_slug


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def infer_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "real"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "text"


def _merge_type(existing: str, new: str) -> str:
    if existing == new:
        return existing
    if existing in ("null", ""):
        return new
    if new == "null":
        return existing
    return "mixed"


def infer_fields_from_documents(
    conn,
    entity_id: str,
    documents: List[Dict[str, Any]],
) -> None:
    """Update atlas_fields registry from many documents in one pass."""
    if not documents:
        return
    now = _utcnow_iso()
    existing_rows = conn.execute(
        "SELECT * FROM atlas_fields WHERE entity_id = ?",
        (entity_id,),
    ).fetchall()
    registry: Dict[str, Dict[str, Any]] = {}
    for row in existing_rows:
        registry[row["slug"]] = {
            "id": row["id"],
            "inferred_type": row["inferred_type"],
            "occurrence_count": row["occurrence_count"] or 0,
            "nullable_ratio": row["nullable_ratio"] if row["nullable_ratio"] is not None else 1.0,
            "is_new": False,
        }

    pending: Dict[str, Dict[str, Any]] = {}
    for document in documents:
        for key, value in document.items():
            if key.startswith("_"):
                continue
            try:
                slug = slugify(key)
                validate_slug(slug)
            except ValueError:
                continue
            itype = infer_type(value)
            if slug not in pending:
                if slug in registry:
                    entry = registry[slug]
                    pending[slug] = {
                        "id": entry["id"],
                        "inferred_type": entry["inferred_type"],
                        "occurrence_count": entry["occurrence_count"],
                        "null_count": entry["nullable_ratio"] * entry["occurrence_count"],
                        "is_new": False,
                    }
                else:
                    pending[slug] = {
                        "id": str(uuid.uuid4()),
                        "inferred_type": itype,
                        "occurrence_count": 0,
                        "null_count": 0.0,
                        "is_new": True,
                    }
            entry = pending[slug]
            entry["inferred_type"] = _merge_type(entry["inferred_type"], itype)
            entry["occurrence_count"] += 1
            if value is None:
                entry["null_count"] += 1.0

    for slug, entry in pending.items():
        occ = entry["occurrence_count"]
        null_ratio = entry["null_count"] / occ if occ else 1.0
        if entry["is_new"]:
            conn.execute(
                """INSERT INTO atlas_fields
                   (id, entity_id, slug, inferred_type, occurrence_count,
                    nullable_ratio, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry["id"], entity_id, slug, entry["inferred_type"],
                    occ, null_ratio, now, now,
                ),
            )
        else:
            conn.execute(
                """UPDATE atlas_fields SET inferred_type = ?, occurrence_count = ?,
                   nullable_ratio = ?, updated_at = ? WHERE id = ?""",
                (entry["inferred_type"], occ, null_ratio, now, entry["id"]),
            )


def infer_fields_from_document(conn, entity_id: str, document: Dict[str, Any]) -> None:
    """Update atlas_fields registry from a document's keys."""
    infer_fields_from_documents(conn, entity_id, [document])


def _sample_key_map(sample: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Map slug -> original document key from a sample document."""
    if not sample:
        return {}
    out: Dict[str, str] = {}
    for key in sample:
        if key.startswith("_") and key != "_id":
            continue
        try:
            slug = slugify(key)
            validate_slug(slug)
        except ValueError:
            continue
        if slug not in out:
            out[slug] = key
    return out


def load_fields(
    conn,
    entity_id: str,
    *,
    include_stats: bool = True,
    include_sparse: bool = True,
    sample_key_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM atlas_fields WHERE entity_id = ? ORDER BY slug",
        (entity_id,),
    ).fetchall()
    fields = []
    for r in rows:
        occ = r["occurrence_count"] or 0
        raw_null = r["nullable_ratio"]
        null_ratio = round(1.0 if raw_null is None else raw_null, 3)
        if not include_sparse and null_ratio > 0.9 and occ <= 1:
            continue
        item: Dict[str, Any] = {
            "slug": r["slug"],
            "inferred_type": r["inferred_type"],
        }
        if sample_key_map and r["slug"] in sample_key_map:
            item["sample_key"] = sample_key_map[r["slug"]]
        elif sample_key_map is not None:
            item["sample_key"] = r["slug"]
        if include_stats:
            item["occurrence_count"] = occ
            item["nullable_ratio"] = null_ratio
        fields.append(item)
    return fields


def get_schema(
    conn,
    entity_id: str,
    entity_name: str,
    table_name: str,
    row_count: int,
    *,
    include_stats: bool = False,
    include_sparse: bool = False,
) -> Dict[str, Any]:
    sample = None
    row = conn.execute(
        f'SELECT _atlas_row_id, _atlas_created_at, _atlas_updated_at, data '
        f'FROM "{table_name}" ORDER BY _atlas_row_id LIMIT 1'
    ).fetchone()
    if row:
        from services.atlas.documents import row_to_document
        sample = row_to_document(dict(row))
    key_map = _sample_key_map(sample)
    fields = load_fields(
        conn, entity_id, include_stats=include_stats, include_sparse=include_sparse,
        sample_key_map=key_map,
    )
    from services.atlas.keys import load_keys_for_entity
    keys = load_keys_for_entity(conn, entity_id)
    return {
        "entity_id": entity_id,
        "entity_name": entity_name,
        "document_count": row_count,
        "fields": fields,
        "keys": keys,
        "sample_document": sample,
    }
