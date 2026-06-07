/**
 * Collapsible JSON tree renderer for Atlas Compass.
 */

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _type(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  return typeof v;
}

function _valClass(v, key) {
  if (key === '_id') return 'atlas-val-id';
  const t = _type(v);
  if (t === 'string') return 'atlas-json-str';
  if (t === 'number') return 'atlas-json-num';
  if (t === 'boolean') return 'atlas-json-bool';
  if (t === 'null') return 'atlas-json-null';
  return '';
}

function _renderPrimitive(v, key) {
  const cls = _valClass(v, key);
  if (v === null) return `<span class="atlas-compass-val atlas-json-null">null</span>`;
  if (typeof v === 'string') return `<span class="atlas-compass-val ${cls}">"${_esc(v)}"</span>`;
  if (typeof v === 'boolean') return `<span class="atlas-compass-val ${cls}">${v}</span>`;
  if (typeof v === 'number') return `<span class="atlas-compass-val ${cls}">${v}</span>`;
  return `<span class="atlas-compass-val">${_esc(String(v))}</span>`;
}

function _renderFieldRows(data, depth, pathPrefix, parentExpanded) {
  if (data === null || data === undefined) {
    return `<div class="atlas-compass-field-row" style="padding-left:${depth * 14}px">
      <span class="atlas-compass-chevron atlas-chevron-empty"></span>
      <span class="atlas-compass-val atlas-json-null">null</span>
    </div>`;
  }
  if (Array.isArray(data)) {
    if (!data.length) {
      return `<div class="atlas-compass-field-row" style="padding-left:${depth * 14}px">
        <span class="atlas-compass-chevron atlas-chevron-empty"></span>
        <span class="atlas-compass-val atlas-json-bracket">[]</span>
      </div>`;
    }
    const collapsed = depth >= 1;
    const label = `[ ${data.length} elements ]`;
    let html = `<div class="atlas-compass-field-row atlas-compass-expandable${collapsed ? ' collapsed' : ''}" style="padding-left:${depth * 14}px" data-path="${_esc(pathPrefix)}">
      <button type="button" class="atlas-compass-chevron" aria-expanded="${!collapsed}">${collapsed ? '▸' : '▾'}</button>
      <span class="atlas-compass-val atlas-json-bracket">${label}</span>
    </div>`;
    html += `<div class="atlas-compass-children${collapsed ? ' atlas-compass-collapsed' : ''}" data-parent="${_esc(pathPrefix)}">`;
    data.forEach((item, i) => {
      const p = `${pathPrefix}[${i}]`;
      if (_type(item) === 'object' || _type(item) === 'array') {
        html += `<div class="atlas-compass-field-row" style="padding-left:${(depth + 1) * 14}px">
          <span class="atlas-compass-key">${i}</span><span class="atlas-compass-colon">:</span>
        </div>`;
        html += _renderFieldRows(item, depth + 2, p, !collapsed);
      } else {
        html += `<div class="atlas-compass-field-row" style="padding-left:${(depth + 1) * 14}px">
          <span class="atlas-compass-chevron atlas-chevron-empty"></span>
          <span class="atlas-compass-key">${i}</span><span class="atlas-compass-colon">:</span>
          ${_renderPrimitive(item, String(i))}
        </div>`;
      }
    });
    html += '</div>';
    return html;
  }
  if (typeof data === 'object') {
    const keys = Object.keys(data);
    if (!keys.length) {
      return `<div class="atlas-compass-field-row" style="padding-left:${depth * 14}px">
        <span class="atlas-compass-chevron atlas-chevron-empty"></span>
        <span class="atlas-compass-val atlas-json-bracket">{}</span>
      </div>`;
    }
    let html = '';
    keys.forEach(k => {
      const v = data[k];
      const p = pathPrefix ? `${pathPrefix}.${k}` : k;
      const t = _type(v);
      if (t === 'object' || t === 'array') {
        const collapsed = depth >= 1;
        const count = Array.isArray(v) ? v.length : Object.keys(v).length;
        const bracket = Array.isArray(v) ? `[ ${count} elements ]` : `{ ${count} fields }`;
        html += `<div class="atlas-compass-field-row atlas-compass-expandable${collapsed ? ' collapsed' : ''}" style="padding-left:${depth * 14}px" data-path="${_esc(p)}">
          <button type="button" class="atlas-compass-chevron" aria-expanded="${!collapsed}">${collapsed ? '▸' : '▾'}</button>
          <span class="atlas-compass-key">"${_esc(k)}"</span><span class="atlas-compass-colon">:</span>
          <span class="atlas-compass-val atlas-json-bracket">${bracket}</span>
        </div>`;
        html += `<div class="atlas-compass-children${collapsed ? ' atlas-compass-collapsed' : ''}" data-parent="${_esc(p)}">`;
        html += _renderFieldRows(v, depth + 1, p, !collapsed);
        html += '</div>';
      } else {
        html += `<div class="atlas-compass-field-row" style="padding-left:${depth * 14}px">
          <span class="atlas-compass-chevron atlas-chevron-empty"></span>
          <span class="atlas-compass-key">"${_esc(k)}"</span><span class="atlas-compass-colon">:</span>
          ${_renderPrimitive(v, k)}
        </div>`;
      }
    });
    return html;
  }
  return `<div class="atlas-compass-field-row" style="padding-left:${depth * 14}px">${_renderPrimitive(data, '')}</div>`;
}

