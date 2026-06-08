/**
 * Atlas world canvas — Obsidian-style pan/zoom entity graph.
 */
import uiModule from './ui.js';
import {
  promptEntity, promptRelationship, promptEditRelationship,
  promptWorld, promptEditEntity, openWorldsManager,
  promptCluster, promptEditCluster, promptTypeToConfirm,
} from './atlas-modals.js';
import { exportWorldExcel, openWorldExcelImportWizard } from './atlas-world-excel.js';
import { parseCardinalities, edgeVisuals, renderCardinalityMarker } from './atlas-rel-cardinality.js';
import {
  toastBrowsing, toastWorldCreated, toastCollectionCreated, toastCollectionUpdated,
  toastConnectionLocked, toastWorldSwitched, toastSaved,
  toastWorldArchived, toastWorldRestored, toastWorldDeleted, toastWorldRenamed,
  toastWorldExported, toastWorldImported, toastClusterCreated, toastClusterUpdated,
} from './atlas-toast.js';

const API_BASE = window.location.origin;
const SVG_NS = 'http://www.w3.org/2000/svg';
const PORT_ANCHORS = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'];
const MOVE_THRESHOLD = 5;
const EDGE_CLICK_DELAY = 250;
const MIN_CLUSTER_W = 160;
const MIN_CLUSTER_H = 120;
const DEFAULT_CLUSTER_W = 400;
const DEFAULT_CLUSTER_H = 300;
const DEFAULT_CARD_W = 200;
const DEFAULT_CARD_H = 120;
const MIN_CARD_W = 120;
const MIN_CARD_H = 72;

