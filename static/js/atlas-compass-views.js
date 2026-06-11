/**
 * Atlas Compass view renderers — list, JSON, table.
 */
import { renderCompassDocument, highlightJson } from './atlas-json-tree.js';
import { toastCopied } from './atlas-toast.js';
import { buildDocKeyIndex, docGetField, fieldDisplayName } from './atlas-field-resolve.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _typeLabel(v, inferred) {
  if (inferred) return inferred;
  if (v === null || v === undefined) return 'Null';
  if (Array.isArray(v)) return 'Array';
  if (typeof v === 'object') return 'Object';
  if (typeof v === 'boolean') return 'Boolean';
  if (typeof v === 'number') return Number.isInteger(v) ? 'Int32' : 'Double';
  return 'String';
}

function _renderCellHtml(v, typeHint, has = true) {
  if (!has) {
    return '<span class="atlas-table-missing">No field</span>';
  }
  if (v === null || v === undefined) {
    return '<span class="atlas-json-null">null</span>';
  }
  const t = typeof v;
  if (t === 'string') return `<span class="atlas-json-str">"${_esc(v)}"</span>`;
  if (t === 'number') return `<span class="atlas-json-num">${v}</span>`;
  if (t === 'boolean') return `<span class="atlas-json-bool">${v}</span>`;
  if (t === 'object') {
    const j = JSON.stringify(v);
    const text = j.length > 48 ? `${j.slice(0, 45)}…` : j;
    return `<span class="atlas-json-str">${_esc(text)}</span>`;
  }
  return _esc(String(v));
}

function _cellValue(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') {
    const j = JSON.stringify(v);
    return j.length > 48 ? `${j.slice(0, 45)}…` : j;
  }
  return String(v);
}

export function renderListView(docs) {
  return docs.map(d => renderCompassDocument(d)).join('');
}

export function renderJsonView(docs) {
  return docs.map(doc => {
    const id = doc._id ?? doc._atlas_row_id ?? '?';
    const body = { ...doc };
    delete body._atlas_created_at;
    delete body._atlas_updated_at;
    const raw = JSON.stringify(body, null, 2);
    return `<div class="atlas-compass-json-block atlas-chrome" data-doc-id="${_esc(id)}">
      <div class="atlas-compass-json-header">
        <span class="atlas-doc-id">_id: ${_esc(id)}</span>
        <div class="atlas-json-header-actions">
          <button type="button" class="admin-btn-sm atlas-json-edit">Edit</button>
          <button type="button" class="admin-btn-sm atlas-json-copy">Copy</button>
          <button type="button" class="admin-btn-sm atlas-json-delete atlas-doc-delete" title="Delete">✕</button>
        </div>
      </div>
      <textarea class="atlas-json-raw" readonly hidden>${_esc(raw)}</textarea>
      <pre class="atlas-compass-json-pre">${highlightJson(raw)}</pre>
    </div>`;
  }).join('');
}

