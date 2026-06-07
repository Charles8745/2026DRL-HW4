// fe/static/js/components/byok.js
import { validateKeyFormat } from '../keyformat.js';

const STORAGE_KEY = 'rb_key';   // sessionStorage (per-tab); cleared on 401.

// ByokGate drives the <dialog data-byok> declared in index.html.
// Contract: key value is held ONLY in sessionStorage; the password <input> is
// cleared immediately after a successful store; the key is never logged or
// written into any visible DOM text node.
export class ByokGate {
  constructor(dialogEl, { demoMode = false } = {}) {
    this.dialog = dialogEl;
    this.demoMode = demoMode;
    this.input   = dialogEl.querySelector('[data-byok-input]');
    this.form    = dialogEl.querySelector('[data-byok-form]');
    this.errEl   = dialogEl.querySelector('[data-byok-error]');
    this.banner  = document.querySelector('[data-demo-banner]');
    this._onReady = null;

    this.form.addEventListener('submit', (e) => this._onSubmit(e));
  }

  // key getter handed to ApiClient — reads sessionStorage live each request.
  getKey() {
    try { return sessionStorage.getItem(STORAGE_KEY); } catch { return null; }
  }

  // Boot: in demo mode show amber banner and skip the gate; otherwise open the
  // dialog only when no key is stored. onReady() fires once a key exists (or demo).
  boot(onReady) {
    this._onReady = onReady;
    if (this.demoMode) {
      if (this.banner) this.banner.hidden = false;
      this._markRail('demo');
      onReady();
      return;
    }
    if (this.getKey()) { this._markRail('byok'); onReady(); return; }
    this.open();
  }

  open()  { if (!this.dialog.open) this.dialog.showModal(); this.input.focus(); }
  close() { if (this.dialog.open) this.dialog.close(); }

  _onSubmit(e) {
    e.preventDefault();
    const value = this.input.value;            // local var only; never logged
    if (!validateKeyFormat(value)) {
      this._showError('金鑰格式不正確（需 sk- 開頭、長度足夠、且無空白）');
      this._shake();
      return;
    }
    try { sessionStorage.setItem(STORAGE_KEY, value); } catch { /* private mode */ }
    this.input.value = '';                     // clear field immediately after store
    this._clearError();
    this._markRail('byok');
    this.close();
    if (this._onReady) this._onReady();
  }

  // Called by main.js when any request returns 401: drop key, reopen, shake.
  onUnauthorized() {
    try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* noop */ }
    this._markRail('demo');
    this.open();
    this._showError('金鑰無效或已被拒絕，請重新輸入');
    this._shake();
  }

  _shake() {
    const card = this.dialog.querySelector('[data-byok-card]') || this.dialog;
    card.classList.remove('shake');
    void card.offsetWidth;                     // reflow to restart animation
    card.classList.add('shake');
  }

  _showError(msg)  { if (this.errEl) { this.errEl.textContent = msg; this.errEl.hidden = false; } }
  _clearError()    { if (this.errEl) { this.errEl.textContent = ''; this.errEl.hidden = true; } }
  _markRail(state) { const r = document.querySelector('[data-key-state]'); if (r) r.dataset.key = state; }
}
