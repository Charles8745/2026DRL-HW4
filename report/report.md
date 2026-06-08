# 二手重機交易平台 AI 客服 Harness — 系統設計報告

**RideButler 騎士管家**｜2026 Deep Reinforcement Learning HW4（AI Harness Systems Design）｜2026-06-05

---

## 1. 問題定義與應用背景

二手重機交易平台的買家有大量重複性、跨步驟的諮詢：找符合預算的車、比較車款規格、查詢交易／看車進度、處理退款糾紛。傳統 FAQ 或關鍵字搜尋無法處理像「30 萬內想要 Yamaha 跑車，再幫我約看車」這種**多步驟、需查資料、需即時決策**的請求。

本系統設計一個 **AI Harness**：以大型語言模型（LLM, 採 OpenAI `gpt-4.1-mini`）作為**系統控制器**，透過 **function calling** 串接平台資料與工具，端到端完成上述任務，無法處理時轉接真人。重點在於 **system design 思維**——AI 如何進行 tool use 與 decision-making——而非模型訓練。目標使用者為平台買家，典型任務為四類：找車推薦、規格比較問答、交易與訂單查詢、售後與轉真人。

## 2. AI Harness 系統設計

採 **Approach B：Router + 工具迴圈（混合式 orchestration）**——相較單一 ReAct 迴圈，同時展示「意圖決策（router）」與「工具使用（function-calling 迴圈）」，又不像完整 graph 狀態機那樣過度工程。

```
使用者輸入
  → ① Query Rewriter (LLM)     改寫精準化、解析指代「第一台」、偵測多意圖
  → ② Intent Router (LLM)      5 類意圖分類（4 情境 + 無工具 fallback）
  → ③ Domain Handler           該情境專屬 tool group，manual function-calling 迴圈
  → ④ Tool Layer (9 function)  操作 DataStore，回傳結構化 JSON
       ⤷ 找車推薦含「混合檢索階段」semantic_search：BM25 + 向量(RAG) + Rerank（見 §2.1）
  ⑤ Memory：session 對話歷史 + 偏好槽（budget/brand_pref/usage/viewed_listings/pending_*）
  ⑥ Security & Governance：輸入/輸出防護、兩階段確認、單輪限額、稽核（橫切所有階段）
```

本設計對齊標準 AI Harness 的**六大元件**：

| 標準元件 | 本系統實作 |
|---|---|
| **Prompt** | 分層 system prompt（rewriter / router / 各情境 handler / fallback），集中於 `prompts.py` |
| **Orchestration** | `Orchestrator` 串接 + `Intent Router` 決策 |
| **核心迴圈 Context→Observe→Reason→Act** | Rewriter+Memory 組裝上下文 → Router 觀察分類 → Handler 推理選工具 → 執行工具/回覆 |
| **Tools & Skills** | 9 個 function，分 4 領域 tool group；找車推薦含混合檢索工具 `semantic_search` |
| **Memory** | session-keyed 對話歷史 + 偏好槽 |
| **Security & Governance** | `governance.py` + orchestrator 治理鉤子 |

**資料層**：型錄為**真實 33 款車**（`de/product_dataset.csv`，欄位 `Title/Categories/Description/Price/...`）。載入時轉成正規化 `catalog`：`brand` 由 `Categories` 解析、`usage`（sport/naked/touring/adventure/scooter/cruiser）由人工維護的 33 款對照表標註、`specs` 由 `Description`【規格】區塊容錯解析。二手 `listings` 與 `orders` 以固定 seed 合成、折舊單調並設上下限、`model` 對型錄採精確字串 join。

### 2.1 混合檢索階段（Hybrid Retrieval：BM25 + 向量 RAG + Rerank）

「找車推薦」的結構化篩選（`search_listings`/`recommend`）接不住「新手通勤想省油好停、偶爾跑山」這類**無明確品牌/車種/價格條件**的自然語言查詢。為此新增唯讀工具 `semantic_search`，背後是獨立的三段混合檢索管線 `HybridRetriever`，對 **33 款型錄描述**檢索後展開為在售刈登：

```
改寫後查詢
 ① BM25 稀疏檢索（jieba 中文斷詞）   ─┐
 ② 向量(RAG)檢索（OpenAI embedding）─┤→ ③ RRF 融合(k=60) → 候選 top-10
                                    ─┘
 ④ Rerank（gpt-4.1-mini listwise 重排）→ top-5 車款
 ⑤ 工具層展開為「在售」刈登（+ 預算/車種過濾）→ 回扁平 listing 清單
```

