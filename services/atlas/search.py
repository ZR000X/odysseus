"""Cross-collection text search within an Atlas world."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from services.atlas.world_db import open_world_db
from services.atlas.worlds import get_world


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def search_world(
    owner: Optional[str],
    world_id: str,
    query: str,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search document JSON text across all collections in a world."""
    needle = (query or "").strip().lower()
    if not needle:
        return []

    limit = max(1, min(int(limit or 10), 20))
    world = get_world(owner, world_id)
    hits: List[Dict[str, Any]] = []

    with open_world_db(world["db_path"]) as conn:
        entities = conn.execute(
            "SELECT id, name, table_name FROM atlas_entities ORDER BY name"
        ).fetchall()
        for ent in entities:
            table = ent["table_name"]
            rows = conn.execute(
                f"SELECT _atlas_row_id, data FROM {_quote_ident(table)}"
            ).fetchall()
            for row in rows:
                raw = row["data"] or ""
                if needle not in raw.lower():
                    continue
                try:
                    doc = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    doc = {}
                snippet = raw[:120].replace("\n", " ")
                if len(raw) > 120:
                    snippet += "..."
                hits.append({
                    "entity_id": ent["id"],
                    "entity_name": ent["name"],
                    "_id": row["_atlas_row_id"],
                    "snippet": snippet,
                    "document": doc,
                })
                if len(hits) >= limit:
                    return hits
    return hits
