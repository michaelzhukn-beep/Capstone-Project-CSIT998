/* ════════════════════════════════════════════════════════════════════════
   lab.js —— 交互层。数据全部来自主站真引擎(经 serve_lab.py 代理)。

   这个实验室只做三件事,别的都不做:
     ① 溯源材质:把「实测 / 假设 / 模型估」做成材质差异,不只靠颜色
     ② 把计算过程变可见:用真实的 node / ranking.count / 耗时,不造假进度
     ③ 一个数值翻滚,只用在该用的地方(条件改动导致数值变化时)

   刻意不做:轮播、手势、3D、玻璃拟态、改主站那三条缓动曲线。
   ════════════════════════════════════════════════════════════════════════ */
'use strict';

(function () {

// ══════════════════════════════════════════════════════════ 错误可见
/* 这个实验室是拿来试错的,所以错误必须**看得见**,不能只躺在 console 里。
   踩到过:页面上只有一句 "on is not a function",没有行号 —— 而 lab.js 有
   900 行,靠猜等于白猜。这里把未捕获异常和未处理的 Promise 拒绝都画到页面上,
   带上行号,一次就能定位。 */
function showFatal(what, err) {
  try {
    const box = document.getElementById('fatal') || (() => {
      const b = document.createElement('div');
      b.id = 'fatal';
      b.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;'
        + 'max-height:42vh;overflow:auto;padding:12px 16px;background:#2A1410;color:#FFD9CE;'
        + 'font:12px/1.6 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;'
        + 'border-top:2px solid #8A3A22';
      document.body.appendChild(b);
      return b;
    })();
    const msg = err && (err.stack || err.message || String(err));
    box.textContent += `[${what}] ${msg}\n\n`;
    box.scrollTop = box.scrollHeight;
  } catch { /* 连错误面板都挂了就只能认了 */ }
}
window.addEventListener('error', e => showFatal('error', e.error || e.message));
window.addEventListener('unhandledrejection', e => showFatal('promise', e.reason));

// ─────────────────────────────────────────────────────────── 工具
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

const money = n => n == null ? '—' : '$' + Math.round(n).toLocaleString('en-AU');
const pct = (n, d = 2) => n == null ? '—' : (n * 100).toFixed(d) + '%';
const dist = m => m == null ? '—'
  : m < 950 ? Math.round(m / 10) * 10 + ' m' : (m / 1000).toFixed(1) + ' km';
const comma = n => n == null ? '—' : Number(n).toLocaleString('en-AU');

/* ── 溯源的三个档 ────────────────────────────────────────────────────────
   这是整个实验室的核心抽象。主站用颜色区分(.assume 灰 / .model 蓝),
   颜色的问题是你得先记住图例;这里改成**材质 + 符号 + 颜色**三重编码:

     proof   实测    纯墨,无底纹,无符号。基准不装饰。
     assume  假设    ~ 前缀 + 暖褐 + 网点底纹(半调,墨没铺满)
     model   模型估  ◆ 前缀 + 冷靛 + 斜纹(唯一冷色,唯一斜纹)

   即使打印成黑白、或用户色觉不同,符号仍然分得开。 */
const PROV = { PROOF: 'proof', ASSUME: 'assume', MODEL: 'model' };

/* 溯源标记:JS 里写错一个 prov 值,CSS 就静默不生效 —— 一个假设会**看起来像实测**。
   所以在这里就把非法值挡下来,并且打印出来。 */
const PROV_OK = new Set(['proof', 'assume', 'model']);
function pv(text, prov, extraCls) {
  const s = el('span', extraCls || '');
  if (!PROV_OK.has(prov)) {
    showFatal('prov', new Error('未知的溯源类型 ' + JSON.stringify(prov) + ' —— 值会退化成"未标注"'));
    prov = 'unknown';
  }
  s.dataset.prov = prov;
  s.textContent = text;
  return s;
}

// ─────────────────────────────────────────────────────────── 状态
const state = {
  meta: null,
  threadId: 'lab-' + Math.random().toString(36).slice(2, 10),
  params: null, intent: null,
  ranking: '', count: 0,
  metrics: [], pool: [], offset: 0,
  selectedId: null,
  running: false,
  map: null, layer: null, blots: [],
};

const MILESTONES = [
  ['parse_intent', '解析条件'],
  ['search',       '检索'],
  ['rank',         '排序'],
  ['present',      '整理'],
  ['explain',      '写说明'],
];

// ══════════════════════════════════════════════════════════ ① 进度刻度条
/* 用真实事件驱动。每一个刻度对应图里一个真节点,候选数是后端真返回的 count,
   耗时是 Date.now() 差值。**没有任何一个数字是估的或编的。** */
function rail(host) {
  const box = el('div', 'rail');
  const head = el('div', 'rail-head');
  const now = el('span', 'rail-now', '正在解析条件');
  const clock = el('span', 'rail-clock', '0.0s');
  head.append(now, clock);

  const ticks = el('div', 'ticks');
  MILESTONES.forEach(() => ticks.appendChild(el('i')));

  const note = el('div', 'rail-note');

  box.append(head, ticks, note);
  host.appendChild(box);

  const t0 = performance.now();
  const tickEls = $$('i', ticks);
  let done = new Set();

  const timer = setInterval(() => {
    clock.textContent = ((performance.now() - t0) / 1000).toFixed(1) + 's';
  }, 100);

  return {
    /** 真节点到达 */
    node(name) {
      const i = MILESTONES.findIndex(m => m[0] === name);
      if (i >= 0) {
        done.add(name);
        tickEls.forEach((t, k) => {
          t.className = k < i ? 'on' : k === i ? 'cur' : '';
        });
        // 已完成的格子回填成实心;当前格闪烁
        tickEls.forEach((t, k) => { if (k < i) t.className = 'on'; });
        now.textContent = '正在' + MILESTONES[i][1];
      }
    },
    /** 真实候选数。后端在 ranking 事件里给了 count,主站没显示它。 */
    count(c, rankingText) {
      state.count = c;
      note.innerHTML = '';
      note.append('候选池 ', pv(comma(c) + ' 套', PROV.PROOF));
      if (rankingText) note.append(document.createTextNode(' · ' + rankingText));
    },
    stage(t) { now.textContent = t; },
    end() {
      clearInterval(timer);
      const secs = ((performance.now() - t0) / 1000).toFixed(1);
      tickEls.forEach(t => { t.className = 'on'; t.style.animation = 'none'; });
      box.style.transition = 'opacity 320ms cubic-bezier(0.23,1,0.32,1)';
      box.style.opacity = '0';
      setTimeout(() => box.remove(), 340);
      return secs;
    },
    fail(msg) {
      clearInterval(timer);
      now.textContent = '中断';
      note.textContent = msg;
      box.style.borderLeft = '2px solid var(--warn)';
    },
  };
}

// ══════════════════════════════════════════════════════════ ② 数字翻滚
/* 唯一的数值动效。用在:条件改动 → 卡片指标变化时。
   做法是等宽字位数对齐 + 逐位竖直滚动 —— 机械计数器的读感,
   和"这是一个被系统重新算过的数"这件事对得上。

   为什么不用主站的 rn- 那套逐字符 DOM 方案:那是给单个大数字用的
   (航班牌/仪表),这里是 5 张卡 × 最多 4 个数字 = 20 个,逐字符会变成
   数百个节点。这里用整值插值 + 一位小数,足够读。 */
function rollText(node, from, to, fmt, ms = 420) {
  if (from === to || !isFinite(from) || !isFinite(to)) { node.textContent = fmt(to); return; }
  const t0 = performance.now();
  const ease = t => 1 - Math.pow(1 - t, 3);          // easeOutCubic,和 --ease-out 同族
  const step = now => {
    const t = Math.min(1, (now - t0) / ms);
    node.textContent = fmt(from + (to - from) * ease(t));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ══════════════════════════════════════════════════════════ ③ 卡片
function typeZh(t) { return (state.meta?.property_types || {})[t] || t || ''; }
function attrZh(a) { return (state.meta?.attributes || {})[a] || a; }

/** 首要指标:口径随排序字段变。返回 {label, prov, fmt, raw}。
 *  prov 的判定依据是**这个数从哪来**:
 *    cap_rate / roi 依赖 opex 假设 → assume
 *    predicted_gap 来自 XGB 模型    → model
 *    其余是库里的实测字段          → proof */
function headline(m) {
  const s = state.params?.sort_by;
  const cs = m.context_scores || {};
  if (s && cs[s] != null) {
    return {
      label: attrZh(s), prov: PROV.PROOF, score: cs[s],
      fmt: v => Math.round(v), raw: cs[s],
      sub: evidenceLine(m, s, 2),
    };
  }
  if (s === 'near_place_distance' && m.near_place) {
    return { label: '距' + m.near_place.name, prov: PROV.PROOF, raw: m.near_place.distance_m,
             fmt: v => dist(v), sub: '' };
  }
  if (s === 'cap_rate') return { label: 'Cap Rate', prov: PROV.ASSUME, raw: m.cap_rate,
                                 fmt: v => pct(v), sub: '按 opex 假设算得' };
  if (s === 'roi') return { label: 'ROI', prov: PROV.ASSUME, raw: m.roi,
                            fmt: v => pct(v), sub: '按 opex 假设算得' };
  if (s === 'predicted_gap') {
    return { label: '估值差', prov: PROV.MODEL, raw: m.predicted_gap,
             fmt: v => (v > 0 ? '+' : '') + pct(v),
             sub: '模型估值 ' + money(m.predicted_price) };
  }
  return { label: '毛回报率', prov: PROV.PROOF, raw: m.gross_yield,
           fmt: v => pct(v), sub: '年租金 ' + money(m.annual_rent) };
}

/** 用户点名要的、但并非排序依据的属性 —— 给证据,不重复分数。 */
function otherScores(m) {
  const s = state.params?.sort_by, out = [];
  for (const need of (state.params?.abstract_needs || [])) {
    const a = need.attribute;
    if (a === s) continue;
    const sc = m.context_scores?.[a];
    if (sc == null) continue;
    out.push([attrZh(a), sc, a]);
  }
  return out.slice(0, 3);
}

function evidenceLine(m, attr, limit) {
  const parts = state.meta?.attribute_parts?.[attr] || [];
  const ev = m.context_evidence || {}, out = [];
  for (const k of parts) {
    if (ev[k] == null) continue;
    const [label, unit] = state.meta?.evidence_labels?.[k] || [k, ''];
    out.push(shortLabel(label) + ' ' + fmtEvidence(ev[k], unit));
    if (out.length >= limit) break;
  }
  return out.join(' · ');
}
const shortLabel = l => l.replace(/^距最近/, '').replace(/^\d+\s*米内/, '').replace(/^Nearest\s+/i, '');
function fmtEvidence(v, unit) {
  if (unit === '米' || unit === 'm') return dist(v);
  if (typeof v === 'number') return (Number.isInteger(v) ? v : v.toFixed(1)) + (unit ? ' ' + unit : '');
  return String(v);
}

/** 标注行。ask = 用户点名的;risk = 风险披露,永远显示、但不做成警告长相。 */
function marks(m) {
  const p = state.params || {}, s = p.sort_by, asked = [], risk = [], extra = [];
  for (const [, , a] of otherScores(m).map(x => [x[0], x[1], x[2]])) {
    const ev = topEvidence(m, a);
    if (ev) asked.push(attrZh(a) + ' · ' + ev);
  }
  for (const need of (p.amenity_needs || [])) {
    const a = m.amenities?.[need.kind];
    if (a?.distance_m != null) asked.push((state.meta?.kinds?.[need.kind] || need.kind) + ' ' + dist(a.distance_m));
  }
  if (m.near_place && s !== 'near_place_distance') asked.push('距' + m.near_place.name + ' ' + dist(m.near_place.distance_m));
  if (p.school_zone && m.school_zones?.primary) asked.push('学区 ' + m.school_zones.primary.replace(/ Primary School$/, ''));

  if (s !== 'gross_yield' && p.min_gross_yield == null) extra.push('毛回报 ' + pct(m.gross_yield));
  // 门槛用**这类房型自己的**典型误差,不是写死的 10% —— 同一套房在卡片和详情里
  // 必须说同一句话,两处用同一条线。(主站踩过这个坑,这里沿用它的解法。)
  const vg = m.predicted_gap, ve = m.valuation_error_pct;
  if (vg != null && ve != null && Math.abs(vg) > ve) {
    extra.push((vg > 0 ? '估值高于售价 ' : '估值低于售价 ') + pct(Math.abs(vg)));
  }
  const pl = m.planning || {};
  for (const o of (pl.overlays || [])) if (o.effect === 'risk') risk.push(o.label);
  if ((pl.overlays || []).some(o => o.family === 'HO')) risk.push('历史建筑保护叠加层');

  const head = asked.slice(0, 4);
  return { asked: head.concat(extra.slice(0, Math.max(0, 4 - head.length))), risk: risk.slice(0, 3) };
}
function topEvidence(m, attr) {
  const parts = state.meta?.attribute_parts?.[attr] || [];
  const ev = m.context_evidence || {};
  for (const k of parts) {
    if (ev[k] == null) continue;
    const [label, unit] = state.meta?.evidence_labels?.[k] || [k, ''];
    return shortLabel(label) + ' ' + fmtEvidence(ev[k], unit);
  }
  return '';
}

function card(m, no, prev) {
  const c = el('div', 'card' + (m.id === state.selectedId ? ' sel' : ''));
  c.dataset.id = m.id; c.dataset.no = no;

  const top = el('div', 'card-top');
  const id = el('div', 'card-id');

  const addr = el('div', 'card-addr');
  addr.append((m.suburb || '') + ' · ', el('span', 'sub', m.address || ''));
  id.appendChild(addr);
  id.appendChild(el('div', 'card-meta',
    [m.bedrooms ? m.bedrooms + ' 房' : '', m.bathrooms ? m.bathrooms + ' 卫' : '',
     typeZh(m.property_type), m.building_area ? m.building_area + ' ㎡' : ''].filter(Boolean).join(' · ')));
  id.appendChild(el('div', 'card-price', money(m.price)));
  top.appendChild(id);

  // 指标区。标签在上、值在下,统一一列 —— 一列卡片扫下来,
  // 同一个口径始终落在同一条竖线上,这是"可比较"的前提。
  const met = el('div', 'metrics');
  for (const [name, sc] of otherScores(m)) {
    const col = el('div', 'metric');
    col.append(el('div', 'ml', name));
    col.appendChild(pv(String(Math.round(sc)), PROV.PROOF, 'mv'));
    met.appendChild(col);
  }
  const hl = headline(m);
  const pm = el('div', 'metric primary');
  pm.appendChild(el('div', 'ml', hl.label));
  const v = pv(hl.fmt(hl.raw), hl.prov, 'mv');
  pm.appendChild(v);
  met.appendChild(pm);
  top.appendChild(met);
  c.appendChild(top);

  // 条件被改过 → 同一个 id 的旧值还在 → 翻滚过去。
  // 这是全站唯一的数值动效,只在"系统重新算过了"这个语义下出现。
  if (prev && prev.has(String(m.id))) {
    const old = prev.get(String(m.id));
    if (Number.isFinite(old) && old !== hl.raw) rollText(v, old, hl.raw, hl.fmt);
  }
  c.dataset.raw = String(hl.raw);

  if (hl.sub) c.appendChild(el('div', 'card-meta', hl.sub));

  const bg = marks(m);
  if (bg.asked.length) {
    const row = el('div', 'marks');
    for (const t of bg.asked) row.appendChild(el('span', 'mark ask', t));
    c.appendChild(row);
  }
  if (bg.risk.length) {
    const row = el('div', 'marks');
    row.appendChild(el('span', 'risk-lead', '须知'));
    for (const t of bg.risk) row.appendChild(el('span', 'mark warn', t));
    c.appendChild(row);
  }

  c.addEventListener('click', () => { select(m.id); openDetail(m); });
  return c;
}

// ══════════════════════════════════════════════════════════ 渲染入口
function render() {
  const head = $('#res-head'), box = $('#results');

  // 先把上一批的主指标值按 id 归档,**必须在清空之前** —— 条件改动后
  // 同一个 id 的数会被重算,那时才翻滚。这是全站唯一的数值动效触发条件。
  state.lastRaw = new Map($$('.card', box).map(c => [c.dataset.id, Number(c.dataset.raw)]));
  const prev = state.lastRaw;

  head.innerHTML = '';

  if (!state.metrics.length) {
    $('#res-hint').textContent = '—';
    if (state.count === 0 && state.ranking) box.appendChild(el('div', 'empty', '没有符合条件的房源。'));
    return;
  }

  // 标头:真实候选数 + 口径注脚。候选数是后端给的,主站一直没显示。
  const t = el('div', 'res-title');
  t.append('候选 ', el('span', 'n', comma(state.count)), ' 套 · 本批 ', el('span', 'n', String(state.metrics.length)));
  head.appendChild(t);

  const notes = el('div', 'res-notes');
  for (const n of (state.ranking || '').split(';').map(s => s.trim()).filter(Boolean)) {
    notes.appendChild(el('div', null, n));
  }
  // 图例直接挂在结果栏标头 —— 用户第一次看到 ◆ 的同一屏内就能查到它是什么意思。
  const lg = el('div', 'legend');
  lg.append(pv('实测', PROV.PROOF), pv('假设', PROV.ASSUME), pv('模型估', PROV.MODEL));
  notes.appendChild(lg);
  head.appendChild(notes);

  // 上一批的数值留存,用来判断哪些数需要翻滚
  const prevBy = new Map($$('.card', box).map(c => [c.dataset.id, c.__hlRaw]));

  // 上一批的数值留存已经不需要了 —— 翻滚的触发条件在 card() 里按 id 比对
  let i = 0;
  for (const m of state.metrics) {
    const no = state.offset + i + 1;
    const c = card(m, no, prev);
    c.style.setProperty('--d', Math.min(i++, 8) * 45 + 'ms');
    box.appendChild(c);
  }
  $('#res-hint').textContent = '本批 ' + state.metrics.length + ' 套';

  // 换一批
  const left = state.pool.length - (state.offset + state.metrics.length);
  if (state.pool.length > state.metrics.length) {
    const more = el('div', 'more');
    const b = el('button', null, left > 0 ? '下一批 · 还有 ' + left + ' 套 →' : '↺ 回到第一批');
    b.addEventListener('click', () => nextBatch(left > 0 ? state.offset + state.metrics.length : 0));
    more.appendChild(b);
    box.appendChild(more);
  }
  renderMap();
}

function select(id) {
  state.selectedId = id;
  $$('.card').forEach(c => c.classList.toggle('sel', c.dataset.id === id));
}

// ══════════════════════════════════════════════════════════ 地图
function renderMap() {
  const empty = $('#map-empty');
  if (!state.metrics.length) { empty.hidden = false; return; }
  empty.hidden = true;

  if (!state.map) {
    state.map = L.map('map', { zoomControl: false, attributionControl: false })
      .setView([-37.8136, 144.9631], 11);
    state.layer = L.layerGroup().addTo(state.map);
  }
  state.layer.clearLayers();
  state.blots = [];

  const pts = [];
  state.metrics.forEach((m, i) => {
    if (m.latitude == null) return;
    pts.push([m.latitude, m.longitude]);
    const no = state.offset + i + 1;
    // 图钉:方钉 + 一根引线 + 一个小菱形落在真实坐标上。
    // 菱形的尖端对着坐标,不是圆点扣在坐标中央 —— 后者会盖住它要标的那栋楼。
    const icon = L.divIcon({
      className: '', iconSize: [22, 34], iconAnchor: [11, 30],
      html: `<div class="pin"><div class="pin-in"><b>${no}</b></div><i></i><span class="pin-dot"></span></div>`,
    });
    const mk = L.marker([m.latitude, m.longitude], { icon }).addTo(state.layer);
    mk.on('click', () => { select(m.id); openDetail(m); });
    m.__marker = mk;
  });
  if (pts.length) state.map.fitBounds(pts, { padding: [40, 40], maxZoom: 14 });

  const m = state.metrics.find(x => x.id === state.selectedId);
  if (m) dropBlot(m);
  $('#map-hint').textContent = pts.length + ' 个坐标';
}

/** 选中时滴一滴颜料。基态可见、动画只挂在 .spreading ——
 *  rAF 被节流时动画停在起始帧,但颜料仍然在。
 *  「动画可以不播,结果不能赌」。(主站为这件事踩过三次,这里继承它的规则。) */
function dropBlot(m) {
  if (m.latitude == null || !state.map) return;
  if (m.__blot) { state.map.removeLayer(m.__blot); m.__blot = null; }
  const w = 0.0055;
  const b = L.rectangle([[m.latitude - w, m.longitude - w], [m.latitude + w, m.longitude + w]], {
    className: 'blot spreading', stroke: false, fillColor: '#BFA24E', fillOpacity: 1,
  }).addTo(state.map);
  m.__blot = b;
  setTimeout(() => { const n = document.querySelector('.blot'); if (n) n.classList.remove('spreading'); }, 620);
}

// ══════════════════════════════════════════════════════════ 详情
function row(k, vNode, cls) {
  const r = el('div', 'row');
  r.appendChild(el('span', 'k', k));
  r.appendChild(el('span', 'lead'));
  if (typeof vNode === 'string') r.appendChild(el('span', 'v' + (cls ? ' ' + cls : ''), vNode));
  else r.appendChild(vNode);
  return r;
}

function openDetail(m) {
  const d = $('#detail');
  d.innerHTML = '';

  const close = el('button', 'detail-close', '关闭 ✕');
  close.addEventListener('click', () => d.classList.remove('open'));
  d.appendChild(close);

  d.appendChild(el('div', 'd-en', 'FILE ' + m.id + ' / ' + (m.planning?.zone || '')));
  d.appendChild(el('h3', null, m.address + ', ' + m.suburb));
  d.appendChild(el('hr'));

  // 价格:实测字段。估值:模型字段。两者并排,溯源材质自己说明可信度。
  const ask = el('div', 'rows');
  ask.appendChild(row('售价', pv(money(m.price), PROV.PROOF)));
  ask.appendChild(row('模型估值', pv(money(m.predicted_price), PROV.MODEL)));
  ask.appendChild(row('估值区间', pv(money(m.valuation_range?.[0]) + ' – ' + money(m.valuation_range?.[1]), PROV.MODEL)));
  const err = m.valuation_error_pct;
  ask.appendChild(row('这类房型典型误差', pv('±' + pct(err, 1), PROV.MODEL)));
  // 估值差必须和"这类房型自己的误差"比,不能写死 10%
  if (m.predicted_gap != null && err != null) {
    const verdict = Math.abs(m.predicted_gap) > err
      ? (m.predicted_gap > 0 ? '低于模型估值' : '高于模型估值')
      : '在误差范围内,价格正常';
    ask.appendChild(row('判定', verdict));
  }
  d.appendChild(ask);
  d.appendChild(el('hr'));

  // 收益:全部依赖 opex / 购置杂费假设 → 整块 assume 材质。
  const inc = el('div', 'rows');
  inc.appendChild(row('年租金', pv(money(m.annual_rent), PROV.PROOF)));
  inc.appendChild(row('运营支出', pv(money(m.operating_expenses), PROV.ASSUME)));
  inc.appendChild(row('净运营收入', pv(money(m.noi), PROV.ASSUME)));
  inc.appendChild(row('毛回报率', pv(pct(m.gross_yield), PROV.PROOF)));
  inc.appendChild(row('Cap Rate', pv(pct(m.cap_rate), PROV.ASSUME)));
  inc.appendChild(row('ROI', pv(pct(m.roi), PROV.ASSUME)));
  d.appendChild(inc);
  d.appendChild(el('div', 'card-meta',
    '假设:运营支出 = 年租金 ' + pct(m.assumptions?.opex_rate, 1) + ' · 购置杂费 ' + money(m.assumptions?.other_acquisition_costs)));

  // 周边:实测直线距离
  if (m.amenities && Object.keys(m.amenities).length) {
    d.appendChild(el('hr'));
    const a = el('div', 'rows');
    for (const [kind, v] of Object.entries(m.amenities)) {
      if (v?.distance_m == null) continue;
      a.appendChild(row((state.meta?.kinds?.[kind] || kind) + (v.name && v.name !== '(未命名)' ? ' · ' + v.name : ''),
        pv(dist(v.distance_m), PROV.PROOF)));
    }
    d.appendChild(a);
  }

  // 规划:法定"允许"范围,不是预测 —— 这句限定必须留在界面上
  if (m.planning?.summary) {
    d.appendChild(el('hr'));
    d.appendChild(el('div', 'd-en', 'PLANNING / 规划'));
    d.appendChild(el('div', null, m.planning.summary));
    if (m.planning.caveat) d.appendChild(el('div', 'card-meta', m.planning.caveat));
  }

  d.classList.add('open');
  dropBlot(m);
}

// ══════════════════════════════════════════════════════════ 条件卡
function renderConditions() {
  const p = state.params;
  const chat = $('#chat');
  let box = $('#cond');
  if (!box) { box = el('div', 'conditions'); box.id = 'cond'; chat.appendChild(box); }
  box.innerHTML = '';

  const head = el('div', 'cond-head');
  head.appendChild(el('span', 'ttl', '系统认为你要的'));
  const edit = el('button', 'lnk', '改条件');
  edit.addEventListener('click', () => editPopover());
  head.appendChild(edit);
  box.appendChild(head);

  const hard = [];
  if (p.max_price) hard.push('预算 ≤ ' + money(p.max_price));
  if (p.min_price) hard.push('预算 ≥ ' + money(p.min_price));
  if (p.bedrooms) hard.push(p.bedrooms + ' 房');
  if (p.bathrooms) hard.push(p.bathrooms + ' 卫');
  if (p.property_type) hard.push(typeZh(p.property_type));
  if (p.suburb) hard.push(p.suburb);

  if (hard.length) {
    const g = el('div', 'cond-group');
    g.appendChild(el('div', 'tk', '硬条件'));
    const cs = el('div', 'chips');
    for (const h of hard) cs.appendChild(el('span', 'chip hard', h));
    g.appendChild(cs);
    box.appendChild(g);
  }

  const soft = [];
  for (const n of (p.abstract_needs || [])) soft.push(attrZh(n.attribute) + (n.weight ? ' · 权重 ' + n.weight : ''));
  for (const a of (p.amenity_needs || [])) {
    soft.push('近' + (state.meta?.kinds?.[a.kind] || a.kind) + (a.max_distance_m ? ' ' + dist(a.max_distance_m) + '内' : ''));
  }
  if (p.near_place) soft.push('近 ' + p.near_place.name);
  if (p.school_zone) soft.push('要学区');
  if (p.min_gross_yield != null) soft.push('毛回报 ≥ ' + pct(p.min_gross_yield, 1));

  if (soft.length) {
    const g = el('div', 'cond-group');
    g.appendChild(el('div', 'tk', '偏好'));
    const cs = el('div', 'chips');
    for (const s of soft) cs.appendChild(el('span', 'chip', s));
    g.appendChild(cs);
    box.appendChild(g);
  }

  if (p.sort_by) {
    const g = el('div', 'cond-group');
    g.appendChild(el('div', 'tk', '排序'));
    const cs = el('div', 'chips');
    cs.appendChild(el('span', 'chip', state.meta?.sort_labels?.[p.sort_by] || p.sort_by));
    g.appendChild(cs);
    box.appendChild(g);
  }

  // 系统答不了的要求。后端在 meta.unsupported 里列了 13 项和原因,
  // 主站没展示 —— 而"知道系统不知道什么"正好是这个项目的立论。
  const uns = p.unsupported_asks;
  if (Array.isArray(uns) && uns.length) {
    const g = el('div', 'cond-group');
    g.appendChild(el('div', 'tk', '这轮答不了的'));
    for (const u of uns) {
      const name = typeof u === 'string' ? u : (u.ask || u.name || '');
      const why = typeof u === 'string' ? (state.meta?.unsupported?.[u] || '') : (u.reason || state.meta?.unsupported?.[name] || '');
      const c = el('div', 'card-meta', name + (why ? ' — ' + why.split('。')[0] : ''));
      g.appendChild(c);
    }
    box.appendChild(g);
  }
}

// ══════════════════════════════════════════════════════════ 浮层
function scrim(on) {
  let s = $('#scrim');
  if (!s) { s = el('div', 'scrim'); s.id = 'scrim'; document.body.appendChild(s); }
  s.classList.toggle('open', on);
}
function closePopover() { $('#popover').classList.remove('open'); scrim(false); }

function popover(title, fields, onApply, hint) {
  const p = $('#popover');
  p.innerHTML = '';
  p.appendChild(el('h4', null, title));
  if (hint) p.appendChild(el('div', 'card-meta', hint));

  const inputs = fields.map(f => {
    const lab = el('label');
    lab.appendChild(el('span', 'tk', f.label));
    let inp;
    if (f.type === 'select') {
      inp = el('select');
      for (const [v, t] of f.options) { const o = el('option', null, t); o.value = v; inp.appendChild(o); }
      inp.value = f.value ?? '';
    } else {
      inp = el('input'); inp.type = f.type; inp.value = f.value ?? '';
    }
    lab.appendChild(inp);
    p.appendChild(lab);
    return inp;
  });

  const acts = el('div', 'acts');
  const cancel = el('button', null, '取消');
  cancel.addEventListener('click', closePopover);
  const go = el('button', 'go', '应用');
  go.addEventListener('click', () => {
    onApply(inputs.map(i => i.value));
    closePopover();
  });
  acts.append(cancel, go);
  p.appendChild(acts);

  p.classList.add('open'); scrim(true);
  inputs[0]?.focus();
}

/** 改条件。只暴露两个真正会变口径的旋钮(预算、排序),
 *  其余留给对话 —— 面板上堆二十个输入框,是把"说一句话"这件事做回去了。 */
function editPopover() {
  const p = state.params || {};
  const sorts = Object.entries(state.meta?.sort_labels || {}).map(([k, v]) => [k, v]);
  popover('改条件', [
    { label: '预算上限(AUD)', type: 'number', value: p.max_price ?? '' },
    { label: '排序口径', type: 'select', value: p.sort_by ?? '', options: [['', '默认(相关度)']].concat(sorts) },
  ], ([maxp, sort]) => {
    const next = { ...p };
    const v = parseFloat(maxp);
    next.max_price = isNaN(v) || v <= 0 ? null : v;
    next.sort_by = sort || null;
    refine(next);
  }, '改完直接重跑,不经过 LLM 解析 —— 所以是秒回。');
}

// ══════════════════════════════════════════════════════════ SSE
async function sse(url, body, on) {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);

  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = 'message', data = '';
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) ev = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      let obj = null; try { obj = JSON.parse(data); } catch { continue; }
      // 一个事件的处理失败不该让整条流静默死掉 —— 之前就是这样:抛出去变成
      // 未处理的 Promise 拒绝,页面上只剩一句没头没尾的话,连是哪个事件都不知道。
      try {
        const fn = on[ev];
        if (typeof fn !== 'function') {
          showFatal('sse', new Error('未知事件 "' + ev + '"(handler 里没有这个名字)'));
          continue;
        }
        fn(obj);
      } catch (err) {
        showFatal('sse:' + ev, err);
      }
    }
  }
}

