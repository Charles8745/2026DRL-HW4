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
│  ① Query Rewriter (LLM)                                   │
│      改寫使用者輸入：消歧義、補上下文、解析指代            │
│      （例「第一台」→ listing_id），輸出精準化 query        │
│                            │ 精準化 query                  │
│  ② Intent Router (LLM)                                    │
│      （精準化 query + 情境判斷 system prompt）              │
│      分類意圖 → {找車推薦, 規格比較, 交易訂單,             │
│                 售後轉真人, 閒聊/範圍外}                   │
│                            │ 分派（各情境獨立）            │
│  ③ Domain Handler ── 核心迴圈 ──┐                         │
│      掛載該情境專屬 tool group   │ Observe→Reason→Act      │
│      執行 OpenAI function loop   └──↺ 未完成則續迴圈        │
│                            │ 呼叫                          │
│  ④ Tool Layer (8 個 function，分屬 4 個 tool group)       │
│      操作資料層、回傳結構化結果                             │
│                            │ 讀寫                          │
│  ⑤ Memory                                                 │
│      對話歷史 + 使用者偏好槽（slot 名定義見 §6）          │
│      ← Query Rewriter 讀此記憶以解析指代與補上下文          │
│                                                           │
│  ⑥ Escalation                                             │
│      無法處理 → create_ticket → escalate_to_human         │
│                                                           │
│  ╔═══════════════════════════════════════════════════╗   │
│  ║ Security & Governance（橫切所有階段）              ║   │
│  ║ 輸入防護 · 輸出 groundedness · 工具授權 · 稽核 · 限額 ║   │
│  ╚═══════════════════════════════════════════════════╝   │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                       資料層                               │
│   catalog（型錄知識庫） · listings（合成二手刊登）          │
│   orders（合成交易） · tickets（執行期建立）               │
└──────────────────────────────────────────────────────────┘
```

**處理管線（pipeline）**：每則使用者輸入依序經過 ① Query Rewriter → ② Intent Router → ③ Domain Handler（含 ④ Tool Layer 迴圈），全程讀寫 ⑤ Memory，必要時走 ⑥ Escalation。

**為何先做 Query Rewriter**：使用者輸入常口語、模糊或含指代（「那台」「再幫我約」）。先用 LLM 結合對話記憶把 query 改寫成完整、明確、自含上下文的版本，可（a）大幅提升 Router 的情境分類準確率，（b）讓 Handler 抽取工具參數更精準。改寫後的 query 再搭配「情境判斷 system prompt」交給 Router。

**情境獨立（domain isolation）**：四大情境彼此獨立，各自擁有專屬的 tool group 與 system prompt；Handler 只會看到該情境的工具子集，降低誤用工具的機率，也讓每個情境可獨立測試與擴充。

**第 5 類 = 無工具 fallback**：Router 共輸出 5 類，其中前 4 類對應四大情境（各有專屬 tool group）；第 5 類「閒聊／範圍外」是**無工具的 fallback path**（空 tool group + 輕量 system prompt），依 §7 走一般回覆或主動詢問澄清，**不是**第五個 domain。評估時（§9）亦把它當一個可標註的分類。

### 2.1 核心迴圈：Context → Observe → Reason → Act

本系統對齊標準 AI Harness 的核心 agent 迴圈。Domain Handler 內部即是此迴圈的具體實作：

| 迴圈階段 | 本系統對應 | 說明 |
|---|---|---|
| **Context** | Query Rewriter + Memory + 情境 system prompt | 組裝本輪上下文：改寫後的精準 query、使用者偏好槽、該情境提示 |
| **Observe** | Router 分類 + 觀察工具回傳 | 觀察當前狀態：分類意圖、讀取上一輪工具結果 |
| **Reason** | Handler LLM（OpenAI function calling）| 推理「該呼叫哪個工具、帶什麼參數」或是否已可作答 |
| **Act** | 執行工具呼叫 / 產生回覆 | 呼叫工具改變狀態或回覆使用者；若任務未完成則回到 Observe |

迴圈持續到任務完成或觸發 escalation。每一圈都產生 decision trace。

### 2.2 對齊標準 AI Harness 六大元件

| 標準元件 | 本系統實作 |
|---|---|
| **Prompt** | Rewriter / Router / 各情境 Handler 的 system prompt（見 §2.3） |
| **Orchestration** | Orchestrator + Intent Router（§10） |
| **核心迴圈** | Context → Observe → Reason → Act（§2.1） |
| **Tools & Skills** | 8 工具 / 4 領域 tool group + 1 無工具 fallback（§4） |
| **Memory** | 對話歷史 + 偏好槽（§6） |
| **Security & Governance** | 輸入/輸出防護、工具授權、稽核、限額（§8） |

### 2.3 Prompt 層

系統以分層 prompt 驅動：（a）**Rewriter prompt**——改寫精準化與指代解析；（b）**Router prompt**——情境判斷與分類；（c）**情境 Handler prompt**——各情境的角色設定、可用工具說明、groundedness 與治理規則。Prompt 為一級設計物件，集中管理便於迭代與評估。

**LLM + Tools + Memory + Security/Governance** 元件齊備，符合作業對 AI system architecture 的要求。

**LLM 後端**：OpenAI API（function calling 透過 tool/function schemas (OpenAI tools)）。使用 `openai` SDK，預設模型 `gpt-4.1-mini`。API key 由使用者寫入 `.env`（`OPENAI_API_KEY=...`），以 `.env.example` 提供範本，`.env` 列入 `.gitignore`。

---

## 3. 資料層（Data Layer）

型錄當作規格知識庫，並以程式合成二手刊登與交易資料。資料層在載入時把原始 CSV **轉成正規化的邏輯表**（非 1:1 複製）。

**原始 CSV schema**：`product_dataset.csv` 實際欄位為 `Title, Categories, Description, Price, Media_url, Uri`（33 筆）。`Categories` 內容僅為「機車, <品牌>」，`Description` 為含【規格】區塊的自由文字，**沒有結構化的規格或車種欄位**。

| 邏輯表 | 來源 | 重要欄位 |
|---|---|---|
| `catalog` | 由 CSV 載入＋轉換（`data/catalog.py`）| `title`(←Title), `brand`(由 `Categories` 切出), `usage`(車種分類，見下), `price`(←Price 純數字), `specs`(由 `Description`【規格】解析的結構化欄位), `description`(←Description 原文), `media_url`, `uri` |
| `listings` | **合成**：每個車款衍生數筆二手刊登 | `listing_id`, `model`→catalog.title（精確字串 join）, `year`, `mileage_km`, `condition`(A/B/C), `asking_price`, `seller`, `location`, `status` |
| `orders` | **合成**：交易/預約紀錄 | `order_id`, `listing_id`, `buyer`, `status`(預約看車/出價中/已成交/已出貨/退款中), `created_at`, `updated_at` |
| `tickets` | 執行期建立 | `ticket_id`, `category`, `description`, `status` |

**衍生欄位來源（避免無中生有，呼應 §8 groundedness）**：
- **`brand`**：由 `Categories`（"機車, <品牌>"）以逗號切出，值為 Honda / Kawasaki / Yamaha。
- **`usage`（車種：sport / naked / touring / adventure / scooter / cruiser）**：CSV 無此欄，由 `data/catalog.py` 以**人工維護的 33 款 model→usage 對照表**標註（比關鍵字規則可靠），作為 `search_listings`／`recommend` 的 `usage` 篩選與 §6 偏好槽的**權威來源**。
- **`specs`**：由 `Description`【規格】區塊以**容錯解析器**抽出並正規化鍵名/單位（排氣量/總排氣量→`displacement_cc`、ps/PS/馬力→`horsepower`、Nm/kg-m→`torque`、座高/乾重等）。**缺值（如 ZX-10R 無馬力欄）以 sentinel 標為「資料未提供」**，不捏造也不靜默省略，使 `compare_models` 與 §7/§8 護欄誠實。

**合成原則**：以固定亂數種子（seed）產生可重現的 `listings`／`orders`。折舊公式 `asking_price = max(floor, 原價 × 年份係數 × 里程係數 × 車況係數)`，**單調**（年份越舊／里程越高／車況越差 → 價不升）、設下限 `floor` 避免荒謬低價、上限不超過原價。`listings.model` 對 `catalog.title` 採**精確字串** join（型錄含近似標題如 `MT-07` vs `MT-07 Y-AMT`、含括號代碼 `Z 650 (ER650-S)`，禁用模糊比對以免錯接規格）。資料量小但足以展示所有工具與多步驟 workflow。

---

## 4. 工具設計（Tool / Function Design）

共 **8 個 function**，依四大領域分組（遠超「至少 3 個」之要求）。每個工具有明確 JSON schema（name, description, parameters），由 OpenAI 以 function calling 決定何時呼叫。

| 領域 | 工具 | 簽章 | 功能 |
|---|---|---|---|
| 找車推薦 | `search_listings` | `(brand_pref?, max_price?, year_from?, usage?)` | 篩選二手刊登（join `catalog` 的 `usage`/`specs`），回傳符合條件清單 |
| | `recommend` | `(budget, usage, brand_pref?)` | 依預算/用途排序推薦最合適車款 |
| 規格比較 | `get_listing_detail` | `(listing_id)` | 單一刊登完整規格 + 車況資訊 |
| | `compare_models` | `(model_a, model_b)` | 兩車款並排比較（讀 `catalog.specs` 正規化欄位；缺值顯示「資料未提供」）|
| 交易訂單 | `check_order` | `(order_id 或 buyer)` | 查詢交易/出貨/退款狀態 |
| | `book_viewing` | `(listing_id, datetime, contact)` | 建立預約看車紀錄 |
| 售後轉真人 | `create_ticket` | `(category, description)` | 建立客訴/退款工單 |
| | `escalate_to_human` | `(reason)` | 轉接真人客服（handoff） |

**工具回傳**一律為結構化 JSON，含成功/錯誤狀態；錯誤時帶可讀訊息供 LLM 轉述。

### 4.1 Function-calling 機制（round-trip protocol）

本系統採 **manual function-call 迴圈**（關閉 SDK 自動代呼），以便每步攔截、產生 decision trace、並執行 §8 單輪工具上限。一輪的往返流程：

1. **送出**：app 把該情境 tool group 的 **tool/function schemas (OpenAI tools)**（每個工具的 `name`/`description`/`parameters` JSON schema）連同對話與 system prompt 一起送進 OpenAI。
2. **模型決策**：OpenAI 回傳的是**結構化 `tool_calls (name, arguments)`**（而非自然語言），代表它決定呼叫哪個工具、帶什麼參數。
3. **執行**：app 端攔截該 `tool_calls`，dispatch 到對應的 Python 工具實際執行。
4. **回填**：工具結果包成 **文字工具結果訊息 (provider-neutral text message)(JSON)** 餵回模型。
5. **續推理**：模型據此續寫——可再 emit 下一個 `tool_calls`（單輪可多次往返，multi-tool loop），或產生最終自然語言回覆。

**終止條件**：模型不再 emit `tool_calls`（已可作答），或達 §8 單輪工具呼叫上限 / token 預算。
*最小範例*：`recommend(budget,usage,brand_pref)` → 模型 emit `tool_calls` → app 執行回 2 筆 → 文字工具結果訊息 (provider-neutral text message) → 模型輸出推薦文字。

---

## 5. Agent Workflow（多步驟任務執行流程）

範例請求：「30 萬內想要 Yamaha 跑車，再幫我約看車」

```
使用者輸入：「30 萬內想要 Yamaha 跑車，再幫我約看車」
  → Query Rewriter：偵測 2 個意圖 → 主意圖「找車推薦」、次意圖「約看車」
       （尚未選定車輛，存為 Memory.pending_intent="約看車"）
  → 改寫主意圖：「搜尋 asking_price ≤ 300000、品牌 Yamaha、用途 sport 的二手刊登」
  → Router 分類 = 找車推薦
  → Handler 迴圈：recommend(budget=300000, brand_pref="Yamaha", usage="sport")
      → 工具回傳 2 筆刊登 → 寫入 Memory(viewed_listings 有序, budget, brand_pref, usage, pending_intent)
  → LLM 整理推薦回覆，並主動提示：「選定後可為您預約看車」（回收 pending_intent）