let _container = null;
let _worldId = null;
let _worlds = [];
let _entities = [];
let _relationships = [];
let _nodes = [];
let _clusters = [];
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
let _selectedClusterId = null;

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
      const payload = {
        nodes: _nodes.map(n => ({
          entity_id: n.entity_id,
          x: n.x, y: n.y, w: n.w, h: n.h,
          z_index: n.z_index || 0,
          cluster_id: n.cluster_id || null,
        })),
        clusters: _clusters.map(c => ({
          id: c.id,
          name: c.name,
          parent_cluster_id: c.parent_cluster_id || null,
          x: c.x, y: c.y, w: c.w, h: c.h,
          color: c.color || '',
          z_index: c.z_index || 0,
          collapsed: !!c.collapsed,
        })),
      };
      await _fetch(`/api/atlas/worlds/${_worldId}/canvas`, {
        method: 'PUT',
        body: JSON.stringify(payload),
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

function _lerpPt(a, b, t) {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

function _splitCubicBezier(p0, p1, p2, p3, t = 0.5) {
  const p01 = _lerpPt(p0, p1, t);
  const p12 = _lerpPt(p1, p2, t);
  const p23 = _lerpPt(p2, p3, t);
  const p012 = _lerpPt(p01, p12, t);
  const p123 = _lerpPt(p12, p23, t);
  const mid = _lerpPt(p012, p123, t);
  return {
    first: `M ${p0.x} ${p0.y} C ${p01.x} ${p01.y}, ${p012.x} ${p012.y}, ${mid.x} ${mid.y}`,
    second: `M ${mid.x} ${mid.y} C ${p123.x} ${p123.y}, ${p23.x} ${p23.y}, ${p3.x} ${p3.y}`,
    mid,
  };
}

function _animDelay(id) {
  let h = 0;
  for (let i = 0; i < (id || '').length; i++) {
    h = (h * 31 + id.charCodeAt(i)) % 1000;
  }
  return `${(h % 350) / 100}s`;
}

function _appendFlowBalls(group, d, direction, color, delaySec, pathUid) {
  const pathId = `atlas-flow-${pathUid}`;
  const track = document.createElementNS(SVG_NS, 'path');
  track.setAttribute('id', pathId);
  track.setAttribute('d', d);
  track.setAttribute('fill', 'none');
  track.setAttribute('stroke', 'none');
  track.classList.add('atlas-edge-flow-track');
  track.setAttribute('pointer-events', 'none');

  const ballsG = document.createElementNS(SVG_NS, 'g');
  ballsG.classList.add('atlas-edge-flow-balls');
  ballsG.setAttribute('pointer-events', 'none');

  const BALL_COUNT = 5;
  const DUR = 1.4;
  const baseDelay = parseFloat(delaySec) || 0;

  for (let i = 0; i < BALL_COUNT; i++) {
    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.classList.add('atlas-edge-flow-ball');
    circle.setAttribute('r', '3.5');
    circle.setAttribute('fill', color);

    const motion = document.createElementNS(SVG_NS, 'animateMotion');
    motion.setAttribute('dur', `${DUR}s`);
    motion.setAttribute('repeatCount', 'indefinite');
    motion.setAttribute('begin', `${baseDelay + (i * DUR) / BALL_COUNT}s`);
    if (direction === 'reverse') {
      motion.setAttribute('keyPoints', '1;0');
      motion.setAttribute('keyTimes', '0;1');
      motion.setAttribute('calcMode', 'linear');
    }
    const mpath = document.createElementNS(SVG_NS, 'mpath');
    mpath.setAttribute('href', `#${pathId}`);
    motion.appendChild(mpath);

    const pulse = document.createElementNS(SVG_NS, 'animate');
    pulse.setAttribute('attributeName', 'opacity');
    pulse.setAttribute('values', '0.25;1;0.25');
    pulse.setAttribute('dur', '0.7s');
    pulse.setAttribute('repeatCount', 'indefinite');
    pulse.setAttribute('begin', `${baseDelay + (i * DUR) / BALL_COUNT}s`);

    const scale = document.createElementNS(SVG_NS, 'animate');
    scale.setAttribute('attributeName', 'r');
    scale.setAttribute('values', '2.5;4;2.5');
    scale.setAttribute('dur', '0.7s');
    scale.setAttribute('repeatCount', 'indefinite');
    scale.setAttribute('begin', `${baseDelay + (i * DUR) / BALL_COUNT}s`);

    circle.appendChild(pulse);
    circle.appendChild(scale);
    circle.appendChild(motion);
    ballsG.appendChild(circle);
  }

  const vis = group.querySelector('path.atlas-edge-vis');
  if (vis) {
    vis.insertAdjacentElement('afterend', track);
    track.insertAdjacentElement('afterend', ballsG);
  } else {
    group.appendChild(track);
    group.appendChild(ballsG);
  }
}

function _updateFlowPaths(group, r, geom) {
  group.querySelectorAll('.atlas-edge-flow-track, .atlas-edge-flow-balls').forEach(el => el.remove());
  if (_selectedRelId === r.id) return;
  const delay = _animDelay(r.id);
  const { d, color, from, to, mx } = geom;
  const p0 = from;
  const p1 = { x: mx, y: from.y };
  const p2 = { x: mx, y: to.y };
  const p3 = to;
  const { from: fromC, to: toC } = parseCardinalities(r);
  const { flowMode } = edgeVisuals(fromC, toC);
  if (flowMode === 'many_many') {
    const split = _splitCubicBezier(p0, p1, p2, p3, 0.5);
    _appendFlowBalls(group, split.second, 'forward', color, delay, `${r.id}-out-to`);
    _appendFlowBalls(group, split.first, 'reverse', color, delay, `${r.id}-out-from`);
  } else if (flowMode === 'one_one') {
    const split = _splitCubicBezier(p0, p1, p2, p3, 0.5);
    _appendFlowBalls(group, split.first, 'forward', color, delay, `${r.id}-in-from`);
    _appendFlowBalls(group, split.second, 'reverse', color, delay, `${r.id}-in-to`);
  } else {
    _appendFlowBalls(group, d, 'forward', color, delay, `${r.id}-fwd`);
  }
}

function _edgeGeometry(r) {
  const from = _portPosition(r.from_entity_id, r.from_anchor);
  const to = _portPosition(r.to_entity_id, r.to_anchor);
  const mx = (from.x + to.x) / 2;
  const d = `M ${from.x} ${from.y} C ${mx} ${from.y}, ${mx} ${to.y}, ${to.x} ${to.y}`;
  const { from: fromC, to: toC } = parseCardinalities(r);
  const { color } = edgeVisuals(fromC, toC);
  const fromUx = Math.sign(mx - from.x) || 1;
  const toUx = Math.sign(to.x - mx) || 1;
  return {
    d, color, mid: _edgeMidpoint(from, to), from, to, mx,
    fromAngle: fromUx > 0 ? 0 : Math.PI,
    toAngle: toUx > 0 ? 0 : Math.PI,
  };
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
      vis.addEventListener('animationend', () => {
        vis.classList.remove('atlas-edge-draw');
        vis.classList.add('atlas-edge-live');
      }, { once: true });
    } else {
      vis.classList.add('atlas-edge-live');
    }
    vis.style.animationDelay = _animDelay(r.id);
    if (_selectedRelId === r.id) vis.classList.add('atlas-edge-selected');

    _updateFlowPaths(group, r, { d, color, mid, from, to, mx });

    const cards = parseCardinalities(r);
    for (const end of ['from', 'to']) {
      const placement = _markerPlacement(from, to, mx, end);
      const card = end === 'from' ? cards.from : cards.to;
      let markerG = group.querySelector(`g.atlas-edge-marker[data-end="${end}"]`);
      if (!markerG) {
        markerG = document.createElementNS(SVG_NS, 'g');
        markerG.classList.add('atlas-edge-marker');
        markerG.dataset.end = end;
        group.appendChild(markerG);
      }
      renderCardinalityMarker(markerG, card, placement.x, placement.y, placement.angle, color);

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
      x, y, w: DEFAULT_CARD_W, h: DEFAULT_CARD_H, z_index: 0, cluster_id: null,
    });
    _entities.push(ent);
    _renderCanvas(_container?.querySelector('#atlas-canvas-world'));
    _renderEmptyState();
    _scheduleSave();
    toastCollectionCreated();
  } catch (err) {
    uiModule.showError(err.message);
  }
}

