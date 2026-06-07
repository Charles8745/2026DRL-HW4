// fe/static/js/sseparse.js
// Incremental SSE frame parser. Accumulates partial chunks; emits one object
// per complete "\n\n"-delimited block. Comment lines (": ...") -> heartbeat, dropped.
// data: payload is JSON.parse'd; on failure the raw string is kept (error-tolerant).
export class SseFrameParser {
  constructor() { this.buf = ''; }

  push(chunk) {
    this.buf += chunk;
    const frames = [];
    let idx;
    while ((idx = this.buf.indexOf('\n\n')) !== -1) {
      const block = this.buf.slice(0, idx);
      this.buf = this.buf.slice(idx + 2);
      const frame = this._parseBlock(block);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  _parseBlock(block) {
    let event = 'message';
    const dataLines = [];
    let sawData = false;
    for (const line of block.split('\n')) {
      if (line === '' || line.startsWith(':')) continue;   // blank / comment(heartbeat)
      const ci = line.indexOf(':');
      const field = ci === -1 ? line : line.slice(0, ci);
      let value = ci === -1 ? '' : line.slice(ci + 1);
      if (value.startsWith(' ')) value = value.slice(1);    // strip one leading space (SSE spec)
      if (field === 'event') event = value;
      else if (field === 'data') { dataLines.push(value); sawData = true; }
    }
    if (!sawData) return null;                               // pure comment/heartbeat block
    const raw = dataLines.join('\n');
    let data;
    try { data = JSON.parse(raw); } catch { data = raw; }
    return { event, data };
  }
}
