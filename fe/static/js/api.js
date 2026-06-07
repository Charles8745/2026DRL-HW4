// fe/static/js/api.js
import { SseFrameParser } from './sseparse.js';

// --- ApiClient: every request carries the BYOK header. Key lives only here +
//     sessionStorage; never written into DOM text, trace drawer, or console. ---
export class ApiClient {
  constructor(getKey) { this._getKey = getKey; this._owner = null; }   // getKey: () => string|null

  _headers(extra) {
    const h = { 'Content-Type': 'application/json', ...(extra || {}) };
    const key = this._getKey();
    if (key) h['X-RideButler-Key'] = key;
    if (this._owner) h['X-RideButler-Owner'] = this._owner;   // round-trip session ownership (R7)
    return h;
  }

  // Capture the per-session ownership token the backend issues on first use of a
  // session_id; resending it on every later request avoids 403 session_forbidden.
  _captureOwner(res) {
    const t = res.headers.get('X-RideButler-Owner');
    if (t) this._owner = t;
  }

  async loadConfig() {
    const res = await fetch('/api/config', { headers: this._headers() });
    if (!res.ok) throw new ApiError('config_failed', res.status);
    return res.json();   // { demo, models:{chat,embed}, media:{title:url} }
  }

  // Non-stream fallback. Returns { session_id, reply, blocked, awaiting_confirmation, trace }.
  async chat(sessionId, message) {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: this._headers(),
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    if (res.status === 401) throw new ApiError('unauthorized', 401);
    if (!res.ok) throw new ApiError('chat_failed', res.status);
    this._captureOwner(res);
    return res.json();
  }
}

export class ApiError extends Error {
  constructor(code, status) { super(code); this.code = code; this.status = status; }
}

// --- SseClient: opens POST /api/chat/stream, parses frames via SseFrameParser,
//     invokes onEvent(event, data) per frame. Falls back to ApiClient.chat()
//     (non-stream) on unsupported body/stream or network refusal. ---
export class SseClient {
  constructor(apiClient) { this._api = apiClient; }

  // onEvent: (eventType, data) => void. Resolves when 'done' (or stream end) reached.
  async stream(sessionId, message, onEvent) {
    let res;
    try {
      res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: this._api._headers({ Accept: 'text/event-stream' }),
        body: JSON.stringify({ session_id: sessionId, message }),
      });
    } catch (e) {
      return this._fallback(sessionId, message, onEvent);   // network/refused
    }
    if (res.status === 401) throw new ApiError('unauthorized', 401);
    if (!res.ok || !res.body) {
      return this._fallback(sessionId, message, onEvent);   // no streaming -> fallback
    }
    this._api._captureOwner(res);   // owner header is on the stream response before the body

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseFrameParser();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const frames = parser.push(decoder.decode(value, { stream: true }));
        for (const f of frames) onEvent(f.event, f.data);
      }
    } finally {
      try { reader.releaseLock(); } catch { /* noop */ }
    }
  }

  // Replays a non-stream JSON turn as a synthetic 'final' + 'done' so the
  // pipeline reducer sees a consistent event shape on fallback.
  async _fallback(sessionId, message, onEvent) {
    const out = await this._api.chat(sessionId, message);
    onEvent('final', {
      reply: out.reply,
      blocked: out.blocked,
      awaiting_confirmation: out.awaiting_confirmation,
      // mirror the orchestrator's streamed `final` defaults so the non-stream
      // fallback is byte-compatible with the SSE `final` for blocked/pending/
      // fallback/domain paths (blocked trace is {}, pending trace is {confirmation:...}).
      router_label: (out.trace && out.trace.router_label) || null,
      resolved_listing_id: (out.trace && out.trace.resolved_listing_id) || null,
      tokens: (out.trace && out.trace.tokens) || 0,
      trace: out.trace,
    });
    onEvent('done', { session_id: out.session_id, elapsed_ms: 0 });
  }
}
