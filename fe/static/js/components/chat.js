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
  }

  setMediaMap(map) { this.mediaMap = map || {}; }

  _scroll() { this.root.scrollTop = this.root.scrollHeight; }

  addUser(text) {
    this.root.appendChild(el('div', 'msg msg--user', text));
    this._scroll();
  }

  // assistant bubble; optional inline deck of enriched listing rows ([] -> empty-state card).
  addAssistant(text, rows) {
    const wrap = el('div', 'msg msg--bot');
    const textEl = el('div', 'msg__text', text);
    wrap.appendChild(textEl);

    if (Array.isArray(rows)) {
      // supersede every previous deck's actions (disable old) before showing the newest live deck
      for (const old of this._decks) {
        old.classList.add('is-superseded');
        old.querySelectorAll('button.btn--card').forEach((b) => { b.disabled = true; b.title = '此卡為舊結果，請使用最新清單'; });
      }
      const deck = renderDeck(rows, this.mediaMap, this.onAction, { superseded: false });
      wrap.appendChild(deck);
      this._decks.push(deck);

      // aria-live honest summary (zero-result must be spoken)
      const summary = rows.length === 0
        ? '查無符合條件的車輛。'
        : `找到 ${rows.length} 台車輛。`;
      if (this.liveEl) this.liveEl.textContent = summary;
    }

    this.root.appendChild(wrap);
    this._maybeClamp(textEl);
    this._scroll();
  }

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
