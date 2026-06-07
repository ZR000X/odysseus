/**
 * Atlas world canvas — Obsidian-style pan/zoom entity graph.
 */
import uiModule from './ui.js';
import { promptEntity, promptRelationship, promptWorld } from './atlas-modals.js';

const API_BASE = window.location.origin;

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

function _entityCenter(entityId) {
  const n = _nodes.find(x => x.entity_id === entityId);
  if (!n) return { x: 0, y: 0 };
  return { x: n.x + n.w / 2, y: n.y + n.h / 2 };
}

function _renderEdges(svg) {
  if (!svg) return;
  const paths = _relationships.map(r => {
    const from = _entityCenter(r.from_entity_id);
    const to = _entityCenter(r.to_entity_id);
    const mx = (from.x + to.x) / 2;
    const d = `M ${from.x} ${from.y} C ${mx} ${from.y}, ${mx} ${to.y}, ${to.x} ${to.y}`;
    const color = r.rel_type === 'one_to_one' ? 'var(--accent)' : r.rel_type === 'many_to_many' ? '#f0abfc' : 'var(--fg)';
    return `<path class="atlas-edge" data-rel-id="${r.id}" d="${d}" stroke="${color}" fill="none" stroke-width="2" opacity="0.55"/>`;
  }).join('');
  svg.innerHTML = paths;
}

function _renderCards(worldEl) {
  if (!worldEl) return;
  worldEl.querySelectorAll('.atlas-canvas-card').forEach(el => el.remove());
  _nodes.forEach(n => {
    const card = document.createElement('div');
    card.className = 'atlas-canvas-card atlas-chrome';
    card.dataset.entityId = n.entity_id;
    card.style.cssText = `left:${n.x}px;top:${n.y}px;width:${n.w}px;min-height:${n.h}px`;
    card.innerHTML = `
      <div class="atlas-card-port atlas-card-port-top" data-side="top"></div>
      <div class="atlas-card-port atlas-card-port-right" data-side="right"></div>
      <div class="atlas-card-port atlas-card-port-bottom" data-side="bottom"></div>
      <div class="atlas-card-port atlas-card-port-left" data-side="left"></div>
      <div class="atlas-card-title">${_esc(n.name)}</div>
      <div class="atlas-card-meta">${n.row_count || 0} docs</div>`;
    _wireCardDrag(card, n);
    card.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      if (_onOpenEntity) _onOpenEntity(n.entity_id, n.name);
    });
    worldEl.appendChild(card);
  });
  _renderEdges(_container?.querySelector('#atlas-canvas-svg'));
}

function _wireCardDrag(card, node) {
  let dragging = false;
  let sx = 0; let sy = 0; let ox = 0; let oy = 0;
  card.addEventListener('pointerdown', (e) => {
    if (e.target.classList.contains('atlas-card-port')) return;
    dragging = true;
    sx = e.clientX; sy = e.clientY;
    ox = node.x; oy = node.y;
    card.setPointerCapture(e.pointerId);
    e.stopPropagation();
  });
  card.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    node.x = ox + (e.clientX - sx) / _zoom;
    node.y = oy + (e.clientY - sy) / _zoom;
    card.style.left = `${node.x}px`;
    card.style.top = `${node.y}px`;
    _renderEdges(_container?.querySelector('#atlas-canvas-svg'));
  });
  card.addEventListener('pointerup', () => {
    if (dragging) {
      dragging = false;
      _scheduleSave();
    }
  });
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
      _renderCards(worldEl);
      _scheduleSave();
      uiModule.showToast('Collection created');
    } catch (err) {
      uiModule.showError(err.message);
    }
  });
}

async function _refresh() {
  if (!_worldId) return;
  const [layout, rels] = await Promise.all([
    _fetch(`/api/atlas/worlds/${_worldId}/canvas`),
    _fetch(`/api/atlas/worlds/${_worldId}/relationships`),
  ]);
  _nodes = layout.nodes || [];
  _relationships = rels.relationships || [];
  const worldEl = _container?.querySelector('#atlas-canvas-world');
  _renderCards(worldEl);
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
      uiModule.showToast('World created');
    } catch (e) {
      uiModule.showError(e.message);
    }
  });

  _container?.querySelector('#atlas-new-entity-btn')?.addEventListener('click', async () => {
    const data = await promptEntity();
    if (!data || !_worldId) return;
    try {
      const ent = await _fetch(`/api/atlas/worlds/${_worldId}/entities`, {
        method: 'POST',
        body: JSON.stringify({ name: data.name }),
      });
      _nodes.push({
        entity_id: ent.id, name: ent.name, row_count: 0,
        x: 100 + _nodes.length * 30, y: 100 + _nodes.length * 30,
        w: 200, h: 120, z_index: 0,
      });
      _entities.push(ent);
      _renderCards(_container?.querySelector('#atlas-canvas-world'));
      _scheduleSave();
      uiModule.showToast('Collection created');
    } catch (e) {
      uiModule.showError(e.message);
    }
  });

  _container?.querySelector('#atlas-connect-btn')?.addEventListener('click', async () => {
    if (_entities.length < 2) {
      uiModule.showError('Need at least two collections');
      return;
    }
    const data = await promptRelationship(_entities);
    if (!data || !data.from_field || !data.to_field) {
      if (data) uiModule.showError('From field and to field are required');
      return;
    }
    try {
      await _fetch(`/api/atlas/worlds/${_worldId}/relationships`, {
        method: 'POST',
        body: JSON.stringify(data),
      });
      await _refresh();
      uiModule.showToast('Relationship created');
    } catch (e) {
      uiModule.showError(e.message);
    }
  });

  _container?.querySelector('#atlas-world-select')?.addEventListener('change', async (e) => {
    _worldId = e.target.value;
    if (_onWorldChange) _onWorldChange(_worldId);
    await _refresh();
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
        <div class="atlas-header-actions">
          <button type="button" class="admin-btn-sm" id="atlas-new-world-btn">+ World</button>
          <button type="button" class="admin-btn-sm" id="atlas-new-entity-btn">+ Collection</button>
          <button type="button" class="admin-btn-sm" id="atlas-connect-btn">Connect</button>
          <button type="button" class="atlas-close-btn" id="atlas-close-btn" title="Close">✕</button>
        </div>
      </div>
      <div class="atlas-canvas-surface" id="atlas-canvas-surface">
        <svg id="atlas-canvas-svg" class="atlas-canvas-svg"></svg>
        <div id="atlas-canvas-world" class="atlas-canvas-world"></div>
      </div>
      <div class="atlas-canvas-hint atlas-chrome">Double-click empty space to add a collection · Double-click card to browse documents · Scroll to zoom · Space+drag to pan</div>
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
  _container = null;
}

export async function reloadCanvasData(worldId, worlds, entities) {
  _worldId = worldId;
  _worlds = worlds || _worlds;
  _entities = entities || _entities;
  _updateWorldSelect();
  await _refresh();
}
