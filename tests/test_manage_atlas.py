"""Tests for manage_atlas agent tool and Atlas services."""
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _ensure_pkg(name: str) -> None:
    if name not in sys.modules:
        sys.modules[name] = ModuleType(name)


def _load_atlas_module(module_name: str, filename: str):
    full = f"services.atlas.{module_name}"
    _ensure_pkg("services")
    _ensure_pkg("services.atlas")
    path = ROOT / "services" / "atlas" / filename
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    setattr(sys.modules["services.atlas"], module_name, mod)
    return mod


def _clear_atlas_modules() -> None:
    for key in list(sys.modules):
        if key == "services.atlas" or key.startswith("services.atlas."):
            del sys.modules[key]


@pytest.fixture()
def atlas_env(tmp_path, monkeypatch):
    """Isolated app.db + atlas worlds directory."""
    _clear_atlas_modules()

    db_path = tmp_path / "test_app.db"
    worlds_dir = tmp_path / "atlas" / "worlds"
    worlds_dir.mkdir(parents=True)

    import core.database as cdb
    from core.database import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    monkeypatch.setattr(cdb, "engine", engine)
    monkeypatch.setattr(cdb, "SessionLocal", TestSession)

    wdb = _load_atlas_module("world_db", "world_db.py")
    monkeypatch.setattr(wdb, "ATLAS_WORLDS_DIR", str(worlds_dir))
    monkeypatch.setattr(wdb, "world_db_path", lambda wid: str(worlds_dir / f"{wid}.db"))

    ddl = _load_atlas_module("ddl", "ddl.py")
    _load_atlas_module("fields", "fields.py")
    _load_atlas_module("query", "query.py")
    worlds_mod = _load_atlas_module("worlds", "worlds.py")
    entities_mod = _load_atlas_module("entities", "entities.py")
    documents_mod = _load_atlas_module("documents", "documents.py")
    rows_mod = _load_atlas_module("rows", "rows.py")
    csv_mod = _load_atlas_module("csv_io", "csv_io.py")
    canvas_mod = _load_atlas_module("canvas", "canvas.py")
    rels_mod = _load_atlas_module("relationships", "relationships.py")

    yield {
        "owner": "testuser",
        "worlds_dir": worlds_dir,
        "worlds": worlds_mod,
        "entities": entities_mod,
        "documents": documents_mod,
        "rows": rows_mod,
        "csv": csv_mod,
        "canvas": canvas_mod,
        "relationships": rels_mod,
        "ddl": ddl,
    }


@pytest.mark.asyncio
async def test_resolve_default_world_creates_my_world(atlas_env):
    w = atlas_env["worlds"].resolve_default_world(atlas_env["owner"])
    assert w["name"] == "My World"
    assert len(atlas_env["worlds"].list_worlds(atlas_env["owner"])) == 1
    assert os.path.isfile(os.path.join(atlas_env["worlds_dir"], f"{w['id']}.db"))


@pytest.mark.asyncio
async def test_create_entity_json_table(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    db_file = w["db_path"]
    conn = sqlite3.connect(db_file)
    info = conn.execute(f"PRAGMA table_info({e['table_name']})").fetchall()
    conn.close()
    cols = {r[1] for r in info}
    assert "data" in cols
    assert "_atlas_row_id" in cols


@pytest.mark.asyncio
async def test_insert_and_find(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    r = atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Alice", "qty": 5}
    )
    assert r["inserted_id"] > 0
    found = atlas_env["documents"].find(
        atlas_env["owner"], w["id"], e["id"], filter_obj={"name": "Alice"}
    )
    assert found["total"] == 1
    assert found["documents"][0]["name"] == "Alice"
    assert found["documents"][0]["_id"] == r["inserted_id"]


@pytest.mark.asyncio
async def test_update_many(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"region": "EU", "x": 1})
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"region": "EU", "x": 2})
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"region": "US", "x": 3})
    r = atlas_env["documents"].update_many(
        atlas_env["owner"], w["id"], e["id"],
        {"region": "EU"}, {"$set": {"currency": "EUR"}},
    )
    assert r["matched_count"] == 2
    assert r["modified_count"] == 2


@pytest.mark.asyncio
async def test_delete_one_and_count(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Nums")
    r = atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"n": 1})
    assert atlas_env["documents"].count_documents(atlas_env["owner"], w["id"], e["id"]) == 1
    atlas_env["documents"].delete_one(atlas_env["owner"], w["id"], e["id"], {"_id": r["inserted_id"]})
    assert atlas_env["documents"].count_documents(atlas_env["owner"], w["id"], e["id"]) == 0


@pytest.mark.asyncio
async def test_get_schema_sample(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Products")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"sku": "A1", "price": 9.99}
    )
    schema = atlas_env["documents"].get_entity_schema(atlas_env["owner"], w["id"], e["id"])
    assert schema["document_count"] == 1
    assert schema["sample_document"]["sku"] == "A1"
    slugs = {f["slug"] for f in schema["fields"]}
    assert "sku" in slugs


