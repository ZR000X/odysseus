"""CSV import/export for Atlas entities."""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from services.atlas import documents as atlas_documents
from services.atlas.entities import get_entity


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


def _parse_csv_documents(csv_text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    documents: List[Dict[str, Any]] = []
    for raw in reader:
        row_data = {
            k: v for k, v in raw.items()
            if k and k not in ("_atlas_row_id",)
        }
        row_id_raw = (raw.get("_atlas_row_id") or raw.get("_id") or "").strip()
        if row_id_raw and "_id" not in row_data:
            row_data["_id"] = int(row_id_raw) if row_id_raw.isdigit() else row_id_raw
        doc: Dict[str, Any] = dict(row_data)
        if row_id_raw:
            doc["_import_merge_id"] = int(row_id_raw) if row_id_raw.isdigit() else row_id_raw
        documents.append(doc)
    return documents


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

    documents = _parse_csv_documents(csv_text)
    result = atlas_documents.import_documents_bulk(
        owner, world_id, entity_id, documents, mode=mode,
    )

    stats = {
        "rows_total": result["rows_total"],
        "rows_inserted": result["rows_inserted"],
        "rows_updated": result["rows_updated"],
        "rows_skipped": result["rows_skipped"],
        "rows_failed": result["rows_failed"],
        "errors": [
            {"row": err["index"] + 2, "message": err["message"]}
            for err in result.get("errors", [])
        ],
    }
    return stats
