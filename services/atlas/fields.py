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


def infer_fields_from_document(conn, entity_id: str, document: Dict[str, Any]) -> None:
    """Update atlas_fields registry from a document's keys."""
    now = _utcnow_iso()
    total_docs = conn.execute(
        "SELECT row_count FROM atlas_entities WHERE id = ?", (entity_id,)
    ).fetchone()
    doc_count = max(1, (total_docs[0] if total_docs else 0))

    for key, value in document.items():
        if key.startswith("_"):
            continue
        try:
            slug = slugify(key)
            validate_slug(slug)
        except ValueError:
            continue
        itype = infer_type(value)
        existing = conn.execute(
            "SELECT * FROM atlas_fields WHERE entity_id = ? AND slug = ?",
            (entity_id, slug),
        ).fetchone()
        if existing:
            merged = _merge_type(existing["inferred_type"], itype)
            occ = (existing["occurrence_count"] or 0) + 1
            null_ratio = existing["nullable_ratio"] or 1.0
            if value is not None:
                null_ratio = ((null_ratio * (occ - 1)) + 0.0) / occ
            conn.execute(
                """UPDATE atlas_fields SET inferred_type = ?, occurrence_count = ?,
                   nullable_ratio = ?, updated_at = ? WHERE id = ?""",
                (merged, occ, null_ratio, now, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO atlas_fields
                   (id, entity_id, slug, inferred_type, occurrence_count,
                    nullable_ratio, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), entity_id, slug, itype,
                    0.0 if value is not None else 1.0, now, now,
                ),
            )


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
    return {
        "entity_id": entity_id,
        "entity_name": entity_name,
        "document_count": row_count,
        "fields": fields,
        "sample_document": sample,
    }
