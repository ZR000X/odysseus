/**
 * Atlas modal dialogs — world, entity, relationship creation.
 */
import uiModule from './ui.js';
import { makeWindowDraggable } from './windowDrag.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _modal(title, bodyHtml, onSubmit, { submitLabel = 'Create' } = {}) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    wrap.innerHTML = `
      <div class="modal-content atlas-modal-content" style="max-width:420px">
        <div class="modal-header">
          <h4>${_esc(title)}</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body">${bodyHtml}</div>
        <div class="modal-footer atlas-modal-footer" style="display:flex;gap:8px;justify-content:flex-end;padding:10px 14px;border-top:1px solid var(--border)">
          <button type="button" class="admin-btn-sm atlas-modal-cancel">Cancel</button>
          <button type="button" class="admin-btn-sm atlas-modal-submit" style="background:var(--accent);color:var(--bg)">${_esc(submitLabel)}</button>
        </div>
      </div>`;
    const close = (val) => { wrap.remove(); resolve(val); };
    wrap.querySelector('.atlas-modal-close')?.addEventListener('click', () => close(null));
    wrap.querySelector('.atlas-modal-cancel')?.addEventListener('click', () => close(null));
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(null); });
    wrap.querySelector('.atlas-modal-submit')?.addEventListener('click', async () => {
      try {
        const val = await onSubmit(wrap);
        if (val !== false) close(val);
      } catch (err) {
        uiModule.showError(err.message || String(err));
      }
    });
    document.body.appendChild(wrap);
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

export function promptRelationship(entities, fromId = '', toId = '', anchors = {}) {
  const fromAnchor = anchors.from_anchor || 'e';
  const toAnchor = anchors.to_anchor || 'w';
  const opts = entities.map(e => `<option value="${_esc(e.id)}"${e.id === fromId ? ' selected' : ''}>${_esc(e.name)}</option>`).join('');
  const toOpts = entities.map(e => `<option value="${_esc(e.id)}"${e.id === toId ? ' selected' : ''}>${_esc(e.name)}</option>`).join('');
  const fromDisabled = fromId ? ' disabled' : '';
  const toDisabled = toId ? ' disabled' : '';
  return _modal(
    'New Relationship',
    `<label class="atlas-form-label">From<select class="atlas-form-input" id="atlas-rel-from"${fromDisabled}>${opts}</select></label>
     <label class="atlas-form-label">To<select class="atlas-form-input" id="atlas-rel-to"${toDisabled}>${toOpts}</select></label>
     <label class="atlas-form-label">Type<select class="atlas-form-input" id="atlas-rel-type">
       <option value="one_to_many">One to many</option>
       <option value="one_to_one">One to one</option>
       <option value="many_to_many">Many to many</option>
     </select></label>
     <label class="atlas-form-label">From field <span class="atlas-filter-hint">(optional)</span><input class="atlas-form-input" id="atlas-rel-from-field" placeholder="Inferred from data" /></label>
     <label class="atlas-form-label">To field <span class="atlas-filter-hint">(optional)</span><input class="atlas-form-input" id="atlas-rel-to-field" placeholder="Inferred from data" /></label>
     <label class="atlas-form-label">Label<input class="atlas-form-input" id="atlas-rel-label" placeholder="Optional" /></label>
     <input type="hidden" id="atlas-rel-from-anchor" value="${_esc(fromAnchor)}" />
     <input type="hidden" id="atlas-rel-to-anchor" value="${_esc(toAnchor)}" />`,
    (wrap) => ({
      from_entity_id: wrap.querySelector('#atlas-rel-from')?.value || fromId,
      to_entity_id: wrap.querySelector('#atlas-rel-to')?.value || toId,
      rel_type: wrap.querySelector('#atlas-rel-type')?.value,
      from_field: wrap.querySelector('#atlas-rel-from-field')?.value?.trim() || '',
      to_field: wrap.querySelector('#atlas-rel-to-field')?.value?.trim() || '',
      label: wrap.querySelector('#atlas-rel-label')?.value?.trim() || '',
      from_anchor: wrap.querySelector('#atlas-rel-from-anchor')?.value || fromAnchor,
      to_anchor: wrap.querySelector('#atlas-rel-to-anchor')?.value || toAnchor,
    }),
  );
}

export function promptAddDocument() {
  return _modal(
    'Add Document',
    `<label class="atlas-form-label">Document JSON<textarea class="atlas-form-input" id="atlas-doc-json" rows="8" placeholder='{"name": "Alice", "email": "a@example.com"}' style="font-family:ui-monospace,monospace;font-size:11px"></textarea></label>
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
    { submitLabel: 'Insert' },
  );
}

export function promptImportJson() {
  return _modal(
    'Import JSON',
    `<label class="atlas-form-label">JSON array<textarea class="atlas-form-input" id="atlas-import-json" rows="10" placeholder='[{"name":"Alice"},{"name":"Bob"}]' style="font-family:ui-monospace,monospace;font-size:11px"></textarea></label>
     <p class="atlas-form-hint">Paste a JSON array of objects, or choose a file below.</p>
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
      let docs;
      try { docs = JSON.parse(raw); } catch { throw new Error('Invalid JSON'); }
      if (!Array.isArray(docs)) throw new Error('JSON must be an array of objects');
      return { documents: docs };
    },
    { submitLabel: 'Import' },
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
        <div class="modal-footer atlas-modal-footer" style="display:flex;gap:8px;justify-content:flex-end;padding:10px 14px;border-top:1px solid var(--border)">
          <button type="button" class="admin-btn-sm atlas-modal-cancel">Cancel</button>
          <button type="button" class="admin-btn-sm atlas-modal-submit atlas-delete-confirm" disabled style="background:#dc2626;color:#fff">Delete</button>
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
    `<label class="atlas-form-label">Document JSON<textarea class="atlas-form-input" id="atlas-doc-json" rows="14" style="font-family:ui-monospace,monospace;font-size:11px">${_esc(raw)}</textarea></label>`,
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
    { submitLabel: 'Save' },
  );
}

export function openWorldsManager({
  fetchWorlds, activeWorldId, onSwitch, apiBase,
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
      const renameBtn = e.target.closest('.atlas-world-rename');
      const archiveBtn = e.target.closest('.atlas-world-archive');
      const restoreBtn = e.target.closest('.atlas-world-restore');
      const deleteBtn = e.target.closest('.atlas-world-delete');

      if (openBtn) {
        await onSwitch(openBtn.dataset.id, 'open');
        close();
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

    document.body.appendChild(wrap);
    const content = wrap.querySelector('.modal-content');
    const header = wrap.querySelector('.modal-header');
    if (content && header) {
      makeWindowDraggable(wrap, { content, header, skipSelector: 'button, input, select, textarea, label', enableDock: true });
    }
    loadList();
  });
}
