// PipelinePanel renderer: DOM view over a reduced PipelineState (spec §4.3).
// Reads state.steps (from pipelineReducer.reduceEvent). Substeps/JSON/raw-trace collapsed by default.
import { STEP_LABELS, INTENT_META } from '../labels.js';
import { fmtMs } from '../uiFormat.js';

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

const DOT = { idle: '○', active: '◐', done: '●', error: '✕' };

// collapsed <details> JSON block
function jsonDetails(label, obj) {
  const d = el('details', 'pp-json');
  d.appendChild(el('summary', null, label));
  const pre = el('pre');
  pre.textContent = JSON.stringify(obj, null, 2);
  d.appendChild(pre);
  return d;
}

function renderStep(step) {
  const row = el('div', 'pp-step pp-step--' + step.status);
  if (step.parentId) row.classList.add('pp-step--sub');
  row.appendChild(el('span', 'pp-step__dot', DOT[step.status] || '○'));
  row.appendChild(el('span', 'pp-step__label', step.label || STEP_LABELS[step.kind] || step.kind));
  if (step.elapsedMs != null) row.appendChild(el('span', 'pp-step__time', fmtMs(step.elapsedMs)));
  // collapsed payload for tool_call / retrieval / confirm_gate
  if (step.kind === 'tool_call' || step.kind === 'retrieval' || step.kind === 'confirm_gate') {
    row.appendChild(jsonDetails('詳情', step.payload));
  }
  return row;
}

// IntentChip from the route step's label (router 5-set zh)
function intentChip(state) {
  const route = state.steps.find((s) => s.kind === 'route');
  const label = route && route.payload && route.payload.label;
  if (!label) return null;
  const meta = INTENT_META[label] || { zh: label, tone: 'offtopic' };
  return el('span', 'pp-intent pp-intent--' + meta.tone, meta.zh);
}

// token + timing footer; reads ONLY final.trace.tokens (honest 0 under FakeLLM)
function footer(state) {
  const fin = state.steps.find((s) => s.kind === 'final');
  const tokens = fin && fin.payload && fin.payload.trace ? (fin.payload.trace.tokens || 0) : 0;
  const done = state.steps.find((s) => s.kind === 'done');
  const ms = done && done.payload ? done.payload.elapsed_ms : null;
  const f = el('div', 'pp-footer');
  f.append(
    el('span', 'pp-footer__tokens', 'tokens ' + tokens),
    el('span', 'pp-footer__time', fmtMs(ms)),
  );
  return f;
}

export class PipelinePanel {
  constructor(root) { this.root = root; }

  // render(state): full repaint from reduced state. status drives the panel state class.
  render(state) {
    this.root.innerHTML = '';
    this.root.dataset.status = state.status;

    const head = el('div', 'pp-head');
    head.appendChild(el('h3', 'pp-title', '推理管線'));
    const chip = intentChip(state);
    if (chip) head.appendChild(chip);
    this.root.appendChild(head);

    const list = el('div', 'pp-steps');
    // parents first; substeps render right after their parent (retrieval under semantic_search)
    const parents = state.steps.filter((s) => !s.parentId);
    for (const p of parents) {
      list.appendChild(renderStep(p));
      const subs = state.steps.filter((s) => s.parentId === p.id);
      for (const sub of subs) list.appendChild(renderStep(sub));
    }
    this.root.appendChild(list);

    // raw trace collapsed (from final.trace)
    const fin = state.steps.find((s) => s.kind === 'final');
    if (fin && fin.payload && fin.payload.trace) {
      this.root.appendChild(jsonDetails('原始 trace', fin.payload.trace));
    }

    this.root.appendChild(footer(state));
  }
}
