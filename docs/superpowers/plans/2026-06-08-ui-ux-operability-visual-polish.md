# UI 操作優化（操作性修復 + 視覺質感）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修好 RideButler 聊天區捲動致命 bug，並把推薦結果、輸入體驗、文字串流、視覺質感打磨到可用、好看、誠實。

**Architecture:** 既有三區指揮中心（rail / center(chat) / panel）+ SSE 即時管線 + BYOK。本輪以 FE/CSS 為主，搭配薄後端變更：M2 一處 prompt 精簡（會動 eval，誠實重跑）、M3 最終回覆 token 串流（只走 SSE 路徑，eval/`/api/chat` 非串流路徑不動）、M4 真實 per-stage 計時。純函式抽出走 `node --test`，UI 行為走真實瀏覽器驗收。

**Tech Stack:** Flask + vanilla ES modules（無框架）、Python 3.10（**務必 `source .venv/bin/activate`**）、OpenAI chat completions（manual function calling）、Node v22 內建 test runner、chrome-devtools/Playwright 真實瀏覽器。

---

## 重要前置（每個 session 開頭）

```bash
cd /Users/charles88/Desktop/2026DRL/HW4
source .venv/bin/activate          # Python 3.10；系統預設 3.9 會壞
git checkout feat/ui-ux-operability   # 分支已建（spec commit 在上面）
python -m pytest -q                # 基線：242 passed
node --test 'fe/static/js/__tests__/*.test.mjs'   # 基線：fail 0
```

啟動 app 驗收（**不要用 port 5000**）：
```bash
lsof -ti tcp:5001 | xargs kill -9 2>/dev/null
DEMO_MODE=1 ALLOW_ENV_KEY=1 python -c "from fe.app import _build_default; _build_default().run(host='127.0.0.1', port=5001, threaded=True)"
# 開 http://127.0.0.1:5001/（用 127.0.0.1，非 localhost）
```

真實瀏覽器驗收法（chrome-devtools）：導航 `http://127.0.0.1:5001/` → 在 landing 搜尋框填查詢「30萬內適合新手通勤的省油檔車」→ 按開始 → `wait_for` 文字「完成」→ 用 `evaluate_script` 量 DOM（捲動量、可見卡數、元素位置）。**headless 單元測試抓不到整合 bug，UI 行為一律真瀏覽器把關。**

---

## File Structure（本輪新增/修改）

**新增（純函式模組 + 測試）**
- `fe/static/js/components/deckPolicy.js` — `shouldRenderDeck(label)`（意圖 gating）
- `fe/static/js/composerKeys.js` — `isSubmitKey(e)`（Enter 送出 / Shift+Enter 換行）+ `composerState(isStreaming)`（串流中禁用/按鈕文字）
- `fe/static/js/uiFormat.js` — `fmtMs(x)`（誠實計時格式）+ `shouldShowConfirm(finalData)`（確認鈕決策）
- 對應測試：`fe/static/js/__tests__/{deckPolicy,composerKeys,uiFormat,splitDeck,streamRender}.test.mjs`

**修改（FE）**
- `fe/templates/index.html` — composer `<input>`→`<textarea>`、rail emoji→SVG、rail `title`
- `fe/static/css/{layout,chat,pipeline}.css` — 捲動、composer、泡泡、rail、面板右緣
- `fe/static/js/main.js` — gating、token/串流/abort 接線、composer 鍵盤
- `fe/static/js/components/chat.js` — 串流增量 API + 確認鈕
- `fe/static/js/components/listingCard.js` — `splitDeck` + 前 N + 顯示更多
- `fe/static/js/components/pipelineReducer.js` — token 忽略、用後端 elapsed_ms
- `fe/static/js/components/pipeline.js` — `fmtMs` 渲染
- `fe/static/js/api.js` — `SseClient.stream` 加 AbortController + `abort()`

**修改（後端，動 eval/串流）**
- `be/harness/prompts.py` — `_HANDLER_BASE` 精簡指引（M2）
- `be/harness/llm.py` — `generate(..., on_token=None)` Protocol + FakeLLM 串流支援（M3）
- `be/harness/openai_client.py` — `generate(..., on_token=None)` 串流實作（M3）
- `be/harness/handlers.py` — `run_handler(..., on_token=None)` 透傳（M3）
- `be/harness/orchestrator.py` — emit `token` 事件 + per-stage `elapsed_ms`（M3/M4）

**文件**
- `report/report.md` §7、`log.md` 新增一節、`HANDOFF.md` 同步（M2 eval 重跑後）

---

# M0 — 捲動修復 + composer 釘底（P0，CSS-only）

### Task 0.1：修聊天區捲動 + composer 固定底部

**Files:**
- Modify: `fe/static/css/layout.css`（`.center` 區塊附近，line 15、24-27）

根因：`.chatlog`（`fe/templates/index.html:69`）無任何 flex/overflow 規則；`#app` 是 `height:100vh; overflow:hidden`。`.chatlog` 不是捲動容器 → 內容溢出被裁、`maxScrollY≈37px`。`.composer`（`index.html:73`）也無 CSS。

- [ ] **Step 1：先量現況（基線，證明 bug 存在）**

啟動 app，真瀏覽器跑查詢「30萬內適合新手通勤的省油檔車」，`wait_for`「完成」後 `evaluate_script`：
```js
() => { const de=document.documentElement; window.scrollTo(0,99999); const m=Math.round(window.scrollY); window.scrollTo(0,0);
  const cards=[...document.querySelectorAll('.listing-card')];
  const vis=cards.filter(c=>{const r=c.getBoundingClientRect(); return r.top<innerHeight&&r.bottom>0;}).length;
  return { maxScrollY:m, totalCards:cards.length, cardsVisible:vis }; }
```
預期（bug）：`maxScrollY≈37`、`cardsVisible:0`。

- [ ] **Step 2：加捲動 + 釘底 CSS**

`layout.css`：把 `.center` 那段補上 `.chatlog` 與 `.composer` 規則（緊接 line 27 的 view-switch 之後）：
```css
/* chat log is THE scroll container; composer is a pinned bottom bar */
.chatlog {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
}
.composer { flex: 0 0 auto; }
#app[data-view="chat"] .composer {
  border-top: 1px solid var(--c-line);
  background: var(--c-surface);
  padding: var(--sp-3) var(--sp-4);
}
```

- [ ] **Step 3：真瀏覽器驗收**

重新整理、重跑同一查詢、`wait_for`「完成」，再跑 Step 1 的 `evaluate_script`，並用滾輪測試：
```js
() => { const el=document.querySelector('.chatlog'); el.scrollTop=el.scrollHeight;
  const cards=[...document.querySelectorAll('.listing-card')];
  const last=cards[cards.length-1].getBoundingClientRect();
  return { chatlogScrolls: el.scrollHeight>el.clientHeight, lastCardReachable: last.top<innerHeight&&last.bottom>0 }; }
```
預期：`chatlogScrolls:true`、滾輪可達最後一張、composer 永遠在底部可見、新訊息自動捲到底（`chat.js:_scroll` 對 `.chatlog` 已生效，無需改 JS）。

- [ ] **Step 4：回歸測試 + commit**

