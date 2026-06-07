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

## J. UI/UX 重新設計：SSE 即時管線 + BYOK + 視覺改版（2026-06-07）

**動機**：決策過程原本是事後一次性的 Decision Trace 側欄，看不到「正在發生」；且原型只能用主人金鑰跑，無法安全公開。本輪把它升級成 **SSE 即時串流的三區指揮中心**，並讓系統以 **BYOK（自帶金鑰）** 安全運行於公開環境。

**流程與 AI 協作**：brainstorming → 設計 spec（`docs/superpowers/specs/2026-06-07-ui-ux-redesign-sse-byok-design.md`）→ 對抗式審查（吸收 6 critical／9 high 風險，逐項對應守門測試）→ writing-plans（M0–M7 里程碑）→ subagent-driven TDD。三項使用者拍板：風格 C·三區指揮中心、BYOK header-only、local-first 圖片 fallback。

**關鍵設計決策（與理由）**：
1. **觀察層 append-only、default `None`、位元零行為變更**：`on_step`/`on_substep` 加進 `process`/`run_handler`/`semantic_search`/`retrieve`，`None` 時與改版前位元相同。最高風險先做（M0），以 `test_on_step_none_is_identical` deep-equal 六路徑回傳鎖死。理由：絕不為了「可觀察」而動到凍結基線或 eval 行為。
2. **`_emit` 唯讀快照**：`copy.deepcopy` + 鍵名 scrub，retriever `on_substep` 只回已算好結果的唯讀引用、禁重排/重切/重呼叫（golden-ranking 守門）。理由：trace/memory 的 listing dict 別名若被就地改動會同時毀掉 eval 與序數指代（R9）。
3. **BYOK 每請求建構、絕不改共享 `store.retriever`**：每請求獨立 DataStore＋Orchestrator（共享唯讀型錄、複製 listings/orders/tickets）。理由：共享 retriever swap 是並發競態根源（R2）——用別人的 embedder/金鑰。
4. **語料嵌入快取失敗不毒化**：`CorpusEmbeddingCache` 例外回 `None` 且不存、per-key double-checked lock。理由：首請求暫時失敗不該永久毒化 dense 檢索（R3）。
5. **金鑰 header-only + 全路徑 scrub + logging redaction filter**：移除 body 通道、`process()` 前 strip、對 `raw_input`/`rewritten_query` 跑 redact、進程級 log filter。理由：金鑰誤入 message 會被送 OpenAI／存 history／echo 進 trace（R4/R6）。
6. **圖片 local-first 三層 fallback**：trace 不帶 `media_url`（`_enrich` 不複製），故 title→media_url map 改由 `/api/config` 提供，鏈尾恆 inline SVG placeholder、推過界不無限 onerror（R12/R18）。
7. **單實例 SSE-safe 部署**：gunicorn `gthread`、workers 硬鉗為 1（boot self-check 拒 >1）、`X-Accel-Buffering: no`；公開主機**絕不**設 `OPENAI_API_KEY`（生產＝BYOK only，R1）。理由：sync worker 會把 SSE 緩衝成一次性突發（R10）、多 worker 會分裂索引/session（R11）。

**回歸保證（M7 全測試 + 凍結基準回歸）**：
- `.venv/bin/python -m pytest -q` → **240 passed**（147 既有 + 新增 SSE/BYOK/安全/部署/JS-mirror 測試），0 failed、0 真實網路（全 `Fake*`/spy）。
- 凍結基準一字未動：27 題主 eval、40 題 robustness、`be/eval/*results*.json` 的守門（`test_testset`/`test_robustness_testset`/`test_run_eval`/`test_robustness_eval`）全綠；`git diff main` 對這些檔為空。
- 最關鍵守門 `test_on_step_none_is_identical` 單獨重跑 PASS：六路徑回傳含 `trace.tokens` deep-equal。
- `node --test 'fe/static/js/__tests__/*.test.mjs'` → 43 pass / 0 fail（注意：Node v22 上 bare-dir 形式 `node --test fe/static/js/__tests__/` 會 MODULE_NOT_FOUND，須用 glob）（圖片解析 33 真 catalog row + slug 規則 + 鏈序 + http→https + 鏈尾恆 placeholder；pipeline reducer active→done→error + retrieval 巢狀 + unknown→generic）。

**手動瀏覽器 smoke（M7.3；本地 `python -m fe.app`，無 DOM 測試框架故以人工檢查點佐證）**：

