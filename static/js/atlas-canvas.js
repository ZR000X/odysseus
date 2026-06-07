/**
 * Atlas world canvas — Obsidian-style pan/zoom entity graph.
 */
import uiModule from './ui.js';
import { promptEntity, promptRelationship, promptWorld, promptEditEntity, openWorldsManager } from './atlas-modals.js';
import {
  toastBrowsing, toastWorldCreated, toastCollectionCreated, toastCollectionUpdated,
  toastConnectionLocked, toastWorldSwitched,
  toastWorldArchived, toastWorldRestored, toastWorldDeleted, toastWorldRenamed,
} from './atlas-toast.js';

const API_BASE = window.location.origin;
const PORT_ANCHORS = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'];
const MOVE_THRESHOLD = 5;

let _container = null;
let _worldId = null;
let _worlds = [];
let _entities = [];
let _relationships = [];
let _nodes = [];
let _panX = 0;
let _panY = 0;
let _zoom = 1;
let _onOpenEntity = null;
let _onWorldChange = null;
let _saveTimer = null;
let _portDrag = null;

async function _fetch(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
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

function _scheduleSave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(async () => {
    if (!_worldId) return;
    try {
      const payload = _nodes.map(n => ({
        entity_id: n.entity_id,
        x: n.x, y: n.y, w: n.w, h: n.h,
        z_index: n.z_index || 0,
      }));
      await _fetch(`/api/atlas/worlds/${_worldId}/canvas`, {
        method: 'PUT',
        body: JSON.stringify({ nodes: payload }),
      });
    } catch (e) {
      console.warn('canvas save failed', e);
    }
  }, 400);
}

function _nodeForEntity(entityId) {
  return _nodes.find(x => x.entity_id === entityId);
}

function _portPosition(entityId, anchor) {
  const n = _nodeForEntity(entityId);
  if (!n) return { x: 0, y: 0 };
  const a = (anchor || 'e').toLowerCase();
  const legacy = { top: 'n', right: 'e', bottom: 's', left: 'w' };
  const key = legacy[a] || a;
  const cx = n.x + n.w / 2;
  const cy = n.y + n.h / 2;
  switch (key) {
    case 'n': return { x: cx, y: n.y };
    case 'ne': return { x: n.x + n.w, y: n.y };
    case 'e': return { x: n.x + n.w, y: cy };
    case 'se': return { x: n.x + n.w, y: n.y + n.h };
    case 's': return { x: cx, y: n.y + n.h };
    case 'sw': return { x: n.x, y: n.y + n.h };
    case 'w': return { x: n.x, y: cy };
    case 'nw': return { x: n.x, y: n.y };
    default: return { x: cx, y: cy };
  }
}

function _renderEdges(svg) {
  if (!svg) return;
  const paths = _relationships.map(r => {
    const from = _portPosition(r.from_entity_id, r.from_anchor);
    const to = _portPosition(r.to_entity_id, r.to_anchor);
    const mx = (from.x + to.x) / 2;
    const d = `M ${from.x} ${from.y} C ${mx} ${from.y}, ${mx} ${to.y}, ${to.x} ${to.y}`;
    const color = r.rel_type === 'one_to_one' ? 'var(--accent)' : r.rel_type === 'many_to_many' ? '#f0abfc' : 'var(--fg)';
    return `<path class="atlas-edge atlas-edge-draw" data-rel-id="${r.id}" d="${d}" stroke="${color}" fill="none" stroke-width="2" opacity="0.55"/>`;
  }).join('');
  svg.innerHTML = paths;
}

function _portMarkup() {
  return PORT_ANCHORS.map(a =>
    `<div class="atlas-card-port atlas-card-port-${a}" data-side="${a}" data-anchor="${a}"></div>`
  ).join('');
}

async function _ensureWorld() {
  if (_worldId) return true;
  const data = await promptWorld();
  if (!data) return false;
  const w = await _fetch('/api/atlas/worlds', { method: 'POST', body: JSON.stringify(data) });
  _worlds.unshift(w);
  _worldId = w.id;
  _updateWorldSelect();
  if (_onWorldChange) _onWorldChange(_worldId);
  _renderEmptyState();
  return true;
}

async function _createEntityAt(x, y) {
  if (!(await _ensureWorld())) return;
  const data = await promptEntity();
  if (!data) return;
  try {
    const ent = await _fetch(`/api/atlas/worlds/${_worldId}/entities`, {
      method: 'POST',
      body: JSON.stringify({ name: data.name }),
    });
    _nodes.push({
      entity_id: ent.id,
      name: ent.name,
      row_count: 0,
      x, y, w: 200, h: 120, z_index: 0,
    });
    _entities.push(ent);
    _renderCards(_container?.querySelector('#atlas-canvas-world'));
    _renderEmptyState();
    _scheduleSave();
    toastCollectionCreated();
  } catch (err) {
    uiModule.showError(err.message);
  }
}

