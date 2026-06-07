// Single display-truth source for zh labels. Verbatim from spec §5.1 / §4.1.
// usage enum source: de/data/catalog.py USAGE_BY_TITLE values (sport/naked/touring/adventure/scooter/cruiser)
// condition source: de/data/listings.py _COND_FACTOR keys (A/B/C)

export const USAGE_ZH = {
  sport: '仿賽', naked: '街車', touring: '休旅',
  adventure: '冒險探險', scooter: '速克達', cruiser: '美式巡航',
};

export const CONDITION_ZH = { A: '近全新', B: '良好', C: '堪用' };

// tool name -> zh (tool names grounded in be/harness/tools.py TOOL_FUNCS L97-103)
export const TOOL_LABELS = {
  search_listings: '條件篩選',
  recommend: '預算推薦',
  semantic_search: '語意檢索',
  get_listing_detail: '刊登詳情',
  compare_models: '規格比較',
  check_order: '訂單查詢',
  book_viewing: '預約看車',
  create_ticket: '建立工單',
  escalate_to_human: '轉接真人',
};

// router.LABELS closed set (be/harness/router.py L3) -> display meta (zh + tone)
export const INTENT_META = {
  找車推薦: { zh: '找車推薦', tone: 'find' },
  規格比較: { zh: '規格比較', tone: 'compare' },
  交易訂單: { zh: '交易訂單', tone: 'order' },
  售後轉真人: { zh: '售後轉真人', tone: 'support' },
  閒聊範圍外: { zh: '閒聊範圍外', tone: 'offtopic' },
};

// pipeline step kind -> zh label (spec §4.1; 1:1 with real stages)
export const STEP_LABELS = {
  guard: '安全檢查',
  rewrite: '查詢改寫',
  route: '意圖路由',
  fallback: '範圍外回應',
  tool_call: '工具呼叫',
  retrieval: '混合檢索',
  confirm_gate: '需要確認',
  memory: '記憶更新',
  done: '完成',
  error: '錯誤',
};

// confirm_gate stage -> zh (spec §4.1: 需要確認 / 已確認 / 已取消)
export const CONFIRM_STAGE_ZH = { proposed: '需要確認', executed: '已確認', cancelled: '已取消' };

// retrieval phase -> zh (spec §2.2 retrieval event phases)
export const RETRIEVAL_PHASE_ZH = { bm25: '關鍵字檢索', vector: '向量檢索', rrf: 'RRF 融合', rerank: '重排序' };
