# HW4 — AI Harness 系統設計：二手重機交易平台 AI 客服

**專案代號：RideButler 騎士管家**
**課程：2026 Deep Reinforcement Learning — Homework 4（AI Harness Systems Design）**
**日期：2026-06-05**

---

## 1. 問題定義與使用情境（Problem & Use Case）

二手重機交易平台的買家有大量重複性、跨步驟的諮詢需求：尋找符合預算的車、比較車款規格、查詢交易／看車進度、處理退款與糾紛。傳統 FAQ 或關鍵字搜尋無法處理像「30 萬內想要 Yamaha 跑車，再幫我約看車」這種**多步驟、需查詢資料、需即時決策**的請求。

本系統設計一個 **AI Harness**：以大型語言模型（LLM）作為系統控制器（system controller），透過 **function calling** 串接平台資料與工具，端到端完成上述任務，並在無法處理時轉接真人客服。重點在於 **system design 思維**——LLM 如何進行 tool use 與 decision-making，而非模型訓練。

**目標使用者**：平台買家（主要）。
**典型任務**：找車推薦、規格比較問答、交易與訂單查詢、售後與轉真人。

---

## 2. 系統架構（System Architecture）

採用 **Approach B：Router + 工具迴圈（混合式 orchestration）**。相較單一 ReAct 迴圈，本方案同時展示「意圖決策（router）」與「工具使用（function-calling 迴圈）」，最能對應評分重點（Tool/Orchestration 25% + Workflow 20%），且不像完整 graph 狀態機那樣過度工程。

```
┌─────────────────────────────────────────────────────────┐
│                   Flask 聊天 UI（前端）                    │
│            對話視窗 + Decision Trace 側欄                   │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────┐
│                     Orchestrator                          │
│                                                           │
│  ① Intent Router (LLM)                                    │
│      分類使用者意圖 → {找車推薦, 規格比較, 交易訂單,        │
│                       售後轉真人, 閒聊/範圍外}             │
│                            │ 分派                          │
│  ② Domain Handler                                         │
│      掛載該領域工具子集，執行 Gemini function-calling 迴圈  │
│                            │ 呼叫                          │
│  ③ Tool Layer (8 個 function)                             │
│      操作資料層、回傳結構化結果                             │
│                            │ 讀寫                          │
│  ④ Memory                                                 │
│      對話歷史 + 使用者偏好槽（budget/brand/usage/viewed）   │
│                                                           │
│  ⑤ Escalation                                             │
│      無法處理 → create_ticket → escalate_to_human         │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                       資料層                               │
│   catalog（型錄知識庫） · listings（合成二手刊登）          │
│   orders（合成交易） · tickets（執行期建立）               │
└──────────────────────────────────────────────────────────┘
```

**LLM + Tools + Memory** 三要素齊備，符合作業對 AI system architecture 的要求。

**LLM 後端**：Google Gemini API（function calling 透過 Gemini function declarations）。使用 `google-genai` SDK，預設模型 `gemini-2.0-flash`。API key 由使用者寫入 `.env`（`GEMINI_API_KEY=...`），以 `.env.example` 提供範本，`.env` 列入 `.gitignore`。

---

## 3. 資料層（Data Layer）

型錄當作規格知識庫，並以程式合成二手刊登與交易資料。

| 資料表 | 來源 | 重要欄位 |
|---|---|---|
| `catalog` | `product_dataset.csv`（33 筆車款）| `title`(車款名), `brand`(Honda/Kawasaki/Yamaha), `description`(規格介紹), `price`(原價), `media_url`, `uri` |
| `listings` | **合成**：每個車款衍生數筆二手刊登 | `listing_id`, `model`→catalog, `year`, `mileage_km`, `condition`(A/B/C), `asking_price`, `seller`, `location`, `status` |
| `orders` | **合成**：交易/預約紀錄 | `order_id`, `listing_id`, `buyer`, `status`(預約看車/出價中/已成交/已出貨/退款中), `created_at`, `updated_at` |
| `tickets` | 執行期建立 | `ticket_id`, `category`, `description`, `status` |

**合成原則**：以固定亂數種子（seed）產生可重現的 `listings` 與 `orders`，`asking_price` 以型錄原價為基準依年份/里程/車況折舊。資料量小但足以展示所有工具與多步驟 workflow。

---

## 4. 工具設計（Tool / Function Design）

共 **8 個 function**，依四大領域分組（遠超「至少 3 個」之要求）。每個工具有明確 JSON schema（name, description, parameters），由 Gemini 以 function calling 決定何時呼叫。

| 領域 | 工具 | 簽章 | 功能 |
|---|---|---|---|
| 找車推薦 | `search_listings` | `(brand?, max_price?, year_from?, usage?)` | 篩選二手刊登（join 型錄規格），回傳符合條件清單 |
| | `recommend` | `(budget, usage, brand_pref?)` | 依預算/用途排序推薦最合適車款 |
| 規格比較 | `get_listing_detail` | `(listing_id)` | 單一刊登完整規格 + 車況資訊 |
| | `compare_models` | `(model_a, model_b)` | 兩車款並排規格/價格比較 |
| 交易訂單 | `check_order` | `(order_id 或 buyer)` | 查詢交易/出貨/退款狀態 |
| | `book_viewing` | `(listing_id, datetime, contact)` | 建立預約看車紀錄 |
| 售後轉真人 | `create_ticket` | `(category, description)` | 建立客訴/退款工單 |
| | `escalate_to_human` | `(reason)` | 轉接真人客服（handoff） |

**工具回傳**一律為結構化 JSON，含成功/錯誤狀態；錯誤時帶可讀訊息供 LLM 轉述。

---

## 5. Agent Workflow（多步驟任務執行流程）

