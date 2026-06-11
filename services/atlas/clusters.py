"""Atlas canvas clusters — nested ringfence containers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.atlas.world_db import open_world_db
from services.atlas.worlds import AtlasNotFoundError, get_world

DEFAULT_CLUSTER_W = 400
DEFAULT_CLUSTER_H = 300


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _row_to_cluster(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "parent_cluster_id": row["parent_cluster_id"],
        "x": row["x"],
        "y": row["y"],
        "w": row["w"],
        "h": row["h"],
        "color": row["color"] or "",
        "z_index": row["z_index"],
        "collapsed": bool(row["collapsed"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _cluster_depth(clusters: List[Dict[str, Any]], cluster_id: Optional[str]) -> int:
    if not cluster_id:
        return 0
    by_id = {c["id"]: c for c in clusters}
    depth = 0
    cur = cluster_id
    seen = set()
    while cur and cur in by_id and cur not in seen:
        seen.add(cur)
        depth += 1
        cur = by_id[cur].get("parent_cluster_id")
    return depth


def _cluster_area(c: Dict[str, Any]) -> float:
    return max(float(c.get("w", 0)), 1) * max(float(c.get("h", 0)), 1)


def contains_point(c: Dict[str, Any], x: float, y: float) -> bool:
    cx, cy = float(c["x"]), float(c["y"])
    cw, ch = float(c["w"]), float(c["h"])
    return cx <= x <= cx + cw and cy <= y <= cy + ch


def hit_test_cluster(
    x: float,
    y: float,
    clusters: List[Dict[str, Any]],
    *,
    exclude_id: Optional[str] = None,
) -> Optional[str]:
    """Return innermost cluster id containing point (x, y)."""
    candidates = [
        c for c in clusters
        if c["id"] != exclude_id and contains_point(c, x, y)
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (-_cluster_depth(clusters, c["id"]), _cluster_area(c))
    )
    return candidates[0]["id"]


def list_clusters(owner: Optional[str], world_id: str) -> List[Dict[str, Any]]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        rows = conn.execute(
            "SELECT * FROM atlas_clusters ORDER BY created_at"
        ).fetchall()
        return [_row_to_cluster(r) for r in rows]


def get_cluster(owner: Optional[str], world_id: str, cluster_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT * FROM atlas_clusters WHERE id = ?", (cluster_id,)
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Cluster not found: {cluster_id}")
        return _row_to_cluster(row)


def resolve_cluster(
    owner: Optional[str],
    world_id: str,
    *,
    cluster_id: Optional[str] = None,
    cluster_name: Optional[str] = None,
) -> Dict[str, Any]:
    cid = (cluster_id or "").strip() or None
    cname = (cluster_name or "").strip() or None

    clusters = list_clusters(owner, world_id)
    if cid:
        for c in clusters:
            if c["id"] == cid:
                return c
        matches = [c for c in clusters if c["id"].startswith(cid)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(f'{c["name"]} ({c["id"][:8]})' for c in matches[:5])
            raise AtlasNotFoundError(
                f'Ambiguous cluster_id prefix "{cid}": {names}. Use full UUID or cluster name.'
            )
        if not cname:
            for c in clusters:
                if c["name"].lower() == cid.lower():
                    return c
        raise AtlasNotFoundError(f'Cluster not found: "{cid}". Try list_clusters.')

    if cname:
        for c in clusters:
            if c["name"].lower() == cname.lower():
                return c
        raise AtlasNotFoundError(f'Cluster not found: "{cname}". Try list_clusters.')

    raise AtlasNotFoundError("cluster_id or cluster_name required")


def _validate_parent(conn, parent_id: Optional[str], cluster_id: Optional[str] = None) -> None:
    if not parent_id:
        return
    row = conn.execute(
        "SELECT id FROM atlas_clusters WHERE id = ?", (parent_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Parent cluster not found: {parent_id}")
    if cluster_id and parent_id == cluster_id:
        raise ValueError("Cluster cannot be its own parent")


def create_cluster(
    owner: Optional[str],
    world_id: str,
    name: str,
    x: float = 0,
    y: float = 0,
    w: float = DEFAULT_CLUSTER_W,
    h: float = DEFAULT_CLUSTER_H,
    parent_cluster_id: Optional[str] = None,
    color: str = "",
    z_index: int = 0,
    description: str = "",
) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Cluster name is required")
    cluster_id = str(uuid.uuid4())
    now = _utcnow_iso()
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        _validate_parent(conn, parent_cluster_id)
        conn.execute(
            """INSERT INTO atlas_clusters
               (id, name, description, parent_cluster_id, x, y, w, h,
                color, z_index, collapsed, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                cluster_id, name, description, parent_cluster_id,
                float(x), float(y), float(w), float(h),
                color or "", int(z_index), now, now,
            ),
        )
    return get_cluster(owner, world_id, cluster_id)


