/**
 * Atlas relationship cardinality — shared parse, visuals, and ER markers.
 */

export const CARDINALITY_OPTIONS = [
  ['one', 'One'],
  ['many', 'Many'],
  ['one_or_zero', 'Zero or one'],
];

const LEGACY_REL_TO_CARDINALITIES = {
  one_to_one: ['one', 'one'],
  one_to_many: ['one', 'many'],
  many_to_one: ['many', 'one'],
  many_to_many: ['many', 'many'],
};

const SVG_NS = 'http://www.w3.org/2000/svg';

function _normalizeCardinality(val) {
  const c = String(val || '').toLowerCase().replace(/-/g, '_');
  if (c === 'one' || c === 'many' || c === 'one_or_zero') return c;
  return null;
}

function _cardinalitiesFromRelType(relType) {
  const t = (relType || 'one_to_many').toLowerCase().replace(/-/g, '_');
  if (LEGACY_REL_TO_CARDINALITIES[t]) {
    return { from: LEGACY_REL_TO_CARDINALITIES[t][0], to: LEGACY_REL_TO_CARDINALITIES[t][1] };
  }
  if (t.includes('_to_')) {
    const [fromPart, toPart] = t.split('_to_', 2);
    const from = _normalizeCardinality(fromPart);
    const to = _normalizeCardinality(toPart);
    if (from && to) return { from, to };
  }
  return { from: 'one', to: 'many' };
}

export function composeRelType(fromC, toC) {
  const from = _normalizeCardinality(fromC) || 'one';
  const to = _normalizeCardinality(toC) || 'many';
  return `${from}_to_${to}`;
}

/** @param {{ from_cardinality?: string, to_cardinality?: string, rel_type?: string }} rel */
export function parseCardinalities(rel) {
  if (rel?.from_cardinality && rel?.to_cardinality) {
    return {
      from: _normalizeCardinality(rel.from_cardinality) || 'one',
      to: _normalizeCardinality(rel.to_cardinality) || 'many',
    };
  }
  return _cardinalitiesFromRelType(rel?.rel_type);
}

export function cardinalityOptionsHtml(selected, side) {
  const id = side === 'from' ? 'atlas-rel-from-cardinality' : 'atlas-rel-to-cardinality';
  const opts = CARDINALITY_OPTIONS.map(([val, label]) =>
    `<option value="${val}"${val === selected ? ' selected' : ''}>${label}</option>`
  ).join('');
  return `<select class="atlas-rel-cardinality-select atlas-form-input" id="${id}" aria-label="${side === 'from' ? 'From' : 'To'} cardinality">${opts}</select>`;
}

/** For flow/color only: zero-or-one behaves like one (except pure 1↔0..1 pairs). */
function _visualCardinality(c) {
  return c === 'one_or_zero' ? 'one' : c;
}

function _isOneToOptional(fromC, toC) {
  return (fromC === 'one' && toC === 'one_or_zero')
    || (fromC === 'one_or_zero' && toC === 'one');
}

export function edgeVisuals(fromC, toC) {
  const from = _normalizeCardinality(fromC) || 'one';
  const to = _normalizeCardinality(toC) || 'many';
  const fromV = _visualCardinality(from);
  const toV = _visualCardinality(to);
  const root = getComputedStyle(document.documentElement);
  const fg = root.getPropertyValue('--fg').trim() || '#cbd5e1';
  const accent = root.getPropertyValue('--accent').trim()
    || root.getPropertyValue('--color-accent').trim()
    || '#00aaff';
  if (from === 'one' && to === 'one') {
    return { color: accent, bidirectional: true, flowMode: 'one_one' };
  }
  if (from === 'one_or_zero' && to === 'one_or_zero') {
    return { color: accent, bidirectional: true, flowMode: 'one_one' };
  }
  if (_isOneToOptional(from, to)) {
    const flowDirection = from === 'one' && to === 'one_or_zero' ? 'forward' : 'reverse';
    return { color: accent, bidirectional: false, flowMode: 'directed', flowDirection };
  }
  if (fromV === 'many' && toV === 'many') {
    return { color: '#f0abfc', bidirectional: true, flowMode: 'many_many' };
  }
  const flowDirection = fromV === 'many' && toV === 'one' ? 'reverse' : 'forward';
  return { color: fg, bidirectional: false, flowMode: 'directed', flowDirection };
}

export function cardinalityMarkerHtml(cardinality, end) {
  const facing = end === 'from' ? 'atlas-rel-marker-out' : 'atlas-rel-marker-in';
  if (cardinality === 'one') {
    return `<div class="atlas-rel-marker atlas-rel-marker-one ${facing}" aria-hidden="true"></div>`;
  }
  if (cardinality === 'one_or_zero') {
    return `<div class="atlas-rel-marker atlas-rel-marker-one_or_zero ${facing}" aria-hidden="true"><span class="atlas-rel-marker-bar"></span></div>`;
  }
  return `<div class="atlas-rel-marker atlas-rel-marker-many ${facing}" aria-hidden="true"><span class="atlas-rel-marker-stem"></span></div>`;
}