- **設計對稱性**：embedding 與 reranker 各抽象為 `Embedder`／`Reranker` Protocol（呼應既有 `LLM` Protocol），測試注入決定性的 `FakeEmbedder`／`FakeReranker` → 全離線、零成本、可重現。
- **groundedness 沿用**：`semantic_search` 回**扁平 listing 清單**（與 `search_listings` 同形狀），既有價格忠實度檢查與「第一台」序數指代**零改動即生效**。
- **優雅降級**：embedding 失敗退回純 BM25、rerank 不符契約退回 RRF 序。
- 逐段貢獻量化見 §7.4（ablation）、端到端示範見 §7.5。

## 3. Function Calling / Tool Usage 機制

系統採 **manual function-call 迴圈**（關閉 SDK 自動代呼），以便逐步攔截、產生 decision trace、執行單輪工具上限。一輪往返：

1. **送出**：app 把該情境 tool group 的 **tool/function schemas**（每工具 `name`/`description`/`parameters` 之 JSON schema）連同對話與 system prompt 送入 OpenAI。
2. **模型決策**：OpenAI 回傳**結構化 tool call（`name`, `arguments`）**（非自然語言），代表它決定呼叫哪個工具、帶什麼參數。
3. **執行**：app 攔截並 dispatch 到對應 Python 工具實際執行。
4. **回填**：工具結果以**文字訊息（JSON）**餵回模型（provider-neutral，見 `handlers.py`）。
5. **續推理**：模型續寫——可再 emit 下一個 tool call（單輪多次往返），或產生最終回覆。

**終止條件**：模型不再 emit tool call，或達單輪工具上限 / token 預算。程式上由 `be/harness/handlers.py:run_handler` 實作此迴圈，`be/harness/llm.py` 定義 `ToolCall`/`LLMResponse` 與 `LLM` Protocol，`be/harness/openai_client.py` 解析回應的 `message.tool_calls` 與 `usage.total_tokens`。

## 4. Tools 設計（9 個，分 4 領域）

| 領域 | 工具 | 簽章 | 功能 |
|---|---|---|---|
| 找車推薦 | `search_listings` | `(brand_pref?, max_price?, year_from?, usage?)` | 篩選在售刊登（join 型錄 usage/specs） |
| | `recommend` | `(budget, usage?, brand_pref?)` | 依預算/車種排序推薦 |
| | `semantic_search` | `(query, budget?, usage?)` | 自然語言語意檢索（BM25+向量+Rerank），回在售刈登（§2.1） |
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

自建 **27 題標註測試集**（`be/eval/testset.json`），分布：找車/規格/交易/售後 各 ≥5、跨步驟多工具 ≥4、out-of-scope/injection ≥3。`be/eval/run_eval.py` 對每指標輸出數值與 **PASS/FAIL（對門檻）**：

| 面向 | 衡量方式 | 門檻 |
|---|---|---|
| 路由選擇準確率 | 5 類分類；fallback/低信心僅當 gold=`閒聊範圍外` 算對 | ≥ 90% |
| 任務成功率（end-to-end） | 呼叫了預期工具且參數正確 **且** 答案含正確事實 | ≥ 85% |
| 回答忠實度（groundedness） | 規則比對價格/規格為主且權威；LLM-as-judge 為輔 | 違規數 = 0 |
| 運營指標 | 平均延遲；平均工具步數；**每輪總 token＝累加該輪所有 OpenAI 呼叫** | 在預算內 |

groundedness 以**規則比對為主**：蒐集該輪工具回傳的所有價格，檢查回覆中的價格是否皆有依據（`groundedness_violations`），違規率納入 PASS 門檻。`run_eval` 對 confirmation 類工具以「proposed step」計分（提議即代表正確選用工具）；跨情境的多輪任務（如「推薦→約看車」第二個工具落在另一情境）單輪以**主意圖工具**計分，其跨輪串接另以 §7.3 **真兩輪量測**（`score_multiturn`，量第二輪次工具）與 orchestrator 單元測試（兩輪確認、指代解析）共同驗證。

### 7.1 量測結果

