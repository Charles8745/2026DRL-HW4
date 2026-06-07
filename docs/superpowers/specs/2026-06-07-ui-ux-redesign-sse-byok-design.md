# RideButler UI/UX 重新設計 — SSE 即時管線 + BYOK + 視覺改版（設計簡報）

> 日期：2026-06-07　|　狀態：設計定稿（待使用者複審 → writing-plans）
> 範圍：把現有極簡聊天 UI 升級為可公開 demo 的「高度視覺化」AI 客服，含三大支柱：**視覺改版（風格 C）**、**即時管線視覺化（真實 SSE）**、**使用者自帶 OpenAI 金鑰（BYOK）**，並產出部署設定檔（Render）。
>
> 本簡報由 brainstorming + 一個 6 維度 × 3 對抗式審查鏡頭的 workflow 產生並對照原始碼驗證。已吸收 **6 個 critical + 9 個 high** must-fix。

---

## 0. 確定決策（brainstorming 結論）

| # | 決策 | 結論 |
|---|---|---|
| 管線即時性 | SSE vs 重播 | **真實 SSE 串流**（orchestrator 加 `on_step` 觀察點，逐步即時 emit） |
| BYOK | 收/存/防護 | **強制 gate + 瀏覽器 sessionStorage + header-only**，伺服器每請求短暫用、永不落地 |
| 部署範圍 | 做到哪 | **demo-ready + 部署設定檔 + 指南**（不實際 push） |
| 部署主機 | 哪家 | **Render**（附 `render.yaml`），通用 Docker 亦可 |
| 版面 | A/B/C | **A · 三區指揮中心**（左 rail｜中聊天卡片內嵌｜右即時管線） |
| 美學 | A/B/C | **C · 暖光高級感 · 賽車綠 + 金** |
| Hero 裝飾圖 | 來源 | 使用者提供 6 張真車照（純裝飾） |
| 車卡圖 | 來源 | **本地優先（會放幾張常見車）→ 原廠 media_url → 賽車綠剪影 placeholder** |
| 中文用語 | usage/condition | 採建議版（見 §5.1） |
| 金鑰驗證 | 時機 | **首訊 401 回報**（不加 liveness 端點） |
| demo 模式 | 語意 | `DEMO_MODE` 僅 UI；`ALLOW_ENV_KEY` 為唯一 .env 回退授權且限 localhost |

**非目標**：不改 LLM/檢索演算法；不動凍結基準（27 題 testset + report §7.1–7.3、40 題 robustness）；不重寫 harness 邏輯；不實際 push 上主機；不引入前端框架/打包器。

---

## 1. 架構總覽

RideButler 是**單一長駐實例**的 Flask 應用：實質狀態（`SessionStore._sessions`、per-request `DataStore` 的 tickets/orders、語料向量索引、SSE 長連線）都在進程記憶體 → **不可 serverless、不可多 worker**。

核心策略：**觀察式零行為變更**。`process()` 維持同步、回傳 dict 與控制流逐字不變，只新增**預設 `None` 的 `on_step` 觀察回呼**；`on_step=None` 時與今日位元相同（147 Fake-based 測試與凍結基準 0 漂移）。BYOK 金鑰只活在瀏覽器 `sessionStorage`，以 header `X-RideButler-Key` 隨每請求傳入，伺服器**每請求建獨立 `Orchestrator`**（共享 `SessionStore` + 共享唯讀 catalog + 進程級快取向量，但**各自獨立可變 `DataStore`**）後即丟，永不入 log/trace/SSE。

```
瀏覽器 (sessionStorage: rb_key)
  ① 首載 → ByokGate 強制輸入金鑰
  ② fetch + ReadableStream  POST /api/chat/stream   header: X-RideButler-Key
        ▼
fe/app.py  ──extract_request_key()──▶ validate_key_format() ──▶ build_request_orchestrator(key)
  per-request:  llm=OpenAIClient(key)  embedder=OpenAIEmbedder(key)  reranker=LLMReranker(llm)
                store = per-request DataStore (catalog 共享唯讀; listings/orders/tickets 各自複本)
                store.retriever = HybridRetriever(catalog, embedder, reranker, vstore=CORPUS_CACHE.get_or_build(...))
                                                  └ 33-doc 向量只算一次、非機密、進程快取、失敗不快取
        ▼
StreamRunner.run(orch, sid, msg)
  └ daemon thread:  orch.process(sid, msg, on_step=queue.put)   ← 唯一新增程式路徑
       guard → (pending) → rewrite → route → (fallback | run_handler tool-loop) → memory → final
       on_step 於每 stage 邊界「事後」emit PipelineEvent（_emit 深拷貝 + scrub 金鑰 + 吞例外）
       run_handler(..., on_step) emit tool_call/tool_result
       HybridRetriever.retrieve(..., on_substep) emit bm25→vector→rrf→rerank（唯讀快照）
  └ generator:  queue.get() → sse_frame() → yield；heartbeat ': ping'；finally 必 emit error?+done
        ▼
PipelinePanel(右側 live stepper)  +  ChatLog inline ListingCard(中央，從 final trace 權威渲染)
```

