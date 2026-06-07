// fe/static/js/__tests__/sseparse.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SseFrameParser } from '../sseparse.js';

test('parses a single complete frame', () => {
  const p = new SseFrameParser();
  const out = p.push('event: guard\ndata: {"blocked":false,"reason":null}\n\n');
  assert.equal(out.length, 1);
  assert.equal(out[0].event, 'guard');
  assert.deepEqual(out[0].data, { blocked: false, reason: null });
});

test('buffers a frame split across two chunks', () => {
  const p = new SseFrameParser();
  let out = p.push('event: route\ndata: {"label":');
  assert.equal(out.length, 0);                 // incomplete: nothing yet
  out = p.push('"找車推薦","tokens":0}\n\n');
  assert.equal(out.length, 1);
  assert.equal(out[0].event, 'route');
  assert.deepEqual(out[0].data, { label: '找車推薦', tokens: 0 });
});

test('parses multiple frames in one chunk and skips heartbeat comments', () => {
  const p = new SseFrameParser();
  const chunk =
    ': ping\n\n' +
    'event: tool_call\ndata: {"name":"semantic_search","index":0}\n\n' +
    'event: done\ndata: {"session_id":"s1","elapsed_ms":12}\n\n';
  const out = p.push(chunk);
  assert.equal(out.length, 2);                  // ping comment is dropped
  assert.equal(out[0].event, 'tool_call');
  assert.equal(out[1].event, 'done');
  assert.equal(out[1].data.session_id, 's1');
});

test('defaults event to "message" when only data: present', () => {
  const p = new SseFrameParser();
  const out = p.push('data: {"x":1}\n\n');
  assert.equal(out.length, 1);
  assert.equal(out[0].event, 'message');
  assert.deepEqual(out[0].data, { x: 1 });
});

test('preserves non-JSON data as raw string without throwing', () => {
  const p = new SseFrameParser();
  const out = p.push('event: error\ndata: boom\n\n');
  assert.equal(out.length, 1);
  assert.equal(out[0].event, 'error');
  assert.equal(out[0].data, 'boom');           // raw string, parse-failure tolerant
});
