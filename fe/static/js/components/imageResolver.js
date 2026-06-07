// Local-first 3-layer listing image fallback (spec §6.2). Pure logic — Node-testable.
// media_url/uri live ONLY in catalog (catalog.py L39-40); _enrich (tools.py L7-10) does NOT
// copy them -> trace rows have no media_url -> client uses a title->media_url map from /api/config.

// Racing-green silhouette placeholder; zero network, never breaks.
export const INLINE_SVG_PLACEHOLDER =
  'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240" viewBox="0 0 400 240">' +
    '<rect width="400" height="240" fill="#0f2a1d"/>' +
    '<path d="M70 165 a30 30 0 1 0 0.1 0 M330 165 a30 30 0 1 0 0.1 0" fill="none" stroke="#3f6b52" stroke-width="6"/>' +
    '<path d="M100 165 L160 120 L250 120 L300 165" fill="none" stroke="#6fae8a" stroke-width="8" stroke-linecap="round"/>' +
    '<text x="200" y="215" fill="#6fae8a" font-family="sans-serif" font-size="16" text-anchor="middle">RideButler</text>' +
    '</svg>',
  );

// slugify(title): lowercase, drop parentheses/whitespace, NFKD, collapse to [a-z0-9-].
// e.g. "Ninja ZX-4RR (ZX400-S)" -> "ninja-zx-4rr-zx400-s"; "Ténéré 700" -> "tenere-700".
export function slugify(title) {
  return String(title)
    .toLowerCase()
    .replace(/[()]/g, '')                          // drop parentheses
    .normalize('NFKD')                             // decompose accents
    .replace(/[\u0300-\u036f]/g, '')               // strip combining marks
    .replace(/[^a-z0-9]+/g, '-')                   // collapse everything else to '-'
    .replace(/^-+|-+$/g, '');                      // trim leading/trailing '-'
}

// http://->https:// (fixes Kawasaki mixed-content). Returns null for empty/missing.
export function upgradeHttp(url) {
  if (!url) return null;
  return String(url).replace(/^http:\/\//i, 'https://');
}

// Build the ordered candidate chain (spec §6.2). Remote layer omitted when no media entry.
export function resolveListingImage(title, mediaMap = {}) {
  const slug = slugify(title);
  const remote = upgradeHttp(mediaMap ? mediaMap[title] : null);
  const chain = [
    '/static/img/bikes/' + slug + '.webp',
    '/static/img/bikes/' + slug + '.jpg',
  ];
  if (remote) chain.push(remote);
  chain.push(INLINE_SVG_PLACEHOLDER);              // chain tail is ALWAYS placeholder
  return chain;
}

// Wire an <img> to advance through candidates on error; tail stays placeholder forever.
export function attachFallback(img, candidates, slug) {
  let i = 0;
  if (slug !== undefined) img.dataset.slug = slug;
  img.referrerPolicy = 'no-referrer';
  img.src = candidates[0];
  img.onerror = () => {
    if (i < candidates.length - 1) {               // overshoot guard: never advance past tail
      i += 1;
      img.src = candidates[i];
    }
    // at tail (placeholder): do nothing -> no infinite onerror loop
  };
}
