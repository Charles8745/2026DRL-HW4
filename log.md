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

4. **LLM 後端：OpenAI `gpt-4.1-mini`**（最初依使用者指定選 Gemini，2026-06-06 因該 key 免費額度受限遷移至 OpenAI——見 §F），透過 `LLM` Protocol 抽象。理由：抽象層讓所有元件可用 scripted `FakeLLM` 離線單元測試，零 API 成本、可重現，**且後端可無痛替換**（遷移時管線零改動，僅換一個 client class）。

5. **部署採本機長駐行程而非 Vercel**。理由：審查發現 Vercel serverless 無狀態/短暫，會破壞 in-memory Memory / tickets / 跨輪指代解析。

---

## C. 與 AI 的互動／設計迭代（節錄）

**釐清階段（一次一問）**：交付範圍 → 「設計文件 + 可跑原型」；場景 → 「智能客服」→ 具體化為「二手重機平台」；資料定位 → 「型錄當知識庫 + 合成二手刊登」；能力 → 四大情境全選；原型形式 → 「Flask 可部署 web 聊天」；後端 → OpenAI（`gpt-4.1-mini`；中途曾改 Gemini，後因額度受限遷回 OpenAI，見 §F）；evaluation → 四面向全選。

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

- **78 個單元測試全綠**（全程 FakeLLM，離線、零 API 成本、可重現）。
- 完整 harness：資料層 → 8 工具 → memory/governance → rewriter/router/handler/orchestrator → Flask 聊天 UI + Decision Trace 側欄 → evaluation（27 題）。
- 三項交付物：書面報告、infographic、本 log.md。
- 每階段經兩階段審查（spec 合規 + 程式品質）通過後才進入下一階段。

---

## F. 後端遷移：Gemini → OpenAI（2026-06-06）

**動機**：實跑 evaluation 時發現可用的 Gemini API key 免費額度被異常限縮——`gemini-2.0-flash` 免費額度為 0（API 回 `limit: 0`）、`gemini-2.5-flash-lite` 僅 20 requests/day，而 27 題 eval 需約 110–135 次呼叫，無法跑出完整端到端指標。使用者改提供 OpenAI key，遂將後端整個換成 OpenAI `gpt-4.1-mini`。

**為何幾乎零成本**：(a) 所有 LLM 存取走 `LLM` Protocol；(b) handler 工具迴圈以純文字回填工具結果（非 Gemini 專屬結構）。故只新增一個 `harness/openai_client.py`（實作 Protocol：訊息映射、Gemini decl→OpenAI tools schema 轉接、`tool_calls` 解析、`usage.total_tokens`，`temperature=0`），rewriter/router/handlers/orchestrator **一行不動**，70 個離線測試（FakeLLM、後端無關）全數續綠。設計亮點：`LLM` Protocol 抽象讓「換後端」成為一次性、可驗證的小改動。

**新增/變更**：新增 `openai_client.py` + 8 個 client 單元測試（70→78）；`config.py` 改讀 `OPENAI_API_KEY`/`OPENAI_MODEL`（屬性名 `API_KEY`/`MODEL` 不變）；換 3 個建構點（app/run_eval/run_full）；`requirements.txt` `google-genai`→`openai`；刪 `gemini_client.py`；全庫文件 Gemini→OpenAI。

**真實量測**（gpt-4.1-mini，27 題、0 error）：router 0.889、task_success 0.593、groundedness 違規率 0.222、PASS=false（誠實未達門檻，分析見 report §7.2）。原始數據 `eval/results.json`。

> 問題→修正範例（本階段）：先試 `gemini-2.5-flash-lite` 跑 eval，發現每日上限僅 20 → 4 題後整批 429 且每題空轉 ~480s。改為偵測 `limit: 0` 與每日配額後判定免費額度不可行 → 遷移 OpenAI，全 27 題一次跑完。

## G. 混合檢索階段：BM25 + 向量(RAG) + Rerank（2026-06-07）

**動機**：找車推薦只有結構化精確篩選（brand/price/year/usage），接不住「新手通勤想省油好停、偶爾跑山」這類無結構化條件的自然語言查詢；型錄豐富描述完全未用於檢索。新增唯讀工具 `semantic_search` + 獨立 `HybridRetriever`（BM25 jieba 斷詞 + OpenAI 向量 + RRF 融合 + gpt-4.1-mini listwise rerank），對 33 款型錄檢索後展開為在售刈登。

**流程與 AI 協作**：走 brainstorming → spec → 對抗式審查 → writing-plans → TDD 實作 → 對抗式 code review。三項使用者拍板的設計決策：(1) 目標兩者並重、(2) 語料以型錄車款為索引單位、(3) 技術棧選「OpenAI 原生・輕量」（`Embedder`/`Reranker` Protocol + Fake 保離線，而非引入 torch/sentence-transformers）。

