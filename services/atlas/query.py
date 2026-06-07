"""Filter compilation for Atlas document queries."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


def _json_path(field: str) -> str:
    """Convert dotted field path to SQLite json_extract path."""
    parts = field.split(".")
    path = "$"
    for p in parts:
        path += f".{p}"
    return path


def compile_filter(filter_obj: Optional[Dict[str, Any]] = None) -> Tuple[str, List[Any]]:
    """
    Compile MongoDB-style equality filter to SQL WHERE clause.
    Supports _id / _atlas_row_id and dotted json paths.
    Returns (where_sql, params) — empty where if no filter.
    """
    if not filter_obj:
        return "", []

    clauses: List[str] = []
    params: List[Any] = []

    for key, val in filter_obj.items():
        if key in ("_id", "_atlas_row_id"):
            clauses.append("_atlas_row_id = ?")
            params.append(int(val))
        elif key.startswith("$"):
            raise ValueError(f"Unsupported filter operator at top level: {key}")
        else:
            path = _json_path(key)
            if isinstance(val, bool):
                clauses.append(
                    f"(json_extract(data, ?) = ? OR json_extract(data, ?) = ?)"
                )
                params.extend([path, 1 if val else 0, path, val])
            elif val is None:
                clauses.append(f"json_extract(data, ?) IS NULL")
                params.append(path)
            else:
                clauses.append(f"json_extract(data, ?) = ?")
                params.extend([path, json.dumps(val) if isinstance(val, (dict, list)) else val])

    if not clauses:
        return "", []
    return " WHERE " + " AND ".join(clauses), params


def compile_sort(sort: Optional[Dict[str, int]] = None) -> str:
    if not sort:
        return " ORDER BY _atlas_row_id"
    parts = []
    for field, direction in sort.items():
        if field in ("_id", "_atlas_row_id"):
            parts.append(f"_atlas_row_id {'DESC' if direction < 0 else 'ASC'}")
        else:
            path = _json_path(field)
            parts.append(f"json_extract(data, '{path}') {'DESC' if direction < 0 else 'ASC'}")
    return " ORDER BY " + ", ".join(parts) if parts else " ORDER BY _atlas_row_id"
