/**
 * Atlas modal dialogs — world, entity, relationship creation.
 */
import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';
import {
  parseCardinalities, edgeVisuals, cardinalityMarkerHtml, cardinalityOptionsHtml,
} from './atlas-rel-cardinality.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _wireModalEnterSubmit(wrap, submitBtn) {
  if (!wrap || !submitBtn) return;
  wrap.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.isComposing) return;
    const tag = e.target?.tagName;
    if (tag === 'TEXTAREA' || tag === 'BUTTON') return;
    if (submitBtn.disabled) return;
    e.preventDefault();
    submitBtn.click();
  });
}

function _modal(title, bodyHtml, onSubmit, { submitLabel = 'Create', modalClass = '', minHeight } = {}) {
  const contentCls = ['modal-content', 'atlas-modal-content', modalClass].filter(Boolean).join(' ');
  const widthStyle = modalClass === 'atlas-doc-modal' ? '' : ' style="max-width:420px"';
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    wrap.innerHTML = `
      <div class="${contentCls}"${widthStyle}>
        <div class="modal-header">
          <h4>${_esc(title)}</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body">${bodyHtml}</div>
        <div class="modal-footer atlas-modal-footer">
          <button type="button" class="admin-btn-sm atlas-modal-cancel">Cancel</button>
          <button type="button" class="admin-btn-sm atlas-modal-submit">${_esc(submitLabel)}</button>
        </div>
      </div>`;
    const close = (val) => { wrap.remove(); resolve(val); };
    wrap.querySelector('.atlas-modal-close')?.addEventListener('click', () => close(null));
    wrap.querySelector('.atlas-modal-cancel')?.addEventListener('click', () => close(null));
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(null); });
    const submitBtn = wrap.querySelector('.atlas-modal-submit');
    submitBtn?.addEventListener('click', async () => {
      try {
        const val = await onSubmit(wrap);
        if (val !== false) close(val);
      } catch (err) {
        uiModule.showError(err.message || String(err));
      }
    });
    _wireModalEnterSubmit(wrap, submitBtn);
    document.body.appendChild(wrap);
    const content = wrap.querySelector('.modal-content');
    const header = wrap.querySelector('.modal-header');
    if (content && header) {
      makeWindowDraggable(wrap, {
        content,
        header,
        skipSelector: 'button, input, select, textarea, label',
        enableDock: true,
        minHeight,
      });
    }
    const first = wrap.querySelector('input, select, textarea');
    if (first) { first.focus(); first.select?.(); }
  });
}

export function promptWorld() {
  return _modal(
    'New World',
    `<label class="atlas-form-label">Name<input type="text" class="atlas-form-input" id="atlas-modal-name" placeholder="My World" value="New World" /></label>
     <label class="atlas-form-label" style="margin-top:10px">Description<textarea class="atlas-form-input" id="atlas-modal-desc" rows="2" placeholder="Optional"></textarea></label>`,
    (wrap) => ({
      name: wrap.querySelector('#atlas-modal-name')?.value?.trim() || 'New World',
      description: wrap.querySelector('#atlas-modal-desc')?.value?.trim() || '',
    }),
  );
}

export function promptEntity(defaultName = 'Untitled') {
  return _modal(
    'New Collection',
    `<label class="atlas-form-label">Name<input type="text" class="atlas-form-input" id="atlas-modal-name" placeholder="Customers" value="${_esc(defaultName)}" /></label>
     <p class="atlas-form-hint">Fields are discovered automatically when you add documents.</p>`,
    (wrap) => {
      const name = wrap.querySelector('#atlas-modal-name')?.value?.trim();
      if (!name) throw new Error('Name is required');
      return { name };
    },
  );
}

export function promptEditEntity(entity) {
  return _modal(
    'Edit Collection',
    `<label class="atlas-form-label">Name<input type="text" class="atlas-form-input" id="atlas-modal-name" value="${_esc(entity?.name || '')}" /></label>
     <label class="atlas-form-label" style="margin-top:10px">Description<textarea class="atlas-form-input" id="atlas-modal-desc" rows="3" placeholder="Data definition or notes">${_esc(entity?.description || '')}</textarea></label>`,
    (wrap) => {
      const name = wrap.querySelector('#atlas-modal-name')?.value?.trim();
      if (!name) throw new Error('Name is required');
      return {
        name,
        description: wrap.querySelector('#atlas-modal-desc')?.value?.trim() || '',
      };
    },
    { submitLabel: 'Save' },
  );
}

