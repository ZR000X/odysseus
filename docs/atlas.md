# Atlas

Atlas is Odysseus's MongoDB-style document store: **worlds** of **collections** (entities) and **documents**, stored locally in SQLite, browsable on an Obsidian-like canvas, drill-down in a Compass-style viewer, and readable/writable from chat via `manage_atlas`.

## Concepts

| Concept | Description |
|---------|-------------|
| **World** | Isolated data universe. Each world has its own SQLite file under `data/atlas/worlds/{id}.db`. |
| **Collection (entity)** | Named group of documents. Schemaless — fields are inferred from data. |
| **Document** | JSON object with auto `_id` (`_atlas_row_id` internally). |
| **Field** | Inferred from documents; shown in Compass schema sidebar and `get_schema`. |
| **Key** | Declared uniqueness on one or more field slugs (composite supported). Managed in Compass **Keys** sidebar. |
| **Relationship** | Typed edge (1:1, 1:N, N:M) joining collections via **keys** (not arbitrary fields). |
| **Query** | MySQL-flavored `SELECT` stored as a virtual collection; results browsed in Compass like any collection. |
| **Cluster** | Nested ringfence container on the canvas — group collections (e.g. Personal vs Work). Relationships can cross cluster boundaries. |

## Using the UI

1. Open **Atlas** from the sidebar (Tools).
2. **Canvas view** — pan/zoom, drag collection cards, connect relationships. **Clusters** ringfence related collections: click **+ Cluster** or Shift+double-click empty space to create one; drag collections into a cluster (innermost nested box wins); drag a cluster header to move everything inside; resize via corner/edge handles; nest clusters inside clusters.
3. Drag from a collection port to another to create a relationship, or drag an **edge endpoint** to reconnect. Double-click empty space to create a collection; double-click a card to browse documents.
4. **Compass view** — filter documents with JSON, browse schema + **keys**, switch between list / JSON / **table** views. Use **+ Key** to declare composite uniqueness; click **dup: N** to filter violating documents (`{"$keyViolation":"<key_id>"}`).
5. **Queries** — click **+ Query** on the canvas for the SQL editor (syntax highlight, Ctrl+Space intellisense, live validation + preview). Query cards show dashed dependency edges from source collections/queries. Double-click a query card to browse results in Compass (read-only).
6. **Canvas planes** — **Focus: Collections / Queries** toggles blur the inactive plane. Theme background animations stay sharp above the blur via a foreground veil.
7. **Background animations** — the same theme background effects as chat (synapse, rain, sparkles, etc.) show through the canvas graph area; Compass uses a lighter frosted overlay. Change the effect in **Settings → Theme → Background / Effect**.
8. **Cardinality** — each relationship has independent **from** and **to** cardinality selectors (One, Many, Zero or one). ER symbols at each end: `|` = one (required), crow's foot = many, bar + open circle = zero or one (optional). Edge color: accent for one-to-one, purple for many-to-many, default otherwise.
9. **World Excel I/O** — in **Worlds…**, export a world to `.xlsx` (one sheet per collection + hidden `_Atlas` meta sheet) or import with an auto-mapping wizard.

Deep link: `/atlas`

## Excel import / export

Export from **Worlds… → Export Excel** on any active world. The workbook contains:

| Sheet | Contents |
|-------|----------|
| `_Atlas` (hidden) | JSON metadata: world name, entities, relationships, canvas layout (nodes + clusters) |
| One per collection | Header row = field names; rows = documents (`_atlas_row_id` preserved) |

Import via **Import world from Excel…** in the Worlds manager:

1. Upload a `.xlsx` file
2. Review auto-discovered sheet → collection mappings (exact, fuzzy, or create-new)
3. Confirm per-sheet mode: **append**, **merge** (match on `_id`), or **replace**

Importing without a target world creates a new world from the file meta. Re-importing an exported file round-trips relationships and canvas positions when **Restore relationships & canvas** is checked.

Requires `openpyxl` (`pip install openpyxl`).

## Agent workflow

Use the **`manage_atlas`** tool for everything below. These are JSON **`action`** values inside that one tool — **not** separate tools named `describe_world`, `get_schema`, etc.

```
describe_world / find_world  →  get_schema (if fields unknown)  →  find / execute_query
```

**Do not** call `/api/atlas/*` via `app_api` — those routes are blocked and return an error pointing at `manage_atlas`.

**world_id** accepts a full UUID, 8-character prefix, or exact world name (case-insensitive). **entity_name** resolves collections the same way. Omit `world_id` only when the user has one world or means the default (most recently updated).

Call `get_schema` when field names or join keys are unknown (returns slugs + a sample document). Use `format=compact` or `fields=[...]` on `find` to save tokens. SQL preview returns up to 25 sample rows but `execute_query` / `total` reflects the full row count.

### manage_atlas actions

