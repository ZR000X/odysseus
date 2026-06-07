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
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _owner_query(q, owner: Optional[str]):
    if owner is None:
        from sqlalchemy import false
        return q.filter(false())
    return q.filter(AtlasWorld.owner == owner)


def list_worlds(owner: Optional[str]) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        q = _owner_query(db.query(AtlasWorld), owner)
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
        )
        db.add(w)
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
    worlds = list_worlds(owner)
    if worlds:
        return worlds[0]
    return create_world(owner, "My World")


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
