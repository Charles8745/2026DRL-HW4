// fe/static/js/main.js — entry point. Boots Gate, wires composer/landing -> SseClient.
// NOTE: PipelinePanel/ChatLog/Landing rendering is added in M4/M5; this file
// establishes the boot order + the single key getter handed to ApiClient.
import { ApiClient, SseClient, ApiError } from './api.js';
import { ByokGate } from './components/byok.js';

async function main() {
  const appEl    = document.getElementById('app');
  const dialogEl = document.querySelector('[data-byok]');

  // 1) load runtime config (demo flag + media map for listing cards in M4)
  let cfg = { demo_mode: false, media: {} };
  const probe = new ApiClient(() => { try { return sessionStorage.getItem('rb_key'); } catch { return null; } });
  try { cfg = await probe.loadConfig(); } catch { /* config optional at boot */ }

  // 2) BYOK gate; key getter is the single source ApiClient reads each request
  const gate = new ByokGate(dialogEl, { demoMode: !!cfg.demo_mode });
  const api  = new ApiClient(() => gate.getKey());
  const sse  = new SseClient(api);

  window.__rb = { cfg, gate, api, sse, sessionId: null };  // namespaced, no key stored here

  gate.boot(() => wireComposer(appEl, gate, sse));
}

function wireComposer(appEl, gate, sse) {
  const form  = document.querySelector('[data-composer]');
  const input = document.querySelector('[data-composer-input]');
  if (!form || !input) return;
  if (form.dataset.bound === '1') return;        // idempotent: bind submit exactly once
  form.dataset.bound = '1';                       // even if onReady fires again after a 401 re-entry

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    if (appEl) appEl.dataset.view = 'chat';     // landing -> chat (full morph lands in M5)

    try {
      await sse.stream(window.__rb.sessionId, text, (event, data) => {
        // M4 PipelinePanel/ChatLog reducer consumes these events.
        if (event === 'done' && data && data.session_id) window.__rb.sessionId = data.session_id;
        if (event === 'final' && data && data.trace && data.trace.session_id) {
          window.__rb.sessionId = data.trace.session_id;
        }
        document.dispatchEvent(new CustomEvent('rb:event', { detail: { event, data } }));
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { gate.onUnauthorized(); return; }
      document.dispatchEvent(new CustomEvent('rb:event', { detail: { event: 'error', data: { message: '串流發生問題，請重試', where: 'client' } } }));
    }
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', main);
} else {
  main();
}