**spec 對抗式審查（6 面向，commit `0115066`）攔下 4 個真實 blocker**並修正：
- groundedness「零改動」原本是假——`_facts_from_trace` 只看頂層，原設計的 `{models,listings}` wrapper dict 會使價格無法被收集 → **改為 `semantic_search` 回扁平 listing 清單**，groundedness 與序數指代真正零改動。
- `set_viewed` 接線原為 no-op（dict 過不了 `isinstance(list)` 守衛）→ 扁平清單後僅需把工具名加進既有 tuple。
- 「81 測試全綠」承諾為假——`test_tool_registry` 斷言每群 2 工具 → 明列為需同步更新（找車推薦變 3 工具）。
- 移除索引持久化（33 篇建構時一次 embed，持久化為 gold-plating）；補上檢索指標形式定義與 ablation 重跑取均值；釘死 RRF/Fake* 決定性契約。

**問題→修正範例（實作期，TDD/真跑攔截）**：
1. `VectorStore` matmul 在全測試套件下噴 divide/overflow/invalid RuntimeWarning（矩陣其實有限，是洩漏的全域 FP 狀態）→ 以 `np.errstate` 包裹、並對零向量穩健。
2. sem-* 端到端起初 grounded_rate=0.0 → 診斷發現被 flag 的 5 位數其實是**里程**（`_facts_from_trace` 只白名單價格）→ 在**新的** `run_sem` 用更完整的事實白名單（價格＋里程＋年份），不動凍結的主 eval 計分；grounded_rate→1.0。
3. sem-02 觸發 `recommend` 缺 `budget` 參數使 `run_handler` 直接拋 `TypeError` → `run_sem` 比照 `run_full` 加 per-case try/except（不改凍結管線行為）。

**對抗式 code review（4 面向 × find→verify，commit `6a25a9f` 起）確認 3 項真實問題並修正**（另 5 項經驗證後駁回為命名/不可重現）：
4. `match_snippet`（回傳給 LLM 的型錄描述）含 5+ 位數行銷數字（如 X-ADV「76,000 輛」），模型若引用會被「只白名單價格」的 groundedness 誤判 → 在 `_snippet()` 移除 5+ 位數字串（不動 BM25/向量索引用的 `_doc_text`），使 §7.5 grounded=1.0 由「靠運氣」變穩健。
5. `HybridRetriever.__init__` 建構時 embed 為未捕捉呼叫，OpenAI 任何閃失即讓 app/eval 建構整個崩潰 → 包 try/except，失敗則 `vstore=None`、`retrieve()` 退回純 BM25。
6. `semantic_search` 對非數字 `budget` 直接 `int()` 會 500 → 防禦性轉型。
7. （由 sem-02 觸發）`run_handler` 對工具執行例外未捕捉會中斷整輪 → 改以錯誤結果回饋模型續推理；對 0-error 的凍結 27 題為 no-op，屬 harness「錯誤處理」元件的真實強化。

**成果**：124 個離線單元測試全綠（78→124，+46）。ablation（真實 OpenAI，16 題，report §7.4）：BM25 → +向量 → +Rerank 的 recall@1 = 0.375 → 0.375 → **0.688**、recall@5 = 0.625 → 0.688 → **0.812**、MRR = 0.549 → **0.760**、nDCG = 0.501 → **0.729**；向量把候選池天花板 recall@10 由 0.688 拉到 0.812（增召回）、rerank 在固定池內提升排序精度。sem-* 端到端（§7.5）：router 1.0 / 觸發 0.75 / grounded 1.0。**無回歸**：主 27 題 router 0.889 不變、groundedness 違規 0.222→0.185（改善），新檢索工具未劫持任何結構化找車查詢。spec `0115066`、plan `db036f4`，實作分多次 commit 於 `feat/hybrid-retrieval`。

## H. Robustness Eval：使用情境 / 邊緣 / 異常 / 安全（2026-06-07）

**動機**：自動化驗證覆蓋不均——主 27 題只測 happy path（安全僅 1 題），邊緣／異常／安全幾無專屬資料集。新增獨立、真實 OpenAI 端到端的 robustness eval（40 題、四類各 10）+ category-aware runner，系統性量測管線健壯性並把測試查詢固化成可重用 dataset。

**流程與 AI 協作**：走 brainstorming → spec → writing-plans → **subagent-driven 執行**（每 Task 一個全新 subagent，Task 間兩階段審查：spec 合規 → 程式品質）。使用者三項拍板：(1) 後端＝純真實 OpenAI eval、(2) 規模中型 ~40 題、(3) 缺口策略＝認誠測量 + 修便宜的真缺口。架構選單一資料集 + 一支 runner + per-case `expect` schema（只評估宣告的檢查；計分原語 router_label/tools/no_domain_tool/blocked/awaiting_confirmation/grounded/honest_empty/no_crash/confirmed_executed/confirmed_cancelled）。