```bash
python -m pytest -q && node --test 'fe/static/js/__tests__/*.test.mjs'
git add fe/static/css/layout.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "fix(m0): chat log scrolls + composer pinned to bottom (P0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# M1 — 聊天版面與視覺重整

> 視覺工作建議實作時讀 frontend-design skill 的原則把關質感。

### Task 1.1：composer 改自動增高 textarea + Enter 送出 + 完整樣式

**Files:**
- Create: `fe/static/js/composerKeys.js`
- Create: `fe/static/js/__tests__/composerKeys.test.mjs`
- Modify: `fe/templates/index.html:73-77`、`fe/static/js/main.js:134-146`、`fe/static/css/chat.css`（檔尾新增）

- [ ] **Step 1：寫 `isSubmitKey` 測試（先失敗）**

`fe/static/js/__tests__/composerKeys.test.mjs`：
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isSubmitKey } from '../composerKeys.js';

test('Enter (no modifier) submits', () => {
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: false }), true);
});
test('Shift+Enter is a newline, not submit', () => {
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: true, isComposing: false }), false);
});
test('Enter during IME composition does NOT submit', () => {
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: true }), false);
});
test('non-Enter keys never submit', () => {
  assert.equal(isSubmitKey({ key: 'a', shiftKey: false, isComposing: false }), false);
});
```

- [ ] **Step 2：跑測試確認失敗**

Run: `node --test fe/static/js/__tests__/composerKeys.test.mjs`
Expected: FAIL（`Cannot find module ../composerKeys.js`）

- [ ] **Step 3：實作 `composerKeys.js`**

```js
// Pure helpers for the chat composer. No DOM access — Node-testable.
// Enter submits; Shift+Enter inserts a newline; Enter during IME composition is ignored.
export function isSubmitKey(e) {
  return e.key === 'Enter' && !e.shiftKey && !e.isComposing;
}

// Composer affordance while a turn is streaming: disable the textarea and turn the
// send button into a stop control. Pure — maps a boolean to display state.
export function composerState(isStreaming) {
  return isStreaming
    ? { disabled: true,  sendLabel: '停止', stop: true }
    : { disabled: false, sendLabel: '送出', stop: false };
}
```

- [ ] **Step 4：加 `composerState` 測試 + 跑全部通過**

於同檔加：
```js
import { composerState } from '../composerKeys.js';
test('streaming -> disabled textarea + stop button', () => {
  assert.deepEqual(composerState(true),  { disabled: true,  sendLabel: '停止', stop: true });
});
test('idle -> enabled textarea + send button', () => {
  assert.deepEqual(composerState(false), { disabled: false, sendLabel: '送出', stop: false });
});
```
Run: `node --test fe/static/js/__tests__/composerKeys.test.mjs` → PASS

- [ ] **Step 5：改 composer 標記為 textarea**

`index.html:73-77` 換成：
```html
      <!-- composer is shared by landing pill (hidden on landing) and chat view -->
      <form data-composer class="composer">
        <textarea data-composer-input class="composer__input" rows="1" autocomplete="off"
                  placeholder="輸入訊息，Enter 送出、Shift+Enter 換行"></textarea>
        <button type="submit" class="composer__send" aria-label="送出">送出</button>
      </form>
```

- [ ] **Step 6：composer 樣式（目前完全無 CSS）**

`chat.css` 檔尾新增：
```css
/* --- Composer (was unstyled) --- */
.composer { display: flex; gap: var(--sp-2); align-items: flex-end; }
.composer__input {
  flex: 1 1 auto; min-height: 44px; max-height: 160px; resize: none;
  font: inherit; line-height: var(--lh-body);
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--c-line); border-radius: var(--r-lg);
  background: var(--c-surface); color: var(--c-ink);
}
.composer__input:focus { outline: none; border-color: var(--c-green); }
.composer__input:disabled { opacity: 0.6; }
.composer__send {
  flex: 0 0 auto; font: inherit; cursor: pointer;
  padding: 0 var(--sp-4); height: 44px; border: none; border-radius: var(--r-lg);
  background: var(--c-green); color: var(--c-on-green);
}
.composer__send:hover { background: var(--c-green-700); }
.composer--streaming .composer__send { background: var(--c-danger); }
```

- [ ] **Step 7：接線 textarea 自動增高 + Enter 送出 + 送出後焦點回輸入框**

`main.js` 的 `wireComposer()`（line 134-146）改為：
```js
  function wireComposer() {
    const form  = document.querySelector('[data-composer]');
    const input = document.querySelector('[data-composer-input]');
    if (!form || !input) return;
    if (form.dataset.bound === '1') return;
    form.dataset.bound = '1';
    const autosize = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px'; };
    input.addEventListener('input', autosize);
    input.addEventListener('keydown', (e) => {
      if (isSubmitKey(e)) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = input.value;
      input.value = ''; autosize();
      runTurn(text);
      input.focus();                 // keep focus on the composer for the next message
    });
  }
```
並在 `main.js` 頂部 import：`import { isSubmitKey } from './composerKeys.js';`（與其他 import 並列）。

- [ ] **Step 8：真瀏覽器驗收 + commit**

驗收：textarea 多行可增高、Enter 送出、Shift+Enter 換行、送出後焦點仍在 textarea。
```bash
node --test 'fe/static/js/__tests__/*.test.mjs' && python -m pytest -q
git add fe/static/js/composerKeys.js fe/static/js/__tests__/composerKeys.test.mjs fe/templates/index.html fe/static/js/main.js fe/static/css/chat.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m1): composer textarea — autosize, Enter-to-send, focus return, full styling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 1.2：對話泡泡版面重整

**Files:** Modify `fe/static/css/chat.css:53-58`

現況：`.msg{max-width:80%}`、`.msg--user` 右、`.msg--bot` 左但 `max-width:100%`（=滿欄）。看起來塞滿、無 role 留白。

- [ ] **Step 1：改泡泡樣式**

`chat.css:53-58` 換成：
```css
/* --- ChatLog feed --- */
.msg { max-width: 76%; padding: var(--sp-3) var(--sp-4); border-radius: var(--r-lg); line-height: var(--lh-body); }
.msg--user { align-self: flex-end;  background: var(--c-green); color: var(--c-on-green); border-bottom-right-radius: var(--r-sm); }
.msg--bot  { align-self: flex-start; background: var(--c-surface); color: var(--c-ink); border: 1px solid var(--c-line); box-shadow: var(--sh-card); }
.msg--bot  { max-width: min(92%, 720px); }      /* readable text width */
.msg__text { white-space: pre-wrap; }
.msg--bot .listing-deck { max-width: 100%; }     /* deck may use the full bot bubble */
```
（`.chatlog` 已是 `display:flex; flex-direction:column; gap`，故 `align-self` 生效。若 `--r-sm` 未定義於 tokens.css，改用 `var(--r-md)`。）

- [ ] **Step 2：真瀏覽器驗收**

跑一輪查詢；確認 user 訊息為右側限寬泡泡（非滿欄綠 bar）、bot 左側限寬、訊息間有間距、車卡 deck 仍可用較寬區域。截圖留存給使用者看。

- [ ] **Step 3：commit**

```bash
git add fe/static/css/chat.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m1): chat bubble layout — aligned, width-bounded, spaced

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 1.3：rail emoji → 內嵌 SVG 圖示

**Files:** Modify `fe/templates/index.html:48-53`、`fe/static/css/layout.css:48-55`

- [ ] **Step 1：換 emoji 為單色 SVG**

