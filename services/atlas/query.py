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


def _compile_field_operator(path: str, op: str, op_val: Any) -> Tuple[str, List[Any]]:
    if op == "$in":
        if not isinstance(op_val, list) or not op_val:
            raise ValueError("$in requires a non-empty array")
        placeholders = ", ".join("?" for _ in op_val)
        clause = f"json_extract(data, ?) IN ({placeholders})"
        params: List[Any] = [path]
        for item in op_val:
            params.append(json.dumps(item) if isinstance(item, (dict, list)) else item)
        return clause, params
    if op == "$contains":
        needle = str(op_val).lower()
        return "LOWER(json_extract(data, ?)) LIKE ?", [path, f"%{needle}%"]
    if op == "$ne":
        if op_val is None:
            return "json_extract(data, ?) IS NOT NULL", [path]
        return "json_extract(data, ?) != ?", [path, json.dumps(op_val) if isinstance(op_val, (dict, list)) else op_val]
    if op in ("$gt", "$gte", "$lt", "$lte"):
        sql_op = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
        return f"json_extract(data, ?) {sql_op} ?", [path, op_val]
    raise ValueError(f"Unsupported filter operator: {op}")


def _compile_field_clause(key: str, val: Any) -> Tuple[str, List[Any]]:
    if key in ("_id", "_atlas_row_id"):
        if isinstance(val, dict):
            raise ValueError("_id does not support operator filters")
        if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
            n = int(val)
            return (
                "(_atlas_row_id = ? OR json_extract(data, '$._id') = ? OR json_extract(data, '$._id') = ?)",
                [n, n, val],
            )
        return (
            "(json_extract(data, '$._id') = ? OR json_extract(data, '$._id') = ?)",
            [val, json.dumps(val)],
        )

    path = _json_path(key)
    if isinstance(val, dict) and val and all(str(k).startswith("$") for k in val):
        sub_clauses: List[str] = []
        sub_params: List[Any] = []
        for op, op_val in val.items():
            c, p = _compile_field_operator(path, op, op_val)
            sub_clauses.append(c)
            sub_params.extend(p)
        return " AND ".join(f"({c})" for c in sub_clauses), sub_params

    if isinstance(val, bool):
        return (
            f"(json_extract(data, ?) = ? OR json_extract(data, ?) = ?)",
            [path, 1 if val else 0, path, val],
        )
    if val is None:
        return "json_extract(data, ?) IS NULL", [path]
    return "json_extract(data, ?) = ?", [path, json.dumps(val) if isinstance(val, (dict, list)) else val]


def compile_filter(filter_obj: Optional[Dict[str, Any]] = None) -> Tuple[str, List[Any]]:
    """
    Compile MongoDB-style filter to SQL WHERE clause.
    Supports _id / _atlas_row_id, dotted json paths, and $in/$contains/$ne/$gt/$gte/$lt/$lte.
    Returns (where_sql, params) — empty where if no filter.
    """
    if not filter_obj:
        return "", []

    clauses: List[str] = []
    params: List[Any] = []

    for key, val in filter_obj.items():
        if key.startswith("$"):
            raise ValueError(f"Unsupported filter operator at top level: {key}")
        clause, clause_params = _compile_field_clause(key, val)
        clauses.append(clause)
        params.extend(clause_params)

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
