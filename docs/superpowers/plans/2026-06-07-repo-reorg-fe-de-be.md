# FE/DE/BE 專案結構重組 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把核心程式/資料以 `git mv` 搬入 `be/`（harness+eval）、`de/`（data+csv）、`fe/`（app+templates+static）三層資料夾，機械式改寫 import 前綴與硬編路徑，並以「147 測試全綠 + 煙測」為驗收關卡——**零行為改變**。

**Architecture:** 純結構搬移。`be/de/fe` 各為含空 `__init__.py` 的分組套件，其下保留原套件名（`be/harness`、`be/eval`、`de/data`）。`config.py`、`conftest.py`、`tests/`、`docs/`、`report/` 等 meta 留根目錄。import 用詞界 sed 改寫（`harness→be.harness`、`eval→be.eval`、`data→de.data`、`app→fe.app`；`config` 不變），硬編 `"eval/…"` 路徑改 `"be/eval/…"`。`conftest.py`、`catalog.py` 的 CSV 路徑、Flask `Flask(__name__)` 皆**無需改**（spec §3.3 已驗證）。

**Tech Stack:** Python 3.10（專案 `.venv`）、pytest、BSD/macOS `sed -i ''`、git。

依據 spec：`docs/superpowers/specs/2026-06-07-repo-reorg-fe-de-be-design.md`（已過對抗式審查）。

---

## 環境前提（每步適用）
- 一律先 `source .venv/bin/activate`（Python 3.10；系統 `python3` 是 3.9 會壞）。
- macOS BSD `sed` 需 `-i ''`（空字串備份參數）。
- 在 git 分支 `refactor/fe-de-be-reorg` 上執行（Task 1 Step 1 建立），完成後由 finishing-a-development-branch ff-merge 進 `main`。

## 移動對照表（Task 1 執行）
| 來源 | 目的 | 方式 |
|---|---|---|
| `harness/`（含 `retrieval/`） | `be/harness/` | `git mv harness be/harness` |
| `eval/`（含所有 `*_testset.json` / `*_results.json` / `robustness_results_postfix.json`） | `be/eval/` | `git mv eval be/eval` |
| `data/` | `de/data/` | `git mv data de/data` |
| `product_dataset.csv` | `de/product_dataset.csv` | `git mv product_dataset.csv de/product_dataset.csv` |
| `app.py` | `fe/app.py` | `git mv app.py fe/app.py` |
| `templates/` | `fe/templates/` | `git mv templates fe/templates` |
| `static/` | `fe/static/` | `git mv static fe/static` |
| （新增空檔） | `be/__init__.py`、`de/__init__.py`、`fe/__init__.py` | `git add` |
| 留根目錄不動 | `config.py` `conftest.py` `tests/` `docs/` `report/` `README.md` `requirements.txt` `.env.example` `log.md` `HANDOFF.md`(gitignored) | — |

---

## Task 1: 結構搬移 + import/路徑改寫 + 驗收關卡（原子）

**Files:** 移動上表所有來源；改寫 `git ls-files '*.py'` 全部 import/路徑；手動改 `be/eval/retrieval_eval.py` 一處 print。

- [ ] **Step 1: 建分支 + 確認基線綠**

```bash
cd /Users/charles88/Desktop/2026DRL/HW4
git checkout -b refactor/fe-de-be-reorg
source .venv/bin/activate
git status -s           # 預期：空（乾淨）
python -m pytest -q     # 預期：147 passed
```
Expected: 乾淨 working tree、`147 passed`。若非 147 綠，停手回報（基線必須先綠）。

- [ ] **Step 2: 清除陳舊 bytecode（git mv 不會移除 __pycache__）**

```bash
find . -path ./.venv -prune -o -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; true
find . -path ./.venv -prune -o -name '*.pyc' -delete 2>/dev/null; true
```
Expected: 無輸出（或忽略）。確保不殘留混版 `.pyc`。

- [ ] **Step 3: 建立分組套件骨架**

```bash
mkdir -p be de fe
touch be/__init__.py de/__init__.py fe/__init__.py
```
Expected: `be/ de/ fe/` 三夾各含空 `__init__.py`。

- [ ] **Step 4: `git mv` 整夾/整檔搬移**

