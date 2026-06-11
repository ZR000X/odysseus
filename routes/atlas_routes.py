# routes/atlas_routes.py
"""Atlas structured data API."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from src.auth_helpers import get_current_user
from services.atlas import worlds as atlas_worlds
from services.atlas import entities as atlas_entities
from services.atlas import rows as atlas_rows
from services.atlas import documents as atlas_documents
from services.atlas import csv_io as atlas_csv
from services.atlas import xlsx_io as atlas_xlsx
from services.atlas import canvas as atlas_canvas
from services.atlas import relationships as atlas_relationships
from services.atlas import clusters as atlas_clusters
from services.atlas import keys as atlas_keys
from services.atlas import key_violations as atlas_key_violations
from services.atlas import queries as atlas_queries
from services.atlas import sql_engine as atlas_sql_engine
from services.atlas.keys import KeyInUseError
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


class SheetMapping(BaseModel):
    sheet_name: str
    action: str = "create_new"  # import_to_existing | create_new | skip
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    mode: Optional[str] = None


class WorldImportBody(BaseModel):
    mappings: List[SheetMapping]
    default_mode: str = "append"
    restore_meta: bool = True
    world_name: Optional[str] = None
    world_description: str = ""


class NewWorldImportBody(WorldImportBody):
    pass


class CanvasSaveBody(BaseModel):
    nodes: List[Dict[str, Any]]
    query_nodes: List[Dict[str, Any]] = []
    clusters: List[Dict[str, Any]] = []


class ClusterCreate(BaseModel):
    name: str
    description: str = ""
    x: float = 0
    y: float = 0
    w: float = 400
    h: float = 300
    parent_cluster_id: Optional[str] = None
    color: str = ""
    z_index: int = 0


class ClusterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    parent_cluster_id: Optional[str] = None
    color: Optional[str] = None
    z_index: Optional[int] = None
    collapsed: Optional[bool] = None


class RelationshipCreate(BaseModel):
    from_entity_id: str
    to_entity_id: str
    rel_type: str = "one_to_many"
    from_cardinality: Optional[str] = None
    to_cardinality: Optional[str] = None
    from_field: str = ""
    to_field: str = ""
    from_key_id: Optional[str] = None
    to_key_id: Optional[str] = None
    label: str = ""
    from_anchor: str = "right"
    to_anchor: str = "left"


class RelationshipUpdate(BaseModel):
    rel_type: Optional[str] = None
    from_cardinality: Optional[str] = None
    to_cardinality: Optional[str] = None
    from_field: Optional[str] = None
    to_field: Optional[str] = None
    from_key_id: Optional[str] = None
    to_key_id: Optional[str] = None
    label: Optional[str] = None
    from_anchor: Optional[str] = None
    to_anchor: Optional[str] = None
    from_entity_id: Optional[str] = None
    to_entity_id: Optional[str] = None


class KeyCreate(BaseModel):
    name: str
    field_slugs: List[str]


class KeyUpdate(BaseModel):
    name: Optional[str] = None
    field_slugs: Optional[List[str]] = None


class KeyViolationBody(BaseModel):
    key_id: str
    limit: int = 50
    offset: int = 0


class QueryCreate(BaseModel):
    name: str
    description: str = ""
    sql_text: str


class QueryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sql_text: Optional[str] = None


class QueryValidateBody(BaseModel):
    sql_text: str
    query_id: Optional[str] = None
    preview_limit: int = 25


def _owner(request: Request) -> Optional[str]:
    return get_current_user(request)


def _handle_err(e: Exception):
    if isinstance(e, AtlasNotFoundError):
        raise HTTPException(404, str(e))
    if isinstance(e, AtlasAccessError):
        raise HTTPException(403, str(e))
    if isinstance(e, KeyInUseError):
        raise HTTPException(409, str(e))
    if isinstance(e, ValueError):
        raise HTTPException(400, str(e))
    if isinstance(e, RuntimeError):
        raise HTTPException(500, str(e))
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
    async def list_entities(request: Request, world_id: str, summary: bool = True):
        owner = _owner(request)
        try:
            entities = atlas_entities.list_entities(owner, world_id, include_fields=not summary)
            if summary:
                return {"entities": [atlas_entities.entity_summary(e) for e in entities]}
            return {"entities": entities}
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

    @router.delete("/api/atlas/worlds/{world_id}/entities/{entity_id}")
    async def delete_entity(request: Request, world_id: str, entity_id: str):
        owner = _owner(request)
        try:
            atlas_entities.delete_entity(owner, world_id, entity_id)
            return {"ok": True}
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/entities/{entity_id}/schema")
    async def get_schema(request: Request, world_id: str, entity_id: str):
        owner = _owner(request)
        try:
            return atlas_documents.get_entity_schema(owner, world_id, entity_id)
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/entities/{entity_id}/keys")
    async def list_keys(request: Request, world_id: str, entity_id: str):
        owner = _owner(request)
        try:
            return {"keys": atlas_keys.list_keys(owner, world_id, entity_id)}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/keys")
    async def create_key(request: Request, world_id: str, entity_id: str, body: KeyCreate):
        owner = _owner(request)
        try:
            return atlas_keys.create_key(
                owner, world_id, entity_id, body.name, body.field_slugs,
            )
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}/entities/{entity_id}/keys/{key_id}")
    async def update_key(request: Request, world_id: str, entity_id: str, key_id: str, body: KeyUpdate):
        owner = _owner(request)
        try:
            return atlas_keys.update_key(
                owner, world_id, entity_id, key_id,
                name=body.name, field_slugs=body.field_slugs,
            )
        except Exception as e:
            _handle_err(e)

    @router.delete("/api/atlas/worlds/{world_id}/entities/{entity_id}/keys/{key_id}")
    async def delete_key(request: Request, world_id: str, entity_id: str, key_id: str):
        owner = _owner(request)
        try:
            atlas_keys.delete_key(owner, world_id, entity_id, key_id)
            return {"ok": True}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/keyViolations")
    async def key_violations(request: Request, world_id: str, entity_id: str, body: KeyViolationBody):
        owner = _owner(request)
        try:
            return atlas_key_violations.find_key_violations(
                owner, world_id, entity_id, body.key_id,
                limit=body.limit, offset=body.offset,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/entities/{entity_id}/keyViolations/count")
    async def key_violations_count(request: Request, world_id: str, entity_id: str, body: KeyViolationBody):
        owner = _owner(request)
        try:
            n = atlas_key_violations.count_key_violations(
                owner, world_id, entity_id, body.key_id,
            )
            return {"count": n, "key_id": body.key_id}
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

    @router.get("/api/atlas/worlds/{world_id}/export.xlsx")
    async def export_world_xlsx(request: Request, world_id: str):
        owner = _owner(request)
        try:
            data, stats = atlas_xlsx.export_world(owner, world_id)
            world = atlas_worlds.get_world(owner, world_id)
            filename = f"{world['name'].replace(' ', '_')}.xlsx"
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "X-Atlas-Entity-Count": str(stats.get("entity_count", 0)),
                    "X-Atlas-Document-Count": str(stats.get("document_count", 0)),
                    "X-Atlas-Relationship-Count": str(stats.get("relationship_count", 0)),
                },
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/import/analyze")
    async def analyze_world_import(request: Request, world_id: str, file: UploadFile = File(...)):
        owner = _owner(request)
        try:
            raw = await file.read()
            return atlas_xlsx.analyze_import(owner, raw, world_id=world_id)
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/import")
    async def import_world_xlsx(
        request: Request,
        world_id: str,
        file: UploadFile = File(...),
        metadata: str = Form("{}"),
    ):
        owner = _owner(request)
        try:
            import json as _json
            meta = _json.loads(metadata or "{}")
            req = WorldImportBody(**meta)
            raw = await file.read()
            mappings = [m.model_dump() for m in req.mappings]
            return atlas_xlsx.import_world(
                owner, raw, mappings,
                world_id=world_id,
                default_mode=req.default_mode,
                restore_meta=req.restore_meta,
            )
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/import/analyze")
    async def analyze_new_world_import(request: Request, file: UploadFile = File(...)):
        owner = _owner(request)
        try:
            raw = await file.read()
            return atlas_xlsx.analyze_import(owner, raw, world_id=None)
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/import")
    async def import_new_world_xlsx(
        request: Request,
        file: UploadFile = File(...),
        metadata: str = Form("{}"),
    ):
        owner = _owner(request)
        try:
            import json as _json
            meta = _json.loads(metadata or "{}")
            req = NewWorldImportBody(**meta)
            raw = await file.read()
            mappings = [m.model_dump() for m in req.mappings]
            return atlas_xlsx.import_world(
                owner, raw, mappings,
                world_id=None,
                world_name=req.world_name,
                world_description=req.world_description or "",
                default_mode=req.default_mode,
                restore_meta=req.restore_meta,
            )
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
            return atlas_canvas.save_layout(
                owner, world_id, body.nodes,
                clusters=body.clusters, query_nodes=body.query_nodes,
            )
        except Exception as e:
            _handle_err(e)

    # Queries
    @router.get("/api/atlas/worlds/{world_id}/queries")
    async def list_queries(request: Request, world_id: str):
        owner = _owner(request)
        try:
            return {"queries": atlas_queries.list_queries(owner, world_id)}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/queries")
    async def create_query(request: Request, world_id: str, body: QueryCreate):
        owner = _owner(request)
        try:
            return atlas_queries.create_query(
                owner, world_id, body.name, body.sql_text, description=body.description,
            )
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}/queries/{query_id}")
    async def update_query(request: Request, world_id: str, query_id: str, body: QueryUpdate):
        owner = _owner(request)
        try:
            return atlas_queries.update_query(
                owner, world_id, query_id,
                name=body.name, description=body.description, sql_text=body.sql_text,
            )
        except Exception as e:
            _handle_err(e)

    @router.delete("/api/atlas/worlds/{world_id}/queries/{query_id}")
    async def delete_query(request: Request, world_id: str, query_id: str):
        owner = _owner(request)
        try:
            atlas_queries.delete_query(owner, world_id, query_id)
            return {"ok": True}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/queries/{query_id}/find")
    async def find_query_results(request: Request, world_id: str, query_id: str, body: FilterBody):
        owner = _owner(request)
        try:
            result = atlas_queries.execute_query(
                owner, world_id, query_id,
                limit=body.limit, offset=body.offset,
            )
            return {
                "documents": result["documents"],
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            }
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/queries/{query_id}/schema")
    async def get_query_schema(request: Request, world_id: str, query_id: str):
        owner = _owner(request)
        try:
            return atlas_queries.get_query_schema(owner, world_id, query_id)
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/queries/validate")
    async def validate_query(request: Request, world_id: str, body: QueryValidateBody):
        owner = _owner(request)
        try:
            return atlas_queries.validate_sql_text(
                owner, world_id, body.sql_text,
                query_id=body.query_id, preview_limit=body.preview_limit,
            )
        except Exception as e:
            _handle_err(e)

    @router.get("/api/atlas/worlds/{world_id}/schema-catalog")
    async def schema_catalog(request: Request, world_id: str):
        owner = _owner(request)
        try:
            return atlas_sql_engine.get_world_catalog(owner, world_id)
        except Exception as e:
            _handle_err(e)

    # Clusters
    @router.get("/api/atlas/worlds/{world_id}/clusters")
    async def list_clusters(request: Request, world_id: str):
        owner = _owner(request)
        try:
            return {"clusters": atlas_clusters.list_clusters(owner, world_id)}
        except Exception as e:
            _handle_err(e)

    @router.post("/api/atlas/worlds/{world_id}/clusters")
    async def create_cluster(request: Request, world_id: str, body: ClusterCreate):
        owner = _owner(request)
        try:
            return atlas_clusters.create_cluster(
                owner, world_id,
                body.name,
                x=body.x, y=body.y, w=body.w, h=body.h,
                parent_cluster_id=body.parent_cluster_id,
                color=body.color,
                z_index=body.z_index,
                description=body.description,
            )
        except Exception as e:
            _handle_err(e)

    @router.put("/api/atlas/worlds/{world_id}/clusters/{cluster_id}")
    async def update_cluster(
        request: Request, world_id: str, cluster_id: str, body: ClusterUpdate,
    ):
        owner = _owner(request)
        try:
            return atlas_clusters.update_cluster(
                owner, world_id, cluster_id,
                **body.model_dump(exclude_unset=True),
            )
        except Exception as e:
            _handle_err(e)

    @router.delete("/api/atlas/worlds/{world_id}/clusters/{cluster_id}")
    async def delete_cluster(request: Request, world_id: str, cluster_id: str):
        owner = _owner(request)
        try:
            atlas_clusters.delete_cluster(owner, world_id, cluster_id)
            return {"ok": True}
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
                from_cardinality=body.from_cardinality,
                to_cardinality=body.to_cardinality,
                from_key_id=body.from_key_id,
                to_key_id=body.to_key_id,
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