function _clusterById(id) {
  return _clusters.find(c => c.id === id);
}

function _clusterDepth(clusterId) {
  let depth = 0;
  let cur = clusterId;
  const seen = new Set();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    depth += 1;
    cur = _clusterById(cur)?.parent_cluster_id;
  }
  return depth;
}

function _containsPoint(c, x, y) {
  return x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h;
}

function _descendantClusterIds(clusterId) {
  const out = [];
  const stack = [clusterId];
  while (stack.length) {
    const id = stack.pop();
    _clusters.filter(c => c.parent_cluster_id === id).forEach(c => {
      out.push(c.id);
      stack.push(c.id);
    });
  }
  return out;
}

function _isDescendantOf(candidateId, ancestorId) {
  if (!candidateId || !ancestorId) return false;
  let cur = _clusterById(candidateId)?.parent_cluster_id;
  const seen = new Set();
  while (cur && !seen.has(cur)) {
    if (cur === ancestorId) return true;
    seen.add(cur);
    cur = _clusterById(cur)?.parent_cluster_id;
  }
  return false;
}

function _hitTestCluster(x, y, excludeId = null) {
  const excludeSet = new Set();
  if (excludeId) {
    excludeSet.add(excludeId);
    _descendantClusterIds(excludeId).forEach(id => excludeSet.add(id));
  }
  const candidates = _clusters.filter(
    c => !excludeSet.has(c.id) && !c.collapsed && _containsPoint(c, x, y),
  );
  if (!candidates.length) return null;
  candidates.sort((a, b) => {
    const dd = _clusterDepth(b.id) - _clusterDepth(a.id);
    if (dd !== 0) return dd;
    return (a.w * a.h) - (b.w * b.h);
  });
  return candidates[0].id;
}

function _clearDropHighlights() {
  _container?.querySelectorAll('.atlas-cluster-drop-target').forEach(el => {
    el.classList.remove('atlas-cluster-drop-target');
  });
  _container?.querySelectorAll('.atlas-card-drop-target').forEach(el => {
    el.classList.remove('atlas-card-drop-target');
  });
}

function _applyDropHighlights(cx, cy, { excludeClusterId = null, cardEl = null } = {}) {
  _clearDropHighlights();
  const targetId = _hitTestCluster(cx, cy, excludeClusterId);
  if (targetId) {
    _container?.querySelector(
      `.atlas-canvas-cluster[data-cluster-id="${targetId}"]`,
    )?.classList.add('atlas-cluster-drop-target');
  }
  if (cardEl) cardEl.classList.add('atlas-card-drop-target');
}

function _clusterStats(clusterId) {
  const memberNodes = _nodes.filter(n => n.cluster_id === clusterId);
  const collections = memberNodes.length;
  const docs = memberNodes.reduce((sum, n) => sum + (n.row_count || 0), 0);
  return { collections, docs };
}