const CLUSTER_COLORS = [
  { id: '', label: 'Default' },
  { id: 'blue', label: 'Blue' },
  { id: 'green', label: 'Green' },
  { id: 'amber', label: 'Amber' },
  { id: 'rose', label: 'Rose' },
  { id: 'violet', label: 'Violet' },
];

function _clusterColorOptions(selected = '') {
  return CLUSTER_COLORS.map(c =>
    `<option value="${_esc(c.id)}"${c.id === selected ? ' selected' : ''}>${_esc(c.label)}</option>`
  ).join('');
}

export function promptCluster(defaultName = 'New Cluster') {
  return _modal(
    'New Cluster',
    `<label class="atlas-form-label">Name<input type="text" class="atlas-form-input" id="atlas-modal-name" placeholder="Work" value="${_esc(defaultName)}" /></label>
     <label class="atlas-form-label" style="margin-top:10px">Color<select class="atlas-form-input" id="atlas-cluster-color">${_clusterColorOptions()}</select></label>
     <p class="atlas-form-hint">Ringfence collections on the canvas — nest clusters inside each other like Draw.io containers.</p>`,
    (wrap) => {
      const name = wrap.querySelector('#atlas-modal-name')?.value?.trim();
      if (!name) throw new Error('Name is required');
      return {
        name,
        color: wrap.querySelector('#atlas-cluster-color')?.value || '',
      };
    },
  );
}

export function promptEditCluster(cluster) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    wrap.innerHTML = `
      <div class="modal-content atlas-modal-content" style="max-width:420px">
        <div class="modal-header">
          <h4>Edit Cluster</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body">
          <label class="atlas-form-label">Name<input type="text" class="atlas-form-input" id="atlas-modal-name" value="${_esc(cluster?.name || '')}" /></label>
          <label class="atlas-form-label" style="margin-top:10px">Color<select class="atlas-form-input" id="atlas-cluster-color">${_clusterColorOptions(cluster?.color || '')}</select></label>
        </div>
        <div class="modal-footer atlas-modal-footer" style="justify-content:space-between">
          <button type="button" class="admin-btn-sm atlas-cluster-delete" style="color:#dc2626">Delete</button>
          <div style="display:flex;gap:8px">
            <button type="button" class="admin-btn-sm atlas-modal-cancel">Cancel</button>
            <button type="button" class="admin-btn-sm atlas-modal-submit">Save</button>
          </div>
        </div>
      </div>`;
    const close = (val) => { wrap.remove(); resolve(val); };
    wrap.querySelector('.atlas-modal-close')?.addEventListener('click', () => close(null));
    wrap.querySelector('.atlas-modal-cancel')?.addEventListener('click', () => close(null));
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(null); });
    wrap.querySelector('.atlas-cluster-delete')?.addEventListener('click', () => close({ delete: true }));
    const submitBtn = wrap.querySelector('.atlas-modal-submit');
    submitBtn?.addEventListener('click', () => {
      const name = wrap.querySelector('#atlas-modal-name')?.value?.trim();
      if (!name) {
        uiModule.showError('Name is required');
        return;
      }
      close({
        name,
        color: wrap.querySelector('#atlas-cluster-color')?.value || '',
      });
    });
    _wireModalEnterSubmit(wrap, submitBtn);
    document.body.appendChild(wrap);
    const content = wrap.querySelector('.modal-content');
    const header = wrap.querySelector('.modal-header');
    if (content && header) {
      makeWindowDraggable(wrap, { content, header, skipSelector: 'button, input, select, textarea, label', enableDock: true });
    }
    wrap.querySelector('#atlas-modal-name')?.focus();
  });
}

const REL_SVG_NS = 'http://www.w3.org/2000/svg';
const REL_CONNECTOR_PATH = 'M 0 20 H 200';

function _entityMeta(entity) {
  return `${entity?.row_count || 0} docs`;
}

