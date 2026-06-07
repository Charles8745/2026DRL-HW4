# Spec — 專案結構重組：FE / DE / BE 三層資料夾

- 日期：2026-06-07
- 狀態：核准，待寫實作計畫（brainstorming 已完成、使用者核准設計）
- 背景：專案根目錄檔案/資料夾雜亂（`harness/ eval/ data/ app.py templates/ static/ product_dataset.csv config.py …` 平鋪）。依「程式/資料特性」重組成 **`fe/`（前端）、`de/`（資料端）、`be/`（後端）** 三個分層資料夾，提升可讀性。**純結構搬移、零行為改變**：147 個離線測試與凍結基線（27 題主 eval、40 題 robustness）全程保持綠。

> 設計決策（brainstorming 確認）：(1) 範圍＝只移核心程式/資料，meta（`tests/ docs/ report/ config.py conftest.py requirements.txt README.md .env.example log.md`）留根目錄；(2) eval 程式＋其資料集都進 `be/`；(3) 採小寫 Pythonic 套件名 `be/de/fe`；(4) 採用「機械式前綴改名 + 巢狀分組」方案（git mv 保留歷史、import 前綴整批替換、conftest 不動）。

---

## 1. 目標與鐵則

1. **依特性分層**：把核心程式/資料移入 `fe/`（Flask UI）、`de/`（資料層）、`be/`（AI harness + evaluation）三個分組資料夾，根目錄只留專案 meta。
2. **零行為改變**：不改任何邏輯，只搬檔 + 改 import 前綴 + 改硬編路徑。**搬完後全 `python -m pytest -q` 必須仍 147 passed**（含 `test_main_testset_frozen_at_27` 與 robustness 守門）。
3. **保留 git 歷史**：所有搬移用 `git mv`。
4. **不破壞進入點**：`python -m pytest`、Flask 啟動、四支 eval runner 在新路徑下皆可正常執行。

---

## 2. 目標佈局（巢狀分組；分組夾內保留原套件名）

```
be/                      # 後端：AI harness + evaluation
  __init__.py            # 新（空）
  harness/               # 由 harness/ 移入（orchestrator/llm/tools/governance/prompts/memory/
                         #   rewriter/router/handlers/openai_client/embedder/reranker/retrieval/）
  eval/                  # 由 eval/ 移入（run_eval/run_full/run_sem/retrieval_eval/robustness_eval
                         #   + *_testset.json + results.json/sem_results.json/retrieval_results.json
                         #   + robustness_results.json + robustness_results_postfix.json）
de/                      # 資料端：領域資料層
  __init__.py            # 新（空）
  data/                  # 由 data/ 移入（catalog/listings/orders/store/spec_parser）
  product_dataset.csv    # 由根目錄移入
fe/                      # 前端：Flask UI
  __init__.py            # 新（空）
  app.py                 # 由根目錄移入
  templates/             # 由根目錄移入（index.html）
  static/                # 由根目錄移入（app.js / style.css）

# 留在根目錄（meta，不分層）：
config.py  conftest.py  tests/  docs/  report/  README.md  requirements.txt  .env.example  log.md  HANDOFF.md(gitignored)
```

- 分組夾 `be/de/fe` 各為一個套件（含空 `__init__.py`）；其下保留原套件 `harness`/`eval`/`data` 名稱（與 `be` 需同時容納 `harness`+`eval` 對稱，故 `de` 也採 `de/data/` 巢狀）。
- 原有 `harness/__init__.py`、`harness/retrieval/__init__.py`、`eval/__init__.py`、`data/__init__.py` 隨套件一起移動。
- **整夾搬移、不逐檔列舉**：用 `git mv harness be/harness`、`git mv eval be/eval`、`git mv data de/data` 等（先 `mkdir -p be de fe` + 建空 `__init__.py`），確保所有產物（含 `robustness_results_postfix.json` 等未在清單逐一列名者）一併移動，不遺漏。

---

## 3. import 與路徑轉換（機械式，128 import 站點 / 46 檔）

### 3.1 import 前綴對應（套用於每個 `from X …` / `import X`）
| 舊 | 新 |
|---|---|
| `harness` | `be.harness` |
| `eval` | `be.eval` |
| `data` | `de.data` |
| `app` | `fe.app` |
| `config` | **不變**（`config.py` 仍在根目錄） |

