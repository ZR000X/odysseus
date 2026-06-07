# Atlas

Atlas is Odysseus's structured data catalogue: **worlds** of **entities** (schemas) and **rows** (data), stored locally in SQLite, browsable in the UI, and readable/writable from chat via the `manage_atlas` agent tool.

## Concepts (MVP1)

| Concept | Description |
|---------|-------------|
| **World** | An isolated data universe. Each world has its own SQLite file under `data/atlas/worlds/{id}.db`. Worlds do not share data. |
| **Entity** | A named table schema (e.g. Customers) with typed attributes (columns). |
| **Attribute** | A column definition: name, type (`text`, `integer`, `real`, `boolean`), optional primary key / unique. |
| **Row** | A data record in an entity's physical `ent_*` table. Each row has a system `_atlas_row_id`. |

Planned for later releases: clusters, canvas graph, relationships, rules.

## Using the UI

1. Open **Atlas** from the sidebar (Tools section).
2. Select a **world** (a default "My World" is created on first use).
3. Select an **entity** to browse rows in a paginated table.
4. Use **Export CSV** to download entity data.
5. **+ World** / **+ Entity** create new worlds and entities.

Deep link: `/atlas`

## Using the agent

Ask in chat — the agent uses `manage_atlas`:

- *"Create a Customers entity with columns id, name, email"*
- *"Add a customer: id=1, name=Alice, email=alice@example.com"*
- *"How many rows in Customers?"*
- *"Import this CSV into Customers: …"*
- *"Open atlas"*

**Do not** store tabular datasets in Memory or Documents unless you explicitly want a document. Use Atlas for structured, queryable data.

After creating entities or worlds, the agent returns clickable links like `[Customers](#atlas-entity-<id>)`.

## manage_atlas actions

| Action | Description |
|--------|-------------|
| `list_worlds` | List all worlds for the current user |
| `create_world` | Create a new world (`name`) |
| `list_entities` | List entities in a world (`world_id` optional) |
| `create_entity` | Create entity with `name` and `attributes` array |
| `add_attribute` | Add a column to an existing entity |
| `list_rows` | Paginated rows (`limit` default 20, max 100) |
| `count_rows` | Row count for an entity |
| `add_row` | Insert one row (`row` object) |
| `update_row` | Update by `_atlas_row_id` |
| `delete_row` | Delete by `_atlas_row_id` |
| `import_rows` | Bulk CSV import (`csv`, `mode`: append/merge/replace) |
| `export_csv` | Return CSV text for an entity |

If `world_id` is omitted, the user's default (most recent) world is used; one is auto-created if none exist.

## HTTP API

All routes require authentication (same as other Odysseus APIs).

```
GET    /api/atlas/worlds
POST   /api/atlas/worlds
GET    /api/atlas/worlds/{wid}/entities
POST   /api/atlas/worlds/{wid}/entities
POST   /api/atlas/worlds/{wid}/entities/{eid}/attributes
GET    /api/atlas/worlds/{wid}/entities/{eid}/rows
POST   /api/atlas/worlds/{wid}/entities/{eid}/rows
PUT    /api/atlas/worlds/{wid}/entities/{eid}/rows/{row_id}
DELETE /api/atlas/worlds/{wid}/entities/{eid}/rows/{row_id}
GET    /api/atlas/worlds/{wid}/entities/{eid}/export.csv
POST   /api/atlas/worlds/{wid}/entities/{eid}/import
```

## Data storage

| Location | Contents |
|----------|----------|
| `app.db` → `atlas_worlds` | World registry (name, owner, paths, stats) |
| `data/atlas/worlds/{id}.db` | Per-world metadata + entity data tables |

Both are under `data/` (gitignored). Back up with the rest of your Odysseus data directory.

## CSV workflow

1. **Export** from the Atlas UI (or agent `export_csv`).
2. Edit in Excel, LibreOffice, or a text editor.
3. **Import** via agent: `import_rows` with `mode`:
   - `append` — add new rows only
   - `merge` — upsert on primary key or `_atlas_row_id`
   - `replace` — truncate and reload

CSV includes `_atlas_row_id` for stable merge identity.

## MVP1 limits

- Attribute types: `text`, `integer`, `real`, `boolean` only
- No clusters, relationships, or rules engine yet
- No cross-world queries
- `list_rows` capped at 100 rows per call (agent default 20)
- UI table is read-only; edit via chat or API

## Roadmap

- Cluster ringfences and canvas graph
- Relationships (1:1, 1:N, N:M) and rules
- CSV import in UI
- External agent API scope (`/api/codex/atlas`)