function _ensureClustersLayer(worldEl) {
  if (!worldEl) return null;
  let layer = worldEl.querySelector('#atlas-canvas-clusters');
  if (!layer) {
    layer = document.createElement('div');
    layer.id = 'atlas-canvas-clusters';
    layer.className = 'atlas-canvas-clusters-layer';
    const svg = worldEl.querySelector('#atlas-canvas-svg');
    if (svg) worldEl.insertBefore(layer, svg);
    else worldEl.prepend(layer);
  }
  return layer;
}

function _renderClusters(worldEl) {
  const layer = _ensureClustersLayer(worldEl);
  if (!layer) return;
  layer.innerHTML = '';
  const sorted = [..._clusters].sort((a, b) => {
    const da = _clusterDepth(a.id) - _clusterDepth(b.id);
    if (da !== 0) return da;
    return (a.z_index || 0) - (b.z_index || 0);
  });
  sorted.forEach((c, idx) => {
    const el = document.createElement('div');
    const depth = _clusterDepth(c.id);
    const colorCls = c.color ? ` atlas-cluster-color-${c.color}` : '';
    el.className = `atlas-canvas-cluster atlas-chrome${colorCls}${c.collapsed ? ' atlas-cluster-collapsed' : ''}${_selectedClusterId === c.id ? ' atlas-cluster-selected' : ''}`;
    el.dataset.clusterId = c.id;
    el.dataset.depth = String(Math.min(depth, 4));
    el.style.left = `${c.x}px`;
    el.style.top = `${c.y}px`;
    el.style.width = `${c.w}px`;
    el.style.height = `${c.h}px`;
    el.style.zIndex = String(5 + (c.z_index || 0));
    const stats = _clusterStats(c.id);
    el.innerHTML = `
      <div class="atlas-cluster-header">
        <div class="atlas-cluster-title">${_esc(c.name)}</div>
        <div class="atlas-cluster-actions">
          <button type="button" class="atlas-cluster-btn atlas-cluster-collapse" title="Collapse">${c.collapsed ? '▸' : '▾'}</button>
          <button type="button" class="atlas-cluster-btn atlas-cluster-edit" title="Edit cluster">✎</button>
        </div>
      </div>
      <div class="atlas-cluster-body"></div>
      <div class="atlas-cluster-footer">${stats.collections} collection${stats.collections === 1 ? '' : 's'} · ${stats.docs} doc${stats.docs === 1 ? '' : 's'}</div>
      <div class="atlas-cluster-resize atlas-cluster-resize-e" data-resize="e"></div>
      <div class="atlas-cluster-resize atlas-cluster-resize-s" data-resize="s"></div>
      <div class="atlas-cluster-resize atlas-cluster-resize-se" data-resize="se"></div>`;
    el.style.setProperty('--cluster-i', String(idx));
    _wireClusterDrag(el, c);
    _wireClusterResize(el, c);
    el.querySelector('.atlas-cluster-collapse')?.addEventListener('click', (e) => {
      e.stopPropagation();
      c.collapsed = !c.collapsed;
      _renderCanvas(worldEl);
      _scheduleSave();
    });
    el.querySelector('.atlas-cluster-edit')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      await _editCluster(c);
    });
    el.addEventListener('click', (e) => {
      if (e.target.closest('.atlas-cluster-resize') || e.target.closest('.atlas-cluster-btn')) return;
      _selectedClusterId = c.id;
      _renderClusters(worldEl);
    });
    layer.appendChild(el);
  });
}

async function _editCluster(cluster) {
  if (!_worldId) return;
  const data = await promptEditCluster(cluster);
  if (!data) return;
  if (data.delete) {
    try {
      await _fetch(`/api/atlas/worlds/${_worldId}/clusters/${cluster.id}`, { method: 'DELETE' });
      const parentId = cluster.parent_cluster_id || null;
      _clusters = _clusters.filter(c => c.id !== cluster.id);
      _clusters.forEach(c => {
        if (c.parent_cluster_id === cluster.id) c.parent_cluster_id = parentId;
      });
      _nodes.forEach(n => {
        if (n.cluster_id === cluster.id) n.cluster_id = parentId;
      });
      if (_selectedClusterId === cluster.id) _selectedClusterId = null;
      _renderCanvas(_container?.querySelector('#atlas-canvas-world'));
      _scheduleSave();
      toastClusterUpdated();
    } catch (err) {
      uiModule.showError(err.message);
    }
    return;
  }
  cluster.name = data.name;
  cluster.color = data.color;
  try {
    await _fetch(`/api/atlas/worlds/${_worldId}/clusters/${cluster.id}`, {
      method: 'PUT',
      body: JSON.stringify({ name: data.name, color: data.color }),
    });
    _renderCanvas(_container?.querySelector('#atlas-canvas-world'));
    _scheduleSave();
    toastClusterUpdated();
  } catch (err) {
    uiModule.showError(err.message);
  }
}