| Action | Description |
|--------|-------------|
| `list_worlds` | List all worlds |
| `find_world` | Find worlds by name substring |
| `create_world` | Create world (`name`) |
| `describe_world` | World snapshot + collections |
| `list_entities` | List collections in a world |
| `find_entity` | Find collections by name substring |
| `create_entity` | Create collection (`name` only — no columns required) |
| `get_schema` | Inferred fields + sample document |
| `find` | Query with `filter`, `limit`, `offset`, `format`, `fields` |
| `findOne` | First matching document |
| `countDocuments` | Count matches |
| `search` | Cross-collection text search within a world |
| `insertOne` | Insert document (`document` object) |
| `insertMany` | Batch insert (`documents` array) |
| `updateOne` | `filter` + `update` (plain merge or `$set`/`$unset`/`$inc`) |
| `updateMany` | Update all matches |
| `replaceOne` | Replace entire document |
| `deleteOne` / `deleteMany` | Delete by filter (`confirm: true` for large/unfiltered deletes) |
| `create_relationship` / `list_relationships` | Typed edges between collections |
| `list_clusters` / `create_cluster` / `assign_entity_to_cluster` | Canvas ringfence containers |
| `import_rows` / `export_csv` | CSV bulk import/export |
| `list_queries` | Saved SQL queries in a world |
| `create_query` | Create query (`name`, `sql_text`) — MySQL-flavored `SELECT` |
| `update_query` | Change saved query (`query_name` or `query_id`, `sql_text`, optional `rename`) |
| `execute_query` | Run saved query (`query_name`, `limit`, `offset`) — check `total` for full count |

Legacy aliases: `list_rows`→`find`, `add_row`→`insertOne`, `update_row`→`updateOne`, `delete_row`→`deleteOne`.

### Filter operators

| Operator | Example |
|----------|---------|
| Equality | `{"status": "active"}` |
| `$in` | `{"state": {"$in": ["NY", "CA"]}}` |
| `$contains` | `{"name": {"$contains": "smith"}}` |
| `$ne` | `{"status": {"$ne": "archived"}}` |
| `$gt` / `$gte` / `$lt` / `$lte` | `{"qty": {"$gt": 10}}` |
| `$keyViolation` | `{"$keyViolation": "<key_id>"}` — documents breaking key uniqueness |

### Agent cookbook

**Orient — what's in a world?**
```json
{"action": "describe_world", "world_id": "CG-BMS"}
```

**Read — active customers (compact, projected fields)**
```json
{"action": "find", "world_id": "CG-BMS", "entity_name": "Customers", "filter": {"status": "active"}, "fields": ["name", "email"], "format": "compact", "limit": 10}
```

**Read — count documents**
```json
{"action": "countDocuments", "world_id": "CG-BMS", "entity_name": "Orders"}
```

**Read — cross-collection search**
```json
{"action": "search", "world_id": "CG-BMS", "query": "battery management", "limit": 10}
```

**Write — insert a row**
```json
{"action": "insertOne", "world_id": "CG-BMS", "entity_name": "Customers", "document": {"name": "Alice", "email": "a@example.com"}}
```

**Write — update by _id**
```json
{"action": "updateOne", "entity_name": "Customers", "filter": {"_id": 3}, "update": {"$set": {"status": "archived"}}}
```

**Write — link collections**
```json
{"action": "create_relationship", "world_id": "CG-BMS", "from_entity_name": "Customers", "to_entity_name": "Orders", "from_field": "id", "to_field": "customer_id", "rel_type": "one_to_many"}
```

**Canvas — create cluster and assign collection**
```json
{"action": "create_cluster", "world_id": "CG-BMS", "name": "Work", "color": "blue"}
```
```json
{"action": "assign_entity_to_cluster", "world_id": "CG-BMS", "entity_name": "Customers", "cluster_name": "Work"}
```

**SQL — list saved queries**
```json
{"action": "list_queries", "world_id": "CG-BMS"}
```

**SQL — inspect schemas before a join**
```json
{"action": "get_schema", "world_id": "CG-BMS", "entity_name": "SIT_Siebel_BRM_Products"}
```
```json
{"action": "get_schema", "world_id": "CG-BMS", "entity_name": "SIT_Deal_Products"}
```

**SQL — update an existing query (join two collections)**
```json
{
  "action": "update_query",
  "world_id": "CG-BMS",
  "query_name": "Query 1",
  "sql_text": "SELECT a.*, b.deal_id FROM SIT_Siebel_BRM_Products a JOIN SIT_Deal_Products b ON a.part_number = b.part_number"
}
```

**SQL — run query and read full row count**
```json
{"action": "execute_query", "world_id": "CG-BMS", "query_name": "Query 1", "limit": 5}
```
The response includes `total` (all matching rows) and `documents` (up to `limit`).

## SQL query syntax

Atlas queries use MySQL-flavored `SELECT`. Reference collections and saved queries by name in `FROM` / `JOIN`:

