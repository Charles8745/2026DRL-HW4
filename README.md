# 🏍️ RideButler 騎士管家 — 二手重機交易平台 AI 客服 Harness

> **2026 Deep Reinforcement Learning — Homework 4（AI Harness Systems Design）**

以大型語言模型（OpenAI `gpt-4.1-mini`）作為系統控制器，透過 **function calling** 串接平台資料與工具，端到端處理二手重機買家的多步驟客服請求（找車、比規格、查訂單、售後轉真人）。重點在 **system design 思維**——AI 如何 tool use 與 decision-making——而非模型訓練。

---

## 系統架構（Approach B：Router + 工具迴圈）

```
使用者輸入
  → ① Query Rewriter（改寫精準化、解析指代、多意圖偵測）
  → ② Intent Router（5 類意圖分類，含無工具 fallback）
  → ③ Domain Handler（該情境專屬 tool group，manual function-calling 迴圈）
  → ④ Tools（8 個 function）→ DataStore
  ⑤ Memory（session 對話 + 偏好槽）／⑥ Security & Governance（橫切）
```

對齊標準 AI Harness 六大元件：**Prompt / Orchestration / 核心迴圈（Context→Observe→Reason→Act）/ Tools & Skills / Memory / Security & Governance**。完整設計見 [`docs/superpowers/specs/`](docs/superpowers/specs/2026-06-05-ai-harness-motorcycle-customer-service-design.md)。

> 頂層分層：`be/`（後端：harness + eval）、`de/`（資料端：data + product_dataset.csv）、`fe/`（前端：Flask app + templates/static）；`config.py`/`tests/`/`docs/`/`report/` 留根目錄。

## 專案結構

| 路徑 | 說明 |
|---|---|
| `config.py` | 讀 `.env`（`OPENAI_API_KEY` / `OPENAI_MODEL`） |
| `de/data/` | `spec_parser`（規格解析）、`catalog`（型錄＋brand/usage/specs）、`listings`/`orders`（合成）、`store`（DataStore） |
| `be/harness/` | `llm`/`openai_client`、`prompts`、`rewriter`、`router`、`handlers`、`tools`、`memory`、`governance`、`orchestrator` |
| `fe/app.py` | Flask app factory：`GET /`、`POST /api/chat` |
| `fe/templates/`、`fe/static/` | 聊天 UI + Decision Trace 側欄 |
| `be/eval/` | `testset.json`（27 題）、`run_eval.py`（指標 + PASS/FAIL）、robustness/retrieval/sem eval |
| `report/` | 書面報告 + infographic |
| `log.md` | AI 輔助設計與開發歷程 |

## 安裝與設定

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填入你的 OPENAI_API_KEY（從 https://platform.openai.com/api-keys 取得）
```

## 執行

```bash
python -m fe.app                 # 啟動 Flask，開 http://localhost:5000
```
範例輸入：`30萬內想要 Yamaha 跑車`，右側 Decision Trace 會即時顯示 router 判定與工具呼叫。

## 測試

```bash
python -m pytest -q           # 78 個單元測試，全程使用 FakeLLM，不需 API key、不花費用
```

## 評估

```bash
python -m be.eval.run_eval                          # 全部 27 題（需 OPENAI_API_KEY）
python -m be.eval.run_eval --limit 8 --sleep 2      # 分批 8 題、每題間隔 2 秒（避開免費額度 429）
python -m be.eval.run_eval --offset 8 --limit 8     # 下一批（第 9–16 題）
```
輸出 router 準確率 / 任務成功率 / groundedness 違規率 / 延遲 / token 與 PASS。單一題 429 不會中斷整批（記為 error 並續跑）。

## 設計重點

- **LLM 抽象層**：所有 LLM 存取走 `LLM` Protocol，單元測試以 scripted `FakeLLM` 注入 → 測試完全離線、可重現。
- **情境隔離**：4 大情境各有專屬 tool group，Handler 只看得到該情境工具，降低誤用。
- **兩階段確認閘**：`book_viewing` / `create_ticket` / `escalate_to_human` 等狀態變更工具，執行前先回確認摘要、暫停，使用者同意後才執行。
- **Groundedness 護欄**：價格/規格/車況等事實必須來自工具回傳；型錄缺值（如 ZX-10R 馬力）標為「資料未提供」，不捏造。
- **可重現資料**：型錄為真實 33 款車；二手刊登/訂單以固定 seed 合成、單調折舊。
