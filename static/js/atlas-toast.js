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

export function toastClusterCreated() {
  uiModule.showToast('Cluster ringfenced.', CHECK);
}

export function toastClusterUpdated() {
  uiModule.showToast('Cluster updated.', CHECK);
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

export function toastImportedJson(n, failed = 0) {
  const failNote = failed ? ` (${failed} failed)` : '';
  uiModule.showToast(`Imported ${n} doc${n === 1 ? '' : 's'}${failNote}. Big brain.`, CHECK);
}

export function toastImporting(label = 'Importing…') {
  uiModule.showToast(label, { leadingIcon: 'spinner', autoHide: false });
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

export function toastDocumentsDeleted(n) {
  uiModule.showToast(`Deleted ${n} document${n === 1 ? '' : 's'}.`, CHECK);
}

export function toastWorldExported(entityCount, docCount) {
  uiModule.showToast(
    `Exported ${entityCount} collection${entityCount === 1 ? '' : 's'}, ${docCount} document${docCount === 1 ? '' : 's'}.`,
    CHECK,
  );
}

export function toastWorldImported(result) {
  const created = result?.entities_created || 0;
  const rows = (result?.rows_inserted || 0) + (result?.rows_updated || 0);
  uiModule.showToast(
    `World imported — ${created} new collection${created === 1 ? '' : 's'}, ${rows} row${rows === 1 ? '' : 's'} synced.`,
    CHECK,
  );
}
