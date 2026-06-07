/**
 * Atlas Compass — MongoDB-style document browser.
 */
import uiModule from './ui.js';
import { wireInlineField, escInline } from './atlas-inline.js';
import {
  renderListView, renderJsonView, renderTableView,
  wireScrollDelegation, expandAllChevrons,
} from './atlas-compass-views.js';
import { promptAddDocument, promptImportJson, promptEditDocument } from './atlas-modals.js';
import {
  toastFilterMatch, toastImportedCsv, toastImportedJson, toastDocumentAdded,
  toastCsvExported, toastRefreshed, toastBackOnMap, toastViewMode, toastAllLoaded,
  toastCopied, toastDocumentUpdated, toastDocumentDeleted,
} from './atlas-toast.js';

const API_BASE = window.location.origin;
const PAGE_SIZE = 50;

let _container = null;
let _worldId = null;
let _entityId = null;
let _entity = null;
let _filter = {};
let _viewMode = 'list';
let _cachedDocs = [];
let _cachedFields = [];
let _totalDocs = 0;
let _fetchOffset = 0;
let _loading = false;
let _allLoaded = false;
let _scrollObserver = null;
let _fetchAbort = null;
let _filterDebounce = null;
let _onBack = null;
let _onEntityUpdated = null;

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
  return escInline(s);
}

function _entityName() {
  return _entity?.name || 'Entity';
}

function _docById(docId) {
  const id = String(docId);
  return _cachedDocs.find(d => String(d._id ?? d._atlas_row_id) === id);
}

function _pickCsvFile() {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv,text/csv';
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (!file) { resolve(null); return; }
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => resolve(null);
      reader.readAsText(file);
    });
    input.click();
  });
}

function _updateMeta() {
  const meta = _container?.querySelector('#atlas-compass-meta');
  if (!meta) return;
  meta.textContent = `Showing ${_cachedDocs.length} of ${_totalDocs} document${_totalDocs === 1 ? '' : 's'}`;
}

function _getScrollEl() {
  return _container?.querySelector('#atlas-compass-scroll');
}

function _updateFilterValidity() {
  const input = _container?.querySelector('#atlas-compass-filter');
  if (!input) return;
  const raw = input.value.trim() || '{}';
  try {
    JSON.parse(raw);
    input.classList.remove('atlas-filter-invalid');
    input.classList.add('atlas-filter-valid');
  } catch {
    input.classList.remove('atlas-filter-valid');
    input.classList.add('atlas-filter-invalid');
  }
}

function _renderDocs(appendOnly = false) {
  const scroll = _getScrollEl();
  if (!scroll) return;

  if (appendOnly && _fetchOffset > PAGE_SIZE) {
    const sentinel = scroll.querySelector('#atlas-compass-sentinel');
    const loadingEl = scroll.querySelector('.atlas-compass-loading');
    loadingEl?.remove();
    const prevSentinel = sentinel;
    const chunk = _viewMode === 'json'
      ? renderJsonView(_cachedDocs.slice(-PAGE_SIZE))
      : _viewMode === 'table'
        ? '' // table re-renders full set for simplicity
        : renderListView(_cachedDocs.slice(-PAGE_SIZE));
    if (_viewMode === 'table') {
      scroll.classList.add('atlas-view-switch');
      scroll.innerHTML = renderTableView(_cachedDocs, _cachedFields)
        + (_loading ? '<div class="atlas-compass-loading">Loading more…</div>' : '')
        + '<div id="atlas-compass-sentinel" class="atlas-compass-sentinel"></div>';
      scroll.classList.remove('atlas-view-switch');
    } else if (chunk && prevSentinel) {
      prevSentinel.insertAdjacentHTML('beforebegin', chunk);
    }
    if (_loading) {
      scroll.querySelector('#atlas-compass-sentinel')?.insertAdjacentHTML('beforebegin', '<div class="atlas-compass-loading">Loading more…</div>');
    }
    _wireSentinel();
    _updateMeta();
    return;
  }

  scroll.classList.add('atlas-view-switch');
  let html = '';
  if (!_cachedDocs.length) {
    html = '<div class="atlas-empty">No documents match this filter.</div>';
  } else if (_viewMode === 'json') {
    html = renderJsonView(_cachedDocs);
  } else if (_viewMode === 'table') {
    html = renderTableView(_cachedDocs, _cachedFields);
  } else {
    html = renderListView(_cachedDocs);
  }
  if (_loading) html += '<div class="atlas-compass-loading">Loading more…</div>';
  html += '<div id="atlas-compass-sentinel" class="atlas-compass-sentinel"></div>';
  scroll.innerHTML = html;
  requestAnimationFrame(() => scroll.classList.remove('atlas-view-switch'));
  _wireSentinel();
  _updateMeta();
}

