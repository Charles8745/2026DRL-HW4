import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initState, reduceEvent } from '../components/pipelineReducer.js';

// helper: fold a list of [etype, data] events
function fold(events, turnId = 't1') {
  let s = initState(turnId);
  for (const [etype, data] of events) s = reduceEvent(s, { etype, data });
  return s;
}

test('initState is empty streaming state', () => {
  const s = initState('t1');
  assert.equal(s.turnId, 't1');
  assert.deepEqual(s.steps, []);
  assert.equal(s.status, 'streaming');
});

test('a kind goes idle->active->done with elapsedMs', () => {
  let s = initState('t1');
  s = reduceEvent(s, { etype: 'guard', data: { active: true } });
  let step = s.steps.find((x) => x.kind === 'guard');
  assert.equal(step.status, 'active');
  s = reduceEvent(s, { etype: 'guard', data: { blocked: false, reason: null } });
  step = s.steps.find((x) => x.kind === 'guard');
  assert.equal(step.status, 'done');
  assert.ok(typeof step.elapsedMs === 'number');
});

test('BLOCKED path: guard(blocked) -> final -> done; no never-fired idle nodes', () => {
  const s = fold([
    ['guard', { blocked: true, reason: 'prompt_injection' }],
    ['final', { reply: '已忽略', blocked: true, trace: { tokens: 0 } }],
    ['done', { session_id: 's', elapsed_ms: 3 }],
  ]);
  // only the kinds that actually fired exist (no rewrite/route/tool_call idle nodes)
  assert.deepEqual(s.steps.map((x) => x.kind), ['guard', 'final', 'done']);
  assert.equal(s.steps[0].status, 'done');
  assert.equal(s.status, 'done');
});

test('FALLBACK path: guard->rewrite->route->fallback->memory->done', () => {
  const s = fold([
    ['guard', { blocked: false, reason: null }],
    ['rewrite', { rewritten_query: '你好', resolved_listing_id: null, tokens: 0 }],
    ['route', { label: '閒聊範圍外', tokens: 0 }],
    ['fallback', { reply_preview: '我是二手重機客服…' }],
    ['memory', { viewed_count: 0, slots: { budget: null, brand_pref: null, usage: null, pending_intent: null } }],
    ['done', { session_id: 's', elapsed_ms: 5 }],
  ]);
  assert.deepEqual(s.steps.map((x) => x.kind),
    ['guard', 'rewrite', 'route', 'fallback', 'memory', 'done']);
  assert.ok(s.steps.every((x) => x.status === 'done'));
});

test('DOMAIN semantic path: retrieval substeps nest under semantic_search tool_call via parentId', () => {
  const s = fold([
    ['guard', { blocked: false, reason: null }],
    ['rewrite', { rewritten_query: '新手通勤', resolved_listing_id: null, tokens: 0 }],
    ['route', { label: '找車推薦', tokens: 0 }],
    ['tool_call', { name: 'semantic_search', args: { query: '新手通勤' }, index: 0 }],
    ['retrieval', { phase: 'bm25', skipped: false, top: [{ title: 'MT-07', score: 1.2, rank: 1 }], k: 10 }],
    ['retrieval', { phase: 'vector', skipped: false, top: [], k: 10 }],
    ['retrieval', { phase: 'rrf', skipped: false, top: [], k: 10 }],
    ['retrieval', { phase: 'rerank', skipped: true, top: [], k: 10 }],
    ['tool_result', { name: 'semantic_search', index: 0, ok: true, error: null, result_summary: [] }],
    ['memory', { viewed_count: 3, slots: { budget: null, brand_pref: null, usage: null, pending_intent: null } }],
    ['done', { session_id: 's', elapsed_ms: 9 }],
  ]);
  const tool = s.steps.find((x) => x.kind === 'tool_call');
  assert.equal(tool.status, 'done');
  // the 4 retrieval substeps reference the tool_call id as parentId
  const subs = s.steps.filter((x) => x.kind === 'retrieval');
  assert.equal(subs.length, 4);
  assert.ok(subs.every((x) => x.parentId === tool.id));
  assert.deepEqual(subs.map((x) => x.payload.phase), ['bm25', 'vector', 'rrf', 'rerank']);
  assert.equal(subs.find((x) => x.payload.phase === 'rerank').payload.skipped, true);
});

test('DOMAIN confirm cross-turn: proposed (turn A) then executed (turn B) is ONE gate node', () => {
  // turn A: confirm_gate proposed -> awaiting
  let s = fold([
    ['guard', { blocked: false, reason: null }],
    ['rewrite', { rewritten_query: '約看 L001', resolved_listing_id: 'L001', tokens: 0 }],
    ['route', { label: '交易訂單', tokens: 0 }],
    ['tool_call', { name: 'book_viewing', args: { listing_id: 'L001' }, index: 0 }],
    ['tool_result', { name: 'book_viewing', index: 0, ok: null, error: null, proposed: true, result_summary: null }],
    ['confirm_gate', { tool_name: 'book_viewing', args: { listing_id: 'L001' }, stage: 'proposed' }],
    ['final', { reply: '請確認', blocked: false, awaiting_confirmation: true, trace: { tokens: 0 } }],
    ['done', { session_id: 's', elapsed_ms: 4, awaiting_confirmation: true }],
  ], 'tA');
  let gate = s.steps.filter((x) => x.kind === 'confirm_gate');
  assert.equal(gate.length, 1);
  assert.equal(gate[0].payload.stage, 'proposed');
  assert.equal(s.status, 'awaiting_confirmation');

  // turn B: the backend re-emits a REAL confirm_gate (stage executed) — the event the
  // orchestrator actually sends (M0.2 Step 4). The client REUSES the prior turn's gate node
  // (does not re-init state), so the executed event upserts the SAME single node.
  s = reduceEvent(s, { etype: 'confirm_gate',
    data: { tool_name: 'book_viewing', args: { listing_id: 'L001' },
      stage: 'executed', tool_result: { ok: true, error: null } } });
  gate = s.steps.filter((x) => x.kind === 'confirm_gate');
  assert.equal(gate.length, 1);                  // STILL one gate node (not duplicated)
  assert.equal(gate[0].payload.stage, 'executed');
  assert.equal(gate[0].status, 'done');          // executed flips the node to done
});

test('unknown kind -> generic node (forward-compatible)', () => {
  let s = initState('t1');
  s = reduceEvent(s, { etype: 'brand_new_kind_2027', data: { foo: 1 } });
  const node = s.steps[0];
  assert.equal(node.kind, 'brand_new_kind_2027');
  assert.ok(node.id);
  assert.deepEqual(node.payload, { foo: 1 });
});

test('error event sets terminal error status', () => {
  const s = fold([
    ['guard', { blocked: false, reason: null }],
    ['error', { message: 'timeout', where: 'stream' }],
  ]);
  assert.equal(s.status, 'error');
  assert.equal(s.steps.find((x) => x.kind === 'error').status, 'error');
});
