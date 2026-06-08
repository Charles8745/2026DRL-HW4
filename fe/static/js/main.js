// fe/static/js/main.js — entry point. Boots the BYOK gate, then wires the full
// M3/M4/M5 UI: landing hero + signature moment, shared composer, ChatLog (with
// inline ListingCard decks), and the PipelinePanel driven by the pure reducer.
//
// Boot order (single source of truth for the key getter handed to ApiClient):
//   loadConfig -> ByokGate -> ApiClient(()=>gate.getKey()) -> SseClient
//   -> mount ChatLog + PipelinePanel(+adapter) + landing -> wire composer/rail.
import { ApiClient, SseClient, ApiError } from './api.js';
import { ByokGate } from './components/byok.js';
import { isSubmitKey } from './composerKeys.js';
import {
  mountLanding, runSignatureMoment,
  ensureLiveRegion, announce, setPanelA11y,
} from './components/landing.js';
import { ChatLog } from './components/chat.js';
import { PipelinePanel } from './components/pipeline.js';
import { initState, reduceEvent } from './components/pipelineReducer.js';
import { shouldRenderDeck } from './components/deckPolicy.js';

// extractRows(trace): the inline deck for an assistant bubble. Scan trace.steps and
// keep the LAST listing-bearing tool_result.data (search_listings/recommend/
// semantic_search). Mirrors the orchestrator's own projection. null => plain bubble.
function extractRows(trace) {
  const steps = (trace && trace.steps) || [];
  let rows = null;
  for (const step of steps) {
    const data = step && step.tool_result && step.tool_result.data;
    if (
      step && (step.tool_name === 'search_listings'
        || step.tool_name === 'recommend'
        || step.tool_name === 'semantic_search')
      && Array.isArray(data)
    ) {
      rows = data;   // keep the LAST such list
    }
  }
  return rows;
}

