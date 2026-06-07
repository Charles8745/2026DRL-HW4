import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  USAGE_ZH, CONDITION_ZH, TOOL_LABELS, INTENT_META, STEP_LABELS,
  CONFIRM_STAGE_ZH, RETRIEVAL_PHASE_ZH,
} from '../labels.js';

test('USAGE_ZH covers exactly the 6 catalog usage enums', () => {
  assert.deepEqual(
    Object.keys(USAGE_ZH).sort(),
    ['adventure', 'cruiser', 'naked', 'scooter', 'sport', 'touring'],
  );
  assert.equal(USAGE_ZH.sport, '仿賽');
  assert.equal(USAGE_ZH.cruiser, '美式巡航');
});

test('CONDITION_ZH covers exactly A/B/C', () => {
  assert.deepEqual(Object.keys(CONDITION_ZH).sort(), ['A', 'B', 'C']);
  assert.equal(CONDITION_ZH.A, '近全新');
});

test('TOOL_LABELS covers all 9 tool names', () => {
  assert.deepEqual(Object.keys(TOOL_LABELS).sort(), [
    'book_viewing', 'check_order', 'compare_models', 'create_ticket',
    'escalate_to_human', 'get_listing_detail', 'recommend',
    'search_listings', 'semantic_search',
  ]);
  assert.equal(TOOL_LABELS.semantic_search, '語意檢索');
});

test('INTENT_META covers the 5 router labels', () => {
  assert.deepEqual(Object.keys(INTENT_META).sort(), [
    '交易訂單', '售後轉真人', '找車推薦', '規格比較', '閒聊範圍外',
  ].sort());
});

test('STEP_LABELS covers all 10 step kinds', () => {
  assert.deepEqual(Object.keys(STEP_LABELS).sort(), [
    'confirm_gate', 'done', 'error', 'fallback', 'guard', 'memory',
    'retrieval', 'rewrite', 'route', 'tool_call',
  ]);
});

test('CONFIRM_STAGE_ZH + RETRIEVAL_PHASE_ZH present', () => {
  assert.equal(CONFIRM_STAGE_ZH.executed, '已確認');
  assert.equal(RETRIEVAL_PHASE_ZH.bm25, '關鍵字檢索');
});
