# Atlas

Atlas is Odysseus's MongoDB-style document store: **worlds** of **collections** (entities) and **documents**, stored locally in SQLite, browsable on an Obsidian-like canvas, drill-down in a Compass-style viewer, and readable/writable from chat via `manage_atlas`.

## Concepts

| Concept | Description |
|---------|-------------|
| **World** | Isolated data universe. Each world has its own SQLite file under `data/atlas/worlds/{id}.db`. |
| **Collection (entity)** | Named group of documents. Schemaless — fields are inferred from data. |
| **Document** | JSON object with auto `_id` (`_atlas_row_id` internally). |
| **Field** | Inferred from documents; shown in Compass schema sidebar and `get_schema`. |
| **Relationship** | Typed edge (1:1, 1:N, N:M) with field mapping between collections. |

## Using the UI

1. Open **Atlas** from the sidebar (Tools).
2. **Canvas view** — pan/zoom, drag collection cards, connect relationships. Drag from a collection port to another to create a relationship, or drag an **edge endpoint** (circle at either end) to reconnect it to a different port. Double-click empty space to create a collection; double-click a card to browse documents.
3. **Compass view** — filter documents with JSON, browse schema, view collapsible JSON cards.
4. **Background animations** — the same theme background effects as chat (synapse, rain, sparkles, etc.) show through the canvas graph area; Compass uses a lighter frosted overlay. Change the effect in **Settings → Theme → Background / Effect**.
5. **Cardinality symbols** — ER notation at each relationship end: `|` = one, crow's foot = many. `one_to_many` shows one on the from side and many on the to side; `one_to_one` shows one at both ends; `many_to_many` shows many at both ends.

Deep link: `/atlas`

## Agent workflow

```
describe_world / find_world  →  find / countDocuments  →  updateOne / insertOne
```

**world_id** accepts a full UUID, 8-character prefix, or exact world name (case-insensitive). **entity_name** resolves collections the same way. Omit `world_id` only when the user has one world or means the default (most recently updated).

Call `get_schema` only when field names are unknown. Use `format=compact` or `fields=[...]` on `find` to save tokens.

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
| `import_rows` / `export_csv` | CSV bulk import/export |

Legacy aliases: `list_rows`→`find`, `add_row`→`insertOne`, `update_row`→`updateOne`, `delete_row`→`deleteOne`.

### Filter operators

| Operator | Example |
|----------|---------|
| Equality | `{"status": "active"}` |
| `$in` | `{"state": {"$in": ["NY", "CA"]}}` |
| `$contains` | `{"name": {"$contains": "smith"}}` |
| `$ne` | `{"status": {"$ne": "archived"}}` |
| `$gt` / `$gte` / `$lt` / `$lte` | `{"qty": {"$gt": 10}}` |

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
GET/POST/PUT/DELETE  /api/atlas/worlds/{wid}/relationships[/{rid}]
```

Legacy row endpoints (`GET/POST/PUT/DELETE .../rows`) remain as thin wrappers.

## Data storage

| Location | Contents |
|----------|----------|
| `app.db` → `atlas_worlds` | World registry |
| `data/atlas/worlds/{id}.db` | Collections, documents (JSON), canvas layout, relationships |

**Note:** Worlds created before the JSON storage rewrite use the old column schema and must be recreated (delete `data/atlas/worlds/*.db` or create a new world).

## Relationships

| Type | Semantics |
|------|-----------|
| `one_to_many` | `from_entity` is "one"; `to_field` on many docs holds FK matching `from_field` |
| `one_to_one` | Single reference each way |
| `many_to_many` | `from_field` / `to_field` hold arrays of referenced `_id` values |