| 檢查點 | 預期 | 觀察 |
|---|---|---|
| SSE 不緩衝（`curl -N` / Network EventStream） | frame 逐步抵達（guard→rewrite→route→tool_call/result＋retrieval 子步→memory→final→done），非一次性突發；無 frame 含 `sk-` | PASS（離線佐證；不打真實 API）。app 於 `127.0.0.1:5000` 啟動（`localhost:5000` 在本機被 macOS AirTunes 佔用回 403，改用 `127.0.0.1`）。streaming 路由回傳 `mimetype=text/event-stream` 並帶 `X-Accel-Buffering: no`＋`Cache-Control: no-store`，StreamRunner 對每個 on_step 事件即 yield 一個 `event: …\ndata: …\n\n` block、worker 跑在 daemon thread、`finally` 恆補 `done` sentinel；orchestrator 實際 emit 的 kind＝guard/rewrite/route/tool_call/tool_result/memory/fallback/final，retriever `on_substep` emit `bm25→vector→rrf→rerank`（`retrieval` phase）；`StreamRunner.run` 對 worker 例外以 `redact_key` 過濾後才送 error frame，frame 不含金鑰。 |
| BYOK 閘強制 + 格式預檢 | 載入即 modal-open；壞格式 key 本地擋（不發網路）；合法格式但錯誤 key 放行到送出 | PASS。`fe/templates/index.html` 有 `<dialog data-byok aria-labelledby="byok-title">`，byok.js `open()` 呼 `dialog.showModal()`（modal-open、focus 入 input）。`_onSubmit` 先 `e.preventDefault()` → `validateKeyFormat`（`^sk-`、len≥20、無空白）；壞格式（如 `hello`）→ 顯示「金鑰格式不正確（需 sk- 開頭、長度足夠、且無空白）」＋ shake，**直接 return、不寫 sessionStorage、不發任何 fetch**。合法格式 key 才 `sessionStorage.setItem('rb_key', …)`＋清空 input＋關閉閘＋觸發 `onReady`，送出時由 ApiClient 經 header 帶出。伺服端對壞格式 key 亦 defence-in-depth：`curl -H "X-RideButler-Key: hello"` → 401 `{"error":"invalid_key","message":"金鑰格式不正確，請重新輸入。"}`。 |
| 401 reopen + shake | 錯誤 key 送出 → 401、閘重開並抖動；payload/response 無 `sk-` echo | PASS。無 key 送 `/api/chat/stream` → `HTTP 401`、JSON `{"error":"missing_key","message":"請先設定您的 OpenAI 金鑰再開始對話。"}`、回應**不含** `sk-`／key（grep `sk-|api_key|authorization` = 0）。client `onUnauthorized()`：`sessionStorage.removeItem('rb_key')` 丟棄金鑰 → `_markRail('demo')` → `open()` 重開閘 → 顯示「金鑰無效或已被拒絕，請重新輸入」→ `_shake()`（移除/reflow/重加 `shake` class 重啟動畫，且 shake 受 `prefers-reduced-motion` gate）。金鑰只活在 sessionStorage 區域變數，password input 送出後立即清空、從不入 log。 |
| 空結果卡 + 放寬 chips | 零在售結果顯空態卡（非空白訊息）＋放寬 chips；`data:[]` 不渲染幻影 deck | PASS。`renderDeck(rows, …)` 對 `!Array.isArray(rows) || rows.length === 0` 走 `renderEmptyCard`——回明確空態卡 `<article class="listing-card empty-card">`：標題「目前沒有符合條件的車輛」＋提示「試試放寬預算、品牌或車種：」＋ `relaxChips`（「放寬到 30 萬」「放寬車種」等 `chip chip--relax` 按鈕，點擊以對應 prefill 重入 `runTurn`）。`data:[]` 因此渲染空態卡而非幻影 deck（R13）。 |
| 圖片 fallback 鏈（強制破圖） | `onerror` 推進 local.webp→local.jpg→遠端(https)→inline SVG placeholder；鏈尾恆 placeholder、不無限 onerror；`referrerpolicy="no-referrer"`＋`data-slug` 存在 | PASS。`imageResolver.js`：`buildCandidates(title, mediaUrl)` 產 `['/static/img/bikes/<slug>.webp', '…/<slug>.jpg', upgradeHttps(mediaUrl), INLINE_SVG_PLACEHOLDER]`——`upgradeHttps` 把 `http://`→`https://`（修 Kawasaki mixed-content），鏈尾恆 inline SVG racing-green placeholder（純 data URI、零網路）。`attachFallback(img, candidates, slug)` 設 `img.referrerPolicy='no-referrer'`＋`img.dataset.slug=slug`，`onerror` 逐一推進；推到 placeholder（鏈尾）後 onerror **不再動作**（不無限 loop，R18）。`/api/config` 提供 33 筆 title→media_url 餵入鏈中段。 |
| a11y reduced-motion | 啟用後 landing morph 招牌動態關閉、改瞬時切換；面板仍可用 | PASS。`landing.js` `motionPolicy(reduced)`：`reduced=true` → `{morph:false, heroStagger:false, openStreamAfterMs:0}`（不跑 FLIP morph／hero stagger、立即切 chat 並開串流）；`reduced=false` → `{morph:true, heroStagger:true, openStreamAfterMs:420}`（先 morph `--dur-slow` 完成才開串流）。`byok.css`／`landing.css` 各有 `@media (prefers-reduced-motion: reduce)` block（shake/動態降級為瞬時）。面板功能不依賴動畫，靜止後照常運作。 |
| a11y aria-live + 鍵盤 | 每輪簡潔 aria-live 摘要（非洗版）；動畫面板 aria-hidden；rail 有 aria-label；Tab/Enter 全可達可操作、閘開時焦點受困 | PASS。單一 polite live region `#rb-live`（`aria-live=polite` `aria-atomic=true`、視覺隱藏 SR 可讀），每輪只 `announce` 一句簡潔摘要（`找到 N 台車輛`／`目前沒有符合條件的車輛`／`已完成回覆`），串流卡片不洗版（R20）。`setPanelA11y(panel, animating=true)` 對動畫中的 PipelinePanel 設 `aria-hidden=true`＋`aria-live=off`，靜止後移除 aria-hidden（stepper 永不自播、摘要走 `#rb-live`）。`<nav class="rail" aria-label="主導覽">`＋每顆 rail 按鈕有 aria-label（新對話/對話/切換管線面板/說明/重設金鑰），裝飾 brand `aria-hidden`。閘為 `<dialog>` `showModal()`（原生焦點受困 + Esc/背景不可互動）；composer 為 `<form>`＋`<button type="submit" aria-label="送出">`，Tab 可達、Enter 送出；卡片動作為真 `<button>`，鍵盤可操作。 |
| responsive | 三區 grid 在 375px/1440px 皆適配、無水平溢出、卡片重排 | PASS。`layout.css` `#app` `grid-template-columns: var(--rail-w) minmax(0,1fr) var(--panel-w)`＝`64px minmax(0,1fr) 400px`（tokens.css 定義 `--rail-w:64px`／`--panel-w:400px`）。`@media (max-width:1100px)` 把第三欄鉗為 `0`＋`.panel { transform: translateX(100%) }`（panel 收合滑出、rail 仍在），故 375px 窄屏單欄無水平溢出；1440px 寬屏三欄完整。listing-deck `grid-template-columns: repeat(auto-fill, minmax(260px,1fr))` 隨寬度自動重排卡片。 |

