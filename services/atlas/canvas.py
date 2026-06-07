"""Atlas world canvas layout persistence."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.atlas.entities import list_entities
from services.atlas.world_db import open_world_db
from services.atlas.worlds import get_world

DEFAULT_W = 200
DEFAULT_H = 120


def _default_layout(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes = []
    cols = 3
    for i, e in enumerate(entities):
        col = i % cols
        row = i // cols
        nodes.append({
            "entity_id": e["id"],
            "x": 80 + col * 280,
            "y": 80 + row * 180,
            "w": DEFAULT_W,
            "h": DEFAULT_H,
            "z_index": 0,
            "name": e["name"],
            "row_count": e["row_count"],
        })
    return nodes


def get_layout(owner: Optional[str], world_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    entities = list_entities(owner, world_id)
    entity_map = {e["id"]: e for e in entities}
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute("SELECT * FROM atlas_canvas_nodes").fetchall()
    saved = {r["entity_id"]: dict(r) for r in rows}
    nodes = []
    for e in entities:
        if e["id"] in saved:
            n = saved[e["id"]]
            nodes.append({
                "entity_id": e["id"],
                "x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"],
                "z_index": n["z_index"],
                "name": e["name"],
                "row_count": e["row_count"],
            })
    placed_ids = {n["entity_id"] for n in nodes}
    missing = [e for e in entities if e["id"] not in placed_ids]
    if missing:
        defaults = _default_layout(missing)
        for i, d in enumerate(defaults):
            d["x"] += len(nodes) * 20
            nodes.append(d)
    elif not nodes:
        nodes = _default_layout(entities)
    return {"nodes": nodes}


def upsert_node(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    x: float,
    y: float,
    w: float = DEFAULT_W,
    h: float = DEFAULT_H,
    z_index: int = 0,
) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        conn.execute(
            """INSERT INTO atlas_canvas_nodes (entity_id, x, y, w, h, z_index)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET
                 x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h, z_index=excluded.z_index""",
            (entity_id, x, y, w, h, z_index),
        )
    return {"entity_id": entity_id, "x": x, "y": y, "w": w, "h": h, "z_index": z_index}


def save_layout(owner: Optional[str], world_id: str, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        for n in nodes:
            eid = n.get("entity_id")
            if not eid:
                continue
            conn.execute(
                """INSERT INTO atlas_canvas_nodes (entity_id, x, y, w, h, z_index)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_id) DO UPDATE SET
                     x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h, z_index=excluded.z_index""",
                (
                    eid,
                    float(n.get("x", 0)),
                    float(n.get("y", 0)),
                    float(n.get("w", DEFAULT_W)),
                    float(n.get("h", DEFAULT_H)),
                    int(n.get("z_index", 0)),
                ),
            )
    return get_layout(owner, world_id)


def delete_node(owner: Optional[str], world_id: str, entity_id: str) -> bool:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        conn.execute("DELETE FROM atlas_canvas_nodes WHERE entity_id = ?", (entity_id,))
    return True