三大跨維度衝突的解法：
- **SSE ↔ gunicorn**：`gthread` worker（sync 會緩衝整段回應毀掉串流）、`workers=1`（程式內硬鉗）、SSE route 加 `X-Accel-Buffering: no` / `Cache-Control: no-store`。
- **BYOK ↔ corpus-cache ↔ 併發**：金鑰只進 client 建構子；語料向量進程快取且**失敗不快取**；**每請求獨立 DataStore + Orchestrator**，消除 `store.retriever` 共享 swap 競態。
- **Panel ↔ trace fields**：live panel 用串流的輕量 `result_summary`（唯讀投影）；**inline 卡片只從 final event 的完整 trace 權威渲染**（單一資料源）。

---

## 2. 後端設計

### 2.1 觀察式 on_step / on_substep（零行為變更）

**`be/harness/orchestrator.py`**（唯一新增程式路徑；append-only 參數）
```python
OnStep = Callable[[str, dict], None]   # on_step(event_type, data) -> None

def process(self, sid: str, user_input: str, on_step: "OnStep | None" = None) -> dict:
    ...  # 控制流與回傳 dict 逐字不變；僅於各 stage「事後」呼叫 self._emit(...)

def _emit(self, on_step, etype: str, data: dict) -> None:
    if on_step is None:
        return                              # 硬 no-op：等同今日位元
    payload = _scrub(copy.deepcopy(data))   # 唯讀深拷貝 + scrub 金鑰；絕不就地改 listing dict
    try:
        on_step(etype, payload)             # 吞所有例外 → 觀察者隔離
    except Exception:
        pass
```
emit 點（嚴格在既有回傳值算完之後）：`guard` →（`confirmation_resume`）→ `rewrite` → `route` →（`fallback`）→ `memory` → `final`；`done`/`error` 由 StreamRunner 補。

**`be/harness/handlers.py`**：`run_handler(llm, store, domain, query, budget, on_step=None)`（最後一參）。執行 `TOOL_FUNCS[call.name](...)` 前 emit `tool_call`、後 emit `tool_result`；CONFIRM_REQUIRED 短路時 emit `tool_call` + `proposed` result。

**`be/harness/tools.py`**：`semantic_search(store, query, budget=None, usage=None, on_substep=None)`，把 `on_substep` 透傳給 `store.retriever.retrieve(...)`。**保持 FLAT list 回傳不變**（專案硬約束）。

**`be/harness/retrieval/retriever.py`**：`retrieve(self, query, k=FINAL_K, use_dense=True, use_rerank=True, on_substep=None)`（最後一參）。
> **純唯讀 callback**：只把 `retrieve()` *已算出的* 中間清單（`bm25.search`、`vstore.query`、`_rrf`、reranker 輸出）以**唯讀參照**傳給 `on_substep`，**絕不重排/重切/重呼叫**（reranker 非決定性，重呼叫會雙花費並漂移凍結 ablation）。沿用既有 `dense_skipped`/`rerank_skipped` 旗標；BM25-only/降級路徑必須 emit 真實 skipped 狀態（panel 不可說謊）。

### 2.2 SSE 端點與事件協定

**`fe/sse.py`**（NEW）：`sse_frame(event, data) -> "event:..\ndata:<json ensure_ascii=False>\n\n"`、`sse_comment() -> ": ping\n\n"`。

**`fe/streaming.py`**（NEW）：`StreamRunner`（daemon thread + `queue.Queue` + heartbeat）。
- `try/except/finally` **必 emit `error`(已 redact)?+`done` sentinel** → 串流永不卡死。
- `finally` 顯式丟棄 OpenAIClient/embedder/orchestrator 參照、清空 queue（金鑰 in-heap 壽命 == 本輪）。
- 設 OpenAI client request timeout + 每輪 wall-clock 上限（即便 gunicorn timeout=0）。
- 偵測 client 斷線（`GeneratorExit`）→ 合作式取消 worker；限制同時串流數。

**SSE event JSON 契約**（`event: <type>\ndata: <json ensure_ascii=False>\n\n`）：
```
guard:        {blocked, reason|null}
rewrite:      {rewritten_query, resolved_listing_id|null, tokens}
route:        {label, tokens}
fallback:     {reply_preview}
tool_call:    {name, args, index}                      # 執行前點亮
tool_result:  {name, index, ok, error|null, proposed?, result_summary}
              # result_summary 唯讀投影：listing 含 listing_id/model/brand/asking_price/year/
              #   condition/match_snippet?/retrieval_rank?（無 media_url，見 §6）
retrieval:    {phase:'bm25'|'vector'|'rrf'|'rerank', skipped, top:[{title,score|null,rank}], k}
confirm_gate: {tool_name, args, stage:'proposed'|'executed'|'cancelled', tool_result?:{ok,error}}
memory:       {viewed_count, slots:{budget,brand_pref,usage,pending_intent}}   # 無 history、無金鑰
final:        {reply, blocked, awaiting_confirmation, router_label, resolved_listing_id,
               tokens, trace:{完整 process() 回傳 trace}}
done:         {session_id, elapsed_ms}
error:        {message(已 redact), where}
```
**安全鐵則**：payload 走 per-kind 白名單；`api_key`/`Authorization`/system prompt/原始 message array 永不出現；scrub 集中在 `_emit`；測試斷言任何 frame 不含 `sk-`。

