// fe/static/js/components/landing.js
// Landing 招牌時刻：hero 卡 + search pill + 4 chips + 序列化動態（morph→開串流）。
// 純邏輯（HERO_SPECS / motionPolicy / liveSummary）可單元測試；DOM mount 在同檔下方。

// --- spec §6.1：6 張 hero 裝飾圖（使用者放置；缺檔 onerror 自隱） ---
export const HERO_FILES = [
  'grom.jpg', 'super-cub.jpg', 'cb650r.jpg',
  'gold-wing.jpg', 'gsx-r.jpg', 'hayabusa.jpg',
];

// 6 張漂浮位置（裝飾用；CSS 以 data-hero 索引定位）。
export function heroSpecs() {
  return HERO_FILES.map((file, i) => ({
    index: i,
    src: '/static/img/hero/' + file,
    // stagger 60ms 淡出（spec §3.3）：第 i 張延遲 i*60ms。
    staggerMs: i * 60,
  }));
}

// --- spec §3.3 / R15：序列化動態策略（gated on prefers-reduced-motion） ---
// reduced=true → 不跑 FLIP morph / hero stagger，直接切到 chat 並立即開串流。
// reduced=false → 先 morph（--dur-slow）→ 完成後才開串流。
export function motionPolicy(reduced) {
  return reduced
    ? { morph: false, heroStagger: false, openStreamAfterMs: 0 }
    : { morph: true, heroStagger: true, openStreamAfterMs: 420 }; // 420 == --dur-slow
}

// --- spec §3.3 / R20：每輪簡潔 aria-live 摘要（screen reader 不被卡片洗版） ---
// 找到 N 台車輛；空結果 / 非車流以中性句。count 來自 final trace 的 listing 結果數。
export function liveSummary(count) {
  if (count == null) return '已完成回覆';
  if (count <= 0) return '目前沒有符合條件的車輛';
  return '找到 ' + count + ' 台車輛';
}
