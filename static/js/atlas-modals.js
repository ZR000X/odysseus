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