**真實瀏覽器整合驗證（控制者親跑 Playwright/Chromium、端到端；上表 8 檢查點為 M7.3 離線+程式碼佐證，此處為控制者真實瀏覽器佐證）**：所有 M0–M7 的單元/元件/node 測試與每任務兩階段審查都綠，但整合層仍有 **4 個只有真實瀏覽器才現形的缺口**（headless 元件測試與程式碼審查皆漏），逐一以真實 app（`python -m fe.app`，demo 模式本機 .env key）驗證並修復：
1. `main.js`（M3.7 早於 M4/M5 撰寫）**從未把** `mountLanding`／`ChatLog`／`PipelinePanel`／reducer／`runSignatureMoment` 接起來，只 dispatch 無人消費的事件 → 重寫 boot 接線（`aa8d2d2`）。
2. `api.js` **未回送** M2.7 後端要求的 `X-RideButler-Owner` token → 多輪第二輪 403 → 加 owner-token round-trip（`5df47c9`）。
3. `index.html`（M3.8）**漏 link** `chat/pipeline/landing/components` 四個 CSS → UI 無樣式（top-left、未置中）→ 補 link（`719be2d`）。
4. `chat.css` 用了**不存在的 token 名**（`--color-*`/`--space-*`/`--radius-*` → fallback 到硬寫深色 `#161616`）→ 聊天區深色不符風格 C → 改回真 token（`--c-*`/`--sp-*`/`--r-*`）、亮色白卡、零裸 hex（`fe786e6`）。

修復後端到端實測通過：landing（置中襯線 wordmark＋賽車綠搜尋膠囊＋4 chips＋demo banner）→ 真實查詢「30萬內 Yamaha 跑車」→ SSE 管線逐步點亮（意圖 chip「找車推薦」、真實 `tokens 1686 · 5974ms`）→ 兩張車卡載入**真實原廠照**（三層 fallback 命中 media_url）＋金色價格＋車況 badge → 多輪（點「查看規格」→ `listing_id` prefill 第 2 輪）**無 403** → user 泡泡賽車綠／bot 泡泡純白（風格 C 確認）。**教訓**：per-milestone 綠燈 ≠ 整合可用；跨里程碑的 boot-wiring／回應 header round-trip／CSS link／token 命名一致性，必須以真實瀏覽器把關。hero 浮動圖（`fe/static/img/hero/`）與自託管字型（`fe/static/fonts/`）為使用者待放的二進位檔——缺檔時優雅降級（hero 卡自隱、字型 fallback 系統字），demo 不放也可用。

**成果**：240 離線測試全綠（含凍結 27＋40 守門）＋全 JS 純邏輯套件 0 fail＋手動 smoke 8 檢查點通過＋控制者真實瀏覽器端到端驗證通過（修復 4 個整合缺口）。spec `docs/superpowers/specs/2026-06-07-ui-ux-redesign-sse-byok-design.md`，實作分 M0–M7 多次 commit 於 `feat/ui-ux-redesign`。
