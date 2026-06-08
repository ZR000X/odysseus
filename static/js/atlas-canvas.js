/**
 * Atlas world canvas — Obsidian-style pan/zoom entity graph.
 */
import uiModule from './ui.js';
import {
  promptEntity, promptRelationship, promptEditRelationship,
  promptWorld, promptEditEntity, openWorldsManager,
} from './atlas-modals.js';
import {
  toastBrowsing, toastWorldCreated, toastCollectionCreated, toastCollectionUpdated,
  toastConnectionLocked, toastWorldSwitched, toastSaved,
  toastWorldArchived, toastWorldRestored, toastWorldDeleted, toastWorldRenamed,
} from './atlas-toast.js';

const API_BASE = window.location.origin;
const SVG_NS = 'http://www.w3.org/2000/svg';
const PORT_ANCHORS = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'];
const MOVE_THRESHOLD = 5;
const EDGE_CLICK_DELAY = 250;

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
let _endpointDrag = null;
let _edgeRaf = 0;
let _edgeClickTimer = null;
let _selectedRelId = null;
let _labelEditor = null;
let _edgesWired = false;

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

function _normalizeAnchor(anchor) {
  const a = (anchor || 'e').toLowerCase();
  const legacy = { top: 'n', right: 'e', bottom: 's', left: 'w' };
  return legacy[a] || a;
}

