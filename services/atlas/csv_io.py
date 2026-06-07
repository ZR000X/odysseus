"""CSV import/export for Atlas entities."""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional

from services.atlas.entities import get_entity
from services.atlas.rows import add_row, update_row
from services.atlas.world_db import open_world_db
from services.atlas.worlds import get_world, refresh_world_stats


def export_csv(owner: Optional[str], world_id: str, entity_id: str) -> str:
    entity = get_entity(owner, world_id, entity_id)
    world = get_world(owner, world_id)
    table = entity["table_name"]
    slugs = ["_atlas_row_id"] + [a["slug"] for a in entity["attributes"]]
    col_list = ", ".join('"' + s.replace('"', '""') + '"' for s in slugs)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(slugs)
    with open_world_db(world["db_path"]) as conn:
        for row in conn.execute(
            f'SELECT {col_list} FROM "{table}" ORDER BY _atlas_row_id'
        ).fetchall():
            writer.writerow([row[s] if row[s] is not None else "" for s in slugs])
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
    slugs = {a["slug"] for a in entity["attributes"]}
    pk_attr = next((a for a in entity["attributes"] if a["is_primary_key"]), None)

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
        row_data = {k: v for k, v in raw.items() if k and k in slugs}
        row_id_raw = raw.get("_atlas_row_id", "").strip()
        try:
            if mode == "merge" and row_id_raw.isdigit():
                update_row(owner, world_id, entity_id, int(row_id_raw), row_data)
                stats["rows_updated"] += 1
                continue
            if mode == "merge" and pk_attr and pk_attr["slug"] in raw and raw[pk_attr["slug"]]:
                # upsert by PK
                pk_val = raw[pk_attr["slug"]]
                from services.atlas.rows import list_rows
                existing = list_rows(
                    owner, world_id, entity_id,
                    limit=1, offset=0,
                    filter_col=pk_attr["slug"], filter_val=pk_val,
                )
                if existing["rows"]:
                    rid = existing["rows"][0]["_atlas_row_id"]
                    update_row(owner, world_id, entity_id, rid, row_data)
                    stats["rows_updated"] += 1
                    continue
            if row_data:
                add_row(owner, world_id, entity_id, row_data)
                stats["rows_inserted"] += 1
            else:
                stats["rows_skipped"] += 1
        except Exception as e:
            stats["rows_failed"] += 1
            stats["errors"].append({"row": i + 2, "message": str(e)})

    refresh_world_stats(owner, world_id)
    return stats