使用者：「第一台規格如何」
  → Query Rewriter：讀 Memory.viewed_listings（有序）解析「第一台」→ viewed_listings[0].listing_id = L001
  → Router = 規格比較 → get_listing_detail("L001") → 回覆規格 + 車況
使用者：「幫我約週六看車」
  → Query Rewriter：補上下文 →「為 listing L001 預約本週六看車」
  → Router = 交易訂單
  → Handler 擬呼叫 book_viewing("L001", 本週六, contact)
       → §8 確認閘：先回「要為您預約 L001 本週六看車，確認嗎？」（暫停，尚未執行）
使用者：「確認」
  → Handler 實際執行 book_viewing("L001", 本週六, contact) → 建立預約紀錄 → 回覆已預約
```

每一步產生 **decision trace**——一筆**結構化 JSON 紀錄**（非純文字），同時供前端側欄、報告、evaluation 與 §8 audit log 使用。欄位至少含：`timestamp`、`session_id`、`raw_input`、`rewritten_query`、`router_label`、`tool_name`、`tool_args`、`tool_result`，以及治理結果 `confirmation`（提議/同意）、`guardrail`（輸入/輸出檢查結果）、`tool_calls_count` 與 `tokens`（呼應 §8 限額與 §9 運營指標）。

---

## 6. Memory 設計

- **Session 與鍵值**：首次訊息發給每位使用者一個 `session_id`(UUID)，回傳前端（cookie 或回應欄位）；記憶以 `{session_id: {history, slots}}` 存於 in-memory dict，生命週期＝行程記憶（重啟即清，符合 Scope）。本專案為單一使用者原型；若要支援併發多人，`session_id` keying 即可避免互相覆蓋。
- **對話記憶（conversation history）**：該 session 的訊息歷史，提供 LLM 上下文。
- **使用者偏好槽（profile slots）**：`budget / brand_pref / usage / viewed_listings / pending_intent`。由 Handler 從對話抽取並持續更新，後續工具呼叫可自動帶入（例如不必重複詢問預算）。
  - `viewed_listings`：**有序陣列**（元素至少含 `listing_id`），順序**嚴格等於**推薦回覆呈現給使用者的順序（採確定性排序，不由 LLM 重排）。
  - **指代解析規則**：序數 N（第 N 台）→ `viewed_listings[N-1].listing_id`；「那台／上一台」→ 最近提及的 listing；超出範圍或空 → 反問澄清，不臆測。
  - `pending_intent`：暫存尚未滿足前置條件的次意圖（如「約看車」需先選定車輛），條件達成後回收（見 §5、§10）。

此即 harness「memory」要素的具體展現，使多輪互動具連續性與個人化。

---

## 7. 錯誤處理與防呆（Error Handling）

- **工具錯誤**（查無資料 / 參數不合法）→ 回傳結構化 error → LLM 轉成「請補充條件 / 換個查法」的友善回覆，流程不中斷。
- **Router 低信心 / 範圍外** → fallback 至一般回覆或主動詢問澄清。
- **Groundedness 護欄**：system prompt 嚴禁捏造規格 / 價格；所有事實必須來自工具回傳，查無即明說。
- **Escalation**：無法解決、退款糾紛、使用者明確要求真人 → `create_ticket` →（必要時）`escalate_to_human`。

---

## 8. Security & Governance（安全與治理）

對齊標準 AI Harness 的第六大元件，橫切整條管線。

- **輸入防護（input guardrails）**：偵測 prompt-injection（如「忽略前述指示」）、拒答範圍外/敏感請求、對使用者個資（聯絡方式）最小化蒐集與不外洩。
- **輸出防護（output guardrails）**：groundedness 檢查——價格/規格/車況等事實必須來自工具回傳，否則攔截並重新生成或改為澄清；禁止給出具約束力承諾（如保證成交價、保證車況）。
- **工具授權（least privilege）**：每情境僅能存取自己的 tool group。狀態變更類工具（`book_viewing`、`create_ticket`、`escalate_to_human`）採**兩階段確認閘**：先回傳「擬執行動作摘要（工具名＋參數）」並**暫停迴圈**；需使用者下一輪明確同意（肯定回覆）後才實際執行。提議與確認皆寫入 decision trace / audit log（pending 狀態暫存於 §6 對話記憶）。
- **稽核軌跡（audit trail）**：decision trace 同時作為 audit log，可回溯每次「改寫→路由→工具呼叫→結果」之決策。
- **成本/頻率限制（rate & cost limits）**：限制單輪最大工具呼叫次數與 token 預算，防止迴圈失控或濫用。
- **治理出口**：偵測到無法安全處理（高風險、反覆失敗、明確糾紛）即 `escalate_to_human`，交由真人接手。

> Security & Governance 與 §7 錯誤處理互補：§7 處理「功能性失敗」，§8 處理「安全、合規、授權與可稽核性」。

---

## 9. Evaluation（評估方法）

建立 **~24–30 題測試集**（`eval/testset.json`），每題標註 `expected_domain`、`expected_tool_calls`（含參數）、`ground_truth_facts` 與 `expected_outcome`。

**測試集分布（避免某領域只有 1–2 題使統計失真）**：找車推薦／規格比較／交易訂單／售後轉真人 **各 ≥5 題**；**跨步驟多工具任務 ≥4 題**；另含 **≥3 題 out-of-scope/閒聊 與 prompt-injection 負例**（標為 `閒聊/範圍外`）。

| 面向 | 衡量方式 | 通過門檻（暫定） |
|---|---|---|
| 工具 / 路由選擇準確率 | 5 類標籤分類；fallback/低信心預測**僅當** gold=`閒聊/範圍外` 時算對 | 準確率 ≥ 90% |
| 任務成功率（end-to-end） | 可驗證述詞：**呼叫了預期工具且參數正確**（如 `book_viewing` 真的以正確 listing_id/時間建立紀錄）**且**最終答案含正確事實 | 成功率 ≥ 85% |
| 回答忠實度（groundedness） | **規則比對為主且權威**：答案中每個價格/cc/hp/車況須與工具回傳 JSON 完全一致（結構化 diff）；LLM-as-judge 為**輔**，只判釋義/語意忠實 | 事實子集違規數 = 0 |
| 運營指標 | 平均回應延遲；平均工具呼叫步數；**每輪總 token＝累加該輪所有 OpenAI 呼叫**（Rewriter＋Router＋每個 Handler round）的 `usage.total_tokens`，非只讀最後一次 | 步數/token 在 §8 預算內 |

**LLM-as-judge rubric**：judge 輸入＝模型答案＋工具回傳事實（testset 的 `ground_truth_facts`），輸出＝faithful / unfaithful＋理由；**規則比對與 judge 衝突時以規則為準**。為降低自評偏誤，judge 模型與作答模型分離（或至少明定「規則比對」才是 pass/fail 依據）。

`eval/run_eval.py` 跑測試集 → 對每個指標輸出 **PASS/FAIL（對門檻）** 與指標表，直接放入報告的 evaluation 段落。

---

## 10. AI Orchestration（流程控制與決策）

- **前處理層**：Query Rewriter 以 LLM 結合對話記憶，把模糊/含指代的輸入改寫成精準、自含上下文的 query，作為後續決策的乾淨輸入。
- **決策層**：Intent Router 以（精準化 query + 情境判斷 system prompt）分類意圖（5 類，含無工具 fallback），決定走哪條領域路徑；領域內由 OpenAI function calling 自主決定工具呼叫順序與參數。
- **多意圖處理**：Rewriter 偵測複合輸入並拆成有序子意圖。本原型採「**單輪處理主意圖 ＋ 次意圖延後**」策略：當前輪只跑主意圖，對尚缺前置條件的次意圖**明確告知並暫存** `Memory.pending_intent`，條件達成（如已選定車輛）後回收，**不靜默丟棄**使用者請求（非並行多 handler，以降低複雜度）。
- **函式呼叫迴圈**：Handler 採 manual function-call 迴圈（見 §4.1），逐步攔截以產生 decision trace 並執行 §8 單輪工具上限。
- **控制流**：Orchestrator 串接 Query Rewriter → Router → Handler → Tools → Memory → Response，並掌管 escalation 出口。各情境獨立、tool group 互不重疊。
- **可解釋性**：每次互動輸出 decision trace（含改寫前後 query），確保決策過程可追蹤、可評估，符合「邏輯一致性與可解釋性」要求。

---

## 11. 交付物（Deliverables）對應

1. **書面報告（2–5 頁）**：濃縮全篇設計——問題定義與使用情境（§1）、系統架構與 AI orchestration（§2、§10）、LLM＋tools＋memory＋security/governance（§4、§6、§8）、function-calling 機制與工具設計（§4、§4.1，8 個工具）、多步驟 agent workflow（§5）、錯誤處理（§7）、evaluation 方法（§9）。（以**內容列舉**取代「第 X–Y 段」式引用，避免章節增改後失準。）
2. **Infographic（資訊圖表）**：視覺化標準 AI Harness **六大元件**——Prompt 層、Orchestration（Router＋工具迴圈）、核心迴圈（Context→Observe→Reason→Act）、Tools & Skills（8 工具/4 group＋fallback）、Memory（偏好槽）、Security & Governance——並含 function calling / tool chain 與 workflow flow。以視覺陪伴工具設計版面後輸出 PNG。
3. **log.md**：記錄本次 AI 輔助設計與開發全程。至少含：(a) 3–5 個關鍵設計決策與理由（如為何採 Approach B、為何前置 Query Rewriter、為何選 OpenAI）；(b) 實際 prompt / 對話節錄；(c) 每次架構調整的前後對比與動機（如本次審查補強）；(d) ≥2 個具體問題分析與修正過程。

---

## 12. 專案結構（Project Structure）

沿用既有 HW 慣例（Flask + templates/static + report + README）。

```
HW4/
  app.py                      # Flask 入口
  config.py                   # 讀 .env：OPENAI_API_KEY、OPENAI_MODEL（預設 gpt-4.1-mini）
  harness/
    rewriter.py               # Query Rewriter（改寫精準化、解析指代、多意圖偵測）
    router.py                 # Intent Router（5 類分類，含無工具 fallback）
    handlers.py               # 四大情境 handler + 無工具 fallback path（manual function-call 迴圈）
    tools.py                  # 8 個工具 function + JSON schema（分 4 tool group）
    memory.py                 # session-keyed 對話歷史 + 偏好槽（有序 viewed_listings、pending_intent）
    governance.py             # 安全與治理：輸入/輸出防護、兩階段確認、限額、稽核
    prompts.py                # 集中管理 rewriter/router/各情境 system prompt
    orchestrator.py           # 串接各層（rewriter→router→handler）、治理鉤子、escalation
  data/
    catalog.py                # 載入＋轉換 CSV：brand 解析、usage 對照表、specs 容錯解析
    listings.py               # 合成二手刊登（固定 seed、精確 join、折舊上下限）
    orders.py                 # 合成交易/預約
  eval/
    testset.json              # ~20-30 題標註測試集
    run_eval.py               # 跑測試集 + 輸出指標表
  templates/ static/          # 聊天 UI + decision trace 側欄
  report/                     # 報告 + infographic 來源
  product_dataset.csv         # 既有型錄資料
  log.md
  requirements.txt
  .env.example                # OPENAI_API_KEY、OPENAI_MODEL 範本
  .gitignore                  # 排除 .env、.superpowers/、__pycache__
  README.md