export function renderCompassDocument(doc) {
  const id = doc._id ?? doc._atlas_row_id ?? '?';
  const body = { ...doc };
  delete body._atlas_created_at;
  delete body._atlas_updated_at;
  return `<div class="atlas-compass-doc" data-doc-id="${_esc(id)}">
    <div class="atlas-compass-doc-toolbar">
      <button type="button" class="atlas-doc-action atlas-doc-edit" title="Edit document">✎</button>
      <button type="button" class="atlas-doc-action atlas-doc-copy" title="Copy JSON">⧉</button>
      <button type="button" class="atlas-doc-action atlas-doc-delete" title="Delete document">✕</button>
    </div>
    <div class="atlas-compass-doc-body">${_renderFieldRows(body, 0, '', true)}</div>
  </div>`;
}

export function docSummaryLine(doc) {
  const body = { ...doc };
  delete body._id;
  delete body._atlas_row_id;
  delete body._atlas_created_at;
  delete body._atlas_updated_at;
  const keys = Object.keys(body);
  if (!keys.length) return '{}';
  const parts = keys.slice(0, 3).map(k => {
    let v = body[k];
    if (typeof v === 'object') v = Array.isArray(v) ? `[${v.length}]` : '{…}';
    else if (typeof v === 'string' && v.length > 20) v = `${v.slice(0, 17)}…`;
    return `${k}: ${JSON.stringify(v)}`.replace(/^"|"$/g, '');
  });
  const extra = keys.length > 3 ? ` … +${keys.length - 3} fields` : '';
  return `{${parts.join(', ')}${extra}}`;
}

export function highlightJson(raw) {
  return _esc(raw)
    .replace(/"([^"\\]|\\.)*"(?=\s*:)/g, m => `<span class="atlas-json-key">${m}</span>`)
    .replace(/: "([^"\\]|\\.)*"/g, m => `: <span class="atlas-json-str">${m.slice(2)}</span>`)
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="atlas-json-num">$1</span>')
    .replace(/: (true|false)/g, ': <span class="atlas-json-bool">$1</span>')
    .replace(/: (null)/g, ': <span class="atlas-json-null">$1</span>');
}

/** @deprecated use renderCompassDocument */
export function renderDocumentCard(doc) {
  return renderCompassDocument(doc);
}

/** Legacy json tree for compatibility */
export function renderJsonTree(data, depth = 0) {
  return _renderFieldRows(data, depth, '', true);
}