```bash
git mv harness be/harness
git mv eval be/eval
git mv data de/data
git mv product_dataset.csv de/product_dataset.csv
git mv app.py fe/app.py
git mv templates fe/templates
git mv static fe/static
git add be/__init__.py de/__init__.py fe/__init__.py
git status -s   # 預期：大量 renamed: ... 與 3 個 new file: be/de/fe __init__.py
```
Expected: `git status` 顯示 renamed（保留歷史）、無遺漏；`product_dataset.csv` 在 `de/`（使 `de/data/catalog.py` 的 `dirname(dirname(__file__))` 解析到 `de/` → 找到 CSV）。

- [ ] **Step 5: 機械式改寫 import 前綴（詞界、冪等）**

```bash
for f in $(git ls-files '*.py'); do
  LC_ALL=C sed -i '' -E \
    -e 's/^([[:space:]]*)(from|import) harness([. ,])/\1\2 be.harness\3/g' \
    -e 's/^([[:space:]]*)(from|import) eval([. ,])/\1\2 be.eval\3/g' \
    -e 's/^([[:space:]]*)(from|import) data([. ,])/\1\2 de.data\3/g' \
    -e 's/^([[:space:]]*)(from|import) app([. ,])/\1\2 fe.app\3/g' \
    "$f"
done
```
說明：只改 `from`/`import` 開頭（可含縮排）且套件名為首 token 者；`config` 不在清單故不變；`[. ,]` 確保 `dataclasses`/`dotenv`/`datetime` 不誤中；對 `be.harness`（已改過）再跑為 no-op（冪等）。
Expected: 無錯誤輸出。

- [ ] **Step 6: 機械式改寫硬編路徑字串**

```bash
for f in $(git ls-files '*.py'); do
  LC_ALL=C sed -i '' \
    -e 's|"eval/|"be/eval/|g' \
    -e 's|python -m eval\.|python -m be.eval.|g' \
    "$f"
done
```
說明：`"eval/` 前有引號，故只命中 `open("eval/…")`、`default="eval/…"` 等路徑字串，不會誤中 `harness/retrieval/`（其無 `"eval/`）；`python -m eval.` 修 docstring 內舊指令。
Expected: 無錯誤輸出。

- [ ] **Step 7: 手動修唯一未被引號錨定的 print 字串**

於 `be/eval/retrieval_eval.py` 第 95 行（`print("\nwrote eval/retrieval_results.json")`）將 `eval/retrieval_results.json` 改為 `be/eval/retrieval_results.json`：

```python
    print("\nwrote be/eval/retrieval_results.json")
```
（用 Edit 工具精確替換該行；此處 `eval/` 前是空白非引號，Step 6 不會命中。）

- [ ] **Step 8: 殘留舊前綴守門（決定性檢查，應為 0）**

```bash
git grep -nE '(from|import) (harness|eval|data|app)([. ]|,|$)' -- '*.py'; echo "exit=$?"
```
Expected: **無任何行輸出、`exit=1`**（grep 找不到 = 0 殘留舊前綴 import）。若有輸出 → 該行漏改，修正後重跑。

- [ ] **Step 9: 全離線測試（核心驗收）**

```bash
python -m pytest -q
```
Expected: **147 passed**（含 `test_main_testset_frozen_at_27`、robustness/retrieval 守門）。任一紅 → 修到綠才可繼續（常見：某 `open("be/eval/…")` 或 import 漏改）。

- [ ] **Step 10: import / Flask / runner 煙測（離線、不可打 API）**

```bash
python -c "import be.harness.orchestrator, be.eval.run_eval, be.eval.robustness_eval, de.data.store, fe.app, config; print('imports ok')"
python -c "from fe.app import create_app, _build_default; print('flask import ok')"
python -m be.eval.run_eval --help >/dev/null && echo "run_eval --help ok"
python -m be.eval.run_full --help >/dev/null && echo "run_full --help ok"
python -m be.eval.robustness_eval --help >/dev/null && echo "robustness --help ok"
python -c "import be.eval.run_sem, be.eval.retrieval_eval; print('run_sem/retrieval_eval import ok')"
```
Expected: 依序印出 `imports ok` / `flask import ok` / `run_eval --help ok` / `run_full --help ok` / `robustness --help ok` / `run_sem/retrieval_eval import ok`，全程無 ImportError、**不觸發任何 OpenAI 呼叫**（注意：`run_sem`/`retrieval_eval` 無 argparse，故用 import-only 煙測，**切勿**對它們下 `--help`）。