- 前綴改寫須同時涵蓋**模組頂層 import**（如 `run_full.py` 9 個、`run_sem.py` 8 個皆在頂層；`robustness_eval.py` 為 2 頂層 + 8 內層）**與函式內縮排的延遲 import**（如 `app.py:_build_default`、`run_eval.py`/`retrieval_eval.py` 的 `main()` 內）。**勿只改 `main()` 內而漏掉頂層**。
- `harness.retrieval...` 自動隨 `harness`→`be.harness` 變為 `be.harness.retrieval...`（前綴替換即可）。
- **建議用 AST/詞界改寫（libcst/rope）或詞界 regex**，而非單純行首錨定 regex，以對未來的逗號多重 import 穩健。

### 3.2 硬編檔案路徑（runner + 測試）
- 所有 `open("eval/…json")` → `open("be/eval/…json")`（CWD 仍為專案根，與現行慣例一致）。涵蓋**讀**與**寫**兩種。
  - 讀取站點：`run_eval.py`、`run_full.py`、`run_sem.py`、`retrieval_eval.py`、`robustness_eval.py`（各讀其 testset）及 `tests/test_testset.py`、`test_retrieval_testset.py`、`test_robustness_testset.py`。
- **結果檔寫入路徑分兩種（勿只 grep `--out`）**：
  - (a) **argparse `--out` 預設（僅 2 支）**：`run_full.py`（`eval/results.json`→`be/eval/results.json`）、`robustness_eval.py`（`eval/robustness_results.json`→`be/eval/robustness_results.json`）。
  - (b) **硬編於 `open(...,'w')`（無 `--out`，須直接改字串）**：`run_sem.py:72`（`eval/sem_results.json`→`be/eval/sem_results.json`）、`retrieval_eval.py:93`（`eval/retrieval_results.json`→`be/eval/retrieval_results.json`）。
  - 註：`run_eval.py` 無 `--out`、不寫結果檔（只 `print`/`json.dumps` 到 stdout）。
- **`tests/test_app.py:5` `from app import create_app` → `from fe.app import create_app`**：這是 `app` 套件的**唯一** consumer，雖被 §3.1 通則涵蓋，但在此明列以免漏改（它在 147 綠的守備範圍內）。
- **使用者可見字串/docstring（zero-drift，須一併改）**：`retrieval_eval.py:95` 的 `print("\nwrote eval/retrieval_results.json")`→`be/eval/...`；docstring 內舊指令 `retrieval_eval.py:1`、`run_sem.py:6`（`python -m eval.run_sem`→`python -m be.eval.run_sem`）。

### 3.3 不需改的耦合（重要）
- **`de/data/catalog.py` 的 CSV 路徑不改**：現為 `os.path.join(os.path.dirname(os.path.dirname(__file__)), "product_dataset.csv")`；`__file__=de/data/catalog.py` → parent-of-parent = `de/` → 找到 `de/product_dataset.csv`。**自動正確**。
- **`conftest.py` 不改**：`sys.path.insert(0, dirname(__file__))` 加入專案根；`be/de/fe/config` 皆在根層 → 測試可 import `be.*`/`de.*`/`fe.*`/`config`。
- **Flask 不改邏輯**：`Flask(__name__)` 於 `fe/app.py` → `root_path=fe/` → 自動找 `fe/templates`、`fe/static`。

---

## 4. 進入點（指令變更）

| 舊指令 | 新指令 |
|---|---|
| `python app.py` | `python -m fe.app` |
| `python -m eval.run_full` | `python -m be.eval.run_full` |
| `python -m eval.run_eval` | `python -m be.eval.run_eval` |
| `python -m eval.run_sem` | `python -m be.eval.run_sem` |
| `python -m eval.retrieval_eval` | `python -m be.eval.retrieval_eval` |
| `python -m eval.robustness_eval` | `python -m be.eval.robustness_eval` |
| `python -m pytest -q` | 不變 |

- `python -m fe.app`：以模組執行使根目錄在 `sys.path` → `be.*`/`de.*`/`config` 可解析。`fe/app.py` **已有正確的 `if __name__ == "__main__": _build_default().run(debug=True, port=5000)` 區塊，且 `_build_default()` 已回傳 Flask app（`return create_app(Orchestrator(...))`）——請勿改寫、勿再用 `create_app()` 包一層**（重複包裝會把 Flask app 塞進 `app.config["ORCH"]`，使 `/api/chat` 在請求時 `AttributeError`）。本步驟只搬檔 + 改 import 前綴，不動 `__main__` 邏輯。
- 直接 `python fe/app.py` 會把 `sys.path[0]` 設為 `fe/` 而非根 → `be.*` 解析失敗；**故一律以 `python -m fe.app` 啟動**（文件據此更新）。