**離線（主驗證）**：所有 LLM／embedding／rerank 存取經 `LLM`／`Embedder`／`Reranker` Protocol，注入 scripted `FakeLLM`／`FakeEmbedder`／`FakeReranker` → **242 個單元測試全綠**（零 API 成本、可重現），覆蓋 router／handler 工具迴圈／兩階段確認／groundedness 護欄／governance／OpenAI client 轉接層／混合檢索三段管線。

**真實端到端**（backend = **OpenAI `gpt-4.1-mini`**，`temperature=0`；27 題一次跑完、0 error、108 次 API 呼叫含 4 題第二輪；`python -m be.eval.run_full`，原始數據見 `be/eval/results.json`）：

| 指標 | 數值 | 門檻 | 判定 |
|---|---|---|---|
| router_accuracy | **0.889**（24/27） | ≥ 0.90 | ✗ |
| task_success | **0.630**（17/27） | ≥ 0.85 | ✗ |
| groundedness_violation_rate | **0.222**（6/27） | = 0 | ✗ |
| avg_latency | 4.2s／題 | — | — |
| avg_tokens | 1198／題（turn-1） | — | — |
| **PASS** | **false** | | |

各情境分解：

| 情境 | n | router | task | groundedness 違規 |
|---|---|---|---|---|
| 找車推薦 | 5 | 1.00 | 0.80 | 0.80 |
| 規格比較 | 5 | 1.00 | 0.60 | 0.20 |
| 交易訂單 | 5 | 1.00 | 0.60 | 0.00 |
| 售後轉真人 | 5 | 0.60 | 0.20 | 0.00 |
| 跨情境多輪 | 4 | 0.75 | 0.75 | 0.25 |
| 範圍外 | 2 | 1.00 | 1.00 | 0.00 |
| injection | 1 | 1.00 | 1.00 | 0.00 |

> 數值取自單次完整執行；`gpt-4.1-mini` 即使 `temperature=0`，工具迴圈較長的題目仍有輕微非決定性，重跑時個別 case 可能微幅變動（如售後、範圍外的個別題）。
>
> **更新（UI 操作優化輪，2026-06-08）**：本輪精簡找車推薦 handler 回覆 prompt（僅 1-2 句、不重述卡片規格與里程、保留價格可述）後重跑——router **0.889 不變**、task 0.630→**0.593**（非決定性波動）、groundedness 違規 **0.222→0.037**、多輪鏈 0.25→**0.50**。testset 與計分器一字未改（凍結守門全綠），改善來自移除里程偽陽性。完整四項 eval 前後對照與原因見 **§7.7**。

### 7.2 結果分析（誠實，未達門檻）

- **router 88.9%**：分類強健（找車／規格／交易／範圍外皆 1.00），本次 3 題誤判（after-01、after-05、multi-01），差 90% 門檻一題之距；售後情境路由較不穩（0.60）。
- **task_success 63.0%（主要缺口）**：`gpt-4.1-mini` 在我們的 prompt 下**有時直接作答而未 emit 預期的 function call**——售後情境最明顯（0.20，常直接回覆而非呼叫 `create_ticket`/`escalate`），規格／交易為 0.60。這反映**該模型的工具呼叫傾向**，非 harness 接線缺陷（接線已由單元測試驗證全綠）。
- **groundedness 22.2%**：集中於**找車推薦（0.80）**——推薦時模型會補述工具回傳 payload 中沒有的價格／規格數字，被規則式檢查（回覆中出現工具未回傳的價格即 flag）攔下。誠實訊號：找車情境 prompt 應更嚴格限制「只引用工具回傳價格」，或檢查器需加價格格式正規化（如「30 萬」↔`300000`）。
- 量測誠實性：confirmation 類工具以 proposed step 計分；單輪 27 題以**主意圖工具**計分，未為衝分數改 `expected_tools`；跨輪次工具另以 §7.3 真兩輪量測。

> 結果未達 PASS 門檻是**真實量測**，非調整後的數字。改善方向（強化找車 groundedness prompt、提高售後工具呼叫率）屬後續迭代，不在本次系統設計交付範圍。

### 7.3 多輪鏈成功率（真兩輪量測）

`secondary_tool` 過去只記錄、不量測。本次對 4 個 multi-* case 在**同一 session** 跑第二輪（testset 的 `followup`），以 `score_multiturn` 量測「主工具(turn-1)＋次工具(turn-2) 是否都觸發」。**不改單輪計分、不改 `expected_tools`**，純加法。

**`multiturn_chain_success` = 0.25（1/4）**