`index.html:48-53` 六顆按鈕的 emoji 文字內容換成內嵌 SVG（`currentColor` 描邊，繼承 `.rail__btn` 顏色）。保留 `data-action`/`aria-label`/`aria-pressed`。範例（每顆取一個語意清楚的 24×24 線性圖示，`stroke="currentColor" fill="none" stroke-width="2"`）：
```html
      <button class="rail__btn" type="button" data-action="new" aria-label="新對話" title="新對話">
        <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
      </button>
      <button class="rail__btn" type="button" data-action="chat" aria-label="對話" aria-pressed="true" title="對話">
        <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.3 7.3L4 21l1.7-5.7A8 8 0 1 1 21 12z"/></svg>
      </button>
      <button class="rail__btn" type="button" data-action="panel" aria-label="切換管線面板" aria-pressed="true" title="切換管線面板">
        <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 19V11M12 19V5M19 19v-5"/></svg>
      </button>
      <button class="rail__btn" type="button" data-action="help" aria-label="說明" title="說明">
        <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1 .9-1 1.7M12 17h.01"/></svg>
      </button>
      <div class="rail__spacer"></div>
      <button class="rail__btn" type="button" data-action="reset-key" aria-label="重設金鑰" title="重設金鑰">
        <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 20 3M16 7l3 3M14 9l2 2"/></svg>
      </button>
```

- [ ] **Step 2：rail 按鈕樣式微調（讓 SVG 置中）**

`layout.css:48-55` `.rail__btn` 已是 `display:grid; place-items:center`，SVG 直接置中即可；確認 `.rail__btn svg{display:block}`。若需要，於 `.rail__btn` 區塊後加：
```css
.rail__btn svg { display: block; }
```

- [ ] **Step 3：真瀏覽器驗收 + commit**

驗收：rail 為乾淨單色線性圖示、無 emoji、hover/pressed 背景正常、aria-pressed 切換（panel 按鈕）仍運作。
```bash
git add fe/templates/index.html fe/static/css/layout.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m1): replace rail emoji with inline SVG icons

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 1.4：landing 收成單一輸入

**Files:** Modify `fe/static/css/layout.css`（view-switch 區，line 24-27 附近）

- [ ] **Step 1：landing 時隱藏底部 composer**

於 layout.css view-switch 規則後加：
```css
#app[data-view="landing"] .composer { display: none; }
```

- [ ] **Step 2：真瀏覽器驗收 + commit**

驗收：首頁只剩中央 `.landing__pill` 一個輸入框（底部 composer 不見）；送出後切到 chat view，composer 出現在底部。
```bash
git add fe/static/css/layout.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m1): hide docked composer on landing (single input)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# M2 — 結果呈現：卡片為主 + 一句話摘要

### Task 2.1：車卡意圖 gating（追問/確認不附車卡）

**Files:**
- Create: `fe/static/js/components/deckPolicy.js`、`fe/static/js/__tests__/deckPolicy.test.mjs`
- Modify: `fe/static/js/main.js:92-98`（`final` 處理）

- [ ] **Step 1：寫測試（先失敗）**

`fe/static/js/__tests__/deckPolicy.test.mjs`：
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldRenderDeck } from '../components/deckPolicy.js';

test('find + compare intents render the deck', () => {
  assert.equal(shouldRenderDeck('找車推薦'), true);
  assert.equal(shouldRenderDeck('規格比較'), true);
});
test('transaction / support / offtopic do NOT render a deck', () => {
  assert.equal(shouldRenderDeck('交易訂單'), false);
  assert.equal(shouldRenderDeck('售後轉真人'), false);
  assert.equal(shouldRenderDeck('閒聊範圍外'), false);
  assert.equal(shouldRenderDeck(null), false);
});
```

- [ ] **Step 2：跑確認失敗** — `node --test fe/static/js/__tests__/deckPolicy.test.mjs` → FAIL

- [ ] **Step 3：實作 `deckPolicy.js`**

```js
// Which router intents should surface an inline listing-card deck. Find/compare DO;
// booking confirmations, support hand-offs and chit-chat must NOT flood the chat with cards.
const DECK_LABELS = new Set(['找車推薦', '規格比較']);
export function shouldRenderDeck(routerLabel) {
  return DECK_LABELS.has(routerLabel);
}
```

- [ ] **Step 4：跑確認通過** — PASS

- [ ] **Step 5：main.js 套用 gating**

import：`import { shouldRenderDeck } from './components/deckPolicy.js';`
`final` 分支（line 92-98）改為：
```js
      if (event === 'final') {
        const trace = (data && data.trace) || {};
        const rows = shouldRenderDeck(data && data.router_label) ? extractRows(trace) : null;
        chat.addAssistant((data && data.reply) || '', rows);   // M3 Task 3.4 會改為 finishAssistant
        announce(rows ? rows.length : null, document);
        captureSession(data, trace);
      }
```
> 註：M2 此處用既有的 `chat.addAssistant(...)`（finishAssistant 到 M3 Task 3.4 才建立）。M3 Task 3.4 會把 addAssistant 重構為委派 finishAssistant，並把本處改成 `chat.finishAssistant(...)`。**本 Step 程式碼以 addAssistant 為準。**

- [ ] **Step 6：真瀏覽器驗收**

跑「找車」→ 有車卡；接著追問「我要預約看第一台」→ **無車卡**（只有確認文字）；問「謝謝」→ 無車卡。

- [ ] **Step 7：測試 + commit**

```bash
node --test 'fe/static/js/__tests__/*.test.mjs'
git add fe/static/js/components/deckPolicy.js fe/static/js/__tests__/deckPolicy.test.mjs fe/static/js/main.js
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m2): gate listing deck by intent — no card flood on booking/support/chitchat

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2.2：前 6 張 + 顯示更多

**Files:**
- Create: `fe/static/js/__tests__/splitDeck.test.mjs`
- Modify: `fe/static/js/components/listingCard.js:129-139`、`fe/static/css/chat.css`

- [ ] **Step 1：寫 `splitDeck` 測試（先失敗）**

`fe/static/js/__tests__/splitDeck.test.mjs`：
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitDeck } from '../components/listingCard.js';

test('fewer than max -> all shown, none hidden', () => {
  const { shown, hidden } = splitDeck([1,2,3], 6);
  assert.deepEqual(shown, [1,2,3]); assert.deepEqual(hidden, []);
});
test('more than max -> first N shown, rest hidden', () => {
  const rows = Array.from({length: 18}, (_, i) => i);
  const { shown, hidden } = splitDeck(rows, 6);
  assert.equal(shown.length, 6); assert.equal(hidden.length, 12);
  assert.deepEqual(shown, [0,1,2,3,4,5]);
});
test('non-array -> empty split', () => {
  assert.deepEqual(splitDeck(null, 6), { shown: [], hidden: [] });
});
```

- [ ] **Step 2：跑確認失敗** — FAIL

- [ ] **Step 3：實作 `splitDeck` + 改 `renderDeck`**

`listingCard.js`：在 `renderDeck` 前新增 export：
```js
// Split rows into a visible head (<= maxShown) and a collapsed tail. Pure.
export function splitDeck(rows, maxShown) {
  if (!Array.isArray(rows)) return { shown: [], hidden: [] };
  return { shown: rows.slice(0, maxShown), hidden: rows.slice(maxShown) };
}
```
`renderDeck`（line 131-139）改為支援 maxShown（預設 6）+ 顯示更多：
```js
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
```
> `.listing-deck` 是 grid；`.listing-deck__more` 也應是同樣 grid 才能無縫銜接。

- [ ] **Step 4：CSS（顯示更多容器與按鈕）**

`chat.css` `.listing-deck` 規則後加：
```css
.listing-deck__more { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: var(--sp-3); margin-top: var(--sp-3); }
.listing-deck__more[hidden] { display: none; }
.listing-deck__more-btn { justify-self: start; margin-top: var(--sp-2); }
```

- [ ] **Step 5：跑測試 + 真瀏覽器驗收**

`node --test fe/static/js/__tests__/splitDeck.test.mjs` → PASS。瀏覽器：18 筆結果預設只見 6 張 + 「顯示更多（12）」；點擊展開其餘、按鈕消失。

- [ ] **Step 6：commit**

```bash
git add fe/static/js/components/listingCard.js fe/static/js/__tests__/splitDeck.test.mjs fe/static/css/chat.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m2): show top 6 cards + 顯示更多 toggle for the rest

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2.3：prompt 精簡（找車推薦回覆不重述卡片規格）