export function updateCardinalityMarkerPlacement(g, cardinality, x, y, angle, color) {
  if (!g.childNodes.length) {
    renderCardinalityMarker(g, cardinality, x, y, angle, color);
    return;
  }
  const strokeW = 1.75;
  if (cardinality === 'one') {
    const perp = angle + Math.PI / 2;
    const len = 5;
    const line = g.querySelector('.atlas-edge-marker-line');
    if (line) {
      line.setAttribute('x1', x - Math.cos(perp) * len);
      line.setAttribute('y1', y - Math.sin(perp) * len);
      line.setAttribute('x2', x + Math.cos(perp) * len);
      line.setAttribute('y2', y + Math.sin(perp) * len);
      line.setAttribute('stroke', color);
    }
    return;
  }
  if (cardinality === 'one_or_zero') {
    const perp = angle + Math.PI / 2;
    const barLen = 5;
    const line = g.querySelector('.atlas-edge-marker-line');
    if (line) {
      line.setAttribute('x1', x - Math.cos(perp) * barLen);
      line.setAttribute('y1', y - Math.sin(perp) * barLen);
      line.setAttribute('x2', x + Math.cos(perp) * barLen);
      line.setAttribute('y2', y + Math.sin(perp) * barLen);
      line.setAttribute('stroke', color);
    }
    const circleOffset = 7;
    const circle = g.querySelector('.atlas-edge-marker-circle');
    if (circle) {
      circle.setAttribute('cx', x + Math.cos(angle) * circleOffset);
      circle.setAttribute('cy', y + Math.sin(angle) * circleOffset);
      circle.setAttribute('stroke', color);
    }
    return;
  }
  const len = 7;
  const spread = 0.48;
  const footAngle = angle + Math.PI;
  const angles = [footAngle, footAngle - spread, footAngle + spread];
  g.querySelectorAll('.atlas-edge-marker-line').forEach((line, i) => {
    const a = angles[i];
    if (a === undefined) return;
    line.setAttribute('x1', x);
    line.setAttribute('y1', y);
    line.setAttribute('x2', x + Math.cos(a) * len);
    line.setAttribute('y2', y + Math.sin(a) * len);
    line.setAttribute('stroke', color);
  });
}

export function renderCardinalityMarker(g, cardinality, x, y, angle, color) {
  g.innerHTML = '';
  const strokeW = 1.75;
  if (cardinality === 'one') {
    const perp = angle + Math.PI / 2;
    const len = 5;
    const line = document.createElementNS(SVG_NS, 'line');
    line.classList.add('atlas-edge-marker-line');
    line.setAttribute('x1', x - Math.cos(perp) * len);
    line.setAttribute('y1', y - Math.sin(perp) * len);
    line.setAttribute('x2', x + Math.cos(perp) * len);
    line.setAttribute('y2', y + Math.sin(perp) * len);
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', strokeW);
    g.appendChild(line);
    return;
  }
  if (cardinality === 'one_or_zero') {
    const perp = angle + Math.PI / 2;
    const barLen = 5;
    const line = document.createElementNS(SVG_NS, 'line');
    line.classList.add('atlas-edge-marker-line');
    line.setAttribute('x1', x - Math.cos(perp) * barLen);
    line.setAttribute('y1', y - Math.sin(perp) * barLen);
    line.setAttribute('x2', x + Math.cos(perp) * barLen);
    line.setAttribute('y2', y + Math.sin(perp) * barLen);
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', strokeW);
    g.appendChild(line);
    const circleOffset = 7;
    const cx = x + Math.cos(angle) * circleOffset;
    const cy = y + Math.sin(angle) * circleOffset;
    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.classList.add('atlas-edge-marker-circle');
    circle.setAttribute('cx', cx);
    circle.setAttribute('cy', cy);
    circle.setAttribute('r', '3');
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', color);
    circle.setAttribute('stroke-width', strokeW);
    g.appendChild(circle);
    return;
  }
  const len = 7;
  const spread = 0.48;
  const footAngle = angle + Math.PI;
  for (const a of [footAngle, footAngle - spread, footAngle + spread]) {
    const line = document.createElementNS(SVG_NS, 'line');
    line.classList.add('atlas-edge-marker-line');
    line.setAttribute('x1', x);
    line.setAttribute('y1', y);
    line.setAttribute('x2', x + Math.cos(a) * len);
    line.setAttribute('y2', y + Math.sin(a) * len);
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', strokeW);
    g.appendChild(line);
  }
}
