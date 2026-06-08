// Render-decision + formatting helpers. Pure — Node-testable.
export function shouldShowConfirm(finalData) {
  return !!(finalData && finalData.awaiting_confirmation);
}

// Honest timing label: sub-millisecond stages read "<1 ms" instead of a fake "0 ms".
export function fmtMs(ms) {
  if (ms == null) return '';
  if (ms < 1) return '<1 ms';
  return Math.round(ms) + ' ms';
}