function _entityPanelHtml({ role, side, entities, entityId, locked }) {
  const selectId = side === 'from' ? 'atlas-rel-from' : 'atlas-rel-to';
  const resolvedId = entityId || entities[0]?.id || '';
  const entity = entities.find(e => e.id === resolvedId);
  const roleLabel = role === 'from' ? 'From' : 'To';

  let nameHtml;
  if (locked && entityId) {
    nameHtml = `<div class="atlas-rel-entity-name">${_esc(entity?.name || '—')}</div>
      <input type="hidden" id="${selectId}" value="${_esc(resolvedId)}" />`;
  } else {
    const opts = entities.map(e =>
      `<option value="${_esc(e.id)}"${e.id === resolvedId ? ' selected' : ''}>${_esc(e.name)}</option>`
    ).join('');
    nameHtml = `<select class="atlas-rel-entity-select" id="${selectId}">${opts}</select>`;
  }

  return `<div class="atlas-rel-entity atlas-rel-entity-${side} atlas-chrome" data-side="${side}">
    <div class="atlas-rel-entity-role">${roleLabel}</div>
    ${nameHtml}
    <div class="atlas-rel-entity-meta">${_entityMeta(entity)}</div>
  </div>`;
}

function _splitModalConnectorPath() {
  const mx = 100;
  return {
    full: REL_CONNECTOR_PATH,
    first: `M 0 20 H ${mx}`,
    second: `M ${mx} 20 H 200`,
  };
}

function _appendModalFlowBalls(svg, ballsG, d, direction, color, pathUid) {
  const pathId = `atlas-modal-flow-${pathUid}`;
  const track = document.createElementNS(REL_SVG_NS, 'path');
  track.setAttribute('id', pathId);
  track.setAttribute('d', d);
  track.setAttribute('fill', 'none');
  track.setAttribute('stroke', 'none');
  track.classList.add('atlas-edge-flow-track');
  svg.appendChild(track);

  const BALL_COUNT = 4;
  const DUR = 1.4;
  for (let i = 0; i < BALL_COUNT; i++) {
    const circle = document.createElementNS(REL_SVG_NS, 'circle');
    circle.classList.add('atlas-edge-flow-ball');
    circle.setAttribute('r', '3');
    circle.setAttribute('fill', color);

    const motion = document.createElementNS(REL_SVG_NS, 'animateMotion');
    motion.setAttribute('dur', `${DUR}s`);
    motion.setAttribute('repeatCount', 'indefinite');
    motion.setAttribute('begin', `${(i * DUR) / BALL_COUNT}s`);
    if (direction === 'reverse') {
      motion.setAttribute('keyPoints', '1;0');
      motion.setAttribute('keyTimes', '0;1');
      motion.setAttribute('calcMode', 'linear');
    }
    const mpath = document.createElementNS(REL_SVG_NS, 'mpath');
    mpath.setAttribute('href', `#${pathId}`);
    motion.appendChild(mpath);

    const pulse = document.createElementNS(REL_SVG_NS, 'animate');
    pulse.setAttribute('attributeName', 'opacity');
    pulse.setAttribute('values', '0.25;1;0.25');
    pulse.setAttribute('dur', '0.7s');
    pulse.setAttribute('repeatCount', 'indefinite');
    pulse.setAttribute('begin', `${(i * DUR) / BALL_COUNT}s`);

    circle.appendChild(pulse);
    circle.appendChild(motion);
    ballsG.appendChild(circle);
  }
}

function _updateModalConnectorFlow(svg, flowMode, color) {
  svg.querySelectorAll('.atlas-edge-flow-track, .atlas-rel-modal-flow-balls').forEach(el => el.remove());
  const ballsG = document.createElementNS(REL_SVG_NS, 'g');
  ballsG.classList.add('atlas-rel-modal-flow-balls', 'atlas-edge-flow-balls');
  const paths = _splitModalConnectorPath();

  if (flowMode === 'many_many') {
    _appendModalFlowBalls(svg, ballsG, paths.second, 'forward', color, 'out-to');
    _appendModalFlowBalls(svg, ballsG, paths.first, 'reverse', color, 'out-from');
  } else if (flowMode === 'one_one') {
    _appendModalFlowBalls(svg, ballsG, paths.first, 'forward', color, 'in-from');
    _appendModalFlowBalls(svg, ballsG, paths.second, 'reverse', color, 'in-to');
  } else {
    _appendModalFlowBalls(svg, ballsG, paths.full, 'forward', color, 'fwd');
  }
  svg.appendChild(ballsG);
}

function _readModalCardinalities(wrap) {
  return {
    from: wrap.querySelector('#atlas-rel-from-cardinality')?.value || 'one',
    to: wrap.querySelector('#atlas-rel-to-cardinality')?.value || 'many',
  };
}

