# Spec — 混合檢索階段：BM25 + 向量(RAG) + Rerank

- 日期：2026-06-07
- 狀態：核准，待實作（已經 6 面向對抗式審查並修正）
- 背景：HW4 「找車推薦」情境目前只有 `search_listings` / `recommend`，兩者皆為**結構化精確篩選**（brand / max_price / year / usage 完全比對 + 依價格排序，見 `harness/tools.py:11-22`）。每款型錄的豐富中文描述（行銷文 + 【規格】）**有載入但完全未用於檢索**（只被 `data/spec_parser.py` 抽成結構化規格，見 `data/catalog.py:37`）。像「新手通勤想省油好停、偶爾跑山」這種**沒有明確結構化條件**的自然語言查詢，現行精確篩選接不住。本 spec 新增一個 **混合檢索階段**（BM25 稀疏 + 向量 RAG + Rerank 重排），補上語意找車能力，並以 ablation 量化每段貢獻。

> 本版已根據對抗式審查修正：(1) `semantic_search` 改回傳**扁平 listing 清單**使 groundedness 與序數指代真正零改動；(2) 移除索引持久化（改記憶體內建索引）；(3) 明列 `test_tool_registry.py` 需同步更新；(4) 修正 find-* 題數與路由邊界；(5) 補上檢索指標的形式定義與標注/ablation 嚴謹度；(6) 釘死 RRF/FakeEmbedder/FakeReranker 的決定性契約。

---

## 1. 目標（兩者並重）

1. **可展示/可量化的管線**：完整實作 BM25 → 向量(RAG) → Rerank 三段檢索，並以 ablation（`BM25 only` → `+向量(RRF)` → `+Rerank`）在報告 §7.4 用 recall@k / MRR / nDCG 量化每段貢獻。
2. **實際搜尋體驗**：把檢索階段**真的接進**「找車推薦」情境，讓使用者用自然語言語意找車（不必明講品牌/車種/價格）。

**全部加法**：不改既有管線四件（rewriter/router/handler 迴圈/orchestrator 主流程）的對外行為。**對 27 題主 eval 無行為回歸**（§7.1–7.3 誠實數字凍結）；既有單元測試保持綠，**惟 `tests/test_tool_registry.py` 的「每群 2 工具」形狀斷言需同步更新**（找車推薦群將有 3 個唯讀工具，見 §5.8、§9）。

---

## 2. 架構與整合

### 2.1 檢索階段 = 唯讀工具 `semantic_search` + 獨立 `HybridRetriever` 元件
既有架構是「Router + 工具迴圈」，handler 由 LLM 決定呼叫哪個工具。最自然、對既有管線動刀最少的整合：在**「找車推薦」工具群**新增唯讀工具 `semantic_search`，背後接獨立的 `HybridRetriever`。

- **這就是 RAG**：`semantic_search` 的工具回傳（命中刈登 + 其車款描述片段）被 append 回 handler 的 messages，LLM 據此生成 grounded 回覆——**檢索到的文字即增強上下文**。
- `HybridRetriever` 是獨立模組，**eval 可不經 LLM 迴圈直接呼叫**（模型層）來跑 ablation。
- **工具選擇（routing tie-break，handler prompt 引導，見 §5.8）**：
  - 查詢**點名 usage（速克達/sport/naked/touring/adventure/cruiser）或品牌，或含任何價格/年份條件（含「便宜」「20萬」之類偏好）** → 走既有 `recommend`/`search_listings`。
  - **僅在完全無上述結構化錨點**（純生活情境/用途/模糊偏好）時 → 走 `semantic_search`。
  - **保護邊界案例**：既有 5 題 find-*（find-01..05）＋ 2 題路由到找車推薦的 multi-*（multi-01/02）皆含明確結構化錨點，應維持原工具。其中 **find-02「有沒有便宜的速克達」、find-05「預算20萬找什麼好」** 是最脆弱的邊界（措辭口語），上述 tie-break 規則就是為了把它們留在 structured 工具。**驗收條件：接線後重跑 27 題 eval，router/task/groundedness 不得回歸（含 multi-01/02 的 `score_multiturn` 鏈計分）。**

