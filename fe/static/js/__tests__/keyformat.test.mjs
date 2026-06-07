// fe/static/js/__tests__/keyformat.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateKeyFormat } from '../keyformat.js';

test('accepts a well-formed sk- key', () => {
  assert.equal(validateKeyFormat('sk-' + 'a'.repeat(40)), true);
});

test('rejects missing sk- prefix', () => {
  assert.equal(validateKeyFormat('pk-' + 'a'.repeat(40)), false);
});

test('rejects too-short key (< 20 chars total)', () => {
  assert.equal(validateKeyFormat('sk-abc'), false);
});

test('rejects whitespace inside key', () => {
  assert.equal(validateKeyFormat('sk-' + 'a'.repeat(10) + ' ' + 'b'.repeat(10)), false);
});

test('rejects null / undefined / empty', () => {
  assert.equal(validateKeyFormat(null), false);
  assert.equal(validateKeyFormat(undefined), false);
  assert.equal(validateKeyFormat(''), false);
});

test('accepts the canonical 20-char boundary length', () => {
  assert.equal(validateKeyFormat('sk-' + 'x'.repeat(17)), true);   // total length 20
  assert.equal(validateKeyFormat('sk-' + 'x'.repeat(16)), false);  // total length 19
});
