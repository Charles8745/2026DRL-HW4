# 二手重機交易平台 AI 客服 Harness — 系統設計報告

**RideButler 騎士管家**｜2026 Deep Reinforcement Learning HW4（AI Harness Systems Design）｜2026-06-05

---

## 1. 問題定義與應用背景

二手重機交易平台的買家有大量重複性、跨步驟的諮詢：找符合預算的車、比較車款規格、查詢交易／看車進度、處理退款糾紛。傳統 FAQ 或關鍵字搜尋無法處理像「30 萬內想要 Yamaha 跑車，再幫我約看車」這種**多步驟、需查資料、需即時決策**的請求。

本系統設計一個 **AI Harness**：以大型語言模型（LLM, 採 Google Gemini）作為**系統控制器**，透過 **function calling** 串接平台資料與工具，端到端完成上述任務，無法處理時轉接真人。重點在於 **system design 思維**——AI 如何進行 tool use 與 decision-making——而非模型訓練。目標使用者為平台買家，典型任務為四類：找車推薦、規格比較問答、交易與訂單查詢、售後與轉真人。

## 2. AI Harness 系統設計

採 **Approach B：Router + 工具迴圈（混合式 orchestration）**——相較單一 ReAct 迴圈，同時展示「意圖決策（router）」與「工具使用（function-calling 迴圈）」，又不像完整 graph 狀態機那樣過度工程。

```
使用者輸入
  → ① Query Rewriter (LLM)     改寫精準化、解析指代「第一台」、偵測多意圖
  → ② Intent Router (LLM)      5 類意圖分類（4 情境 + 無工具 fallback）
  → ③ Domain Handler           該情境專屬 tool group，manual function-calling 迴圈
  → ④ Tool Layer (8 function)  操作 DataStore，回傳結構化 JSON
  ⑤ Memory：session 對話歷史 + 偏好槽（budget/brand_pref/usage/viewed_listings/pending_*）
  ⑥ Security & Governance：輸入/輸出防護、兩階段確認、單輪限額、稽核（橫切所有階段）
```

本設計對齊標準 AI Harness 的**六大元件**：

| 標準元件 | 本系統實作 |
|---|---|
| **Prompt** | 分層 system prompt（rewriter / router / 各情境 handler / fallback），集中於 `prompts.py` |
| **Orchestration** | `Orchestrator` 串接 + `Intent Router` 決策 |
| **核心迴圈 Context→Observe→Reason→Act** | Rewriter+Memory 組裝上下文 → Router 觀察分類 → Handler 推理選工具 → 執行工具/回覆 |
| **Tools & Skills** | 8 個 function，分 4 領域 tool group |
| **Memory** | session-keyed 對話歷史 + 偏好槽 |
| **Security & Governance** | `governance.py` + orchestrator 治理鉤子 |

**資料層**：型錄為**真實 33 款車**（`product_dataset.csv`，欄位 `Title/Categories/Description/Price/...`）。載入時轉成正規化 `catalog`：`brand` 由 `Categories` 解析、`usage`（sport/naked/touring/adventure/scooter/cruiser）由人工維護的 33 款對照表標註、`specs` 由 `Description`【規格】區塊容錯解析。二手 `listings` 與 `orders` 以固定 seed 合成、折舊單調並設上下限、`model` 對型錄採精確字串 join。

## 3. Function Calling / Tool Usage 機制

系統採 **manual function-call 迴圈**（關閉 SDK 自動代呼），以便逐步攔截、產生 decision trace、執行單輪工具上限。一輪往返：

1. **送出**：app 把該情境 tool group 的 **function declarations**（每工具 `name`/`description`/`parameters` 之 JSON schema）連同對話與 system prompt 送入 Gemini。
2. **模型決策**：Gemini 回傳**結構化 `function_call(name, args)`**（非自然語言），代表它決定呼叫哪個工具、帶什麼參數。
3. **執行**：app 攔截並 dispatch 到對應 Python 工具實際執行。
4. **回填**：工具結果包成 **`function_response`(JSON)** 餵回模型。
5. **續推理**：模型續寫——可再 emit 下一個 `function_call`（單輪多次往返），或產生最終回覆。

**終止條件**：模型不再 emit `function_call`，或達單輪工具上限 / token 預算。程式上由 `harness/handlers.py:run_handler` 實作此迴圈，`harness/llm.py` 定義 `ToolCall`/`LLMResponse` 與 `LLM` Protocol，`gemini_client.py` 解析回應的 `function_call` parts 與 `usage_metadata`。

## 4. Tools 設計（8 個，分 4 領域）

