import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowConfirm, fmtMs } from '../uiFormat.js';

test('awaiting_confirmation true -> show confirm/cancel', () => {
  assert.equal(shouldShowConfirm({ awaiting_confirmation: true }), true);
});
test('otherwise hidden', () => {
  assert.equal(shouldShowConfirm({ awaiting_confirmation: false }), false);
  assert.equal(shouldShowConfirm({}), false);
  assert.equal(shouldShowConfirm(null), false);
});

test('sub-ms shows <1 ms, else rounded integer', () => {
  assert.equal(fmtMs(0), '<1 ms');
  assert.equal(fmtMs(0.4), '<1 ms');
  assert.equal(fmtMs(12.6), '13 ms');
  assert.equal(fmtMs(1200), '1200 ms');
  assert.equal(fmtMs(null), '');
});