function _renderEmptyState() {
  const surface = _container?.querySelector('#atlas-canvas-surface');
  if (!surface) return;
  surface.querySelector('.atlas-canvas-empty')?.remove();
  if (_worlds.length) return;
  const el = document.createElement('div');
  el.className = 'atlas-canvas-empty';
  el.innerHTML = `
    <div class="atlas-canvas-empty-inner atlas-chrome">
      <p>No worlds yet. Create one to start building your data graph.</p>
      <button type="button" class="admin-btn-sm" id="atlas-empty-world-btn" style="background:var(--accent);color:var(--bg)">+ Create your first world</button>
    </div>`;
  el.querySelector('#atlas-empty-world-btn')?.addEventListener('click', async () => {
    if (await _ensureWorld()) {
      await _refresh();
      toastWorldCreated();
    }
  });
  surface.appendChild(el);
}

function _renderCards(worldEl) {
  if (!worldEl) return;
  worldEl.querySelectorAll('.atlas-canvas-card').forEach(el => el.remove());
  _nodes.forEach((n, idx) => {
    const card = document.createElement('div');
    card.className = 'atlas-canvas-card atlas-chrome atlas-card-enter';
    card.style.animationDelay = `${Math.min(idx * 40, 400)}ms`;
    card.dataset.entityId = n.entity_id;
    card.style.cssText = `left:${n.x}px;top:${n.y}px;width:${n.w}px;min-height:${n.h}px`;
    card.innerHTML = `
      ${_portMarkup()}
      <div class="atlas-card-header">
        <div class="atlas-card-title">${_esc(n.name)}</div>
        <button type="button" class="atlas-card-edit" title="Edit collection" aria-label="Edit collection">✎</button>
      </div>
      <div class="atlas-card-meta">${n.row_count || 0} docs</div>`;
    _wireCardDrag(card, n);
    _wirePortDrag(card, n);
    card.querySelector('.atlas-card-edit')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      const entity = _entities.find(x => x.id === n.entity_id) || { id: n.entity_id, name: n.name };
      const data = await promptEditEntity(entity);
      if (!data || !_worldId) return;
      try {
        const updated = await _fetch(`/api/atlas/worlds/${_worldId}/entities/${n.entity_id}`, {
          method: 'PUT',
          body: JSON.stringify(data),
        });
        n.name = updated.name;
        const idx = _entities.findIndex(x => x.id === n.entity_id);
        if (idx >= 0) _entities[idx] = updated;
        card.querySelector('.atlas-card-title').textContent = updated.name;
        toastCollectionUpdated();
      } catch (err) {
        uiModule.showError(err.message);
      }
    });
    worldEl.appendChild(card);
  });
  _renderEdges(_container?.querySelector('#atlas-canvas-svg'));
}

function _wireCardDrag(card, node) {
  let dragging = false;
  let moved = false;
  let sx = 0; let sy = 0; let ox = 0; let oy = 0;
  card.addEventListener('pointerdown', (e) => {
    if (e.target.classList.contains('atlas-card-port') || e.target.closest('.atlas-card-edit')) return;
    dragging = true;
    moved = false;
    sx = e.clientX; sy = e.clientY;
    ox = node.x; oy = node.y;
    card.setPointerCapture(e.pointerId);
    e.stopPropagation();
  });
  card.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - sx;
    const dy = e.clientY - sy;
    if (!moved && Math.hypot(dx, dy) > MOVE_THRESHOLD) {
      moved = true;
      card.classList.add('atlas-card-dragging');
    }
    if (!moved) return;
    node.x = ox + dx / _zoom;
    node.y = oy + dy / _zoom;
    card.style.left = `${node.x}px`;
    card.style.top = `${node.y}px`;
    _renderEdges(_container?.querySelector('#atlas-canvas-svg'));
    if (_portDrag) _updateDragLine(_portDrag.cursorX, _portDrag.cursorY, _portDrag.overValid);
  });
  card.addEventListener('pointerup', (e) => {
    if (!dragging) return;
    dragging = false;
    card.classList.remove('atlas-card-dragging');
    if (moved) {
      e.preventDefault();
      _scheduleSave();
      return;
    }
    if (e.target.closest('.atlas-card-edit') || e.target.closest('.atlas-card-port')) return;
    card.classList.add('atlas-card-open-flash');
    setTimeout(() => {
      card.classList.remove('atlas-card-open-flash');
      if (_onOpenEntity) {
        toastBrowsing(node.name);
        _onOpenEntity(node.entity_id, node.name);
      }
    }, 150);
  });
  card.addEventListener('pointercancel', () => {
    dragging = false;
    moved = false;
    card.classList.remove('atlas-card-dragging');
  });
}

