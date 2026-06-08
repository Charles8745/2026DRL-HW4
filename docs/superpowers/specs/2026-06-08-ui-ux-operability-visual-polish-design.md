# Spec — UI 操作優化：操作性修復 + 視覺質感

- 日期：2026-06-08
- 狀態：核准，待 writing-plans
- 背景：上一輪把 UI 重新設計成「SSE 即時管線 + BYOK + 風格 C」（已合併、HEAD `8cdbeca`）。本輪用**真實瀏覽器**（chrome-devtools 端到端，非 headless）親自操作一輪 landing→查詢→管線→車卡→多輪→確認閘，量到一個**致命操作性 bug** 與多個體驗痛點，並由使用者追加 4 個視覺/互動痛點。本 spec 聚焦**操作體驗 + 視覺質感**的打磨。
- 範圍決策（使用者選定）：
  1. 結果呈現 = **卡片為主 + 一句話摘要**（前 6 張 + 顯示更多；追問/確認不附車卡）。
  2. 風險邊界 = **開放動 prompt/後端求最佳 UX**（接受重跑/重審 eval）。
  3. 本輪 P0–P3 全包，外加使用者追加 4 點：文字串流輸出、rail emoji 換圖示、對話泡泡版面重整、composer 釘底。

---

## 1. 目標

1. **可用**：修好聊天區捲動（目前根本捲不動），讓回答/車卡/多輪都看得到、composer 釘在底部固定列。
2. **不洪流**：推薦只在找車/比較情境出車卡、預設 6 張可展開、文字只給 1–2 句摘要不重述卡片規格；追問/確認類不再灌一副不相關車卡。
3. **質感**：對話泡泡限寬留白排版、rail 改乾淨 SVG 圖示、文字回覆 token 串流輸出、串流中可禁用/中止、確認閘出「確認/取消」鈕、管線真實計時。
4. **不灌水**：凍結 testset/守門測試不動；唯一動 eval 數字處（M2 prompt 精簡）誠實重跑並更新 report/log。

---

## 2. 現況實測（真實瀏覽器，佐證）

查詢「30萬內適合新手通勤的省油檔車」→ 18 張車卡 + 一段重述前 3 名規格的冗長文字；追問「我要預約看第一台」→ 確認 prose **又附 13 張不相關車卡**。量測：

- **捲動**：聊天內容 5893px，但整頁 `maxScrollY = 37px`；真實滾輪事件（連續 3000px 意圖）完全無效；可見車卡數 = 0；做完第二輪後畫面仍卡在第一輪頂端。
- 先前「real-browser 驗證過」很可能用短回答/少車卡查詢，剛好沒踩到。

---

## 3. 跨里程碑紀律

- **凍結不動**：`be/eval/testset.json`(27)、`robustness_testset.json`(40)、`retrieval_testset.json`(16)、`sem_testset.json`(4) 的題數/內容與所有 `test_*_frozen` 守門測試一律不改。
- **唯一動 eval 數字 = M2 的 prompt 精簡**：完工後重跑 `run_full` / `retrieval_eval` / `run_sem` / `robustness_eval`，誠實更新 report §7.1–7.6，並在 log 新增一節記錄前後差異與原因。
- **串流不影響 eval**：eval 與 `/api/chat` 走**非串流**路徑（直呼 orchestrator），保留不動；只在 SSE 串流路徑加 token 串流。
- **每個 milestone**：純函式 `node --test` + **真實瀏覽器驗收**（依 memory `real-browser-verify-multimilestone-frontend`：headless 抓不到整合 bug；boot 接線、header round-trip、CSS link、token 命名都要在真瀏覽器確認）。
- **既有 242 Python 測試 + JS 純邏輯套件全程綠**；BYOK key 不入 log 的紀律延續（串流路徑同樣 redact、finally 必收尾）。
- 分支 `feat/ui-ux-operability`，逐 milestone commit；commit 結尾 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`；git 身分 `git -c user.name="Charles" -c user.email="charles@j-tcg.com"`；最後走 finishing-a-development-branch。

---

## 4. 里程碑與確切改點

> 行號為現況快照（探索代理 read-only 定位），實作時以實際檔案為準。

### M0 — 捲動修復 + composer 釘底（P0 + 追加 #4，CSS 為主）

**根因**：`fe/static/css/layout.css:5-11` 的 `#app` 是 `height:100vh; overflow:hidden` 的 grid；`.center`(`:15`) 與 `.view-chat`(`:27`) 是 flex column 且 `min-height:0`，但 `.chatlog` **完全沒有 flex/overflow 規則**（`fe/templates/index.html:68-70` 只有 class，CSS 無對應 rule）→ 內容溢出但無人提供捲動。