function _portPosition(entityId, anchor) {
  const n = _nodeForEntity(entityId);
  if (!n) return { x: 0, y: 0 };
  const key = _normalizeAnchor(anchor);
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

function _edgeMidpoint(from, to) {
  const mx = (from.x + to.x) / 2;
  const t = 0.5;
  const u = 1 - t;
  return {
    x: u ** 3 * from.x + 3 * u ** 2 * t * mx + 3 * u * t ** 2 * mx + t ** 3 * to.x,
    y: u ** 3 * from.y + 3 * u ** 2 * t * from.y + 3 * u * t ** 2 * to.y + t ** 3 * to.y,
  };
}

function _edgeGeometry(r) {
  const from = _portPosition(r.from_entity_id, r.from_anchor);
  const to = _portPosition(r.to_entity_id, r.to_anchor);
  const mx = (from.x + to.x) / 2;
  const d = `M ${from.x} ${from.y} C ${mx} ${from.y}, ${mx} ${to.y}, ${to.x} ${to.y}`;
  const color = r.rel_type === 'one_to_one' ? 'var(--accent)' : r.rel_type === 'many_to_many' ? '#f0abfc' : 'var(--fg)';
  const fromUx = Math.sign(mx - from.x) || 1;
  const toUx = Math.sign(to.x - mx) || 1;
  return {
    d, color, mid: _edgeMidpoint(from, to), from, to, mx,
    fromAngle: fromUx > 0 ? 0 : Math.PI,
    toAngle: toUx > 0 ? 0 : Math.PI,
  };
}

function _cardinalityForEnd(relType, end) {
  const t = relType || 'one_to_many';
  if (t === 'one_to_one') return 'one';
  if (t === 'many_to_many') return 'many';
  return end === 'from' ? 'one' : 'many';
}

function _markerPlacement(from, to, mx, end) {
  const offset = 10;
  if (end === 'from') {
    const ux = Math.sign(mx - from.x) || 1;
    return { x: from.x + ux * offset, y: from.y, angle: ux > 0 ? 0 : Math.PI };
  }
  const ux = Math.sign(to.x - mx) || 1;
  return { x: to.x - ux * offset, y: to.y, angle: ux > 0 ? Math.PI : 0 };
}

function _renderCardinalityMarker(g, cardinality, x, y, angle, color) {
  g.innerHTML = '';
  const strokeW = 1.75;
  if (cardinality === 'one') {
    const perp = angle + Math.PI / 2;
    const len = 5;
    const line = document.createElementNS(SVG_NS, 'line');
    line.classList.add('atlas-edge-marker-line');
    line.setAttribute('x1', x - Math.cos(perp) * len);
    line.setAttribute('y1', y - Math.sin(perp) * len);
    line.setAttribute('x2', x + Math.cos(perp) * len);
    line.setAttribute('y2', y + Math.sin(perp) * len);
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', strokeW);
    g.appendChild(line);
    return;
  }
  const len = 7;
  const spread = 0.48;
  const footAngle = angle + Math.PI;
  for (const a of [footAngle, footAngle - spread, footAngle + spread]) {
    const line = document.createElementNS(SVG_NS, 'line');
    line.classList.add('atlas-edge-marker-line');
    line.setAttribute('x1', x);
    line.setAttribute('y1', y);
    line.setAttribute('x2', x + Math.cos(a) * len);
    line.setAttribute('y2', y + Math.sin(a) * len);
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', strokeW);
    g.appendChild(line);
  }
}

function _relById(relId) {
  return _relationships.find(x => x.id === relId);
}

function _clearEdgeSelection() {
  _selectedRelId = null;
  _container?.querySelectorAll('.atlas-edge-selected').forEach(el => {
    el.classList.remove('atlas-edge-selected');
  });
}

function _dismissLabelEditor() {
  _labelEditor?.remove();
  _labelEditor = null;
  _clearEdgeSelection();
}

function _updateLabelEditorPosition(relId) {
  if (!_labelEditor || _labelEditor.dataset.relId !== relId) return;
  const rel = _relById(relId);
  if (!rel) return;
  const { mid } = _edgeGeometry(rel);
  _labelEditor.style.left = `${mid.x}px`;
  _labelEditor.style.top = `${mid.y}px`;
}

async function _saveEdgeLabel(rel, label) {
  if (!_worldId) return;
  try {
    const updated = await _fetch(`/api/atlas/worlds/${_worldId}/relationships/${rel.id}`, {
      method: 'PUT',
      body: JSON.stringify({ label }),
    });
    const idx = _relationships.findIndex(x => x.id === rel.id);
    if (idx >= 0) _relationships[idx] = { ..._relationships[idx], ...updated };
    _dismissLabelEditor();
    _renderEdges(_container?.querySelector('#atlas-canvas-svg'), { animate: false });
    toastSaved();
  } catch (err) {
    uiModule.showError(err.message);
  }
}

function _openLabelEditor(rel) {
  _dismissLabelEditor();
  _selectedRelId = rel.id;
  const svg = _container?.querySelector('#atlas-canvas-svg');
  svg?.querySelector(`g.atlas-edge-group[data-rel-id="${rel.id}"]`)
    ?.classList.add('atlas-edge-selected');
  svg?.querySelector(`g.atlas-edge-group[data-rel-id="${rel.id}"] path.atlas-edge-vis`)
    ?.classList.add('atlas-edge-selected');

  const { mid } = _edgeGeometry(rel);
  const world = _container?.querySelector('#atlas-canvas-world');
  if (!world) return;

  const el = document.createElement('div');
  el.className = 'atlas-edge-label-editor';
  el.dataset.relId = rel.id;
  el.style.left = `${mid.x}px`;
  el.style.top = `${mid.y}px`;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'atlas-edge-label-input';
  input.value = rel.label || '';
  input.placeholder = 'Label';
  el.appendChild(input);
  world.appendChild(el);
  _labelEditor = el;
  input.focus();
  input.select();

  let saving = false;
  const finish = async (save) => {
    if (saving || !_labelEditor) return;
    saving = true;
    if (save) {
      await _saveEdgeLabel(rel, input.value.trim());
    } else {
      _dismissLabelEditor();
      _renderEdges(svg, { animate: false });
    }
    saving = false;
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      finish(false);
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      finish(true);
    }
  });
  input.addEventListener('blur', () => {
    setTimeout(() => {
      if (_labelEditor === el) finish(true);
    }, 0);
  });
}

async function _deleteRelationship(rel) {
  if (!_worldId) return;
  try {
    await _fetch(`/api/atlas/worlds/${_worldId}/relationships/${rel.id}`, { method: 'DELETE' });
    _relationships = _relationships.filter(x => x.id !== rel.id);
    _dismissLabelEditor();
    _renderEdges(_container?.querySelector('#atlas-canvas-svg'), { animate: false });
    uiModule.showToast('Relationship deleted.', { leadingIcon: 'check', duration: 1800 });
  } catch (err) {
    uiModule.showError(err.message);
  }
}

