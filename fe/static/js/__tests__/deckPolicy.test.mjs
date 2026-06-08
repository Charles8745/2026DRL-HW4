import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldRenderDeck } from '../components/deckPolicy.js';

test('find + compare intents render the deck', () => {
  assert.equal(shouldRenderDeck('找車推薦'), true);
  assert.equal(shouldRenderDeck('規格比較'), true);
});
test('transaction / support / offtopic do NOT render a deck', () => {
  assert.equal(shouldRenderDeck('交易訂單'), false);
  assert.equal(shouldRenderDeck('售後轉真人'), false);
  assert.equal(shouldRenderDeck('閒聊範圍外'), false);
  assert.equal(shouldRenderDeck(null), false);
});
