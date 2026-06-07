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
2. **Canvas view** — pan/zoom, drag collection cards, connect relationships. Double-click empty space to create a collection; double-click a card to browse documents.
3. **Compass view** — filter documents with JSON, browse schema, view collapsible JSON cards.
4. Background animations from chat remain visible (transparent canvas).

Deep link: `/atlas`

## Agent workflow

```
get_schema → find → updateOne / insertOne
```

Each document has an auto `_id`. Call `get_schema` before writing unfamiliar collections.

### manage_atlas actions

| Action | Description |
|--------|-------------|
| `list_worlds` | List worlds |
| `create_world` | Create world (`name`) |
| `list_entities` | List collections in a world |
| `create_entity` | Create collection (`name` only — no columns required) |
| `get_schema` | Inferred fields + sample document |
| `find` | Query with `filter` object, `limit`, `offset` |
| `findOne` | First matching document |
| `countDocuments` | Count matches |
| `insertOne` | Insert document (`document` object) |
| `insertMany` | Batch insert (`documents` array) |
| `updateOne` | `filter` + `update` (plain merge or `$set`/`$unset`/`$inc`) |
| `updateMany` | Update all matches |
| `replaceOne` | Replace entire document |
| `deleteOne` / `deleteMany` | Delete by filter (`confirm: true` for large/unfiltered deletes) |
| `create_relationship` / `list_relationships` | Typed edges between collections |
| `import_rows` / `export_csv` | CSV bulk import/export |

Legacy aliases: `list_rows`→`find`, `add_row`→`insertOne`, `update_row`→`updateOne`, `delete_row`→`deleteOne`.

### Examples

```json
{"action": "get_schema", "entity_name": "Customers"}
{"action": "find", "entity_name": "Customers", "filter": {"status": "active"}, "limit": 10}
{"action": "insertOne", "entity_name": "Customers", "document": {"name": "Alice", "email": "a@example.com"}}
{"action": "updateOne", "filter": {"_id": 3}, "update": {"$set": {"status": "archived"}}}
{"action": "updateMany", "filter": {"region": "EU"}, "update": {"$set": {"currency": "EUR"}}}
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