function _wireClusterDrag(el, cluster) {
  let dragging = false;
  let moved = false;
  let sx = 0; let sy = 0;
  const startPositions = new Map();
  const header = el.querySelector('.atlas-cluster-header');
  const body = el.querySelector('.atlas-cluster-body');
  const dragTargets = [header, body].filter(Boolean);
  dragTargets.forEach(target => {
    target.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.atlas-cluster-btn')) return;
      _dismissLabelEditor();
      _selectedClusterId = cluster.id;
      dragging = true;
      moved = false;
      sx = e.clientX; sy = e.clientY;
      startPositions.clear();
      const descIds = [cluster.id, ..._descendantClusterIds(cluster.id)];
      descIds.forEach(id => {
        const c = _clusterById(id);
        if (c) startPositions.set(`c:${id}`, { x: c.x, y: c.y });
      });
      _nodes.filter(n => n.cluster_id && descIds.includes(n.cluster_id)).forEach(n => {
        startPositions.set(`n:${n.entity_id}`, { x: n.x, y: n.y });
      });
      el.setPointerCapture(e.pointerId);
      e.stopPropagation();
    });
  });
  el.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const dx = (e.clientX - sx) / _zoom;
    const dy = (e.clientY - sy) / _zoom;
    if (!moved && Math.hypot(e.clientX - sx, e.clientY - sy) > MOVE_THRESHOLD) {
      moved = true;
      el.classList.add('atlas-cluster-dragging');
    }
    if (!moved) return;
    startPositions.forEach((pos, key) => {
      if (key.startsWith('c:')) {
        const c = _clusterById(key.slice(2));
        if (c) {
          c.x = pos.x + dx;
          c.y = pos.y + dy;
          const cel = _container?.querySelector(`.atlas-canvas-cluster[data-cluster-id="${c.id}"]`);
          if (cel) {
            cel.style.left = `${c.x}px`;
            cel.style.top = `${c.y}px`;
          }
        }
      } else if (key.startsWith('n:')) {
        const n = _nodes.find(x => x.entity_id === key.slice(2));
        if (n) {
          n.x = pos.x + dx;
          n.y = pos.y + dy;
          const card = _container?.querySelector(`.atlas-canvas-card[data-entity-id="${n.entity_id}"]`);
          if (card) {
            card.style.left = `${n.x}px`;
            card.style.top = `${n.y}px`;
          }
        }
      }
    });
    const cx = cluster.x + cluster.w / 2;
    const cy = cluster.y + cluster.h / 2;
    _applyDropHighlights(cx, cy, { excludeClusterId: cluster.id });
    _scheduleEdgeRender(false);
  });
  el.addEventListener('pointerup', (e) => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove('atlas-cluster-dragging');
    _clearDropHighlights();
    if (moved) {
      e.preventDefault();
      const cx = cluster.x + cluster.w / 2;
      const cy = cluster.y + cluster.h / 2;
      const targetParent = _hitTestCluster(cx, cy, cluster.id);
      if (targetParent) {
        cluster.parent_cluster_id = targetParent;
      } else {
        cluster.parent_cluster_id = null;
      }
      _scheduleSave();
      return;
    }
  });
  el.addEventListener('pointercancel', () => {
    dragging = false;
    moved = false;
    el.classList.remove('atlas-cluster-dragging');
    _clearDropHighlights();
  });
}

function _wireClusterResize(el, cluster) {
  el.querySelectorAll('.atlas-cluster-resize').forEach(handle => {
    handle.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      e.preventDefault();
      const mode = handle.dataset.resize || 'se';
      const sx = e.clientX;
      const sy = e.clientY;
      const ow = cluster.w;
      const oh = cluster.h;
      const onMove = (ev) => {
        const dx = (ev.clientX - sx) / _zoom;
        const dy = (ev.clientY - sy) / _zoom;
        if (mode.includes('e')) cluster.w = Math.max(MIN_CLUSTER_W, ow + dx);
        if (mode.includes('s')) cluster.h = Math.max(MIN_CLUSTER_H, oh + dy);
        el.style.width = `${cluster.w}px`;
        el.style.height = `${cluster.h}px`;
      };
      const onUp = () => {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        document.removeEventListener('pointercancel', onUp);
        _scheduleSave();
      };
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
      document.addEventListener('pointercancel', onUp);
    });
  });
}