### 2.2 三段管線
```
改寫後查詢
 ┌─ HybridRetriever.retrieve()  → 回傳「排序後的車款清單」(供 ablation 與工具) ─┐
 │   ① BM25 稀疏檢索（全 33 篇排序）─┐                                          │
 │   ② 向量(RAG)檢索（全 33 篇排序）─┤→ ③ RRF 融合 → 候選 top-N(預設 10)         │
 │                                  ─┘                                          │
 │   ④ Rerank 重排（LLM listwise）→ top-k 車款(預設 5)                           │
 └──────────────────────────────────────────────────────────────────────────┘
 ⑤（工具層 `semantic_search`）expand_to_listings：把 top-k 車款展開成其「在售」刈登
    (+ 預算/車種結構化過濾) → 回傳**扁平 listing 清單**（非 wrapper dict）
```
- `retrieve()` 的回傳是**車款 dict 清單**（模型層，ablation 用）。
- 工具層再 `expand_to_listings()` 攤平成 listing 清單。**這個 dict-vs-list 的分層是刻意的**：模型層做 IR 指標、listing 層接 groundedness/序數指代。
- 每段有開關（`use_dense`、`use_rerank`）供 ablation；任一段失敗皆**優雅降級**（embedding 失敗→純 BM25；rerank 失敗→RRF 序）。

---

## 3. 語料與文件模型

- **索引單位 = 33 款型錄車款**（非刈登）。豐富描述位於車款層級，且 33 篇互不重複、標注好寫。
- 每篇文件文字（給 BM25 與 embedding）：`f"{title}｜{brand}｜{usage}｜{description}"`。`doc_id = title`。
- **snippet（單一定義，全程共用）**：`description` 中 **【規格】之前的行銷文前 `SNIPPET_CHARS`（預設 200）字**。同一份 snippet 同時用於：reranker 候選的 `snippet` 欄、以及攤平後每筆 listing 的 `match_snippet` 欄（給 LLM 解釋命中原因）。
- **展開為刈登**：取 `store.listings` 中 `model == title 且 status == "在售"` 者，套 `_enrich`（與 `search_listings` 同形狀，含 `asking_price`、`listing_id`、`brand`、`usage`、`specs`），再附 `match_snippet`、`retrieval_rank`（該車款在 top-k 的名次）。
- **無在售車款的處理**：型錄 33 款中 **`XMAX`、`AFRICA TWIN ES` 無任何「在售」刈登**（執行期驗證：31/33 可成交）。`retrieve()` 仍在 33 篇上排序（語意匹配完整），但 `expand_to_listings()` 對無在售車款**貢獻 0 筆 listing**；攤平後清單只含可成交刈登 → 回覆不會宣稱無庫存車款「有現貨」。
- **ablation gold 限制**：§8.1 的 `relevant_models` 只允許**有 ≥1 在售刈登**的車款（排除上述 2 款），由 `test_retrieval_testset` 斷言，避免 recall 被結構性不可成交的 gold 拖低。

---

## 4. 模組佈局（新增）

