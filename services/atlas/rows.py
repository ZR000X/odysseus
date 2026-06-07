"""Legacy row API — thin wrappers over documents.py."""
from __future__ import annotations

from typing import Any, Dict, Optional

from services.atlas import documents as atlas_documents


def list_rows(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    limit: int = 20,
    offset: int = 0,
    filter_col: Optional[str] = None,
    filter_val: Optional[str] = None,
) -> Dict[str, Any]:
    filter_obj = None
    if filter_col and filter_val is not None:
        if filter_col in ("_atlas_row_id", "_id"):
            filter_obj = {"_id": int(filter_val)}
        else:
            filter_obj = {filter_col: filter_val}
    return atlas_documents.find(
        owner, world_id, entity_id,
        filter_obj=filter_obj, limit=limit, offset=offset,
    )


def count_rows(owner: Optional[str], world_id: str, entity_id: str) -> int:
    return atlas_documents.count_documents(owner, world_id, entity_id)


def add_row(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    row: Dict[str, Any],
) -> Dict[str, Any]:
    return atlas_documents.insert_one(owner, world_id, entity_id, row)


def update_row(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    row_id: int,
    row: Dict[str, Any],
) -> Dict[str, Any]:
    r = atlas_documents.update_one(
        owner, world_id, entity_id, {"_id": row_id}, row,
    )
    doc = atlas_documents.find_one(owner, world_id, entity_id, {"_id": row_id})
    return {"row_id": row_id, "row": doc or {"_atlas_row_id": row_id}, **r}


def delete_row(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    row_id: int,
) -> bool:
    atlas_documents.delete_one(owner, world_id, entity_id, {"_id": row_id})
    return True
