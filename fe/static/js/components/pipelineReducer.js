// PipelineState / Step reducer (spec §4.3). Pure — Node-testable.
// PipelineState = { turnId, steps:Step[], byId, status:'streaming'|'awaiting_confirmation'|'done'|'error' }
// Step          = { id, kind, label, status:'idle'|'active'|'done'|'error', payload, parentId?, elapsedMs? }
import { STEP_LABELS, TOOL_LABELS, CONFIRM_STAGE_ZH, RETRIEVAL_PHASE_ZH } from '../labels.js';

let _seq = 0;
const nextId = () => 'step-' + (++_seq);

export function initState(turnId) {
  return { turnId, steps: [], byId: Object.create(null), status: 'streaming' };
}

function labelFor(kind, data) {
  if (kind === 'tool_call' || kind === 'tool_result') {
    const zh = TOOL_LABELS[data && data.name] || (data && data.name) || '';
    return STEP_LABELS.tool_call + '·' + zh;
  }
  if (kind === 'confirm_gate') {
    const stage = (data && data.stage) || 'proposed';
    return CONFIRM_STAGE_ZH[stage] || STEP_LABELS.confirm_gate;
  }
  if (kind === 'retrieval') {
    const ph = data && data.phase;
    return STEP_LABELS.retrieval + '·' + (RETRIEVAL_PHASE_ZH[ph] || ph || '');
  }
  return STEP_LABELS[kind] || kind;   // unknown kind -> raw kind (generic node)
}

function upsert(state, { id, kind, status, payload, parentId }) {
  const existing = id ? state.byId[id] : null;
  if (existing) {
    existing.status = status;
    existing.payload = payload;
    if (status === 'done' && existing.elapsedMs == null) {
      existing.elapsedMs = Date.now() - (existing._t0 || Date.now());
    }
    existing.label = labelFor(kind, payload);
    return state;
  }
  const step = {
    id: id || nextId(), kind, label: labelFor(kind, payload),
    status, payload, _t0: Date.now(),
  };
  if (status === 'done') step.elapsedMs = 0;
  if (parentId) step.parentId = parentId;
  state.steps.push(step);
  state.byId[step.id] = step;
  return step.id, state;
}

// stable per-(turn,kind,index) key so a kind started 'active' then closed 'done' updates one node.
function keyFor(state, etype, data) {
  if (etype === 'tool_call' || etype === 'tool_result') {
    return state.turnId + ':tool:' + (data && data.index != null ? data.index : (data && data.name));
  }
  if (etype === 'retrieval') {
    return state.turnId + ':retr:' + (data && data.phase);
  }
  if (etype === 'confirm_gate') {
    // turn-INDEPENDENT key so proposed (turn A) and executed (turn B) collapse to ONE node
    return 'gate:' + (data.tool_name || (data.args && data.args.listing_id) || '');
  }
  return state.turnId + ':' + etype;
}

export function reduceEvent(state, { etype, data }) {
  data = data || {};

  // terminal error
  if (etype === 'error') {
    upsert(state, { id: keyFor(state, etype, data), kind: 'error', status: 'error', payload: data });
    state.status = 'error';
    return state;
  }

  // done sentinel: close out the turn; honor awaiting_confirmation to keep gate open
  if (etype === 'done') {
    upsert(state, { id: keyFor(state, etype, data), kind: 'done', status: 'done', payload: data });
    state.status = data.awaiting_confirmation ? 'awaiting_confirmation' : 'done';
    return state;
  }

  // confirm_gate spans turns: proposed (turn A) -> executed|cancelled (turn B). The backend
  // emits a single event name (confirm_gate, stage in {proposed,executed,cancelled}); the
  // executed/cancelled stage flips the SAME gate node to done. The client reuses the prior
  // turn's gate node (stable turn-independent key), so there is ONE confirm_gate node.
  if (etype === 'confirm_gate') {
    const id = keyFor(state, etype, data);
    const status = (data.stage === 'executed' || data.stage === 'cancelled') ? 'done' : 'active';
    upsert(state, { id, kind: 'confirm_gate', status, payload: data });
    if (data.stage === 'proposed') state.status = 'awaiting_confirmation';
    return state;
  }

  // retrieval substep nests under the current semantic_search tool_call (parentId)
  if (etype === 'retrieval') {
    const parent = [...state.steps].reverse().find(
      (x) => x.kind === 'tool_call' && x.payload && x.payload.name === 'semantic_search');
    const id = keyFor(state, etype, data);
    upsert(state, { id, kind: 'retrieval', status: 'done', payload: data,
      parentId: parent ? parent.id : undefined });
    return state;
  }

  // tool_call (start) -> active; tool_result (close) -> done/error on same node
  if (etype === 'tool_call') {
    const id = keyFor(state, etype, data);
    upsert(state, { id, kind: 'tool_call', status: 'active', payload: data });
    return state;
  }
  if (etype === 'tool_result') {
    const id = keyFor(state, etype, data);  // same key as the matching tool_call (by index)
    const status = data.ok === false ? 'error' : 'done';
    upsert(state, { id, kind: 'tool_call', status, payload: { ...data } });
    return state;
  }

  // final carries the full trace (token footer reads trace.tokens later)
  if (etype === 'final') {
    upsert(state, { id: keyFor(state, etype, data), kind: 'final', status: 'done', payload: data });
    return state;
  }

  // explicit synthetic "active" pre-event (used by skeleton); else a normal stage close -> done
  const id = keyFor(state, etype, data);
  const status = data.active ? 'active' : 'done';
  upsert(state, { id, kind: etype, status, payload: data });   // unknown kind -> generic node
  return state;
}
