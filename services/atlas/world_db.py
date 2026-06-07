"""Per-world SQLite file bootstrap and connection management."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

ATLAS_WORLDS_DIR = os.path.join("data", "atlas", "worlds")
SCHEMA_VERSION = 2

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

CREATE TABLE IF NOT EXISTS atlas_relationships (
    id              TEXT PRIMARY KEY,
    from_entity_id  TEXT NOT NULL,
    to_entity_id    TEXT NOT NULL,
    rel_type        TEXT NOT NULL,
    from_field      TEXT NOT NULL,
    to_field        TEXT NOT NULL,
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
"""


def ensure_atlas_dir() -> str:
    os.makedirs(ATLAS_WORLDS_DIR, exist_ok=True)
    return ATLAS_WORLDS_DIR


def world_db_path(world_id: str) -> str:
    ensure_atlas_dir()
    return os.path.join(ATLAS_WORLDS_DIR, f"{world_id}.db")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def bootstrap_world_db(world_id: str, db_path: Optional[str] = None) -> str:
    path = db_path or world_db_path(world_id)
    ensure_atlas_dir()
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_WORLD_BOOTSTRAP_SQL)
        now = _utcnow_iso()
        conn.execute(
            "INSERT OR REPLACE INTO atlas_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
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
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
