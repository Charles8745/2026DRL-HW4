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
