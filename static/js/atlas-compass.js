/**
 * Atlas Compass — MongoDB-style document browser.
 */
import uiModule from './ui.js';
import { renderDocumentCard } from './atlas-json-tree.js';

const API_BASE = window.location.origin;
const PAGE_SIZE = 50;

let _container = null;
let _worldId = null;
let _entityId = null;
let _entityName = '';
let _page = 0;
let _filter = {};
let _onBack = null;

async function _fetch(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: opts.body ? { 'Content-Type': 'application/json', ...(opts.headers || {}) } : (opts.headers || {}),
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || res.statusText);
  }
  return res.json();
}

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function _loadSchema(sidebar) {
  if (!sidebar || !_worldId || !_entityId) return;
  try {
    const schema = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/schema`);
    sidebar.innerHTML = `
      <div class="atlas-compass-schema-title">Schema</div>
      <div class="atlas-compass-schema-count">${schema.document_count} documents</div>
      ${(schema.fields || []).map(f => `
        <div class="atlas-schema-field" data-field="${_esc(f.slug)}" title="Click to filter">
          <span class="atlas-schema-field-name">${_esc(f.slug)}</span>
          <span class="atlas-schema-field-type">${_esc(f.inferred_type)}</span>
        </div>`).join('') || '<div class="atlas-empty">No fields yet</div>'}
    `;
    sidebar.querySelectorAll('.atlas-schema-field').forEach(el => {
      el.addEventListener('click', () => {
        const f = el.dataset.field;
        const input = _container?.querySelector('#atlas-compass-filter');
        if (input) {
          const cur = input.value.trim();
          let obj = {};
          try { obj = cur ? JSON.parse(cur) : {}; } catch { obj = {}; }
          obj[f] = '';
          input.value = JSON.stringify(obj, null, 2);
        }
      });
    });
  } catch (e) {
    sidebar.innerHTML = `<div class="atlas-empty">${_esc(e.message)}</div>`;
  }
}

async function _loadDocs() {
  const list = _container?.querySelector('#atlas-compass-docs');
  const meta = _container?.querySelector('#atlas-compass-meta');
  if (!list) return;
  list.innerHTML = '<div class="atlas-empty">Loading…</div>';
  try {
    const data = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/find`, {
      method: 'POST',
      body: JSON.stringify({ filter: _filter, limit: PAGE_SIZE, offset: _page * PAGE_SIZE }),
    });
    const docs = data.documents || [];
    const total = data.total || 0;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (meta) meta.textContent = `${_entityName} — ${total} documents (page ${_page + 1}/${pages})`;
    list.innerHTML = docs.length
      ? docs.map(d => renderDocumentCard(d)).join('')
      : '<div class="atlas-empty">No documents match this filter.</div>';
    const prev = _container?.querySelector('#atlas-compass-prev');
    const next = _container?.querySelector('#atlas-compass-next');
    if (prev) prev.disabled = _page <= 0;
    if (next) next.disabled = (_page + 1) * PAGE_SIZE >= total;
  } catch (e) {
    list.innerHTML = `<div class="atlas-empty">${_esc(e.message)}</div>`;
  }
}

function _wire() {
  _container?.querySelector('#atlas-compass-back')?.addEventListener('click', () => {
    if (_onBack) _onBack();
  });
  _container?.querySelector('#atlas-compass-apply')?.addEventListener('click', () => {
    const raw = _container?.querySelector('#atlas-compass-filter')?.value?.trim() || '{}';
    try {
      _filter = JSON.parse(raw);
      _page = 0;
      _loadDocs().catch(e => uiModule.showError(e.message));
    } catch {
      uiModule.showError('Invalid JSON filter');
    }
  });
  _container?.querySelector('#atlas-compass-prev')?.addEventListener('click', () => {
    if (_page > 0) { _page--; _loadDocs().catch(() => {}); }
  });
  _container?.querySelector('#atlas-compass-next')?.addEventListener('click', () => {
    _page++; _loadDocs().catch(() => {});
  });
  _container?.querySelector('#atlas-compass-export')?.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = `${API_BASE}/api/atlas/worlds/${_worldId}/entities/${_entityId}/export.csv`;
    a.download = `${_entityName.replace(/\s+/g, '_')}.csv`;
    a.click();
  });
  _container?.querySelector('#atlas-compass-refresh')?.addEventListener('click', async () => {
    await _loadSchema(_container?.querySelector('#atlas-compass-schema'));
    await _loadDocs();
  });
}

export function mountCompass(container, { worldId, entityId, entityName, onBack }) {
  _container = container;
  _worldId = worldId;
  _entityId = entityId;
  _entityName = entityName || 'Entity';
  _page = 0;
  _filter = {};
  _onBack = onBack;
  container.innerHTML = `
    <div class="atlas-compass atlas-chrome">
      <div class="atlas-compass-toolbar">
        <button type="button" class="admin-btn-sm" id="atlas-compass-back">← Canvas</button>
        <span class="atlas-compass-title">${_esc(_entityName)}</span>
        <div class="atlas-compass-toolbar-actions">
          <button type="button" class="admin-btn-sm" id="atlas-compass-export">Export CSV</button>
          <button type="button" class="admin-btn-sm" id="atlas-compass-refresh">Refresh</button>
          <button type="button" class="admin-btn-sm" id="atlas-compass-prev">‹</button>
          <button type="button" class="admin-btn-sm" id="atlas-compass-next">›</button>
        </div>
      </div>
      <div class="atlas-compass-filter-bar">
        <label>Filter <span class="atlas-filter-hint">JSON e.g. {"name":"Alice"}</span></label>
        <textarea id="atlas-compass-filter" class="atlas-compass-filter-input" rows="2">{}</textarea>
        <button type="button" class="admin-btn-sm" id="atlas-compass-apply">Apply</button>
      </div>
      <div class="atlas-compass-body">
        <aside id="atlas-compass-schema" class="atlas-compass-sidebar"></aside>
        <main class="atlas-compass-main">
          <div id="atlas-compass-meta" class="atlas-data-meta"></div>
          <div id="atlas-compass-docs" class="atlas-compass-docs"></div>
        </main>
      </div>
    </div>`;
  _wire();
  _loadSchema(container.querySelector('#atlas-compass-schema'));
  _loadDocs().catch(e => uiModule.showError(e.message));
}

export function unmountCompass() {
  _container = null;
}