```

---

## 13. 技術選型摘要

| 項目 | 選擇 |
|---|---|
| LLM 後端 | OpenAI API（`openai`，模型由 `OPENAI_MODEL` env 指定，預設 `gpt-4.1-mini`），manual function calling；`requirements.txt` 釘版本範圍 |
| 後端框架 | Flask（**本機長駐行程**；如需雲端用單一長駐實例如 Render/Railway/Fly.io）。**不建議 Vercel serverless**——無狀態/短暫，會破壞 in-memory Memory/tickets/bookings |
| 前端 | HTML/CSS/JS 聊天 UI + decision trace 側欄 |
| 資料 | pandas 載入 CSV；in-memory 合成 listings/orders |
| Orchestration | Router + 領域工具迴圈（混合式） |
| 評估 | 自建測試集 + 規則比對 + LLM-as-judge |

---

## 範圍界定（Scope）

**包含**：上述 harness 設計、Flask 可跑原型（4 領域 8 工具）、合成資料、evaluation 腳本、三項交付物。
**不包含**：模型訓練/微調、真實金流、真實使用者帳號系統、跨重啟持久化（狀態以 in-memory 為主，重啟即清；如需持久可選**本機檔案 SQLite**，僅適用長駐行程；serverless 檔案系統短暫，本機 SQLite 不適用）。