function handlers(r, asst) {
  let tokens = '', answered = false;
  return {
    node: ({ node }) => r.node(node),
    params: ({ intent, params }) => { state.intent = intent; state.params = params; renderConditions(); },
    ranking: ({ ranking, count }) => { state.ranking = ranking || ''; r.count(count || 0, ''); },
    more: ({ metrics }) => { },
    results: ({ metrics }) => {
      state.metrics = metrics || []; state.selectedId = null;
      state.pool = metrics || []; state.offset = 0;
      r.stage('整理结果');
      render();
    },
    token: ({ t }) => {
      if (!answered) { tokens += t; asst.textContent = tokens; asst.classList.add('streaming'); }
    },
    answer: ({ answer }) => {
      answered = true;
      asst.classList.remove('streaming');
      asst.textContent = '';
      renderAnswer(asst, answer || tokens);
    },
    done: ({ params, ranking, count, intent }) => {
      if (params) state.params = params;
      if (ranking != null) state.ranking = ranking;
      if (count != null) state.count = count;
      if (intent) state.intent = intent;
      r.end();
      renderConditions();
      if (!state.metrics.length) render();
    },
    error: ({ message }) => { r.fail(message || '出错了'); },
  };
}

/** 说明排成「一句话结论 + 要点」。主站已经证明分段列表比一大段好读,
 *  这里保留它的结构,只把要点换成等宽行首短横。 */
