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
from services.atlas import documents as atlas_documents
from services.atlas import csv_io as atlas_csv
from services.atlas import canvas as atlas_canvas
from services.atlas import relationships as atlas_relationships
from services.atlas.worlds import AtlasNotFoundError, AtlasAccessError

logger = logging.getLogger(__name__)


class WorldCreate(BaseModel):
    name: str
    description: str = ""


class WorldUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    archived: Optional[bool] = None


class EntityCreate(BaseModel):
    name: str
    description: str = ""


class EntityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RowBody(BaseModel):
    row: Dict[str, Any]


class DocumentBody(BaseModel):
    document: Dict[str, Any]


class DocumentsBody(BaseModel):
    documents: List[Dict[str, Any]]


class FilterBody(BaseModel):
    filter: Dict[str, Any] = {}
    limit: int = 50
    offset: int = 0
    sort: Optional[Dict[str, int]] = None
    confirm: bool = False


class UpdateBody(BaseModel):
    filter: Dict[str, Any] = {}
    update: Dict[str, Any]
    upsert: bool = False
    confirm: bool = False


class ReplaceBody(BaseModel):
    filter: Dict[str, Any] = {}
    replacement: Dict[str, Any]
    upsert: bool = False


class ImportBody(BaseModel):
    mode: str = "append"
    csv: str


class CanvasSaveBody(BaseModel):
    nodes: List[Dict[str, Any]]


class RelationshipCreate(BaseModel):
    from_entity_id: str
    to_entity_id: str
    rel_type: str = "one_to_many"
    from_field: str = ""
    to_field: str = ""
    label: str = ""
    from_anchor: str = "right"
    to_anchor: str = "left"


