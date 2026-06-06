# Spec — LLM 後端遷移：Gemini → OpenAI (gpt-4.1-mini)

- 日期：2026-06-06
- 狀態：核准，待實作
- 取代：原設計 `docs/superpowers/specs/2026-06-05-ai-harness-motorcycle-customer-service-design.md` 中「LLM 後端 = Google Gemini」之決策。

## 1. 背景與動機

原系統以 Google Gemini（`gemini-2.0-flash`）為 LLM 後端。實際執行 evaluation 時發現可用的 Gemini API key 免費額度被異常限縮：`gemini-2.0-flash` 免費額度為 0（`limit: 0`）、`gemini-2.5-flash-lite` 僅 20 requests/day，而 27 題 eval 需約 110–135 次 API 呼叫，無法跑出完整端到端指標。

使用者改提供 OpenAI API key（付費、有真實額度）。本 spec 將後端**整個替換**為 OpenAI `gpt-4.1-mini`，以便：(1) 真正跑出 report §7 的端到端指標；(2) 順帶證明 `LLM` Protocol 抽象是可插拔的（系統設計賣點）。

## 2. 為何成本極低（關鍵洞察）

- 所有 LLM 存取統一走 `LLM` Protocol：`generate(system, messages, tools=None) -> LLMResponse`。
- handler 工具迴圈（`harness/handlers.py`）以**純文字**回填工具結果（`{"role":"user","content":"工具 X 回傳：…"}`），**未使用 Gemini 專屬的 function_response 結構** → message 歷史是 provider-neutral 的 role/content。

因此只需新增一個實作 Protocol 的 `OpenAIClient`，rewriter/router/handlers/orchestrator **一行不動**。70 個離線單元測試以 `FakeLLM` 注入、與後端無關 → 不受影響。

## 3. 設計

### 3.1 `harness/openai_client.py`（新增）
`OpenAIClient.generate(system, messages, tools=None) -> LLMResponse`：
- **訊息映射**：prepend `{"role":"system","content":system}`；歷史中 `user`→`user`，其餘→`assistant`。
- **schema 轉接**（純函式 `_to_openai_tools`）：Gemini `{name, description, parameters}` → OpenAI `{"type":"function","function":{name, description, parameters}}`。
- **回傳解析**：`choices[0].message.content` → text；`message.tool_calls[*]` 的 `function.arguments`（JSON 字串）→ `ToolCall(name, dict)`；JSON 解析失敗 → `{}`。
- **參數**：`temperature=0`（eval 可重現）、有 tools 時 `tool_choice="auto"`、`parallel_tool_calls=False`。
- **token**：`usage.total_tokens`。
- 介面與 `GeminiClient` 對齊（`__init__(api_key=None, model=None)`，預設取 `config.API_KEY`/`config.MODEL`）。

### 3.2 `config.py`
- env 改讀 `OPENAI_API_KEY`、`OPENAI_MODEL`（預設 `gpt-4.1-mini`）。
- **屬性名 `API_KEY` / `MODEL` 不變**（維持後端中立的抽象），`MAX_TOOL_CALLS_PER_TURN` 不動。

### 3.3 建構點（3 處）
`app.py`、`eval/run_eval.py`（main）、`eval/run_full.py`：`GeminiClient(...)` → `OpenAIClient(...)`。

### 3.4 相依與清理
- `requirements.txt`：`google-genai>=1.0,<2.0` → `openai>=1.0,<2.0`。
- 刪除 `harness/gemini_client.py`（git 歷史可回溯）。
- `.env.example`：`OPENAI_API_KEY` / `OPENAI_MODEL=gpt-4.1-mini`。

## 4. 測試（TDD，離線、不需 key）
新增 `tests/test_openai_client.py`，以 fake OpenAI client（注入 `.client`）驗證：
- schema 轉換形狀正確；
- 訊息映射（system 置頂、assistant 角色）；
- tool_call 解析（arguments JSON→dict、多個→list、壞 JSON→`{}`）；
- token 萃取；
- 純文字（無 tool_calls）回應。
更新 `tests/test_config.py` 斷言為 `gpt-4.1-mini` / `OPENAI_MODEL`。預期總數 70 → ~75 全綠。

## 5. 文件（全庫徹底替換）
README、report/report.md、report/infographic.html、HANDOFF.md、log.md、`docs/superpowers/specs/*`、`docs/superpowers/plans/*`、.env.example 內所有 `Gemini`/`gemini-2.0-flash`/`google-genai` → `OpenAI`/`gpt-4.1-mini`/`openai`。dated specs/plans 以本 spec 為準同步更新。

## 6. 端到端驗收
key 就位後 `python -m eval.run_full` 跑全 27 題 → 以真實 OpenAI 指標（router_accuracy / task_success / groundedness_violation_rate / avg_latency / avg_tokens / PASS + 各情境分解）取代 report §7 的「配額受限」註記，標明 backend = OpenAI `gpt-4.1-mini`。

## 7. 不在本次範圍
- multi-* 兩輪 eval 強化（task 2 brainstorm 暫停，遷移完成後續做）。
- 任何 handler/router/rewriter 邏輯變更。
