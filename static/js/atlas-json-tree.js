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

function _renderValue(v, depth) {
  const t = _type(v);
  if (t === 'object') return renderJsonTree(v, depth);
  if (t === 'array') return renderJsonTree(v, depth);
  if (t === 'string') return `<span class="atlas-json-str">"${_esc(v)}"</span>`;
  if (t === 'boolean') return `<span class="atlas-json-bool">${v}</span>`;
  if (t === 'number') return `<span class="atlas-json-num">${v}</span>`;
  return `<span class="atlas-json-null">null</span>`;
}

export function renderJsonTree(data, depth = 0) {
  if (data === null || data === undefined) {
    return `<span class="atlas-json-null">null</span>`;
  }
  if (Array.isArray(data)) {
    if (!data.length) return '<span class="atlas-json-bracket">[]</span>';
    const id = `jt-${Math.random().toString(36).slice(2, 9)}`;
    let inner = data.map((item, i) =>
      `<div class="atlas-json-line" style="padding-left:${(depth + 1) * 14}px">
        <span class="atlas-json-key">${i}</span>: ${_renderValue(item, depth + 1)}
      </div>`
    ).join('');
    return `<details class="atlas-json-node" open${depth > 2 ? '' : ''}>
      <summary class="atlas-json-summary"><span class="atlas-json-bracket">[</span><span class="atlas-json-meta">${data.length} items</span></summary>
      ${inner}<div style="padding-left:${depth * 14}px"><span class="atlas-json-bracket">]</span></div>
    </details>`;
  }
  if (typeof data === 'object') {
    const keys = Object.keys(data);
    if (!keys.length) return '<span class="atlas-json-bracket">{}</span>';
    let inner = keys.map(k =>
      `<div class="atlas-json-line" style="padding-left:${(depth + 1) * 14}px">
        <span class="atlas-json-key">"${_esc(k)}"</span>: ${_renderValue(data[k], depth + 1)}
      </div>`
    ).join('');
    return `<details class="atlas-json-node" open${depth > 1 ? '' : ''}>
      <summary class="atlas-json-summary"><span class="atlas-json-bracket">{</span><span class="atlas-json-meta">${keys.length} fields</span></summary>
      ${inner}<div style="padding-left:${depth * 14}px"><span class="atlas-json-bracket">}</span></div>
    </details>`;
  }
  return _renderValue(data, depth);
}

export function renderDocumentCard(doc) {
  const id = doc._id ?? doc._atlas_row_id ?? '?';
  const body = { ...doc };
  delete body._atlas_created_at;
  delete body._atlas_updated_at;
  return `<div class="atlas-doc-card atlas-chrome" data-doc-id="${id}">
    <div class="atlas-doc-card-header">
      <span class="atlas-doc-id">_id: ${_esc(id)}</span>
    </div>
    <div class="atlas-doc-card-body">${renderJsonTree(body)}</div>
  </div>`;
}