- [ ] **Step 11: Commit（結構搬移）**

```bash
git add -A
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "$(cat <<'EOF'
refactor: reorganize into be/ (harness+eval), de/ (data+csv), fe/ (app+ui)

Mechanical move via git mv (history preserved) + import-prefix rewrite
(harness->be.harness, eval->be.eval, data->de.data, app->fe.app; config unchanged)
+ hardcoded "eval/..." paths -> "be/eval/...". conftest, catalog CSV path, and Flask
template/static resolution need no change. Zero behavior change: 147 tests green
incl. frozen-27 guard; import/Flask/runner smokes pass.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
git log --follow --oneline -1 -- be/harness/orchestrator.py   # 預期：能追溯到搬移前歷史
```
Expected: 提交成功；`git log --follow` 可追溯舊歷史（證明 git mv 生效）。

---

## Task 2: 更新 live 文件（README / report / log）

**Files:** Modify `README.md`、`report/report.md`、`log.md`。（`docs/superpowers/specs|plans/*` 為歷史快照，不動。）

- [ ] **Step 1: 安全的指令型 sed（README + report + log）**

```bash
for f in README.md report/report.md log.md; do
  LC_ALL=C sed -i '' \
    -e 's|python -m eval\.|python -m be.eval.|g' \
    -e 's|python app\.py|python -m fe.app|g' \
    "$f"
done
```
說明：只改不歧義的指令字串（`python -m eval.*`、`python app.py`），不碰含 `retrieval/` 的路徑（那些用下面的精確 Edit 處理）。
Expected: 無錯誤。

- [ ] **Step 2: README 結構表與執行段（精確 Edit）**

於 `README.md` 套用以下精確替換（用 Edit 工具）：
- 結構表列：
  - `| \`data/\` | ` → `| \`de/data/\` | `
  - `| \`harness/\` | ` → `| \`be/harness/\` | `
  - `| \`app.py\` | Flask app factory：\`GET /\`、\`POST /api/chat\` |` → `| \`fe/app.py\` | Flask app factory：\`GET /\`、\`POST /api/chat\` |`
  - `| \`templates/\`、\`static/\` | 聊天 UI + Decision Trace 側欄 |` → `| \`fe/templates/\`、\`fe/static/\` | 聊天 UI + Decision Trace 側欄 |`
  - `| \`eval/\` | \`testset.json\`（27 題）、\`run_eval.py\`（指標 + PASS/FAIL） |` → `| \`be/eval/\` | \`testset.json\`（27 題）、\`run_eval.py\`（指標 + PASS/FAIL）、robustness/retrieval/sem eval |`
- 在「## 專案結構」表格上方加一行頂層佈局說明：
  `> 頂層分層：\`be/\`（後端：harness + eval）、\`de/\`（資料端：data + product_dataset.csv）、\`fe/\`（前端：Flask app + templates/static）；\`config.py\`/\`tests/\`/\`docs/\`/\`report/\` 留根目錄。`

（`python app.py`→`python -m fe.app`、`python -m eval.run_eval`→`python -m be.eval.run_eval` 已由 Step 1 sed 處理。）

- [ ] **Step 3: report.md 內 prose 路徑字串（精確 Edit）**

於 `report/report.md` 套用以下精確替換（用 Edit；指令字串已由 Step 1 sed 改）：
- `（\`product_dataset.csv\`，欄位` → `（\`de/product_dataset.csv\`，欄位`
- `\`harness/handlers.py:run_handler\`` → `\`be/harness/handlers.py:run_handler\``
- `\`harness/llm.py\` 定義` → `\`be/harness/llm.py\` 定義`
- `（\`eval/testset.json\`），分布` → `（\`be/eval/testset.json\`），分布`
- `\`eval/run_eval.py\` 對每指標` → `\`be/eval/run_eval.py\` 對每指標`
- `見 \`eval/results.json\`` → `見 \`be/eval/results.json\``
- `\`eval/retrieval_testset.json\`；gold` → `\`be/eval/retrieval_testset.json\`；gold`
- `數據 \`eval/retrieval_results.json\`` → `數據 \`be/eval/retrieval_results.json\``
- `\`eval/sem_testset.json\` 驗證` → `\`be/eval/sem_testset.json\` 驗證`
- `\`eval/sem_results.json\`）` → `\`be/eval/sem_results.json\`）`
- `\`eval/robustness_testset.json\`（40 題` → `\`be/eval/robustness_testset.json\`（40 題`
- `\`eval/robustness_results.json\`、修補後 \`eval/robustness_results_postfix.json\`` → `\`be/eval/robustness_results.json\`、修補後 \`be/eval/robustness_results_postfix.json\``

