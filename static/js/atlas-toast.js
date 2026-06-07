/**
 * Characterful Atlas toast messages.
 */
import uiModule from './ui.js';

const CHECK = { leadingIcon: 'check', duration: 1800 };

export function toastSaved() {
  uiModule.showToast('Saved. Chef\'s kiss.', CHECK);
}

export function toastBrowsing(name) {
  uiModule.showToast(`Browsing ${name}`, { duration: 1400 });
}

export function toastWorldCreated() {
  uiModule.showToast('World deployed.', CHECK);
}

export function toastWorldSwitched(name) {
  uiModule.showToast(`Switched to ${name}`, { duration: 1400 });
}

export function toastCollectionCreated() {
  uiModule.showToast('Collection created.', CHECK);
}

export function toastCollectionUpdated() {
  uiModule.showToast('Collection updated.', CHECK);
}

export function toastConnectionLocked() {
  uiModule.showToast('Connection locked in.', CHECK);
}

export function toastBackOnMap() {
  uiModule.showToast('Back on the map.', { duration: 1200 });
}

export function toastFilterMatch(n) {
  uiModule.showToast(`${n} document${n === 1 ? '' : 's'} match`, { duration: 1400 });
}

export function toastImportedCsv(inserted, failed) {
  uiModule.showToast(`Imported ${inserted} rows${failed ? ` (${failed} failed)` : ''}. Absolute unit.`, CHECK);
}

export function toastImportedJson(n) {
  uiModule.showToast(`Imported ${n} doc${n === 1 ? '' : 's'}. Big brain.`, CHECK);
}

export function toastDocumentAdded() {
  uiModule.showToast('Document added.', CHECK);
}

export function toastCsvExported() {
  uiModule.showToast('CSV exported.', CHECK);
}

export function toastRefreshed() {
  uiModule.showToast('Refreshed.', { duration: 1000 });
}

export function toastCopied() {
  uiModule.showToast('Copied.', CHECK);
}

export function toastAllLoaded() {
  uiModule.showToast('All documents loaded.', { duration: 1200 });
}

export function toastViewMode(mode) {
  const labels = { list: 'List', json: 'JSON', table: 'Table' };
  uiModule.showToast(`${labels[mode] || mode} view`, { duration: 900 });
}

export function toastWorldArchived(name) {
  uiModule.showToast(`"${name}" archived.`, CHECK);
}

export function toastWorldRestored(name) {
  uiModule.showToast(`"${name}" restored.`, CHECK);
}

export function toastWorldDeleted(name) {
  uiModule.showToast(`"${name}" deleted.`, CHECK);
}

export function toastWorldRenamed(name) {
  uiModule.showToast(`Renamed to "${name}".`, CHECK);
}

export function toastDocumentUpdated() {
  uiModule.showToast('Document updated.', CHECK);
}

export function toastDocumentDeleted() {
  uiModule.showToast('Document deleted.', CHECK);
}
