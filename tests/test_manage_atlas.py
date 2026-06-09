"""Tests for manage_atlas agent tool and Atlas services."""
import importlib.util
import json
import os
import sqlite3
import sys
import time
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
    _load_atlas_module("names", "names.py")
    entities_mod = _load_atlas_module("entities", "entities.py")
    documents_mod = _load_atlas_module("documents", "documents.py")
    rows_mod = _load_atlas_module("rows", "rows.py")
    csv_mod = _load_atlas_module("csv_io", "csv_io.py")
    clusters_mod = _load_atlas_module("clusters", "clusters.py")
    keys_mod = _load_atlas_module("keys", "keys.py")
    key_violations_mod = _load_atlas_module("key_violations", "key_violations.py")
    sql_engine_mod = _load_atlas_module("sql_engine", "sql_engine.py")
    queries_mod = _load_atlas_module("queries", "queries.py")
    rels_mod = _load_atlas_module("relationships", "relationships.py")
    canvas_mod = _load_atlas_module("canvas", "canvas.py")
    search_mod = _load_atlas_module("search", "search.py")

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
        "clusters": clusters_mod,
        "ddl": ddl,
        "search": search_mod,
        "keys": keys_mod,
        "key_violations": key_violations_mod,
        "sql_engine": sql_engine_mod,
        "queries": queries_mod,
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
async def test_import_merge_updates_existing(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    csv1 = "name,email\nAlice,a@x.com\nBob,b@x.com\n"
    stats = atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], csv1, mode="append")
    assert stats["rows_inserted"] == 2

    exported = atlas_env["csv"].export_csv(atlas_env["owner"], w["id"], e["id"])
    csv2 = exported.replace("a@x.com", "alice@x.com").rstrip() + "\nCarol,c@x.com\n"
    stats2 = atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], csv2, mode="merge")
    assert stats2["rows_updated"] >= 1
    assert stats2["rows_inserted"] >= 1
    assert atlas_env["documents"].count_documents(atlas_env["owner"], w["id"], e["id"]) == 3

    alice = atlas_env["documents"].find_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Alice"},
    )
    assert alice["email"] == "alice@x.com"


@pytest.mark.asyncio
async def test_import_rows_populates_field_registry(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    csv_text = "name,qty\nWidget,5\nGadget,10\n"
    atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], csv_text, mode="append")
    schema = atlas_env["documents"].get_entity_schema(atlas_env["owner"], w["id"], e["id"])
    slugs = {f["slug"] for f in schema["fields"]}
    assert "name" in slugs
    assert "qty" in slugs


@pytest.mark.asyncio
async def test_import_rows_bulk_performance(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Bulk")
    rows = ["name,value"] + [f"item{i},{i}" for i in range(200)]
    csv_text = "\n".join(rows) + "\n"
    start = time.perf_counter()
    stats = atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], csv_text, mode="append")
    elapsed = time.perf_counter() - start
    assert stats["rows_inserted"] == 200
    assert stats["rows_failed"] == 0
    assert elapsed < 2.0
    assert atlas_env["documents"].count_documents(atlas_env["owner"], w["id"], e["id"]) == 200