@pytest.mark.asyncio
async def test_legacy_update_row_alias(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    r = atlas_env["rows"].add_row(atlas_env["owner"], w["id"], e["id"], {"qty": 5})
    atlas_env["rows"].update_row(atlas_env["owner"], w["id"], e["id"], r["row_id"], {"qty": 10})
    doc = atlas_env["documents"].find_one(
        atlas_env["owner"], w["id"], e["id"], {"_id": r["row_id"]}
    )
    assert doc["qty"] == 10


@pytest.mark.asyncio
async def test_import_merge(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    csv1 = "name,email\nAlice,a@x.com\nBob,b@x.com\n"
    atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], csv1, mode="append")
    assert atlas_env["documents"].count_documents(atlas_env["owner"], w["id"], e["id"]) == 2


@pytest.mark.asyncio
async def test_owner_isolation(atlas_env):
    w = atlas_env["worlds"].create_world("alice", "Alice World")
    with pytest.raises(atlas_env["worlds"].AtlasAccessError):
        atlas_env["worlds"].get_world("bob", w["id"])


@pytest.mark.asyncio
async def test_update_entity_name_description(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "Customers", description="Initial",
    )
    updated = atlas_env["entities"].update_entity(
        atlas_env["owner"], w["id"], e["id"],
        name="Clients", description="Renamed collection",
    )
    assert updated["name"] == "Clients"
    assert updated["description"] == "Renamed collection"


@pytest.mark.asyncio
async def test_relationship_optional_fields(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    a = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    b = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "B")
    r = atlas_env["relationships"].create_relationship(
        atlas_env["owner"], w["id"],
        a["id"], b["id"], "one_to_many", "", "",
        from_anchor="e", to_anchor="w",
    )
    assert r["from_field"] == ""
    assert r["to_field"] == ""
    assert r["from_anchor"] == "e"


@pytest.mark.asyncio
async def test_relationship_crud(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    a = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    b = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Orders")
    r = atlas_env["relationships"].create_relationship(
        atlas_env["owner"], w["id"],
        a["id"], b["id"], "one_to_many", "id", "customer_id",
    )
    rels = atlas_env["relationships"].list_relationships(atlas_env["owner"], w["id"])
    assert len(rels) == 1
    assert rels[0]["id"] == r["id"]


@pytest.mark.asyncio
async def test_canvas_layout(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    atlas_env["canvas"].upsert_node(atlas_env["owner"], w["id"], e["id"], 100, 200)
    layout = atlas_env["canvas"].get_layout(atlas_env["owner"], w["id"])
    node = next(n for n in layout["nodes"] if n["entity_id"] == e["id"])
    assert node["x"] == 100
    assert node["y"] == 200


@pytest.mark.asyncio
async def test_delete_many_requires_confirm(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "X")
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"a": 1})
    with pytest.raises(ValueError, match="confirm"):
        atlas_env["documents"].delete_many(atlas_env["owner"], w["id"], e["id"], {})


@pytest.mark.asyncio
async def test_do_manage_atlas_insert_one(atlas_env, monkeypatch):
    wdb = sys.modules["services.atlas.world_db"]
    monkeypatch.setattr(wdb, "ATLAS_WORLDS_DIR", str(atlas_env["worlds_dir"]))
    monkeypatch.setattr(
        wdb, "world_db_path", lambda wid: str(atlas_env["worlds_dir"] / f"{wid}.db")
    )
    from src.tool_implementations import do_manage_atlas

    r = await do_manage_atlas(json.dumps({
        "action": "create_world", "name": "Agent World",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0

    r2 = await do_manage_atlas(json.dumps({
        "action": "create_entity",
        "world_id": r["world_id"],
        "name": "Customers",
    }), owner=atlas_env["owner"])
    assert r2["exit_code"] == 0

    r3 = await do_manage_atlas(json.dumps({
        "action": "insertOne",
        "world_id": r["world_id"],
        "entity_id": r2["entity_id"],
        "document": {"name": "Carol"},
    }), owner=atlas_env["owner"])
    assert r3["exit_code"] == 0
    assert r3.get("inserted_id")


def test_legacy_world_db_gets_v2_tables(atlas_env):
    """Opening a pre-v2 world DB adds atlas_fields and related tables."""
    wdb = sys.modules["services.atlas.world_db"]
    legacy_path = atlas_env["worlds_dir"] / "legacy.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE atlas_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO atlas_meta VALUES ('schema_version', '1');
        CREATE TABLE atlas_entities (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            table_name TEXT NOT NULL UNIQUE, row_count INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        );
    """)
    conn.close()

    with wdb.open_world_db(str(legacy_path)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "atlas_fields" in tables
        assert "atlas_canvas_nodes" in tables
        assert "atlas_relationships" in tables
        ver = conn.execute(
            "SELECT value FROM atlas_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert int(ver) == 2