範例請求：「30 萬內想要 Yamaha 跑車，再幫我約看車」

```
使用者輸入
  → Router 分類 = 找車推薦
  → Handler 迴圈：recommend(budget=300000, brand_pref="Yamaha", usage="sport")
      → 工具回傳 2 筆刊登 → 寫入 Memory(viewed_listings, budget, brand_pref, usage)
  → LLM 整理推薦回覆
使用者：「第一台規格如何」
  → Router = 規格比較 → get_listing_detail(listing_id) → 回覆規格 + 車況
使用者：「幫我約週六看車」
  → Router = 交易訂單 → book_viewing(listing_id, 週六, contact) → 確認預約
```

每一步產生 **decision trace**：`Router 判定 → 選用工具 → 參數 → 工具結果`。前端側欄即時顯示，報告與 evaluation 皆引用此 trace。

---

## 6. Memory 設計

- **對話記憶（conversation history）**：session 內訊息歷史，提供 LLM 上下文。
- **使用者偏好槽（profile slots）**：`budget / brand_pref / usage / viewed_listings`。由 Handler 從對話抽取並持續更新，後續工具呼叫可自動帶入（例如不必重複詢問預算）。

此即 harness「memory」要素的具體展現，使多輪互動具連續性與個人化。

---

## 7. 錯誤處理與防呆（Error Handling）

- **工具錯誤**（查無資料 / 參數不合法）→ 回傳結構化 error → LLM 轉成「請補充條件 / 換個查法」的友善回覆，流程不中斷。
- **Router 低信心 / 範圍外** → fallback 至一般回覆或主動詢問澄清。
- **Groundedness 護欄**：system prompt 嚴禁捏造規格 / 價格；所有事實必須來自工具回傳，查無即明說。
- **Escalation**：無法解決、退款糾紛、使用者明確要求真人 → `create_ticket` →（必要時）`escalate_to_human`。

---

## 8. Evaluation（評估方法）

建立 **~20–30 題測試集**（`eval/testset.json`），每題標註預期領域、預期結果與事實依據，涵蓋四大能力。

| 面向 | 衡量方式 |
|---|---|
| 工具 / 路由選擇準確率 | 每題標註 `expected_domain`，比對 Router 實際判定 |
| 任務成功率（end-to-end） | 多步任務是否正確完成（推薦在預算內、查到正確訂單） |
| 回答忠實度（groundedness） | 答案是否忠於 CSV / 刊登（規則比對價格規格 + LLM-as-judge） |
| 運營指標 | 平均回應延遲、平均工具呼叫步數、token 成本 |

`eval/run_eval.py` 跑測試集 → 輸出指標表，直接放入報告的 evaluation 段落。

---

## 9. AI Orchestration（流程控制與決策）

- **決策層**：Intent Router 以 LLM 分類意圖，決定走哪條領域路徑；領域內由 Gemini function calling 自主決定工具呼叫順序與參數。
- **控制流**：Orchestrator 串接 Router → Handler → Tools → Memory → Response，並掌管 escalation 出口。
- **可解釋性**：每次互動輸出 decision trace，確保決策過程可追蹤、可評估，符合「邏輯一致性與可解釋性」要求。

---

## 10. 交付物（Deliverables）對應

1. **書面報告（2–5 頁）**：濃縮第 1–9 段——問題定義、AI Harness 系統設計、tools 設計（8 個）、workflow / agent 流程、evaluation 方法。
2. **Infographic（資訊圖表）**：視覺化 system architecture（LLM/tools/memory）、orchestration / workflow flow、function calling / tool chain。以視覺陪伴工具設計版面後輸出 PNG。
3. **log.md**：記錄本次 AI 輔助設計與開發全程——互動紀錄、設計迭代、架構調整與決策、問題分析與修正。

---

## 11. 專案結構（Project Structure）

沿用既有 HW 慣例（Flask + templates/static + report + README）。

```
HW4/
  app.py                      # Flask 入口
  harness/
    router.py                 # Intent Router（LLM 意圖分類）
    handlers.py               # 四大領域 handler（function-calling 迴圈）
    tools.py                  # 8 個工具 function + JSON schema
    memory.py                 # 對話歷史 + 偏好槽
    orchestrator.py           # 串接各層、escalation 控制
  data/
    catalog.py                # 載入 product_dataset.csv
    listings.py               # 合成二手刊登（固定 seed）
    orders.py                 # 合成交易/預約
  eval/
    testset.json              # ~20-30 題標註測試集
    run_eval.py               # 跑測試集 + 輸出指標表
  templates/ static/          # 聊天 UI + decision trace 側欄
  report/                     # 報告 + infographic 來源
  product_dataset.csv         # 既有型錄資料
  log.md
  requirements.txt
  .env.example                # GEMINI_API_KEY 範本
  .gitignore                  # 排除 .env、.superpowers/、__pycache__
  README.md
```

---

## 12. 技術選型摘要

| 項目 | 選擇 |
|---|---|
| LLM 後端 | Google Gemini API（`google-genai`，`gemini-2.0-flash`），function calling |
| 後端框架 | Flask（可部署 Vercel） |
| 前端 | HTML/CSS/JS 聊天 UI + decision trace 側欄 |
| 資料 | pandas 載入 CSV；in-memory 合成 listings/orders |
| Orchestration | Router + 領域工具迴圈（混合式） |
| 評估 | 自建測試集 + 規則比對 + LLM-as-judge |

---

## 範圍界定（Scope）

**包含**：上述 harness 設計、Flask 可跑原型（4 領域 8 工具）、合成資料、evaluation 腳本、三項交付物。
**不包含**：模型訓練/微調、真實金流、真實使用者帳號系統、跨 session 持久化資料庫（以 in-memory 為主，可選 SQLite）。