def update_cluster(
    owner: Optional[str],
    world_id: str,
    cluster_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    now = _utcnow_iso()
    allowed = {
        "name", "description", "parent_cluster_id",
        "x", "y", "w", "h", "color", "z_index", "collapsed",
    }
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k not in allowed or v is None:
            continue
        if k == "collapsed":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return get_cluster(owner, world_id, cluster_id)

    with open_world_db(world["db_path"]) as conn:
        current = conn.execute(
            "SELECT * FROM atlas_clusters WHERE id = ?", (cluster_id,)
        ).fetchone()
        if not current:
            raise AtlasNotFoundError(f"Cluster not found: {cluster_id}")

        new_parent = kwargs.get("parent_cluster_id", current["parent_cluster_id"])
        if new_parent == cluster_id:
            raise ValueError("Cluster cannot be its own parent")
        _validate_parent(conn, new_parent, cluster_id)

        sets.append("updated_at = ?")
        vals.append(now)
        vals.append(cluster_id)
        cur = conn.execute(
            f"UPDATE atlas_clusters SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Cluster not found: {cluster_id}")
    return get_cluster(owner, world_id, cluster_id)


def delete_cluster(owner: Optional[str], world_id: str, cluster_id: str) -> bool:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        row = conn.execute(
            "SELECT parent_cluster_id FROM atlas_clusters WHERE id = ?", (cluster_id,)
        ).fetchone()
        if not row:
            raise AtlasNotFoundError(f"Cluster not found: {cluster_id}")
        parent_id = row["parent_cluster_id"]

        conn.execute(
            "UPDATE atlas_clusters SET parent_cluster_id = ? WHERE parent_cluster_id = ?",
            (parent_id, cluster_id),
        )
        conn.execute(
            "UPDATE atlas_canvas_nodes SET cluster_id = ? WHERE cluster_id = ?",
            (parent_id, cluster_id),
        )
        cur = conn.execute("DELETE FROM atlas_clusters WHERE id = ?", (cluster_id,))
        if cur.rowcount == 0:
            raise AtlasNotFoundError(f"Cluster not found: {cluster_id}")
    return True


def save_clusters(owner: Optional[str], world_id: str, clusters: List[Dict[str, Any]]) -> None:
    """Bulk upsert cluster geometry from canvas save."""
    world = get_world(owner, world_id)
    now = _utcnow_iso()
    with open_world_db(world["db_path"]) as conn:
        for c in clusters:
            cid = c.get("id")
            if not cid:
                continue
            existing = conn.execute(
                "SELECT id FROM atlas_clusters WHERE id = ?", (cid,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE atlas_clusters SET
                       name = ?, parent_cluster_id = ?, x = ?, y = ?, w = ?, h = ?,
                       color = ?, z_index = ?, collapsed = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        c.get("name") or "Cluster",
                        c.get("parent_cluster_id"),
                        float(c.get("x", 0)),
                        float(c.get("y", 0)),
                        float(c.get("w", DEFAULT_CLUSTER_W)),
                        float(c.get("h", DEFAULT_CLUSTER_H)),
                        c.get("color") or "",
                        int(c.get("z_index", 0)),
                        1 if c.get("collapsed") else 0,
                        now,
                        cid,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO atlas_clusters
                       (id, name, description, parent_cluster_id, x, y, w, h,
                        color, z_index, collapsed, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cid,
                        c.get("name") or "Cluster",
                        c.get("description") or "",
                        c.get("parent_cluster_id"),
                        float(c.get("x", 0)),
                        float(c.get("y", 0)),
                        float(c.get("w", DEFAULT_CLUSTER_W)),
                        float(c.get("h", DEFAULT_CLUSTER_H)),
                        c.get("color") or "",
                        int(c.get("z_index", 0)),
                        1 if c.get("collapsed") else 0,
                        now,
                        now,
                    ),
                )


def assign_entity_to_cluster(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    cluster_id: Optional[str],
) -> bool:
    from services.atlas.canvas import DEFAULT_H, DEFAULT_W, get_layout

    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        if cluster_id:
            row = conn.execute(
                "SELECT id FROM atlas_clusters WHERE id = ?", (cluster_id,)
            ).fetchone()
            if not row:
                raise AtlasNotFoundError(f"Cluster not found: {cluster_id}")
        existing = conn.execute(
            "SELECT entity_id FROM atlas_canvas_nodes WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if not existing:
            layout = get_layout(owner, world_id)
            node = next((n for n in layout["nodes"] if n["entity_id"] == entity_id), None)
            if node:
                conn.execute(
                    """INSERT INTO atlas_canvas_nodes
                       (entity_id, x, y, w, h, z_index, cluster_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entity_id, node["x"], node["y"], node["w"], node["h"],
                        node.get("z_index", 0), cluster_id,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO atlas_canvas_nodes
                       (entity_id, x, y, w, h, z_index, cluster_id)
                       VALUES (?, ?, ?, ?, ?, 0, ?)""",
                    (entity_id, 0, 0, DEFAULT_W, DEFAULT_H, cluster_id),
                )
        else:
            conn.execute(
                "UPDATE atlas_canvas_nodes SET cluster_id = ? WHERE entity_id = ?",
                (cluster_id, entity_id),
            )
    return True