async function _createClusterAt(x, y) {
  if (!(await _ensureWorld())) return;
  const data = await promptCluster();
  if (!data) return;
  try {
    const parentId = _hitTestCluster(x + DEFAULT_CLUSTER_W / 2, y + DEFAULT_CLUSTER_H / 2);
    const cluster = await _fetch(`/api/atlas/worlds/${_worldId}/clusters`, {
      method: 'POST',
      body: JSON.stringify({
        name: data.name,
        color: data.color,
        x, y,
        w: DEFAULT_CLUSTER_W,
        h: DEFAULT_CLUSTER_H,
        parent_cluster_id: parentId,
      }),
    });
    _clusters.push(cluster);
    _selectedClusterId = cluster.id;
    _renderCanvas(_container?.querySelector('#atlas-canvas-world'));
    _scheduleSave();
    toastClusterCreated();
  } catch (err) {
    uiModule.showError(err.message);
  }
}

function _renderCanvas(worldEl) {
  _renderClusters(worldEl);
  _renderCards(worldEl);
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
    card.className = 'atlas-canvas-card atlas-chrome atlas-card-alive';
    card.style.setProperty('--card-i', String(idx));
    card.style.setProperty('--card-enter-delay', `${Math.min(idx * 40, 400)}ms`);
    card.dataset.entityId = n.entity_id;
    card.style.left = `${n.x}px`;
    card.style.top = `${n.y}px`;
    card.style.width = `${n.w || DEFAULT_CARD_W}px`;
    card.style.height = `${n.h || DEFAULT_CARD_H}px`;
    if (n.z_index) card.style.zIndex = String(20 + n.z_index);
    card.innerHTML = `
      ${_portMarkup()}
      <div class="atlas-card-header">
        <div class="atlas-card-title">${_esc(n.name)}</div>
        <button type="button" class="atlas-card-edit" title="Edit collection" aria-label="Edit collection">✎</button>
      </div>
      <div class="atlas-card-meta">${n.row_count || 0} docs</div>
      <div class="atlas-card-resize atlas-card-resize-e" data-resize="e"></div>
      <div class="atlas-card-resize atlas-card-resize-s" data-resize="s"></div>
      <div class="atlas-card-resize atlas-card-resize-se" data-resize="se"></div>`;
    _wireCardDrag(card, n);
    _wireCardResize(card, n);
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
    if (e.target.classList.contains('atlas-card-port')
      || e.target.closest('.atlas-card-edit')
      || e.target.closest('.atlas-card-resize')) return;
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
    const cx = node.x + (node.w || 200) / 2;
    const cy = node.y + (node.h || 120) / 2;
    _applyDropHighlights(cx, cy, { cardEl: card });
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
    _clearDropHighlights();
    if (moved) {
      e.preventDefault();
      const cx = node.x + (node.w || 200) / 2;
      const cy = node.y + (node.h || 120) / 2;
      node.cluster_id = _hitTestCluster(cx, cy);
      _scheduleSave();
      return;
    }
    if (e.target.closest('.atlas-card-edit') || e.target.closest('.atlas-card-port') || e.target.closest('.atlas-card-resize')) return;
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
    _clearDropHighlights();
  });
}

