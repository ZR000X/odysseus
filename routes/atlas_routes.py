# routes/atlas_routes.py
"""Atlas structured data API."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from src.auth_helpers import get_current_user
from services.atlas import worlds as atlas_worlds
from services.atlas import entities as atlas_entities
from services.atlas import rows as atlas_rows
from services.atlas import csv_io as atlas_csv
from services.atlas.worlds import AtlasNotFoundError, AtlasAccessError

logger = logging.getLogger(__name__)


class WorldCreate(BaseModel):
    name: str
    description: str = ""


class AttributeSpec(BaseModel):
    name: str
    type: str = "text"
    primary_key: bool = False
    unique: bool = False
    nullable: bool = True


class EntityCreate(BaseModel):
    name: str
    description: str = ""
    attributes: List[AttributeSpec] = []


class AttributeCreate(BaseModel):
    name: str
    type: str = "text"
    primary_key: bool = False
    unique: bool = False
    nullable: bool = True


class RowBody(BaseModel):
    row: Dict[str, Any]


class ImportBody(BaseModel):
    mode: str = "append"
    csv: str


def _owner(request: Request) -> Optional[str]:
    return get_current_user(request)


def _handle_err(e: Exception):
    if isinstance(e, AtlasNotFoundError):
        raise HTTPException(404, str(e))
    if isinstance(e, AtlasAccessError):
        raise HTTPException(403, str(e))
    if isinstance(e, ValueError):
        raise HTTPException(400, str(e))
    raise


def setup_atlas_routes() -> APIRouter:
    router = APIRouter()

    @router.get("/api/atlas/worlds")
    async def list_worlds(request: Request):
        owner = _owner(request)
        return {"worlds": atlas_worlds.list_worlds(owner)}

    @router.post("/api/atlas/worlds")
    async def create_world(request: Request, body: WorldCreate):
        owner = _owner(request)
        try:
            w = atlas_worlds.create_world(owner, body.name, body.description)
            return w
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/entities")
    async def list_entities(request: Request, world_id: str):
        owner = _owner(request)
        try:
            return {"entities": atlas_entities.list_entities(owner, world_id)}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities")
    async def create_entity(request: Request, world_id: str, body: EntityCreate):
        owner = _owner(request)
        try:
            attrs = [a.model_dump() for a in body.attributes]
            return atlas_entities.create_entity(
                owner, world_id, body.name, attributes=attrs, description=body.description
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/attributes")
    async def add_attribute(request: Request, world_id: str, entity_id: str, body: AttributeCreate):
        owner = _owner(request)
        try:
            return atlas_entities.add_attribute(
                owner, world_id, entity_id, body.name,
                attr_type=body.type,
                nullable=body.nullable,
                is_primary_key=body.primary_key,
                is_unique=body.unique,
            )
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/entities/{entity_id}/rows")
    async def list_rows(
        request: Request, world_id: str, entity_id: str,
        limit: int = 50, offset: int = 0,
        filter_col: Optional[str] = None, filter_val: Optional[str] = None,
    ):
        owner = _owner(request)
        try:
            return atlas_rows.list_rows(
                owner, world_id, entity_id,
                limit=limit, offset=offset,
                filter_col=filter_col, filter_val=filter_val,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/rows")
    async def add_row(request: Request, world_id: str, entity_id: str, body: RowBody):
        owner = _owner(request)
        try:
            return atlas_rows.add_row(owner, world_id, entity_id, body.row)
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}/entities/{entity_id}/rows/{row_id}")
    async def update_row(request: Request, world_id: str, entity_id: str, row_id: int, body: RowBody):
        owner = _owner(request)
        try:
            return atlas_rows.update_row(owner, world_id, entity_id, row_id, body.row)
        except Exception as e:
            _handle_err(e)

    @router.delete("/api/atlas/worlds/{world_id}/entities/{entity_id}/rows/{row_id}")
    async def delete_row(request: Request, world_id: str, entity_id: str, row_id: int):
        owner = _owner(request)
        try:
            atlas_rows.delete_row(owner, world_id, entity_id, row_id)
            return {"ok": True}
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/entities/{entity_id}/export.csv")
    async def export_csv(request: Request, world_id: str, entity_id: str):
        owner = _owner(request)
        try:
            text = atlas_csv.export_csv(owner, world_id, entity_id)
            entity = atlas_entities.get_entity(owner, world_id, entity_id)
            filename = f"{entity['name'].replace(' ', '_')}.csv"
            return PlainTextResponse(
                text,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/import")
    async def import_csv(request: Request, world_id: str, entity_id: str, body: ImportBody):
        owner = _owner(request)
        try:
            return atlas_csv.import_rows(owner, world_id, entity_id, body.csv, mode=body.mode)
        except Exception as e:
            _handle_err(e)

    return router