### 2.3 BYOK 每請求建構 + 語料嵌入快取

**`be/harness/retrieval/corpus_cache.py`**（NEW）
```python
class CorpusEmbeddingCache:
    # 進程級單例；threading.Lock + per-key double-checked build lock
    def get_or_build(self, embed_model, doc_ids, texts, embedder) -> "VectorStore | None":
        # hit  → 回快取 VectorStore（不嵌入、不需金鑰）
        # miss → 鎖內 re-check → embedder.embed(texts) 一次 → 成功才存
        # 例外 → 回 None 但「不存」（transient miss，下個有效請求重試）  ← 不毒化
```
只存 numpy 向量 + doc_ids（catalog 33 標題），**零金鑰素材**。`embed_model` 伺服器固定為 `config.EMBED_MODEL`（單一快取條目）。

**`be/harness/retrieval/retriever.py`** 加 append-only kwargs：`__init__(self, catalog, embedder, reranker, *, vstore=None)`。給 `vstore` → 重用快取向量、不再 build-time embed；不給 → 行為與今日位元相同（保 147 測試 + 凍結 eval）。

**`fe/keyauth.py`**（NEW，或併入 `fe/app.py`）
```python
extract_request_key(req, *, allow_env) -> str | None   # header X-RideButler-Key only；allow_env 才回退 config.API_KEY
validate_key_format(key) -> bool                        # ^sk- 開頭、len>=20、無空白；僅 UX 預檢非安全控制
redact_key(text, key) -> str                            # 字面 key + 通用 sk-[A-Za-z0-9_-]{20,} → 'sk-***REDACTED***'
build_request_orchestrator(key, *, model, embed_model, memory, corpus_cache) -> Orchestrator
    # per-request DataStore（catalog 共享唯讀；listings/orders/tickets 複本）；per-request Orchestrator
```

**`fe/app.py` 路由**
- `POST /api/chat`（改）：header 取 key → 無效回 401 `{error:'missing_key'|'invalid_key'}`；建每請求 orchestrator；`orch.process(sid, message)`（簽章不變）。回應加 `Cache-Control: no-store, Pragma: no-cache`。
- `POST /api/chat/stream`（NEW，SSE）：同上取 key → `StreamRunner.run(...)` → `Response(gen, mimetype='text/event-stream', headers={'Cache-Control':'no-store','X-Accel-Buffering':'no','Connection':'keep-alive'})`。
- `GET /api/config`（NEW）：回 `{demo: bool, models:{...}, media:{<catalog title>: <media_url>}}` — 供前端 title→media_url 對照（見 §6，避免改 trace）。
- **不提供** `/api/key/verify` liveness（消除驗證 oracle + 省花費；金鑰錯誤靠首訊 401 回報）。
- **不提供** body `api_key` channel（header-only）；請求進 `process()` 前先 strip body 內任何 `api_key`/`authorization` 形狀欄位。

**`config.py`** 加：`ALLOW_ENV_KEY`（唯一授權 .env 回退、預設關、且僅 localhost / 顯式 public override 生效）、`DEMO_MODE`（僅 UI：跳 modal 顯 banner、**不授權** config.API_KEY）。**不動** `API_KEY/MODEL/EMBED_MODEL/MAX_TOOL_CALLS_PER_TURN`。

### 2.4 零行為變更 + 凍結基準保證

| 機制 | 保證 |
|---|---|
| `on_step`/`on_substep` 預設 None 且為最後一參 | eval（×5 位置呼叫）、147 測試以原簽章呼叫 → 不受影響 |
| `_emit` 在 None 時硬 no-op | `process(sid,inp)` 位元等同今日 |
| `_emit` 深拷貝 + 不就地改 listing dict | trace.data / `viewed_listings`(ordinal) / eval `_facts_from_trace` 價格事實不被汙染 |
| retriever 唯讀快照、禁 enrichment | `retrieval_results.json` 三組 ablation 排名位元不變 |
| eval 直接 import harness、從不 import `fe.app` | BYOK/SSE 觸不到凍結數字 |
| BYOK 走每請求 DataStore；eval 維持單一共享 DataStore | robustness orders/tickets delta 計分不變 |
| token footer 只讀 final trace.tokens、不加總串流事件 | 不雙計、不漂移 |

