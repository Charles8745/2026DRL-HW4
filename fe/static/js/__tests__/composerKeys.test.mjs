import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isSubmitKey } from '../composerKeys.js';

test('Enter (no modifier) submits', () => {
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: false }), true);
});
test('Shift+Enter is a newline, not submit', () => {
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: true, isComposing: false }), false);
});
test('Enter during IME composition does NOT submit', () => {
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: true }), false);
});
test('non-Enter keys never submit', () => {
  assert.equal(isSubmitKey({ key: 'a', shiftKey: false, isComposing: false }), false);
});

import { composerState } from '../composerKeys.js';
test('streaming -> disabled textarea + stop button', () => {
  assert.deepEqual(composerState(true),  { disabled: true,  sendLabel: '停止', stop: true });
});
test('idle -> enabled textarea + send button', () => {
  assert.deepEqual(composerState(false), { disabled: false, sendLabel: '送出', stop: false });
});