function renderAnswer(host, text) {
  const lines = String(text || '').split('\n').map(s => s.trim()).filter(Boolean);
  const frag = document.createDocumentFragment();
  const bullets = el('div', 'bullets');
  let started = false;
  for (const line of lines) {
    const isB = /^[-•*·]\s*/.test(line);
    const txt = line.replace(/^[-•*·]\s*/, '');
    if (isB) { started = true; bullets.appendChild(el('div', null, txt)); }
    else {
      if (started) { frag.appendChild(bullets.cloneNode(true)); while (bullets.firstChild) bullets.removeChild(bullets.firstChild); started = false; }
      frag.appendChild(el('p', null, txt));
    }
  }
  if (bullets.childNodes.length) frag.appendChild(bullets);
  host.replaceChildren(frag);
}

// ══════════════════════════════════════════════════════════ 动作
function setStage(s) { $('#lab').dataset.stage = s; }
function setRunning(v) { state.running = v; $('#send').disabled = v; }

function addUser(text) {
  const e = el('div', 'msg-user', text);
  $('#chat').appendChild(e); scrollChat(); return e;
}
function addAsst() {
  const a = el('div', 'msg-asst');
  $('#chat').appendChild(a); scrollChat(); return a;
}
function scrollChat() {
  const c = $('#chat-scroll');
  c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' });
}