---

## 3. 前端視覺系統與版面（風格 C · 三區）

**美學**：暖光高級感、賽車綠 + 金。奶油底 `#f3efe6`、白卡、深賽車綠主色 `#1d6b4f`、金 `#b8860b` **稀缺保留**給 wordmark／價格數字／stepper done 金環／語意命中徽章。zh-Hant copy（經 humanizer-zh-tw 過一遍避免機翻味）。**無框架/無打包器**（vanilla ES modules）；字型自託管（Fraunces 顯示 / Noto Sans TC 內文子集 / Space Mono trace），離線可用。

### 3.1 Design tokens（`fe/static/css/tokens.css` — 單一真相源）
色彩、字級（1.25 major-third、16px base、`--fs-display: clamp(40px,6vw,68px)` … `--fs-xs:11.5px`）、間距（4px base `--sp-1..8`）、圓角、陰影（`--sh-card`/`--sh-pop`）、動態（`--ease-out:cubic-bezier(.16,1,.3,1)`、`--ease-spring`、`--dur-fast:140ms`/`--dur:240ms`/`--dur-slow:420ms`）、z-index。**component CSS 不得出現裸 hex**（lint 守則）。

### 3.2 三區指揮中心
`grid-template-columns: 64px minmax(0,1fr) 400px`（rail / center / panel）。`data-view='landing|chat'` 驅動 landing→chat；`data-panel='open|collapsed'` 驅動右欄收合。
- **左 IconRail**（深綠）：金色 RB monogram、`新對話`、`對話`、`管線`(toggle)、`說明`、底部 `金鑰狀態`點（綠=BYOK／琥珀=demo）+ reset。每鈕 `aria-label`。**不做「收藏」**（`viewed_listings` 每輪覆寫，非真收藏）。
- **中央 ChatLog**（視覺主角）。
- **右 PipelinePanel**（glanceable，非 study-able）。

### 3.3 Landing → Chat（招牌時刻；序列化動態，解 UX high）
Landing = Shop 風：wordmark「RideButler / 騎士管家 · 二手重機智慧客服」、中央 search pill、4 個 zh 建議 chips（`30萬內 Yamaha 跑車`／`新手通勤省油好停`／`比較 CB650R 與 MT-07`／`查訂單 O001`）、背景 6 張漂浮 hero 車卡（裝飾、`aria-hidden`、缺檔自隱）。
動態腳本：
1. 送出 → 先跑 FLIP morph（pill→docked composer，`--dur-slow --ease-out`）、hero 卡 stagger 60ms 淡出；
2. morph 完成**後才開** SSE 串流；
3. panel **立即**渲染全 idle skeleton（永不空白）；
4. `guard` 無 LLM → ~50ms 內翻 done 給即時生命感；
5. `rewrite` 等待期 active-shimmer 為有界 loop + 誠實「思考中…」affordance（真實首 token 1–3s 不顯凍結）。
全部 gated 於 `prefers-reduced-motion`。

### 3.4 Inline ListingCard（中央 signature 物件）
從 `search_listings`/`recommend`/`semantic_search` 的 enriched row 渲染：`model`(標題)、`asking_price`(NT$ 金色)、`year`、`mileage_km`、`condition`(A/B/C badge + **zh** 釋義)、`location`、`seller`、`usage`(**zh** chip)、`specs` 前 2–3 顆 pill、`match_snippet` + `retrieval_rank`(`語意命中 #n`，僅 semantic)。
- **zh 標籤源**（`fe/static/js/labels.js`，唯一真相源，見 §5.1）。
- **空結果**（critical）：`data:[]` 時**不渲染 deck**，改渲染 zh 空態卡「目前沒有符合條件的車輛」+ 2–3 個放寬建議 chips（`放寬到 XX 萬`／`看其他品牌`）。panel 仍顯 tool_call done(ok)，但聊天必須明說零結果。
- **卡片動作**（解 memory 語意衝突）：`查看規格`/`預約看車`/`比較` 以 **`listing_id` 顯式 prefill**（如 `幫我約看 listing_id=Lxxx`），**不用「第N台」ordinal**（`set_viewed` 每輪覆寫，舊 deck 點擊會 mis-book）。orchestrator 已支援 `（指定 listing_id=...）` 注入。superseded deck 的動作可禁用。

### 3.5 BYOK Gate（強制 modal）
首載若無 `sessionStorage.rb_key` 顯示 `<dialog>`：password input(mono)、`記住於此瀏覽器分頁`說明、`開始使用`、`如何取得金鑰`連結。client 端 `validateKeyFormat`，存 `sessionStorage` 後清空欄位；`ApiClient` 每請求帶 `X-RideButler-Key`。401 → 清 key、重開 modal（shake）。金鑰**永不**入 DOM 文字／trace drawer／console。demo 模式改顯琥珀 banner。

