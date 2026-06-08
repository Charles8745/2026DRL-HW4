// Inline ListingCard (spec §3.4). Renders from an enriched listing row.
// Actions prefill listing_id explicitly (NOT "第N台" ordinal) so a superseded deck never mis-books.
import { USAGE_ZH, CONDITION_ZH } from '../labels.js';
import { resolveListingImage, attachFallback, slugify } from './imageResolver.js';

const NT = (n) => 'NT$ ' + Number(n).toLocaleString('en-US');

// 2-3 spec pills from the enriched row's specs dict (catalog specs: displacement_cc/horsepower/torque_nm/...)
function specPills(specs) {
  if (!specs) return [];
  const pills = [];
  if (specs.displacement_cc != null) pills.push(specs.displacement_cc + ' cc');
  if (specs.horsepower != null) pills.push(specs.horsepower + ' hp');
  if (specs.weight_kg != null) pills.push(specs.weight_kg + ' kg');
  return pills.slice(0, 3);
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

// One card. `onAction(prefillText)` is called with an explicit listing_id-bearing prompt.
// `superseded` disables actions on an old deck (memory set_viewed overwrites each turn).
export function renderListingCard(row, mediaMap, onAction, { superseded = false } = {}) {
  const card = el('article', 'listing-card');
  if (superseded) card.classList.add('is-superseded');
  card.dataset.listingId = row.listing_id;

  // image (3-layer fallback)
  const fig = el('figure', 'listing-card__media');
  const img = el('img');
  img.alt = row.model;
  img.loading = 'lazy';
  attachFallback(img, resolveListingImage(row.model, mediaMap), slugify(row.model));
  fig.appendChild(img);
  card.appendChild(fig);

  const body = el('div', 'listing-card__body');

  const title = el('h4', 'listing-card__title', row.model);
  body.appendChild(title);

  const price = el('div', 'listing-card__price', NT(row.asking_price));
  body.appendChild(price);

  // meta line: year · mileage · location · seller
  const meta = el('div', 'listing-card__meta');
  meta.append(
    el('span', null, row.year + ' 年'),
    el('span', null, Number(row.mileage_km).toLocaleString('en-US') + ' km'),
    el('span', null, row.location || ''),
    el('span', null, row.seller || ''),
  );
  body.appendChild(meta);

  // chips: condition badge (zh) + usage chip (zh)
  const chips = el('div', 'listing-card__chips');
  const condBadge = el('span', 'badge badge--cond badge--cond-' + row.condition,
    row.condition + '·' + (CONDITION_ZH[row.condition] || row.condition));
  chips.appendChild(condBadge);
  if (row.usage) chips.appendChild(el('span', 'chip chip--usage', USAGE_ZH[row.usage] || row.usage));
  body.appendChild(chips);

  // spec pills (2-3)
  const pills = el('div', 'listing-card__pills');
  for (const p of specPills(row.specs)) pills.appendChild(el('span', 'pill', p));
  body.appendChild(pills);

  // semantic-only: match_snippet + 語意命中 #n
  // NOTE: retrieval_rank is 0-based in the trace (top hit = 0; retriever.py L80
  // `enumerate(...)`), but displayed +1 so the best match reads 語意命中 #1.
  if (row.match_snippet != null) {
    const sn = el('p', 'listing-card__snippet', row.match_snippet);
    if (row.retrieval_rank != null) {
      sn.appendChild(el('span', 'listing-card__rank', '語意命中 #' + (row.retrieval_rank + 1)));
    }
    body.appendChild(sn);
  }

  // actions: explicit listing_id prefill (NOT ordinal). superseded -> disabled.
  const actions = el('div', 'listing-card__actions');
  const mk = (label, prefill) => {
    const b = el('button', 'btn btn--card', label);
    b.type = 'button';
    if (superseded) { b.disabled = true; b.title = '此卡為舊結果，請使用最新清單'; }
    else b.addEventListener('click', () => onAction(prefill));
    return b;
  };
  actions.append(
    mk('查看規格', `幫我看規格 listing_id=${row.listing_id}`),
    mk('預約看車', `幫我約看 listing_id=${row.listing_id}`),
    mk('比較', `幫我比較 listing_id=${row.listing_id}`),
  );
  body.appendChild(actions);

  card.appendChild(body);
  return card;
}

// Relax-suggestion chips for the empty state (spec §3.4).
function relaxChips(onAction) {
  const wrap = el('div', 'empty-card__relax');
  const suggestions = [
    ['放寬到 30 萬', '預算放寬到 30 萬，有推薦嗎'],
    ['看其他品牌', '不限品牌，再幫我看看'],
    ['放寬車種', '不限車種，再幫我推薦'],
  ];
  for (const [label, prefill] of suggestions) {
    const b = el('button', 'chip chip--relax', label);
    b.type = 'button';
    b.addEventListener('click', () => onAction(prefill));
    wrap.appendChild(b);
  }
  return wrap;
}

// Empty-state card (data:[]). NOT an empty deck — explicit zero-result card + relax chips.
export function renderEmptyCard(onAction) {
  const card = el('article', 'listing-card empty-card');
  card.appendChild(el('h4', 'empty-card__title', '目前沒有符合條件的車輛'));
  card.appendChild(el('p', 'empty-card__hint', '試試放寬預算、品牌或車種：'));
  card.appendChild(relaxChips(onAction));
  return card;
}

// Split rows into a visible head (<= maxShown) and a collapsed tail. Pure.
export function splitDeck(rows, maxShown) {
  if (!Array.isArray(rows)) return { shown: [], hidden: [] };
  return { shown: rows.slice(0, maxShown), hidden: rows.slice(maxShown) };
}

// Render a deck of cards (or the empty-state) into a container element.
// rows: enriched listing list (possibly []). superseded marks an old deck.
export function renderDeck(rows, mediaMap, onAction, { superseded = false, maxShown = 6 } = {}) {
  const deck = el('div', 'listing-deck');
  if (!Array.isArray(rows) || rows.length === 0) {
    deck.appendChild(renderEmptyCard(onAction));
    return deck;
  }
  const { shown, hidden } = splitDeck(rows, maxShown);
  for (const row of shown) deck.appendChild(renderListingCard(row, mediaMap, onAction, { superseded }));
  if (hidden.length) {
    const more = el('div', 'listing-deck__more');
    for (const row of hidden) more.appendChild(renderListingCard(row, mediaMap, onAction, { superseded }));
    more.hidden = true;
    const btn = el('button', 'btn listing-deck__more-btn', `顯示更多（${hidden.length}）`);
    btn.type = 'button';
    btn.addEventListener('click', () => { more.hidden = false; btn.remove(); });
    deck.appendChild(more);
    deck.appendChild(btn);
  }
  return deck;
}