async function send(text) {
  if (!text.trim() || state.running) return;
  setStage('working'); setRunning(true);
  addUser(text);
  const asst = addAsst();
  const r = rail($('#chat'));
  try {
    await sse('/api/chat', { thread_id: state.threadId, message: text },
      handlers(r, asst));
  } catch (e) {
    r.fail(String(e.message || e));
  } finally {
    setRunning(false);
  }
}

async function refine(params) {
  if (state.running) return;
  setRunning(true);
  const asst = addAsst();
  const r = rail($('#chat'));
  r.stage('按新条件重新找');
  try {
    await sse('/api/refine', { thread_id: state.threadId, params }, handlers(r, asst));
  } catch (e) {
    r.fail(String(e.message || e));
  } finally {
    setRunning(false);
  }
}

async function nextBatch(offset) {
  if (state.running) return;
  setRunning(true);
  const asst = addAsst();
  const r = rail($('#chat'));
  r.stage('换一批');
  try {
    await sse('/api/rebatch', { thread_id: state.threadId, offset }, handlers(r, asst));
  } catch (e) {
    r.fail(String(e.message || e));
  } finally {
    setRunning(false);
  }
}

// ══════════════════════════════════════════════════════════ 初始化
const EXAMPLES = [
  '100 万以内、离火车站近的三房',
  '靠近墨尔本大学,安静一点的公寓',
  '80 万以下,租金回报最高的',
  'Richmond 附近,售价低于估值的',
];

