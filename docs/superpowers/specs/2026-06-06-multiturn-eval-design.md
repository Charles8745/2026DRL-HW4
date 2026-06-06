# Spec — 多輪跨情境 eval（Approach A：真兩輪量測）

- 日期：2026-06-06
- 狀態：核准，待實作
- 背景：HW4 §7-2。`testset.json` 的 multi-* case 記了 `ground_truth.secondary_tool` 卻**無任何程式讀取**（死資料）；系統的招牌能力——跨情境多輪串接（defer + ordinal 解析 + 兩輪確認）——只有 FakeLLM 單元測試驗證接線，eval harness 每次只送一輪，次工具**永遠碰不到**。

## 1. 目標
把「只記錄」的 `secondary_tool` 變成「誠實量測」：對 multi-* case 在**同一 session** 跑第二輪（`followup`），量測次工具是否在 turn-2 觸發。**不改 `score_case`、不改 `expected_tools`、不破現有 78 測試、不作弊。**

## 2. 設計（全部加法）

### 2.1 testset.json
每個 multi-* case 新增 `followup`（turn-2 使用者訊息）。`expected_tools`（主工具，turn-1）與 `ground_truth.secondary_tool` 不變。

| case | followup（turn-2） | secondary_tool |
|---|---|---|
| multi-01 | 「第一台規格如何」 | get_listing_detail |
| multi-02 | 「約看第一台」 | book_viewing |
| multi-03 | 「便宜的那台幫我約看車」 | book_viewing（**預期誠實失敗**，見 §4） |
| multi-04 | 「幫我開工單」 | create_ticket |

### 2.2 `eval/run_eval.py`：新增 `score_multiturn(case, out1, out2)`（純函式）
- `primary_ok` = `score_case(case, out1)["tools_ok"]`（turn-1 主工具）
- `secondary_ok` = `secondary_tool ∈ turn-2 trace 的 tool_name`（含 proposed step）
- `chain_ok` = `primary_ok and secondary_ok`
- 回 `{id, primary_ok, secondary_ok, chain_ok}`

### 2.3 `eval/run_full.py`：兩輪執行 + 指標
對有 `followup` 的 case：turn-1 process（照舊計單輪 router/task/groundedness）後，**同一 session** 再 process(`followup`) 得 out2，呼 `score_multiturn`。新增彙總指標 `multiturn_chain_success`（multi-* 中 chain_ok 的比例），寫入 `results.json` 並印出。**單輪 27 題指標不受影響**（turn-1 仍是主計分輪）。

### 2.4 報告
report 新增 **§7.3 多輪鏈成功率**：填真實 `multiturn_chain_success` 與逐 case primary/secondary/chain，並註明 multi-03 的限制。

## 3. 測試（TDD）
- `tests/test_run_eval.py`：`score_multiturn` 的 chain_ok True/False（次工具有/無、含 proposed）。
- `tests/test_orchestrator.py`：FakeLLM 驅動的**兩輪串接**特性測試——turn-1 recommend 設 viewed_listings、turn-2「約看第一台」經 ordinal 解析使 book_viewing 帶正確 listing_id 觸發（驗證 defer+resume 跨輪確實運作）。

## 4. multi-03 的真實限制（誠實揭露，不擴 scope）
`compare_models` 回的是**車款**非**刊登**，且 `set_viewed` 只記 search/recommend 結果 → 「便宜的那台」無價格可比、無 listing 可約。此「車款比較→刊登預約」橋接缺口為 **future work**；multi-03 在兩輪 eval 誠實顯示鏈失敗，`multiturn_chain_success` 預期約 3/4。

## 5. 不在範圍
- price-aware／語意參照解析（multi-03 的修法）。
- 改動 router/rewriter/handler 既有邏輯（僅 testset + eval + 報告）。