async function main() {
  const app = document.getElementById('app');
  const dialogEl  = document.querySelector('[data-byok]');
  const panelRoot = document.querySelector('[data-pipeline]');

  // 1) runtime config (demo flag + media map for listing cards)
  let cfg = { demo: false, media: {} };
  const probe = new ApiClient(() => { try { return sessionStorage.getItem('rb_key'); } catch { return null; } });
  try { cfg = await probe.loadConfig(); } catch { /* config optional at boot */ }

  // 2) BYOK gate + ApiClient (live key getter) + SseClient
  const gate = new ByokGate(dialogEl, { demoMode: !!cfg.demo });
  const api  = new ApiClient(() => gate.getKey());
  const sse  = new SseClient(api);

  // 3) build views
  const liveEl = ensureLiveRegion(document);
  const chat = new ChatLog(document.querySelector('[data-chatlog]'), {
    liveEl,
    mediaMap: cfg.media || {},
    onAction: (prefill) => runTurn(prefill),   // card/relax chips re-enter the turn loop
  });

  // PipelinePanel has no idle-skeleton/shimmer; provide them via a thin adapter
  // (keeps pipeline.js + its node test untouched). The adapter holds the reduced
  // state and exposes the small surface runSignatureMoment expects.
  const panel = new PipelinePanel(panelRoot);
  const panelView = {
    _state: null,
    render(state) { this._state = state; panel.render(state); },
    renderIdleSkeleton() { this.render(initState('t' + turnSeq)); },
    startRewriteShimmer() { if (panelRoot) panelRoot.dataset.status = 'streaming'; },
  };

  const shell = { setView: (v) => { if (app) app.dataset.view = v; } };

  window.__rb = { cfg, gate, api, sse, chat, panel: panelView, sessionId: null };

  let turnSeq = 0;
  let pstate = null;

  // capture session id from done/final so the 2nd+ turn reuses the same session
  function captureSession(data, trace) {
    const sid = (data && data.session_id) || (trace && trace.session_id);
    if (sid) window.__rb.sessionId = sid;
  }

  // 6) openStream: drive the pipeline reducer + chat from SSE frames.
  function openStream(text) {
    setPanelA11y(panelRoot, true);
    pstate = initState('t' + turnSeq);
    return sse.stream(window.__rb.sessionId, text, (event, data) => {
      if (event === 'token') { chat.appendToken((data && data.text) || ''); return; }
      pstate = reduceEvent(pstate, { etype: event, data });
      panelView.render(pstate);
      if (event === 'final') {
        const trace = (data && data.trace) || {};
        const rows = shouldRenderDeck(data && data.router_label) ? extractRows(trace) : null;
        chat.finishAssistant((data && data.reply) || '', rows);
        announce(rows ? rows.length : null, document);
        captureSession(data, trace);
      }
      if (event === 'done') {
        captureSession(data, {});
        setPanelA11y(panelRoot, false);
      }
    }).catch((err) => {
      if (err instanceof ApiError && err.status === 401) { gate.onUnauthorized(); return; }
      setPanelA11y(panelRoot, false);
      pstate = reduceEvent(pstate, { etype: 'error', data: { message: '串流發生問題，請重試', where: 'client' } });
      panelView.render(pstate);
    });
  }

  // 5) runTurn: the single entry for landing pill, chips, composer, card actions.
  function runTurn(text) {
    const t = (text || '').trim();
    if (!t) return;
    turnSeq++;
    chat.addUser(t);
    if (turnSeq === 1) {
      // first turn: FLIP morph (or reduced-motion immediate) -> idle skeleton -> openStream.
      runSignatureMoment({ landing, shell, panel: panelView, text: t, openStream });
    } else {
      panelView.renderIdleSkeleton();
      panelView.startRewriteShimmer();
      openStream(t);
      shell.setView('chat');
    }
  }

  // 3b) mount landing into .view-landing (clear the static placeholder first)
  const landingHost = document.querySelector('.view-landing');
  if (landingHost) landingHost.innerHTML = '';
  const landing = mountLanding(landingHost, runTurn);

  // 4) shared bottom composer — bound once, idempotent across 401 re-entry.
  function wireComposer() {
    const form  = document.querySelector('[data-composer]');
    const input = document.querySelector('[data-composer-input]');
    if (!form || !input) return;
    if (form.dataset.bound === '1') return;
    form.dataset.bound = '1';
    const autosize = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px'; };
    input.addEventListener('input', autosize);
    input.addEventListener('keydown', (e) => {
      if (isSubmitKey(e)) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = input.value;
      input.value = ''; autosize();
      runTurn(text);
      input.focus();                 // keep focus on the composer for the next message
    });
  }

  // 9) IconRail actions (minimal but functional).
  function wireRail() {
    const rail = document.querySelector('.rail');
    if (!rail || rail.dataset.bound === '1') return;
    rail.dataset.bound = '1';
    rail.addEventListener('click', (e) => {
      const btn = e.target.closest('.rail__btn');
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === 'new') {
        // reset conversation: clear chat + session + back to landing.
        const log = document.querySelector('[data-chatlog]');
        if (log) log.innerHTML = '';
        chat._decks = [];
        window.__rb.sessionId = null;
        turnSeq = 0;
        if (panelRoot) panelRoot.innerHTML = '';
        shell.setView('landing');
      } else if (action === 'panel') {
        if (app) app.dataset.panel = app.dataset.panel === 'open' ? 'collapsed' : 'open';
        btn.setAttribute('aria-pressed', String(app.dataset.panel === 'open'));
      } else if (action === 'reset-key') {
        gate.onUnauthorized();   // drop key + reopen the BYOK dialog to re-enter
      } else if (action === 'help' || action === 'chat') {
        /* no-op: chat is the default view; help is informational */
      }
    });
  }

  // boot the gate; onReady fires once a key exists (or demo). Wire interactive
  // surfaces here so they only attach after the gate clears (idempotent guards
  // make a second onReady after 401 re-entry a no-op).
  gate.boot(() => { wireComposer(); wireRail(); });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', main);
} else {
  main();
}