async function _editRelationship(rel) {
  if (!_worldId) return;
  const data = await promptEditRelationship(rel, _entities);
  if (!data) return;
  if (data._delete) {
    await _deleteRelationship(rel);
    return;
  }
  try {
    const updated = await _fetch(`/api/atlas/worlds/${_worldId}/relationships/${rel.id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
    const idx = _relationships.findIndex(x => x.id === rel.id);
    if (idx >= 0) _relationships[idx] = { ..._relationships[idx], ...updated };
    _renderEdges(_container?.querySelector('#atlas-canvas-svg'), { animate: false });
    toastSaved();
  } catch (err) {
    uiModule.showError(err.message);
  }
}

function _scheduleEdgeRender(animate = false) {
  if (_edgeRaf) return;
  _edgeRaf = requestAnimationFrame(() => {
    _edgeRaf = 0;
    const svg = _container?.querySelector('#atlas-canvas-svg');
    _renderEdges(svg, { animate });
    if (_labelEditor?.dataset.relId) {
      _updateLabelEditorPosition(_labelEditor.dataset.relId);
    }
  });
}

function _ensureEdgeInteractions(svg) {
  if (!svg || _edgesWired) return;
  _edgesWired = true;

  svg.addEventListener('pointerdown', (e) => {
    const handle = e.target.closest?.('.atlas-edge-endpoint');
    if (!handle) return;
    e.stopPropagation();
    e.preventDefault();
    _dismissLabelEditor();
    const rel = _relById(handle.dataset.relId);
    if (!rel) return;
    const end = handle.dataset.end;
    const pos = _portPosition(
      end === 'from' ? rel.from_entity_id : rel.to_entity_id,
      end === 'from' ? rel.from_anchor : rel.to_anchor,
    );
    handle.setPointerCapture(e.pointerId);
    _endpointDrag = {
      relId: rel.id,
      end,
      cursorX: pos.x,
      cursorY: pos.y,
      originalEntityId: end === 'from' ? rel.from_entity_id : rel.to_entity_id,
      originalAnchor: end === 'from' ? rel.from_anchor : rel.to_anchor,
      overValid: false,
      handleEl: handle,
      pointerId: e.pointerId,
    };
    _container?.querySelector('#atlas-canvas-surface')?.classList.add('atlas-endpoint-dragging');
    _updateDragLine(pos.x, pos.y, false);
    document.addEventListener('pointermove', _onDragPointerMove);
    document.addEventListener('pointerup', _onEndpointPointerUp);
    document.addEventListener('pointercancel', _onEndpointPointerUp);
  });

  svg.addEventListener('click', (e) => {
    if (e.target.closest?.('.atlas-edge-endpoint')) return;
    const hit = e.target.closest?.('.atlas-edge-hit');
    if (!hit) return;
    e.stopPropagation();
    const rel = _relById(hit.dataset.relId);
    if (!rel) return;
    clearTimeout(_edgeClickTimer);
    _edgeClickTimer = setTimeout(() => _openLabelEditor(rel), EDGE_CLICK_DELAY);
  });

  svg.addEventListener('dblclick', (e) => {
    if (e.target.closest?.('.atlas-edge-endpoint')) return;
    const hit = e.target.closest?.('.atlas-edge-hit');
    if (!hit) return;
    e.stopPropagation();
    clearTimeout(_edgeClickTimer);
    _dismissLabelEditor();
    const rel = _relById(hit.dataset.relId);
    if (rel) _editRelationship(rel);
  });
}

function _renderEdges(svg, { animate = true } = {}) {
  if (!svg) return;
  _ensureEdgeInteractions(svg);
  const seen = new Set();

  _relationships.forEach(r => {
    const { d, color, mid, from, to, mx } = _edgeGeometry(r);
    seen.add(r.id);

    let group = svg.querySelector(`g.atlas-edge-group[data-rel-id="${r.id}"]`);
    if (!group) {
      group = document.createElementNS(SVG_NS, 'g');
      group.classList.add('atlas-edge-group');
      group.dataset.relId = r.id;
      svg.appendChild(group);
    }
    group.classList.toggle('atlas-edge-selected', _selectedRelId === r.id);

    let hit = group.querySelector('path.atlas-edge-hit');
    if (!hit) {
      hit = document.createElementNS(SVG_NS, 'path');
      hit.classList.add('atlas-edge-hit');
      hit.setAttribute('stroke', 'transparent');
      hit.setAttribute('stroke-width', '14');
      hit.setAttribute('fill', 'none');
      hit.style.cursor = 'pointer';
      group.appendChild(hit);
    }
    hit.setAttribute('d', d);
    hit.dataset.relId = r.id;

    let vis = group.querySelector('path.atlas-edge-vis');
    const isNew = !vis;
    if (!vis) {
      vis = document.createElementNS(SVG_NS, 'path');
      vis.classList.add('atlas-edge', 'atlas-edge-vis');
      vis.setAttribute('fill', 'none');
      vis.setAttribute('stroke-width', '2');
      vis.setAttribute('opacity', '0.55');
      vis.setAttribute('pointer-events', 'none');
      group.appendChild(vis);
    }
    vis.setAttribute('d', d);
    vis.setAttribute('stroke', color);
    vis.classList.remove('atlas-edge-draw', 'atlas-edge-live', 'atlas-edge-selected');
    if (animate && isNew) {
      vis.classList.add('atlas-edge-draw');
    } else {
      vis.classList.add('atlas-edge-live');
    }
    if (_selectedRelId === r.id) vis.classList.add('atlas-edge-selected');

    for (const end of ['from', 'to']) {
      const placement = _markerPlacement(from, to, mx, end);
      const card = _cardinalityForEnd(r.rel_type, end);
      let markerG = group.querySelector(`g.atlas-edge-marker[data-end="${end}"]`);
      if (!markerG) {
        markerG = document.createElementNS(SVG_NS, 'g');
        markerG.classList.add('atlas-edge-marker');
        markerG.dataset.end = end;
        group.appendChild(markerG);
      }
      _renderCardinalityMarker(markerG, card, placement.x, placement.y, placement.angle, color);

      const port = end === 'from' ? from : to;
      let endpoint = group.querySelector(`circle.atlas-edge-endpoint[data-end="${end}"]`);
      if (!endpoint) {
        endpoint = document.createElementNS(SVG_NS, 'circle');
        endpoint.classList.add('atlas-edge-endpoint');
        endpoint.dataset.end = end;
        endpoint.setAttribute('r', '10');
        group.appendChild(endpoint);
      }
      endpoint.dataset.relId = r.id;
      endpoint.setAttribute('cx', port.x);
      endpoint.setAttribute('cy', port.y);
    }

    let labelEl = group.querySelector('text.atlas-edge-label');
    if (r.label && _labelEditor?.dataset.relId !== r.id) {
      if (!labelEl) {
        labelEl = document.createElementNS(SVG_NS, 'text');
        labelEl.classList.add('atlas-edge-label');
        labelEl.setAttribute('pointer-events', 'none');
        labelEl.setAttribute('text-anchor', 'middle');
        labelEl.setAttribute('dominant-baseline', 'middle');
        labelEl.setAttribute('font-size', '10');
        group.appendChild(labelEl);
      }
      labelEl.setAttribute('x', mid.x);
      labelEl.setAttribute('y', mid.y - 10);
      labelEl.setAttribute('fill', 'var(--fg)');
      labelEl.textContent = r.label;
    } else if (labelEl) {
      labelEl.remove();
    }
  });

  svg.querySelectorAll('g.atlas-edge-group[data-rel-id]').forEach(el => {
    if (!seen.has(el.dataset.relId)) el.remove();
  });
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
      <button type="button" class="admin-btn-sm atlas-modal-primary-cta" id="atlas-empty-world-btn">+ Create your first world</button>
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
    _dismissLabelEditor();
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
    _scheduleEdgeRender(false);
    if (_portDrag || _endpointDrag) {
      const d = _portDrag || _endpointDrag;
      _updateDragLine(d.cursorX, d.cursorY, d.overValid);
    }
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

function _dragLineEndpoints(cursorX, cursorY) {
  if (_portDrag) {
    const from = _portPosition(_portDrag.fromEntityId, _portDrag.fromAnchor);
    return { from, to: { x: cursorX, y: cursorY } };
  }
  if (_endpointDrag) {
    const rel = _relById(_endpointDrag.relId);
    if (!rel) return null;
    if (_endpointDrag.end === 'from') {
      return {
        from: { x: cursorX, y: cursorY },
        to: _portPosition(rel.to_entity_id, rel.to_anchor),
      };
    }
    return {
      from: _portPosition(rel.from_entity_id, rel.from_anchor),
      to: { x: cursorX, y: cursorY },
    };
  }
  return null;
}

function _updateDragLine(cursorX, cursorY, overValid = false) {
  const pts = _dragLineEndpoints(cursorX, cursorY);
  if (!pts) return;
  const svg = _getDragLineSvg();
  if (!svg) return;
  const { from, to } = pts;
  const mx = (from.x + to.x) / 2;
  const d = `M ${from.x} ${from.y} C ${mx} ${from.y}, ${mx} ${to.y}, ${to.x} ${to.y}`;
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
      _dismissLabelEditor();
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
      document.addEventListener('pointermove', _onDragPointerMove);
      document.addEventListener('pointerup', _onPortPointerUp);
      document.addEventListener('pointercancel', _onPortPointerUp);
    });
  });
}

function _nearestPortOnCard(card, clientX, clientY) {
  let best = null;
  let bestDist = Infinity;
  card.querySelectorAll('.atlas-card-port').forEach(port => {
    const rect = port.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const d = Math.hypot(clientX - cx, clientY - cy);
    if (d < bestDist) {
      bestDist = d;
      best = port;
    }
  });
  return best;
}

function _portAtPoint(clientX, clientY) {
  const el = document.elementFromPoint(clientX, clientY);
  let port = el?.closest?.('.atlas-card-port');
  if (!port) {
    const card = el?.closest?.('.atlas-canvas-card');
    if (card) port = _nearestPortOnCard(card, clientX, clientY);
  }
  if (!port) return null;
  const card = port.closest('.atlas-canvas-card');
  if (!card) return null;
  return {
    port,
    entityId: card.dataset.entityId,
    anchor: port.dataset.anchor || 'w',
  };
}

function _validateDropTarget(clientX, clientY, dragState) {
  _container?.querySelectorAll('.atlas-port-drop-target').forEach(el => {
    el.classList.remove('atlas-port-drop-target');
  });
  const hit = _portAtPoint(clientX, clientY);
  if (!hit) return { valid: false };
  const { port, entityId, anchor } = hit;

  if (dragState.mode === 'port') {
    if (entityId === dragState.fromEntityId) return { valid: false };
    port.classList.add('atlas-port-drop-target');
    return { valid: true, entityId, anchor };
  }

  const rel = _relById(dragState.relId);
  if (!rel) return { valid: false };
  const oppositeId = dragState.end === 'from' ? rel.to_entity_id : rel.from_entity_id;
  if (entityId === oppositeId) return { valid: false };
  if (
    entityId === dragState.originalEntityId
    && _normalizeAnchor(anchor) === _normalizeAnchor(dragState.originalAnchor)
  ) {
    return { valid: false };
  }
  port.classList.add('atlas-port-drop-target');
  return { valid: true, entityId, anchor };
}

function _onDragPointerMove(e) {
  const w = _surfaceToWorld(e.clientX, e.clientY);
  let dragState = null;
  if (_portDrag) {
    _portDrag.cursorX = w.x;
    _portDrag.cursorY = w.y;
    dragState = { mode: 'port', fromEntityId: _portDrag.fromEntityId };
  } else if (_endpointDrag) {
    _endpointDrag.cursorX = w.x;
    _endpointDrag.cursorY = w.y;
    dragState = {
      mode: 'endpoint',
      relId: _endpointDrag.relId,
      end: _endpointDrag.end,
      originalEntityId: _endpointDrag.originalEntityId,
      originalAnchor: _endpointDrag.originalAnchor,
    };
  } else {
    return;
  }
  const drop = _validateDropTarget(e.clientX, e.clientY, dragState);
  if (_portDrag) _portDrag.overValid = drop.valid;
  if (_endpointDrag) _endpointDrag.overValid = drop.valid;
  _updateDragLine(w.x, w.y, drop.valid);
}

async function _onPortPointerUp(e) {
  document.removeEventListener('pointermove', _onDragPointerMove);
  document.removeEventListener('pointerup', _onPortPointerUp);
  document.removeEventListener('pointercancel', _onPortPointerUp);
  if (!_portDrag) return;
  const drag = _portDrag;
  _portDrag = null;
  _clearDragLine();

  const drop = _validateDropTarget(e.clientX, e.clientY, {
    mode: 'port', fromEntityId: drag.fromEntityId,
  });
  if (!drop.valid) return;

  const data = await promptRelationship(_entities, drag.fromEntityId, drop.entityId, {
    from_anchor: drag.fromAnchor,
    to_anchor: drop.anchor,
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

function _endEndpointDrag() {
  _container?.querySelector('#atlas-canvas-surface')?.classList.remove('atlas-endpoint-dragging');
}

async function _onEndpointPointerUp(e) {
  document.removeEventListener('pointermove', _onDragPointerMove);
  document.removeEventListener('pointerup', _onEndpointPointerUp);
  document.removeEventListener('pointercancel', _onEndpointPointerUp);
  if (!_endpointDrag) return;
  const drag = _endpointDrag;
  _endpointDrag = null;
  drag.handleEl?.releasePointerCapture?.(drag.pointerId);
  _endEndpointDrag();
  _clearDragLine();

  const drop = _validateDropTarget(e.clientX, e.clientY, {
    mode: 'endpoint',
    relId: drag.relId,
    end: drag.end,
    originalEntityId: drag.originalEntityId,
    originalAnchor: drag.originalAnchor,
  });
  if (!drop.valid) return;

  const payload = drag.end === 'from'
    ? { from_entity_id: drop.entityId, from_anchor: drop.anchor }
    : { to_entity_id: drop.entityId, to_anchor: drop.anchor };
  try {
    const updated = await _fetch(`/api/atlas/worlds/${_worldId}/relationships/${drag.relId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    const idx = _relationships.findIndex(x => x.id === drag.relId);
    if (idx >= 0) _relationships[idx] = { ..._relationships[idx], ...updated };
    _scheduleEdgeRender(false);
    toastSaved();
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
    if (e.target === surface || e.target.classList.contains('atlas-canvas-surface')) {
      _dismissLabelEditor();
    }
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
      <div class="atlas-canvas-hint atlas-chrome">Click card to browse · Click edge to label · Double-click edge to edit · Drag ports or edge ends to connect · | one · &lt; many · Double-click empty space to add collection · Scroll to zoom · Space+drag to pan</div>
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
  clearTimeout(_edgeClickTimer);
  if (_edgeRaf) cancelAnimationFrame(_edgeRaf);
  _edgeRaf = 0;
  _edgesWired = false;
  _dismissLabelEditor();
  _portDrag = null;
  _endpointDrag = null;
  _endEndpointDrag();
  _clearDragLine();
  document.removeEventListener('pointermove', _onDragPointerMove);
  document.removeEventListener('pointerup', _onPortPointerUp);
  document.removeEventListener('pointercancel', _onPortPointerUp);
  document.removeEventListener('pointerup', _onEndpointPointerUp);
  document.removeEventListener('pointercancel', _onEndpointPointerUp);
  _container = null;
}

export async function reloadCanvasData(worldId, worlds, entities) {
  _worldId = worldId;
  _worlds = worlds || _worlds;
  _entities = entities || _entities;
  _updateWorldSelect();
  await _refresh();
}
