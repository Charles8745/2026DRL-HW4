import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  slugify, upgradeHttp, INLINE_SVG_PLACEHOLDER, resolveListingImage, attachFallback,
} from '../components/imageResolver.js';

// 33 real catalog rows: [title, expectedSlug] (from de/data/catalog.py load_catalog())
const ROWS = [
  ['YZF-R9', 'yzf-r9'], ['YZF-R3', 'yzf-r3'], ['MT-09 Y-AMT', 'mt-09-y-amt'],
  ['MT-07 Y-AMT', 'mt-07-y-amt'], ['MT-07', 'mt-07'], ['MT-15', 'mt-15'],
  ['Ténéré 700', 'tenere-700'], ['TMAX', 'tmax'], ['XMAX', 'xmax'],
  ['Ninja ZX-4RR (ZX400-S)', 'ninja-zx-4rr-zx400-s'],
  ['Ninja ZX-6R (ZX636-J)', 'ninja-zx-6r-zx636-j'],
  ['Ninja ZX-10R (ZX-1002L)', 'ninja-zx-10r-zx-1002l'],
  ['Ninja 500 SE (EX500-J)', 'ninja-500-se-ex500-j'],
  ['Ninja 500 (EX500-G)', 'ninja-500-ex500-g'],
  ['Ninja H2SX SE (ZX1002-R)', 'ninja-h2sx-se-zx1002-r'],
  ['Z 500 (ER500-E)', 'z-500-er500-e'], ['Z 650 (ER650-S)', 'z-650-er650-s'],
  ['Z 900 (ZR900-F)', 'z-900-zr900-f'], ['Z 650RS (ER650-R)', 'z-650rs-er650-r'],
  ['ELIMINATOR 500 SE (EL450-B)', 'eliminator-500-se-el450-b'],
  ['FORZA350', 'forza350'], ['ADV350', 'adv350'], ['CB1000F', 'cb1000f'],
  ['CB1000 Hornet SP', 'cb1000-hornet-sp'], ['CB650R E-Clutch', 'cb650r-e-clutch'],
  ['CB300R', 'cb300r'], ['CBR650R E-Clutch', 'cbr650r-e-clutch'], ['CBR500R', 'cbr500r'],
  ['AFRICA TWIN ADVENTURE SPORTS ES DCT', 'africa-twin-adventure-sports-es-dct'],
  ['AFRICA TWIN ES', 'africa-twin-es'], ['X-ADV', 'x-adv'], ['CRF300L', 'crf300l'],
  ['CB1000GT', 'cb1000gt'],
];

test('33 catalog rows produce the expected ascii slug', () => {
  assert.equal(ROWS.length, 33);
  for (const [title, slug] of ROWS) {
    assert.equal(slugify(title), slug, `slug for ${title}`);
    assert.match(slugify(title), /^[a-z0-9-]+$/, `ascii-only slug for ${title}`);
  }
});

test('Ténéré NFKD strips diacritics to ascii', () => {
  assert.equal(slugify('Ténéré 700'), 'tenere-700');
});

test('upgradeHttp upgrades http:// to https:// (Kawasaki), leaves https untouched', () => {
  assert.equal(upgradeHttp('http://www.tw-kawasaki.com/x.jpg'), 'https://www.tw-kawasaki.com/x.jpg');
  assert.equal(upgradeHttp('https://moto.honda-taiwan.com.tw/x'), 'https://moto.honda-taiwan.com.tw/x');
  assert.equal(upgradeHttp(null), null);
  assert.equal(upgradeHttp(undefined), null);
  assert.equal(upgradeHttp(''), null);
});

test('chain order = local webp, local jpg, upgraded remote, placeholder', () => {
  const media = { 'Z 900 (ZR900-F)': 'http://www.tw-kawasaki.com/photo/color/80/x' };
  const chain = resolveListingImage('Z 900 (ZR900-F)', media);
  assert.deepEqual(chain, [
    '/static/img/bikes/z-900-zr900-f.webp',
    '/static/img/bikes/z-900-zr900-f.jpg',
    'https://www.tw-kawasaki.com/photo/color/80/x',
    INLINE_SVG_PLACEHOLDER,
  ]);
});

test('chain with no media entry skips the remote layer, tail is placeholder', () => {
  const chain = resolveListingImage('MT-07', {});
  assert.deepEqual(chain, [
    '/static/img/bikes/mt-07.webp',
    '/static/img/bikes/mt-07.jpg',
    INLINE_SVG_PLACEHOLDER,
  ]);
  assert.equal(chain[chain.length - 1], INLINE_SVG_PLACEHOLDER);
});

test('placeholder is an inline data-URI (zero network)', () => {
  assert.match(INLINE_SVG_PLACEHOLDER, /^data:image\/svg\+xml/);
});

test('attachFallback advances onerror and STOPS at placeholder (no infinite loop)', () => {
  const candidates = [
    '/static/img/bikes/x.webp',
    '/static/img/bikes/x.jpg',
    INLINE_SVG_PLACEHOLDER,
  ];
  // minimal fake <img>: setter records src; onerror is a handler we invoke manually
  const img = { _src: '', dataset: {}, set src(v) { this._src = v; }, get src() { return this._src; }, onerror: null };
  attachFallback(img, candidates);
  assert.equal(img.src, candidates[0]);          // starts at index 0
  img.onerror();                                  // webp fails
  assert.equal(img.src, candidates[1]);           // -> jpg
  img.onerror();                                  // jpg fails
  assert.equal(img.src, candidates[2]);           // -> placeholder
  const before = img.src;
  img.onerror();                                  // OVERSHOOT: placeholder "fails"
  assert.equal(img.src, before);                  // stays placeholder, no advance
  img.onerror();                                  // overshoot again
  assert.equal(img.src, INLINE_SVG_PLACEHOLDER);  // still placeholder, no loop
});

test('attachFallback exposes data-slug for debugging when provided', () => {
  const img = { _src: '', dataset: {}, set src(v) { this._src = v; }, get src() { return this._src; }, onerror: null };
  attachFallback(img, [INLINE_SVG_PLACEHOLDER], 'mt-07');
  assert.equal(img.dataset.slug, 'mt-07');
});