function _relationshipLayoutHtml(opts) {
  const {
    entities, fromId, toId, fromLocked, toLocked,
    fromCardinality, toCardinality,
    fromField, toField, label, fromAnchor, toAnchor,
  } = opts;
  const anchorFields = fromAnchor !== undefined
    ? `<input type="hidden" id="atlas-rel-from-anchor" value="${_esc(fromAnchor)}" />
       <input type="hidden" id="atlas-rel-to-anchor" value="${_esc(toAnchor)}" />`
    : '';

  return `<div class="atlas-rel-modal">
    <section class="atlas-rel-bridge" aria-label="Relationship endpoints">
      ${_entityPanelHtml({ role: 'from', side: 'from', entities, entityId: fromId, locked: fromLocked })}
      <div class="atlas-rel-end-cap atlas-rel-end-from">
        <div class="atlas-rel-entity-marker" data-end="from"></div>
      </div>
      <div class="atlas-rel-connector">
        <svg class="atlas-rel-connector-svg" viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true">
          <path class="atlas-edge-live atlas-rel-connector-path" d="${REL_CONNECTOR_PATH}" fill="none" stroke-width="2"/>
        </svg>
      </div>
      <div class="atlas-rel-end-cap atlas-rel-end-to">
        <div class="atlas-rel-entity-marker" data-end="to"></div>
      </div>
      ${_entityPanelHtml({ role: 'to', side: 'to', entities, entityId: toId, locked: toLocked })}
    </section>
    <section class="atlas-rel-fields">
      <div class="atlas-rel-cardinality-row">
        <label class="atlas-form-label">From cardinality${cardinalityOptionsHtml(fromCardinality, 'from')}</label>
        <label class="atlas-form-label">To cardinality${cardinalityOptionsHtml(toCardinality, 'to')}</label>
      </div>
      <label class="atlas-form-label">From field <span class="atlas-filter-hint">(optional)</span><input class="atlas-form-input" id="atlas-rel-from-field" value="${_esc(fromField)}" placeholder="Inferred from data" /></label>
      <label class="atlas-form-label">To field <span class="atlas-filter-hint">(optional)</span><input class="atlas-form-input" id="atlas-rel-to-field" value="${_esc(toField)}" placeholder="Inferred from data" /></label>
      <label class="atlas-form-label">Label<input class="atlas-form-input" id="atlas-rel-label" value="${_esc(label)}" placeholder="Optional" /></label>
      ${anchorFields}
    </section>
  </div>`;
}

function _updateRelModalVisuals(wrap, entities) {
  const { from, to } = _readModalCardinalities(wrap);
  const { color, flowMode } = edgeVisuals(from, to);
  const path = wrap.querySelector('.atlas-rel-connector-path');
  if (path) path.setAttribute('stroke', color);
  const svg = wrap.querySelector('.atlas-rel-connector-svg');
  if (svg) _updateModalConnectorFlow(svg, flowMode, color);
  wrap.querySelectorAll('.atlas-rel-entity-marker').forEach(host => {
    const end = host.dataset.end === 'from' ? 'from' : 'to';
    host.innerHTML = cardinalityMarkerHtml(end === 'from' ? from : to, end);
  });
  wrap.querySelectorAll('.atlas-rel-entity-select').forEach(sel => {
    const ent = entities.find(e => e.id === sel.value);
    const meta = sel.closest('.atlas-rel-entity')?.querySelector('.atlas-rel-entity-meta');
    if (meta && ent) meta.textContent = _entityMeta(ent);
  });
  const bridge = wrap.querySelector('.atlas-rel-bridge');
  if (bridge) bridge.style.setProperty('--atlas-rel-color', color);
}

function _wireRelationshipModal(wrap, entities) {
  wrap.querySelector('#atlas-rel-from-cardinality')?.addEventListener('change', () => _updateRelModalVisuals(wrap, entities));
  wrap.querySelector('#atlas-rel-to-cardinality')?.addEventListener('change', () => _updateRelModalVisuals(wrap, entities));
  wrap.querySelectorAll('.atlas-rel-entity-select').forEach(sel => {
    sel.addEventListener('change', () => _updateRelModalVisuals(wrap, entities));
  });
  _updateRelModalVisuals(wrap, entities);
}

