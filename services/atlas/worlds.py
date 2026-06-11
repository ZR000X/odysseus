"""Atlas world registry operations."""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from core.database import AtlasWorld, SessionLocal
from services.atlas.world_db import bootstrap_world_db, open_world_db, world_db_path


class AtlasNotFoundError(Exception):
    pass


class AtlasAccessError(Exception):
    pass


def _world_to_dict(w: AtlasWorld) -> Dict[str, Any]:
    return {
        "id": w.id,
        "owner": w.owner,
        "name": w.name,
        "description": w.description or "",
        "db_path": w.db_path,
        "entity_count": w.entity_count or 0,
        "row_count": w.row_count or 0,
        "schema_version": w.schema_version or 1,
        "archived": bool(w.archived),
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _owner_query(q, owner: Optional[str]):
    if owner is None:
        from sqlalchemy import false
        return q.filter(false())
    return q.filter(AtlasWorld.owner == owner)


def list_worlds(owner: Optional[str], *, archived: Optional[bool] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = _owner_query(db.query(AtlasWorld), owner)
        if archived is not None:
            q = q.filter(AtlasWorld.archived == archived)
        rows = q.order_by(AtlasWorld.updated_at.desc()).all()
        return [_world_to_dict(w) for w in rows]
    finally:
        db.close()


def get_world(owner: Optional[str], world_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        w = db.query(AtlasWorld).filter(AtlasWorld.id == world_id).first()
        if not w:
            raise AtlasNotFoundError(f"World not found: {world_id}")
        if owner is not None and w.owner != owner:
            raise AtlasAccessError("World not accessible")
        return _world_to_dict(w)
    finally:
        db.close()


def create_world(owner: Optional[str], name: str, description: str = "") -> Dict[str, Any]:
    world_id = str(uuid.uuid4())
    db_path = world_db_path(world_id)
    bootstrap_world_db(world_id, db_path)
    db = SessionLocal()
    try:
        w = AtlasWorld(
            id=world_id,
            owner=owner,
            name=name.strip() or "Untitled World",
            description=description or "",
            db_path=db_path,
            entity_count=0,
            row_count=0,
            schema_version=2,
            archived=False,
        )
        db.add(w)
        db.commit()
        db.refresh(w)
        return _world_to_dict(w)
    finally:
        db.close()


def update_world(
    owner: Optional[str],
    world_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    archived: Optional[bool] = None,
) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        w = db.query(AtlasWorld).filter(AtlasWorld.id == world_id).first()
        if not w:
            raise AtlasNotFoundError(f"World not found: {world_id}")
        if owner is not None and w.owner != owner:
            raise AtlasAccessError("World not accessible")
        if name is not None:
            w.name = name.strip() or "Untitled World"
        if description is not None:
            w.description = description
        if archived is not None:
            w.archived = archived
        db.commit()
        db.refresh(w)
        return _world_to_dict(w)
    finally:
        db.close()


def delete_world(owner: Optional[str], world_id: str) -> bool:
    db = SessionLocal()
    try:
        w = db.query(AtlasWorld).filter(AtlasWorld.id == world_id).first()
        if not w:
            raise AtlasNotFoundError(f"World not found: {world_id}")
        if owner is not None and w.owner != owner:
            raise AtlasAccessError("World not accessible")
        path = w.db_path
        db.delete(w)
        db.commit()
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        return True
    finally:
        db.close()


def resolve_default_world(owner: Optional[str]) -> Dict[str, Any]:
    worlds = list_worlds(owner, archived=False)
    if worlds:
        return worlds[0]
    return create_world(owner, "My World")


def _looks_like_uuid(value: str) -> bool:
    v = (value or "").strip()
    if len(v) == 36 and v.count("-") == 4:
        return True
    return len(v) >= 8 and all(c in "0123456789abcdefABCDEF-" for c in v)


def _world_not_found_message(ref: str, owner: Optional[str]) -> str:
    msg = f'World not found: "{ref}". Try find_world with name="{ref}", or list_worlds.'
    suggestions = find_worlds(owner, ref, limit=3)
    if suggestions:
        hints = ", ".join(f'"{s["name"]}" (world_id: {s["id"][:8]})' for s in suggestions)
        msg += f" Did you mean: {hints}?"
    return msg


def resolve_world(
    owner: Optional[str],
    *,
    world_id: Optional[str] = None,
    world_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve by full UUID, UUID prefix, or case-insensitive exact name."""
    ref_id = (world_id or "").strip() or None
    ref_name = (world_name or "").strip() or None

    if ref_id:
        try:
            return get_world(owner, ref_id)
        except AtlasNotFoundError:
            if _looks_like_uuid(ref_id):
                worlds = list_worlds(owner, archived=False)
                matches = [w for w in worlds if w["id"].startswith(ref_id)]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    names = ", ".join(f'{w["name"]} ({w["id"][:8]})' for w in matches[:5])
                    raise AtlasNotFoundError(
                        f'Ambiguous world_id prefix "{ref_id}": {names}. Use full UUID or world name.'
                    )
            elif not ref_name:
                worlds = list_worlds(owner, archived=False)
                for w in worlds:
                    if w["name"].lower() == ref_id.lower():
                        return w
            raise AtlasNotFoundError(_world_not_found_message(ref_id, owner))

    if ref_name:
        worlds = list_worlds(owner, archived=False)
        for w in worlds:
            if w["name"].lower() == ref_name.lower():
                return w
        raise AtlasNotFoundError(_world_not_found_message(ref_name, owner))

    raise AtlasNotFoundError("world_id or world_name required")


def find_worlds(owner: Optional[str], query: str, *, limit: int = 20) -> List[Dict[str, Any]]:
    """Case-insensitive substring match on world name; exact matches ranked first."""
    q = (query or "").strip().lower()
    if not q:
        return []
    worlds = list_worlds(owner, archived=False)
    exact = [w for w in worlds if w["name"].lower() == q]
    partial = [w for w in worlds if q in w["name"].lower() and w not in exact]
    ranked = exact + partial
    return ranked[: max(1, min(int(limit or 20), 50))]


def refresh_world_stats(owner: Optional[str], world_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    db_path = world["db_path"]
    entity_count = 0
    row_count = 0
    with open_world_db(db_path) as conn:
        entity_count = conn.execute("SELECT COUNT(*) FROM atlas_entities").fetchone()[0]
        for row in conn.execute("SELECT row_count FROM atlas_entities").fetchall():
            row_count += row[0] or 0
    db = SessionLocal()
    try:
        w = db.query(AtlasWorld).filter(AtlasWorld.id == world_id).first()
        if w:
            w.entity_count = entity_count
            w.row_count = row_count
            db.commit()
            db.refresh(w)
            return _world_to_dict(w)
    finally:
        db.close()
    return world
