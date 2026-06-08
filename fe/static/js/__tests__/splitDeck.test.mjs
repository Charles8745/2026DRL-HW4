import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitDeck } from '../components/listingCard.js';

test('fewer than max -> all shown, none hidden', () => {
  const { shown, hidden } = splitDeck([1,2,3], 6);
  assert.deepEqual(shown, [1,2,3]); assert.deepEqual(hidden, []);
});
test('more than max -> first N shown, rest hidden', () => {
  const rows = Array.from({length: 18}, (_, i) => i);
  const { shown, hidden } = splitDeck(rows, 6);
  assert.equal(shown.length, 6); assert.equal(hidden.length, 12);
  assert.deepEqual(shown, [0,1,2,3,4,5]);
});
test('non-array -> empty split', () => {
  assert.deepEqual(splitDeck(null, 6), { shown: [], hidden: [] });
});