function init() {
  const ex = $('#examples');
  EXAMPLES.forEach((t, i) => {
    const b = el('button', 'example', t);
    b.type = 'button'; b.dataset.n = String(i + 1).padStart(2, '0');
    b.addEventListener('click', () => { $('#input').value = t; send(t); });
    ex.appendChild(b);
  });

  $('#composer').addEventListener('submit', e => {
    e.preventDefault();
    const v = $('#input').value;
    $('#input').value = '';
    send(v);
  });

  $('#btn-new').addEventListener('click', () => {
    state.threadId = 'lab-' + Math.random().toString(36).slice(2, 10);
    state.metrics = []; state.pool = []; state.params = null; state.selectedId = null; state.count = 0;
    $('#chat').innerHTML = ''; $('#results').innerHTML = ''; $('#res-head').innerHTML = '';
    $('#detail').classList.remove('open');
    setStage('welcome');
    if (state.layer) state.layer.clearLayers();
  });

  $('#btn-assume').addEventListener('click', async () => {
    const m = await (await fetch('/api/meta')).json();
    const a = m.assumptions || {};
    popover('全局假设', [
      { label: '运营支出占年租金比例(%)', type: 'number', value: (a.snapshot?.opex_rate ?? 0.28) * 100 },
      { label: '购置杂费(AUD)', type: 'number', value: a.snapshot?.other_acquisition_costs ?? 2000 },
    ], async ([r, f]) => {
      await fetch('/api/assumptions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ opex_rate: parseFloat(r) / 100, other_acquisition_costs: parseFloat(f) }),
      });
      if (state.params) refine(state.params);
    }, '改这里会重算所有 Cap Rate / ROI。注意:假设是进程级的 —— 你改了,别人也变。');
  });

  $('#scrim')?.addEventListener('click', closePopover);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closePopover(); $('#detail').classList.remove('open'); } });

  setStage('welcome');
}

(async () => {
  init();
  try {
    state.meta = await (await fetch('/api/meta')).json();
  } catch (e) {
    console.error('meta 加载失败', e);
  }
})();

})();