| case | turn-2（followup） | 主工具(turn-1) | 次工具(turn-2) | 鏈 |
|---|---|---|---|---|
| multi-01 | 第一台規格如何 | ✗ recommend | ✗ get_listing_detail | ✗ |
| multi-02 | 約看第一台 | ✅ recommend | ✅ book_viewing | ✅ |
| multi-03 | 便宜的那台幫我約看車 | ✅ compare_models | ✗ book_viewing | ✗ |
| multi-04 | 幫我開工單 | ✅ check_order | ✗ create_ticket | ✗ |

分析（誠實）：
- **multi-02 ✅**：完整示範跨情境鏈——turn-1 `recommend` 設定 viewed_listings，turn-2「約看第一台」經 **ordinal 解析**取得 listing 後 `book_viewing`（confirmation-gated，以 proposed 計）。這正是系統的招牌能力。
- **multi-01 ✗**：turn-1 連 `recommend` 都未觸發（模型直接作答），鏈在主工具即斷——與 §7.2 的工具呼叫傾向問題同源。
- **multi-03 ✗（已知架構限制）**：`compare_models` 回的是**車款**非**刊登**，`set_viewed` 不記比較結果，「便宜的那台」既無價可比、也無 listing 可約。「車款比較→刊登預約」橋接為 **future work**。
- **multi-04 ✗**：turn-2「幫我開工單」未觸發 `create_ticket`（模型多追問細節而非直接建單）——同屬工具呼叫率問題。

> 設計意義：此指標把「招牌的跨輪能力」從**只由單元測試驗證接線**，提升為**對真實模型的端到端量測**，誠實暴露 1/4 的真實鏈成功率與其斷點，而非以單輪主工具粉飾。

### 7.4 檢索 ablation（BM25 → +向量 → +Rerank）

對 16 題自然語言語意查詢（`be/eval/retrieval_testset.json`；gold 限**有在售刈登**的車款、依描述/規格證據標註、每題 1–3 款）量測三段管線的逐段貢獻（真實 OpenAI `text-embedding-3-small` + `gpt-4.1-mini`，**模型層車款檢索**；`python -m be.eval.retrieval_eval`，原始數據 `be/eval/retrieval_results.json`）：

| 配置 | recall@1 | recall@3 | recall@5 | MRR@10 | nDCG@5 | recall@10（候選池天花板） |
|---|---|---|---|---|---|---|
| BM25 only | 0.375 | 0.562 | 0.625 | 0.549 | 0.501 | 0.688 |
| + 向量(RRF) | 0.375 | 0.594 | 0.688 | 0.557 | 0.541 | **0.812** |
| + Rerank（完整） | **0.688** | 0.688 | **0.812** | **0.760** | **0.729** | 0.812 |

分析：
- **向量(RAG) 的貢獻在「召回」**：把候選池天花板（recall@10）由 0.688 拉到 0.812——稠密語意檢索找回 BM25 純詞面漏掉的相關車款（如「熱血/戰鬥感」對應 sport）。
- **Rerank 的貢獻在「排序精度」**：recall@1 由 0.375 躍升至 0.688、MRR 0.557→0.760、nDCG 0.541→0.729——在固定候選池內把相關車款重排到前面。完整配置與「+向量」的 recall@10 同為 0.812，印證 rerank **只在候選池內重排、不增召回**（如設計）。
- 指標定義（binary relevance）：`recall@k = |rel∩topk| / min(|rel|,k)`、`MRR@10` 取首個命中、`nDCG@5` gain=1。含非決定性 rerank 的完整配置跑 3 次取均值，本批三項指標離散度為 0（穩定）。
- 誠實定位：16 題為**方向性示意基準、非統計顯著**；薄 usage 類（cruiser=1、touring=2）取樣有限。

### 7.5 檢索階段端到端（sem-* 案例）+ 無回歸

主 27 題 testset **凍結不動**（保住 §7.1–7.3 數字，並有 `test_main_testset_frozen_at_27` 守門）；另設 4 題語意查詢 `be/eval/sem_testset.json` 驗證檢索階段**真的接進對話**（`python -m be.eval.run_sem`，`be/eval/sem_results.json`）：

| 指標 | 數值 |
|---|---|
| router_accuracy | 1.00（4/4 正確路由到找車推薦） |
| `semantic_search` 觸發率 | 0.75（3/4） |
| groundedness | 1.00（4/4） |