class RelationshipUpdate(BaseModel):
    rel_type: Optional[str] = None
    from_field: Optional[str] = None
    to_field: Optional[str] = None
    label: Optional[str] = None
    from_anchor: Optional[str] = None
    to_anchor: Optional[str] = None
    from_entity_id: Optional[str] = None
    to_entity_id: Optional[str] = None


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
    async def list_worlds(request: Request, archived: Optional[bool] = None):
        owner = _owner(request)
        return {"worlds": atlas_worlds.list_worlds(owner, archived=archived)}

    @router.post("/api/atlas/worlds")
    async def create_world(request: Request, body: WorldCreate):
        owner = _owner(request)
        try:
            w = atlas_worlds.create_world(owner, body.name, body.description)
            return w
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}")
    async def update_world(request: Request, world_id: str, body: WorldUpdate):
        owner = _owner(request)
        try:
            return atlas_worlds.update_world(
                owner, world_id,
                name=body.name, description=body.description, archived=body.archived,
            )
        except Exception as e:
            _handle_err(e)

    @router.delete("/api/atlas/worlds/{world_id}")
    async def delete_world(request: Request, world_id: str):
        owner = _owner(request)
        try:
            atlas_worlds.delete_world(owner, world_id)
            return {"ok": True}
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
            return atlas_entities.create_entity(
                owner, world_id, body.name, description=body.description
            )
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}/entities/{entity_id}")
    async def update_entity(request: Request, world_id: str, entity_id: str, body: EntityUpdate):
        owner = _owner(request)
        try:
            return atlas_entities.update_entity(
                owner, world_id, entity_id,
                name=body.name, description=body.description,
            )
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/entities/{entity_id}/schema")
    async def get_schema(request: Request, world_id: str, entity_id: str):
        owner = _owner(request)
        try:
            return atlas_documents.get_entity_schema(owner, world_id, entity_id)
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/find")
    async def find_docs(request: Request, world_id: str, entity_id: str, body: FilterBody):
        owner = _owner(request)
        try:
            return atlas_documents.find(
                owner, world_id, entity_id,
                filter_obj=body.filter or None,
                limit=body.limit, offset=body.offset, sort=body.sort,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/findOne")
    async def find_one_doc(request: Request, world_id: str, entity_id: str, body: FilterBody):
        owner = _owner(request)
        try:
            doc = atlas_documents.find_one(owner, world_id, entity_id, body.filter or None)
            return {"document": doc}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/insertOne")
    async def insert_one(request: Request, world_id: str, entity_id: str, body: DocumentBody):
        owner = _owner(request)
        try:
            return atlas_documents.insert_one(owner, world_id, entity_id, body.document)
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/insertMany")
    async def insert_many(request: Request, world_id: str, entity_id: str, body: DocumentsBody):
        owner = _owner(request)
        try:
            return atlas_documents.insert_many(owner, world_id, entity_id, body.documents)
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/updateOne")
    async def update_one(request: Request, world_id: str, entity_id: str, body: UpdateBody):
        owner = _owner(request)
        try:
            return atlas_documents.update_one(
                owner, world_id, entity_id,
                body.filter or None, body.update, upsert=body.upsert,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/updateMany")
    async def update_many(request: Request, world_id: str, entity_id: str, body: UpdateBody):
        owner = _owner(request)
        try:
            return atlas_documents.update_many(
                owner, world_id, entity_id, body.filter or None, body.update,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/replaceOne")
    async def replace_one(request: Request, world_id: str, entity_id: str, body: ReplaceBody):
        owner = _owner(request)
        try:
            return atlas_documents.replace_one(
                owner, world_id, entity_id,
                body.filter or None, body.replacement, upsert=body.upsert,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/deleteOne")
    async def delete_one(request: Request, world_id: str, entity_id: str, body: FilterBody):
        owner = _owner(request)
        try:
            return atlas_documents.delete_one(owner, world_id, entity_id, body.filter or None)
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/deleteMany")
    async def delete_many(request: Request, world_id: str, entity_id: str, body: FilterBody):
        owner = _owner(request)
        try:
            return atlas_documents.delete_many(
                owner, world_id, entity_id, body.filter or None, confirm=body.confirm,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/count")
    async def count_docs(request: Request, world_id: str, entity_id: str, body: FilterBody):
        owner = _owner(request)
        try:
            n = atlas_documents.count_documents(owner, world_id, entity_id, body.filter or None)
            return {"count": n}
        except Exception as e:
            _handle_err(e)

    # Legacy row endpoints
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

    # Canvas
    @router.get("/api/atlas/worlds/{world_id}/canvas")
    async def get_canvas(request: Request, world_id: str):
        owner = _owner(request)
        try:
            return atlas_canvas.get_layout(owner, world_id)
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}/canvas")
    async def put_canvas(request: Request, world_id: str, body: CanvasSaveBody):
        owner = _owner(request)
        try:
            return atlas_canvas.save_layout(owner, world_id, body.nodes)
        except Exception as e:
            _handle_err(e)

    # Relationships
    @router.get("/api/atlas/worlds/{world_id}/relationships")
    async def list_relationships(request: Request, world_id: str):
        owner = _owner(request)
        try:
            return {"relationships": atlas_relationships.list_relationships(owner, world_id)}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/relationships")
    async def create_relationship(request: Request, world_id: str, body: RelationshipCreate):
        owner = _owner(request)
        try:
            return atlas_relationships.create_relationship(
                owner, world_id,
                body.from_entity_id, body.to_entity_id,
                body.rel_type, body.from_field, body.to_field,
                label=body.label,
                from_anchor=body.from_anchor, to_anchor=body.to_anchor,
            )
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}/relationships/{rel_id}")
    async def update_relationship(request: Request, world_id: str, rel_id: str, body: RelationshipUpdate):
        owner = _owner(request)
        try:
            return atlas_relationships.update_relationship(
                owner, world_id, rel_id,
                **body.model_dump(exclude_unset=True),
            )
        except Exception as e:
            _handle_err(e)

    @router.delete("/api/atlas/worlds/{world_id}/relationships/{rel_id}")
    async def delete_relationship(request: Request, world_id: str, rel_id: str):
        owner = _owner(request)
        try:
            atlas_relationships.delete_relationship(owner, world_id, rel_id)
            return {"ok": True}
        except Exception as e:
            _handle_err(e)

    return router