**Files:**
- Modify: `be/harness/prompts.py:13-24`
- Create/Modify: `tests/test_prompts_concise.py`

> ⚠️ 這是本輪唯一動 eval 數字處。eval 重跑在 Task 5.1 統一做。

- [ ] **Step 1：寫 Python 斷言（先失敗）**

`tests/test_prompts_concise.py`：
```python
from be.harness.prompts import handler_sys

def test_find_handler_asks_for_concise_summary():
    s = handler_sys("找車推薦")
    assert "1-2 句" in s or "1–2 句" in s
    assert "不要" in s and "重述" in s   # 不重述卡片規格
```

- [ ] **Step 2：跑確認失敗** — `python -m pytest tests/test_prompts_concise.py -q` → FAIL

- [ ] **Step 3：改 `_HANDLER_BASE`**

`prompts.py:13-17` 換成：
```python
_HANDLER_BASE = (
    "你是二手重機平台客服的「{domain}」處理器。只能使用本情境提供的工具取得事實。"
    "所有車款、規格、價格、車況、訂單狀態都必須來自工具回傳，不可捏造（groundedness）。"
    "查無資料就如實告知。完成後以繁體中文清楚回覆使用者。"
    "若有推薦或列出車輛，卡片會另外完整呈現規格與價格，因此你的文字回覆**僅以 1-2 句**"
    "總結推薦理由或重點，**不要逐台重述卡片上已顯示的規格與里程**（價格可自然帶到）。"
)
```
> **為何保留「價格可自然帶到」**：groundedness 計分器（`be/eval/run_eval.py:14-16`）只白名單價格。若連價格都不提，groundedness 變成「無事實可驗」的空泛通過（不誠實）。保留價格 → 仍可量測；里程（5 位數）非白名單、是已知偽陽性來源，不重述里程預期合理降低違規率。Step 1 測試斷言（`不要`+`重述`）仍成立，無需改測試。

- [ ] **Step 4：跑確認通過 + 全 pytest 綠**

```bash
python -m pytest tests/test_prompts_concise.py -q   # PASS
python -m pytest -q                                 # 既有 242 + 1 全綠（凍結守門不受影響）
```

- [ ] **Step 5：commit**

```bash
git add be/harness/prompts.py tests/test_prompts_concise.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m2): concise find-recommend reply — summarize, don't repeat card specs (eval re-run pending)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2.4：prose 安全收合（長文字預設收起）

**Files:** Modify `fe/static/css/chat.css`、`fe/static/js/components/chat.js`

> 即使 prompt 已精簡，保險：bot 文字超過約 6 行時 clamp + 「展開」。

- [ ] **Step 1：CSS clamp**

`chat.css` 加：
```css
.msg__text--clamped { display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }
.msg__expand { margin-top: var(--sp-1); background: none; border: none; color: var(--c-green); cursor: pointer; font: inherit; padding: 0; }
```

- [ ] **Step 2：chat.js 在訊息收尾時判斷是否 clamp**

**本 M2 階段**：把 `_maybeClamp(textEl)` 加到 `addAssistant` 設定文字後呼叫（finishAssistant 到 M3 Task 3.4 才建立）。M3 Task 3.4 把 addAssistant 重構為委派 finishAssistant 時，`_maybeClamp` 的呼叫會一併移進 finishAssistant（同一處）。設定文字後，量 `scrollHeight` 是否超過 clamp 高度，超過則加 `.msg__text--clamped` 並插入「展開」按鈕：
```js
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
```
> 依賴渲染後量高，故用 `requestAnimationFrame`。串流期間不 clamp（只在 finish 後量一次）。

- [ ] **Step 3：真瀏覽器驗收 + commit**

驗收：短回覆不 clamp；若出現長回覆則收 6 行 + 「展開」。
```bash
git add fe/static/css/chat.css fe/static/js/components/chat.js
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m2): clamp long assistant prose with 展開 fallback

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# M3 — 文字串流輸出 + 串流互動

### Task 3.1：後端 streaming generate（OpenAIClient + Protocol + FakeLLM）

**Files:**
- Modify: `be/harness/llm.py:15-25`、`be/harness/openai_client.py:33-51`
- Create: `tests/test_streaming_llm.py`

- [ ] **Step 1：寫 FakeLLM 串流測試（先失敗）**

`tests/test_streaming_llm.py`：
```python
from be.harness.llm import FakeLLM, LLMResponse

def test_fake_llm_streams_text_via_on_token():
    fake = FakeLLM([LLMResponse(text="新手通勤推薦這幾台", tool_calls=[], total_tokens=5)])
    chunks = []
    resp = fake.generate("sys", [{"role": "user", "content": "x"}], on_token=chunks.append)
    assert "".join(chunks) == "新手通勤推薦這幾台"   # 串流片段拼回原文
    assert len(chunks) >= 2                          # 真的分多段
    assert resp.text == "新手通勤推薦這幾台"          # 回傳值不變

def test_fake_llm_without_on_token_is_unchanged():
    fake = FakeLLM([LLMResponse(text="hi", tool_calls=[], total_tokens=1)])
    resp = fake.generate("sys", [], )               # 無 on_token
    assert resp.text == "hi"
```

- [ ] **Step 2：跑確認失敗** — FAIL（`generate() got unexpected keyword 'on_token'`）

- [ ] **Step 3：Protocol + FakeLLM 加 on_token**

`llm.py`：
```python
class LLM(Protocol):
    def generate(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 on_token=None) -> LLMResponse: ...

class FakeLLM:
    """Returns scripted LLMResponses in order. Used by all unit tests."""
    def __init__(self, scripted: list):
        self.scripted, self.calls = scripted, 0
    def generate(self, system, messages, tools=None, on_token=None) -> LLMResponse:
        resp = self.scripted[self.calls]
        self.calls += 1
        if on_token is not None and resp.text:        # mimic token streaming deterministically
            for i in range(0, len(resp.text), 4):
                on_token(resp.text[i:i + 4])
        return resp
```

- [ ] **Step 4：OpenAIClient 串流實作**