**改動**：
- `layout.css` 新增：`.chatlog { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: var(--sp-3); padding: var(--sp-4); }`（`display:flex` + `gap` + `padding` 一併在 M0 加上：M1 Task 1.2 的訊息泡泡靠 `align-self` 左右對齊，需父層是 flex 容器；間距/內距也讓 M0 當下就可讀）。
- `.composer { flex: 0 0 auto; }`（釘成底部固定列、不被壓縮、不隨內容捲走；視覺上 `border-top` + surface 背景與 chatlog 區隔）。
- `fe/static/js/components/chat.js` 的 `_scroll()`：確認對 `.chatlog`（現在才是 scroller）做 `scrollTop = scrollHeight`；若原本指錯元素則修正。

**驗收（真瀏覽器）**：18 張車卡回答可滾輪捲到最後一張（`cardsVisible>0`）；新訊息自動捲到底；composer 永遠可見在底部；`maxScrollY` 反映真實內容高度。

---

### M1 — 聊天版面與視覺重整（追加 #3 + #2 + composer 結構）

實作走 **frontend-design** skill 把關質感；此 milestone settle 後續要疊串流的 DOM/CSS 結構。

1. **對話泡泡重排（#3）** — `fe/static/js/components/chat.js`（現 56 行，`addUser`/`addAssistant`）+ `fe/static/css/chat.css`：
   - user 訊息：右對齊、限寬泡泡（非現在的滿欄綠 bar）；bot 訊息：左對齊、限寬、留白、role 區隔。
   - bot 文字內容限**可讀寬度**（如 ~680px）；車卡 `.listing-deck` 可用較寬區域。
2. **rail emoji → SVG 圖示（#2）** — `fe/templates/index.html:46-54` 的 `＋💬📊？🔑` 換成內嵌單色 **SVG**（對齊 design tokens 顏色/尺寸）；`fe/static/css/layout.css:48-55` `.rail__btn` 配合調整。保留既有 `aria-label`/`aria-pressed`。
3. **composer 改自動增高 textarea** — `index.html:73-77` 的 `<input>` → `<textarea>`（1→約 5 行自動增高、滿欄寬、加大點擊區）；`main.js:134-146` `wireComposer`：**Enter 送出 / Shift+Enter 換行**、送出後**焦點回 textarea**。抽鍵盤決策純函式（`isSubmitKey(e)`）測試。
4. **landing 收成單一輸入** — `layout.css` 加 `#app[data-view="landing"] .composer { display:none }`：首頁只留中央 `.landing__pill`，送出切到 chat view 才出現 composer。

**驗收**：泡泡限寬/對齊/留白美觀（截圖給使用者）；rail 為乾淨圖示無 emoji；composer 多行、Enter 送出、焦點回輸入框；landing 單一輸入。

---

### M2 — 結果呈現：卡片為主 + 一句話摘要（原 M1）

1. **意圖 gating（FE-only）** — `fe/static/js/main.js:21-36`(`extractRows`)/`:92-95`(`final` 處理)：只有 `data.router_label ∈ {找車推薦, 規格比較}` 才取 rows 傳 deck，其餘傳 `null` → 不渲染車卡。`router_label` 已在 `final` event（`orchestrator.py:199-201`）。抽 `shouldRenderDeck(label)` 純函式測試。
2. **前 6 張 + 顯示更多（FE-only）** — `fe/static/js/components/listingCard.js:129-139`(`renderDeck`) 加 `maxShown=6`：前 6 張顯示、其餘收在「顯示更多（N）」按鈕後。抽 `splitDeck(rows, n)→{shown,hidden}` 純函式測試。
3. **prompt 精簡（動後端，影響 eval）** — `be/harness/prompts.py:13-24` 的 `_HANDLER_BASE`/找車推薦 hint 加指引：「若有推薦車輛，僅以 1–2 句總結選擇理由，**不要逐台重述卡片上已顯示的規格與里程**（價格可自然帶到）」。加 Python 斷言 `handler_sys('找車推薦')` 含此指引。
4. **prose 安全收合（FE-only）** — prose 過長（> ~6 行）時 clamp + 「展開」。即使 prompt 已精簡仍保險。

**eval 風險與對策**：groundedness 計分器（`be/eval/run_eval.py:14-16` `_facts_from_trace`）**只白名單價格**。因此：
- **刻意保留「價格可自然帶到」**：若叫模型連價格都不提，groundedness 會變成「無事實可驗」的空泛通過（等於不誠實拉高分數）；保留價格 → groundedness 仍實際量測價格 grounding。
- **叫模型別重述里程**：里程（5 位數）非白名單、是**已知偽陽性來源**（現況里程會被誤判違規），不重述里程預期**降低違規率（合理、非灌水）**。
- **量化退回門檻**：改完先量 baseline → 重跑。若 groundedness 違規率較 baseline **上升 > 5 個百分點**：停、退回 prompts.py 原文、log 記「嘗試精簡 prompt，違規上升 X%，已退回」。否則接受新數字並更新 report/log。全部誠實記錄。