function _surfaceToWorld(clientX, clientY) {
  const surface = _container?.querySelector('#atlas-canvas-surface');
  if (!surface) return { x: 0, y: 0 };
  const rect = surface.getBoundingClientRect();
  return {
    x: (clientX - rect.left - _panX) / _zoom,
    y: (clientY - rect.top - _panY) / _zoom,
  };
}

function _getDragLineSvg() {
  const world = _container?.querySelector('#atlas-canvas-world');
  if (!world) return null;
  let svg = world.querySelector('#atlas-canvas-drag-svg');
  if (!svg) {
    svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'atlas-canvas-drag-svg';
    svg.classList.add('atlas-canvas-drag-line');
    world.appendChild(svg);
  } else if (svg.parentElement === world && svg !== world.lastElementChild) {
    world.appendChild(svg);
  }
  return svg;
}

function _updateDragLine(cursorX, cursorY, overValid = false) {
  if (!_portDrag) return;
  const svg = _getDragLineSvg();
  if (!svg) return;
  const from = _portPosition(_portDrag.fromEntityId, _portDrag.fromAnchor);
  const mx = (from.x + cursorX) / 2;
  const d = `M ${from.x} ${from.y} C ${mx} ${from.y}, ${mx} ${cursorY}, ${cursorX} ${cursorY}`;
  const stroke = overValid ? '#86efac' : 'var(--accent)';
  svg.innerHTML = `<path d="${d}" stroke="${stroke}" fill="none" stroke-width="2.5" stroke-dasharray="8 5" opacity="0.95"/>`;
}

function _clearDragLine() {
  _container?.querySelector('#atlas-canvas-drag-svg')?.remove();
  _container?.querySelectorAll('.atlas-port-drop-target').forEach(el => {
    el.classList.remove('atlas-port-drop-target');
  });
}

function _wirePortDrag(card, node) {
  card.querySelectorAll('.atlas-card-port').forEach(port => {
    port.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      e.preventDefault();
      const anchor = port.dataset.anchor || 'e';
      const pos = _portPosition(node.entity_id, anchor);
      port.setPointerCapture(e.pointerId);
      _portDrag = {
        fromEntityId: node.entity_id,
        fromAnchor: anchor,
        startX: pos.x,
        startY: pos.y,
        cursorX: pos.x,
        cursorY: pos.y,
        pointerId: e.pointerId,
        overValid: false,
      };
      _updateDragLine(pos.x, pos.y, false);
      document.addEventListener('pointermove', _onPortPointerMove);
      document.addEventListener('pointerup', _onPortPointerUp);
      document.addEventListener('pointercancel', _onPortPointerUp);
    });
  });
}

function _onPortPointerMove(e) {
  if (!_portDrag) return;
  const w = _surfaceToWorld(e.clientX, e.clientY);
  _portDrag.cursorX = w.x;
  _portDrag.cursorY = w.y;
  _container?.querySelectorAll('.atlas-port-drop-target').forEach(el => {
    el.classList.remove('atlas-port-drop-target');
  });
  const el = document.elementFromPoint(e.clientX, e.clientY);
  const port = el?.closest?.('.atlas-card-port');
  let overValid = false;
  if (port) {
    const card = port.closest('.atlas-canvas-card');
    if (card && card.dataset.entityId !== _portDrag.fromEntityId) {
      port.classList.add('atlas-port-drop-target');
      overValid = true;
    }
  }
  _portDrag.overValid = overValid;
  _updateDragLine(w.x, w.y, overValid);
}