`openai_client.py` 的 `generate`（line 33-51）改為：
```python
    def generate(self, system, messages, tools=None, on_token=None) -> LLMResponse:
        kwargs = {"model": self.model, "messages": _to_openai_messages(system, messages),
                  "temperature": 0}
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False
        if on_token is None:
            resp = self.client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            calls = []
            for tc in (msg.tool_calls or []):
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                calls.append(ToolCall(tc.function.name, args))
            usage = getattr(resp, "usage", None)
            return LLMResponse(text=msg.content, tool_calls=calls,
                               total_tokens=getattr(usage, "total_tokens", 0) or 0)
        # streaming path: forward content deltas to on_token; reconstruct tool calls + usage
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        parts, frags, total = [], {}, 0
        for chunk in self.client.chat.completions.create(**kwargs):
            if getattr(chunk, "usage", None):
                total = chunk.usage.total_tokens or 0
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                parts.append(delta.content)
                try:
                    on_token(delta.content)
                except Exception:
                    pass
            for tc in (getattr(delta, "tool_calls", None) or []):
                slot = frags.setdefault(tc.index, {"name": None, "args": ""})
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
        calls = []
        for idx in sorted(frags):
            f = frags[idx]
            if not f["name"]:
                continue
            try:
                args = json.loads(f["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(f["name"], args))
        return LLMResponse(text=("".join(parts) or None), tool_calls=calls, total_tokens=total)
```
> **實作注意（保 eval 相同性 + 穩健）**：(1) 非串流與串流兩路徑的 tool_call 參數都走 `json.loads(... or "{}")`、text 都以 `"".join` 重組，確保 `test_on_step_none_is_identical` 位元相同；(2) `tc.index` 可能為 None → `frags.setdefault(...)` 前先 `if tc.index is None: continue`；(3) 只在 `delta.content` 非空才呼叫 `on_token`（工具輪通常無 content）；(4) `on_token` 例外不可中斷串流——以 `import logging; logging.warning(...)` 取代 bare `pass`；(5) `usage` 只在最後一個 chunk 出現（`include_usage`），用「最後看到的值」即可。

- [ ] **Step 5：跑測試 + 全 pytest** — `python -m pytest tests/test_streaming_llm.py -q` PASS；`python -m pytest -q` 全綠。

- [ ] **Step 6：commit**

```bash
git add be/harness/llm.py be/harness/openai_client.py tests/test_streaming_llm.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m3): LLM.generate(on_token=...) streaming path (FakeLLM + OpenAI)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 3.2：run_handler 透傳 on_token

**Files:** Modify `be/harness/handlers.py:39-48`、Create `tests/test_handler_streaming.py`

- [ ] **Step 1：寫測試（先失敗）**

`tests/test_handler_streaming.py`：
```python
from be.harness.llm import FakeLLM, LLMResponse
from be.harness.governance import TurnBudget
from be.harness.handlers import run_handler
from de.data.store import DataStore   # 若建構需參數，依現有測試的建法

def test_run_handler_streams_final_reply():
    fake = FakeLLM([LLMResponse(text="這是最終回覆", tool_calls=[], total_tokens=3)])
    chunks = []
    out = run_handler(fake, None, "找車推薦", "查詢", TurnBudget(5), on_token=chunks.append)
    assert out["reply"] == "這是最終回覆"
    assert "".join(chunks) == "這是最終回覆"
```
> 若 `store=None` 在無工具呼叫路徑可行（本案最終回覆輪不碰 store）。建構 DataStore 的方式參考 `tests/` 既有 handler 測試。

- [ ] **Step 2：跑確認失敗** — FAIL

- [ ] **Step 3：handlers.py 加 on_token**

`run_handler` 簽章與最終回覆那輪的 generate：
```python
def run_handler(llm, store, domain, query, budget, on_step=None, on_token=None) -> dict:
    schemas = schemas_for(domain)
    messages = [{"role": "user", "content": query}]
    trace, tokens = [], 0
    while True:
        resp = llm.generate(handler_sys(domain), messages, tools=schemas, on_token=on_token)
        tokens += resp.total_tokens
        if not resp.tool_calls:
            return {"reply": resp.text or "", "trace": trace,
                    "pending_action": None, "budget_exceeded": False, "tokens": tokens}
        ...
```
（其餘不變。on_token 傳給每輪 generate；工具輪通常無 content → 不發 token，最終輪才串流。）

- [ ] **Step 4：跑測試 + 全 pytest 綠 + commit**

```bash
python -m pytest tests/test_handler_streaming.py -q && python -m pytest -q
git add be/harness/handlers.py tests/test_handler_streaming.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m3): run_handler forwards on_token to the LLM

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 3.3：orchestrator emit `token` 事件（保 on_step=None 不變）

**Files:** Modify `be/harness/orchestrator.py:58-203`、Create `tests/test_orchestrator_streaming.py`

- [ ] **Step 1：寫測試（先失敗）— 用既有 `_orch` 樣式，無 fixture 依賴**

`tests/test_orchestrator_streaming.py`（建構照 `tests/test_orchestrator_stream.py:15-16` 的 `_orch`：`Orchestrator(FakeLLM(scripted), DataStore(seed=42), SessionStore())`。一個找車輪 = rewrite→route→handler 共 3 次 `generate`（rewriter.py:5 一次、router 一次、handler 一次）；讓 handler 第一次就回文字、不呼叫工具，最終文字即會串流）：
```python
from de.data.store import DataStore
from be.harness.memory import SessionStore
from be.harness.llm import FakeLLM, LLMResponse
from be.harness.orchestrator import Orchestrator


def _orch(scripted):
    return Orchestrator(FakeLLM(scripted), DataStore(seed=42), SessionStore())


def test_emits_token_events_when_on_step_present():
    o = _orch([
        LLMResponse(text="新手通勤推薦", total_tokens=1),        # rewrite
        LLMResponse(text="找車推薦", total_tokens=1),            # route
        LLMResponse(text="這幾台都適合新手通勤", total_tokens=3),  # handler: 無 tool_call → 直接最終文字
    ])
    sid = o.memory.new_session()
    events = []
    o.process(sid, "推薦新手通勤車", on_step=lambda e, d: events.append((e, d)))
    toks = [d["text"] for (e, d) in events if e == "token"]
    assert "".join(toks) == "這幾台都適合新手通勤"   # FakeLLM 分段 on_token，拼回原文


def test_no_token_when_on_step_none():
    o = _orch([
        LLMResponse(text="新手通勤推薦", total_tokens=1),
        LLMResponse(text="找車推薦", total_tokens=1),
        LLMResponse(text="這幾台都適合新手通勤", total_tokens=3),
    ])
    sid = o.memory.new_session()
    out = o.process(sid, "推薦新手通勤車")   # on_step=None → 不串流、無 token
    assert out["reply"] == "這幾台都適合新手通勤"
```

- [ ] **Step 2：跑確認失敗** — `python -m pytest tests/test_orchestrator_streaming.py -q` → FAIL

- [ ] **Step 3：orchestrator 建立 on_token 並透傳**

`process` 內、guard 通過後（約 line 70 之後、進入各路徑前）建立：
```python
        on_token = None
        if on_step is not None:
            def on_token(t, _emit=self._emit, _os=on_step):
                _emit(_os, "token", {"text": t})
```
fallback 路徑的 generate（line 131）改：
```python
            resp = self.llm.generate(FALLBACK_SYS, [{"role": "user", "content": rw["rewritten_query"]}],
                                     tools=None, on_token=on_token)
```
handler 呼叫（line 154-155）改：
```python
        out = run_handler(self.llm, self.store, label, handler_query,
                          TurnBudget(config.MAX_TOOL_CALLS_PER_TURN), on_step=on_step, on_token=on_token)
```
> **非 SSE 路徑保持 on_step=None**：eval（`be/eval/*`）與 `/api/chat` 直呼 `orchestrator.process(...)` 不帶 on_step → on_token=None → 非串流，行為不變。只有 SSE 路徑（`fe/streaming.py` 的 StreamRunner 以 `on_step=queue.put` 呼叫）會帶 on_step。

- [ ] **Step 4：⚠️ 更新既有「精確事件序列」測試（token 是新事件，會插進序列）**