| 路徑 | 責任 |
|---|---|
| `harness/embedder.py` | `Embedder` Protocol、`OpenAIEmbedder`（text-embedding-3-small）、`FakeEmbedder`（決定性本地向量，測試用）— 與既有 `LLM` Protocol 對稱 |
| `harness/reranker.py` | `Reranker` Protocol、`LLMReranker`（gpt-4.1-mini listwise 重排）、`FakeReranker`（決定性、**不吃 LLM**，測試用） |
| `harness/retrieval/__init__.py` | 匯出 `HybridRetriever` |
| `harness/retrieval/bm25.py` | `BM25Index`：jieba 中文斷詞 + `rank_bm25.BM25Okapi`，`search(query)` → 全 33 篇 ranked `[(doc_id, score)]` |
| `harness/retrieval/vectorstore.py` | `VectorStore`：numpy 矩陣 cosine、`query(qvec, top_n)`（記憶體內，無持久化） |
| `harness/retrieval/retriever.py` | `HybridRetriever`：建索引（建構時 embed）、RRF 融合、三段編排、ablation 開關、`retrieve()` 與 `expand_to_listings()` |
| `harness/tools.py` | 新增 `semantic_search`，掛進「找車推薦」群（唯讀，**不**進 `CONFIRM_REQUIRED`） |
| `eval/retrieval_testset.json` | 語意查詢標注集（gold `relevant_models`，限可成交車款） |
| `eval/retrieval_eval.py` | ablation runner：recall@k / MRR / nDCG（真實 OpenAI；config 3 跑多次取均值） |

> 模組以小型套件 `harness/retrieval/` 切分（多元件、職責清楚），是對既有「一檔一元件」扁平慣例的合理小幅偏離；`embedder.py`、`reranker.py` 維持扁平單檔。**不新增** `data/index/` 或 `eval/build_index.py`（持久化已移出本次範圍，見 §12）。

---

## 5. 元件細節

### 5.1 `Embedder` Protocol（`harness/embedder.py`）
```
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```
- `OpenAIEmbedder`：`__init__(api_key=None, model=None)`（預設 `config.API_KEY` / `config.EMBED_MODEL`）；單次 batch 呼叫 `client.embeddings.create(model=..., input=texts)`；回傳每段向量；API 失敗丟例外（由 `HybridRetriever` 捕捉降級）。
- `FakeEmbedder`：**決定性契約（釘死，供可移植測試）**：維度 `dim`（測試預設 64）；對每個文字取字元 bigram，對每個 bigram `idx = zlib.crc32(bigram.encode()) % dim`、`vec[idx] += 1`（**禁用 Python 內建 `hash()`**，因其加鹽不可重現）；最後 L2-normalize。相近文字向量相近，足以給穩定排序。

### 5.2 `VectorStore`（`harness/retrieval/vectorstore.py`）
- 持有 `doc_ids: list[str]` 與 `matrix: np.ndarray (N, d)`（建構時 L2-normalize 每列）。
- `query(qvec, top_n)`：對 qvec 正規化後算 cosine（矩陣乘法）→ argsort 取 top_n → 回 ranked `[(doc_id, score)]`。**tie-break：分數相同時依 `doc_id` 字典序**（穩定可重現）。
- 純記憶體；無 persist/load（持久化為 future add，介面已可擴充）。

### 5.3 `BM25Index`（`harness/retrieval/bm25.py`）
- `_tokenize(text)`：`jieba.lcut(text)`，去除空白/空字串 token（中文詞級）。
- 以全語料 tokenized docs 建 `BM25Okapi`；`search(query)` → 對 query tokens 取**全 33 篇**分數、排序回 ranked `[(doc_id, score)]`（不截斷，避免「因截斷而 missing」）。tie-break 依 `doc_id` 字典序。

### 5.4 RRF 融合（`retriever.py`）
- BM25 與向量各回**全 33 篇** ranked list。RRF：`score(d) = Σ_r 1/(k_rrf + rank_r(d))`，`k_rrf = 60`，`rank` 自 0 起算（兩 ranker 皆涵蓋全 33 篇 → 無「缺項」問題；`use_dense=False` 時只用 BM25 ranker）。
- 依 RRF 分數降序取候選 top-N（預設 10）。**RRF tie-break：分數相同 → BM25 分數高者優先 → 再 `doc_id` 字典序**（使 `BM25-only` 與融合序皆可重現）。