### 3.6 檔案組織
```
fe/templates/index.html          重寫：三區 skeleton + <dialog byok> + landing + 字型 preload
fe/static/css/{tokens,base,layout,landing,chat,pipeline,components}.css
fe/static/js/main.js             entry：boot Gate/Shell/ChatLog/Panel，wire composer/landing→SseClient
fe/static/js/api.js              ApiClient(header) + SseClient(fetch ReadableStream + 非串流 fallback) + /api/config
fe/static/js/labels.js           USAGE_ZH / CONDITION_ZH / TOOL_LABELS / INTENT meta（唯一顯示真相源）
fe/static/js/components/{listingCard,pipeline,chat,byok,landing}.js
fe/static/fonts/                 自託管 woff2（Noto Sans TC 子集 等）
fe/static/img/hero/              6 張 hero 裝飾圖（使用者放置）
fe/static/img/bikes/             車卡本地圖（使用者放幾張常見車）
（舊 fe/static/style.css / app.js 由上述取代，或留 no-op shim）
```

---

## 4. 管線視覺化資料契約

### 4.1 有序步驟分類（1:1 對應真實 stage）
`guard 安全檢查` → `rewrite 查詢改寫` → `route 意圖路由` →（`fallback 範圍外回應`）→ `tool_call 工具呼叫·<zhName>`(×N) →（`retrieval 混合檢索`，**僅 semantic_search 子步**）→ `confirm_gate 需要確認/已確認/已取消` → `memory 記憶更新` → `done 完成`。

`TOOL_LABELS`：search_listings=條件篩選、recommend=預算推薦、semantic_search=語意檢索、get_listing_detail=刊登詳情、compare_models=規格比較、check_order=訂單查詢、book_viewing=預約看車、create_ticket=建立工單、escalate_to_human=轉接真人。
`router.LABELS`（5 closed set）：找車推薦／規格比較／交易訂單／售後轉真人／閒聊範圍外。

### 4.2 四條路徑的事件序列（逐行對照 orchestrator.py）
- **BLOCKED**（trace={}）：`guard(blocked)` → `final` → `done`（0 LLM call）
- **PENDING-確認/取消**（無 LLM）：`confirmation_resume(executed|cancelled)` → `final` → `done`
- **FALLBACK**（steps=[]）：`guard` → `rewrite` → `route` → `fallback` → `memory` → `done`
- **DOMAIN tool-loop**：`guard` → `rewrite` → `route` → [`tool_call`(+`retrieval` 若 semantic)]×N →（`confirm_gate(proposed)` 若 CONFIRM_REQUIRED）→ `memory` → `done(awaiting?)`

### 4.3 Client 狀態模型（reducer-driven）
```
PipelineState = { turnId, steps:Step[], byId, status:'streaming'|'awaiting_confirmation'|'done'|'error' }
Step = { id, kind, label, status:'idle'|'active'|'done'|'error', payload, parentId?, elapsedMs? }
reduceEvent(state, ev): active→upsert active；done→done+elapsedMs；error→error。
  retrieval 以 parentId 掛在 semantic_search tool_call 下。未知 kind→generic node（前向相容）。
```
- **解 D3↔D4 衝突**：landing 完整路徑可顯預期 skeleton；**blocked / confirm 短路徑純由收到事件驅動**（不可顯永不觸發的 idle 節點，否則 panel 說謊）。
- confirm_gate 跨輪：turn A `proposed` → turn B `executed|cancelled`，以 `done.awaiting_confirmation` 維持單一 gate 節點。
- **chat-dominant 階層**：tool args/result JSON、retrieval 子步、raw-trace `<details>` 預設收合；靜止時只見 step 標籤 + 狀態點 + IntentChip + token/timing footer；done 後 panel 可自動收為 slim 摘要。
- **token footer** 只讀 final trace.tokens（FakeLLM 下誠實顯示 0）。

---

## 5. 顯示用語與標籤

### 5.1 zh 標籤（`fe/static/js/labels.js`，唯一真相源；經 humanizer-zh-tw）
```js
export const USAGE_ZH = { sport:'仿賽', naked:'街車', touring:'休旅',
                          adventure:'冒險探險', scooter:'速克達', cruiser:'美式巡航' };
export const CONDITION_ZH = { A:'近全新', B:'良好', C:'堪用' };
```
（usage/condition 原始資料為英文 enum，無 zh map；以上為使用者核可版。）

---

## 6. 圖片策略

### 6.1 Hero 裝飾（6 張，使用者放置）
`fe/static/img/hero/`：`grom.jpg`、`super-cub.jpg`、`cb650r.jpg`、`gold-wing.jpg`、`gsx-r.jpg`、`hayabusa.jpg`。純裝飾、`aria-hidden`、lazy、`onerror` 自隱（缺檔不顯破圖）。