加 on_token 後，`tests/test_orchestrator_stream.py` 內**對精確事件序列做斷言**的測試會看到新的 `token` 事件而失敗——這些是我們自己的測試，誠實更新：序列斷言改成「先濾掉 token 再比對」，並另外正向斷言有 token。已知會中招（實作時 grep `types == [` 再全部掃過）：
- `test_fallback_path_event_sequence`（約 line 170-173）：fallback 的 generate 串流 → token 落在 route 與 fallback 之間。
- `test_recommend_path_emits_tool_call_then_tool_result`（約 line 177-180）：handler 最終文字串流 → token 落在 tool_result 與 memory 之間。
- 同檔其他 `types == [...]` 精確比對的路徑測試（semantic 等）一併掃。

改法（每處把取 types 那行改為濾 token，並加一行正向斷言）：
```python
    types = [et for et, _ in events if et != "token"]   # token 是 streaming 文字事件，與階段序列正交
    assert types == ["guard", "rewrite", "route", "tool_call", "tool_result", "memory", "final"]
    assert any(et == "token" for et, _ in events)        # 會產生文字的路徑：確有串流出 token
```
> guard-only / pending-confirm（純確認、無 generate 文字）路徑無 token，那些測試不必動。`test_on_step_none_is_identical` 也不必動（on_step=None 無 token）。

- [ ] **Step 5：驗證 on_step=None 位元相同（凍結守門）+ 全綠**

```bash
python -m pytest tests/test_orchestrator_stream.py::test_on_step_none_is_identical -q   # 必過（on_step=None → on_token=None → 非串流 → 位元相同）
python -m pytest tests/test_orchestrator_streaming.py -q                                # 新測試 PASS
python -m pytest -q                                                                     # 全綠（含上面更新後的序列測試）
```

- [ ] **Step 6：commit**

```bash
git add be/harness/orchestrator.py tests/test_orchestrator_streaming.py tests/test_orchestrator_stream.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m3): orchestrator emits token events on SSE path (on_step=None unchanged)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 3.4：FE token 增量渲染

**Files:**
- Modify: `fe/static/js/components/chat.js`、`fe/static/js/main.js:86-109`、`fe/static/js/components/pipelineReducer.js:66-68`
- Create: `fe/static/js/__tests__/streamRender.test.mjs`

- [ ] **Step 1：reducer 忽略 token（先寫測試）**

`fe/static/js/__tests__/streamRender.test.mjs`：
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initState, reduceEvent } from '../components/pipelineReducer.js';

test('token events do not create pipeline steps', () => {
  let s = initState('t1');
  s = reduceEvent(s, { etype: 'token', data: { text: '你' } });
  s = reduceEvent(s, { etype: 'token', data: { text: '好' } });
  assert.equal(s.steps.length, 0);
});
```

- [ ] **Step 2：跑確認失敗** — FAIL（目前 token 會建 generic node）

- [ ] **Step 3：reducer 早退 token**

`pipelineReducer.js` `reduceEvent` 開頭（`data = data || {};` 之後）加：
```js
  if (etype === 'token') return state;   // streamed reply text is rendered by ChatLog, not the pipeline
```

- [ ] **Step 4：跑確認通過** — PASS

- [ ] **Step 5：ChatLog 串流增量 API（重構 addAssistant）**

`chat.js`：把 deck 附掛抽成 `_attachDeck`，新增 `beginAssistant/appendToken/finishAssistant`，`addAssistant` 保留為一次性（委派 finish）：
```js
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
```

- [ ] **Step 6：main.js 接 token + finish**

`openStream` 的 callback（line 89-98）：
```js
    return sse.stream(window.__rb.sessionId, text, (event, data) => {
      if (event === 'token') { chat.appendToken((data && data.text) || ''); return; }
      pstate = reduceEvent(pstate, { etype: event, data });
      panelView.render(pstate);
      if (event === 'final') {
        const trace = (data && data.trace) || {};
        const rows = shouldRenderDeck(data && data.router_label) ? extractRows(trace) : null;
        chat.finishAssistant((data && data.reply) || '', rows);
        announce(rows ? rows.length : null, document);
        captureSession(data, trace);
      }
      if (event === 'done') { captureSession(data, {}); setPanelA11y(panelRoot, false); }
    })
```

- [ ] **Step 7：真瀏覽器驗收（真實 OpenAI）**

用 demo 模式跑「找車」：文字逐段（4 字/段或真 token）出現在 bot 泡泡，結束後文字定稿 + 車卡掛上（前 6 + 顯示更多）。確認管線面板**不**出現 token 節點。

- [ ] **Step 8：測試 + commit**

```bash
node --test 'fe/static/js/__tests__/*.test.mjs'
git add fe/static/js/components/chat.js fe/static/js/main.js fe/static/js/components/pipelineReducer.js fe/static/js/__tests__/streamRender.test.mjs
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m3): incremental token rendering in ChatLog; reducer ignores token

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 3.5：串流中禁用 composer + 可停止

**Files:** Modify `fe/static/js/api.js:51-85`、`fe/static/js/main.js`

- [ ] **Step 1：SseClient 支援中止**

`api.js` `SseClient`：
```js
export class SseClient {
  constructor(apiClient) { this._api = apiClient; this._ctrl = null; }

  abort() { try { this._ctrl && this._ctrl.abort(); } catch { /* noop */ } }

  async stream(sessionId, message, onEvent) {
    this._ctrl = new AbortController();
    let res;
    try {
      res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: this._api._headers({ Accept: 'text/event-stream' }),
        body: JSON.stringify({ session_id: sessionId, message }),
        signal: this._ctrl.signal,
      });
    } catch (e) {
      if (e && e.name === 'AbortError') return;     // user stopped before headers
      return this._fallback(sessionId, message, onEvent);
    }
    if (res.status === 401) throw new ApiError('unauthorized', 401);
    if (!res.ok || !res.body) return this._fallback(sessionId, message, onEvent);
    this._api._captureOwner(res);
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
    } catch (e) {
      if (!(e && e.name === 'AbortError')) throw e;  // abort = clean stop, swallow
    } finally {
      try { reader.releaseLock(); } catch { /* noop */ }
      this._ctrl = null;
    }
  }
  // _fallback unchanged
```

- [ ] **Step 2：main.js 串流狀態 + 停止鈕**

import：`import { isSubmitKey, composerState } from './composerKeys.js';`
新增套用函式 + 在 stream 起訖切換狀態。**宣告位置**：把 `let streaming = false;` 與 `function setStreaming(on){...}` 放在 `main()` body 內、緊接 `let pstate = null;`（約 line 77）之後、且在 `wireComposer`/`openStream` 定義之前——兩者皆為 `main()` 內的巢狀函式，故能共用此閉包變數：
```js
  let streaming = false;
  function setStreaming(on) {
    streaming = on;
    const form  = document.querySelector('[data-composer]');
    const input = document.querySelector('[data-composer-input]');
    const send  = document.querySelector('.composer__send');
    if (!form || !input || !send) return;
    const st = composerState(on);
    input.disabled = st.disabled;
    send.textContent = st.sendLabel;
    form.classList.toggle('composer--streaming', st.stop);
  }
```
`openStream` 開頭 `setStreaming(true)`；在 `.catch`、`done` 與 `final` 收尾後 `setStreaming(false)`（最穩妥：done 一定到）。實作：把 `setPanelA11y(panelRoot,false)` 之處一併 `setStreaming(false)`，並在 `.catch` 內也呼叫。
`wireComposer` 的 submit handler 先判斷停止：
```js
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      if (streaming) { sse.abort(); setStreaming(false); return; }   // 送出鈕在串流中＝停止
      const text = input.value;
      input.value = ''; autosize();
      runTurn(text);
      input.focus();
    });
