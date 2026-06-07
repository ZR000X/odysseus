"""CSV import/export for Atlas entities."""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Optional

from services.atlas import documents as atlas_documents
from services.atlas.entities import get_entity
from services.atlas.world_db import open_world_db
from services.atlas.worlds import get_world, refresh_world_stats


def export_csv(owner: Optional[str], world_id: str, entity_id: str) -> str:
    entity = get_entity(owner, world_id, entity_id)
    result = atlas_documents.find(owner, world_id, entity_id, limit=10000, offset=0)
    docs = result["documents"]
    all_keys: set = set()
    for d in docs:
        all_keys.update(k for k in d if not k.startswith("_") or k == "_atlas_row_id")
    slugs = ["_atlas_row_id"] + sorted(k for k in all_keys if k != "_atlas_row_id")
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(slugs)
    for d in docs:
        row = []
        for s in slugs:
            v = d.get(s, d.get("_id") if s == "_atlas_row_id" else "")
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            row.append("" if v is None else str(v))
        writer.writerow(row)
    return buf.getvalue()


def import_rows(
    owner: Optional[str],
    world_id: str,
    entity_id: str,
    csv_text: str,
    mode: str = "append",
) -> Dict[str, Any]:
    mode = (mode or "append").lower()
    if mode not in ("append", "merge", "replace"):
        raise ValueError("mode must be append, merge, or replace")
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    stats = {
        "rows_total": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
        "rows_failed": 0,
        "errors": [],
    }

    if mode == "replace":
        with open_world_db(world["db_path"]) as conn:
            conn.execute(f'DELETE FROM "{table}"')
            conn.execute(
                "UPDATE atlas_entities SET row_count = 0, updated_at = datetime('now') WHERE id = ?",
                (entity_id,),
            )

    for i, raw in enumerate(reader):
        stats["rows_total"] += 1
        row_data = {
            k: v for k, v in raw.items()
            if k and k not in ("_atlas_row_id", "_id")
        }
        row_id_raw = (raw.get("_atlas_row_id") or raw.get("_id") or "").strip()
        try:
            if mode == "merge" and row_id_raw.isdigit():
                atlas_documents.update_one(
                    owner, world_id, entity_id,
                    {"_id": int(row_id_raw)}, row_data,
                )
                stats["rows_updated"] += 1
                continue
            if row_data or mode == "append":
                atlas_documents.insert_one(owner, world_id, entity_id, row_data)
                stats["rows_inserted"] += 1
            else:
                stats["rows_skipped"] += 1
        except Exception as e:
            stats["rows_failed"] += 1
            stats["errors"].append({"row": i + 2, "message": str(e)})

    refresh_world_stats(owner, world_id)
    return stats
