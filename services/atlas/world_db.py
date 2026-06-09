"""Per-world SQLite file bootstrap and connection management."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

ATLAS_WORLDS_DIR = os.path.join("data", "atlas", "worlds")
SCHEMA_VERSION = 6

_WORLD_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS atlas_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS atlas_entities (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    table_name      TEXT NOT NULL UNIQUE,
    row_count       INTEGER NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS atlas_fields (
    id              TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    slug            TEXT NOT NULL,
    inferred_type   TEXT NOT NULL DEFAULT 'text',
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    nullable_ratio  REAL NOT NULL DEFAULT 1.0,
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES atlas_entities(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_atlas_fields_entity_slug
    ON atlas_fields (entity_id, slug);
CREATE INDEX IF NOT EXISTS ix_atlas_entities_name
    ON atlas_entities (name);

CREATE TABLE IF NOT EXISTS atlas_canvas_nodes (
    entity_id   TEXT PRIMARY KEY,
    x           REAL NOT NULL DEFAULT 0,
    y           REAL NOT NULL DEFAULT 0,
    w           REAL NOT NULL DEFAULT 200,
    h           REAL NOT NULL DEFAULT 120,
    z_index     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (entity_id) REFERENCES atlas_entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS atlas_entity_keys (
    id              TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    name            TEXT NOT NULL,
    field_slugs     TEXT NOT NULL DEFAULT '[]',
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES atlas_entities(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_atlas_entity_keys_entity_name
    ON atlas_entity_keys (entity_id, name);

CREATE TABLE IF NOT EXISTS atlas_relationships (
    id              TEXT PRIMARY KEY,
    from_entity_id  TEXT NOT NULL,
    to_entity_id    TEXT NOT NULL,
    rel_type        TEXT NOT NULL,
    from_field      TEXT NOT NULL,
    to_field        TEXT NOT NULL,
    from_key_id     TEXT REFERENCES atlas_entity_keys(id) ON DELETE SET NULL,
    to_key_id       TEXT REFERENCES atlas_entity_keys(id) ON DELETE SET NULL,
    label           TEXT DEFAULT '',
    from_anchor     TEXT DEFAULT 'right',
    to_anchor       TEXT DEFAULT 'left',
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    FOREIGN KEY (from_entity_id) REFERENCES atlas_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (to_entity_id) REFERENCES atlas_entities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_atlas_relationships_from
    ON atlas_relationships (from_entity_id);
CREATE INDEX IF NOT EXISTS ix_atlas_relationships_to
    ON atlas_relationships (to_entity_id);

CREATE TABLE IF NOT EXISTS atlas_clusters (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT DEFAULT '',
    parent_cluster_id TEXT,
    x                 REAL NOT NULL DEFAULT 0,
    y                 REAL NOT NULL DEFAULT 0,
    w                 REAL NOT NULL DEFAULT 400,
    h                 REAL NOT NULL DEFAULT 300,
    color             TEXT DEFAULT '',
    z_index           INTEGER NOT NULL DEFAULT 0,
    collapsed         INTEGER NOT NULL DEFAULT 0,
    created_at        DATETIME NOT NULL,
    updated_at        DATETIME NOT NULL,
    FOREIGN KEY (parent_cluster_id) REFERENCES atlas_clusters(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_atlas_clusters_parent
    ON atlas_clusters (parent_cluster_id);

CREATE TABLE IF NOT EXISTS atlas_queries (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    sql_text        TEXT NOT NULL DEFAULT '',
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_atlas_queries_name
    ON atlas_queries (name);

CREATE TABLE IF NOT EXISTS atlas_query_deps (
    id              TEXT PRIMARY KEY,
    query_id        TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    created_at      DATETIME NOT NULL,
    FOREIGN KEY (query_id) REFERENCES atlas_queries(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_atlas_query_deps_query
    ON atlas_query_deps (query_id);
CREATE INDEX IF NOT EXISTS ix_atlas_query_deps_source
    ON atlas_query_deps (source_id);

CREATE TABLE IF NOT EXISTS atlas_canvas_query_nodes (
    query_id    TEXT PRIMARY KEY,
    x           REAL NOT NULL DEFAULT 0,
    y           REAL NOT NULL DEFAULT 0,
    w           REAL NOT NULL DEFAULT 200,
    h           REAL NOT NULL DEFAULT 120,
    z_index     INTEGER NOT NULL DEFAULT 0,
    cluster_id  TEXT,
    FOREIGN KEY (query_id) REFERENCES atlas_queries(id) ON DELETE CASCADE
);
"""


def ensure_atlas_dir() -> str:
    os.makedirs(ATLAS_WORLDS_DIR, exist_ok=True)
    return ATLAS_WORLDS_DIR


