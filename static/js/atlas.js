/**
 * Atlas — structured data worlds (canvas + compass).
 */
import uiModule from './ui.js';
import { mountCanvas, unmountCanvas, updateEntityCard, reloadCanvasData } from './atlas-canvas.js';
import { mountCompass, unmountCompass } from './atlas-compass.js';

const API_BASE = window.location.origin;
const VIEW_TRANSITION_MS = 300;
let _open = false;
let _worlds = [];
let _entities = [];
let _selectedWorldId = null;
let _view = 'canvas'; // canvas | compass
let _compassEntityId = null;
let _compassEntityName = '';
let _compassKind = 'entity'; // entity | query
let _canvasMounted = false;
let _escHandler = null;

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

async function _loadWorlds() {
  const data = await _fetch('/api/atlas/worlds?archived=false');
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
}

function _playViewEnter(main, className) {
  if (!main) return;
  main.classList.remove('atlas-compass-enter', 'atlas-canvas-enter');
  main.classList.add(className);
  setTimeout(() => main.classList.remove(className), VIEW_TRANSITION_MS);
}

function _setViewMode(mode) {
  document.body.classList.remove('atlas-canvas-mode', 'atlas-compass-mode');
  if (mode === 'canvas') {
    document.body.classList.add('atlas-canvas-mode');
  } else if (mode === 'compass') {
    document.body.classList.add('atlas-canvas-mode', 'atlas-compass-mode');
  }
}

function _removeEscHandler() {
  if (_escHandler) {
    document.removeEventListener('keydown', _escHandler);
    _escHandler = null;
  }
}

function _destroyCompassOverlay() {
  unmountCompass();
  _removeEscHandler();
  document.getElementById('atlas-compass-overlay')?.remove();
}

function _closeCompass() {
  _destroyCompassOverlay();
  _view = 'canvas';
  _compassEntityId = null;
  _setViewMode('canvas');
}

function _wireCompassOverlay(overlay) {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) _closeCompass();
  });
  _removeEscHandler();
  _escHandler = (e) => {
    if (e.key !== 'Escape') return;
    if (document.querySelector('.atlas-modal, .modal:not(.hidden)')) return;
    e.preventDefault();
    _closeCompass();
  };
  document.addEventListener('keydown', _escHandler);
}

async function _ensureCanvasMounted() {
  const main = document.getElementById('atlas-main');
  if (!main || _canvasMounted) return;
  _playViewEnter(main, 'atlas-canvas-enter');
  const closeBtn = await mountCanvas(main, {
    worldId: _selectedWorldId,
    worlds: _worlds,
    entities: _entities,
    onOpenEntity: (entityId, entityName) => _showCompass(entityId, entityName, 'entity'),
    onOpenQuery: (queryId, queryName) => _showCompass(queryId, queryName, 'query'),
    onWorldChange: async (wid) => {
      _selectedWorldId = wid;
      await _loadEntities();
    },
  });
  closeBtn?.addEventListener('click', () => closePanel());
  _canvasMounted = true;
}

async function _showCanvas() {
  _closeCompass();
  _setViewMode('canvas');
  await _ensureCanvasMounted();
}

function _mountCompassInOverlay(entityId, entityName, kind = 'entity') {
  const entity = kind === 'query'
    ? { id: entityId, name: entityName || 'Query', description: '' }
    : (_entities.find(e => e.id === entityId) || {
      id: entityId,
      name: entityName || 'Entity',
      description: '',
    });
  const pane = document.getElementById('atlas-pane');
  if (!pane) return;

  _destroyCompassOverlay();

  const overlay = document.createElement('div');
  overlay.id = 'atlas-compass-overlay';
  overlay.className = 'atlas-compass-overlay atlas-compass-enter';
  overlay.innerHTML = '<div class="atlas-compass-modal" id="atlas-compass-mount"></div>';
  pane.appendChild(overlay);
  setTimeout(() => overlay.classList.remove('atlas-compass-enter'), VIEW_TRANSITION_MS);

  const mountTarget = overlay.querySelector('#atlas-compass-mount');
  _wireCompassOverlay(overlay);

  mountCompass(mountTarget, {
    worldId: _selectedWorldId,
    entityId,
    entity,
    entityName: entity.name,
    kind,
    onBack: () => _closeCompass(),
    onEntityUpdated: (updated) => {
      const idx = _entities.findIndex(e => e.id === updated.id);
      if (idx >= 0) _entities[idx] = updated;
      else _entities.push(updated);
      _compassEntityName = updated.name;
      updateEntityCard(updated.id, { name: updated.name });
    },
    onEditQuery: kind === 'query' ? async () => {
      const { promptQuery } = await import('./atlas-modals.js');
      const catalog = await _fetch(`/api/atlas/worlds/${_selectedWorldId}/schema-catalog`);
      const q = await _fetch(`/api/atlas/worlds/${_selectedWorldId}/queries`).then(d =>
        (d.queries || []).find(x => x.id === entityId));
      const data = await promptQuery({
        worldId: _selectedWorldId,
        catalog,
        query: q,
        onValidate: (sql, qid) => _fetch(`/api/atlas/worlds/${_selectedWorldId}/queries/validate`, {
          method: 'POST',
          body: JSON.stringify({ sql_text: sql, query_id: qid, preview_limit: 25 }),
        }),
      });
      if (!data) return;
      await _fetch(`/api/atlas/worlds/${_selectedWorldId}/queries/${entityId}`, {
        method: 'PUT', body: JSON.stringify(data),
      });
      _compassEntityName = data.name;
      _mountCompassInOverlay(entityId, data.name, 'query');
    } : null,
  });
}

async function _showCompass(entityId, entityName, kind = 'entity') {
  _view = 'compass';
  _compassEntityId = entityId;
  _compassEntityName = entityName;
  _compassKind = kind;
  _setViewMode('compass');
  await _ensureCanvasMounted();
  _mountCompassInOverlay(entityId, entityName, kind);
}

function _buildPane() {
  document.getElementById('atlas-backdrop')?.remove();
  const backdrop = document.createElement('div');
  backdrop.className = 'atlas-backdrop';
  backdrop.id = 'atlas-backdrop';

  const pane = document.createElement('div');
  pane.id = 'atlas-pane';
  pane.className = 'atlas-pane';
  pane.innerHTML = `<div id="atlas-main" class="atlas-main"></div>`;
  backdrop.appendChild(pane);
  document.body.appendChild(backdrop);
}

async function _refresh() {
  await _loadWorlds();
  await _loadEntities();
  if (_canvasMounted) {
    await reloadCanvasData(_selectedWorldId, _worlds, _entities);
  }
  if (_view === 'compass' && _compassEntityId) {
    if (!_compassEntityName) {
      const ent = _entities.find(e => e.id === _compassEntityId);
      _compassEntityName = ent?.name || 'Entity';
    }
    await _ensureCanvasMounted();
    _mountCompassInOverlay(_compassEntityId, _compassEntityName, _compassKind);
  } else {
    await _showCanvas();
  }
}

export async function openPanel(opts = {}) {
  if (opts.worldId) _selectedWorldId = opts.worldId;
  if (opts.entityId) {
    _view = 'compass';
    _compassEntityId = opts.entityId;
    _compassEntityName = '';
  }
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
  _destroyCompassOverlay();
  unmountCanvas();
  _canvasMounted = false;
  document.getElementById('atlas-backdrop')?.remove();
  document.getElementById('tool-atlas-btn')?.classList.remove('active');
  document.body.classList.remove('atlas-view', 'atlas-canvas-mode', 'atlas-compass-mode');
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