function _readRelationshipValues(wrap, fromIdFallback, toIdFallback, fromAnchor, toAnchor) {
  const { from, to } = _readModalCardinalities(wrap);
  return {
    from_entity_id: wrap.querySelector('#atlas-rel-from')?.value || fromIdFallback,
    to_entity_id: wrap.querySelector('#atlas-rel-to')?.value || toIdFallback,
    from_cardinality: from,
    to_cardinality: to,
    from_field: wrap.querySelector('#atlas-rel-from-field')?.value?.trim() || '',
    to_field: wrap.querySelector('#atlas-rel-to-field')?.value?.trim() || '',
    label: wrap.querySelector('#atlas-rel-label')?.value?.trim() || '',
    from_anchor: wrap.querySelector('#atlas-rel-from-anchor')?.value || fromAnchor,
    to_anchor: wrap.querySelector('#atlas-rel-to-anchor')?.value || toAnchor,
  };
}

function _mountRelationshipModal({
  title, submitLabel, bodyHtml, onSubmit, onMount, footerExtra = '', footerSplit = false,
}) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    const footerStyle = footerSplit ? ' style="justify-content:space-between"' : '';
    const btnGroupStyle = footerSplit ? ' style="display:flex;gap:8px"' : ' style="display:flex;gap:8px;margin-left:auto"';
    wrap.innerHTML = `
      <div class="modal-content atlas-modal-content atlas-rel-modal-content" style="max-width:520px">
        <div class="modal-header">
          <h4>${_esc(title)}</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body">${bodyHtml}</div>
        <div class="modal-footer atlas-modal-footer"${footerStyle}>
          ${footerExtra}
          <div${btnGroupStyle}>
            <button type="button" class="admin-btn-sm atlas-modal-cancel">Cancel</button>
            <button type="button" class="admin-btn-sm atlas-modal-submit">${_esc(submitLabel)}</button>
          </div>
        </div>
      </div>`;
    const close = (val) => { wrap.remove(); resolve(val); };
    wrap.querySelector('.atlas-modal-close')?.addEventListener('click', () => close(null));
    wrap.querySelector('.atlas-modal-cancel')?.addEventListener('click', () => close(null));
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(null); });
    const submitBtn = wrap.querySelector('.atlas-modal-submit');
    submitBtn?.addEventListener('click', async () => {
      try {
        const val = await onSubmit(wrap);
        if (val !== false) close(val);
      } catch (err) {
        uiModule.showError(err.message || String(err));
      }
    });
    _wireModalEnterSubmit(wrap, submitBtn);
    document.body.appendChild(wrap);
    onMount?.(wrap, close);
    const content = wrap.querySelector('.modal-content');
    const header = wrap.querySelector('.modal-header');
    if (content && header) {
      makeWindowDraggable(wrap, {
        content,
        header,
        skipSelector: 'button, input, select, textarea, label',
        enableDock: true,
      });
    }
    wrap.querySelector('#atlas-rel-label')?.focus();
  });
}

export function promptRelationship(entities, fromId = '', toId = '', anchors = {}) {
  const fromAnchor = anchors.from_anchor || 'e';
  const toAnchor = anchors.to_anchor || 'w';
  const bodyHtml = _relationshipLayoutHtml({
    entities,
    fromId,
    toId,
    fromLocked: !!fromId,
    toLocked: !!toId,
    fromCardinality: 'one',
    toCardinality: 'many',
    fromField: '',
    toField: '',
    label: '',
    fromAnchor,
    toAnchor,
  });
  return _mountRelationshipModal({
    title: 'New Relationship',
    submitLabel: 'Create',
    bodyHtml,
    onMount: (wrap) => _wireRelationshipModal(wrap, entities),
    onSubmit: (wrap) => _readRelationshipValues(wrap, fromId, toId, fromAnchor, toAnchor),
  });
}

