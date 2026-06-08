// ChatLog: message feed + inline ListingCard deck per turn + aria-live summary (spec §3.4 / §4).
import { renderDeck } from './listingCard.js';

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export class ChatLog {
  // root: scroll container; liveEl: visually-hidden aria-live region; mediaMap: title->media_url;
  // onAction(prefillText): fired by card/relax chips (explicit listing_id prefill).
  constructor(root, { liveEl, mediaMap = {}, onAction = () => {} } = {}) {
    this.root = root;
    this.liveEl = liveEl;
    this.mediaMap = mediaMap;
    this.onAction = onAction;
    this._decks = [];          // track decks to supersede older ones
    this._cur = null;          // in-progress streaming bubble (set by beginAssistant)
    this._curText = null;
  }

  setMediaMap(map) { this.mediaMap = map || {}; }

  _scroll() { this.root.scrollTop = this.root.scrollHeight; }

  addUser(text) {
    this.root.appendChild(el('div', 'msg msg--user', text));
    this._scroll();
  }

  // attach an inline deck of enriched listing rows ([] -> empty-state card) to a bubble,
  // superseding every previous deck's actions first; speak an aria-live honest summary.
  _attachDeck(wrap, rows) {
    if (!Array.isArray(rows)) return;
    for (const old of this._decks) {
      old.classList.add('is-superseded');
      old.querySelectorAll('button.btn--card').forEach((b) => { b.disabled = true; b.title = '此卡為舊結果，請使用最新清單'; });
    }
    const deck = renderDeck(rows, this.mediaMap, this.onAction, { superseded: false });
    wrap.appendChild(deck);
    this._decks.push(deck);
    const summary = rows.length === 0 ? '查無符合條件的車輛。' : `找到 ${rows.length} 台車輛。`;
    if (this.liveEl) this.liveEl.textContent = summary;
  }

  beginAssistant() {
    this._cur = el('div', 'msg msg--bot');
    this._curText = el('div', 'msg__text', '');
    this._cur.appendChild(this._curText);
    this.root.appendChild(this._cur);
    this._scroll();
  }

  appendToken(t) {
    if (!this._cur) this.beginAssistant();
    this._curText.textContent += t;
    this._scroll();
  }

  // finalize the (possibly streamed) bubble: authoritative text + optional deck.
  finishAssistant(text, rows) {
    if (!this._cur) this.beginAssistant();
    this._curText.textContent = text;          // replace streamed text with the source-of-truth reply
    this._attachDeck(this._cur, rows);
    this._maybeClamp(this._curText);           // M2 Task 2.4
    this._cur = null; this._curText = null;
    this._scroll();
  }

  // one-shot (non-stream fallback / blocked / guard paths)
  addAssistant(text, rows) { this.finishAssistant(text, rows); }

  _maybeClamp(textEl) {
    requestAnimationFrame(() => {
      if (textEl.scrollHeight <= textEl.clientHeight + 2) return;  // fits — no clamp
      textEl.classList.add('msg__text--clamped');
      const btn = el('button', 'msg__expand', '展開');
      btn.type = 'button';
      btn.addEventListener('click', () => { textEl.classList.remove('msg__text--clamped'); btn.remove(); });
      textEl.after(btn);
    });
  }
}
