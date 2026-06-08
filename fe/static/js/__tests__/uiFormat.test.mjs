import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowConfirm } from '../uiFormat.js';

test('awaiting_confirmation true -> show confirm/cancel', () => {
  assert.equal(shouldShowConfirm({ awaiting_confirmation: true }), true);
});
test('otherwise hidden', () => {
  assert.equal(shouldShowConfirm({ awaiting_confirmation: false }), false);
  assert.equal(shouldShowConfirm({}), false);
  assert.equal(shouldShowConfirm(null), false);
});