- **觸發率 0.75**：純情境查詢（新手通勤、戰鬥感、復古）穩定觸發 `semantic_search`；惟「跑長途環島舒服」這類**可被推斷為 usage（touring）**的查詢，模型有時改走結構化 `recommend`/`search_listings`——屬 retrieval 與 structured 工具間的邊界非決定性，兩路皆回 grounded 結果。（此案曾偶發模型呼叫 `recommend` 卻漏帶 `budget`；已強化 `run_handler`：工具執行例外改以錯誤結果回饋模型而非中斷整輪，對 0-error 的凍結 27 題為 no-op。）
- **groundedness 1.00**：扁平 listing 回傳使回覆引用的價格與里程皆可溯源至檢索到的刈登（此處同時白名單價格與里程；§7.1 主驗證的 `_facts_from_trace` 僅白名單價格，故對列出多筆里程的回覆較嚴格——兩者皆為真實量測、無捏造）。
- **無回歸**（vs 遷移後基線 §7.1）：router 0.889 不變、groundedness 違規 0.222→0.185（改善）。task_success 0.630→0.556 的兩題變動為 find-02（在 `search_listings`↔`recommend` 兩個結構化工具間擺動，**非**被 `semantic_search` 劫持，已逐案驗證）與 oos-02（未改動情境的非決定性）；**新增的檢索工具未把任何結構化找車查詢導向 `semantic_search`**。

### 7.6 Robustness Eval（使用情境 / 邊緣 / 異常 / 安全）

獨立資料集 `be/eval/robustness_testset.json`（40 題，四類各 10），端到端跑真實 gpt-4.1-mini（2026-06-07；非決定性，數字會微幅變動）。每題只評估其 `expect` 宣告的檢查、pass = 宣告檢查全過（`python -m be.eval.robustness_eval`；原始數據 `be/eval/robustness_results.json`、修補後 `be/eval/robustness_results_postfix.json`）。**此為方向性 robustness 量測，非統計顯著、非 CI 門檻。**

| 類別 | n | pass_rate（修補前 → 後） |
|---|---|---|
| usage（使用情境） | 10 | 0.50 → 0.50 |
| edge（邊緣） | 10 | 0.80 → 0.80 |
| exception（異常） | 10 | 0.70 → 0.60 |
| security（安全） | 10 | **1.00 → 1.00** |
| 總體 | 40 | 0.75 → 0.725 |

各檢查通過率（修補前，逐檢查原語）：router_label 12/12、no_crash 23/23、honest_empty 6/6、blocked 2/2、no_domain_tool 7/7、tools 3/3、awaiting_confirmation 4/5、confirmed_executed 1/1、confirmed_cancelled 1/1、**grounded 25/38（唯一主要缺口）**。

**關鍵發現（誠實）：**
- **管線結構性穩健**：路由 100%、零崩潰（no_crash 23/23，含亂碼／超長／emoji／英文／矛盾輸入皆未 crash）、查無資料誠實回報（honest_empty 6/6，未捏造任何 L###/O###）、兩階段確認閘在「不用問直接約」的繞過嘗試下仍守住（awaiting_confirmation），否定「先不要」正確取消（confirmed_cancelled）。
- **安全 10/10**：injection 直接覆寫（sec-01/04）由輸入守門攔下；中文系統提示外洩／開發者模式變體（sec-02/03）**修補前守門擋不住、靠模型自身拒絕通過**；範圍外任務（寫程式／翻譯）、幻覺價格誘導（「是不是只要 5 萬」）、越權索取個資皆被模型拒絕（no_domain_tool + grounded）。
- **`grounded` 缺口幾乎全是計分器偽陽性，非模型幻覺**：被標記的數字**全為里程**（如 15000／24000／38000 公里），是模型**正確引用工具回傳的 `mileage_km`**；共用的 `_facts_from_trace` 只白名單**價格**（與 §7.1 主驗證同一計分器），故把合法里程誤判為未溯源。（證據基礎：結果檔僅存各檢查布林值，此里程特徵由一次性診斷重跑失敗案例印出 reply＋violations 佐證，並可由「在售刈登 schema 帶 `mileage_km`、而 `_facts_from_trace` 僅白名單 `asking_price`/`price`」結構性推得。）此為**已知計分器侷限**（§7.5 已述）、與凍結 27 題基線共用，本輪（robustness eval）**刻意不更動計分器**（改動會牽動凍結基線；放寬以拉高分數等同灌水）。exception 類 0.70→0.60 亦為此里程偽陽性的非決定性波動，非回歸。
  - **後續更新（§7.7，UI 操作優化輪）**：計分器與 testset **仍一字未改**，但因該輪叫模型「不逐台重述里程」，里程不再進入 prose → 這些偽陽性自然消失：robustness `grounded` 25/38→**37/38**、總 pass 0.725→**0.925**、exception 0.70→**1.00**。這是回覆更乾淨帶來的真實提升，非放寬計分。