### 6.2 Listing 卡圖：local-first 三層 fallback（解 critical media_url 缺口）
**已驗證**：`media_url`/`uri` **只在 catalog**，`_enrich()` **不複製** → trace 裡 listing row **沒有** media_url。故採 **client-side title→media_url map（不改 trace）**：`GET /api/config` 回 `media:{<catalog title>: <media_url>}`，卡片以 `listing.model`(== catalog title)查圖。

**三層鏈（`resolveListingImage`）**：
```
['/static/img/bikes/'+slug+'.webp',
 '/static/img/bikes/'+slug+'.jpg',
 upgradeHttp(mediaMap[title]),        // http://→https:// 修 Kawasaki 混合內容；Honda 無副檔名自然 onerror 落下
 INLINE_SVG_PLACEHOLDER]              // 賽車綠剪影 data-URI；零網路、永不破
```
- `slugify(title)`：lowercase、去括號/空白、NFKD、收斂 `[a-z0-9-]`（如 `Ninja ZX-4RR (ZX400-S)`→`ninja-zx-4rr-zx400-s`），`data-slug` 輸出供除錯。
- `attachFallback(img, candidates)`：`onerror` 推進索引；**鏈尾恆停 placeholder，推過界仍停 placeholder**（單元測試守門）。
- 所有 listing/hero `<img>` 加 `referrerpolicy="no-referrer"`。
- **誠實註記**：未放本地圖時 Honda(13/33) 與 Kawasaki-https-失敗會偏 placeholder；使用者已同意**放幾張常見車本地圖**，其餘 placeholder 帶 per-brand tint + 車名 overlay（看起來刻意設計而非空白）。Honda 無副檔名 URL 瀏覽器可能仍以 content-type 載入成功（先試再 onerror）。

---

## 7. 部署（Render + 通用 Docker；不實際 push）

**單一實例理由**：`SessionStore._sessions`、`CORPUS_CACHE`、語料向量索引、SSE 長連線皆進程內。多 worker → 各自分歧複本（session/ticket/索引各算一次、ordinal 失效）→ `workers=1` + 單實例，排除 serverless。

**新檔（純增量，不改任何 .py harness 邏輯）**：
- `wsgi.py`：`import config` 後 `app = create_app(...)`（BYOK-aware，免真金鑰即可 boot；`assert not app.debug`）。
- `gunicorn.conf.py`：`worker_class='gthread'`（非 sync，避免緩衝；非 gevent 以免 monkeypatch openai SDK socket）、`threads=8`(env)、`workers=1`（讀 `WEB_CONCURRENCY` 但**硬鉗為 1**、boot self-check 拒 >1）、`timeout=120`／`graceful_timeout=30`／`keepalive=5`、`chdir=repo root`、log→stdout/stderr（**不記 request body、不記 key**）。
- `Procfile`：`web: gunicorn --config gunicorn.conf.py wsgi:app`。
- `render.yaml`：Render web service（Docker 或 native、單實例、health check `/`、env `DEMO_MODE`/`ALLOW_ENV_KEY` 預設 0、**不設 `OPENAI_API_KEY`**）。
- `Dockerfile`：`python:3.10-slim`、`WORKDIR /app`、`pip install -r requirements.txt`、`COPY .`、`ENV PYTHONUNBUFFERED=1`、CMD 同 Procfile。
- `.dockerignore`：排除 `.venv .git __pycache__ .pytest_cache .env .env.* .superpowers HANDOFF.md`。
- `requirements.txt`：加 `gunicorn>=21,<24`（gthread 內建，無額外依賴）。
- `docs/DEPLOY.md`：單實例理由、SSE-safe gunicorn、**粗體警語「生產 = 僅 BYOK，公開主機絕不設 `OPENAI_API_KEY`」**、env 表、Render 步驟（含免費層冷啟動註記）、通用 Docker 步驟、serverless-out。
- `.env.example`：`DEMO_MODE=0`、`ALLOW_ENV_KEY=0`（+ MODEL/EMBED_MODEL）。

**SSE-safe 鐵則**：stream route 必帶 `X-Accel-Buffering: no` / `Cache-Control: no-store` / `Connection: keep-alive`；generator 定期 `: ping`；hard per-turn wall-clock 上限。所有帶 key 的 route 一律 `no-store`。

**安全旗標硬化**：`DEMO_MODE` 僅 UI、**不授權** config.API_KEY；`ALLOW_ENV_KEY` 為唯一 .env 回退授權，且僅 localhost（或顯式 `ALLOW_ENV_KEY_PUBLIC=1`）生效；boot 若「`ALLOW_ENV_KEY` + 非空 `API_KEY` + `0.0.0.0` bind」同時成立 → 顯著 WARNING（不含 key），non-debug 下考慮拒啟。進程級 `logging.Filter` 對每筆 LogRecord 跑 `redact_key`。

---

## 8. 測試策略

