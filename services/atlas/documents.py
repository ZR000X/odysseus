"""MongoDB-style document operations for Atlas entities."""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from services.atlas.entities import get_entity
from services.atlas.fields import get_schema, infer_fields_from_document, load_fields
from services.atlas.query import compile_filter, compile_sort
from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world, refresh_world_stats

DELETE_MANY_CONFIRM_THRESHOLD = 100
SYSTEM_KEYS = frozenset({"_id", "_atlas_row_id", "_atlas_created_at", "_atlas_updated_at"})


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def row_to_document(row: Dict[str, Any]) -> Dict[str, Any]:
    data = row.get("data")
    if isinstance(data, str):
        try:
            doc = json.loads(data) if data else {}
        except json.JSONDecodeError:
            doc = {}
    elif isinstance(data, dict):
        doc = dict(data)
    else:
        doc = {}
    rid = row["_atlas_row_id"]
    return {
        "_id": rid,
        "_atlas_row_id": rid,
        "_atlas_created_at": row.get("_atlas_created_at"),
        "_atlas_updated_at": row.get("_atlas_updated_at"),
        **doc,
    }


def _strip_system_keys(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in SYSTEM_KEYS}


def _normalize_mongo_id(val: Any) -> Any:
    if isinstance(val, dict) and "$oid" in val:
        return str(val["$oid"])
    return val


def _prepare_insert_data(document: Dict[str, Any]) -> Dict[str, Any]:
    data = {
        k: v for k, v in document.items()
        if k not in ("_atlas_row_id", "_atlas_created_at", "_atlas_updated_at")
    }
    if "_id" in document:
        data["_id"] = _normalize_mongo_id(document["_id"])
    else:
        data.pop("_id", None)
    return data


def _id_exists_in_table(conn, table: str, external_id: Any) -> bool:
    norm = _normalize_mongo_id(external_id)
    row = conn.execute(
        f"SELECT 1 FROM {_quote_ident(table)} WHERE "
        f"json_extract(data, '$._id') = ? OR json_extract(data, '$._id') = ? LIMIT 1",
        (norm, json.dumps(norm)),
    ).fetchone()
    return row is not None


def _apply_update(existing: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(existing)
    has_operator = any(k.startswith("$") for k in update)

    if not has_operator:
        result.update(update)
        return result

    if "$set" in update:
        sets = update["$set"]
        if isinstance(sets, dict):
            result.update(sets)
    if "$unset" in update:
        unsets = update["$unset"]
        if isinstance(unsets, list):
            for k in unsets:
                result.pop(k, None)
        elif isinstance(unsets, dict):
            for k in unsets:
                result.pop(k, None)
    if "$inc" in update:
        incs = update["$inc"]
        if isinstance(incs, dict):
            for k, delta in incs.items():
                cur = result.get(k, 0)
                try:
                    result[k] = (cur or 0) + delta
                except TypeError:
                    result[k] = delta
    return result


def find(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]] = None,
    limit: int = 20,
    offset: int = 0,
    sort: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    where, params = compile_filter(filter_obj)
    order = compile_sort(sort)
    sql = f"SELECT _atlas_row_id, _atlas_created_at, _atlas_updated_at, data FROM {_quote_ident(table)}{where}{order} LIMIT ? OFFSET ?"
    count_sql = f"SELECT COUNT(*) FROM {_quote_ident(table)}{where}"
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute(sql, params + [limit, offset]).fetchall()
        total = conn.execute(count_sql, params).fetchone()[0]
    documents = [row_to_document(dict(r)) for r in rows]
    return {"documents": documents, "rows": documents, "total": total, "limit": limit, "offset": offset}


def find_one(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    result = find(owner, world_id, entity_id, filter_obj=filter_obj, limit=1, offset=0)
    docs = result["documents"]
    return docs[0] if docs else None


def count_documents(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]] = None,
) -> int:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    where, params = compile_filter(filter_obj)
    with open_world_db(world["db_path"]) as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM {_quote_ident(table)}{where}", params
        ).fetchone()[0]


def insert_one(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    document: Dict[str, Any],
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    data = _prepare_insert_data(document)
    with open_world_db(world["db_path"]) as conn:
        if "_id" in data and _id_exists_in_table(conn, table, data["_id"]):
            raise ValueError(f"Duplicate _id: {data['_id']}")
        cur = conn.execute(
            f"INSERT INTO {_quote_ident(table)} (data) VALUES (?)",
            (json.dumps(data),),
        )
        row_id = cur.lastrowid
        conn.execute(
            "UPDATE atlas_entities SET row_count = row_count + 1, updated_at = datetime('now') WHERE id = ?",
            (entity_id,),
        )
        infer_fields_from_document(conn, entity_id, data)
        row = conn.execute(
            f"SELECT _atlas_row_id, _atlas_created_at, _atlas_updated_at, data FROM {_quote_ident(table)} WHERE _atlas_row_id = ?",
            (row_id,),
        ).fetchone()
    refresh_world_stats(owner, world_id)
    doc = row_to_document(dict(row))
    return {"inserted_id": row_id, "row_id": row_id, "document": doc, "row": doc}


def insert_many(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    ids: List[int] = []
    errors: List[Dict[str, Any]] = []
    inserted_count = 0

    with open_world_db(world["db_path"]) as conn:
        for i, document in enumerate(documents):
            try:
                data = _prepare_insert_data(document)
                if "_id" in data and _id_exists_in_table(conn, table, data["_id"]):
                    errors.append({"index": i, "message": f"Duplicate _id: {data['_id']}"})
                    continue
                cur = conn.execute(
                    f"INSERT INTO {_quote_ident(table)} (data) VALUES (?)",
                    (json.dumps(data),),
                )
                row_id = cur.lastrowid
                ids.append(row_id)
                inserted_count += 1
                infer_fields_from_document(conn, entity_id, data)
            except Exception as e:
                errors.append({"index": i, "message": str(e)})

        if inserted_count:
            conn.execute(
                "UPDATE atlas_entities SET row_count = row_count + ?, updated_at = datetime('now') WHERE id = ?",
                (inserted_count, entity_id),
            )

    if inserted_count:
        refresh_world_stats(owner, world_id)

    result: Dict[str, Any] = {"inserted_ids": ids, "inserted_count": inserted_count}
    if errors:
        result["errors"] = errors
    return result


def update_one(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]],
    update: Dict[str, Any],
    upsert: bool = False,
) -> Dict[str, Any]:
    existing = find_one(owner, world_id, entity_id, filter_obj)
    if existing is None:
        if upsert and update:
            data = _apply_update({}, update if not any(k.startswith("$") for k in update) else update.get("$set", {}))
            r = insert_one(owner, world_id, entity_id, data)
            return {"matched_count": 0, "modified_count": 0, "upserted_id": r["inserted_id"]}
        return {"matched_count": 0, "modified_count": 0}
    return _update_by_id(owner, world_id, entity_id, existing["_atlas_row_id"], update, matched=1)