### 5.5 `Reranker` Protocol（`harness/reranker.py`）
```
class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[dict]) -> list[str]: ...
        # candidates: [{doc_id, title, snippet}]；回傳重排後的 doc_id 清單（best-first）
```
- `LLMReranker(llm)`：把 query + N 個候選（`doc_id` + `title` + 截短 `snippet`）組成 prompt，要求 LLM **只回含 doc_id 的 JSON 陣列**（best-first）。**解析/fallback 契約（釘死）**：以**精確字串比對**把回傳 id 對回候選 `doc_id`；若**任一回傳 id 無法辨識，或可辨識 id 集合 ≠ 輸入候選集合**（含數量不符），則**整批丟棄、保留 RRF 序**、`rerank_skipped=true`，**不做任何模糊比對**（型錄標題含括號/空白，如 `Ninja ZX-4RR (ZX400-S)`）。
- `FakeReranker()`：**不吃 LLM**、決定性。依候選與 query 的 token 重疊數重排；**tie-break：重疊數相同 → 保留輸入（RRF）順序（穩定排序）**。

### 5.6 `HybridRetriever`（`harness/retrieval/retriever.py`）
- `__init__(catalog, embedder, reranker)`：建 docs；建 `BM25Index`；**建構時** `embedder.embed(doc_texts)` 建 `VectorStore`（記憶體內，一次 batch 呼叫）。`DataStore` 不主動建 retriever（避免 import 期打 API），由建構點注入（§5.8）。
- `retrieve(query, k=5, use_dense=True, use_rerank=True) -> list[dict]`（**回車款**，模型層）：
  1. `BM25Index.search(query)` → ranked（全 33）。
  2. 若 `use_dense`：`embedder.embed([query])` → `VectorStore.query` → ranked；embed 失敗 → 記 `dense_skipped=true`、跳過。
  3. 融合：兩 ranker 皆有 → RRF；僅 BM25 → BM25 序 → 候選 top-N。
  4. 若 `use_rerank` 且候選 >1：`reranker.rerank`（失敗/契約不符→`rerank_skipped=true`、保留 RRF 序）。
  5. 取 top-k `doc_id` → 回對應車款 dict（含 `title, brand, usage, specs, snippet, retrieval_rank`）。
- `expand_to_listings(models, budget=None, usage=None) -> list[dict]`（**回扁平 listing 清單**）：
  - **順序**：先在**車款層**完成相關度排序與 top-k（過濾**不**重排相關度）；再對展開後的 listing 套結構化過濾。
  - 對每個 top-k 車款取其「在售」刈登（`_enrich` 形狀 + `match_snippet` + `retrieval_rank`）；`budget` → `asking_price <= budget`；`usage` → 車款 usage == usage（等同模型層 usage 檢查）。
  - 維持「車款相關度序、同車款內依 `asking_price` 升冪」。**某車款 listing 全被過濾掉 → 該車款不貢獻 listing**（仍可能其他車款有）。

### 5.7 `semantic_search` 工具（`harness/tools.py`）
- 簽名：`semantic_search(store, query, budget=None, usage=None)`。
- `models = store.retriever.retrieve(query, k=FINAL_K)`；`listings = store.retriever.expand_to_listings(models, budget, usage)`。
- **回傳 `_ok(listings)`——扁平 listing 清單**（與 `search_listings` 同形狀，每筆另含 `match_snippet`、`retrieval_rank`）；無命中或無在售 → `_ok([])`。
  - **這是修正後的關鍵決策**：回扁平清單使既有 `_facts_from_trace`（list 路徑）自動收集 `asking_price`、且 `set_viewed` 只需把工具名加進既有 tuple → groundedness 與序數指代**真正零改動**。
- 註冊：`TOOL_FUNCS` 加 `semantic_search`；`TOOL_GROUPS["找車推薦"]` 追加 `"semantic_search"`（該群變 3 工具）；`TOOL_SCHEMAS` 新增 schema（`query` required，`budget`/`usage` optional）。**不**進 `CONFIRM_REQUIRED`。
- schema description：「以自然語言語意檢索車款（用途/情境/模糊偏好），回傳相關在售刈登」。