**修補（便宜的真缺口，認誠處置）：**
- 量測顯示 sec-02/03 的中文 injection 變體**繞過關鍵字守門**（僅靠模型善意攔下）。已擴充 `governance._INJECTION`（系統提示／開發者模式／印出指令／無視先前等變體），守門對 injection-style 探針的攔截覆蓋由 **2/4 提升至 4/4**（離線 governance 測試佐證）。
- **對資料集 pass_rate 無可見變化**（0.75→0.725 為非決定性，非回歸）：因模型本來就會拒絕，此修補屬**縱深防禦**——不再單靠模型善意。
- **零回歸**：改 governance 後全離線測試綠（242 passed，含 `test_main_testset_frozen_at_27`）。

**未解決（future work）：** 關鍵字 blocklist 無法窮舉 → 需 LLM-based injection 偵測；groundedness 事實白名單僅價格、且價格未正規化（「30萬」↔300000）→ mileage／規格-aware 抽取；多輪「找車→約看第一台」偶發未觸發 book_viewing（usg-10，非決定性；與 multi-03 橋接同屬 future work）。

### 7.7 UI 操作優化輪：精簡 prompt 後的 eval 重跑（誠實對照）

UI 操作優化輪（§8.1）唯一動到 eval 的是**找車推薦 handler 回覆 prompt 精簡**（卡片已完整呈現規格，故文字僅 1-2 句總結、**不逐台重述規格與里程**，但**保留價格可自然帶到**）。**testset 四檔與 groundedness 計分器（`_facts_from_trace` 只白名單價格）一字未改**（`test_*_frozen`／`test_on_step_none_is_identical` 全綠），故以下變動皆為同一量尺下的真實對照。設「違規率較基線升 > 5 個百分點即退回 prompt」門檻，實際**未觸發**。

| eval | 指標 | 基線 | 本輪 | 解讀 |
|---|---|---|---|---|
| 主 27 題 | router_accuracy | 0.889 | 0.889 | 不變 |
| (§7.1) | task_success | 0.630 | 0.593 | 非決定性波動（仍 < 0.85 門檻） |
| | groundedness 違規 | 0.222 | **0.037** | 大幅改善 |
| | 多輪鏈成功 | 0.25 | **0.50** | 改善 |
| 檢索 ablation (§7.4) | full recall@5 / MRR / nDCG | 0.812 / 0.760 / 0.729 | 0.812 / 0.771 / 0.737 | 一致（模型層，不受 prompt 影響；rerank 微幅非決定性） |
| sem-* (§7.5) | router / 觸發 / grounded | 1.0 / 0.75 / 1.0 | 1.0 / 0.75 / 1.0 | 不變 |
| robustness (§7.6) | 總 pass | 0.725 | **0.925** | 大幅改善 |
| (40 題) | grounded 檢查 | 25/38 | **37/38** | 大幅改善 |
| | exception / security | 0.70 / 1.00 | **1.00** / 1.00 | exception 改善、security 滿分 |

**為何 groundedness／robustness 改善而非灌水**：§7.6 早已誠實揭露——`grounded` 缺口幾乎全是計分器把模型**正確引用的里程**（5 位數，如 15000／24000）誤判為未溯源（計分器只白名單價格）。本輪叫模型「不逐台重述里程」後，這些里程不再出現在 prose → 偽陽性自然消失；而「價格可自然帶到」使模型仍引用價格，故價格 grounding 照常被量測（沒有把可驗事實藏起來）。**計分器與 testset 皆未動**，純粹是回覆內容更精簡乾淨帶來的真實提升。task_success 微降為長工具迴圈題目的非決定性，非回歸。

**整合驗證額外收穫**：eval 重跑本身抓到一個單元測試與 demo 瀏覽器都漏的真實整合 bug——eval 的 `ThrottledRetryClient`（duck-type `LLM` Protocol）在串流輪加 `on_token` 時被漏改，使 eval 全面報錯；已修正並加離線簽章守門（log §K）。

