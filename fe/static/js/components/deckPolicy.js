// Which router intents should surface an inline listing-card deck. Find/compare DO;
// booking confirmations, support hand-offs and chit-chat must NOT flood the chat with cards.
const DECK_LABELS = new Set(['找車推薦', '規格比較']);
export function shouldRenderDeck(routerLabel) {
  return DECK_LABELS.has(routerLabel);
}