export function promptEditRelationship(rel, entities) {
  const { from, to } = parseCardinalities(rel);
  const bodyHtml = _relationshipLayoutHtml({
    entities,
    fromId: rel.from_entity_id,
    toId: rel.to_entity_id,
    fromLocked: true,
    toLocked: true,
    fromCardinality: from,
    toCardinality: to,
    fromField: rel.from_field || '',
    toField: rel.to_field || '',
    label: rel.label || '',
  });
  return _mountRelationshipModal({
    title: 'Edit Relationship',
    submitLabel: 'Save',
    bodyHtml,
    footerSplit: true,
    footerExtra: '<button type="button" class="admin-btn-sm atlas-rel-delete" style="color:#dc2626">Delete</button>',
    onMount: (wrap, close) => {
      _wireRelationshipModal(wrap, entities);
      wrap.querySelector('.atlas-rel-delete')?.addEventListener('click', async () => {
        const ok = await uiModule.styledConfirm('Delete this relationship?', { confirmText: 'Delete', danger: true });
        if (ok) close({ _delete: true });
      });
    },
    onSubmit: (wrap) => {
      const { from, to } = _readModalCardinalities(wrap);
      return {
        from_cardinality: from,
        to_cardinality: to,
        from_field: wrap.querySelector('#atlas-rel-from-field')?.value?.trim() || '',
        to_field: wrap.querySelector('#atlas-rel-to-field')?.value?.trim() || '',
        label: wrap.querySelector('#atlas-rel-label')?.value?.trim() || '',
      };
    },
  });
}

export function promptAddDocument() {
  return _modal(
    'Add Document',
    `<label class="atlas-form-label">Document JSON<textarea class="atlas-form-input atlas-doc-json" id="atlas-doc-json" rows="8" placeholder='{"name": "Alice", "email": "a@example.com"}'></textarea></label>
     <p class="atlas-form-hint">Paste a JSON object. An _id is assigned automatically.</p>`,
    (wrap) => {
      const raw = wrap.querySelector('#atlas-doc-json')?.value?.trim();
      if (!raw) throw new Error('Document JSON is required');
      let doc;
      try { doc = JSON.parse(raw); } catch { throw new Error('Invalid JSON'); }
      if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
        throw new Error('Document must be a JSON object');
      }
      return { document: doc };
    },
    { submitLabel: 'Insert', modalClass: 'atlas-doc-modal', minHeight: 440 },
  );
}

function _normalizeMongoId(val) {
  if (val && typeof val === 'object' && !Array.isArray(val) && val.$oid) {
    return String(val.$oid);
  }
  return val;
}

function _normalizeImportDoc(doc) {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return doc;
  if (!Object.prototype.hasOwnProperty.call(doc, '_id')) return doc;
  return { ...doc, _id: _normalizeMongoId(doc._id) };
}

export function normalizeImportDocuments(raw) {
  const trimmed = String(raw || '').trim();
  if (!trimmed) throw new Error('JSON is required');

  let parsed;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    const lines = trimmed.split(/\r?\n/).filter((l) => l.trim());
    if (lines.length > 1) {
      return lines
        .map((l) => _normalizeImportDoc(JSON.parse(l)))
        .filter((d) => d && typeof d === 'object' && !Array.isArray(d));
    }
    throw new Error('Invalid JSON');
  }

  if (Array.isArray(parsed)) {
    return parsed
      .map(_normalizeImportDoc)
      .filter((d) => d && typeof d === 'object' && !Array.isArray(d));
  }
  if (parsed && typeof parsed === 'object') {
    if (Array.isArray(parsed.documents)) {
      return normalizeImportDocuments(JSON.stringify(parsed.documents));
    }
    return [_normalizeImportDoc(parsed)];
  }
  throw new Error('Invalid JSON');
}

export function promptImportJson() {
  return _modal(
    'Import JSON',
    `<label class="atlas-form-label">JSON<textarea class="atlas-form-input atlas-doc-json" id="atlas-import-json" rows="10" placeholder='[{"name":"Alice"},{"name":"Bob"}]'></textarea></label>
     <p class="atlas-form-hint">Paste a JSON array, a single object, or NDJSON (one object per line). MongoDB <code>_id</code> values are preserved. Or choose a file below.</p>
     <label class="atlas-form-label" style="margin-top:8px">Or pick a file<input type="file" class="atlas-form-input" id="atlas-import-file" accept=".json,application/json" /></label>`,
    async (wrap) => {
      const fileInput = wrap.querySelector('#atlas-import-file');
      const textarea = wrap.querySelector('#atlas-import-json');
      let raw = textarea?.value?.trim() || '';
      if (fileInput?.files?.length) {
        raw = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ''));
          reader.onerror = () => reject(new Error('Could not read file'));
          reader.readAsText(fileInput.files[0]);
        });
      }
      if (!raw) throw new Error('JSON is required');
      return { raw };
    },
    { submitLabel: 'Import', modalClass: 'atlas-doc-modal', minHeight: 440 },
  );
}