async function _applyFilter() {
  const raw = _container?.querySelector('#atlas-compass-filter')?.value?.trim() || '{}';
  try {
    _filter = JSON.parse(raw);
  } catch {
    uiModule.showError('Invalid JSON filter');
    return;
  }
  _fetchAbort?.abort();
  _getScrollEl()?.scrollTo(0, 0);
  await _fetchPage(false);
  toastFilterMatch(_totalDocs);
}

function _scheduleFilterApply() {
  clearTimeout(_filterDebounce);
  _filterDebounce = setTimeout(() => _applyFilter(), FILTER_DEBOUNCE_MS);
}

async function _fetchPage(append = false) {
  if (_loading || (_allLoaded && append)) return;
  _loading = true;
  if (!append) {
    _fetchOffset = 0;
    _cachedDocs = [];
    _allLoaded = false;
  }
  const scroll = _getScrollEl();
  if (scroll && !append) scroll.innerHTML = '<div class="atlas-empty">Loading…</div>';

  _fetchAbort?.abort();
  _fetchAbort = new AbortController();

  try {
    const res = await fetch(`${API_BASE}/api/atlas/worlds/${_worldId}/entities/${_entityId}/find`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filter: _filter, limit: PAGE_SIZE, offset: _fetchOffset }),
      signal: _fetchAbort.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || res.statusText);
    }
    const data = await res.json();
    const docs = data.documents || [];
    _totalDocs = data.total ?? docs.length;
    if (append) _cachedDocs.push(...docs);
    else _cachedDocs = docs;
    _fetchOffset += docs.length;
    if (_fetchOffset >= _totalDocs || docs.length < PAGE_SIZE) {
      _allLoaded = true;
      if (_totalDocs > 0 && _fetchOffset >= _totalDocs && append) toastAllLoaded();
    }
    _renderDocs(append);
  } catch (e) {
    if (e.name === 'AbortError') return;
    if (scroll) scroll.innerHTML = `<div class="atlas-empty">${_esc(e.message)}</div>`;
  } finally {
    _loading = false;
  }
}

function _wireSentinel() {
  _scrollObserver?.disconnect();
  const sentinel = _container?.querySelector('#atlas-compass-sentinel');
  const scroll = _getScrollEl();
  if (!sentinel || !scroll || _allLoaded) return;
  _scrollObserver = new IntersectionObserver((entries) => {
    if (entries.some(en => en.isIntersecting) && !_loading && !_allLoaded) {
      _fetchPage(true);
    }
  }, { root: scroll, rootMargin: '120px', threshold: 0 });
  _scrollObserver.observe(sentinel);
}

async function _loadSchema(sidebar) {
  if (!sidebar || !_worldId || !_entityId) return;
  try {
    const schema = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/schema`);
    _cachedFields = schema.fields || [];
    sidebar.innerHTML = `
      <div class="atlas-compass-schema-title">Schema</div>
      <div class="atlas-compass-schema-count">${schema.document_count} documents</div>
      ${(_cachedFields).map(f => `
        <div class="atlas-schema-field" data-field="${_esc(f.slug)}" title="Click to filter">
          <span class="atlas-schema-field-name">${_esc(f.slug)}</span>
          <span class="atlas-schema-field-type">${_esc(f.inferred_type)}</span>
        </div>`).join('') || '<div class="atlas-empty">No fields yet</div>'}
    `;
  } catch (e) {
    sidebar.innerHTML = `<div class="atlas-empty">${_esc(e.message)}</div>`;
  }
}

async function _editDocument(docId) {
  const doc = _docById(docId);
  if (!doc) return;
  const data = await promptEditDocument(doc);
  if (!data) return;
  try {
    await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/replaceOne`, {
      method: 'POST',
      body: JSON.stringify({ filter: { _id: data.docId }, replacement: data.document }),
    });
    const idx = _cachedDocs.findIndex(d => String(d._id ?? d._atlas_row_id) === String(docId));
    if (idx >= 0) _cachedDocs[idx] = { ...data.document, _id: data.docId };
    _renderDocs(false);
    toastDocumentUpdated();
  } catch (e) {
    uiModule.showError(e.message);
  }
}

async function _copyDocument(docId) {
  const doc = _docById(docId);
  if (!doc) return;
  try {
    const body = { ...doc };
    delete body._atlas_created_at;
    delete body._atlas_updated_at;
    await navigator.clipboard.writeText(JSON.stringify(body, null, 2));
    toastCopied();
  } catch { /* ignore */ }
}