驗證：`git grep -nE '[^/]eval/|[^./]data/|[^/]harness/|product_dataset' -- report/report.md` 應只剩**歷史不需改**或已加前綴者；逐一確認無漏。

- [ ] **Step 4: log.md 追加 §I**

於 `log.md` 末尾追加（仿既有 §G/§H 風格）：

```markdown

## I. 專案結構重組：FE / DE / BE（2026-06-07）

**動機**：根目錄平鋪雜亂（harness/ eval/ data/ app.py templates/ static/ product_dataset.csv …）。依程式/資料特性分層為 `be/`（後端：harness + eval）、`de/`（資料端：data + product_dataset.csv）、`fe/`（前端：Flask app + templates/static）；meta（config.py/tests/docs/report/…）留根目錄。

**流程與 AI 協作**：brainstorming → spec → **對抗式 self-review（5 讀-only 驗證 agent + 綜整）** → writing-plans → subagent-driven 執行。對抗式審查在動手前攔下 3 個 blocker：(1) `fe/app.py` 已有正確 `__main__` 且 `_build_default()` 已回傳 Flask app（原 spec 誤指示重複包裝 `create_app`）；(2) 只有 `run_full`/`robustness_eval` 有 argparse `--out`，`run_sem`/`retrieval_eval` 硬編寫入路徑；(3) `run_sem`/`retrieval_eval` 無 argparse，`--help` 會落入 `main()` 直打真實 API → 驗證改用 import-only 煙測。另修正 import 計數（128）、`robustness_results_postfix.json` 遺漏、`__pycache__` 陳舊清除等。

**手法**：`git mv`（保留歷史）+ 詞界 sed 改 import 前綴（`harness→be.harness`/`eval→be.eval`/`data→de.data`/`app→fe.app`；`config` 不變）+ `"eval/"→"be/eval/"`。`conftest.py`（root 在 sys.path）、`data/catalog.py` 的 CSV 路徑（`dirname(dirname(__file__))`→`de/`）、Flask `Flask(__name__)`（templates/static 隨 app 移）皆**無需改**。進入點：`python -m fe.app`、`python -m be.eval.*`。

**驗證（零行為改變）**：殘留舊前綴 import grep = 0；`python -m pytest -q` 147 passed（含凍結 27 守門）；import/Flask/runner 煙測全過。spec `b5908d7`、plan 見 `docs/superpowers/plans/2026-06-07-repo-reorg-fe-de-be.md`。
```

- [ ] **Step 5: 確認文件無殘留舊路徑 + 測試仍綠 + Commit**

