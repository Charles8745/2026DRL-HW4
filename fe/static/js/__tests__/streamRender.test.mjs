import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initState, reduceEvent } from '../components/pipelineReducer.js';

test('token events do not create pipeline steps', () => {
  let s = initState('t1');
  s = reduceEvent(s, { etype: 'token', data: { text: '你' } });
  s = reduceEvent(s, { etype: 'token', data: { text: '好' } });
  assert.equal(s.steps.length, 0);
});