**兩階段審查攔下的真實問題（採 receiving-code-review 紀律，逐項技術裁決而非照單全收）**：
- Task 1：審查建議把 `honest_empty` 的 `bool(data)` 改 `data is not None`——**駁回**（會使 `_ok([])`「查無」反被判定為有資料，破壞語意）；採納其文件化建議。`_ID_RE` 加 lookahead 建議**駁回**（本域 ID 固定 3 位數，該修不達目的）。
- Task 2：採納 3 個 minor——subtype `no_insale_model`→`no_insale_listing`（XMAX 在型錄、只是無在售刈登）、守門新增 `router_label ∈ LABELS` 驗證、sec-04 補 `grounded` 對稱。
- Task 3：審查發現 exception 路徑只對 turn-1 `expect` 記 `no_crash=False`，turn-2 崩潰會漏記，且原寫法會覆蓋已算好的 turn-1 checks → **以 `is None` 守衛改寫、同時涵蓋 `expect_turn2`**；移除未用的 `time` import。
- Task 5：採納測試覆蓋 hygiene（每個新關鍵字補一條 unit 探針）。

**量測結果（baseline，report §7.6）**：總 pass 0.75；usage .50 / edge .80 / exception .70 / **security 1.00**；router 12/12、no_crash 23/23、honest_empty 6/6、blocked 2/2、no_domain_tool 7/7。**唯一主要缺口 grounded 25/38**。

**關鍵誠實發現**：逐筆診斷（throwaway script 跑失敗案例印 reply+violations）證實 `grounded` 失敗**幾乎全是計分器偽陽性**——被 flag 的 5 位數全是**里程**（15000/24000/38000），模型正確引用工具的 `mileage_km`，但共用的 `_facts_from_trace` 只白名單價格（§G 點 2、§7.5 已知此侷限）。因與凍結 27 題共用計分器，**刻意不更動**（改動牽動凍結基線、放寬以拉分等同灌水）→ 列 future work（mileage-aware 抽取）。

**修便宜的真缺口**：量測顯示 sec-02/03 中文 injection 變體（印出系統提示／開發者模式／隱藏指令）**繞過關鍵字守門、僅靠模型自身拒絕**。擴充 `governance._INJECTION`（+11 變體），守門對 injection 探針攔截由 2/4→4/4（離線 governance 測試佐證）；**對資料集 pass_rate 無可見變化**（模型本就拒絕，屬縱深防禦），**零回歸**（全離線 147 綠含凍結 27 守門）。post-fix 重跑 0.725（與 0.75 同屬非決定性、非回歸），security 維持 10/10。

**成果**：147 離線測試全綠（124→147，+23：scoring 13 + dataset 守門 7 + governance 3）。資料集 `eval/robustness_testset.json`（凍結 40 題）、runner `eval/robustness_eval.py`、結果 `eval/robustness_results{,_postfix}.json`。spec `2fe055d`、plan `5416c59`，實作分多次 commit 於 `feat/robustness-eval`。

## I. 專案結構重組：FE / DE / BE（2026-06-07）

**動機**：根目錄平鋪雜亂（harness/ eval/ data/ app.py templates/ static/ product_dataset.csv …）。依程式/資料特性分層為 `be/`（後端：harness + eval）、`de/`（資料端：data + product_dataset.csv）、`fe/`（前端：Flask app + templates/static）；meta（config.py/tests/docs/report/…）留根目錄。

**流程與 AI 協作**：brainstorming → spec → **對抗式 self-review（5 讀-only 驗證 agent + 綜整）** → writing-plans → subagent-driven 執行。對抗式審查在動手前攔下 3 個 blocker：(1) `fe/app.py` 已有正確 `__main__` 且 `_build_default()` 已回傳 Flask app（原 spec 誤指示重複包裝 `create_app`）；(2) 只有 `run_full`/`robustness_eval` 有 argparse `--out`，`run_sem`/`retrieval_eval` 硬編寫入路徑；(3) `run_sem`/`retrieval_eval` 無 argparse，`--help` 會落入 `main()` 直打真實 API → 驗證改用 import-only 煙測。另修正 import 計數（128）、`robustness_results_postfix.json` 遺漏、`__pycache__` 陳舊清除等。

**手法**：`git mv`（保留歷史）+ 詞界 sed 改 import 前綴（`harness→be.harness`/`eval→be.eval`/`data→de.data`/`app→fe.app`；`config` 不變）+ `"eval/"→"be/eval/"`。`conftest.py`（root 在 sys.path）、`de/data/catalog.py` 的 CSV 路徑（`dirname(dirname(__file__))`→`de/`）、Flask `Flask(__name__)`（templates/static 隨 app 移）皆**無需改**。進入點：`python -m fe.app`、`python -m be.eval.*`。

**驗證（零行為改變）**：殘留舊前綴 import grep = 0；`python -m pytest -q` 147 passed（含凍結 27 守門）；import/Flask/runner 煙測全過。spec `b5908d7`、plan 見 `docs/superpowers/plans/2026-06-07-repo-reorg-fe-de-be.md`。