async function _deleteDocument(docId) {
  const ok = await uiModule.styledConfirm('Delete this document?', { confirmText: 'Delete', danger: true });
  if (!ok) return;
  try {
    await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/deleteOne`, {
      method: 'POST',
      body: JSON.stringify({ filter: { _id: docId } }),
    });
    _cachedDocs = _cachedDocs.filter(d => String(d._id ?? d._atlas_row_id) !== String(docId));
    _totalDocs = Math.max(0, _totalDocs - 1);
    _renderDocs(false);
    toastDocumentDeleted();
  } catch (e) {
    uiModule.showError(e.message);
  }
}

function _wireScrollActions() {
  const scroll = _getScrollEl();
  wireScrollDelegation(scroll, {
    onEdit: (id) => _editDocument(id),
    onCopy: (id) => _copyDocument(id),
    onDelete: (id) => _deleteDocument(id),
  });
}

function _setViewMode(mode) {
  _viewMode = mode;
  _container?.querySelectorAll('.atlas-view-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.view === mode);
  });
  toastViewMode(mode);
  _renderDocs(false);
}

function _wireEntityHeader() {
  const nameEl = _container?.querySelector('.atlas-inline-name');
  const descEl = _container?.querySelector('.atlas-inline-desc');
  wireInlineField(nameEl, {
    getValue: () => _entity?.name || '',
    onSave: async (name) => {
      const updated = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}`, {
        method: 'PUT', body: JSON.stringify({ name }),
      });
      _entity = updated;
      if (_onEntityUpdated) _onEntityUpdated(updated);
    },
  });
  wireInlineField(descEl, {
    multiline: true,
    placeholder: 'Click to add a description…',
    getValue: () => _entity?.description || '',
    onSave: async (description) => {
      const updated = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}`, {
        method: 'PUT', body: JSON.stringify({ description }),
      });
      _entity = updated;
      if (_onEntityUpdated) _onEntityUpdated(updated);
    },
  });
}

function _wire() {
  _container?.querySelector('#atlas-compass-back')?.addEventListener('click', () => {
    toastBackOnMap();
    if (_onBack) _onBack();
  });

  _container?.querySelectorAll('.atlas-view-tab').forEach(tab => {
    tab.addEventListener('click', () => _setViewMode(tab.dataset.view));
  });

  _container?.querySelector('#atlas-expand-all')?.addEventListener('click', () => {
    expandAllChevrons(_getScrollEl(), true);
  });
  _container?.querySelector('#atlas-collapse-all')?.addEventListener('click', () => {
    expandAllChevrons(_getScrollEl(), false);
  });

  const filterInput = _container?.querySelector('#atlas-compass-filter');
  filterInput?.addEventListener('input', () => _updateFilterValidity());
  filterInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      _applyFilter();
    }
  });

  _container?.querySelector('#atlas-compass-apply')?.addEventListener('click', () => _applyFilter());

  _container?.querySelector('#atlas-compass-schema')?.addEventListener('click', (e) => {
    const field = e.target.closest('.atlas-schema-field');
    if (!field || !filterInput) return;
    let obj = {};
    try { obj = JSON.parse(filterInput.value.trim() || '{}'); } catch { obj = {}; }
    obj[field.dataset.field] = '';
    filterInput.value = JSON.stringify(obj);
    _updateFilterValidity();
  });

  _container?.querySelector('#atlas-compass-export')?.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = `${API_BASE}/api/atlas/worlds/${_worldId}/entities/${_entityId}/export.csv`;
    a.download = `${_entityName().replace(/\s+/g, '_')}.csv`;
    a.click();
    toastCsvExported();
  });

  _container?.querySelector('#atlas-compass-import-csv')?.addEventListener('click', async () => {
    const csv = await _pickCsvFile();
    if (!csv) return;
    try {
      const stats = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/import`, {
        method: 'POST', body: JSON.stringify({ mode: 'append', csv }),
      });
      toastImportedCsv(stats.rows_inserted || 0, stats.rows_failed || 0);
      await _loadSchema(_container?.querySelector('#atlas-compass-schema'));
      _getScrollEl()?.scrollTo(0, 0);
      await _fetchPage(false);
    } catch (e) { uiModule.showError(e.message); }
  });

  _container?.querySelector('#atlas-compass-import-json')?.addEventListener('click', async () => {
    const data = await promptImportJson();
    if (!data?.documents?.length) return;
    try {
      const result = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/insertMany`, {
        method: 'POST', body: JSON.stringify({ documents: data.documents }),
      });
      toastImportedJson(result.inserted_count ?? data.documents.length);
      await _loadSchema(_container?.querySelector('#atlas-compass-schema'));
      _getScrollEl()?.scrollTo(0, 0);
      await _fetchPage(false);
    } catch (e) { uiModule.showError(e.message); }
  });

  _container?.querySelector('#atlas-compass-add-doc')?.addEventListener('click', async () => {
    const data = await promptAddDocument();
    if (!data?.document) return;
    try {
      await _fetch(`/api/atlas/worlds/${_worldId}/entities/${_entityId}/insertOne`, {
        method: 'POST', body: JSON.stringify({ document: data.document }),
      });
      toastDocumentAdded();
      await _loadSchema(_container?.querySelector('#atlas-compass-schema'));
      await _fetchPage(false);
    } catch (e) { uiModule.showError(e.message); }
  });

  _container?.querySelector('#atlas-compass-refresh')?.addEventListener('click', async () => {
    await _loadSchema(_container?.querySelector('#atlas-compass-schema'));
    _getScrollEl()?.scrollTo(0, 0);
    await _fetchPage(false);
    toastRefreshed();
  });
}

export function mountCompass(container, {
  worldId, entityId, entity, entityName, onBack, onEntityUpdated,
}) {
  _container = container;
  _worldId = worldId;
  _entityId = entityId;
  _entity = entity || { id: entityId, name: entityName || 'Entity', description: '' };
  _filter = {};
  _viewMode = 'list';
  _cachedDocs = [];
  _totalDocs = 0;
  _fetchOffset = 0;
  _allLoaded = false;
  _onBack = onBack;
  _onEntityUpdated = onEntityUpdated;

  container.innerHTML = `
    <div class="atlas-compass atlas-chrome atlas-compass-enter">
      <div class="atlas-compass-sticky">
        <div class="atlas-compass-toolbar">
          <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-compass-back">← Canvas</button>
          <div class="atlas-compass-entity-header">
            <div class="atlas-inline-field atlas-inline-name" data-field="name" tabindex="0">${_esc(_entity.name)}</div>
            <div class="atlas-inline-field atlas-inline-desc" data-field="description" tabindex="0">${_esc(_entity.description || '')}</div>
          </div>
          <div class="atlas-compass-toolbar-actions">
            <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-compass-add-doc">+ Document</button>
            <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-compass-import-csv">Import CSV</button>
            <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-compass-import-json">Import JSON</button>
            <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-compass-export">Export CSV</button>
            <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-compass-refresh">Refresh</button>
          </div>
        </div>
        <div class="atlas-compass-filter-bar">
          <label>Filter <span class="atlas-filter-hint">JSON · Enter to apply</span></label>
          <textarea id="atlas-compass-filter" class="atlas-compass-filter-input" rows="2">{}</textarea>
          <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-compass-apply">Find</button>
        </div>
        <div class="atlas-compass-view-bar">
          <div class="atlas-view-tabs">
            <button type="button" class="atlas-view-tab active atlas-btn-press" data-view="list">List</button>
            <button type="button" class="atlas-view-tab atlas-btn-press" data-view="json">JSON</button>
            <button type="button" class="atlas-view-tab atlas-btn-press" data-view="table">Table</button>
          </div>
          <div class="atlas-view-extra">
            <button type="button" class="atlas-link-btn" id="atlas-expand-all">Expand all</button>
            <span class="atlas-view-sep">·</span>
            <button type="button" class="atlas-link-btn" id="atlas-collapse-all">Collapse all</button>
          </div>
        </div>
      </div>
      <div class="atlas-compass-body">
        <aside id="atlas-compass-schema" class="atlas-compass-sidebar"></aside>
        <div class="atlas-compass-results">
          <div id="atlas-compass-meta" class="atlas-compass-meta"></div>
          <div id="atlas-compass-scroll" class="atlas-compass-scroll"></div>
        </div>
      </div>
    </div>`;

  _wire();
  _wireEntityHeader();
  _wireScrollActions();
  if (!_entity.description) {
    const descEl = _container.querySelector('.atlas-inline-desc');
    if (descEl && !descEl.textContent.trim()) {
      descEl.classList.add('atlas-inline-empty');
      descEl.textContent = 'Click to add a description…';
    }
  }
  _loadSchema(container.querySelector('#atlas-compass-schema'));
  _fetchPage(false).catch(e => uiModule.showError(e.message));

  requestAnimationFrame(() => {
    container.querySelector('.atlas-compass')?.classList.remove('atlas-compass-enter');
  });
}

export function unmountCompass() {
  _scrollObserver?.disconnect();
  _scrollObserver = null;
  _fetchAbort?.abort();
  clearTimeout(_filterDebounce);
  _container = null;
}