def update_many(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]],
    update: Dict[str, Any],
) -> Dict[str, Any]:
    result = find(owner, world_id, entity_id, filter_obj=filter_obj, limit=100, offset=0)
    docs = result["documents"]
    modified = 0
    for doc in docs:
        r = _update_by_id(owner, world_id, entity_id, doc["_atlas_row_id"], update, matched=0)
        if r.get("modified_count"):
            modified += 1
    return {"matched_count": len(docs), "modified_count": modified}


def _update_by_id(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    row_id: int,
    update: Dict[str, Any],
    matched: int = 1,
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            f"SELECT data FROM {_quote_ident(table)} WHERE _atlas_row_id = ?",
            (row_id,),
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Document not found: {row_id}")
        existing = json.loads(row["data"] or "{}")
        new_data = _apply_update(existing, update)
        conn.execute(
            f"UPDATE {_quote_ident(table)} SET data = ?, _atlas_updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE _atlas_row_id = ?",
            (json.dumps(new_data), row_id),
        )
        infer_fields_from_document(conn, entity_id, new_data)
    return {"matched_count": matched, "modified_count": 1, "row_id": row_id}


def replace_one(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]],
    replacement: Dict[str, Any],
    upsert: bool = False,
) -> Dict[str, Any]:
    data = _strip_system_keys(replacement)
    existing = find_one(owner, world_id, entity_id, filter_obj)
    if existing is None:
        if upsert:
            r = insert_one(owner, world_id, entity_id, data)
            return {"matched_count": 0, "modified_count": 0, "upserted_id": r["inserted_id"]}
        return {"matched_count": 0, "modified_count": 0}
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    row_id = existing["_atlas_row_id"]
    with open_world_db(world["db_path"]) as conn:
        conn.execute(
            f"UPDATE {_quote_ident(table)} SET data = ?, _atlas_updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE _atlas_row_id = ?",
            (json.dumps(data), row_id),
        )
        infer_fields_from_document(conn, entity_id, data)
    return {"matched_count": 1, "modified_count": 1, "row_id": row_id}


def delete_one(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    existing = find_one(owner, world_id, entity_id, filter_obj)
    if not existing:
        return {"deleted_count": 0}
    _delete_by_id(owner, world_id, entity_id, existing["_atlas_row_id"])
    return {"deleted_count": 1}


def delete_many(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    filter_obj: Optional[Dict[str, Any]] = None,
    confirm: bool = False,
) -> Dict[str, Any]:
    count = count_documents(owner, world_id, entity_id, filter_obj)
    if not filter_obj and count > 0 and not confirm:
        raise ValueError(
            f"deleteMany with empty filter would delete {count} documents. "
            f"Pass confirm=true to proceed."
        )
    if count > DELETE_MANY_CONFIRM_THRESHOLD and not confirm:
        raise ValueError(
            f"deleteMany would delete {count} documents (>{DELETE_MANY_CONFIRM_THRESHOLD}). "
            f"Pass confirm=true to proceed."
        )
    result = find(owner, world_id, entity_id, filter_obj=filter_obj, limit=10000, offset=0)
    deleted = 0
    for doc in result["documents"]:
        _delete_by_id(owner, world_id, entity_id, doc["_atlas_row_id"])
        deleted += 1
    return {"deleted_count": deleted}


def _delete_by_id(owner: Optional[str], world_id: str, entity_id: str, row_id: int) -> None:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    with open_world_db(world["db_path"]) as conn:
        cur = conn.execute(
            f"DELETE FROM {_quote_ident(table)} WHERE _atlas_row_id = ?",
            (row_id,),
        )
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Document not found: {row_id}")
        conn.execute(
            "UPDATE atlas_entities SET row_count = MAX(0, row_count - 1), updated_at = datetime('now') WHERE id = ?",
            (entity_id,),
        )
    refresh_world_stats(owner, world_id)


def get_entity_schema(owner: Optional[str], world_id: str, entity_id: str) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        return get_schema(
            conn, entity_id, entity["name"], entity["table_name"], entity["row_count"]
        )


def describe_collection(owner: Optional[str], world_id: str, entity_id: str) -> Dict[str, Any]:
    return get_entity_schema(owner, world_id, entity_id)