### 5.8 接線與既有檔案的明確改動（逐項）
1. **`harness/tools.py`**：新增 `semantic_search` 與其 schema、加入 `TOOL_GROUPS["找車推薦"]`、`TOOL_FUNCS`、`TOOL_SCHEMAS`（見 §5.7）。
2. **`tests/test_tool_registry.py`（必須更新）**：`test_four_groups_with_two_tools_each` 的 `all(len(v)==2 ...)` 改為允許找車推薦 3 工具（其餘群仍 2）；`test_every_tool_has_callable_and_schema` 的 `schemas_for("找車推薦")` 期望名集合加入 `"semantic_search"`。
3. **`harness/orchestrator.py:71`**：把 `"semantic_search"` 加入 `set_viewed` 的工具名 tuple。因為 `semantic_search` 的 `data` 現在是 **list**，既有 `isinstance(data, list)` 守衛通過，`set_viewed(sid, data)` 正常觸發 → 「第一台」序數指代可用於語意結果（listing 皆含 `listing_id`）。**`_facts_from_trace` 無需改動**（list 路徑）。slot 自動填值（line 74）會讀 `semantic_search` 的 `budget`/`usage` 填偏好槽，屬**預期行為**。
4. **`harness/prompts.py`**：`handler_sys` 為「找車推薦」加 domain 專屬附註（其他 domain 不變），落實 §2.1 的 routing tie-break。
5. **`store.retriever` 注入**：`app.py`、`eval/run_eval.py`、`eval/run_full.py`、`eval/retrieval_eval.py` 在建 orchestrator 時建立 `HybridRetriever(store.catalog, OpenAIEmbedder(), LLMReranker(llm))` 並掛 `store.retriever`。測試注入 `FakeEmbedder()` / `FakeReranker()`（或 `LLMReranker(FakeLLM(...))` 測 LLM 重排路徑）→ 全離線。
6. **執行環境**：所有 `python -m ...` 指令假設**專案 venv（`.venv`，Python 3.10+）**，非系統 `python3`（3.9，且 `python` 不在 PATH）。

---

## 6. 設定與依賴

- **`config.py`**：新增 `EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")`；`.env.example` 補一行。`API_KEY`/`MODEL`/`MAX_TOOL_CALLS_PER_TURN` 不變。
- **`requirements.txt`**：新增（依既有 `>=x,<y` 釘版慣例）`rank_bm25>=0.2,<1.0`、`jieba>=0.42,<1.0`、`numpy>=1.26,<3.0`。注意 **numpy 已由 pandas 傳遞滿足（venv 內 2.2.6）**，明列僅為清晰；**實際需安裝者為 `rank_bm25` 與 `jieba`**。
- **無**重量級 ML 依賴、**無**外部向量 DB server、**無**索引持久化檔。

---

## 7. 錯誤處理（沿用既有慣例）

| 情況 | 處理 |
|---|---|
| embedding API 失敗 / 建索引失敗 | 該次查詢退回純 BM25，trace 記 `dense_skipped: true` |
| rerank 失敗 / LLM 輸出不符契約 | 退回 RRF 序，trace 記 `rerank_skipped: true`（精確比對，不模糊匹配） |
| 查無結果 / 無在售刈登 | 回 `_ok([])`，回覆「目前查無符合的在售車輛」，不捏造 |
| top-k 含無在售車款 | 該車款不貢獻 listing（§3）；回覆不得宣稱其有現貨 |
| groundedness | `semantic_search` 回**扁平 listing 清單**含 `asking_price` → 既有 `_facts_from_trace`（list 路徑）自動收集 → **真正零改動即生效**；缺規格仍標「資料未提供」 |
| injection / input guard | 不變（orchestrator 層、檢索前） |
| 唯讀 | `semantic_search` 不需確認閘 |
| 非決定性 | OpenAI embedding / LLM rerank 即使 temp=0 仍輕微非決定性（同既有 eval 誠實註記）；Fake 版全決定性供測試 |