| 領域 | 工具 | 簽章 | 功能 |
|---|---|---|---|
| 找車推薦 | `search_listings` | `(brand_pref?, max_price?, year_from?, usage?)` | 篩選在售刊登（join 型錄 usage/specs） |
| | `recommend` | `(budget, usage?, brand_pref?)` | 依預算/車種排序推薦 |
| 規格比較 | `get_listing_detail` | `(listing_id)` | 單一刊登完整規格＋車況 |
| | `compare_models` | `(model_a, model_b)` | 並排比較；缺值顯示「資料未提供」 |
| 交易訂單 | `check_order` | `(order_id? / buyer?)` | 查交易/出貨/退款狀態 |
| | `book_viewing` ⚠ | `(listing_id, datetime, contact)` | 建立預約看車（**狀態變更**） |
| 售後轉真人 | `create_ticket` ⚠ | `(category, description)` | 建立客訴/退款工單（**狀態變更**） |
| | `escalate_to_human` ⚠ | `(reason)` | 轉接真人（**狀態變更**） |

每個工具回傳統一的 `{"ok", "data", "error"}` 結構化封包；⚠ 標記者經兩階段確認閘。

## 5. Agent Workflow（多步驟任務）

以「30 萬內想要 Yamaha 跑車，再幫我約看車」為例：

```
T1 使用者：30萬內 Yamaha 跑車，再幫我約看車
   Rewriter 偵測雙意圖 → 主「找車推薦」、次「約看車」存 pending_intent
   Router=找車推薦 → recommend(300000,"sport","Yamaha") → 2 筆 → 寫入 viewed_listings(有序)
   回覆推薦 + 主動提示「選定後可預約看車」
T2 使用者：第一台規格如何
   Rewriter 讀 Memory 解析「第一台」→ viewed_listings[0]=L001
   Router=規格比較 → get_listing_detail("L001") → 回覆規格+車況
T3 使用者：幫我約週六看車
   Router=交易訂單 → 擬呼叫 book_viewing → 確認閘：「要為您預約 L001 本週六看車，確認嗎？」（暫停）
T4 使用者：確認 → 實際執行 book_viewing → 建立預約
```

**多意圖策略**：單輪處理主意圖、次意圖延後（`pending_intent`），不靜默丟棄。每步輸出結構化 **decision trace**（`raw_input / rewritten_query / router_label / 工具步驟 / tokens`），前端側欄即時顯示，亦作 audit log。

## 6. 錯誤處理與安全治理

- **工具錯誤**（查無/參數不合法）回傳結構化 error，LLM 轉成友善澄清，流程不中斷。
- **Router 低信心/範圍外** → 無工具 fallback 一般回覆或澄清。
- **Groundedness 護欄**：價格/規格/車況須來自工具回傳；型錄缺值（如 ZX-10R 馬力）標「資料未提供」，不捏造（`compare_models` sentinel + system prompt 規則）。
- **輸入防護**：偵測 prompt-injection（「忽略前述指示…」）於任何 LLM 呼叫前攔截。
- **兩階段確認閘**：狀態變更工具先回確認摘要、暫停、使用者同意才執行（避免誤觸發）。
- **單輪限額**：`TurnBudget` 限制單輪工具呼叫次數，防迴圈失控。
- **治理出口**：無法安全處理 → `escalate_to_human`。

## 7. Evaluation 方法

自建 **27 題標註測試集**（`eval/testset.json`），分布：找車/規格/交易/售後 各 ≥5、跨步驟多工具 ≥4、out-of-scope/injection ≥3。`eval/run_eval.py` 對每指標輸出數值與 **PASS/FAIL（對門檻）**：

| 面向 | 衡量方式 | 門檻 |
|---|---|---|
| 路由選擇準確率 | 5 類分類；fallback/低信心僅當 gold=`閒聊範圍外` 算對 | ≥ 90% |
| 任務成功率（end-to-end） | 呼叫了預期工具且參數正確 **且** 答案含正確事實 | ≥ 85% |
| 回答忠實度（groundedness） | 規則比對價格/規格為主且權威；LLM-as-judge 為輔 | 違規數 = 0 |
| 運營指標 | 平均延遲；平均工具步數；**每輪總 token＝累加該輪所有 Gemini 呼叫** | 在預算內 |

> **量測結果**：本報告交付時測試以離線 `FakeLLM` 驗證系統邏輯（62 個單元測試全綠、零 API 成本）。對真實 Gemini 的端到端指標由 `python -m eval.run_eval` 產生；執行後將輸出表貼於此（router_accuracy / task_success / avg_latency / avg_tokens / PASS）。

## 8. 結論

本系統以 LLM 為控制器、function calling 為手段，完整實作標準 AI Harness 六大元件，並以情境隔離、兩階段確認、groundedness 護欄與結構化稽核確保**邏輯一致性與可解釋性**。所有 LLM 存取經 `LLM` Protocol 抽象，使整個 harness 可離線、可重現地單元測試（62 tests），是一個兼顧設計完整性與工程可驗證性的 AI 系統設計範例。

*附：系統架構與 tool-chain 視覺化見 `report/infographic.html`／`infographic.png`；完整規格見 `docs/superpowers/specs/`；設計與開發歷程見 `log.md`。*