```

- [ ] **Step 3：真瀏覽器驗收**

串流中 textarea 禁用、送出鈕變「停止」(紅)；點停止 → 文字停止增長、面板回 idle、composer 恢復；可再送下一輪。中止後不應有 console 例外。

- [ ] **Step 4：測試 + commit**

```bash
node --test 'fe/static/js/__tests__/*.test.mjs'
git add fe/static/js/api.js fe/static/js/main.js
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m3): disable composer while streaming + stop button (AbortController)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# M4 — 確認/取消 + 細節打磨

### Task 4.1：確認/取消快捷鈕

**Files:**
- Create: `fe/static/js/uiFormat.js`、`fe/static/js/__tests__/uiFormat.test.mjs`
- Modify: `fe/static/js/components/chat.js`、`fe/static/js/main.js`、`fe/static/css/chat.css`

- [ ] **Step 1：寫 `shouldShowConfirm` 測試（先失敗）**

`fe/static/js/__tests__/uiFormat.test.mjs`：
```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowConfirm } from '../uiFormat.js';

test('awaiting_confirmation true -> show confirm/cancel', () => {
  assert.equal(shouldShowConfirm({ awaiting_confirmation: true }), true);
});
test('otherwise hidden', () => {
  assert.equal(shouldShowConfirm({ awaiting_confirmation: false }), false);
  assert.equal(shouldShowConfirm({}), false);
  assert.equal(shouldShowConfirm(null), false);
});
```

- [ ] **Step 2：跑確認失敗** — FAIL

- [ ] **Step 3：實作 `uiFormat.js`（先放 shouldShowConfirm）**

```js
// Render-decision + formatting helpers. Pure — Node-testable.
export function shouldShowConfirm(finalData) {
  return !!(finalData && finalData.awaiting_confirmation);
}
```

- [ ] **Step 4：跑確認通過** — PASS

- [ ] **Step 5：ChatLog 確認鈕 + main.js 接線**

`chat.js` 加方法（附在當前 bot 泡泡下）：
```js
  addConfirmActions(onConfirm, onCancel) {
    const wrap = el('div', 'msg-confirm');
    const yes = el('button', 'btn msg-confirm__yes', '確認'); yes.type = 'button';
    const no  = el('button', 'btn msg-confirm__no', '取消');  no.type = 'button';
    const done = () => wrap.remove();
    yes.addEventListener('click', () => { done(); onConfirm(); });
    no.addEventListener('click',  () => { done(); onCancel(); });
    wrap.append(yes, no);
    this.root.appendChild(wrap);   // 直接掛在 .chatlog（flex 容器）下，align-self 才生效
    this._scroll();
  }
```
> ⚠️ **務必 append 到 `this.root`（即 `.chatlog`）**，不要 append 到 `lastElementChild`（會塞進 bot 泡泡內部，使 CSS `.msg-confirm{align-self:flex-start}` 失效）。`.msg-confirm` 是 chatlog 的直接 flex 子層。
`main.js` import `shouldShowConfirm`；在 `final` 收尾後：
```js
        if (shouldShowConfirm(data)) {
          chat.addConfirmActions(() => runTurn('確認'), () => runTurn('取消'));
        }
```

- [ ] **Step 6：CSS**

`chat.css` 加：
```css
.msg-confirm { display: flex; gap: var(--sp-2); align-self: flex-start; margin-top: calc(var(--sp-2) * -1); }
.msg-confirm__yes { border-color: var(--c-green); color: var(--c-green); }
.msg-confirm__no  { color: var(--c-ink-soft); }
```

- [ ] **Step 7：真瀏覽器驗收 + commit**

驗收：找車→「我要預約看第一台」→ bot 確認文字下出現「確認/取消」；點「確認」→ 送出「確認」→ 後端執行（`is_affirmative` 命中）→ 鈕消失、回「已為您完成預約」。
```bash
node --test 'fe/static/js/__tests__/*.test.mjs'
git add fe/static/js/uiFormat.js fe/static/js/__tests__/uiFormat.test.mjs fe/static/js/components/chat.js fe/static/js/main.js fe/static/css/chat.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m4): confirm/cancel quick-reply buttons for the two-stage gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 4.2：真實 per-stage 計時

**Files:** Modify `be/harness/orchestrator.py`、`fe/static/js/components/pipelineReducer.js:34-44`、`fe/static/js/components/pipeline.js:29`、`fe/static/js/uiFormat.js`、`fe/static/js/__tests__/uiFormat.test.mjs`

- [ ] **Step 1：`fmtMs` 測試（先失敗）**

於 `uiFormat.test.mjs` 加：
```js
import { fmtMs } from '../uiFormat.js';
test('sub-ms shows <1 ms, else rounded integer', () => {
  assert.equal(fmtMs(0), '<1 ms');
  assert.equal(fmtMs(0.4), '<1 ms');
  assert.equal(fmtMs(12.6), '13 ms');
  assert.equal(fmtMs(1200), '1200 ms');
  assert.equal(fmtMs(null), '');
});
```

- [ ] **Step 2：跑確認失敗 → 實作 `fmtMs`**

`uiFormat.js` 加：
```js
// Honest timing label: sub-millisecond stages read "<1 ms" instead of a fake "0 ms".
export function fmtMs(ms) {
  if (ms == null) return '';
  if (ms < 1) return '<1 ms';
  return Math.round(ms) + ' ms';
}
```
跑：`node --test fe/static/js/__tests__/uiFormat.test.mjs` → PASS

- [ ] **Step 3：後端每階段量真實耗時並 emit `elapsed_ms`**

`orchestrator.py`：在 rewrite / route / handler(or fallback) 周圍量 `time.monotonic`，把 `elapsed_ms`（float, ms）放進對應 emit 的 data。範例（rewrite）：
```python
        import time
        _t = time.monotonic()
        rw = rewrite(self.llm, self.memory, sid, user_input)
        self._emit(on_step, "rewrite", {"rewritten_query": rw["rewritten_query"],
                                        "resolved_listing_id": rw["resolved_listing_id"],
                                        "tokens": rw["tokens"],
                                        "elapsed_ms": (time.monotonic() - _t) * 1000})
```
**明確哪些階段帶 `elapsed_ms`**：`rewrite`（量 `rewrite()` 周圍，orchestrator 約 line 116）、`route`（量 `route()` 周圍，約 line 120）、`handler`/`fallback`（量 `run_handler()`/fallback `generate()` 周圍，把耗時放進該路徑 `final` event 的 data）。`guard`、`memory`、`token` 等瞬時/串流事件**不帶** `elapsed_ms` → reducer 不設 `elapsedMs` → `pipeline.js` 不渲染時間（**顯示空白，非 `<1 ms`**）。`<1 ms` 只出現在「有量到但 <1ms」的階段（FakeLLM 下 rewrite/route 即如此）。

- [ ] **Step 4：reducer 採用後端 elapsed_ms（移除假 0）**

`pipelineReducer.js` `upsert`：
- 移除 line 44 的 `if (status === 'done') step.elapsedMs = 0;`
- 改成：若 `payload.elapsed_ms != null` 用之，否則不設 `elapsedMs`：
```js
  const step = { id: id || nextId(), kind, label: labelFor(kind, payload), status, payload, _t0: Date.now() };
  if (payload && payload.elapsed_ms != null) step.elapsedMs = payload.elapsed_ms;
  if (parentId) step.parentId = parentId;
