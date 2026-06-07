/**
 * Atlas modal dialogs — world, entity, relationship creation.
 */
import uiModule from './ui.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _modal(title, bodyHtml, onSubmit) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal atlas-modal';
    wrap.style.display = 'block';
    wrap.innerHTML = `
      <div class="modal-content atlas-modal-content" style="max-width:420px">
        <div class="modal-header">
          <h4>${_esc(title)}</h4>
          <button type="button" class="close-btn atlas-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="modal-body atlas-modal-body">${bodyHtml}</div>
        <div class="modal-footer atlas-modal-footer" style="display:flex;gap:8px;justify-content:flex-end;padding:10px 14px;border-top:1px solid var(--border)">
          <button type="button" class="admin-btn-sm atlas-modal-cancel">Cancel</button>
          <button type="button" class="admin-btn-sm atlas-modal-submit" style="background:var(--accent);color:var(--bg)">Create</button>
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

export function promptRelationship(entities, fromId = '', toId = '') {
  const opts = entities.map(e => `<option value="${_esc(e.id)}"${e.id === fromId ? ' selected' : ''}>${_esc(e.name)}</option>`).join('');
  const toOpts = entities.map(e => `<option value="${_esc(e.id)}"${e.id === toId ? ' selected' : ''}>${_esc(e.name)}</option>`).join('');
  return _modal(
    'New Relationship',
    `<label class="atlas-form-label">From<select class="atlas-form-input" id="atlas-rel-from">${opts}</select></label>
     <label class="atlas-form-label">To<select class="atlas-form-input" id="atlas-rel-to">${toOpts}</select></label>
     <label class="atlas-form-label">Type<select class="atlas-form-input" id="atlas-rel-type">
       <option value="one_to_many">One to many</option>
       <option value="one_to_one">One to one</option>
       <option value="many_to_many">Many to many</option>
     </select></label>
     <label class="atlas-form-label">From field<input class="atlas-form-input" id="atlas-rel-from-field" placeholder="id" /></label>
     <label class="atlas-form-label">To field<input class="atlas-form-input" id="atlas-rel-to-field" placeholder="customer_id" /></label>
     <label class="atlas-form-label">Label<input class="atlas-form-input" id="atlas-rel-label" placeholder="Optional" /></label>`,
    (wrap) => ({
      from_entity_id: wrap.querySelector('#atlas-rel-from')?.value,
      to_entity_id: wrap.querySelector('#atlas-rel-to')?.value,
      rel_type: wrap.querySelector('#atlas-rel-type')?.value,
      from_field: wrap.querySelector('#atlas-rel-from-field')?.value?.trim(),
      to_field: wrap.querySelector('#atlas-rel-to-field')?.value?.trim(),
      label: wrap.querySelector('#atlas-rel-label')?.value?.trim() || '',
    }),
  );
}