function _wireCardResize(card, node) {
  card.querySelectorAll('.atlas-card-resize').forEach(handle => {
    handle.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      e.preventDefault();
      const mode = handle.dataset.resize || 'se';
      const sx = e.clientX;
      const sy = e.clientY;
      const ow = node.w || DEFAULT_CARD_W;
      const oh = node.h || DEFAULT_CARD_H;
      card.classList.add('atlas-card-resizing');
      const onMove = (ev) => {
        const dx = (ev.clientX - sx) / _zoom;
        const dy = (ev.clientY - sy) / _zoom;
        if (mode.includes('e')) node.w = Math.max(MIN_CARD_W, ow + dx);
        if (mode.includes('s')) node.h = Math.max(MIN_CARD_H, oh + dy);
        card.style.width = `${node.w}px`;
        card.style.height = `${node.h}px`;
        _scheduleEdgeRender(false);
      };
      const onUp = () => {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        document.removeEventListener('pointercancel', onUp);
        card.classList.remove('atlas-card-resizing');
        _scheduleSave();
        _scheduleEdgeRender(false);
      };
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
      document.addEventListener('pointercancel', onUp);
    });
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

function _viewportCenterWorld(w = 0, h = 0) {
  const surface = _container?.querySelector('#atlas-canvas-surface');
  if (!surface) return { x: 100, y: 100 };
  const rect = surface.getBoundingClientRect();
  const world = _surfaceToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
  return { x: world.x - w / 2, y: world.y - h / 2 };
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

function _applyWorldTransform(worldEl) {
  worldEl.style.transform = `translate(${_panX}px,${_panY}px) scale(${_zoom})`;
}

function _wirePanZoom(surface, worldEl) {
  let panning = false;
  let sx = 0; let sy = 0;
  let spaceDown = false;

  window.addEventListener('keydown', (e) => { if (e.code === 'Space') spaceDown = true; });
  window.addEventListener('keyup', (e) => { if (e.code === 'Space') spaceDown = false; });

  surface.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = surface.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const worldX = (mx - _panX) / _zoom;
    const worldY = (my - _panY) / _zoom;
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.min(2.5, Math.max(0.25, _zoom * delta));
    _panX = mx - worldX * newZoom;
    _panY = my - worldY * newZoom;
    _zoom = newZoom;
    _applyWorldTransform(worldEl);
  }, { passive: false });

  surface.addEventListener('pointerdown', (e) => {
    if (e.button !== 1) return;
    e.preventDefault();
    e.stopPropagation();
    panning = true;
    sx = e.clientX; sy = e.clientY;
    surface.setPointerCapture(e.pointerId);
  }, { capture: true });

  surface.addEventListener('pointerdown', (e) => {
    if (e.target === surface || e.target.classList.contains('atlas-canvas-surface')) {
      _dismissLabelEditor();
    }
    if (spaceDown || e.target === surface || e.target.classList.contains('atlas-canvas-surface')) {
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
    _applyWorldTransform(worldEl);
  });
  surface.addEventListener('pointerup', () => { panning = false; });
  surface.addEventListener('pointercancel', () => { panning = false; });

  surface.addEventListener('dblclick', async (e) => {
    if (e.target !== surface && !e.target.classList.contains('atlas-canvas-surface')) return;
    const rect = surface.getBoundingClientRect();
    const x = (e.clientX - rect.left - _panX) / _zoom;
    const y = (e.clientY - rect.top - _panY) / _zoom;
    if (e.shiftKey) {
      await _createClusterAt(x, y);
    } else {
      await _createEntityAt(x, y);
    }
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
  _nodes = (layout.nodes || []).map(n => ({
    ...n,
    w: n.w ?? DEFAULT_CARD_W,
    h: n.h ?? DEFAULT_CARD_H,
  }));
  _clusters = layout.clusters || [];
  _relationships = rels.relationships || [];
  _entities = entData.entities || _entities;
  const worldEl = _container?.querySelector('#atlas-canvas-world');
  _renderCanvas(worldEl);
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
  _updateWorldActionsState();
}

function _currentWorld() {
  return _worlds.find(w => w.id === _worldId) || null;
}

function _updateWorldActionsState() {
  const actions = _container?.querySelector('.atlas-world-actions');
  if (!actions) return;
  actions.classList.toggle('atlas-disabled', !_worldId);
}

function _worldManagerCallbacks() {
  return {
    activeWorldId: _worldId,
    fetchWorlds: async (archived) => {
      const q = archived ? 'true' : 'false';
      const data = await _fetch(`/api/atlas/worlds?archived=${q}`);
      return data.worlds || [];
    },
    onExportExcel: async (wid, name) => {
      try {
        const stats = await exportWorldExcel(wid, name);
        toastWorldExported(stats.entity_count, stats.document_count);
      } catch (e) {
        uiModule.showError(e.message);
      }
    },
    onImportExcel: async (targetWorldId) => {
      await openWorldExcelImportWizard({
        worldId: targetWorldId || null,
        entities: _entities,
        onComplete: async (result) => {
          if (!result?.world_id) return;
          _worldId = result.world_id;
          await _reloadActiveWorlds();
          _updateWorldSelect();
          if (_onWorldChange) await _onWorldChange(_worldId);
          await _refresh();
          toastWorldImported(result);
        },
      });
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
  };
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
    const { x, y } = _viewportCenterWorld(200, 120);
    await _createEntityAt(x, y);
  });

  _container?.querySelector('#atlas-new-cluster-btn')?.addEventListener('click', async () => {
    await _createClusterAt(80 + _clusters.length * 40, 80 + _clusters.length * 40);
  });

  _container?.querySelector('#atlas-world-select')?.addEventListener('change', async (e) => {
    _worldId = e.target.value;
    const w = _worlds.find(x => x.id === _worldId);
    if (w) toastWorldSwitched(w.name);
    if (_onWorldChange) _onWorldChange(_worldId);
    await _refresh();
  });

  _container?.querySelector('#atlas-worlds-btn')?.addEventListener('click', () => {
    openWorldsManager(_worldManagerCallbacks());
  });

  const cb = _worldManagerCallbacks();

  _container?.querySelector('#atlas-world-export-btn')?.addEventListener('click', async () => {
    const w = _currentWorld();
    if (!w) return;
    await cb.onExportExcel(w.id, w.name);
  });

  _container?.querySelector('#atlas-world-rename-btn')?.addEventListener('click', async () => {
    const w = _currentWorld();
    if (!w) return;
    const name = await uiModule.styledPrompt(`Rename "${w.name}"`, {
      title: 'Rename world', defaultValue: w.name, confirmText: 'Save',
    });
    if (!name || name === w.name) return;
    await cb.onSwitch(w.id, 'rename', { name });
  });

  _container?.querySelector('#atlas-world-archive-btn')?.addEventListener('click', async () => {
    const w = _currentWorld();
    if (!w) return;
    await cb.onSwitch(w.id, 'archive');
  });

  _container?.querySelector('#atlas-world-delete-btn')?.addEventListener('click', async () => {
    const w = _currentWorld();
    if (!w) return;
    const ok = await promptTypeToConfirm(
      w.name,
      `This permanently deletes "${w.name}" and all its data. This cannot be undone.`,
    );
    if (!ok) return;
    await cb.onSwitch(w.id, 'delete', { name: w.name });
  });

  _container?.querySelector('#atlas-world-import-excel-btn')?.addEventListener('click', async () => {
    if (!_worldId) return;
    await cb.onImportExcel(_worldId);
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
        <div class="atlas-world-actions">
          <button type="button" class="admin-btn-sm" id="atlas-world-export-btn">Export Excel</button>
          <button type="button" class="admin-btn-sm" id="atlas-world-rename-btn">Rename</button>
          <button type="button" class="admin-btn-sm" id="atlas-world-archive-btn">Archive</button>
          <button type="button" class="admin-btn-sm" id="atlas-world-delete-btn" style="color:#dc2626">Delete</button>
          <button type="button" class="admin-btn-sm" id="atlas-world-import-excel-btn">Import Excel…</button>
        </div>
        <button type="button" class="admin-btn-sm" id="atlas-worlds-btn">Worlds…</button>
        <div class="atlas-header-actions">
          <button type="button" class="admin-btn-sm" id="atlas-new-world-btn">+ World</button>
          <button type="button" class="admin-btn-sm" id="atlas-new-cluster-btn">+ Cluster</button>
          <button type="button" class="admin-btn-sm" id="atlas-new-entity-btn">+ Collection</button>
          <button type="button" class="atlas-close-btn" id="atlas-close-btn" title="Close">✕</button>
        </div>
      </div>
      <div class="atlas-canvas-surface" id="atlas-canvas-surface">
        <div id="atlas-canvas-world" class="atlas-canvas-world">
          <div id="atlas-canvas-clusters" class="atlas-canvas-clusters-layer"></div>
          <svg id="atlas-canvas-svg" class="atlas-canvas-svg"></svg>
        </div>
      </div>
      <div class="atlas-canvas-hint atlas-chrome">Click card to browse · Drag collections into clusters (innermost wins) · + Cluster or Shift+double-click empty space · Drag cluster header to move group · Scroll to zoom · Middle-click or Space+drag to pan</div>
    </div>`;

  _updateWorldSelect();
  _wireToolbar();
  const surface = container.querySelector('#atlas-canvas-surface');
  const worldEl = container.querySelector('#atlas-canvas-world');
  worldEl.style.transform = `translate(${_panX}px,${_panY}px) scale(${_zoom})`;
  _updateWorldActionsState();
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
  _selectedClusterId = null;
  _clusters = [];
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