---

## 5. 文件更新（只動 live 文件）

- **更新**：
  - `README.md`（指令/結構/目錄樹）。
  - `report/report.md`：**不只**檔案地圖與 `python -m` 指令——還有散落在 **prose** 的路徑/模組字串（約 lines 39 `product_dataset.csv`、69 `harness/handlers.py`/`harness/llm.py`、118 `eval/testset.json`/`eval/run_eval.py`、133/190/206/220 的 `python -m eval.*` 與 `eval/*.json`，含 220 的 `eval/robustness_results_postfix.json`），全部改為新前綴。
  - `HANDOFF.md`（gitignored，結構/指令/檢查清單）。
  - `log.md` 追加 **§I**（重組紀錄）。
- **不動（歷史快照）**：`docs/superpowers/specs/2026-06-05-*`、`2026-06-07-hybrid-*`、`2026-06-07-robustness-*`、`docs/superpowers/plans/*`——這些是當時的設計快照，描述當時佈局，保留原樣；本次新增的重組 spec/plan 自然記錄新佈局。
- `.gitignore`：檢查是否有 `eval/` 路徑樣式需同步為 `be/eval/`（若有則更新；無則不動）。

---

## 6. 驗證（搬完後的必跑關卡）

依使用者要求，搬移完成後**做程式測試確保功能正常**，關卡：
0. **先清陳舊 bytecode**（混有 cpython-39/310 `.pyc`，`git mv` 不會移除舊 `__pycache__`，會孤兒化於空掉的 `harness/ data/ eval/` 並造成幻影 import）：`find . -path ./.venv -prune -o -name __pycache__ -type d -exec rm -rf {} +`；並刪殘留 `harness/ data/ eval/` 空夾的 `__pycache__`。
1. **無殘留舊前綴 import 守門**（機械改寫的決定性檢查）：`git grep -nE '(from|import) (harness|eval|data|app)([. ]|,|$)' -- '*.py'` 應回 **0 筆**（證明沒有漏改的頂層前綴）。
2. **全離線測試**：`python -m pytest -q` → **必須 147 passed**（含 `test_main_testset_frozen_at_27`、robustness/retrieval 守門）。任一轉紅即視為搬移未完成，須修到綠。
3. **import 煙測**：`python -c "import be.harness.orchestrator, be.eval.run_eval, be.eval.robustness_eval, de.data.store, fe.app, config"` → 無 ImportError。
4. **Flask 建構煙測**：`python -c "from fe.app import create_app, _build_default"` 可 import；並確認 `python -m fe.app` 能起 Flask（不需長跑，確認不因 import/路徑崩潰即可）。
5. **eval runner 載入煙測（離線、不可打 API）**：
   - 有 argparse 的 3 支用 `--help`（會在任何 API 呼叫前 short-circuit）：`python -m be.eval.run_eval --help`、`python -m be.eval.run_full --help`、`python -m be.eval.robustness_eval --help`。
   - **`run_sem` 與 `retrieval_eval` 無 argparse**——`--help` 會落入 `main()` 直打真實 OpenAI！**改用純 import 煙測**：`python -c "import be.eval.run_sem, be.eval.retrieval_eval"`（驗模組頂層 import + 路徑解析、不碰 API）。
6. **git 歷史**：`git log --follow` 對任一搬移檔可追溯（確認用 `git mv`）。

> 不需重跑真實 OpenAI eval：本次為純結構搬移、零行為改變；既有凍結結果檔（`be/eval/*_results.json`）隨檔移動、內容不變。

---

## 7. 不在本次範圍

- 任何邏輯/行為改變、prompt 調整、計分器修改（純搬移）。
- 把 `tests/`、`config.py`、`docs/`、`report/` 也塞進 FE/DE/BE（使用者已選「meta 留根目錄」）。
- 改成 flatten 佈局（`de/store.py`）或 `pyproject.toml` editable-install（已於 approaches 否決）。
- 重寫歷史 spec/plan 內的舊路徑（保留為快照）。
- 重跑真實 OpenAI eval / 變更凍結基線數字。