**基準閘門**：每次新增前後跑 `.venv/bin/python -m pytest -q`，確認 147 既有測試恆綠、計數為 `147 + 新測試`、0 回歸。**不碰** `test_testset.py`/`test_robustness_testset.py`/`test_run_eval.py`/`test_robustness_eval.py`/`be/eval/*results*.json`。所有新測試只用 `Fake*`/spy，**0 真實網路**。

**核心零行為變更守門（最重要一條）**
`tests/test_orchestrator_stream.py::test_on_step_none_is_identical` — 同腳本 FakeLLM 跑兩次（`on_step=None` vs collector），deep-equal 整個回傳（reply/blocked/awaiting/`trace` 含 `trace.tokens`），涵蓋 guard / pending-yes / pending-cancel / fallback / recommend / semantic 六路徑。

**新測試檔**
- `test_orchestrator_stream.py`：各路徑事件序列；guard/pending 路徑 emit 事件但 `o.llm.calls==0`；semantic 出 `retrieval` 子步且 `dense_skipped/rerank_skipped` 對；觀察者拋例外不改回傳；**唯讀斷言**：streamed turn 後 `trace.steps[i].tool_result.data` 與 None 版 deep-equal、`memory.get(sid)['slots']['viewed_listings']` 仍含完整 listing dict。
- **golden-ranking 守門**：FakeEmbedder/FakeReranker 下，`retrieve(query,k=10,use_dense,use_rerank)` 三組 ablation 輸出在「加 on_substep 前後位元相同」。
- `test_app_sse.py`：`/api/chat/stream`（test_client + FakeLLM）→ 200 + `text/event-stream`；frame 有序、final trace == `/api/chat` 同輸入 trace；**`X-RideButler-Key` 值不在任何 frame / resp.data**；無 key + 非 demo → 401 zh 錯誤無串流；`/api/chat` JSON 回歸不變；過短 FakeLLM 在 drain timeout 內以 `error+done` 收尾（不卡死）。
- `test_byok.py`：spy factory 斷言用「請求 key 而非 config.API_KEY」；`CorpusEmbeddingCache` 兩次呼叫 embed 恰一次且回同物件；**失敗不毒化**；`vars()` 掃無 key；`ALLOW_ENV_KEY` 非 localhost 不回退（401）；**2-thread spy-embedder 並發**斷言各請求只用自己的 embedder；**並發確認不雙執行**。
- `test_image_resolver`（JS/node 或 Python 對映）：跑全 33 真 catalog row；slug 規則；鏈序 local→remote→placeholder；`http://`→https upgrade；鏈尾恆 placeholder、推過界不無限 onerror。
- `test_secret_safety.py`：sentinel `sk-LEAKCANARY` 穿 build/streamed/JSON turn → 不在 `json.dumps(trace)`／任何 SSE frame／resp.data／`caplog.text`；**含「key 誤填進 message」案例**（斷言 scrub 自 `raw_input`/`rewritten_query`）；trace 無 `api_key/openai_key/authorization` 鍵名。

**回歸金絲雀（不改）**：`tests/test_app.py`（`create_app(orchestrator)` + `/api/chat` 形狀）、`tests/test_orchestrator.py`（兩參數呼叫各路徑）。`conftest.py` 維持只 `sys.path.insert`；SSE frame 解析放 `tests/_sse_util.py`。

---

## 9. 風險登記簿（6 critical / 9 high 全已吸收）