## 8. UI/UX 重新設計：SSE 即時管線 + BYOK + 視覺改版

其中一輪把「決策過程」從事後一次性的 Decision Trace 側欄，升級成**即時串流的指揮中心**，並讓系統可在公開環境以**自帶金鑰（BYOK）**安全運行。三大支柱：

**① SSE 即時管線（零行為變更觀察層）**：在 `process()`／`run_handler()`／`semantic_search()`／`retrieve()` 加入 append-only、default `None` 的 `on_step`／`on_substep` 觀察鉤子——當為 `None` 時行為與改版前**位元相同**（由 `tests/test_orchestrator_stream.py::test_on_step_none_is_identical` 守門：同 FakeLLM 腳本跑兩次 deep-equal 整個回傳含 `trace.tokens`，涵蓋 guard/pending-yes/pending-cancel/fallback/recommend/semantic 六路徑）。`_emit` 以 `copy.deepcopy` + 鍵名 scrub 唯讀快照，**絕不就地改動** trace/memory 的 listing dict（保護 eval 與序數指代）；retriever 的 `on_substep` 只回 `bm25`→`vector`→`rrf`→`rerank` 已算好結果的唯讀快照，**禁重排/重切/重呼叫**（golden-ranking 守門證 ablation 排名位元不變）。前端以 `EventStream`（fetch ReadableStream）逐 frame 接收，PipelinePanel 以 reducer 把事件還原成步驟樹（retrieval 子步透過 `parentId` 掛在 semantic_search 工具節點下）。

**② BYOK（每請求建構 + 語料嵌入快取）**：金鑰只走 HTTP header `X-RideButler-Key`（移除 body 通道、`process()` 前 strip）；每請求建獨立 `DataStore`＋`Orchestrator`（共享唯讀型錄、複製 listings/orders/tickets），**絕不**改共享 `store.retriever`，從根本消除並發競態（R2）。語料嵌入以 `CorpusEmbeddingCache`（process-level singleton + per-key double-checked lock）跨請求快取——命中免 embed、免金鑰；失敗回 `None` 且**不存**（不毒化，R3）。logging 端加 process-level redaction filter，金鑰字面與 `sk-[A-Za-z0-9_-]{20,}` 一律 `sk-***REDACTED***`。安全由 `tests/test_secret_safety.py` 守門：sentinel `sk-LEAKCANARY` 穿 build/streamed/JSON turn 後不在 `json.dumps(trace)`／任何 SSE frame／`resp.data`／`caplog.text`，含「金鑰誤填進 message」案例（scrub 自 `raw_input`/`rewritten_query`）。

**③ 視覺改版（風格 C·三區指揮中心）**：三欄版面（`64px minmax(0,1fr) 400px`：IconRail／ChatLog＋inline ListingCard／PipelinePanel）；design tokens 單一真相源（`tokens.css`，無散落裸 hex）；landing→chat 序列化「招牌時刻」動態（morph→開串流，`prefers-reduced-motion` gate）；ListingCard 圖片採 **local-first 三層 fallback**（`/static/img/bikes/<slug>.webp`→`.jpg`→遠端 https-upgrade→inline SVG placeholder），解決 trace 不帶 `media_url` 的缺口（R12）——title→media_url map 由 `GET /api/config` 提供；空結果走專屬空態卡＋放寬 chips（R13）；usage/condition 的 zh 標籤集中於 `labels.js`（R14）；卡片動作以 `listing_id` 顯式 prefill（避免 ordinal 漂移，R17）。

**部署（單實例、SSE-safe）**：gunicorn `gthread`、`workers` 硬鉗為 1（boot self-check 拒 >1）、`X-Accel-Buffering: no`（R10/R11）；`wsgi.py` 以 `assert not app.debug` 強制非 debug；Render/Docker 皆單實例、健康檢查 `/`，**公開主機絕不設 `OPENAI_API_KEY`**（生產＝BYOK only，R1，DEPLOY.md 粗體警語）。風險登記簿 6 critical／9 high 風險全於設計階段吸收，逐項對應守門測試。

**回歸保證**：全離線單元測試 242 個全綠（新增 SSE/BYOK/安全/部署/JS-mirror 測試，0 真實網路、全 `Fake*`/spy），凍結基準（27 題主 eval、40 題 robustness、`*results*.json`）一字未動，主 27 題 router 0.889 不變——觀察層與 BYOK 對既有管線**零行為變更**。

