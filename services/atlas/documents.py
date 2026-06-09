"""MongoDB-style document operations for Atlas entities."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from services.atlas.entities import get_entity, get_entity_table
from services.atlas.fields import get_schema, infer_fields_from_document, infer_fields_from_documents, load_fields
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


def _load_id_to_row_map(conn, table: str) -> Dict[Any, int]:
    """Map document _id / _atlas_row_id values to internal row ids."""
    id_map: Dict[Any, int] = {}
    rows = conn.execute(
        f"SELECT _atlas_row_id, json_extract(data, '$._id') AS ext_id "
        f"FROM {_quote_ident(table)}"
    ).fetchall()
    for row in rows:
        rid = row["_atlas_row_id"]
        for key in (rid, str(rid)):
            id_map[key] = rid
        ext = row["ext_id"]
        if ext is None:
            continue
        norm = _normalize_mongo_id(ext)
        for key in (norm, str(norm), json.dumps(norm)):
            id_map[key] = rid
    return id_map


def _resolve_merge_row_id(id_map: Dict[Any, int], merge_id: Any) -> Optional[int]:
    if merge_id is None or merge_id == "":
        return None
    norm = int(merge_id) if isinstance(merge_id, str) and merge_id.isdigit() else merge_id
    for key in (norm, str(norm), json.dumps(norm)):
        if key in id_map:
            return id_map[key]
    return None


def _strip_import_meta(document: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in document.items() if k != "_import_merge_id"}


def import_documents_bulk(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    documents: List[Dict[str, Any]],
    *,
    mode: str = "append",
) -> Dict[str, Any]:
    """Bulk import documents in a single transaction with deferred metadata updates."""
    mode = (mode or "append").lower()
    if mode not in ("append", "merge", "replace"):
        raise ValueError("mode must be append, merge, or replace")

    entity = get_entity_table(owner, world_id, entity_id)
    table = entity["table_name"]
    stats: Dict[str, Any] = {
        "rows_total": len(documents),
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
        "rows_failed": 0,
        "errors": [],
        "inserted_ids": [],
    }
    if not documents:
        return stats

    to_insert: List[tuple[int, Dict[str, Any]]] = []
    to_update: List[tuple[int, int, Dict[str, Any]]] = []
    infer_docs: List[Dict[str, Any]] = []
    has_explicit_ids = any(
        "_id" in _prepare_insert_data(_strip_import_meta(doc))
        or doc.get("_import_merge_id") not in (None, "")
        for doc in documents
    )

    with open_world_db(entity["db_path"]) as conn:
        if mode == "replace":
            conn.execute(f"DELETE FROM {_quote_ident(table)}")
            conn.execute(
                "UPDATE atlas_entities SET row_count = 0, updated_at = datetime('now') WHERE id = ?",
                (entity_id,),
            )

        existing_ids: set = set()
        id_map: Dict[Any, int] = {}
        if mode in ("append", "merge") and has_explicit_ids:
            id_map = _load_id_to_row_map(conn, table)
            existing_ids = set(id_map.keys())
        elif mode == "merge":
            id_map = _load_id_to_row_map(conn, table)

        for i, raw in enumerate(documents):
            merge_id = raw.get("_import_merge_id")
            doc = _strip_import_meta(raw)
            try:
                data = _prepare_insert_data(doc)
            except Exception as e:
                stats["rows_failed"] += 1
                stats["errors"].append({"index": i, "message": str(e)})
                continue

            if mode == "merge" and merge_id not in (None, ""):
                row_id = _resolve_merge_row_id(id_map, merge_id)
                if row_id is not None:
                    to_update.append((i, row_id, data))
                    continue
                if "_id" in data:
                    dup_key = data["_id"]
                    for key in (dup_key, str(dup_key), json.dumps(dup_key)):
                        if key in existing_ids:
                            stats["rows_failed"] += 1
                            stats["errors"].append({"index": i, "message": f"Duplicate _id: {dup_key}"})
                            break
                    else:
                        to_insert.append((i, data))
                    continue
                to_insert.append((i, data))
                continue

            if not data and mode != "append":
                stats["rows_skipped"] += 1
                continue

            if "_id" in data:
                dup_key = data["_id"]
                is_dup = False
                for key in (dup_key, str(dup_key), json.dumps(dup_key)):
                    if key in existing_ids:
                        stats["rows_failed"] += 1
                        stats["errors"].append({"index": i, "message": f"Duplicate _id: {dup_key}"})
                        is_dup = True
                        break
                if is_dup:
                    continue

            to_insert.append((i, data))

        update_ts = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        for i, row_id, data in to_update:
            try:
                row = conn.execute(
                    f"SELECT data FROM {_quote_ident(table)} WHERE _atlas_row_id = ?",
                    (row_id,),
                ).fetchone()
                if not row:
                    to_insert.append((i, data))
                    continue
                existing = json.loads(row["data"] or "{}")
                new_data = _apply_update(existing, data)
                conn.execute(
                    f"UPDATE {_quote_ident(table)} SET data = ?, _atlas_updated_at = {update_ts} "
                    f"WHERE _atlas_row_id = ?",
                    (json.dumps(new_data), row_id),
                )
                infer_docs.append(new_data)
                stats["rows_updated"] += 1
            except Exception as e:
                stats["rows_failed"] += 1
                stats["errors"].append({"index": i, "message": str(e)})

        insert_sql = f"INSERT INTO {_quote_ident(table)} (data) VALUES (?)"
        insert_params: List[tuple[str]] = []
        for i, data in to_insert:
            insert_params.append((json.dumps(data),))
            key = data.get("_id")
            if key is not None:
                for k in (key, str(key), json.dumps(key)):
                    existing_ids.add(k)

        if insert_params:
            conn.executemany(insert_sql, insert_params)
            first_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            count = len(insert_params)
            first_id = first_id - count + 1
            stats["inserted_ids"] = list(range(first_id, first_id + count))
            stats["rows_inserted"] = count
            infer_docs.extend(data for _, data in to_insert)

        if mode == "replace":
            conn.execute(
                "UPDATE atlas_entities SET row_count = ?, updated_at = datetime('now') WHERE id = ?",
                (stats["rows_inserted"], entity_id),
            )
        elif stats["rows_inserted"]:
            conn.execute(
                "UPDATE atlas_entities SET row_count = row_count + ?, updated_at = datetime('now') WHERE id = ?",
                (stats["rows_inserted"], entity_id),
            )

        if infer_docs:
            infer_fields_from_documents(conn, entity_id, infer_docs)

    if stats["rows_inserted"] or stats["rows_updated"] or mode == "replace":
        refresh_world_stats(owner, world_id)

    return stats


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


def _compile_entity_filter(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    table: str,
    filter_obj: Optional[Dict[str, Any]],
) -> tuple:
    extra_where = ""
    extra_params: List[Any] = []
    filt = dict(filter_obj) if filter_obj else {}
    key_violation = filt.pop("$keyViolation", None)
    if key_violation:
        from services.atlas.key_violations import compile_key_violation_filter, load_slug_to_key
        from services.atlas.keys import get_key
        from services.atlas.world_db import open_world_db
        from services.atlas.worlds import get_world
        key = get_key(owner, world_id, entity_id, str(key_violation))
        world = get_world(owner, world_id)
        with open_world_db(world["db_path"]) as conn:
            slug_to_key = load_slug_to_key(conn, table)
        extra_where, extra_params = compile_key_violation_filter(
            table, key["field_slugs"], slug_to_key=slug_to_key
        )
        extra_where = extra_where.replace(" WHERE ", "", 1) if extra_where.startswith(" WHERE ") else extra_where
    return compile_filter(filt or None, extra_where=extra_where, extra_params=extra_params)


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
    where, params = _compile_entity_filter(owner, world_id, entity_id, table, filter_obj)
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
    where, params = _compile_entity_filter(owner, world_id, entity_id, table, filter_obj)
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
    result = import_documents_bulk(owner, world_id, entity_id, documents, mode="append")
    out: Dict[str, Any] = {
        "inserted_ids": result.get("inserted_ids", []),
        "inserted_count": result["rows_inserted"],
    }
    if result.get("errors"):
        out["errors"] = result["errors"]
    return out


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


def get_entity_schema(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    *,
    include_stats: bool = False,
    include_sparse: bool = False,
) -> Dict[str, Any]:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        return get_schema(
            conn, entity_id, entity["name"], entity["table_name"], entity["row_count"],
            include_stats=include_stats,
            include_sparse=include_sparse,
        )


def describe_collection(owner: Optional[str], world_id: str, entity_id: str) -> Dict[str, Any]:
    return get_entity_schema(owner, world_id, entity_id)