```bash
git grep -nE 'python -m eval\.|python app\.py' -- README.md report/report.md log.md; echo "stale-cmd exit=$?"   # 預期無輸出、exit=1
python -m pytest -q   # 預期仍 147 passed（文件改動不影響）
git add README.md report/report.md log.md
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "$(cat <<'EOF'
docs: update live docs for be/de/fe layout (README/report/log §I)

Commands -> python -m {fe.app,be.eval.*}; inline path strings -> be/de/fe prefixes
(incl. report.md prose refs + robustness_results_postfix.json). Historical
specs/plans left as dated snapshots.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: 無殘留舊指令、`147 passed`、提交成功。

---

## Task 3: 最終驗證 + HANDOFF 更新（gitignored）

**Files:** Modify `HANDOFF.md`（gitignored，不 commit）。

- [ ] **Step 1: 最終全關卡複跑**

```bash
source .venv/bin/activate
git grep -nE '(from|import) (harness|eval|data|app)([. ]|,|$)' -- '*.py'; echo "stale-import exit=$?"   # 預期無輸出、exit=1
python -m pytest -q                                                                                     # 預期 147 passed
python -c "import be.harness.orchestrator, be.eval.robustness_eval, de.data.store, fe.app, config; print('ok')"
git status -s                                                                                            # 預期乾淨
ls be de fe                                                                                              # 預期見 harness/eval、data/product_dataset.csv、app.py/templates/static
```
Expected: stale-import=0、147 passed、imports ok、tree 乾淨、佈局正確。

- [ ] **Step 2: Flask 啟動煙測（短跑、確認不崩）**

```bash
timeout 6 python -m fe.app >/tmp/flask_smoke.log 2>&1; echo "exit=$?"; grep -iE "Running on|Traceback|Error" /tmp/flask_smoke.log | head
```
Expected: log 出現 `Running on http://...:5000`（Flask 起得來）、無 Traceback。`timeout` 殺掉算正常（exit 124）。若出現 ImportError/Traceback → 修正。

- [ ] **Step 3: 更新 HANDOFF.md（gitignored，不 commit）**

用 Edit 更新 `HANDOFF.md`：
- §2 環境/§3 指令：`python app.py`→`python -m fe.app`、`python -m eval.*`→`python -m be.eval.*`。
- §5 檔案地圖：路徑加 `be/`/`de/`/`fe/` 前綴（`harness/`→`be/harness/`、`eval/`→`be/eval/`、`data/`→`de/data/`、`app.py`→`fe/app.py`、`product_dataset.csv`→`de/product_dataset.csv`）。
- §1/§9：HEAD 更新為合併後 SHA、頂層佈局一句話、接手檢查清單沿用 `python -m pytest -q`（147）。
Expected: HANDOFF 反映新佈局（此檔 gitignored，不進 commit）。

- [ ] **Step 4: 完成分支**（交由 finishing-a-development-branch）

不在此手動 merge；回報控制器以 superpowers:finishing-a-development-branch 處理（預期 ff-merge 進 `main` 後刪分支，比照前例）。

---

## Self-Review（plan vs spec）

**Spec coverage：**
- §1 鐵則（分層/零行為/git 歷史/進入點）→ Task 1（move+rewrite+gate）、Task 3（history check）✓
- §2 目標佈局（be/de/fe 巢狀 + meta 留根 + __init__）→ Task 1 Step 3-4 + 移動對照表 ✓
- §3.1 import 前綴（含頂層+內層、AST/詞界）→ Task 1 Step 5（詞界 sed）+ Step 8 守門 ✓
- §3.2 路徑（讀/寫、argparse vs 硬編、test_app 唯一 app consumer、print/docstring）→ Step 6（`"eval/`、`python -m eval.`）+ Step 7（print）；`from app`→`fe.app` 與 docstring 由 Step 5/6 涵蓋 ✓
- §3.3 無需改（catalog CSV/conftest/Flask）→ 計畫刻意不動，Step 4 註記 CSV 落點、Task 3 Flask 煙測佐證 ✓
- §4 進入點（python -m fe.app / be.eval.*；app __main__ 不動）→ Task 1 Step 10、Task 3 Step 2 ✓
- §5 文件（README/report 含 prose/HANDOFF/log §I；歷史不動）→ Task 2 + Task 3 Step 3 ✓
- §6 驗證（pycache 清除、stale-prefix=0、147、import/flask/runner 煙測、git --follow）→ Task 1 Step 2/8/9/10/11 + Task 3 Step 1/2 ✓
- §7 不在範圍（無邏輯改、不重跑真實 eval、不動凍結數字、不重寫歷史 spec）→ 全程未觸碰 ✓

**Placeholder scan：** 無 TBD/TODO；每步含可執行指令與預期輸出；README/report 的精確 old→new 字串均列出（取自實際檔案內容）。✓

**Type/命令一致性：** 套件前綴對應在 Step 5/8/10、Task 3 一致（`be.harness`/`be.eval`/`de.data`/`fe.app`、`config` 不變）；`run_sem`/`retrieval_eval` 全程用 import-only 煙測（不 `--help`）一致；`"be/eval/"` 路徑前綴一致。✓