def world_db_path(world_id: str) -> str:
    ensure_atlas_dir()
    return os.path.join(ATLAS_WORLDS_DIR, f"{world_id}.db")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _migrate_legacy_relationship_keys(conn: sqlite3.Connection) -> None:
    """Auto-create single-column keys for relationships with legacy from_field/to_field."""
    import uuid

    rows = conn.execute(
        """SELECT id, from_entity_id, to_entity_id, from_field, to_field,
                  from_key_id, to_key_id
           FROM atlas_relationships"""
    ).fetchall()
    now = _utcnow_iso()
    for row in rows:
        from_key_id = row["from_key_id"]
        to_key_id = row["to_key_id"]
        from_field = (row["from_field"] or "").strip()
        to_field = (row["to_field"] or "").strip()
        updates = []
        params: list = []

        if not from_key_id and from_field:
            from_key_id = _ensure_legacy_key(
                conn, row["from_entity_id"], "__legacy_from", from_field, now
            )
            updates.append("from_key_id = ?")
            params.append(from_key_id)

        if not to_key_id and to_field:
            to_key_id = _ensure_legacy_key(
                conn, row["to_entity_id"], "__legacy_to", to_field, now
            )
            updates.append("to_key_id = ?")
            params.append(to_key_id)

        if updates:
            params.append(row["id"])
            conn.execute(
                f"UPDATE atlas_relationships SET {', '.join(updates)} WHERE id = ?",
                params,
            )


def _ensure_innate_keys_for_all_entities(conn: sqlite3.Connection) -> None:
    from services.atlas.keys import ensure_innate_key

    rows = conn.execute("SELECT id FROM atlas_entities").fetchall()
    for row in rows:
        ensure_innate_key(conn, row["id"])


def _ensure_legacy_key(
    conn: sqlite3.Connection,
    entity_id: str,
    key_name: str,
    field_slug: str,
    now: str,
) -> str:
    import uuid

    existing = conn.execute(
        "SELECT id FROM atlas_entity_keys WHERE entity_id = ? AND name = ?",
        (entity_id, key_name),
    ).fetchone()
    if existing:
        return existing["id"]
    key_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO atlas_entity_keys
           (id, entity_id, name, field_slugs, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (key_id, entity_id, key_name, json.dumps([field_slug]), now, now),
    )
    return key_id


def _has_case_insensitive_name_duplicates(conn: sqlite3.Connection) -> bool:
    """True if any entity/query names collide case-insensitively within the world."""
    ent_names = [r[0].lower() for r in conn.execute("SELECT name FROM atlas_entities").fetchall()]
    if len(ent_names) != len(set(ent_names)):
        return True
    q_names = [r[0].lower() for r in conn.execute("SELECT name FROM atlas_queries").fetchall()]
    if len(q_names) != len(set(q_names)):
        return True
    return bool(set(ent_names) & set(q_names))


def _migrate_v6_unique_names(conn: sqlite3.Connection) -> None:
    """Add per-table case-insensitive unique indexes when safe."""
    if _has_case_insensitive_name_duplicates(conn):
        conn.execute(
            "INSERT OR REPLACE INTO atlas_meta (key, value) VALUES (?, ?)",
            ("name_duplicates_present", "1"),
        )
        return
    conn.execute("DROP INDEX IF EXISTS ix_atlas_entities_name")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_atlas_entities_name "
        "ON atlas_entities (name COLLATE NOCASE)"
    )
    conn.execute("DROP INDEX IF EXISTS uq_atlas_queries_name")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_atlas_queries_name "
        "ON atlas_queries (name COLLATE NOCASE)"
    )
    conn.execute("DELETE FROM atlas_meta WHERE key = 'name_duplicates_present'")


def _repair_schema_columns(conn: sqlite3.Connection) -> None:
    """Add any columns missing from older/partially-migrated world DBs."""
    if not _table_has_column(conn, "atlas_canvas_nodes", "cluster_id"):
        conn.execute(
            "ALTER TABLE atlas_canvas_nodes ADD COLUMN cluster_id TEXT "
            "REFERENCES atlas_clusters(id) ON DELETE SET NULL"
        )
    if not _table_has_column(conn, "atlas_relationships", "from_key_id"):
        conn.execute(
            "ALTER TABLE atlas_relationships ADD COLUMN from_key_id TEXT "
            "REFERENCES atlas_entity_keys(id) ON DELETE SET NULL"
        )
    if not _table_has_column(conn, "atlas_relationships", "to_key_id"):
        conn.execute(
            "ALTER TABLE atlas_relationships ADD COLUMN to_key_id TEXT "
            "REFERENCES atlas_entity_keys(id) ON DELETE SET NULL"
        )


def ensure_world_schema(conn: sqlite3.Connection) -> int:
    """Apply additive schema updates idempotently (v1 worlds → current)."""
    conn.executescript(_WORLD_BOOTSTRAP_SQL)
    row = conn.execute(
        "SELECT value FROM atlas_meta WHERE key = 'schema_version'"
    ).fetchone()
    current = int(row[0]) if row else 1
    _repair_schema_columns(conn)
    if current < 4:
        _migrate_legacy_relationship_keys(conn)
    if current < 5:
        _ensure_innate_keys_for_all_entities(conn)
    if current < 6:
        _migrate_v6_unique_names(conn)
    if current < SCHEMA_VERSION:
        conn.execute(
            "INSERT OR REPLACE INTO atlas_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
    return SCHEMA_VERSION


def bootstrap_world_db(world_id: str, db_path: Optional[str] = None) -> str:
    path = db_path or world_db_path(world_id)
    ensure_atlas_dir()
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_world_schema(conn)
        now = _utcnow_iso()
        conn.execute(
            "INSERT OR REPLACE INTO atlas_meta (key, value) VALUES (?, ?)",
            ("world_id", json.dumps(world_id)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO atlas_meta (key, value) VALUES (?, ?)",
            ("created_at", json.dumps(now)),
        )
        conn.commit()
    finally:
        conn.close()
    return path


@contextmanager
def open_world_db(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        ensure_world_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
