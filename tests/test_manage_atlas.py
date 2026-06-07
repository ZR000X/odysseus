"""Tests for manage_atlas agent tool and Atlas services."""
import importlib.util
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
    worlds_mod = _load_atlas_module("worlds", "worlds.py")
    entities_mod = _load_atlas_module("entities", "entities.py")
    rows_mod = _load_atlas_module("rows", "rows.py")
    csv_mod = _load_atlas_module("csv_io", "csv_io.py")

    yield {
        "owner": "testuser",
        "worlds_dir": worlds_dir,
        "worlds": worlds_mod,
        "entities": entities_mod,
        "rows": rows_mod,
        "csv": csv_mod,
        "ddl": ddl,
    }


@pytest.mark.asyncio
async def test_resolve_default_world_creates_my_world(atlas_env):
    w = atlas_env["worlds"].resolve_default_world(atlas_env["owner"])
    assert w["name"] == "My World"
    assert len(atlas_env["worlds"].list_worlds(atlas_env["owner"])) == 1
    assert os.path.isfile(os.path.join(atlas_env["worlds_dir"], f"{w['id']}.db"))


@pytest.mark.asyncio
async def test_create_entity_creates_physical_table(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "Customers",
        attributes=[
            {"name": "id", "type": "text", "primary_key": True},
            {"name": "name", "type": "text"},
        ],
    )
    db_file = w["db_path"]
    conn = sqlite3.connect(db_file)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (e["table_name"],)
    ).fetchall()]
    conn.close()
    assert e["table_name"] in tables


@pytest.mark.asyncio
async def test_row_crud_roundtrip(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "Items",
        attributes=[{"name": "id", "type": "text", "primary_key": True}, {"name": "qty", "type": "integer"}],
    )
    r = atlas_env["rows"].add_row(atlas_env["owner"], w["id"], e["id"], {"id": "a1", "qty": 5})
    assert r["row_id"] > 0
    assert atlas_env["rows"].count_rows(atlas_env["owner"], w["id"], e["id"]) == 1
    listed = atlas_env["rows"].list_rows(atlas_env["owner"], w["id"], e["id"])
    assert listed["rows"][0]["id"] == "a1"
    atlas_env["rows"].update_row(atlas_env["owner"], w["id"], e["id"], r["row_id"], {"qty": 10})
    listed2 = atlas_env["rows"].list_rows(atlas_env["owner"], w["id"], e["id"])
    assert listed2["rows"][0]["qty"] == 10
    atlas_env["rows"].delete_row(atlas_env["owner"], w["id"], e["id"], r["row_id"])
    assert atlas_env["rows"].count_rows(atlas_env["owner"], w["id"], e["id"]) == 0


@pytest.mark.asyncio
async def test_import_merge_upserts_on_pk(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "Customers",
        attributes=[{"name": "id", "type": "text", "primary_key": True}, {"name": "name", "type": "text"}],
    )
    csv1 = "id,name\n1,Alice\n2,Bob\n"
    atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], csv1, mode="append")
    assert atlas_env["rows"].count_rows(atlas_env["owner"], w["id"], e["id"]) == 2
    csv2 = "id,name\n1,Alice Updated\n3,Carol\n"
    stats = atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], csv2, mode="merge")
    assert stats["rows_updated"] >= 1
    assert atlas_env["rows"].count_rows(atlas_env["owner"], w["id"], e["id"]) == 3
    rows = atlas_env["rows"].list_rows(atlas_env["owner"], w["id"], e["id"], limit=10)
    names = {r["id"]: r["name"] for r in rows["rows"]}
    assert names["1"] == "Alice Updated"


@pytest.mark.asyncio
async def test_import_replace_truncates(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "Items",
        attributes=[{"name": "id", "type": "text", "primary_key": True}],
    )
    atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], "id\n1\n2\n3\n", mode="append")
    atlas_env["csv"].import_rows(atlas_env["owner"], w["id"], e["id"], "id\n9\n", mode="replace")
    assert atlas_env["rows"].count_rows(atlas_env["owner"], w["id"], e["id"]) == 1


@pytest.mark.asyncio
async def test_owner_isolation(atlas_env):
    w = atlas_env["worlds"].create_world("alice", "Alice World")
    with pytest.raises(atlas_env["worlds"].AtlasAccessError):
        atlas_env["worlds"].get_world("bob", w["id"])


@pytest.mark.asyncio
async def test_list_rows_limit_cap(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "Nums",
        attributes=[{"name": "n", "type": "integer"}],
    )
    for i in range(30):
        atlas_env["rows"].add_row(atlas_env["owner"], w["id"], e["id"], {"n": i})
    result2 = atlas_env["rows"].list_rows(atlas_env["owner"], w["id"], e["id"], limit=5)
    assert len(result2["rows"]) == 5


def test_reserved_slug_rejected(atlas_env):
    with pytest.raises(ValueError):
        atlas_env["ddl"].slugify("rowid")


@pytest.mark.asyncio
async def test_export_csv_headers(atlas_env):
    w = atlas_env["worlds"].create_world(atlas_env["owner"], "Test")
    e = atlas_env["entities"].create_entity(
        atlas_env["owner"], w["id"], "Products",
        attributes=[{"name": "sku", "type": "text"}, {"name": "price", "type": "real"}],
    )
    text = atlas_env["csv"].export_csv(atlas_env["owner"], w["id"], e["id"])
    header = text.splitlines()[0]
    assert "_atlas_row_id" in header
    assert "sku" in header
    assert "price" in header


@pytest.mark.asyncio
async def test_do_manage_atlas_create_entity(atlas_env, monkeypatch):
    import json

    wdb = sys.modules["services.atlas.world_db"]
    monkeypatch.setattr(wdb, "ATLAS_WORLDS_DIR", str(atlas_env["worlds_dir"]))
    monkeypatch.setattr(
        wdb,
        "world_db_path",
        lambda wid: str(atlas_env["worlds_dir"] / f"{wid}.db"),
    )

    from src.tool_implementations import do_manage_atlas

    r = await do_manage_atlas(json.dumps({
        "action": "create_world",
        "name": "Agent World",
    }), owner=atlas_env["owner"])
    assert r["exit_code"] == 0
    assert r.get("world_id")

    r2 = await do_manage_atlas(json.dumps({
        "action": "create_entity",
        "world_id": r["world_id"],
        "name": "Customers",
        "attributes": [{"name": "id", "type": "text", "primary_key": True}],
    }), owner=atlas_env["owner"])
    assert r2["exit_code"] == 0
    assert r2.get("entity_id")
