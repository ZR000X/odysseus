"""MySQL-flavored SQL execution over Atlas collections (virtual views)."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import sqlglot
    from sqlglot import exp
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

from services.atlas.documents import row_to_document
from services.atlas.entities import list_entities
from services.atlas.fields import _sample_key_map, load_fields
from services.atlas.world_db import open_world_db
from services.atlas.worlds import get_world


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _safe_view_name(kind: str, id_: str) -> str:
    return f"v_{kind}_{id_.replace('-', '_')}"


def _require_sqlglot() -> None:
    if not HAS_SQLGLOT:
        raise RuntimeError("sqlglot is required for Atlas queries. pip install sqlglot")


def _is_query_expression(parsed: exp.Expression) -> bool:
    return isinstance(parsed, (exp.Select, exp.Union))


# $("Name") → `Name` before sqlglot parse; supports escaped \" inside name.
_SOURCE_MACRO_RE = re.compile(r'\$\("((?:[^"\\]|\\.)*)"\)')


def _expand_source_macros(sql_text: str) -> str:
    def _replace(m: re.Match) -> str:
        name = m.group(1).replace('\\"', '"')
        escaped = name.replace('`', '``')
        return f'`{escaped}`'

    return _SOURCE_MACRO_RE.sub(_replace, sql_text)


def prepare_sql(sql_text: str) -> str:
    """Normalize user SQL: trim and expand $(\"Name\") source macros."""
    return _expand_source_macros((sql_text or "").strip())


def rewrite_source_references(sql_text: str, old_name: str, new_name: str) -> str:
    """Update collection/query name references in stored SQL after a rename."""
    if old_name == new_name:
        return sql_text

    out = sql_text

    old_macro = old_name.replace('\\', '\\\\').replace('"', '\\"')
    new_macro = new_name.replace('\\', '\\\\').replace('"', '\\"')
    out = out.replace(f'$("{old_macro}")', f'$("{new_macro}")')

    old_bt = old_name.replace('`', '``')
    new_bt = new_name.replace('`', '``')
    out = out.replace(f'`{old_bt}`', f'`{new_bt}`')

    if re.fullmatch(r'\w+', old_name):
        out = re.sub(
            rf'(?i)\b((?:FROM|JOIN)\s+){re.escape(old_name)}(?=\s|$)',
            lambda m: m.group(1) + new_name,
            out,
        )

    return out


def _name_map(conn, world_id: str) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """Case-insensitive name -> entity/query record."""
    entities = list_entities(None, world_id)
    ent_by_name = {e["name"].lower(): e for e in entities}
    rows = conn.execute("SELECT * FROM atlas_queries ORDER BY name").fetchall()
    queries = [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"] or "",
            "sql_text": r["sql_text"] or "",
        }
        for r in rows
    ]
    q_by_name = {q["name"].lower(): q for q in queries}
    return ent_by_name, q_by_name


def _json_path_for_key(key: str) -> str:
    """SQLite JSON path for an arbitrary document key."""
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return '$."' + escaped + '"'


