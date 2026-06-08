/**
 * Resolve Atlas schema slugs to actual document keys.
 * Mirrors services/atlas/ddl.py slugify().
 */

const RESERVED_SLUGS = new Set([
  '_atlas_row_id', '_atlas_created_at', '_atlas_updated_at', '_id', 'rowid',
]);

export function slugify(name) {
  let s = String(name ?? '').trim().toLowerCase();
  s = s.replace(/[^a-z0-9_]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  if (!s) return null;
  if (/^\d/.test(s)) s = `col_${s}`;
  if (RESERVED_SLUGS.has(s)) return null;
  return s;
}

/** @param {Record<string, unknown>} doc */
export function buildDocKeyIndex(doc) {
  const index = new Map();
  if (!doc || typeof doc !== 'object') return index;
  for (const key of Object.keys(doc)) {
    if (key.startsWith('_') && key !== '_id') continue;
    const slug = slugify(key);
    if (slug && !index.has(slug)) index.set(slug, key);
  }
  return index;
}

/** @param {Record<string, unknown>} doc @param {string} slug @param {Map<string,string>|null} index */
export function resolveDocKey(doc, slug, index = null) {
  if (!doc || !slug) return null;
  if (Object.prototype.hasOwnProperty.call(doc, slug)) return slug;
  const idx = index || buildDocKeyIndex(doc);
  return idx.get(slug) || null;
}

/** @param {Record<string, unknown>} doc @param {string} slug @param {Map<string,string>|null} index */
export function docHasField(doc, slug, index = null) {
  const key = resolveDocKey(doc, slug, index);
  return key != null && Object.prototype.hasOwnProperty.call(doc, key);
}

/** @param {Record<string, unknown>} doc @param {string} slug @param {Map<string,string>|null} index */
export function docGetField(doc, slug, index = null) {
  const key = resolveDocKey(doc, slug, index);
  if (key == null) return { key: null, value: undefined, has: false };
  return { key, value: doc[key], has: true };
}
