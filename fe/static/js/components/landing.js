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

// --- spec §3.3：4 個 zh 建議 chips（唯一字面源） ---
export const LANDING_CHIPS = [
  '30萬內 Yamaha 跑車',
  '新手通勤省油好停',
  '比較 CB650R 與 MT-07',
  '查訂單 O001',
];

// mountLanding：把 landing 渲入 host，回傳 { root, pillInput, els } 供 M5.3 morph 取用。
// onSubmit(text) 由 main.js 提供（擁有 SseClient 與序列化動態）。
export function mountLanding(host, onSubmit) {
  const root = document.createElement('section');
  root.className = 'landing';
  root.setAttribute('data-landing', '');

  // 背景 6 張漂浮 hero 卡（純裝飾、aria-hidden、lazy、缺檔自隱）。
  const heroLayer = document.createElement('div');
  heroLayer.className = 'landing__hero-layer';
  heroLayer.setAttribute('aria-hidden', 'true');
  for (const spec of heroSpecs()) {
    const card = document.createElement('div');
    card.className = 'hero-card';
    card.style.setProperty('--hero-delay', spec.staggerMs + 'ms');
    card.setAttribute('data-hero', String(spec.index));
    const img = document.createElement('img');
    img.src = spec.src;
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.setAttribute('referrerpolicy', 'no-referrer');
    // 缺檔 onerror 自隱：藏整張卡片，不顯破圖。
    img.addEventListener('error', () => { card.style.display = 'none'; });
    card.appendChild(img);
    heroLayer.appendChild(card);
  }

  // 前景：wordmark + search pill + chips。
  const stage = document.createElement('div');
  stage.className = 'landing__stage';

  const mark = document.createElement('div');
  mark.className = 'landing__wordmark';
  mark.innerHTML =
    '<span class="wm-en">RideButler</span>' +
    '<span class="wm-zh">騎士管家 · 二手重機智慧客服</span>';

  const form = document.createElement('form');
  form.className = 'landing__pill';
  form.setAttribute('role', 'search');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'landing__pill-input';
  input.autocomplete = 'off';
  input.placeholder = '描述你想找的車，或試試下方建議';
  input.setAttribute('aria-label', '描述你想找的車');
  const btn = document.createElement('button');
  btn.type = 'submit';
  btn.className = 'landing__pill-btn';
  btn.textContent = '開始';
  form.append(input, btn);

  const chips = document.createElement('div');
  chips.className = 'landing__chips';
  for (const text of LANDING_CHIPS) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'landing__chip';
    chip.textContent = text;
    chip.addEventListener('click', () => onSubmit(text));
    chips.appendChild(chip);
  }

  function submit(e) {
    e.preventDefault();
    const text = input.value.trim();
    if (text) onSubmit(text);
  }
  form.addEventListener('submit', submit);

  stage.append(mark, form, chips);
  root.append(heroLayer, stage);
  host.appendChild(root);

  return { root, pillInput: input, els: { heroLayer, stage, form, chips } };
}