**驗收**：找車 → 1–2 句摘要 + 6 張卡 + 顯示更多；約看/確認/閒聊 → 無車卡；eval 重跑數字入 report/log。

---

### M3 — 文字串流輸出（追加 #1）+ 串流互動

1. **後端最終回覆 token 串流** — `be/harness/openai_client.py` 最終 completion（無更多 tool call 的那次）改支援 `stream=True` 逐 token 產出；orchestrator/handler 把 token 經 `fe/streaming.py` 的 StreamRunner 以新 SSE `token` frame 發出（接續既有 stage events，`final` 仍送完整 reply 收尾以相容）。
2. **FE 增量渲染** — `main.js`/`chat.js`：收 `token` event 增量寫入「當前 bot 泡泡」；`final` 收尾（定稿文字 + 依 gating 掛車卡）。pipelineReducer 視需要加 `token` 處理。
3. **串流中禁用 + 可停止** — 串流期間禁用 composer；送出鈕變「停止」→ `fe/static/js/api.js:51-85` `stream()` 改用 `AbortController` 並開 `abort()`；後端 StreamRunner 在斷線（`GeneratorExit`）即取消（`streaming.py:83-90` 已具備）。抽串流狀態→禁用/按鈕文字純函式測試。

**安全/穩定**：串流中錯誤、中止、逾時都要 finally 收尾（既有 `streaming.py` 已 emit `error?`+`done`）；BYOK key 不入 log 延續；**保留非串流路徑**供 eval/`/api/chat`。

**驗收**：文字逐字串流出現；串流中 composer 禁用且「停止」可中止（畫面停、後端取消）；中止/錯誤後 composer 恢復；eval/`/api/chat` 行為不變。

---

### M4 — 確認/取消 + 細節打磨（原 M2 確認鈕 + 原 M3）

1. **確認/取消快捷鈕（幾乎 FE-only）** — `final` event 已帶 `awaiting_confirmation`（`orchestrator.py:199-201`、`api.js:94`）；為 true 時在該則 bot 訊息下渲染「確認」「取消」鈕，點擊送出對應字（後端 `is_affirmative` 已處理）；本輪解決後鈕消失/禁用。抽決策純函式測試。
2. **真實 per-stage 計時** — 移除 `fe/static/js/components/pipelineReducer.js:44` 的 `step.elapsedMs = 0`（假值）；`be/harness/orchestrator.py` 每階段量 `time.monotonic` 差，隨 step event 發 `elapsed_ms`（float）；`pipeline.js:29` 改用後端值。抽 `fmtMs(x)`（`<1 ms` / 四捨五入）純函式測試。
3. **管線面板右緣裁切（FE-only CSS）** — `fe/static/css/pipeline.css:6-15`：`.pp-step{min-width:0}`、`.pp-step__label{min-width:0;overflow:hidden;text-overflow:ellipsis}`、`.pp-step__time{flex-shrink:0;white-space:nowrap}` + 面板內距。
4. **rail tooltip（FE-only）** — `index.html:46-54` rail 按鈕加 `title`（對齊既有 aria-label），滑鼠族 hover 看得到。

**驗收**：約看 → 出現確認/取消 → 點確認真的執行；階段顯示誠實計時（或 `<1 ms`）；右緣不被切；hover 出 tooltip。

---

## 5. 測試策略

- **新增純函式 `node --test`**（`fe/static/js/__tests__/`）：`isSubmitKey`、`shouldRenderDeck`、`splitDeck`、串流狀態→禁用/按鈕、確認 UI 決策、`fmtMs`。
- **Python**：prompt 指引存在性斷言；既有 242 測試與凍結守門全綠（含 `test_on_step_none_is_identical`、各 `test_*_frozen`）。
- **真實瀏覽器（每 milestone 收尾）**：捲動 + composer 釘底、泡泡版面、rail 圖示、composer 多行/Enter/焦點、landing 單輸入、gating、6+顯示更多、文字串流、串流中止、確認鈕、計時、無裁切、tooltip。
- **eval 重跑**：M2 後 `run_full`/`retrieval_eval`/`run_sem`/`robustness_eval`，誠實更新 report §7 + log。

---

## 6. 不做（YAGNI）

- 不做「結果搬到獨立可篩選面板 / 比較托盤 / 收藏」等大改版（方案 C，延後）。
- 不做串流「重試」按鈕（先做禁用 + 中止即可）。
- 不動檢索演算法、不改凍結 testset、不持久化向量索引。
- 不為了拉高分數改共用 groundedness 計分器（凍結基線）。

---

## 7. 交付

- 程式：M0–M4 改動，分支 `feat/ui-ux-operability`。
- 文件：report §7 更新（M2 後誠實數字）、log 新增一節記錄本輪與 eval 前後差異、HANDOFF 同步。
- 驗證：每 milestone 真實瀏覽器截圖 + node/pytest 綠。
