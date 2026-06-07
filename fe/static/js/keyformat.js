// fe/static/js/keyformat.js
// UX precheck ONLY (not a security control): ^sk- prefix, total len >= 20, no whitespace.
export function validateKeyFormat(key) {
  if (typeof key !== 'string') return false;
  if (!key.startsWith('sk-')) return false;
  if (key.length < 20) return false;
  if (/\s/.test(key)) return false;
  return true;
}