async function _onPortPointerUp(e) {
  document.removeEventListener('pointermove', _onPortPointerMove);
  document.removeEventListener('pointerup', _onPortPointerUp);
  document.removeEventListener('pointercancel', _onPortPointerUp);
  if (!_portDrag) return;
  const drag = _portDrag;
  _portDrag = null;
  _clearDragLine();

  const el = document.elementFromPoint(e.clientX, e.clientY);
  const port = el?.closest?.('.atlas-card-port');
  const card = port?.closest?.('.atlas-canvas-card');
  if (!port || !card || card.dataset.entityId === drag.fromEntityId) return;

  const toEntityId = card.dataset.entityId;
  const toAnchor = port.dataset.anchor || 'w';
  const data = await promptRelationship(_entities, drag.fromEntityId, toEntityId, {
    from_anchor: drag.fromAnchor,
    to_anchor: toAnchor,
  });
  if (!data) return;
  try {
    await _fetch(`/api/atlas/worlds/${_worldId}/relationships`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
    await _refresh();
    toastConnectionLocked();
  } catch (err) {
    uiModule.showError(err.message);
  }
}

function _wirePanZoom(surface, worldEl) {
  let panning = false;
  let sx = 0; let sy = 0;
  let spaceDown = false;

  window.addEventListener('keydown', (e) => { if (e.code === 'Space') spaceDown = true; });
  window.addEventListener('keyup', (e) => { if (e.code === 'Space') spaceDown = false; });

  surface.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    _zoom = Math.min(2.5, Math.max(0.25, _zoom * delta));
    worldEl.style.transform = `translate(${_panX}px,${_panY}px) scale(${_zoom})`;
  }, { passive: false });

  surface.addEventListener('pointerdown', (e) => {
    if (e.button === 1 || spaceDown || e.target === surface || e.target.classList.contains('atlas-canvas-surface')) {
      panning = true;
      sx = e.clientX; sy = e.clientY;
      surface.setPointerCapture(e.pointerId);
    }
  });
  surface.addEventListener('pointermove', (e) => {
    if (!panning) return;
    _panX += e.clientX - sx;
    _panY += e.clientY - sy;
    sx = e.clientX; sy = e.clientY;
    worldEl.style.transform = `translate(${_panX}px,${_panY}px) scale(${_zoom})`;
  });
  surface.addEventListener('pointerup', () => { panning = false; });

  surface.addEventListener('dblclick', async (e) => {
    if (e.target !== surface && !e.target.classList.contains('atlas-canvas-surface')) return;
    const rect = surface.getBoundingClientRect();
    const x = (e.clientX - rect.left - _panX) / _zoom;
    const y = (e.clientY - rect.top - _panY) / _zoom;
    await _createEntityAt(x, y);
  });
}

async function _refresh() {
  if (!_worldId) {
    _renderEmptyState();
    return;
  }
  const [layout, rels, entData] = await Promise.all([
    _fetch(`/api/atlas/worlds/${_worldId}/canvas`),
    _fetch(`/api/atlas/worlds/${_worldId}/relationships`),
    _fetch(`/api/atlas/worlds/${_worldId}/entities`),
  ]);
  _nodes = layout.nodes || [];
  _relationships = rels.relationships || [];
  _entities = entData.entities || _entities;
  const worldEl = _container?.querySelector('#atlas-canvas-world');
  _renderCards(worldEl);
  _renderEmptyState();
  if (_portDrag) _updateDragLine(_portDrag.cursorX, _portDrag.cursorY, _portDrag.overValid);
}

async function _reloadActiveWorlds() {
  const data = await _fetch('/api/atlas/worlds?archived=false');
  _worlds = data.worlds || [];
  if (_worldId && !_worlds.some(w => w.id === _worldId)) {
    _worldId = _worlds[0]?.id || null;
    if (_onWorldChange && _worldId) _onWorldChange(_worldId);
  }
  _updateWorldSelect();
}

function _updateWorldSelect() {
  const sel = _container?.querySelector('#atlas-world-select');
  if (!sel) return;
  sel.innerHTML = _worlds.map(w =>
    `<option value="${w.id}"${w.id === _worldId ? ' selected' : ''}>${_esc(w.name)}</option>`
  ).join('');
}

