# log.md — AI 輔助設計與開發歷程

> RideButler 二手重機客服 AI Harness（HW4）。本檔記錄與 AI（Claude Code）協作的設計決策、迭代、架構調整與問題修正過程。對應 git 歷史可用 `git log --oneline --reverse` 對照。

---

## A. 流程總覽

採 superpowers 工作流：**brainstorming（釐清需求 → 設計 spec）→ writing-plans（TDD 實作計畫）→ subagent-driven-development（每任務派 subagent 實作 + 兩階段審查）**。

1. 腦力激盪：一次一個問題釐清 → 選定場景與技術棧 → 寫成設計 spec 並 commit。
2. 對抗式審查 spec：4 個審查員（矛盾／可行性／需求覆蓋／完整性）+ 逐條獨立驗證 → 修正 24 條。
3. 寫實作計畫（9 階段、TDD、含完整程式碼）。
4. 逐階段派 subagent 實作，每階段做 spec 合規審查 + 程式品質審查。

---

## B. 關鍵設計決策（與理由）

1. **場景：二手重機交易平台客服**，而非通用客服。理由：可重用使用者既有的真實 33 款車型錄 `product_dataset.csv`，場景具體、tool use 可展示性高。

2. **Orchestration 採 Approach B（Router + 工具迴圈）**，而非單一 ReAct 迴圈或完整 graph 狀態機。理由：同時展示「意圖決策」與「工具使用」兩種能力，最對應評分重點（Tool/Orchestration 25% + Workflow 20%），又不過度工程。決策時用視覺工具畫了 3 種方案的架構圖比較。

3. **前置 Query Rewriter 階段**（在 Router 之前）。理由：使用者輸入常口語、含指代（「第一台」「再幫我約」）。先改寫成精準、自含上下文的 query，能提升路由準確率與工具參數抽取品質。

4. **LLM 後端選 Google Gemini**（使用者指定），透過 `LLM` Protocol 抽象。理由：抽象層讓所有元件可用 scripted `FakeLLM` 離線單元測試，零 API 成本、可重現。

5. **部署採本機長駐行程而非 Vercel**。理由：審查發現 Vercel serverless 無狀態/短暫，會破壞 in-memory Memory / tickets / 跨輪指代解析。

---

## C. 與 AI 的互動／設計迭代（節錄）

**釐清階段（一次一問）**：交付範圍 → 「設計文件 + 可跑原型」；場景 → 「智能客服」→ 具體化為「二手重機平台」；資料定位 → 「型錄當知識庫 + 合成二手刊登」；能力 → 四大情境全選；原型形式 → 「Flask 可部署 web 聊天」；後端 → 先 OpenAI 後改 Gemini；evaluation → 四面向全選。

**架構迭代**（git 可見）：
- `f229185` 加入 Query Rewriter 前置階段。
- `77b9beb` 對齊標準 AI Harness：把管線對映到 **Context→Observe→Reason→Act** 迴圈，並補上原本缺的第六大元件 **Security & Governance**（使用者提供標準 AI Harness 架構圖後發現缺口）。

**使用者主導的兩次重要修正**：
- 提出「先改寫 query 再判斷情境、每情境獨立 tool 群」→ 形成 Rewriter→Router→Handler 管線與情境隔離設計。
- 提供標準 AI Harness 六大元件圖，要求檢查覆蓋度 → 補 Security & Governance + C-O-R-A 表述。

---

## D. 問題分析與修正過程

### D1. spec 對抗式審查 → 修正 24 條（commit `6a9b6ac`）
4 審查員 + 逐條獨立驗證（對照實際 spec 與真實 CSV），確認 24 條為真（剔除 2 條假陽性）。重點修正：

- **`usage`/`brand`/規格沒有資料來源**：真實 CSV 欄位是 `Title,Categories,Description,Price,...`，無結構化 brand/usage/規格欄。→ 改為：brand 由 `Categories` 解析、usage 由人工 33 款對照表標註、specs 由 `Description`【規格】容錯解析，缺值標「資料未提供」。
- **Vercel 無狀態 vs in-memory 狀態**：→ 改本機長駐行程。
- **Evaluation 無門檻/判準**：→ 補題數配額、通過門檻、judge rubric、可驗證 end-to-end 述詞、token 累加。
- **Router 第 5 類無 handler**：→ 明定為無工具 fallback。
- **複合請求次意圖被丟棄**：→ 多意圖延後策略（`pending_intent`）。
- **狀態變更工具確認步驟未定義且與範例矛盾**：→ 兩階段確認閘。
- 另補 **function-calling round-trip 機制說明**（作業必含項，原本只點名未說明）。

### D2. 實作期 subagent 找到的真實程式缺陷（TDD + 審查攔截）
- **規格解析器 split bug**（Phase 1）：`re.split(r"[:：]", line, maxsplit=1)` 只回 2 段卻解包成 3 個變數 → ValueError。修正用 capturing group `r"([:：])"`（`5dfcec2` 同批）。
- **型錄標題截斷**（Phase 1）：`AFRICA TWIN ADVENTURE SPORTS ES` 實際 CSV 為 `...ES DCT`，靜默 fallback 成 naked。→ 修正標題 + 加「無 title 靜默 fallback」防護測試（`5dfcec2`）。
- **Orchestrator 傳錯 store**（Phase 6）：`rewrite()` 需要 `SessionStore`（有 `.get`/`.resolve_reference`），但 plan 寫成傳 `DataStore` → AttributeError。修正 `self.store`→`self.memory`（`e99a546`）。審查並逐一驗證兩輪確認閘「只執行一次、確認輪零 LLM 呼叫」。
- **Evaluation 配額不足**（Phase 8）：spec 要求 out-of-scope/injection ≥3 但測試集只有 2。→ 補 1 題 + 收緊斷言（`a022146`）。

每次修正後皆回頭同步 plan 文件，使「spec ↔ plan ↔ code」三者一致。

---

## E. 成果

- **62 個單元測試全綠**（全程 FakeLLM，離線、零 API 成本、可重現）。
- 完整 harness：資料層 → 8 工具 → memory/governance → rewriter/router/handler/orchestrator → Flask 聊天 UI + Decision Trace 側欄 → evaluation（27 題）。
- 三項交付物：書面報告、infographic、本 log.md。
- 每階段經兩階段審查（spec 合規 + 程式品質）通過後才進入下一階段。
