/**
 * Click-to-edit inline fields for Atlas Compass entity header.
 */
import uiModule from './ui.js';
import { toastSaved } from './atlas-toast.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function wireInlineField(el, {
  multiline = false,
  placeholder = '',
  getValue,
  onSave,
}) {
  if (!el) return;

  const showDisplay = (text) => {
    el.classList.remove('atlas-inline-editing');
    const empty = !text?.trim();
    if (empty && placeholder) {
      el.classList.add('atlas-inline-empty');
      el.textContent = placeholder;
    } else {
      el.classList.remove('atlas-inline-empty');
      el.textContent = text || '';
    }
  };

  showDisplay(getValue());

  el.addEventListener('click', () => {
    if (el.dataset.editing === '1') return;
    el.dataset.editing = '1';
    el.classList.add('atlas-inline-editing');
    el.classList.remove('atlas-inline-empty');
    const cur = getValue();
    const input = document.createElement(multiline ? 'textarea' : 'input');
    input.className = 'atlas-inline-input';
    if (multiline) input.rows = 2;
    else input.type = 'text';
    input.value = cur;
    el.textContent = '';
    el.appendChild(input);
    input.focus();
    input.select?.();

    const finish = async (save) => {
      if (el.dataset.editing !== '1') return;
      el.dataset.editing = '0';
      input.remove();
      if (save) {
        const next = input.value.trim();
        if (multiline || next) {
          try {
            await onSave(next);
            showDisplay(next);
            el.classList.add('atlas-inline-saved');
            setTimeout(() => el.classList.remove('atlas-inline-saved'), 600);
            toastSaved();
          } catch (err) {
            uiModule.showError(err.message || String(err));
            showDisplay(getValue());
          }
          return;
        }
      }
      showDisplay(getValue());
    };

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        finish(false);
      }
      if (!multiline && e.key === 'Enter') {
        e.preventDefault();
        finish(true);
      }
    });
    input.addEventListener('blur', () => finish(true));
  });
}

export { _esc as escInline };