export function renderTableView(docs, fields) {
  if (!docs.length) {
    return '<div class="atlas-empty">No documents to show in table.</div>';
  }
  const cols = fields || [];
  const idField = cols.find(f => f.slug === '_id');
  const fieldCols = cols.filter(f => f.slug !== '_id');

  const head = `
    <th class="atlas-table-col-idx">#</th>
    <th class="atlas-table-col-id">
      <div class="atlas-table-col-name">_id</div>
      <div class="atlas-table-col-type">${_esc(idField?.inferred_type || 'Int32')}</div>
    </th>
    ${fieldCols.map(f => `
      <th>
        <div class="atlas-table-col-name">${_esc(fieldDisplayName(f))}</div>
        <div class="atlas-table-col-type">${_esc(f.inferred_type || 'Mixed')}</div>
      </th>`).join('')}
    <th class="atlas-table-col-actions"></th>`;

  const rows = docs.map((doc, idx) => {
    const id = doc._id ?? doc._atlas_row_id ?? '';
    const idType = _typeLabel(id, idField?.inferred_type);
    const keyIndex = buildDocKeyIndex(doc);
    const cells = fieldCols.map(f => {
      const sampleKey = f.sample_key;
      const resolvedSlug = sampleKey && Object.prototype.hasOwnProperty.call(doc, sampleKey)
        ? sampleKey
        : null;
      const { value: v, has } = resolvedSlug
        ? { value: doc[resolvedSlug], has: true }
        : docGetField(doc, f.slug, keyIndex);
      const inner = _renderCellHtml(v, f.inferred_type, has);
      const title = has && typeof v === 'object' ? _esc(JSON.stringify(v)) : _esc(_cellValue(v));
      return `<td title="${title}">${inner}</td>`;
    }).join('');
    return `<tr class="atlas-table-row" data-doc-id="${_esc(id)}">
      <td class="atlas-table-col-idx">${idx + 1}</td>
      <td class="atlas-table-col-id"><span class="atlas-val-id">${_esc(idType)}('${_esc(id)}')</span></td>
      ${cells}
      <td class="atlas-table-col-actions">
        <button type="button" class="atlas-table-action atlas-doc-edit" title="Edit">✎</button>
        <button type="button" class="atlas-table-action atlas-doc-copy" title="Copy">⧉</button>
        <button type="button" class="atlas-table-action atlas-doc-delete" title="Delete">✕</button>
      </td>
    </tr>`;
  }).join('');

  return `<div class="atlas-compass-table-wrap">
    <table class="atlas-compass-table">
      <thead><tr>${head}</tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

export function wireScrollDelegation(scrollEl, handlers) {
  if (!scrollEl || scrollEl.dataset.wired === '1') return;
  scrollEl.dataset.wired = '1';

  scrollEl.addEventListener('click', async (e) => {
    const chevron = e.target.closest('.atlas-compass-chevron');
    if (chevron && !chevron.classList.contains('atlas-chevron-empty')) {
      e.stopPropagation();
      const row = chevron.closest('.atlas-compass-expandable');
      const path = row?.dataset.path;
      if (!path) return;
      const children = scrollEl.querySelector(`.atlas-compass-children[data-parent="${CSS.escape(path)}"]`);
      if (!children) return;
      const collapsed = children.classList.toggle('atlas-compass-collapsed');
      row?.classList.toggle('collapsed', collapsed);
      chevron.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      chevron.textContent = collapsed ? '▸' : '▾';
      return;
    }

    const editBtn = e.target.closest('.atlas-doc-edit, .atlas-json-edit');
    if (editBtn && handlers.onEdit) {
      const docEl = editBtn.closest('[data-doc-id]');
      const docId = docEl?.dataset.docId;
      if (docId) handlers.onEdit(docId);
      return;
    }

    const copyBtn = e.target.closest('.atlas-doc-copy, .atlas-json-copy, .atlas-table-action.atlas-doc-copy');
    if (copyBtn && handlers.onCopy) {
      const docEl = copyBtn.closest('[data-doc-id]');
      const docId = docEl?.dataset.docId;
      if (docId) handlers.onCopy(docId);
      return;
    }

    const deleteBtn = e.target.closest('.atlas-doc-delete, .atlas-table-action.atlas-doc-delete');
    if (deleteBtn && handlers.onDelete) {
      const docEl = deleteBtn.closest('[data-doc-id]');
      const docId = docEl?.dataset.docId;
      if (docId) handlers.onDelete(docId);
    }
  });
}

export function expandAllChevrons(scrollEl, expand) {
  scrollEl?.querySelectorAll('.atlas-compass-children').forEach(el => {
    el.classList.toggle('atlas-compass-collapsed', !expand);
  });
  scrollEl?.querySelectorAll('.atlas-compass-expandable').forEach(row => {
    row.classList.toggle('collapsed', !expand);
    const chev = row.querySelector('.atlas-compass-chevron');
    if (chev) {
      chev.setAttribute('aria-expanded', expand ? 'true' : 'false');
      chev.textContent = expand ? '▾' : '▸';
    }
  });
}

/** @deprecated */
export function wireListViewInteractions() {}
export function wireJsonCopyButtons() {}
export function expandAllCards(scrollEl, expand) {
  expandAllChevrons(scrollEl, expand);
}