def _entity_column_map(fields: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map lowercase field labels (slug or original key) -> view column slug."""
    out: Dict[str, str] = {"_id": "_id"}
    for field in fields:
        slug = field["slug"]
        out[slug.lower()] = slug
        sample = field.get("sample_key")
        if sample:
            out[str(sample).lower()] = slug
    return out


def _query_result_column_map(conn: sqlite3.Connection, sub_sql: str) -> Dict[str, str]:
    cur = conn.execute(f"SELECT * FROM ({sub_sql}) AS _sub LIMIT 0")
    return {name.lower(): name for name in (d[0] for d in (cur.description or []))}


def _entity_view_sql(table_name: str, fields: List[Dict[str, Any]]) -> str:
    cols = ["_atlas_row_id AS _id"]
    seen_slugs: Set[str] = set()
    for field in fields:
        slug = field["slug"]
        if slug == "_id" or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        json_key = field.get("sample_key") or slug
        path = _json_path_for_key(json_key)
        cols.append(f"json_extract(data, '{path}') AS {_quote_ident(slug)}")
    col_sql = ", ".join(cols)
    return f"SELECT {col_sql} FROM {_quote_ident(table_name)}"


def _extract_table_refs(sql_text: str) -> Set[str]:
    _require_sqlglot()
    sql_text = prepare_sql(sql_text)
    try:
        parsed = sqlglot.parse_one(sql_text, read="mysql")
    except Exception as e:
        raise ValueError(f"SQL parse error: {e}") from e
    tables: Set[str] = set()
    for node in parsed.find_all(exp.Table):
        name = node.name
        if name:
            tables.add(name)
    return tables


def parse_dependencies(
    conn,
    sql_text: str,
    ent_by_name: Dict[str, Dict],
    q_by_name: Dict[str, Dict],
    *,
    self_query_id: Optional[str] = None,
) -> List[Dict[str, str]]:
    tables = _extract_table_refs(sql_text)
    deps: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for t in tables:
        key = t.lower()
        if key in seen:
            continue
        if key in ent_by_name:
            deps.append({"source_type": "entity", "source_id": ent_by_name[key]["id"]})
            seen.add(key)
        elif key in q_by_name:
            qid = q_by_name[key]["id"]
            if self_query_id and qid == self_query_id:
                raise ValueError(f"Query cannot reference itself: {t}")
            deps.append({"source_type": "query", "source_id": qid})
            seen.add(key)
        else:
            raise ValueError(f"Unknown table/query: {t}")
    return deps


def get_world_catalog(owner: Optional[str], world_id: str) -> Dict[str, Any]:
    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as conn:
        entities = list_entities(owner, world_id)
        collections = []
        for e in entities:
            fields = load_fields(conn, e["id"], include_stats=False, include_sparse=False)
            collections.append({
                "id": e["id"],
                "name": e["name"],
                "fields": [{"slug": f["slug"], "type": f["inferred_type"]} for f in fields],
            })
        qrows = conn.execute("SELECT id, name, description, sql_text FROM atlas_queries ORDER BY name").fetchall()
        queries = []
        for r in qrows:
            cols: List[Dict[str, str]] = []
            try:
                if r["sql_text"]:
                    cols = _infer_result_columns(conn, owner, world_id, r["sql_text"], r["id"])
            except Exception:
                pass
            queries.append({
                "id": r["id"],
                "name": r["name"],
                "columns": cols,
            })
    return {"collections": collections, "queries": queries}


def _infer_result_columns(
    conn,
    owner: Optional[str],
    world_id: str,
    sql_text: str,
    self_query_id: Optional[str] = None,
) -> List[Dict[str, str]]:
    try:
        result = execute_sql(
            owner, world_id, sql_text,
            limit=0, offset=0, self_query_id=self_query_id,
            conn=conn, columns_only=True,
        )
        return result.get("columns", [])
    except Exception:
        return []


def _build_views(
    conn: sqlite3.Connection,
    owner: Optional[str],
    world_id: str,
    sql_text: str,
    *,
    self_query_id: Optional[str] = None,
    visited_queries: Optional[Set[str]] = None,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """Create temp views; return table/view maps and per-table column resolvers."""
    visited_queries = visited_queries or set()
    ent_by_name, q_by_name = _name_map(conn, world_id)
    tables = _extract_table_refs(sql_text)
    name_to_view: Dict[str, str] = {}
    column_maps: Dict[str, Dict[str, str]] = {}

    for t in tables:
        key = t.lower()
        if key in name_to_view:
            continue
        if key in ent_by_name:
            ent = ent_by_name[key]
            sample = None
            row = conn.execute(
                f"SELECT _atlas_row_id, _atlas_created_at, _atlas_updated_at, data "
                f"FROM {_quote_ident(ent['table_name'])} ORDER BY _atlas_row_id LIMIT 1"
            ).fetchone()
            if row:
                sample = row_to_document(dict(row))
            key_map = _sample_key_map(sample)
            fields = load_fields(
                conn, ent["id"], include_stats=False, include_sparse=False,
                sample_key_map=key_map,
            )
            view = _safe_view_name("ent", ent["id"])
            conn.execute(f"DROP VIEW IF EXISTS {_quote_ident(view)}")
            conn.execute(
                f"CREATE TEMP VIEW {_quote_ident(view)} AS "
                f"{_entity_view_sql(ent['table_name'], fields)}"
            )
            name_to_view[key] = view
            column_maps[key] = _entity_column_map(fields)
        elif key in q_by_name:
            q = q_by_name[key]
            if q["id"] in visited_queries:
                raise ValueError(f"Circular query dependency: {q['name']}")
            visited_queries.add(q["id"])
            sub_views, sub_column_maps = _build_views(
                conn, owner, world_id, q["sql_text"],
                self_query_id=q["id"], visited_queries=visited_queries,
            )
            sub_sql = _rewrite_sql_to_views(
                prepare_sql(q["sql_text"]), sub_views, sub_column_maps, ent_by_name, q_by_name,
            )
            view = _safe_view_name("qry", q["id"])
            conn.execute(f"DROP VIEW IF EXISTS {_quote_ident(view)}")
            conn.execute(
                f"CREATE TEMP VIEW {_quote_ident(view)} AS {sub_sql}"
            )
            name_to_view[key] = view
            column_maps[key] = _query_result_column_map(conn, sub_sql)
        else:
            raise ValueError(f"Unknown table/query: {t}")
    return name_to_view, column_maps


def _table_alias_map(parsed: exp.Expression) -> Tuple[Dict[str, str], Set[str]]:
    """Map alias/table ref (lower) -> source table key (lower)."""
    alias_to_key: Dict[str, str] = {}
    table_keys: Set[str] = set()
    for node in parsed.find_all(exp.Table):
        key = (node.name or "").lower()
        if not key:
            continue
        table_keys.add(key)
        alias_to_key[key] = key
        alias = node.alias
        if alias:
            alias_name = alias if isinstance(alias, str) else getattr(alias, "name", None)
            if alias_name:
                alias_to_key[str(alias_name).lower()] = key
    return alias_to_key, table_keys


def _resolve_column_slug(
    col_name: str,
    table_ref: Optional[str],
    alias_to_key: Dict[str, str],
    table_keys: Set[str],
    column_maps: Dict[str, Dict[str, str]],
) -> Optional[str]:
    table_key: Optional[str] = None
    if table_ref:
        table_key = alias_to_key.get(str(table_ref).lower())
    elif len(table_keys) == 1:
        table_key = next(iter(table_keys))
    if not table_key:
        return None
    return column_maps.get(table_key, {}).get(col_name.lower())


def _rewrite_sql_to_views(
    sql_text: str,
    name_to_view: Dict[str, str],
    column_maps: Dict[str, Dict[str, str]],
    ent_by_name: Dict[str, Dict],
    q_by_name: Dict[str, Dict],
) -> str:
    _require_sqlglot()
    parsed = sqlglot.parse_one(prepare_sql(sql_text), read="mysql")
    alias_to_key, table_keys = _table_alias_map(parsed)

    for node in parsed.find_all(exp.Table):
        key = (node.name or "").lower()
        if key in name_to_view:
            node.set("this", exp.to_identifier(name_to_view[key]))

    for node in parsed.find_all(exp.Column):
        col_name = node.name
        if not col_name or col_name == "*":
            continue
        table_ref = node.table
        if isinstance(table_ref, exp.Identifier):
            table_ref = table_ref.name
        resolved = _resolve_column_slug(
            col_name, table_ref, alias_to_key, table_keys, column_maps,
        )
        if resolved:
            node.set("this", exp.to_identifier(resolved, quoted=True))

    return parsed.sql(dialect="sqlite", identify=True)


def _sql_validation_error(message: str) -> Dict[str, Any]:
    return {"valid": False, "error": message, "dependencies": [], "columns": []}


def validate_sql(
    owner: Optional[str],
    world_id: str,
    sql_text: str,
    *,
    self_query_id: Optional[str] = None,
) -> Dict[str, Any]:
    _require_sqlglot()
    sql_text = prepare_sql(sql_text)
    if not sql_text:
        return _sql_validation_error("sql_text is required")
    try:
        parsed = sqlglot.parse_one(sql_text, read="mysql")
    except Exception as e:
        return _sql_validation_error(f"SQL parse error: {e}")
    if not _is_query_expression(parsed):
        return _sql_validation_error("Only SELECT queries are supported")
    try:
        world = get_world(owner, world_id)
        with open_world_db(world["db_path"]) as conn:
            ent_by_name, q_by_name = _name_map(conn, world_id)
            deps = parse_dependencies(
                conn, sql_text, ent_by_name, q_by_name, self_query_id=self_query_id,
            )
            columns = _infer_result_columns(
                conn, owner, world_id, sql_text, self_query_id,
            )
    except ValueError as e:
        return _sql_validation_error(str(e))
    return {
        "valid": True,
        "dependencies": deps,
        "columns": columns,
    }


def execute_sql(
    owner: Optional[str],
    world_id: str,
    sql_text: str,
    *,
    limit: int = 50,
    offset: int = 0,
    self_query_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    columns_only: bool = False,
) -> Dict[str, Any]:
    _require_sqlglot()
    sql_text = prepare_sql(sql_text)
    if not sql_text:
        raise ValueError("sql_text is required")
    parsed = sqlglot.parse_one(sql_text, read="mysql")
    if not _is_query_expression(parsed):
        raise ValueError("Only SELECT queries are supported")

    limit = max(0, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))

    def _run(c: sqlite3.Connection) -> Dict[str, Any]:
        ent_by_name, q_by_name = _name_map(c, world_id)
        views, column_maps = _build_views(
            c, owner, world_id, sql_text, self_query_id=self_query_id,
        )
        rewritten = _rewrite_sql_to_views(
            sql_text, views, column_maps, ent_by_name, q_by_name,
        )
        try:
            if columns_only and limit == 0:
                cur = c.execute(f"SELECT * FROM ({rewritten}) AS _q LIMIT 0")
                cols = [{"name": d[0], "type": "text"} for d in (cur.description or [])]
                return {"columns": cols, "documents": [], "total": 0}
            count_sql = f"SELECT COUNT(*) FROM ({rewritten}) AS _q"
            total = c.execute(count_sql).fetchone()[0]
            data_sql = f"SELECT * FROM ({rewritten}) AS _q LIMIT ? OFFSET ?"
            cur = c.execute(data_sql, [limit, offset])
        except sqlite3.Error as e:
            raise ValueError(f"SQL execution error: {e}") from e
        col_names = [d[0] for d in (cur.description or [])]
        rows = cur.fetchall()
        documents = []
        for i, row in enumerate(rows):
            doc = {"_id": offset + i + 1}
            for j, col in enumerate(col_names):
                val = row[j]
                if isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                doc[col] = val
            documents.append(doc)
        columns = [{"name": n, "type": "text"} for n in col_names]
        return {
            "documents": documents,
            "total": int(total),
            "columns": columns,
            "limit": limit,
            "offset": offset,
        }

    if conn is not None:
        return _run(conn)

    world = get_world(owner, world_id)
    with open_world_db(world["db_path"]) as c:
        return _run(c)