---

## 8. 評估（報告 §7.4 + §7.5）

### 8.1 ablation 標注集 `eval/retrieval_testset.json`
- ~15–20 條自然語言語意查詢，每條 `{id, query, relevant_models: [title, ...]}`。
- **標注原則**：(a) relevance 以**描述/規格證據**（座高、排氣量、行銷訴求）判定，**不只用 usage label**；(b) gold 集合**小而具體（1–3 款）**，使 recall@1 可達成、避免 usage 大類（naked=12、sport=9）灌大分母；(c) `relevant_models` 只含**有在售刈登**的車款（排除 `XMAX`、`AFRICA TWIN ES`，由 `test_retrieval_testset` 斷言）；(d) 跨 usage 類盡量平衡，**薄類（cruiser=1、touring=2）取樣不足者明示**。
- **誠實定位**：~15–20 題是**方向性/示意基準，非統計顯著**，報告明載此 caveat、不下信賴宣稱。

### 8.2 ablation runner `eval/retrieval_eval.py`
- **指標形式定義（binary relevance）**：
  - `recall@k = |rel ∩ topk| / min(|rel|, k)`（分母取 `min` 使小 k 可達成）。
  - `MRR@10 = 1 / (第一個命中相關車款的名次)`（多相關取首個命中）。
  - `nDCG@5`：gain=1（相關）/0（不相關），`DCG@5 = Σ_{i=1..5} rel_i / log2(i+1)`，`IDCG@5 = Σ_{i=1..min(|rel|,5)} 1/log2(i+1)`，`nDCG = DCG/IDCG`。
- **三配置 ablation**：1) `BM25 only`（`use_dense=False,use_rerank=False`）2) `BM25+向量(RRF)`（`use_dense=True,use_rerank=False`）3) 完整（`+use_rerank=True`）。
- **真實 OpenAI**（比照 `run_full`）。**config 3 的 rerank 非決定性**：config 3 跑 **N=3 次取均值並回報離散度（範圍/標準差）**；config 1/2 決定性跑 1 次即可。報告 §7.4 載明 rerank delta 為**指示性、未做顯著性檢定**（n 小）。
- **候選池天花板**：rerank 只重排 RRF top-10，故 §7.4 另列 **RRF top-10 recall** 作為 rerank 能操作的上限，並說明 rerank 貢獻是「固定候選池內的重排」而非候選召回。
- 輸出三配置對照表 → 報告 §7.4。

### 8.3 端到端 sem-* 案例（主集凍結 + 獨立文件）
- 27 題主 testset **完全不動**（`run_eval.py`/`run_full.py` 皆硬讀 `eval/testset.json`，獨立檔天然隔離）。新增 `test_testset_frozen`：斷言 `testset.json` 仍 27 題（防漂移）。
- 另加 3–5 題 sem-* 端到端案例於**獨立檔** `eval/sem_testset.json`，報告 §7.5 單獨回報「語意查詢能觸發 `semantic_search` 且 groundedness 成立」。
- §7.4/§7.5 比照 §7.1–7.3 **載明 embedding/rerank 的 model id、日期、與非決定性 caveat**。

---

## 9. 測試策略（TDD、全離線）

新增約 18–22 個單元測試，全用 `FakeEmbedder` + `FakeReranker` + `FakeLLM`，**既有單元測試保持綠（除 §5.8.2 的 `test_tool_registry` 兩條斷言同步更新）**：

