/**
 * Atlas whole-world Excel import/export wizard.
 */
import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';

const API_BASE = window.location.origin;

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function _confidenceBadge(c) {
  const map = {
    exact: ['atlas-map-badge-exact', 'Exact match'],
    fuzzy: ['atlas-map-badge-fuzzy', 'Fuzzy match'],
    meta: ['atlas-map-badge-meta', 'From export'],
    new: ['atlas-map-badge-new', 'New collection'],
  };
  const [cls, label] = map[c] || map.new;
  return `<span class="atlas-map-badge ${cls}">${label}</span>`;
}

export async function exportWorldExcel(worldId, worldName) {
  const res = await fetch(`${API_BASE}/api/atlas/worlds/${worldId}/export.xlsx`, {
    credentials: 'same-origin',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || res.statusText);
  }
  const blob = await res.blob();
  const entCount = res.headers.get('X-Atlas-Entity-Count') || '?';
  const docCount = res.headers.get('X-Atlas-Document-Count') || '?';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${(worldName || 'world').replace(/\s+/g, '_')}.xlsx`;
  a.click();
  URL.revokeObjectURL(a.href);
  return { entity_count: entCount, document_count: docCount };
}

async function _analyzeFile(file, worldId) {
  const fd = new FormData();
  fd.append('file', file);
  const url = worldId
    ? `${API_BASE}/api/atlas/worlds/${worldId}/import/analyze`
    : `${API_BASE}/api/atlas/worlds/import/analyze`;
  const res = await fetch(url, { method: 'POST', credentials: 'same-origin', body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || res.statusText);
  }
  return res.json();
}

async function _executeImport(file, worldId, metadata) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('metadata', JSON.stringify(metadata));
  const url = worldId
    ? `${API_BASE}/api/atlas/worlds/${worldId}/import`
    : `${API_BASE}/api/atlas/worlds/import`;
  const res = await fetch(url, { method: 'POST', credentials: 'same-origin', body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || res.statusText);
  }
  return res.json();
}

function _buildMappingRow(sheet, entities, idx) {
  const action = sheet.suggested_action === 'import_to_existing' ? 'import_to_existing' : 'create_new';
  const entityOpts = entities.map(e =>
    `<option value="${_esc(e.id)}"${e.id === sheet.suggested_entity_id ? ' selected' : ''}>${_esc(e.name)}</option>`
  ).join('');
  return `<tr class="atlas-map-row" data-idx="${idx}">
    <td>${_esc(sheet.sheet_name)}</td>
    <td>${sheet.row_count}</td>
    <td>${_confidenceBadge(sheet.match_confidence)}</td>
    <td>
      <select class="atlas-form-input atlas-map-action">
        <option value="import_to_existing"${action === 'import_to_existing' ? ' selected' : ''}>Import to existing</option>
        <option value="create_new"${action === 'create_new' ? ' selected' : ''}>Create new</option>
        <option value="skip">Skip</option>
      </select>
    </td>
    <td>
      <select class="atlas-form-input atlas-map-entity"${action !== 'import_to_existing' ? ' disabled' : ''}>
        <option value="">—</option>${entityOpts}
      </select>
      <input type="text" class="atlas-form-input atlas-map-name" value="${_esc(sheet.suggested_entity_name || sheet.sheet_name)}"${action === 'import_to_existing' ? ' hidden' : ''} />
    </td>
    <td>
      <select class="atlas-form-input atlas-map-mode">
        <option value="append">Append</option>
        <option value="merge">Merge</option>
        <option value="replace">Replace</option>
      </select>
    </td>
  </tr>`;
}

export function openWorldExcelImportWizard({
  worldId = null,
  entities = [],
  onComplete,
}) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    let step = 1;
    let file = null;
    let analysis = null;

    const close = (result = null) => {
      wrap.remove();
      resolve(result);
      if (result && onComplete) onComplete(result);
    };

    function render() {
      const body = wrap.querySelector('.atlas-excel-body');
      if (!body) return;

      if (step === 1) {
        body.innerHTML = `
          <div class="atlas-excel-steps"><span class="active">1 Upload</span><span>2 Map</span><span>3 Done</span></div>
          <div class="atlas-excel-drop atlas-chrome" id="atlas-excel-drop">
            <p>Drop an Excel workbook here, or click to browse</p>
            <p class="atlas-excel-hint">.xlsx · one sheet per collection · optional hidden _Atlas meta sheet</p>
            <input type="file" id="atlas-excel-file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden />
          </div>
          <div id="atlas-excel-file-info" class="atlas-excel-file-info" hidden></div>
          ${worldId ? '' : `<label class="atlas-form-label" style="margin-top:12px">New world name (optional)
            <input type="text" class="atlas-form-input" id="atlas-excel-world-name" placeholder="From file meta or sheet names" /></label>`}`;
        const drop = body.querySelector('#atlas-excel-drop');
        const input = body.querySelector('#atlas-excel-file');
        drop?.addEventListener('click', () => input?.click());
        drop?.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('atlas-excel-drop-hover'); });
        drop?.addEventListener('dragleave', () => drop.classList.remove('atlas-excel-drop-hover'));
        drop?.addEventListener('drop', (e) => {
          e.preventDefault();
          drop.classList.remove('atlas-excel-drop-hover');
          const f = e.dataTransfer?.files?.[0];
          if (f) _setFile(f);
        });
        input?.addEventListener('change', () => {
          const f = input.files?.[0];
          if (f) _setFile(f);
        });
      } else if (step === 2 && analysis) {
        const sheets = analysis.sheets || [];
        body.innerHTML = `
          <div class="atlas-excel-steps"><span>1 Upload</span><span class="active">2 Map</span><span>3 Done</span></div>
          ${analysis.world_hint ? `<div class="atlas-excel-meta atlas-chrome">From file: <strong>${_esc(analysis.world_hint.world_name || '')}</strong> · ${analysis.world_hint.entity_count || 0} collections · ${analysis.world_hint.relationship_count || 0} relationships</div>` : ''}
          <div class="atlas-excel-map-wrap">
            <table class="atlas-excel-map-table">
              <thead><tr>
                <th>Sheet</th><th>Rows</th><th>Match</th><th>Action</th><th>Target</th><th>Mode</th>
              </tr></thead>
              <tbody>${sheets.map((s, i) => _buildMappingRow(s, entities, i)).join('')}</tbody>
            </table>
          </div>
          <label class="atlas-form-label" style="margin-top:10px">
            <input type="checkbox" id="atlas-excel-restore-meta" checked /> Restore relationships & canvas layout from _Atlas meta sheet
          </label>`;
        body.querySelectorAll('.atlas-map-action').forEach(sel => {
          sel.addEventListener('change', () => {
            const row = sel.closest('.atlas-map-row');
            const entSel = row?.querySelector('.atlas-map-entity');
            const nameIn = row?.querySelector('.atlas-map-name');
            const isExisting = sel.value === 'import_to_existing';
            if (entSel) entSel.disabled = !isExisting;
            if (nameIn) nameIn.hidden = isExisting;
          });
        });
      } else if (step === 3) {
        body.innerHTML = `
          <div class="atlas-excel-steps"><span>1 Upload</span><span>2 Map</span><span class="active">3 Done</span></div>
          <div class="atlas-excel-progress atlas-chrome"><div class="atlas-excel-progress-bar" id="atlas-excel-bar"></div></div>
          <div id="atlas-excel-result" class="atlas-excel-result">Importing…</div>`;
      }
      _updateFooter();
    }

    function _setFile(f) {
      file = f;
      const info = wrap.querySelector('#atlas-excel-file-info');
      if (info) {
        info.hidden = false;
        info.textContent = `${f.name} · ${_fmtSize(f.size)}`;
      }
      _updateFooter();
    }

    function _updateFooter() {
      const next = wrap.querySelector('#atlas-excel-next');
      const back = wrap.querySelector('#atlas-excel-back');
      if (!next || !back) return;
      back.hidden = step === 1;
      if (step === 1) {
        next.textContent = 'Analyze mappings';
        next.disabled = !file;
      } else if (step === 2) {
        next.textContent = 'Import world';
        next.disabled = false;
      } else {
        next.hidden = true;
        back.hidden = true;
      }
    }

    async function _goNext() {
      const nextBtn = wrap.querySelector('#atlas-excel-next');
      if (step === 1) {
        if (!file) return;
        if (nextBtn) nextBtn.disabled = true;
        try {
          analysis = await _analyzeFile(file, worldId);
          step = 2;
          render();
        } catch (e) {
          uiModule.showError(e.message);
        } finally {
          if (nextBtn) nextBtn.disabled = false;
        }
      } else if (step === 2) {
        const rows = wrap.querySelectorAll('.atlas-map-row');
        const mappings = [...rows].map(row => {
          const idx = Number(row.dataset.idx);
          const sheet = analysis.sheets[idx];
          const action = row.querySelector('.atlas-map-action')?.value || 'skip';
          return {
            sheet_name: sheet.sheet_name,
            action,
            entity_id: row.querySelector('.atlas-map-entity')?.value || null,
            entity_name: row.querySelector('.atlas-map-name')?.value?.trim() || sheet.sheet_name,
            mode: row.querySelector('.atlas-map-mode')?.value || 'append',
          };
        });
        const metadata = {
          mappings,
          default_mode: 'append',
          restore_meta: wrap.querySelector('#atlas-excel-restore-meta')?.checked !== false,
          world_name: wrap.querySelector('#atlas-excel-world-name')?.value?.trim() || analysis.world_hint?.world_name || null,
        };
        step = 3;
        render();
        const bar = wrap.querySelector('#atlas-excel-bar');
        const resultEl = wrap.querySelector('#atlas-excel-result');
        if (bar) bar.style.width = '35%';
        try {
          if (bar) bar.style.width = '70%';
          const result = await _executeImport(file, worldId, metadata);
          if (bar) bar.style.width = '100%';
          if (resultEl) {
            resultEl.innerHTML = `<div class="atlas-excel-summary atlas-chrome">
              <p><strong>Import complete</strong></p>
              <ul>
                <li>${result.entities_created || 0} collections created</li>
                <li>${result.rows_inserted || 0} rows inserted · ${result.rows_updated || 0} updated</li>
                <li>${result.relationships_restored || 0} relationships restored</li>
                ${result.rows_failed ? `<li>${result.rows_failed} rows failed</li>` : ''}
              </ul>
              ${result.errors?.length ? `<details><summary>${result.errors.length} warnings</summary><pre>${_esc(JSON.stringify(result.errors, null, 2))}</pre></details>` : ''}
            </div>`;
          }
          const doneBtn = document.createElement('button');
          doneBtn.type = 'button';
          doneBtn.className = 'admin-btn-sm atlas-btn-press';
          doneBtn.textContent = 'Done';
          doneBtn.style.marginTop = '12px';
          doneBtn.addEventListener('click', () => close(result));
          resultEl?.appendChild(doneBtn);
        } catch (e) {
          if (resultEl) resultEl.innerHTML = `<div class="atlas-empty">${_esc(e.message)}</div>`;
          uiModule.showError(e.message);
        }
      }
    }

    wrap.innerHTML = `
      <div class="modal-content atlas-modal-content atlas-excel-modal" style="max-width:720px">
        <div class="modal-header">
          <h4>Import world from Excel</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body atlas-excel-body"></div>
        <div class="modal-footer atlas-excel-footer" style="display:flex;gap:8px;justify-content:flex-end;padding:12px">
          <button type="button" class="admin-btn-sm" id="atlas-excel-back">Back</button>
          <button type="button" class="admin-btn-sm atlas-btn-press" id="atlas-excel-next">Analyze mappings</button>
        </div>
      </div>`;

    const next = wrap.querySelector('#atlas-excel-next');
    const back = wrap.querySelector('#atlas-excel-back');
    wrap.querySelector('.atlas-modal-close')?.addEventListener('click', () => close(null));
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(null); });
    next?.addEventListener('click', () => _goNext());
    back?.addEventListener('click', () => {
      if (step === 2) { step = 1; render(); }
    });

    document.body.appendChild(wrap);
    const content = wrap.querySelector('.modal-content');
    const header = wrap.querySelector('.modal-header');
    if (content && header) makeWindowDraggable(content, header);
    render();
  });
}
