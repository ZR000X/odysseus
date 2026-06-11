/**
 * Atlas SQL query editor — syntax highlight + intellisense.
 */
const SQL_KEYWORDS = [
  'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'OUTER', 'ON',
  'GROUP', 'BY', 'HAVING', 'ORDER', 'LIMIT', 'OFFSET', 'AS', 'AND', 'OR', 'NOT',
  'IN', 'IS', 'NULL', 'LIKE', 'BETWEEN', 'DISTINCT', 'UNION', 'ALL',
];
const SQL_FUNCTIONS = [
  'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'COALESCE', 'CAST', 'CONCAT', 'LOWER', 'UPPER',
];

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const _TABLE_REF = String.raw`(?:\$\("(?:[^"\\]|\\.)*"\)|` + '`[^`]+`|"[^"]+"|[\\w]+)';

function _parseTableRef(raw) {
  const macro = raw.match(/^\$\("((?:[^"\\]|\\.)*)"\)$/);
  if (macro) return macro[1].replace(/\\"/g, '"');
  return raw.replace(/^[`"]|[`"]$/g, '');
}

function _macroRef(name) {
  const escaped = String(name).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  return `$("${escaped}")`;
}

function _scanAliases(sql) {
  const aliases = {};
  const re = new RegExp(String.raw`\b(?:FROM|JOIN)\s+(${_TABLE_REF})(?:\s+(?:AS\s+)?([\w]+))?`, 'gi');
  let m;
  while ((m = re.exec(sql)) !== null) {
    const table = _parseTableRef(m[1]);
    const alias = (m[2] || table).replace(/[`"]/g, '');
    aliases[alias.toLowerCase()] = table;
  }
  return aliases;
}

function _caretCoords(textarea, pos) {
  const style = getComputedStyle(textarea);
  const mirror = document.createElement('div');
  const mirrorProps = [
    'boxSizing', 'fontFamily', 'fontSize', 'fontWeight', 'fontStyle',
    'letterSpacing', 'textTransform', 'wordSpacing', 'textIndent', 'tabSize',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
    'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'lineHeight',
  ];
  for (const prop of mirrorProps) mirror.style[prop] = style[prop];
  mirror.style.position = 'absolute';
  mirror.style.visibility = 'hidden';
  mirror.style.top = '0';
  mirror.style.left = '-9999px';
  mirror.style.whiteSpace = 'pre-wrap';
  mirror.style.wordWrap = 'break-word';
  mirror.style.overflowWrap = 'break-word';
  mirror.style.overflow = 'hidden';
  mirror.style.width = `${textarea.clientWidth}px`;

  mirror.textContent = textarea.value.substring(0, pos);
  const marker = document.createElement('span');
  marker.textContent = textarea.value.substring(pos, pos + 1) || '\u200b';
  mirror.appendChild(marker);

  document.body.appendChild(mirror);
  const markerRect = marker.getBoundingClientRect();
  const mirrorRect = mirror.getBoundingClientRect();
  document.body.removeChild(mirror);

  const taRect = textarea.getBoundingClientRect();
  return {
    top: taRect.top + (markerRect.top - mirrorRect.top) - textarea.scrollTop,
    left: taRect.left + (markerRect.left - mirrorRect.left) - textarea.scrollLeft,
  };
}

function _contextAt(sql, pos) {
  const before = sql.slice(0, pos);
  const macroMatch = before.match(/\$\("((?:[^"\\]|\\.)*)$/);
  if (macroMatch) {
    return { kind: 'macro', prefix: macroMatch[1].replace(/\\"/g, '"') };
  }
  if (/\$\(\s*$/.test(before)) {
    return { kind: 'macro', prefix: '' };
  }
  const dotMatch = before.match(/([\w]+)\.\s*[`"\w]*$/);
  if (dotMatch) {
    return { kind: 'field', alias: dotMatch[1].toLowerCase() };
  }
  const fromMatch = before.match(new RegExp(String.raw`\b(?:FROM|JOIN)\s+(${_TABLE_REF}*)$`, 'i'));
  if (fromMatch) {
    return { kind: 'table', prefix: _parseTableRef(fromMatch[1] || '') };
  }
  const wordMatch = before.match(/([`"\w]+)$/);
  if (wordMatch) return { kind: 'word', prefix: wordMatch[1] };
  return { kind: 'general' };
}

export function mountSqlEditor(container, { catalog, initialSql = '', onChange, onValidate }) {
  const wrap = document.createElement('div');
  wrap.className = 'atlas-sql-editor';
  wrap.innerHTML = `
    <div class="atlas-sql-split">
      <div class="atlas-sql-preview-pane">
        <div class="atlas-sql-pane-title">Preview</div>
        <div class="atlas-sql-preview-table" id="atlas-sql-preview">
          <div class="atlas-sql-preview-empty">Enter a valid SELECT to preview results</div>
        </div>
      </div>
      <div class="atlas-sql-editor-pane">
        <div class="atlas-sql-pane-title">SQL <span class="atlas-filter-hint">MySQL · Ctrl+Space</span></div>
        <div class="atlas-sql-editor-wrap">
          <textarea id="atlas-sql-textarea" class="atlas-sql-textarea" spellcheck="false" placeholder="SELECT name, email FROM Customers WHERE status = 'active'"></textarea>
          <pre id="atlas-sql-highlight" class="atlas-sql-highlight" aria-hidden="true"><code class="language-sql" id="atlas-sql-code"></code></pre>
        </div>
        <div class="atlas-sql-status" id="atlas-sql-status"></div>
      </div>
    </div>
    <div class="atlas-sql-complete-popup" id="atlas-sql-complete" hidden></div>`;
  container.appendChild(wrap);

  const textarea = wrap.querySelector('#atlas-sql-textarea');
  const codeEl = wrap.querySelector('#atlas-sql-code');
  const pre = wrap.querySelector('#atlas-sql-highlight');
  const statusEl = wrap.querySelector('#atlas-sql-status');
  const popup = wrap.querySelector('#atlas-sql-complete');
  const previewEl = wrap.querySelector('#atlas-sql-preview');
  let validateTimer = null;
  let selectedIdx = 0;
  let suggestions = [];

  textarea.value = initialSql;

  function syncHighlight() {
    /* Single-layer editor: typed text renders in the textarea directly. */
  }

  function tableByName(name) {
    const n = name.toLowerCase();
    return catalog.collections?.find(c => c.name.toLowerCase() === n)
      || catalog.queries?.find(q => q.name.toLowerCase() === n);
  }

  function getSuggestions(ctx) {
    const items = [];
    if (ctx.kind === 'field' && ctx.alias) {
      const aliases = _scanAliases(textarea.value);
      const tableName = aliases[ctx.alias];
      const src = tableByName(tableName);
      if (src?.fields) {
        for (const f of src.fields) {
          items.push({ label: f.slug, detail: f.type, kind: 'field' });
        }
      } else if (src?.columns) {
        for (const c of src.columns) {
          items.push({ label: c.name, detail: c.type || 'col', kind: 'field' });
        }
      }
    } else if (ctx.kind === 'table' || ctx.kind === 'macro') {
      const prefix = (ctx.prefix || '').toLowerCase();
      for (const c of catalog.collections || []) {
        if (!prefix || c.name.toLowerCase().startsWith(prefix)) {
          items.push({ label: c.name, detail: 'collection', kind: 'table' });
        }
      }
      for (const q of catalog.queries || []) {
        if (!prefix || q.name.toLowerCase().startsWith(prefix)) {
          items.push({ label: q.name, detail: 'query', kind: 'table' });
        }
      }
    } else {
      const prefix = (ctx.prefix || '').toUpperCase();
      for (const kw of SQL_KEYWORDS) {
        if (!prefix || kw.startsWith(prefix)) items.push({ label: kw, detail: 'keyword', kind: 'keyword' });
      }
      for (const fn of SQL_FUNCTIONS) {
        if (!prefix || fn.startsWith(prefix)) items.push({ label: fn, detail: 'function', kind: 'function' });
      }
      const aliases = _scanAliases(textarea.value);
      for (const [alias, table] of Object.entries(aliases)) {
        if (!prefix || alias.toUpperCase().startsWith(prefix)) {
          items.push({ label: alias, detail: table, kind: 'alias' });
        }
        const src = tableByName(table);
        const fields = src?.fields || src?.columns?.map(c => ({ slug: c.name, type: c.type })) || [];
        for (const f of fields) {
          const slug = f.slug || f.name;
          if (!prefix || slug.toUpperCase().startsWith(prefix)) {
            items.push({ label: slug, detail: table, kind: 'column' });
          }
        }
      }
    }
    return items.slice(0, 40);
  }

  function hidePopup() {
    popup.hidden = true;
    suggestions = [];
    selectedIdx = 0;
  }

  function _positionPopup(pos) {
    const coords = _caretCoords(textarea, pos);
    const lh = parseFloat(getComputedStyle(textarea).lineHeight) || 18;
    popup.style.top = `${coords.top + lh + 2}px`;
    popup.style.left = `${coords.left}px`;
    popup.hidden = false;
    const margin = 8;
    const rect = popup.getBoundingClientRect();
    let top = coords.top + lh + 2;
    let left = coords.left;
    if (left + rect.width > window.innerWidth - margin) {
      left = Math.max(margin, window.innerWidth - rect.width - margin);
    }
    if (top + rect.height > window.innerHeight - margin) {
      top = Math.max(margin, coords.top - rect.height - 4);
    }
    if (left < margin) left = margin;
    popup.style.top = `${top}px`;
    popup.style.left = `${left}px`;
  }

  function showPopup(items, pos) {
    if (!items.length) { hidePopup(); return; }
    suggestions = items;
    selectedIdx = 0;
    popup.innerHTML = items.map((it, i) =>
      `<div class="atlas-sql-complete-item${i === 0 ? ' selected' : ''}" data-idx="${i}">
        <span class="atlas-sql-complete-label">${_esc(it.label)}</span>
        <span class="atlas-sql-complete-detail">${_esc(it.detail || '')}</span>
      </div>`
    ).join('');
    if (popup.parentElement !== document.body) document.body.appendChild(popup);
    _positionPopup(pos);
  }

  function insertSuggestion(label) {
    const pos = textarea.selectionStart;
    const before = textarea.value.slice(0, pos);
    const after = textarea.value.slice(pos);
    const ctx = _contextAt(textarea.value, pos);
    let newBefore = before;
    if (ctx.kind === 'field') {
      newBefore = before.replace(/\.[`"\w]*$/, `.${label}`);
    } else if (ctx.kind === 'macro') {
      newBefore = before.replace(/\$\("((?:[^"\\]|\\.)*)$/, _macroRef(label));
    } else if (ctx.kind === 'table') {
      newBefore = before.replace(
        new RegExp(String.raw`${_TABLE_REF}*$`, 'i'),
        _macroRef(label),
      );
    } else if (ctx.kind === 'word' || ctx.kind === 'general') {
      newBefore = before.replace(/[`"\w]+$/, label);
    }
    textarea.value = newBefore + after;
    const newPos = newBefore.length;
    textarea.selectionStart = textarea.selectionEnd = newPos;
    syncHighlight();
    hidePopup();
    scheduleValidate();
    onChange?.(textarea.value);
  }

  function _formatPreviewCell(val) {
    if (val === null || val === undefined) return '';
    if (typeof val === 'object') return JSON.stringify(val);
    return String(val);
  }

  function _setPreviewEmpty(msg) {
    previewEl.innerHTML = `<div class="atlas-sql-preview-empty">${_esc(msg)}</div>`;
  }

  function scheduleValidate() {
    clearTimeout(validateTimer);
    validateTimer = setTimeout(async () => {
      if (!onValidate) return;
      const sql = textarea.value.trim();
      if (!sql) {
        statusEl.innerHTML = '';
        _setPreviewEmpty('Enter a valid SELECT to preview results');
        return;
      }
      statusEl.innerHTML = '<span class="atlas-sql-status-pending">Validating…</span>';
      try {
        const result = await onValidate(sql);
        if (result?.valid === false) {
          statusEl.innerHTML = `<span class="atlas-sql-status-err">${_esc(result.error || 'Invalid SQL')}</span>`;
          _setPreviewEmpty('Fix SQL errors to preview results');
          return;
        }
        const cols = (result.columns || []).map(c => c.name).join(', ');
        const deps = (result.dependencies || []).length;
        const rows = result.preview?.documents || [];
        const total = result.preview?.total ?? rows.length;
        const shown = rows.length;
        statusEl.innerHTML = `<span class="atlas-sql-status-ok">Valid · ${deps} source(s) · ${total} row${total === 1 ? '' : 's'} · columns: ${_esc(cols || '(none)')}</span>`;
        if (rows.length) {
          const keys = Object.keys(rows[0]);
          const foot = total > shown
            ? `<div class="atlas-sql-preview-foot">Showing ${shown} of ${total} rows in preview</div>`
            : `<div class="atlas-sql-preview-foot">${total} row${total === 1 ? '' : 's'}</div>`;
          previewEl.innerHTML = `<table class="atlas-sql-preview-grid"><thead><tr>${keys.map(k => `<th>${_esc(k)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${keys.map(k => `<td>${_esc(_formatPreviewCell(r[k]))}</td>`).join('')}</tr>`).join('')}</tbody></table>${foot}`;
        } else {
          _setPreviewEmpty(total > 0 ? `Query matches ${total} rows (none in preview window)` : 'Query returned no rows');
        }
      } catch (e) {
        statusEl.innerHTML = `<span class="atlas-sql-status-err">${_esc(e.message || String(e))}</span>`;
        _setPreviewEmpty('Fix SQL errors to preview results');
      }
    }, 450);
  }

  textarea.addEventListener('input', () => {
    syncHighlight();
    onChange?.(textarea.value);
    scheduleValidate();
    const pos = textarea.selectionStart;
    const ctx = _contextAt(textarea.value, pos);
    if (ctx.kind === 'field' || ctx.kind === 'table' || ctx.kind === 'macro' || ctx.kind === 'word') {
      showPopup(getSuggestions(ctx), pos);
    } else {
      hidePopup();
    }
  });

  textarea.addEventListener('scroll', () => {
    if (!popup.hidden && textarea.selectionStart != null) {
      _positionPopup(textarea.selectionStart);
    }
  });


  textarea.addEventListener('keydown', (e) => {
    if (!popup.hidden && suggestions.length) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIdx = Math.min(selectedIdx + 1, suggestions.length - 1);
        popup.querySelectorAll('.atlas-sql-complete-item').forEach((el, i) => {
          el.classList.toggle('selected', i === selectedIdx);
        });
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIdx = Math.max(selectedIdx - 1, 0);
        popup.querySelectorAll('.atlas-sql-complete-item').forEach((el, i) => {
          el.classList.toggle('selected', i === selectedIdx);
        });
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        insertSuggestion(suggestions[selectedIdx].label);
        return;
      }
      if (e.key === 'Escape') {
        hidePopup();
        return;
      }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === ' ') {
      e.preventDefault();
      const pos = textarea.selectionStart;
      showPopup(getSuggestions(_contextAt(textarea.value, pos)), pos);
    }
  });

  popup.addEventListener('mousedown', (e) => {
    const item = e.target.closest('.atlas-sql-complete-item');
    if (!item) return;
    e.preventDefault();
    insertSuggestion(suggestions[Number(item.dataset.idx)].label);
  });

  syncHighlight();
  scheduleValidate();

  return {
    getSql: () => textarea.value,
    setSql: (sql) => { textarea.value = sql; syncHighlight(); scheduleValidate(); },
    destroy: () => { hidePopup(); popup.remove(); wrap.remove(); },
  };
}