| # | 風險 | 嚴重 | 緩解 |
|---|---|---|---|
| R1 | DEMO_MODE/ALLOW_ENV_KEY 使公開部署變燒主人金鑰的開放代理 | Critical | 拆兩旗標；ALLOW_ENV_KEY 限 localhost/顯式 override；boot 危險組合 WARNING/拒啟；DEPLOY 粗體警語；測 `test_no_env_key_fallback_on_public` |
| R2 | 共享 `store.retriever` swap 並發競態 → 用到別人 embedder/key | Critical | 每請求獨立 DataStore + Orchestrator；絕不改共享 store.retriever；2-thread spy 並發測試 |
| R3 | CorpusEmbeddingCache 首請求失敗永久毒化 dense | Critical | 例外回 None **不存**；per-key double-checked build lock；失敗不毒化測試 |
| R8 | retriever instrumentation 觸動凍結 ablation 排名 | Critical | 唯讀 on_substep；禁重排/重切/重呼叫；golden-ranking 測試 |
| R12 | trace 無 media_url → 圖片三層退兩層、全卡 placeholder | Critical | client-side title→media_url map（/api/config）；鏈尾恆 placeholder |
| R13 | 空結果 panel 顯成功但聊天空白 | Critical | 空態卡 + 放寬建議 chips；data:[] 不渲染 deck |
| R4 | 金鑰誤入 message → 送 OpenAI / 存 history / echo trace | High | header-only、移除 body channel、process 前 strip、對 raw_input/rewritten_query 跑 redact、誤填測試 |
| R5 | SSE worker thread 持金鑰超過請求壽命 | High | finally 丟參照清 queue、request timeout、wall-clock 上限、GeneratorExit 取消、限並發 |
| R6 | debug/SDK 例外/快取洩漏金鑰 | High | 非本地 bind 強制 debug=False（wsgi assert）；全路徑 no-store；進程級 logging redaction filter |
| R7 | client-chosen session_id 無 ownership → 可執行受害者 confirm gate / 雙執行 | High | per-sid owner token、per-sid lock 包 pending_action 讀改寫、不雙執行測試 |
| R9 | trace/memory listing dict 別名共享 → 就地改毀 eval + ordinal | High | `_emit`/summary builder 嚴格唯讀（deepcopy/新 dict）；完整性測試 |
| R10 | gunicorn sync worker 緩衝 → SSE 退化成一次性突發 | High | gthread；X-Accel-Buffering:no；事件序列測試 |
| R14 | usage/condition 無 zh 違反 locked zh-Hant | High | labels.js 權威 USAGE_ZH/CONDITION_ZH |
| R15 | landing→chat 與 panel 動態未定義/真實首 token 顯凍結 | High | 序列化動態（morph→開串流）、即時 skeleton、guard 快翻 done、reduced-motion gate |
| R16 | panel 過重壓過中央卡片 | High | 子步/JSON/raw drawer 預設收合；done 後自動收 slim |
| R19 | StreamRunner worker 例外致串流卡死 | High | try/except/finally 必 emit error?+done sentinel；drain-timeout 測試 |
| R11 | 平台覆寫 workers>1 → 索引/session 分裂 | Medium | gunicorn.conf 硬鉗 workers=1、boot self-check 拒 >1、DEPLOY 標明 |
| R17 | 卡片動作用「第N台」ordinal 但 viewed 每輪覆寫 → mis-book | Low→Med | 改 listing_id 顯式 prefill；舊 deck 動作可禁用 |
| R18 | 原廠圖 hotlink 403/referrer 洩漏/混合內容 | Medium | local-first + referrerpolicy=no-referrer + https upgrade；遠端僅 best-effort |
| R20 | screen reader 被串流卡片洗版 | Medium | 每輪簡潔 aria-live 摘要；動畫 panel aria-hidden/live=off；rail aria-label |

---

## 10. 分階段實作順序（里程碑）

每個里程碑結束都重跑 `pytest -q`（恆 `147+N` 綠）作為硬閘門。

1. **M0 後端觀察層（純內部）**：`on_step`/`on_substep` 加進 `process`/`run_handler`/`semantic_search`/`retrieve`（全 default None、append-only）+ `_emit` scrub/唯讀。先寫 `test_on_step_none_is_identical` + golden-ranking 守門，**跑 147 綠 + 凍結基準 0 漂移**。← 最高風險，先做、解鎖一切。
2. **M1 BYOK 核心**：`corpus_cache.py`（失敗不毒化）+ `HybridRetriever(vstore=)` + `keyauth`（extract/validate/redact）+ `build_request_orchestrator`（每請求 DataStore/Orchestrator）。測 `test_byok`（含並發 spy）。
3. **M2 SSE 端點**：`fe/sse.py`、`fe/streaming.py`（finally sentinel/取消/timeout）、`/api/chat/stream`、`/api/config`、`/api/chat` 加 key 與 no-store。測 `test_app_sse` + `test_secret_safety`。
4. **M3 前端視覺系統**：tokens/base/layout/字型 → IconRail/三區 shell → ByokGate → ApiClient/SseClient。
5. **M4 互動內容**：ChatLog + ListingCard（labels.js zh、空態卡、listing_id 動作、圖片三層鏈）+ PipelinePanel（reducer、collapsed 子步、IntentChip）。測 image_resolver + reducer。
6. **M5 Landing 招牌時刻**：hero 卡 + search pill + 序列化動態（morph→串流）+ reduced-motion + a11y。
7. **M6 部署**：`wsgi.py`/`gunicorn.conf.py`（硬鉗 workers=1）/`Procfile`/`render.yaml`/`Dockerfile`/`.dockerignore`/`requirements`/`DEPLOY.md`/`.env.example` + 旗標硬化 + logging redaction filter。本地 gunicorn + `curl -N` SSE 驗證 + docker build/run smoke。
8. **M7 收尾**：全測試 + 凍結基準回歸再跑；瀏覽器 a11y/responsive/SSE-not-buffered 手動 smoke；更新 `report/`、`log.md`、`README.md`、`HANDOFF.md`。

---

## 11. 開放問題（已全數拍板）

1. zh 用語 → **採建議版**（§5.1）。
2. 本地車圖 → **放幾張常見車本地圖 + 其餘 premium placeholder**。
3. 部署主機 → **Render**（`render.yaml`）。
4. 金鑰驗證 → **首訊 401**（不加 liveness 端點）。
5. demo 模式 → `DEMO_MODE` 僅 UI、`ALLOW_ENV_KEY` 限 localhost（安全預設）。
