/**
 * Atlas — structured data worlds (MVP1).
 */
import uiModule from './ui.js';

const API_BASE = window.location.origin;
let _open = false;
let _worlds = [];
let _entities = [];
let _selectedWorldId = null;
let _selectedEntityId = null;
let _rowPage = 0;
const PAGE_SIZE = 50;

async function _fetch(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: opts.body && typeof opts.body === 'string'
      ? { 'Content-Type': 'application/json', ...(opts.headers || {}) }
      : (opts.headers || {}),
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || res.statusText);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function _loadWorlds() {
  const data = await _fetch('/api/atlas/worlds');
  _worlds = data.worlds || [];
  if (!_selectedWorldId && _worlds.length) {
    _selectedWorldId = _worlds[0].id;
  }
}

async function _loadEntities() {
  if (!_selectedWorldId) {
    _entities = [];
    return;
  }
  const data = await _fetch(`/api/atlas/worlds/${_selectedWorldId}/entities`);
  _entities = data.entities || [];
  if (_selectedEntityId && !_entities.find(e => e.id === _selectedEntityId)) {
    _selectedEntityId = null;
  }
}

async function _loadRows() {
  const body = document.getElementById('atlas-data-body');
  const meta = document.getElementById('atlas-data-meta');
  if (!body || !_selectedWorldId || !_selectedEntityId) {
    if (body) body.innerHTML = '<div class="atlas-empty">Select an entity to browse rows.</div>';
    if (meta) meta.textContent = '';
    return;
  }
  const entity = _entities.find(e => e.id === _selectedEntityId);
  const offset = _rowPage * PAGE_SIZE;
  const data = await _fetch(
    `/api/atlas/worlds/${_selectedWorldId}/entities/${_selectedEntityId}/rows?limit=${PAGE_SIZE}&offset=${offset}`
  );
  const attrs = entity?.attributes || [];
  const cols = ['_atlas_row_id', ...attrs.map(a => a.slug)];
  let html = '<div class="csv-table-wrap"><table class="csv-table atlas-table"><thead><tr>';
  for (const c of cols) {
    html += `<th>${_esc(c)}</th>`;
  }
  html += '</tr></thead><tbody>';
  for (const row of data.rows || []) {
    html += '<tr>';
    for (const c of cols) {
      html += `<td>${_esc(row[c] ?? '')}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table></div>';
  body.innerHTML = html;
  const total = data.total || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (meta) {
    meta.textContent = `${entity?.name || 'Entity'} — ${total} rows (page ${_rowPage + 1}/${pages})`;
  }
  const prev = document.getElementById('atlas-page-prev');
  const next = document.getElementById('atlas-page-next');
  if (prev) prev.disabled = _rowPage <= 0;
  if (next) next.disabled = (_rowPage + 1) * PAGE_SIZE >= total;
}

function _renderSidebar() {
  const worldsEl = document.getElementById('atlas-world-list');
  const entitiesEl = document.getElementById('atlas-entity-list');
  if (worldsEl) {
    worldsEl.innerHTML = _worlds.map(w => `
      <div class="atlas-list-item${w.id === _selectedWorldId ? ' active' : ''}" data-world-id="${w.id}">
        <span class="atlas-list-name">${_esc(w.name)}</span>
        <span class="atlas-list-meta">${w.entity_count} ent</span>
      </div>
    `).join('') || '<div class="atlas-empty">No worlds yet.</div>';
  }
  if (entitiesEl) {
    entitiesEl.innerHTML = _entities.map(e => `
      <div class="atlas-list-item${e.id === _selectedEntityId ? ' active' : ''}" data-entity-id="${e.id}">
        <span class="atlas-list-name">${_esc(e.name)}</span>
        <span class="atlas-list-meta">${e.row_count} rows</span>
      </div>
    `).join('') || '<div class="atlas-empty">No entities.</div>';
  }
}

async function _refresh() {
  await _loadWorlds();
  await _loadEntities();
  _renderSidebar();
  await _loadRows();
}

function _buildPane() {
  document.getElementById('atlas-pane')?.remove();
  const pane = document.createElement('div');
  pane.id = 'atlas-pane';
  pane.className = 'atlas-pane';
  pane.innerHTML = `
    <div class="atlas-header">
      <h2>Atlas</h2>
      <div class="atlas-header-actions">
        <button type="button" class="admin-btn-sm" id="atlas-new-world-btn">+ World</button>
        <button type="button" class="admin-btn-sm" id="atlas-new-entity-btn">+ Entity</button>
        <button type="button" class="atlas-close-btn" id="atlas-close-btn" title="Close">✕</button>
      </div>
    </div>
    <div class="atlas-body">
      <aside class="atlas-sidebar">
        <div class="atlas-sidebar-section">
          <div class="atlas-sidebar-title">Worlds</div>
          <div id="atlas-world-list" class="atlas-list"></div>
        </div>
        <div class="atlas-sidebar-section">
          <div class="atlas-sidebar-title">Entities</div>
          <div id="atlas-entity-list" class="atlas-list"></div>
        </div>
      </aside>
      <main class="atlas-main">
        <div class="atlas-toolbar">
          <span id="atlas-data-meta" class="atlas-data-meta"></span>
          <div class="atlas-toolbar-actions">
            <button type="button" class="admin-btn-sm" id="atlas-export-btn">Export CSV</button>
            <button type="button" class="admin-btn-sm" id="atlas-refresh-btn">Refresh</button>
            <button type="button" class="admin-btn-sm" id="atlas-page-prev">‹ Prev</button>
            <button type="button" class="admin-btn-sm" id="atlas-page-next">Next ›</button>
          </div>
        </div>
        <div id="atlas-data-body" class="atlas-data-body"></div>
      </main>
    </div>
  `;
  document.body.appendChild(pane);

  pane.querySelector('#atlas-close-btn')?.addEventListener('click', () => closePanel());
  pane.querySelector('#atlas-refresh-btn')?.addEventListener('click', () => _refresh().catch(e => uiModule.showError(e.message)));
  pane.querySelector('#atlas-page-prev')?.addEventListener('click', () => {
    if (_rowPage > 0) { _rowPage--; _loadRows().catch(() => {}); }
  });
  pane.querySelector('#atlas-page-next')?.addEventListener('click', () => {
    _rowPage++; _loadRows().catch(() => {});
  });
  pane.querySelector('#atlas-export-btn')?.addEventListener('click', async () => {
    if (!_selectedWorldId || !_selectedEntityId) return;
    const entity = _entities.find(e => e.id === _selectedEntityId);
    const a = document.createElement('a');
    a.href = `${API_BASE}/api/atlas/worlds/${_selectedWorldId}/entities/${_selectedEntityId}/export.csv`;
    a.download = `${(entity?.name || 'export').replace(/\s+/g, '_')}.csv`;
    a.click();
  });
  pane.querySelector('#atlas-new-world-btn')?.addEventListener('click', async () => {
    const name = prompt('World name:', 'New World');
    if (!name) return;
    try {
      await _fetch('/api/atlas/worlds', { method: 'POST', body: JSON.stringify({ name }) });
      await _refresh();
      uiModule.showToast('World created');
    } catch (e) {
      uiModule.showError(e.message);
    }
  });
  pane.querySelector('#atlas-new-entity-btn')?.addEventListener('click', async () => {
    if (!_selectedWorldId) { uiModule.showError('Select a world first'); return; }
    const name = prompt('Entity name:', 'Untitled');
    if (!name) return;
    const cols = prompt('Columns (comma-separated names):', 'id,name');
    if (cols === null) return;
    const attributes = cols.split(',').map((c, i) => ({
      name: c.trim(),
      type: 'text',
      primary_key: i === 0,
    })).filter(a => a.name);
    try {
      const e = await _fetch(`/api/atlas/worlds/${_selectedWorldId}/entities`, {
        method: 'POST',
        body: JSON.stringify({ name, attributes }),
      });
      _selectedEntityId = e.id;
      _rowPage = 0;
      await _refresh();
      uiModule.showToast('Entity created');
    } catch (err) {
      uiModule.showError(err.message);
    }
  });
  pane.querySelector('#atlas-world-list')?.addEventListener('click', (ev) => {
    const item = ev.target.closest('[data-world-id]');
    if (!item) return;
    _selectedWorldId = item.dataset.worldId;
    _selectedEntityId = null;
    _rowPage = 0;
    _refresh().catch(() => {});
  });
  pane.querySelector('#atlas-entity-list')?.addEventListener('click', (ev) => {
    const item = ev.target.closest('[data-entity-id]');
    if (!item) return;
    _selectedEntityId = item.dataset.entityId;
    _rowPage = 0;
    _loadRows().catch(() => {});
    _renderSidebar();
  });
}

export async function openPanel(opts = {}) {
  if (opts.worldId) _selectedWorldId = opts.worldId;
  if (opts.entityId) _selectedEntityId = opts.entityId;
  if (!_open) {
    _buildPane();
    _open = true;
    document.getElementById('tool-atlas-btn')?.classList.add('active');
    document.body.classList.add('atlas-view');
  }
  try {
    await _refresh();
  } catch (e) {
    uiModule.showError(e.message);
  }
}

export function closePanel() {
  _open = false;
  document.getElementById('atlas-pane')?.remove();
  document.getElementById('tool-atlas-btn')?.classList.remove('active');
  document.body.classList.remove('atlas-view');
}

export function togglePanel() {
  if (_open) closePanel();
  else openPanel();
}

export function isPanelOpen() {
  return _open;
}

const atlasModule = { openPanel, closePanel, togglePanel, isPanelOpen };
export default atlasModule;
window.atlasModule = atlasModule;
