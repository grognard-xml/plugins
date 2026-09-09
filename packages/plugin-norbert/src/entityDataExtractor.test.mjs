import test from 'node:test';
import assert from 'node:assert/strict';
import { extractNorbertEntityData } from './entityDataExtractor.mjs';

/**
 * Minimal, dependency-free DOM stub — just enough of the Element interface
 * (`getElementsByTagName`, `children`, `localName`, `parentElement`,
 * `getAttribute`, `textContent`) for this extractor's tree-walking logic.
 * No XML parser needed: trees are built directly.
 */
class El {
  constructor(localName, { attrs = {}, text = '', children = [] } = {}) {
    this.localName = localName;
    this._attrs = attrs;
    this._text = text;
    this.children = children;
    for (const child of children) child.parentElement = this;
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this._attrs, name) ? this._attrs[name] : null;
  }

  get textContent() {
    if (this.children.length === 0) return this._text;
    return this.children.map((child) => child.textContent).join('');
  }

  getElementsByTagName(name) {
    const out = [];
    const walk = (el) => {
      for (const child of el.children) {
        if (child.localName === name) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
}

const wrapper = (children) => new El('name', { attrs: { type: 'personWrapper' }, children });

test('extracts nationality from a bare top-level element', () => {
  const w = wrapper([new El('nationality', { text: '晉' }), new El('persName', { text: '範' })]);
  const assertions = extractNorbertEntityData({ wrapper: w });
  assert.deepEqual(
    assertions.filter((a) => a.element === 'nationality'),
    [{ element: 'nationality', value: '晉', ref: undefined }],
  );
});

test('recognizes both placeOfOrigin (Norbert) and a bare top-level placeName (canonical TEI) as origin', () => {
  const legacy = wrapper([
    new El('placeOfOrigin', { text: '陳郡' }),
    new El('persName', { text: '謝超宗' }),
  ]);
  const canonical = wrapper([
    new El('placeName', { text: '陳郡' }),
    new El('persName', { text: '謝超宗' }),
  ]);
  for (const w of [legacy, canonical]) {
    const assertions = extractNorbertEntityData({ wrapper: w });
    assert.deepEqual(
      assertions.filter((a) => a.element === 'placeName'),
      [{ element: 'placeName', value: '陳郡', ref: undefined }],
    );
  }
});

test('recognizes both officeName (Norbert) and a bare top-level roleName (canonical TEI) as office', () => {
  const legacy = wrapper([new El('officeName', { text: '刺史' }), new El('persName', { text: '範' })]);
  const canonical = wrapper([new El('roleName', { text: '刺史' }), new El('persName', { text: '範' })]);
  for (const w of [legacy, canonical]) {
    const assertions = extractNorbertEntityData({ wrapper: w });
    assert.deepEqual(
      assertions.filter((a) => a.element === 'state'),
      [{ element: 'state', value: '刺史', ref: undefined }],
    );
  }
});

test('does not mistake a nobleTitle\'s own fief/rank for the top-level origin/office', () => {
  const w = wrapper([
    new El('nobleTitle', {
      children: [new El('placeName', { text: '建安' }), new El('roleName', { text: '王' })],
    }),
    new El('persName', { text: '休仁' }),
  ]);
  const assertions = extractNorbertEntityData({ wrapper: w });
  assert.equal(assertions.filter((a) => a.element === 'placeName').length, 0);
  assert.equal(assertions.filter((a) => a.element === 'state').length, 0);
  assert.equal(assertions.filter((a) => a.element === 'nobleTitle').length, 1);
});

test('extracts a nobleTitle with nested fief, rank, and posthumous name', () => {
  const w = wrapper([
    new El('nobleTitle', {
      attrs: { ref: 'norbert:nt:1' },
      children: [
        new El('placeName', { text: '建安' }),
        new El('persName', { attrs: { type: 'posthumous' }, text: '康' }),
        new El('roleName', { text: '王' }),
      ],
    }),
    new El('persName', { text: '休仁' }),
  ]);
  const [title] = extractNorbertEntityData({ wrapper: w }).filter((a) => a.element === 'nobleTitle');
  assert.equal(title.value, '建安康王');
  assert.equal(title.ref, 'norbert:nt:1');
  assert.deepEqual(
    title.children.map((c) => [c.element, c.value]),
    [
      ['placeName', '建安'],
      ['roleName', '王'],
      ['persName', '康'],
    ],
  );
});

test('extracts every slot together from a fully populated canonical wrapper', () => {
  const w = wrapper([
    new El('nationality', { text: '宋' }),
    new El('roleName', { text: '刺史' }),
    new El('nobleTitle', {
      children: [new El('placeName', { text: '建安' }), new El('roleName', { text: '王' })],
    }),
    new El('placeName', { text: '陳郡' }),
    new El('persName', { text: '休仁' }),
  ]);
  const assertions = extractNorbertEntityData({ wrapper: w });
  assert.deepEqual(
    assertions.map((a) => a.element).sort(),
    ['nationality', 'nobleTitle', 'placeName', 'state'].sort(),
  );
});

test('returns nothing for a wrapper with no recognized slots', () => {
  const w = wrapper([new El('persName', { text: '範' })]);
  assert.deepEqual(extractNorbertEntityData({ wrapper: w }), []);
});
