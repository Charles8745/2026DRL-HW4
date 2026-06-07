// fe/static/js/__tests__/landing.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HERO_FILES, heroSpecs, motionPolicy, liveSummary }
  from '../components/landing.js';

test('HERO_FILES are the 6 spec §6.1 filenames in order', () => {
  assert.deepEqual(HERO_FILES, [
    'grom.jpg', 'super-cub.jpg', 'cb650r.jpg',
    'gold-wing.jpg', 'gsx-r.jpg', 'hayabusa.jpg',
  ]);
});

test('heroSpecs builds 6 lazy hero src + 60ms stagger', () => {
  const specs = heroSpecs();
  assert.equal(specs.length, 6);
  assert.equal(specs[0].src, '/static/img/hero/grom.jpg');
  assert.equal(specs[5].src, '/static/img/hero/hayabusa.jpg');
  assert.equal(specs[0].staggerMs, 0);
  assert.equal(specs[3].staggerMs, 180); // 3 * 60
  assert.equal(specs[5].staggerMs, 300); // 5 * 60
});

test('motionPolicy: reduced disables morph+stagger and opens stream immediately', () => {
  const r = motionPolicy(true);
  assert.equal(r.morph, false);
  assert.equal(r.heroStagger, false);
  assert.equal(r.openStreamAfterMs, 0);
});

test('motionPolicy: full motion morphs then opens stream after --dur-slow', () => {
  const f = motionPolicy(false);
  assert.equal(f.morph, true);
  assert.equal(f.heroStagger, true);
  assert.equal(f.openStreamAfterMs, 420);
});

test('liveSummary: count-driven concise zh summary', () => {
  assert.equal(liveSummary(3), '找到 3 台車輛');
  assert.equal(liveSummary(1), '找到 1 台車輛');
  assert.equal(liveSummary(0), '目前沒有符合條件的車輛');
  assert.equal(liveSummary(null), '已完成回覆');
});

import { runSignatureMoment } from '../components/landing.js';

// 最小 fake landing/shell/panel（無真 DOM；用記錄 spy）。
function fakeDeps(opened) {
  const log = [];
  const listeners = {};
  const landing = {
    root: { classList: { add: (c) => log.push('root+' + c) } },
    els: {
      heroLayer: { classList: { add: (c) => log.push('hero+' + c) } },
      form: {
        addEventListener: (_e, fn) => { listeners.te = fn; },
        removeEventListener: () => {},
      },
    },
  };
  const shell = { setView: (v) => log.push('view:' + v) };
  const panel = {
    renderIdleSkeleton: () => log.push('skeleton'),
    startRewriteShimmer: () => log.push('shimmer'),
  };
  const openStream = (t) => { log.push('open:' + t); opened.push(t); };
  return { landing, shell, panel, openStream, log, listeners };
}

test('runSignatureMoment(reduced): skeleton first, then immediate open (no morph)', async () => {
  // 強制 reduced：stub matchMedia。
  globalThis.window = { matchMedia: () => ({ matches: true }) };
  const opened = [];
  const d = fakeDeps(opened);
  runSignatureMoment({ landing: d.landing, shell: d.shell, panel: d.panel,
                       text: '找車', openStream: d.openStream });
  assert.deepEqual(d.log, ['skeleton', 'view:chat', 'shimmer', 'open:找車']);
  assert.deepEqual(opened, ['找車']);
  delete globalThis.window;
});

test('runSignatureMoment(full): skeleton + morph classes first, open deferred until transitionend', async () => {
  // 強制 full-motion：matchMedia matches=false；stub timers via long delay.
  globalThis.window = { matchMedia: () => ({ matches: false }) };
  const opened = [];
  const d = fakeDeps(opened);
  runSignatureMoment({ landing: d.landing, shell: d.shell, panel: d.panel,
                       text: '比較', openStream: d.openStream });
  // morph 啟動但「尚未」開串流（gate 在 morph 之後）。
  assert.deepEqual(d.log, ['skeleton', 'root+is-morphing', 'hero+is-leaving']);
  assert.equal(opened.length, 0);
  // 模擬 morph 完成 → transitionend(transform) → 開一次。
  d.listeners.te({ propertyName: 'transform' });
  assert.deepEqual(opened, ['比較']);
  // 二次 transitionend 不重複開。
  d.listeners.te({ propertyName: 'transform' });
  assert.equal(opened.length, 1);
  delete globalThis.window;
});