function _wireToolbar() {
  _container?.querySelector('#atlas-new-world-btn')?.addEventListener('click', async () => {
    const data = await promptWorld();
    if (!data) return;
    try {
      const w = await _fetch('/api/atlas/worlds', { method: 'POST', body: JSON.stringify(data) });
      _worlds.unshift(w);
      _worldId = w.id;
      _updateWorldSelect();
      if (_onWorldChange) _onWorldChange(_worldId);
      await _refresh();
      toastWorldCreated();
    } catch (e) {
      uiModule.showError(e.message);
    }
  });

  _container?.querySelector('#atlas-new-entity-btn')?.addEventListener('click', async () => {
    await _createEntityAt(100 + _nodes.length * 30, 100 + _nodes.length * 30);
  });

  _container?.querySelector('#atlas-world-select')?.addEventListener('change', async (e) => {
    _worldId = e.target.value;
    const w = _worlds.find(x => x.id === _worldId);
    if (w) toastWorldSwitched(w.name);
    if (_onWorldChange) _onWorldChange(_worldId);
    await _refresh();
  });

  _container?.querySelector('#atlas-worlds-btn')?.addEventListener('click', () => {
    openWorldsManager({
      activeWorldId: _worldId,
      fetchWorlds: async (archived) => {
        const q = archived ? 'true' : 'false';
        const data = await _fetch(`/api/atlas/worlds?archived=${q}`);
        return data.worlds || [];
      },
      onSwitch: async (worldId, action, extra = {}) => {
        try {
          if (action === 'open') {
            _worldId = worldId;
            _updateWorldSelect();
            if (_onWorldChange) await _onWorldChange(_worldId);
            await _refresh();
            const w = _worlds.find(x => x.id === worldId);
            if (w) toastWorldSwitched(w.name);
          } else if (action === 'rename') {
            await _fetch(`/api/atlas/worlds/${worldId}`, {
              method: 'PUT', body: JSON.stringify({ name: extra.name }),
            });
            await _reloadActiveWorlds();
            toastWorldRenamed(extra.name);
          } else if (action === 'archive') {
            await _fetch(`/api/atlas/worlds/${worldId}`, {
              method: 'PUT', body: JSON.stringify({ archived: true }),
            });
            const w = _worlds.find(x => x.id === worldId);
            await _reloadActiveWorlds();
            if (_worldId === worldId) await _refresh();
            toastWorldArchived(w?.name || 'World');
          } else if (action === 'restore') {
            await _fetch(`/api/atlas/worlds/${worldId}`, {
              method: 'PUT', body: JSON.stringify({ archived: false }),
            });
            await _reloadActiveWorlds();
            toastWorldRestored(extra.name || 'World');
          } else if (action === 'delete') {
            await _fetch(`/api/atlas/worlds/${worldId}`, { method: 'DELETE' });
            if (_worldId === worldId) {
              await _reloadActiveWorlds();
              await _refresh();
            } else {
              await _reloadActiveWorlds();
            }
            toastWorldDeleted(extra.name || 'World');
          }
        } catch (err) {
          uiModule.showError(err.message);
        }
      },
    });
  });
}

export async function mountCanvas(container, {
  worldId, worlds, entities, onOpenEntity, onWorldChange,
}) {
  _container = container;
  _worldId = worldId;
  _worlds = worlds || [];
  _entities = entities || [];
  _onOpenEntity = onOpenEntity;
  _onWorldChange = onWorldChange;
  _panX = 40; _panY = 40; _zoom = 1;

  container.innerHTML = `
    <div class="atlas-canvas-view">
      <div class="atlas-header atlas-chrome">
        <h2>Atlas</h2>
        <select id="atlas-world-select" class="atlas-world-select atlas-chrome"></select>
        <button type="button" class="admin-btn-sm" id="atlas-worlds-btn">Worlds…</button>
        <div class="atlas-header-actions">
          <button type="button" class="admin-btn-sm" id="atlas-new-world-btn">+ World</button>
          <button type="button" class="admin-btn-sm" id="atlas-new-entity-btn">+ Collection</button>
          <button type="button" class="atlas-close-btn" id="atlas-close-btn" title="Close">✕</button>
        </div>
      </div>
      <div class="atlas-canvas-surface" id="atlas-canvas-surface">
        <div id="atlas-canvas-world" class="atlas-canvas-world">
          <svg id="atlas-canvas-svg" class="atlas-canvas-svg"></svg>
        </div>
      </div>
      <div class="atlas-canvas-hint atlas-chrome">Click card to browse · Drag port dots to connect · Double-click empty space to add collection · Scroll to zoom · Space+drag to pan</div>
    </div>`;

  _updateWorldSelect();
  _wireToolbar();
  const surface = container.querySelector('#atlas-canvas-surface');
  const worldEl = container.querySelector('#atlas-canvas-world');
  worldEl.style.transform = `translate(${_panX}px,${_panY}px) scale(${_zoom})`;
  _wirePanZoom(surface, worldEl);
  await _refresh();
  return container.querySelector('#atlas-close-btn');
}

export function unmountCanvas() {
  clearTimeout(_saveTimer);
  _portDrag = null;
  _clearDragLine();
  _container = null;
}

export async function reloadCanvasData(worldId, worlds, entities) {
  _worldId = worldId;
  _worlds = worlds || _worlds;
  _entities = entities || _entities;
  _updateWorldSelect();
  await _refresh();
}