export function promptTypeToConfirm(expectedName, message) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    wrap.innerHTML = `
      <div class="modal-content atlas-modal-content" style="max-width:420px">
        <div class="modal-header">
          <h4>Delete world</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body">
          <p style="margin:0 0 12px;font-size:13px">${_esc(message)}</p>
          <label class="atlas-form-label">Type <strong>${_esc(expectedName)}</strong> to confirm
            <input type="text" class="atlas-form-input" id="atlas-type-confirm" autocomplete="off" />
          </label>
        </div>
        <div class="modal-footer atlas-modal-footer">
          <button type="button" class="admin-btn-sm atlas-modal-cancel">Cancel</button>
          <button type="button" class="admin-btn-sm atlas-modal-submit atlas-delete-confirm" disabled>Delete</button>
        </div>
      </div>`;
    const close = (val) => { wrap.remove(); resolve(val); };
    const input = wrap.querySelector('#atlas-type-confirm');
    const delBtn = wrap.querySelector('.atlas-delete-confirm');
    input?.addEventListener('input', () => {
      delBtn.disabled = input.value !== expectedName;
    });
    wrap.querySelector('.atlas-modal-close')?.addEventListener('click', () => close(false));
    wrap.querySelector('.atlas-modal-cancel')?.addEventListener('click', () => close(false));
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(false); });
    delBtn?.addEventListener('click', () => { if (input?.value === expectedName) close(true); });
    _wireModalEnterSubmit(wrap, delBtn);
    document.body.appendChild(wrap);
    input?.focus();
  });
}

function _docForEdit(doc) {
  const body = { ...doc };
  delete body._atlas_created_at;
  delete body._atlas_updated_at;
  delete body._atlas_row_id;
  return body;
}

export function promptEditDocument(doc) {
  const raw = JSON.stringify(_docForEdit(doc), null, 2);
  return _modal(
    'Edit Document',
    `<label class="atlas-form-label">Document JSON<textarea class="atlas-form-input atlas-doc-json" id="atlas-doc-json" rows="14">${_esc(raw)}</textarea></label>`,
    (wrap) => {
      const text = wrap.querySelector('#atlas-doc-json')?.value?.trim();
      if (!text) throw new Error('Document JSON is required');
      let parsed;
      try { parsed = JSON.parse(text); } catch { throw new Error('Invalid JSON'); }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Document must be a JSON object');
      }
      return { document: parsed, docId: doc._id ?? doc._atlas_row_id };
    },
    { submitLabel: 'Save', modalClass: 'atlas-doc-modal', minHeight: 440 },
  );
}