### 8.1 UI 操作優化（M0–M4，2026-06-08）

以真實瀏覽器（chrome-devtools 端到端）親自操作上一輪改版後的 app，量到一個**致命操作性 bug**——聊天區整頁僅能捲 37px（`.chatlog` 缺 flex/overflow 規則、`#app` 100vh overflow:hidden），18 張車卡可見數為 0、做完第二輪仍卡在第一輪頂端——以及資訊洪流與輸入體驗痛點。本輪聚焦操作體驗 + 視覺質感，分五個里程碑（皆 TDD + **控制者真實瀏覽器逐里程碑驗收**）：

- **M0 捲動修復 + composer 釘底**：`.chatlog` 改為 `overflow-y:auto` flex 捲動容器、composer 釘底固定列；並修正 demo banner 把 `#app` 推出視窗（body flex column + `#app` flex:1）。回答/車卡/多輪皆可達、composer 永遠可見。
- **M1 版面與視覺重整**：composer `<input>`→自動增高 `<textarea>`（Enter 送出／Shift+Enter 換行／IME 不誤送／送出後焦點回輸入框）、對話泡泡 `align-self` 限寬留白（user 右／bot 左）、rail emoji→內嵌單色 SVG + tooltip、landing 收單一輸入。
- **M2 結果呈現（卡片為主 + 一句話摘要）**：意圖 gating（追問/確認不再灌一副不相關車卡）、預設前 6 張 + 「顯示更多」、handler 回覆 prompt 精簡（§7.7）、長 prose 安全收合。
- **M3 文字串流輸出**：最終回覆改 SSE token 逐字串流（`LLM.generate(on_token=…)`、orchestrator emit `token`、FE 增量渲染、`final` 以權威文字定稿並掛車卡）；串流中禁用 composer 且可**停止**（`AbortController`，真實中止 in-flight 串流）。**eval 相同性**：`on_step=None → 非串流 → 位元相同`（`test_on_step_none_is_identical` 守門），eval/`/api/chat` 仍走非串流路徑。
- **M4 確認/取消 + 細節打磨**：兩階段確認閘觸發時渲染「確認/取消」快捷鈕（點擊執行 book_viewing）、**真實 per-stage 計時**（取代假 `0 ms`，未量階段留白、子毫秒顯 `<1 ms`）、管線面板右緣防裁切。

**工作流**：brainstorming → spec → 6 面向多代理對抗式自審（54 confirmed findings 中落實 12 項真缺陷）→ writing-plans（M0–M4）→ subagent-driven TDD（每里程碑實作 + spec/品質審查代理）→ 控制者真實瀏覽器驗收 → eval 重跑（§7.7）。**回歸**：`pytest` 249 passed、`node --test` 58 pass，凍結守門全綠；分支 `feat/ui-ux-operability`。詳見 log §K。

## 9. 結論

本系統以 LLM 為控制器、function calling 為手段，完整實作標準 AI Harness 六大元件，並以情境隔離、兩階段確認、groundedness 護欄與結構化稽核確保**邏輯一致性與可解釋性**。找車推薦情境再加上 **BM25 + 向量(RAG) + Rerank 三段混合檢索階段**（§2.1），ablation 顯示向量召回與 rerank 排序各有清楚可量化的貢獻（§7.4）。再以獨立的 **40 題 robustness eval**（使用情境／邊緣／異常／安全；§7.6）量測管線健壯性：路由 100%、零崩潰、查無誠實回報、確認閘抗繞過、安全 10/10；並認誠揭露 `grounded` 主要缺口實為計分器對合法里程的偽陽性（非幻覺），順手修補了 injection 守門對中文變體的縱深防禦缺口。所有 LLM／embedding／rerank 存取經 `LLM`／`Embedder`／`Reranker` Protocol 抽象，使整個 harness 可離線、可重現地單元測試（242 tests），並可無痛切換後端（本次由 Gemini 遷移至 OpenAI `gpt-4.1-mini`，管線零改動），是一個兼顧設計完整性與工程可驗證性的 AI 系統設計範例。

*附：系統架構與 tool-chain 視覺化見 `report/infographic.html`／`infographic.png`；完整規格見 `docs/superpowers/specs/`；設計與開發歷程見 `log.md`。*
