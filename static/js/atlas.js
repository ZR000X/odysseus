/**
 * Atlas — structured data worlds (canvas + compass).
 */
import uiModule from './ui.js';
import { mountCanvas, unmountCanvas } from './atlas-canvas.js';
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

function _showCanvas() {
  _view = 'canvas';
  _compassEntityId = null;
  const main = document.getElementById('atlas-main');
  if (!main) return;
  unmountCompass();
  main.innerHTML = '';
  _playViewEnter(main, 'atlas-canvas-enter');
  mountCanvas(main, {
    worldId: _selectedWorldId,
    worlds: _worlds,
    entities: _entities,
    onOpenEntity: (entityId, entityName) => _showCompass(entityId, entityName),
    onWorldChange: async (wid) => {
      _selectedWorldId = wid;
      await _loadEntities();
    },
  }).then(closeBtn => {
    closeBtn?.addEventListener('click', () => closePanel());
  });
}

function _showCompass(entityId, entityName) {
  _view = 'compass';
  _compassEntityId = entityId;
  _compassEntityName = entityName;
  const entity = _entities.find(e => e.id === entityId) || {
    id: entityId,
    name: entityName || 'Entity',
    description: '',
  };
  const main = document.getElementById('atlas-main');
  if (!main) return;
  unmountCanvas();
  main.innerHTML = '';
  _playViewEnter(main, 'atlas-compass-enter');
  mountCompass(main, {
    worldId: _selectedWorldId,
    entityId,
    entity,
    entityName: entity.name,
    onBack: async () => {
      await _loadEntities();
      _showCanvas();
    },
    onEntityUpdated: (updated) => {
      const idx = _entities.findIndex(e => e.id === updated.id);
      if (idx >= 0) _entities[idx] = updated;
      else _entities.push(updated);
      _compassEntityName = updated.name;
    },
  });
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
  if (_view === 'compass' && _compassEntityId) {
    _showCompass(_compassEntityId, _compassEntityName);
  } else {
    _showCanvas();
  }
}

export async function openPanel(opts = {}) {
  if (opts.worldId) _selectedWorldId = opts.worldId;
  if (opts.entityId) {
    _view = 'compass';
    _compassEntityId = opts.entityId;
  }
  if (!_open) {
    _buildPane();
    _open = true;
    document.getElementById('tool-atlas-btn')?.classList.add('active');
    document.body.classList.add('atlas-view');
  }
  try {
    await _refresh();
    if (opts.entityId) {
      const ent = _entities.find(e => e.id === opts.entityId);
      _showCompass(opts.entityId, ent?.name || 'Entity');
    }
  } catch (e) {
    uiModule.showError(e.message);
  }
}

export function closePanel() {
  _open = false;
  unmountCanvas();
  unmountCompass();
  document.getElementById('atlas-backdrop')?.remove();
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