export function openWorldsManager({
  fetchWorlds, activeWorldId, onSwitch, apiBase,
  onExportExcel, onImportExcel,
}) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    wrap.innerHTML = `
      <div class="modal-content atlas-modal-content atlas-worlds-modal" style="max-width:520px">
        <div class="modal-header">
          <h4>Worlds</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body">
          <div class="atlas-worlds-tabs">
            <button type="button" class="atlas-worlds-tab active" data-tab="active">Active</button>
            <button type="button" class="atlas-worlds-tab" data-tab="archived">Archived</button>
          </div>
          <div id="atlas-worlds-list" class="atlas-worlds-list"></div>
          ${onImportExcel ? `<div class="atlas-worlds-footer" style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">
            <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-world-import-excel">Import world from Excel…</button>
          </div>` : ''}
        </div>
      </div>`;

    let tab = 'active';
    let worlds = [];

    const close = () => { wrap.remove(); resolve(); };

    async function loadList() {
      const listEl = wrap.querySelector('#atlas-worlds-list');
      if (!listEl) return;
      listEl.innerHTML = '<div class="atlas-empty">Loading…</div>';
      try {
        worlds = await fetchWorlds(tab === 'archived');
        if (!worlds.length) {
          listEl.innerHTML = `<div class="atlas-empty">No ${tab} worlds.</div>`;
          return;
        }
        listEl.innerHTML = worlds.map(w => {
          const updated = w.updated_at ? new Date(w.updated_at).toLocaleDateString() : '';
          const isActive = w.id === activeWorldId;
          return `<div class="atlas-world-row${isActive ? ' atlas-world-row-active' : ''}" data-world-id="${_esc(w.id)}">
            <div class="atlas-world-row-main">
              <div class="atlas-world-row-name">${_esc(w.name)}${isActive ? ' <span class="atlas-world-current">current</span>' : ''}</div>
              <div class="atlas-world-row-meta">${w.entity_count || 0} collections · ${w.row_count || 0} docs · ${updated}</div>
            </div>
            <div class="atlas-world-row-actions">
              ${tab === 'active' ? `<button type="button" class="admin-btn-sm atlas-world-open" data-id="${_esc(w.id)}">Open</button>` : ''}
              ${tab === 'active' && onExportExcel ? `<button type="button" class="admin-btn-sm atlas-world-export" data-id="${_esc(w.id)}" data-name="${_esc(w.name)}">Export Excel</button>` : ''}
              <button type="button" class="admin-btn-sm atlas-world-rename" data-id="${_esc(w.id)}">Rename</button>
              ${tab === 'active'
    ? `<button type="button" class="admin-btn-sm atlas-world-archive" data-id="${_esc(w.id)}">Archive</button>`
    : `<button type="button" class="admin-btn-sm atlas-world-restore" data-id="${_esc(w.id)}">Restore</button>`}
              <button type="button" class="admin-btn-sm atlas-world-delete" data-id="${_esc(w.id)}" data-name="${_esc(w.name)}" style="color:#dc2626">Delete</button>
            </div>
          </div>`;
        }).join('');
      } catch (e) {
        listEl.innerHTML = `<div class="atlas-empty">${_esc(e.message)}</div>`;
      }
    }

    wrap.querySelector('.atlas-modal-close')?.addEventListener('click', close);
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });

    wrap.querySelector('.atlas-worlds-tabs')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('.atlas-worlds-tab');
      if (!btn) return;
      tab = btn.dataset.tab;
      wrap.querySelectorAll('.atlas-worlds-tab').forEach(t => t.classList.toggle('active', t === btn));
      await loadList();
    });

    wrap.querySelector('#atlas-worlds-list')?.addEventListener('click', async (e) => {
      const openBtn = e.target.closest('.atlas-world-open');
      const exportBtn = e.target.closest('.atlas-world-export');
      const renameBtn = e.target.closest('.atlas-world-rename');
      const archiveBtn = e.target.closest('.atlas-world-archive');
      const restoreBtn = e.target.closest('.atlas-world-restore');
      const deleteBtn = e.target.closest('.atlas-world-delete');

      if (openBtn) {
        await onSwitch(openBtn.dataset.id, 'open');
        close();
        return;
      }
      if (exportBtn && onExportExcel) {
        await onExportExcel(exportBtn.dataset.id, exportBtn.dataset.name);
        return;
      }
      if (renameBtn) {
        const w = worlds.find(x => x.id === renameBtn.dataset.id);
        if (!w) return;
        const name = await uiModule.styledPrompt(`Rename "${w.name}"`, {
          title: 'Rename world', defaultValue: w.name, confirmText: 'Save',
        });
        if (!name || name === w.name) return;
        await onSwitch(w.id, 'rename', { name });
        await loadList();
        return;
      }
      if (archiveBtn) {
        await onSwitch(archiveBtn.dataset.id, 'archive');
        await loadList();
        return;
      }
      if (restoreBtn) {
        const w = worlds.find(x => x.id === restoreBtn.dataset.id);
        if (!w) return;
        await onSwitch(w.id, 'restore', { name: w.name });
        await loadList();
        return;
      }
      if (deleteBtn) {
        const name = deleteBtn.dataset.name;
        const ok = await promptTypeToConfirm(
          name,
          `This permanently deletes "${name}" and all its data. This cannot be undone.`,
        );
        if (!ok) return;
        await onSwitch(deleteBtn.dataset.id, 'delete', { name });
        await loadList();
      }
    });

    wrap.querySelector('#atlas-world-import-excel')?.addEventListener('click', async () => {
      if (!onImportExcel) return;
      await onImportExcel(activeWorldId);
    });

    document.body.appendChild(wrap);
    const content = wrap.querySelector('.modal-content');
    const header = wrap.querySelector('.modal-header');
    if (content && header) {
      makeWindowDraggable(wrap, { content, header, skipSelector: 'button, input, select, textarea, label', enableDock: true });
    }
    loadList();
  });
}