@pytest.mark.asyncio
async def test_insert_many_uses_bulk_path(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Docs")
    docs = [{"name": f"n{i}", "value": i} for i in range(50)]
    result = atlas_env["documents"].insert_many(atlas_env["owner"], w["id"], e["id"], docs)
    assert result["inserted_count"] == 50
    assert len(result["inserted_ids"]) == 50
    assert atlas_env["documents"].count_documents(atlas_env["owner"], w["id"], e["id"]) == 50


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
    assert rels[0]["from_cardinality"] == "one"
    assert rels[0]["to_cardinality"] == "many"


@pytest.mark.asyncio
async def test_relationship_cardinality_one_or_zero(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    a = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    b = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "B")
    r = atlas_env["relationships"].create_relationship(
        atlas_env["owner"], w["id"],
        a["id"], b["id"], "one_to_many", "", "",
        from_cardinality="one_or_zero", to_cardinality="many",
    )
    assert r["rel_type"] == "one_or_zero_to_many"
    assert r["from_cardinality"] == "one_or_zero"
    assert r["to_cardinality"] == "many"

    updated = atlas_env["relationships"].update_relationship(
        atlas_env["owner"], w["id"], r["id"],
        from_cardinality="one", to_cardinality="one_or_zero",
    )
    assert updated["rel_type"] == "one_to_one_or_zero"
    assert updated["from_cardinality"] == "one"
    assert updated["to_cardinality"] == "one_or_zero"


@pytest.mark.asyncio
async def test_relationship_invalid_cardinality(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    a = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    b = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "B")
    with pytest.raises(ValueError):
        atlas_env["relationships"].create_relationship(
            atlas_env["owner"], w["id"],
            a["id"], b["id"], "one_to_many", "", "",
            from_cardinality="invalid", to_cardinality="many",
        )
    r = atlas_env["relationships"].create_relationship(
        atlas_env["owner"], w["id"],
        a["id"], b["id"], "one_to_many", "", "",
    )
    with pytest.raises(ValueError):
        atlas_env["relationships"].update_relationship(
            atlas_env["owner"], w["id"], r["id"],
            rel_type="not_a_real_type",
        )


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
async def test_canvas_layout(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    atlas_env["canvas"].upsert_node(atlas_env["owner"], w["id"], e["id"], 100, 200)
    layout = atlas_env["canvas"].get_layout(atlas_env["owner"], w["id"])
    node = next(n for n in layout["nodes"] if n["entity_id"] == e["id"])
    assert node["x"] == 100
    assert node["y"] == 200
    assert layout["clusters"] == []


@pytest.mark.asyncio
async def test_cluster_crud_and_nested(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    outer = atlas_env["clusters"].create_cluster(
        atlas_env["owner"], w["id"], "Work", x=0, y=0, w=500, h=400,
    )
    inner = atlas_env["clusters"].create_cluster(
        atlas_env["owner"], w["id"], "Project X",
        x=50, y=50, w=200, h=150, parent_cluster_id=outer["id"],
    )
    listed = atlas_env["clusters"].list_clusters(atlas_env["owner"], w["id"])
    assert len(listed) == 2
    assert inner["parent_cluster_id"] == outer["id"]


@pytest.mark.asyncio
async def test_hit_test_cluster_innermost(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    outer = atlas_env["clusters"].create_cluster(
        atlas_env["owner"], w["id"], "Outer", x=0, y=0, w=400, h=300,
    )
    inner = atlas_env["clusters"].create_cluster(
        atlas_env["owner"], w["id"], "Inner",
        x=50, y=50, w=150, h=100, parent_cluster_id=outer["id"],
    )
    clusters = atlas_env["clusters"].list_clusters(atlas_env["owner"], w["id"])
    hit = atlas_env["clusters"].hit_test_cluster(100, 100, clusters)
    assert hit == inner["id"]


@pytest.mark.asyncio
async def test_canvas_cluster_roundtrip(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    c = atlas_env["clusters"].create_cluster(
        atlas_env["owner"], w["id"], "Personal", x=10, y=10,
    )
    atlas_env["canvas"].save_layout(
        atlas_env["owner"], w["id"],
        [{"entity_id": e["id"], "x": 40, "y": 40, "w": 200, "h": 120, "z_index": 0, "cluster_id": c["id"]}],
        clusters=[{**c, "x": 10, "y": 10, "w": 400, "h": 300, "collapsed": False}],
    )
    layout = atlas_env["canvas"].get_layout(atlas_env["owner"], w["id"])
    node = next(n for n in layout["nodes"] if n["entity_id"] == e["id"])
    assert node["cluster_id"] == c["id"]
    assert len(layout["clusters"]) == 1
    assert layout["clusters"][0]["name"] == "Personal"


@pytest.mark.asyncio
async def test_delete_entity(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    a = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    b = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "B")
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], a["id"], {"name": "test"})
    atlas_env["relationships"].create_relationship(
        atlas_env["owner"], w["id"],
        a["id"], b["id"], "one_to_many", "", "",
    )
    atlas_env["entities"].delete_entity(atlas_env["owner"], w["id"], a["id"])
    remaining = atlas_env["entities"].list_entities(atlas_env["owner"], w["id"])
    assert len(remaining) == 1
    assert remaining[0]["id"] == b["id"]
    rels = atlas_env["relationships"].list_relationships(atlas_env["owner"], w["id"])
    assert len(rels) == 0
    layout = atlas_env["canvas"].get_layout(atlas_env["owner"], w["id"])
    assert all(n["entity_id"] != a["id"] for n in layout["nodes"])


@pytest.mark.asyncio
async def test_delete_cluster_reparents(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    outer = atlas_env["clusters"].create_cluster(
        atlas_env["owner"], w["id"], "Outer", x=0, y=0, w=500, h=400,
    )
    inner = atlas_env["clusters"].create_cluster(
        atlas_env["owner"], w["id"], "Inner",
        x=50, y=50, w=200, h=150, parent_cluster_id=outer["id"],
    )
    atlas_env["clusters"].assign_entity_to_cluster(
        atlas_env["owner"], w["id"], e["id"], inner["id"],
    )
    atlas_env["clusters"].delete_cluster(atlas_env["owner"], w["id"], outer["id"])
    layout = atlas_env["canvas"].get_layout(atlas_env["owner"], w["id"])
    node = next(n for n in layout["nodes"] if n["entity_id"] == e["id"])
    assert node["cluster_id"] == inner["id"]
    remaining = atlas_env["clusters"].list_clusters(atlas_env["owner"], w["id"])
    assert len(remaining) == 1
    assert remaining[0]["id"] == inner["id"]
    assert remaining[0]["parent_cluster_id"] is None


@pytest.mark.asyncio
async def test_do_manage_atlas_clusters(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    r = await do_manage_atlas(json.dumps({
        "action": "create_world", "name": "Cluster World",
    }), owner=atlas_env["owner"])
    wid = r["world_id"]

    r2 = await do_manage_atlas(json.dumps({
        "action": "create_cluster", "world_id": wid, "name": "Work",
    }), owner=atlas_env["owner"])
    assert r2["exit_code"] == 0
    assert r2.get("cluster_id")

    r3 = await do_manage_atlas(json.dumps({
        "action": "create_entity", "world_id": wid, "name": "Orders",
    }), owner=atlas_env["owner"])

    r4 = await do_manage_atlas(json.dumps({
        "action": "assign_entity_to_cluster",
        "world_id": wid,
        "entity_name": "Orders",
        "cluster_name": "Work",
    }), owner=atlas_env["owner"])
    assert r4["exit_code"] == 0
    assert "Work" in r4.get("response", "")


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


@pytest.mark.asyncio
async def test_update_world_rename(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Alpha")
    updated = atlas_env["worlds"].update_world(atlas_env["owner"], w["id"], name="Beta")
    assert updated["name"] == "Beta"


@pytest.mark.asyncio
async def test_list_worlds_archived_filter(atlas_env):
    w1 = atlas_env["worlds"].create_world(atlas_env["owner"], "Active One")
    w2 = atlas_env["worlds"].create_world(atlas_env["owner"], "To Archive")
    atlas_env["worlds"].update_world(atlas_env["owner"], w2["id"], archived=True)
    active = atlas_env["worlds"].list_worlds(atlas_env["owner"], archived=False)
    archived = atlas_env["worlds"].list_worlds(atlas_env["owner"], archived=True)
    assert len(active) == 1
    assert active[0]["id"] == w1["id"]
    assert len(archived) == 1
    assert archived[0]["id"] == w2["id"]
    assert archived[0]["archived"] is True


@pytest.mark.asyncio
async def test_delete_world(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Doomed")
    db_file = w["db_path"]
    assert os.path.isfile(db_file)
    atlas_env["worlds"].delete_world(atlas_env["owner"], w["id"])
    assert not os.path.isfile(db_file)
    with pytest.raises(atlas_env["worlds"].AtlasNotFoundError):
        atlas_env["worlds"].get_world(atlas_env["owner"], w["id"])


def test_legacy_world_db_gets_v3_tables(atlas_env):
    """Opening a pre-v3 world DB adds atlas_clusters and cluster_id column."""
    wdb = sys.modules["services.atlas.world_db"]
    legacy_path = atlas_env["worlds_dir"] / "legacy.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE atlas_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO atlas_meta VALUES ('schema_version', '2');
        CREATE TABLE atlas_entities (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            table_name TEXT NOT NULL UNIQUE, row_count INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        );
        CREATE TABLE atlas_canvas_nodes (
            entity_id TEXT PRIMARY KEY, x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0,
            w REAL NOT NULL DEFAULT 200, h REAL NOT NULL DEFAULT 120, z_index INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.close()

    with wdb.open_world_db(str(legacy_path)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "atlas_clusters" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(atlas_canvas_nodes)").fetchall()}
        assert "cluster_id" in cols
        ver = conn.execute(
            "SELECT value FROM atlas_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert int(ver) == 6


def _tool_env_patch(atlas_env, monkeypatch):
    wdb = sys.modules["services.atlas.world_db"]
    monkeypatch.setattr(wdb, "ATLAS_WORLDS_DIR", str(atlas_env["worlds_dir"]))
    monkeypatch.setattr(
        wdb, "world_db_path", lambda wid: str(atlas_env["worlds_dir"] / f"{wid}.db")
    )


@pytest.mark.asyncio
async def test_resolve_world_by_name(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "CG-BMS")
    resolved = atlas_env["worlds"].resolve_world(atlas_env["owner"], world_id="CG-BMS")
    assert resolved["id"] == w["id"]


@pytest.mark.asyncio
async def test_resolve_world_by_prefix(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Prefix World")
    resolved = atlas_env["worlds"].resolve_world(atlas_env["owner"], world_id=w["id"][:8])
    assert resolved["id"] == w["id"]


@pytest.mark.asyncio
async def test_find_worlds_substring(atlas_env):
    atlas_env["worlds"].create_world(atlas_env["owner"], "CG-BMS")
    atlas_env["worlds"].create_world(atlas_env["owner"], "CG-BMS-Dev")
    matches = atlas_env["worlds"].find_worlds(atlas_env["owner"], "CG-BMS")
    assert len(matches) == 2
    assert matches[0]["name"] == "CG-BMS"


@pytest.mark.asyncio
async def test_resolve_entity_by_name(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    resolved = atlas_env["entities"].resolve_entity(
        atlas_env["owner"], w["id"], entity_name="customers"
    )
    assert resolved["id"] == e["id"]


@pytest.mark.asyncio
async def test_filter_contains_and_in(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "People")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Smith", "state": "NY"}
    )
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Jones", "state": "CA"}
    )
    found = atlas_env["documents"].find(
        atlas_env["owner"], w["id"], e["id"],
        filter_obj={"name": {"$contains": "smith"}},
    )
    assert found["total"] == 1
    found2 = atlas_env["documents"].find(
        atlas_env["owner"], w["id"], e["id"],
        filter_obj={"state": {"$in": ["NY", "CA"]}},
    )
    assert found2["total"] == 2


@pytest.mark.asyncio
async def test_search_world(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Notes")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"body": "battery management system"}
    )
    hits = atlas_env["search"].search_world(
        atlas_env["owner"], w["id"], "battery management", limit=5
    )
    assert len(hits) == 1
    assert hits[0]["entity_name"] == "Notes"


@pytest.mark.asyncio
async def test_do_manage_atlas_list_entities_by_world_name(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    w = atlas_env["worlds"].create_world(atlas_env["owner"], "CG-BMS")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")

    r = await do_manage_atlas(json.dumps({
        "action": "list_entities",
        "world_id": "CG-BMS",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert r["world_name"] == "CG-BMS"
    assert "Customers" in r["results"]
    assert "entity_id:" in r["results"]


@pytest.mark.asyncio
async def test_do_manage_atlas_describe_world(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    w = atlas_env["worlds"].create_world(atlas_env["owner"], "CG-BMS")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Orders")

    r = await do_manage_atlas(json.dumps({
        "action": "describe_world",
        "world_id": "CG-BMS",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert "Orders" in r["results"]
    assert r["world_id"] == w["id"]


@pytest.mark.asyncio
async def test_do_manage_atlas_find_compact_fields(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"],
        {"name": "Alice", "email": "a@x.com", "secret": "hidden"},
    )

    r = await do_manage_atlas(json.dumps({
        "action": "find",
        "world_id": w["id"],
        "entity_name": "Customers",
        "fields": ["name", "email"],
        "format": "compact",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert "name=Alice" in r["results"]
    assert "secret" not in r["results"]


@pytest.mark.asyncio
async def test_do_manage_atlas_create_relationship_by_name(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Orders")

    r = await do_manage_atlas(json.dumps({
        "action": "create_relationship",
        "world_id": w["id"],
        "from_entity_name": "Customers",
        "to_entity_name": "Orders",
        "from_field": "id",
        "to_field": "customer_id",
        "rel_type": "one_to_many",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert "Customers.id" in r["response"]


@pytest.mark.asyncio
async def test_do_manage_atlas_create_relationship_cardinality(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "B")

    r = await do_manage_atlas(json.dumps({
        "action": "create_relationship",
        "world_id": w["id"],
        "from_entity_name": "A",
        "to_entity_name": "B",
        "from_field": "id",
        "to_field": "a_id",
        "from_cardinality": "one_or_zero",
        "to_cardinality": "many",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    rel = atlas_env["relationships"].list_relationships(atlas_env["owner"], w["id"])[0]
    assert rel["rel_type"] == "one_or_zero_to_many"
    assert rel["from_cardinality"] == "one_or_zero"
    assert rel["to_cardinality"] == "many"


@pytest.mark.asyncio
async def test_do_manage_atlas_default_world_flag(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Only World")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")

    r = await do_manage_atlas(json.dumps({
        "action": "countDocuments",
        "entity_name": "Items",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert r.get("_used_default_world") is True
    assert r["world_name"] == "Only World"


@pytest.mark.asyncio
async def test_do_manage_atlas_find_world(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas

    atlas_env["worlds"].create_world(atlas_env["owner"], "CG-BMS")

    r = await do_manage_atlas(json.dumps({
        "action": "find_world",
        "name": "CG-BMS",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert "world_id:" in r["results"]
    assert "CG-BMS" in r["results"]


@pytest.mark.asyncio
async def test_list_entities_summary_default_no_fields(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Alice", "qty": 5},
    )
    entities = atlas_env["entities"].list_entities(atlas_env["owner"], w["id"])
    assert entities[0]["fields"] == []
    summary = atlas_env["entities"].entity_summary(entities[0])
    assert set(summary.keys()) == {"id", "name", "description", "row_count"}


@pytest.mark.asyncio
async def test_list_entities_include_fields(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Alice"},
    )
    entities = atlas_env["entities"].list_entities(
        atlas_env["owner"], w["id"], include_fields=True,
    )
    slugs = {f["slug"] for f in entities[0]["fields"]}
    assert "name" in slugs


@pytest.mark.asyncio
async def test_do_manage_atlas_list_entities_summary_output(atlas_env, monkeypatch):
    _tool_env_patch(atlas_env, monkeypatch)
    from src.tool_implementations import do_manage_atlas
    from src.tool_execution import format_tool_result

    w = atlas_env["worlds"].create_world(atlas_env["owner"], "CG-BMS")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Alice", "email": "a@x.com"},
    )

    r = await do_manage_atlas(json.dumps({
        "action": "list_entities",
        "world_id": "CG-BMS",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert r["entities"] == [{
        "id": e["id"],
        "name": "Customers",
        "description": "",
        "row_count": 1,
    }]
    assert "nullable_ratio" not in r["results"]
    formatted = format_tool_result("manage_atlas", r)
    assert "**data:**" not in formatted
    assert len(formatted) < 500


@pytest.mark.asyncio
async def test_app_api_blocks_atlas(monkeypatch):
    from src.tool_implementations import do_app_api

    r = await do_app_api(json.dumps({
        "action": "call",
        "method": "GET",
        "path": "/api/atlas/worlds/abc/entities",
    }), owner="testuser")
    assert r["exit_code"] == 1
    assert "manage_atlas" in r["error"]
    assert "not separate tools" in r["error"].lower() or "actions inside" in r["error"].lower()


@pytest.mark.asyncio
async def test_get_schema_sparse_filter(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Products")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"sku": "A1", "noise": None},
    )
    schema = atlas_env["documents"].get_entity_schema(
        atlas_env["owner"], w["id"], e["id"], include_sparse=False, include_stats=True,
    )
    slugs = {f["slug"] for f in schema["fields"]}
    assert "sku" in slugs
    assert "noise" not in slugs
    sku_field = next(f for f in schema["fields"] if f["slug"] == "sku")
    assert sku_field["nullable_ratio"] == 0.0


def test_legacy_world_db_gets_v4_tables(atlas_env):
    """Opening a pre-v4 world DB adds keys, queries, and relationship key columns."""
    wdb = sys.modules["services.atlas.world_db"]
    legacy_path = atlas_env["worlds_dir"] / "legacy-v4.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE atlas_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO atlas_meta VALUES ('schema_version', '3');
        CREATE TABLE atlas_entities (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            table_name TEXT NOT NULL UNIQUE, row_count INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        );
        CREATE TABLE atlas_relationships (
            id TEXT PRIMARY KEY, from_entity_id TEXT NOT NULL, to_entity_id TEXT NOT NULL,
            rel_type TEXT NOT NULL, from_field TEXT NOT NULL, to_field TEXT NOT NULL,
            label TEXT DEFAULT '', from_anchor TEXT DEFAULT 'right', to_anchor TEXT DEFAULT 'left',
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
        assert "atlas_entity_keys" in tables
        assert "atlas_queries" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(atlas_relationships)").fetchall()}
        assert "from_key_id" in cols
        assert "to_key_id" in cols
        ver = conn.execute(
            "SELECT value FROM atlas_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert int(ver) == 6


def test_partial_v5_world_repairs_relationship_key_columns(atlas_env):
    """schema_version 5 but missing key columns still gets repaired on open."""
    wdb = sys.modules["services.atlas.world_db"]
    legacy_path = atlas_env["worlds_dir"] / "partial-v5.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE atlas_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO atlas_meta VALUES ('schema_version', '5');
        CREATE TABLE atlas_entities (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
            table_name TEXT NOT NULL UNIQUE, row_count INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        );
        CREATE TABLE atlas_entity_keys (
            id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, name TEXT NOT NULL,
            field_slugs TEXT NOT NULL DEFAULT '[]',
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        );
        CREATE TABLE atlas_relationships (
            id TEXT PRIMARY KEY, from_entity_id TEXT NOT NULL, to_entity_id TEXT NOT NULL,
            rel_type TEXT NOT NULL, from_field TEXT NOT NULL, to_field TEXT NOT NULL,
            label TEXT DEFAULT '', from_anchor TEXT DEFAULT 'right', to_anchor TEXT DEFAULT 'left',
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        );
    """)
    conn.close()

    with wdb.open_world_db(str(legacy_path)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(atlas_relationships)").fetchall()}
        assert "from_key_id" in cols
        assert "to_key_id" in cols


@pytest.mark.asyncio
async def test_keys_crud_and_violations(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Keys")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"sku": "A1"})
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"sku": "A1"})
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"sku": "B2"})

    key = atlas_env["keys"].create_key(
        atlas_env["owner"], w["id"], e["id"], "sku_key", ["sku"],
    )
    assert key["name"] == "sku_key"

    schema = atlas_env["documents"].get_entity_schema(atlas_env["owner"], w["id"], e["id"])
    assert any(k["id"] == key["id"] for k in schema.get("keys", []))

    n = atlas_env["key_violations"].count_key_violations(
        atlas_env["owner"], w["id"], e["id"], key["id"],
    )
    assert n == 2

    result = atlas_env["documents"].find(
        atlas_env["owner"], w["id"], e["id"],
        filter_obj={"$keyViolation": key["id"]},
    )
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_key_violations_with_display_key_name(atlas_env):
    """Document keys that slugify differently must still detect duplicates."""
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "DisplayKeys")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Parts")
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"Part Number": "A1"})
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"Part Number": "A1"})
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], e["id"], {"Part Number": "B2"})

    schema = atlas_env["documents"].get_entity_schema(atlas_env["owner"], w["id"], e["id"])
    part_field = next(f for f in schema["fields"] if f["slug"] == "part_number")
    assert part_field["sample_key"] == "Part Number"

    key = atlas_env["keys"].create_key(
        atlas_env["owner"], w["id"], e["id"], "part_key", ["part_number"],
    )
    n = atlas_env["key_violations"].count_key_violations(
        atlas_env["owner"], w["id"], e["id"], key["id"],
    )
    assert n == 2

    result = atlas_env["documents"].find(
        atlas_env["owner"], w["id"], e["id"],
        filter_obj={"$keyViolation": key["id"]},
    )
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_innate_id_key_on_empty_collection(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Innate")
    a = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    b = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "B")

    keys_a = atlas_env["keys"].list_keys(atlas_env["owner"], w["id"], a["id"])
    innate_a = next(k for k in keys_a if k.get("innate"))
    assert innate_a["name"] == "_id"
    assert innate_a["field_slugs"] == ["_id"]

    rel = atlas_env["relationships"].create_relationship(
        atlas_env["owner"], w["id"],
        a["id"], b["id"], "one_to_many",
        from_key_id=innate_a["id"],
        to_key_id=atlas_env["keys"].innate_key_id(b["id"]),
    )
    assert rel["from_key"]["name"] == "_id"
    assert rel["to_key"]["name"] == "_id"

    n = atlas_env["key_violations"].count_key_violations(
        atlas_env["owner"], w["id"], a["id"], innate_a["id"],
    )
    assert n == 0

    with pytest.raises(ValueError, match="cannot be deleted"):
        atlas_env["keys"].delete_key(
            atlas_env["owner"], w["id"], a["id"], innate_a["id"],
        )


@pytest.mark.asyncio
async def test_key_based_relationship(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Rels")
    a = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "A")
    b = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "B")
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], a["id"], {"id": 1})
    atlas_env["documents"].insert_one(atlas_env["owner"], w["id"], b["id"], {"ref": 1})
    ka = atlas_env["keys"].create_key(atlas_env["owner"], w["id"], a["id"], "pk", ["id"])
    kb = atlas_env["keys"].create_key(atlas_env["owner"], w["id"], b["id"], "fk", ["ref"])
    rel = atlas_env["relationships"].create_relationship(
        atlas_env["owner"], w["id"],
        a["id"], b["id"], "one_to_many",
        from_key_id=ka["id"], to_key_id=kb["id"],
    )
    assert rel["from_key"]["name"] == "pk"
    assert rel["to_key"]["name"] == "fk"


@pytest.mark.asyncio
async def test_sql_validate_incomplete_query(atlas_env):
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Validate")
    result = atlas_env["queries"].validate_sql_text(
        atlas_env["owner"], w["id"], "SELECT * FROM ",
    )
    assert result["valid"] is False
    assert "parse error" in result["error"].lower()


@pytest.mark.asyncio
async def test_sql_query_execute(atlas_env):
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "SQL")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Alice", "status": "active"},
    )
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Bob", "status": "inactive"},
    )
    q = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Active",
        "SELECT name FROM Customers WHERE status = 'active'",
    )
    result = atlas_env["queries"].execute_query(atlas_env["owner"], w["id"], q["id"])
    assert result["total"] == 1
    assert result["documents"][0]["name"] == "Alice"
    assert len(q["dependencies"]) == 1
    assert q["dependencies"][0]["source_type"] == "entity"


@pytest.mark.asyncio
async def test_sql_query_execute_original_document_keys(atlas_env):
    """Documents may store original keys while field slugs differ."""
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "SQLKeys")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Products")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"],
        {"Part Number": "ABC-123", "Deal ID": 42},
    )
    q = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "AllProducts",
        "SELECT * FROM Products",
    )
    result = atlas_env["queries"].execute_query(atlas_env["owner"], w["id"], q["id"])
    assert result["total"] == 1
    doc = result["documents"][0]
    assert doc["part_number"] == "ABC-123"
    assert doc["deal_id"] == 42

    preview = atlas_env["queries"].validate_sql_text(
        atlas_env["owner"], w["id"], "SELECT * FROM Products", preview_limit=10,
    )
    assert preview["valid"] is True
    assert preview["preview"]["documents"][0]["part_number"] == "ABC-123"


@pytest.mark.asyncio
async def test_sql_query_special_column_names(atlas_env):
    """Columns with spaces/symbols resolve via original document keys."""
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "SQLSpecial")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Parts")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"],
        {"Part #": "X-100", "Deal ID": 7},
    )
    result = atlas_env["queries"].validate_sql_text(
        atlas_env["owner"], w["id"],
        "SELECT b.`Part #`, b.`Deal ID` FROM Parts AS b",
        preview_limit=10,
    )
    assert result["valid"] is True, result.get("error")
    doc = result["preview"]["documents"][0]
    assert doc["part"] == "X-100"
    assert doc["deal_id"] == 7


@pytest.mark.asyncio
async def test_canvas_query_nodes_roundtrip(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Canvas")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "E1")
    pytest.importorskip("sqlglot")
    q = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Q1", "SELECT * FROM E1",
    )
    layout = atlas_env["canvas"].save_layout(
        atlas_env["owner"], w["id"],
        nodes=[], query_nodes=[{
            "query_id": q["id"], "x": 10, "y": 20, "w": 200, "h": 120,
        }],
    )
    assert len(layout["query_nodes"]) == 1
    assert layout["query_nodes"][0]["query_id"] == q["id"]


@pytest.mark.asyncio
async def test_sql_macro_query_join_table(atlas_env):
    """$('Name') references a saved query joined with a collection."""
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "MacroJoin")
    missing = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "SIT - Missing Part Numbers on our Products",
    )
    products = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "SIT_Siebel_BRM_Products",
    )
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], missing["id"],
        {"product_name": "Widget", "part_number": "PN-1"},
    )
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], products["id"],
        {"name": "Widget", "part": "PART-A"},
    )
    base_q = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Missing Parts",
        'SELECT product_name, part_number FROM $("SIT - Missing Part Numbers on our Products")',
    )
    join_q = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Joined",
        'SELECT x.part_number, y.part FROM $("Missing Parts") x '
        'JOIN SIT_Siebel_BRM_Products y ON x.product_name = y.name',
    )
    result = atlas_env["queries"].execute_query(atlas_env["owner"], w["id"], join_q["id"])
    assert result["total"] == 1
    assert result["documents"][0]["part_number"] == "PN-1"
    assert result["documents"][0]["part"] == "PART-A"
    assert len(base_q["dependencies"]) == 1


@pytest.mark.asyncio
async def test_sql_macro_query_on_query(atlas_env):
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "MacroChain")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Items")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"name": "Alpha", "qty": 3},
    )
    q1 = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Active Items",
        "SELECT name, qty FROM Items WHERE qty > 0",
    )
    q2 = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Doubled",
        'SELECT name, qty * 2 AS doubled FROM $("Active Items")',
    )
    result = atlas_env["queries"].execute_query(atlas_env["owner"], w["id"], q2["id"])
    assert result["total"] == 1
    assert result["documents"][0]["doubled"] == 6
    assert q2["dependencies"][0]["source_id"] == q1["id"]


@pytest.mark.asyncio
async def test_query_rename_propagates_to_dependents(atlas_env):
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "RenameQ")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Src")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"val": 1},
    )
    q_a = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Query A", "SELECT val FROM Src",
    )
    q_b = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Query B",
        'SELECT val FROM $("Query A") UNION SELECT val FROM `Query A`',
    )
    atlas_env["queries"].update_query(
        atlas_env["owner"], w["id"], q_a["id"], name="Query Alpha",
    )
    updated_b = atlas_env["queries"].get_query(atlas_env["owner"], w["id"], q_b["id"])
    assert '$("Query Alpha")' in updated_b["sql_text"]
    assert "`Query Alpha`" in updated_b["sql_text"]
    result = atlas_env["queries"].execute_query(atlas_env["owner"], w["id"], q_b["id"])
    assert result["total"] == 1
    assert result["documents"][0]["val"] == 1


@pytest.mark.asyncio
async def test_entity_rename_propagates_to_dependents(atlas_env):
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "RenameE")
    e = atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "OldName")
    atlas_env["documents"].insert_one(
        atlas_env["owner"], w["id"], e["id"], {"x": 9},
    )
    q = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Uses Entity",
        'SELECT x FROM $("OldName") UNION SELECT x FROM OldName',
    )
    atlas_env["entities"].update_entity(
        atlas_env["owner"], w["id"], e["id"], name="NewName",
    )
    updated_q = atlas_env["queries"].get_query(atlas_env["owner"], w["id"], q["id"])
    assert '$("NewName")' in updated_q["sql_text"]
    assert "FROM NewName" in updated_q["sql_text"]
    result = atlas_env["queries"].execute_query(atlas_env["owner"], w["id"], q["id"])
    assert result["total"] == 1
    assert result["documents"][0]["x"] == 9


@pytest.mark.asyncio
async def test_atlas_name_uniqueness_cross_type(atlas_env):
    pytest.importorskip("sqlglot")
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Unique")
    atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "Customers")
    with pytest.raises(ValueError, match="already used by collection"):
        atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "customers")
    with pytest.raises(ValueError, match="already used by collection"):
        atlas_env["queries"].create_query(
            atlas_env["owner"], w["id"], "Customers", "SELECT 1",
        )
    q = atlas_env["queries"].create_query(
        atlas_env["owner"], w["id"], "Active", "SELECT 1",
    )
    with pytest.raises(ValueError, match="already used by query"):
        atlas_env["entities"].create_entity(atlas_env["owner"], w["id"], "active")
    with pytest.raises(ValueError, match="already used by collection"):
        atlas_env["queries"].update_query(
            atlas_env["owner"], w["id"], q["id"], name="Customers",
        )