| Form | Example | When to use |
|------|---------|-------------|
| **Macro (preferred)** | `FROM $("Missing Parts") x` | Names with spaces or special characters |
| Backticks | `` FROM `Missing Parts` x `` | Same as macro; still supported |
| Bare identifier | `FROM Customers c` | Simple names without spaces |

**Query-on-query** — reference another saved query the same way:

```sql
SELECT x.part_number, y.part
FROM $("Missing Parts") x
JOIN SIT_Siebel_BRM_Products y ON x.product_name = y.name
```

**Naming** — collection and query display names share one namespace per world (case-insensitive). You cannot create a query named `Customers` if a collection with that name already exists.

**Rename propagation** — renaming a collection or query automatically updates `sql_text` in every dependent query (`$("Old")`, `` `Old` ``, and unquoted `Old` references).

Use `get_schema` for column **slugs** before writing join keys. Always declare table aliases when joining (`x`, `y`, etc.).

## Agent troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Agent says `manage_atlas` / `get_schema` / `describe_world` is not in its tool list | RAG tool selection only injects ~8 tools per turn; `manage_atlas` is not always-on (unlike `app_api`) | Ask again mentioning **Atlas** or **collection**; or ensure Atlas tools are enabled in Settings. Keyword hints now force-include `manage_atlas` for atlas/world/query/join vocabulary. |
| `app_api` error: "Don't hit /api/atlas/* — use manage_atlas" | Atlas HTTP routes are intentionally blocked on `app_api` | Use `manage_atlas` with the appropriate `action` — the error message names actions, not separate tools. |
| Agent loops trying schemas | Used `app_api` repeatedly or never called `manage_atlas` | First call: `{"action":"describe_world","world_id":"<name>"}` then `get_schema` per collection. |
| Join fails / wrong columns | SQL uses display labels instead of slugs | `get_schema` returns **slugs** (e.g. `part_number`); original keys appear in the sample doc. Use slugs in SQL; engine maps common label variants. |
| Query "only has 25 rows" | UI preview caps at 25 rows | Full count is in `execute_query` → `total` and Compass meta ("Showing X of Y"). |

## HTTP API

```
GET/POST  /api/atlas/worlds
GET/POST  /api/atlas/worlds/{wid}/entities
GET       /api/atlas/worlds/{wid}/entities/{eid}/schema
POST      /api/atlas/worlds/{wid}/entities/{eid}/find
POST      /api/atlas/worlds/{wid}/entities/{eid}/findOne
POST      /api/atlas/worlds/{wid}/entities/{eid}/insertOne
POST      /api/atlas/worlds/{wid}/entities/{eid}/insertMany
POST      /api/atlas/worlds/{wid}/entities/{eid}/updateOne
POST      /api/atlas/worlds/{wid}/entities/{eid}/updateMany
POST      /api/atlas/worlds/{wid}/entities/{eid}/deleteOne
POST      /api/atlas/worlds/{wid}/entities/{eid}/deleteMany
POST      /api/atlas/worlds/{wid}/entities/{eid}/count
GET/PUT   /api/atlas/worlds/{wid}/canvas
GET/POST/PUT/DELETE  /api/atlas/worlds/{wid}/clusters[/{cid}]
GET/POST/PUT/DELETE  /api/atlas/worlds/{wid}/relationships[/{rid}]
GET       /api/atlas/worlds/{wid}/export.xlsx
POST      /api/atlas/worlds/{wid}/import/analyze
POST      /api/atlas/worlds/{wid}/import
POST      /api/atlas/worlds/import/analyze
POST      /api/atlas/worlds/import
```

Legacy row endpoints (`GET/POST/PUT/DELETE .../rows`) remain as thin wrappers.

## Data storage

| Location | Contents |
|----------|----------|
| `app.db` → `atlas_worlds` | World registry |
| `data/atlas/worlds/{id}.db` | Collections, documents (JSON), canvas layout, clusters, relationships |

**Note:** Worlds created before the JSON storage rewrite use the old column schema and must be recreated (delete `data/atlas/worlds/*.db` or create a new world).

## Relationships

Each end has its own cardinality: `one`, `many`, or `one_or_zero` (zero or one). Stored as composite `rel_type` (`{from}_to_{to}`, e.g. `one_or_zero_to_many`). Legacy types (`one_to_many`, `many_to_one`, `one_to_one`, `many_to_many`) remain valid.

| From | To | Typical semantics |
|------|-----|-------------------|
| one | many | `to_field` on many docs holds FK matching `from_field` |
| many | one | `from_field` on many docs holds FK matching `to_field` |
| one | one | Single reference each way |
| many | many | `from_field` / `to_field` hold arrays of referenced `_id` values |
| one_or_zero | * | Optional link — the from side may have zero or one related record |
| * | one_or_zero | Optional link — the to side may have zero or one related record |

API and tool calls accept `from_cardinality` + `to_cardinality` (preferred) or legacy `rel_type`. Responses include both cardinalities derived from storage.