- `tests/test_embedder.py`：`FakeEmbedder` 決定性（同輸入同向量、crc32 契約）、維度、L2-norm；`OpenAIEmbedder` 以 monkeypatch 驗證（不打真 API）。
- `tests/test_vectorstore.py`：已知向量 cosine 排序；`doc_id` tie-break 決定性。
- `tests/test_bm25.py`：jieba 斷詞；中文詞命中；全 33 篇排序。
- `tests/test_reranker.py`：`FakeReranker` 決定性重排與 tie-break；`LLMReranker` 以 `FakeLLM` 測 prompt/解析；**契約測試**（未知 id / 數量不符 / 重複 → 整批 fallback、`rerank_skipped`）。
- `tests/test_retriever.py`：RRF 融合數學 + tie-break；ablation 開關改變管線；embedder 拋錯→純 BM25 降級；`expand_to_listings` 只展開「在售」、budget/usage 過濾、無在售車款貢獻 0 筆、相關度序。
- `tests/test_tools_semantic.py`：回**扁平 list**、僅在售、`listing_id`/`match_snippet`/`retrieval_rank` 存在、budget 過濾、空結果 `_ok([])`。
- `tests/test_handlers.py` / `tests/test_orchestrator.py`（擴充）：scripted FakeLLM → 語意查詢觸發 `semantic_search`；`set_viewed` 納入語意結果並可序數指代「第一台」；retrieved 價格 groundedness 通過（驗證 `_facts_from_trace` 對 list 形狀有效）。
- `tests/test_retrieval_eval.py`：recall@k / MRR / nDCG 公式（tiny fixture，含 `|rel|<k`、`|rel|>k` 邊界）。
- `tests/test_retrieval_testset.py`：schema 驗證 + 每個 `relevant_model` 存在於型錄**且有在售刈登**。
- `tests/test_tool_registry.py`：更新後仍綠（找車推薦 3 工具）。
- `tests/test_app.py` 或既有：`test_testset_frozen`（27 題）。

---

## 10. 報告 / log 整合

- 報告 §2 架構圖加入檢索階段（① BM25 / ② 向量 / ③ RRF / ④ Rerank / ⑤ 工具層展開刈登）。
- 新增 §7.4 retrieval ablation 表（三配置 × recall@k/MRR/nDCG + RRF top-10 recall 天花板 + rerank 均值±離散度）；§7.5 sem-* 端到端結果。皆載 model id/日期/caveat。
- `log.md` 追加本功能建置紀錄（仿既有 §F 風格）。

---

## 11. 預設參數

| 參數 | 預設 | 說明 |
|---|---|---|
| 候選 N | 10 | RRF 後送入 rerank 的候選數（亦為 rerank 天花板候選池） |
| 最終 k（`FINAL_K`） | 5 | 回傳車款數 |
| RRF `k_rrf` | 60 | 標準值 |
| `SNIPPET_CHARS` | 200 | snippet 取 description 行銷文前 N 字 |
| recall@ | {1,3,5} | ablation |
| MRR | @10 | 首個命中 |
| nDCG | @5 | binary gain |
| ablation config 3 重跑次數 | 3 | 取均值±離散度（rerank 非決定性） |
| `FakeEmbedder` 維度 | 64 | 測試用 |

---

## 12. 不在本次範圍

- **向量索引持久化**（persist/load、corpus_hash、`data/index/`、`eval/build_index.py`）—— 33 篇於建構時一次 batch embed（<1s），持久化為 gold-plating 與失敗面；列為 future add（`VectorStore` 介面已可擴充）。
- 改用 `sqlite-vec` / `chromadb` brand-name 向量資料庫（介面已預留，可一檔替換）。
- 本地 sentence-transformers / cross-encoder（方案2/3）。
- 新增購車指南 / FAQ 知識庫。
- multi-03「車款比較→刊登預約」橋接（既有 future work）。
- 刈登異動即時重建索引（索引以型錄為準）。
- 把 sem-* 案例混入主 27 題 testset（已決定主集凍結）。

---

## 13. 新增依賴

實際安裝：`rank_bm25>=0.2,<1.0`、`jieba>=0.42,<1.0`（numpy 已由 pandas 滿足，於 requirements 明列 `numpy>=1.26,<3.0` 以利清晰）。無重量級 ML 依賴、無外部向量 DB server。
