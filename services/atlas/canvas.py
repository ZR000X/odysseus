"""Atlas world canvas layout persistence."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.atlas import clusters as atlas_clusters
from services.atlas.entities import list_entities
from services.atlas.world_db import open_world_db
from services.atlas.worlds import get_world

DEFAULT_W = 200
DEFAULT_H = 120


def _default_layout(entities: List[Dict[str, Any]], *, y_offset: float = 0) -> List[Dict[str, Any]]:
    nodes = []
    cols = 3
    for i, e in enumerate(entities):
        col = i % cols
        row = i // cols
        nodes.append({
            "entity_id": e["id"],
            "x": 80 + col * 280,
            "y": 80 + row * 180 + y_offset,
            "w": DEFAULT_W,
            "h": DEFAULT_H,
            "z_index": 0,
            "cluster_id": None,
            "name": e["name"],
            "row_count": e["row_count"],
        })
    return nodes


def _default_query_layout(queries: List[Dict[str, Any]], *, y_offset: float = 400) -> List[Dict[str, Any]]:
    nodes = []
    cols = 3
    for i, q in enumerate(queries):
        col = i % cols
        row = i // cols
        nodes.append({
            "query_id": q["id"],
            "x": 80 + col * 280,
            "y": 80 + row * 180 + y_offset,
            "w": DEFAULT_W,
            "h": DEFAULT_H,
            "z_index": 0,
            "cluster_id": None,
            "name": q["name"],
            "row_count": 0,
        })
    return nodes


def _query_row_count(owner: Optional[str], world_id: str, query_id: str) -> int:
    try:
        from services.atlas import queries as atlas_queries
        result = atlas_queries.execute_query(owner, world_id, query_id, limit=1, offset=0)
        return int(result.get("total", 0))
    except Exception:
        return 0


def get_layout(owner: Optional[str], world_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    entities = list_entities(owner, world_id)
    from services.atlas import queries as atlas_queries
    query_list = atlas_queries.list_queries(owner, world_id)
    clusters = atlas_clusters.list_clusters(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute("SELECT * FROM atlas_canvas_nodes").fetchall()
        qrows = conn.execute("SELECT * FROM atlas_canvas_query_nodes").fetchall()
    saved = {r["entity_id"]: dict(r) for r in rows}
    qsaved = {r["query_id"]: dict(r) for r in qrows}
    nodes = []
    for e in entities:
        if e["id"] in saved:
            n = saved[e["id"]]
            cluster_id = n.get("cluster_id")
            nodes.append({
                "entity_id": e["id"],
                "x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"],
                "z_index": n["z_index"],
                "cluster_id": cluster_id,
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

    query_nodes = []
    for q in query_list:
        rc = _query_row_count(owner, world_id, q["id"])
        if q["id"] in qsaved:
            n = qsaved[q["id"]]
            query_nodes.append({
                "query_id": q["id"],
                "x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"],
                "z_index": n["z_index"],
                "cluster_id": n.get("cluster_id"),
                "name": q["name"],
                "row_count": rc,
                "dependencies": q.get("dependencies", []),
            })
    placed_q = {n["query_id"] for n in query_nodes}
    missing_q = [q for q in query_list if q["id"] not in placed_q]
    if missing_q:
        defaults = _default_query_layout(missing_q)
        for d in defaults:
            q = next(x for x in query_list if x["id"] == d["query_id"])
            d["row_count"] = _query_row_count(owner, world_id, q["id"])
            d["dependencies"] = q.get("dependencies", [])
            query_nodes.append(d)
    elif not query_nodes and query_list:
        for d in _default_query_layout(query_list):
            q = next(x for x in query_list if x["id"] == d["query_id"])
            d["row_count"] = _query_row_count(owner, world_id, q["id"])
            d["dependencies"] = q.get("dependencies", [])
            query_nodes.append(d)

    return {"nodes": nodes, "query_nodes": query_nodes, "clusters": clusters}


def upsert_node(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    x: float,
    y: float,
    w: float = DEFAULT_W,
    h: float = DEFAULT_H,
    z_index: int = 0,
    cluster_id: Optional[str] = None,
) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        conn.execute(
            """INSERT INTO atlas_canvas_nodes (entity_id, x, y, w, h, z_index, cluster_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET
                 x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h,
                 z_index=excluded.z_index, cluster_id=excluded.cluster_id""",
            (entity_id, x, y, w, h, z_index, cluster_id),
        )
    return {
        "entity_id": entity_id, "x": x, "y": y, "w": w, "h": h,
        "z_index": z_index, "cluster_id": cluster_id,
    }


def save_layout(
    owner: Optional[str],
    world_id: str,
    nodes: List[Dict[str, Any]],
    clusters: Optional[List[Dict[str, Any]]] = None,
    query_nodes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        for n in nodes:
            eid = n.get("entity_id")
            if not eid:
                continue
            cluster_id = n.get("cluster_id")
            conn.execute(
                """INSERT INTO atlas_canvas_nodes (entity_id, x, y, w, h, z_index, cluster_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_id) DO UPDATE SET
                     x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h,
                     z_index=excluded.z_index, cluster_id=excluded.cluster_id""",
                (
                    eid,
                    float(n.get("x", 0)),
                    float(n.get("y", 0)),
                    float(n.get("w", DEFAULT_W)),
                    float(n.get("h", DEFAULT_H)),
                    int(n.get("z_index", 0)),
                    cluster_id,
                ),
            )
        if query_nodes is not None:
            for n in query_nodes:
                qid = n.get("query_id")
                if not qid:
                    continue
                cluster_id = n.get("cluster_id")
                conn.execute(
                    """INSERT INTO atlas_canvas_query_nodes
                       (query_id, x, y, w, h, z_index, cluster_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(query_id) DO UPDATE SET
                         x=excluded.x, y=excluded.y, w=excluded.w, h=excluded.h,
                         z_index=excluded.z_index, cluster_id=excluded.cluster_id""",
                    (
                        qid,
                        float(n.get("x", 0)),
                        float(n.get("y", 0)),
                        float(n.get("w", DEFAULT_W)),
                        float(n.get("h", DEFAULT_H)),
                        int(n.get("z_index", 0)),
                        cluster_id,
                    ),
                )
    if clusters is not None:
        atlas_clusters.save_clusters(owner, world_id, clusters)
    return get_layout(owner, world_id)


def delete_node(owner: Optional[str], world_id: str, entity_id: str) -> bool:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        conn.execute("DELETE FROM atlas_canvas_nodes WHERE entity_id = ?", (entity_id,))
    return True


def delete_query_node(owner: Optional[str], world_id: str, query_id: str) -> bool:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        conn.execute("DELETE FROM atlas_canvas_query_nodes WHERE query_id = ?", (query_id,))
    return True