```
existing 分支（line 34-36）同樣改為優先採 `payload.elapsed_ms`：
```js
    if (status === 'done') {
      existing.elapsedMs = (payload && payload.elapsed_ms != null)
        ? payload.elapsed_ms
        : (existing.elapsedMs != null ? existing.elapsedMs : Date.now() - (existing._t0 || Date.now()));
    }
```

- [ ] **Step 5：pipeline.js 用 fmtMs 渲染**

`pipeline.js` import `fmtMs`（`import { fmtMs } from '../uiFormat.js';`），line 29 改：
```js
  if (step.elapsedMs != null) row.appendChild(el('span', 'pp-step__time', fmtMs(step.elapsedMs)));
```
footer 的總計（line 51,55）也可改用 `fmtMs(ms)`（一致）。

- [ ] **Step 6：pytest 修補（若 emit-shape 測試因新 `elapsed_ms` 欄位失敗）**

```bash
python -m pytest -q
```
若有 orchestrator emit-shape 測試對 data 做精確比對而失敗：那是我們自己的測試，誠實更新以容納新欄位（例如改成「包含」斷言或加上 elapsed_ms）。**`test_on_step_none_is_identical` 必須仍過**（on_step=None 不 emit、不量）。

- [ ] **Step 7：真瀏覽器驗收 + commit**

驗收：管線各階段顯示真實耗時或 `<1 ms`（不再一律 0 ms）；總計仍正確。
```bash
node --test 'fe/static/js/__tests__/*.test.mjs' && python -m pytest -q
git add be/harness/orchestrator.py fe/static/js/components/pipelineReducer.js fe/static/js/components/pipeline.js fe/static/js/uiFormat.js fe/static/js/__tests__/uiFormat.test.mjs
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m4): honest per-stage timing (backend elapsed_ms + <1 ms label)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 4.3：管線面板右緣裁切修正

**Files:** Modify `fe/static/css/pipeline.css:7-15`

- [ ] **Step 1：加防裁切規則**

`pipeline.css` 的 `.pp-step` 段（line 7-15）補：
```css
.pp-step { min-width: 0; }
.pp-step__label { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pp-step__time  { flex-shrink: 0; white-space: nowrap; }
```
（`.pp-step__label` 既有 `flex:1 1 auto`，補 `min-width:0` + ellipsis；面板 `.panel` 已 `overflow-y:auto`，確認有左右內距，若無則於 `.panel` 或 `.pipeline` 加 `padding: var(--sp-4)`。）

- [ ] **Step 2：真瀏覽器驗收 + commit**

驗收：「工具呼叫·條件篩選」+「8 ms ▶詳情」、總計「N ms」皆不被右緣切到；長標籤以 … 收尾。
```bash
git add fe/static/css/pipeline.css
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "fix(m4): pipeline rows no longer clip at the right edge

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 4.4：rail tooltip

**Files:** Modify `fe/templates/index.html:48-53`（若 Task 1.3 已加 `title` 則本任務僅驗收）

- [ ] **Step 1：確認/補上 `title`**

Task 1.3 範例已含 `title="…"`。若缺，為每顆 rail 按鈕補與 `aria-label` 同字的 `title`。

- [ ] **Step 2：真瀏覽器驗收 + commit（如有變更）**

驗收：hover rail 各鈕出現原生 tooltip。
```bash
git add fe/templates/index.html
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat(m4): rail button title tooltips for sighted users

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# 收尾（整合驗證 + eval 重跑 + 文件）

### Task 5.1：重跑 eval、誠實更新 report/log（M2 prompt 變更後）

**Files:** Modify `report/report.md`（§7.1–7.6）、`log.md`（新增一節）

- [ ] **Step 1：重跑全部 eval（真實 OpenAI，需 .env key）**

```bash
source .venv/bin/activate
python -m be.eval.run_full         # 27 題 → be/eval/results.json
python -m be.eval.retrieval_eval   # → be/eval/retrieval_results.json
python -m be.eval.run_sem          # → be/eval/sem_results.json
python -m be.eval.robustness_eval  # 40 題 → be/eval/robustness_results.json
```

- [ ] **Step 2：比對 prompt 變更前後**

先記 baseline（變更前的 groundedness 違規率）。重跑後：prose 不再重述**里程**（已知偽陽性來源）、但**價格仍可述**（維持 groundedness 可量測），違規率預期持平或下降。**量化退回門檻**：若違規率較 baseline **上升 > 5 個百分點** → 停、`git checkout be/harness/prompts.py` 退回原文、log 記「嘗試精簡 prompt，違規 +X pp，已退回」；否則接受新數字。並檢查 task_success 無明顯回歸。

- [ ] **Step 3：誠實更新 report §7 + log 新增一節**

report 各節對應：**§7.1–7.3 = run_full（主 27 題：router/task/groundedness/multiturn）**、**§7.4 = retrieval_eval**、**§7.5 = run_sem**、**§7.6 = robustness_eval**——逐節換成新數字。log 新增「§K UI 操作優化 + eval 重跑」記錄：本輪 M0–M4 內容、prompt 變更、各 eval 前後差異與解讀（不灌水）。

- [ ] **Step 4：commit**

```bash
git add report/report.md log.md be/eval/*.json
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "docs(eval): re-run all evals after concise-prompt change; honest report/log update

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 5.2：全功能真實瀏覽器端到端驗收 + HANDOFF 同步

- [ ] **Step 1：完整跑一輪所有 milestone**

啟動 app，依序驗收：landing 單輸入 → 查詢（文字串流出現、串流中可停止）→ 6 張卡 + 顯示更多 → 捲動順暢、composer 釘底 → 追問「預約看第一台」（無洪水車卡、出現確認/取消）→ 點確認執行 → rail SVG/tooltip → 管線真實計時、右緣不裁切 → 泡泡版面美觀。截圖留存。

- [ ] **Step 2：全測試綠**

```bash
python -m pytest -q                                  # 全綠（含凍結守門）
node --test 'fe/static/js/__tests__/*.test.mjs'      # fail 0
```

- [ ] **Step 3：更新 HANDOFF.md**（測試數、本輪摘要、分支狀態）並 commit。

### Task 5.3：收束分支

- [ ] 走 superpowers:finishing-a-development-branch（呈現 merge / PR / cleanup 選項，依使用者決定）。

---

## Self-Review（plan 對 spec 覆蓋檢查）

- spec §M0 捲動+釘底 → Task 0.1 ✓
- spec §M1 泡泡(#3)/emoji(#2)/composer/landing 單輸入 → Task 1.1–1.4 ✓
- spec §M2 gating/前6+更多/prompt精簡/prose收合 → Task 2.1–2.4 ✓
- spec §M3 token串流/增量渲染/禁用+停止 → Task 3.1–3.5 ✓
- spec §M4 確認鈕/真實計時/右緣/tooltip → Task 4.1–4.4 ✓
- spec §3 紀律（凍結守門、eval 重跑、真瀏覽器、BYOK 不入 log）→ Task 3.3 Step4、5.1、各 Step 真瀏覽器、3.5 ✓
- 命名一致：`shouldRenderDeck`/`splitDeck`/`isSubmitKey`/`composerState`/`shouldShowConfirm`/`fmtMs`/`finishAssistant`/`appendToken`/`beginAssistant` 跨任務一致 ✓
- 無 placeholder：所有 code step 皆含實際程式碼/測試/指令 ✓
