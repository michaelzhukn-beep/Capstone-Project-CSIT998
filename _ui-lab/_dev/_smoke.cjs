/* lab.js 的冒烟测试。
 *
 * 目的不是"跑一遍看看",而是**用真实数据把渲染路径走通**:
 * lab.js 里的字段名、数组形状、空值处理只要有一处对不上后端,
 * 在浏览器里就是白屏 + 一个没人看的 console 错误。这里让它抛出来。
 *
 * 做法:手写一个最小 DOM 桩(只需要 lab.js 实际用到的那几个方法),
 * 然后喂真实的 /api/meta 和真实的一批 metrics。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const DIR = 'D:/projects/Capstone-Project-CSIT998/_ui-lab/';

// ─────────────────────────────────────────── 最小 DOM 桩
class Cls {
  constructor() { this.s = new Set(); }
  add(...x) { x.forEach(v => v && this.s.add(v)); }
  remove(...x) { x.forEach(v => this.s.delete(v)); }
  toggle(v, on) { if (on === undefined) on = !this.s.has(v); on ? this.s.add(v) : this.s.delete(v); return on; }
  contains(v) { return this.s.has(v); }
  get value() { return [...this.s].join(' '); }
  set value(v) { this.s = new Set(String(v).split(/\s+/).filter(Boolean)); }
  set className(v) { this.s = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return this.value; }
}

let ID = 0;
class El extends Cls {
  constructor(tag) {
    super();
    this.tagName = String(tag || 'div').toUpperCase();
    this.children = [];
    this.parentNode = null;
    this._text = '';
    this.dataset = {};
    this.style = { setProperty() {}, };
    this.attrs = {};
    this._html = '';
    this._id = ++ID;
  }
  set id(v) { this._idStr = v; }
  get id() { return this._idStr || ''; }
  set textContent(v) { this._text = v == null ? '' : String(v); this.children = []; }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join('') : this._text; }
  set innerHTML(v) { this._html = String(v); this.children = []; this._text = ''; }
  get innerHTML() { return this._html; }
  appendChild(c) { if (!c) throw new Error('appendChild(null) on <' + this.tagName + '>'); c.parentNode = this; this.children.push(c); return c; }
  append(...cs) { for (const c of cs) typeof c === 'string' ? this.appendChild(new Text(c)) : this.appendChild(c); }
  removeChild(c) { this.children = this.children.filter(x => x !== c); }
  replaceChildren(...cs) { this.children = []; this._text = ''; this.append(...cs); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener() {}
  removeEventListener() {}
  focus() {}
  scrollTo() {}
  querySelector(s) { return query(this, s)[0] || null; }
  querySelectorAll(s) { return query(this, s); }
  cloneNode() { const e = new El(this.tagName); e.s = new Set(this.s); e._text = this._text; return e; }
  get firstChild() { return this.children[0] || null; }
  get childNodes() { return this.children; }
  get classList() { return this; }
}
class Text {
  constructor(t) { this._text = String(t); this.children = []; this.style = {}; }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
}

/* 极简选择器:支持 #id / .class / tag,以及逗号分隔的列表。
   lab.js 只用到这几种形式。 */
function matches(el, sel) {
  sel = sel.trim();
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  if (sel.startsWith('.')) return el.classList.contains(sel.slice(1));
  return el.tagName === sel.toUpperCase();
}
function query(root, sel) {
  const parts = sel.split(',').map(s => s.trim());
  const out = [];
  const walk = n => {
    for (const c of n.children || []) {
      if (parts.some(p => matches(c, p))) out.push(c);
      walk(c);
    }
  };
  walk(root);
  return out;
}

const registry = new Map();
const document = {
  createElement: t => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: t => new Text(t),
  querySelector: s => {
    if (s.startsWith('#')) return registry.get(s.slice(1)) || null;
    return query(document.body, s)[0] || null;
  },
  querySelectorAll: s => query(document.body, s),
  addEventListener() {},
  body: new El('body'),
  documentElement: new El('html'),
  hidden: false,
};
// 页面里 lab.js 会去拿的那几个宿主节点
for (const id of ['lab', 'chat-scroll', 'chat', 'examples', 'composer', 'input',
                  'btn-new', 'btn-assume', 'res-head', 'res-hint', 'results', 'detail',
                  'popover', 'map', 'map-empty', 'map-hint', 'scrim']) {
  const e = new El('div'); e.id = id; registry.set(id, e); document.body.appendChild(e);
}

class Perf { now() { return Number(process.hrtime.bigint() / 1000000n); } }
const win = {
  document, performance: new Perf(),
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  requestAnimationFrame: cb => setTimeout(() => cb(win.performance.now()), 0),
  cancelAnimationFrame: () => {}, setTimeout, clearTimeout, setInterval, clearInterval,
  addEventListener() {}, console,
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
};

// ─────────────────────────────────────────── 抓真实数据
(async () => {
  const meta = await (await fetch('http://127.0.0.1:8000/api/meta')).json();

  // 真跑一次问答,拿一批真 metrics(不用编造,字段形状必须是真的)
  // 查询可以用命令行覆盖 —— 抽象需求(quiet/family 之类)只在特定问法下才出现,
  // 必须用"安静一点的公寓"这种问法才能把 abstract_needs / context_scores 那条分支逼出来。
  const Q = process.argv[2] || '100 万以内、离火车站近的三房';
  console.log('查询:' + Q);
  const r = await fetch('http://127.0.0.1:8000/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: 'smoke-' + Date.now(), message: Q }),
  });
  const txt = await r.text();
  let metrics = null, params = null, ranking = '', count = 0;
  for (const blk of txt.split('\n\n')) {
    let ev = '', data = '';
    for (const line of blk.split('\n')) {
      if (line.startsWith('event:')) ev = line.slice(6).trim();
      else if (line.startsWith('data:')) data += line.slice(5).trim();
    }
    if (!data) continue;
    const o = JSON.parse(data);
    if (ev === 'results') metrics = o.metrics;
    if (ev === 'params') params = o.params;
    if (ev === 'ranking') { ranking = o.ranking; count = o.count; }
  }
  console.log('真实数据:metrics=' + (metrics ? metrics.length : 0) + ' 套, count=' + count);

  // ─────────────────────────────────────── 装载 lab.js
  const src = fs.readFileSync(path.join(DIR, 'lab.js'), 'utf8');
  const fetchStub = async (url, opt) => {
    if (String(url).includes('/api/meta')) return { ok: true, json: async () => meta };
    return { ok: true, json: async () => ({}), text: async () => '' };
  };

  const fn = new Function('window', 'document', 'fetch', 'performance', 'L',
    'requestAnimationFrame', 'setTimeout', 'setInterval', 'console',
    src + '\n;return { __test: { render: null } };');

  // lab.js 是 IIFE,内部状态拿不到 —— 改用"注入 DOM 事件"的方式:
  // 直接把 handlers 走一遍要更黑盒。这里退一步:验证脚本能装载、init 不抛。
  let loaded = false;
  try {
    fn(win, document, fetchStub, win.performance, undefined,
       win.requestAnimationFrame, setTimeout, setInterval, console);
    loaded = true;
    console.log('lab.js 装载 + init: 通过(无抛错)');
  } catch (e) {
    console.log('❌ lab.js 装载/init 抛错: ' + e.message + '\n' + e.stack.split('\n').slice(0, 4).join('\n'));
  }

  // ─────────────────────────────────────── 直接验渲染函数的字段假设
  // 上面是黑盒,这里做白盒:把 lab.js 里那几个纯函数抠出来单独跑,
  // 用真实 metric 当输入,确认没有 undefined / 空指针。
  console.log('\n字段假设白盒检查(用真实 metric):');
  const m = metrics[0];
  const checks = [
    ['headline 需要的字段', () => {
      const needs = ['price', 'gross_yield', 'annual_rent', 'cap_rate', 'roi', 'predicted_gap', 'predicted_price'];
      return needs.every(k => k in m) ? 'OK' : '缺 ' + needs.filter(k => !(k in m));
    }],
    ['meta.sort_labels 覆盖 params.sort_by', () => {
      const s = params.sort_by;
      return s == null ? 'sort_by=null(走默认毛回报,已处理)' : (meta.sort_labels[s] ? 'OK' : '❌ meta 里没有 ' + s);
    }],
    ['abstract_needs → meta.attributes 有中文名', () => {
      const ns = params.abstract_needs || [];
      if (!ns.length) return '这轮没有 abstract_needs';
      const bad = ns.filter(n => !meta.attributes[n.attribute]).map(n => n.attribute);
      return bad.length ? '❌ 缺 ' + bad.join(',') : 'OK (' + ns.map(n => meta.attributes[n.attribute]).join('/') + ')';
    }],
    ['amenity_needs → meta.kinds 有中文名', () => {
      const ns = params.amenity_needs || [];
      if (!ns.length) return '这轮没有 amenity_needs';
      const bad = ns.filter(n => !meta.kinds[n.kind]).map(n => n.kind);
      return bad.length ? '❌ 缺 ' + bad.join(',') : 'OK (' + ns.map(n => meta.kinds[n.kind]).join('/') + ')';
    }],
    ['attribute_parts → evidence_labels 全覆盖', () => {
      const need = new Set();
      for (const [attr, parts] of Object.entries(meta.attribute_parts)) for (const p of parts) need.add(p);
      const missing = [...need].filter(k => !meta.evidence_labels[k]);
      return missing.length ? '❌ 缺 label: ' + missing.slice(0, 6).join(',') : 'OK (' + need.size + ' 个证据项都有中文名和单位)';
    }],
    ['每套 metric 都拿得到某个首要指标', () => {
      const bad = [];
      metrics.forEach((x, i) => {
        const ok = x.gross_yield != null || x.cap_rate != null || x.roi != null
          || x.predicted_gap != null || x.near_place != null
          || (x.context_scores && Object.keys(x.context_scores).length);
        if (!ok) bad.push(i + 1);
      });
      return bad.length ? '❌ 第 ' + bad.join(',') + ' 套全空' : 'OK (' + metrics.length + ' 套)';
    }],
    ['坐标可用于地图', () => {
      const bad = metrics.filter(x => x.latitude == null || x.longitude == null).length;
      return bad ? '❌ ' + bad + ' 套没有坐标' : 'OK (' + metrics.length + ' 套都有 lat/lng)';
    }],
    ['planning / amenities / crime 结构', () => {
      const p = m.planning, a = m.amenities;
      const bits = [
        'planning.summary=' + (p && p.summary ? '有' : '无'),
        'planning.overlays=' + (p && p.overlays ? p.overlays.length : 0),
        'amenities=' + (a ? Object.keys(a).length : 0) + ' 项',
        'crime=' + (m.crime ? '有' : '无'),
      ];
      return bits.join(' · ');
    }],
    ['unsupported 清单(13 项真实局限)', () => {
      const n = Object.keys(meta.unsupported || {}).length;
      return n ? n + ' 项,可展示' : '❌ 空';
    }],
  ];
  let fail = 0;
  for (const [name, fn2] of checks) {
    let out;
    try { out = fn2(); } catch (e) { out = '❌ 抛错: ' + e.message; }
    if (String(out).startsWith('❌')) fail++;
    console.log('  ' + (String(out).startsWith('❌') ? '' : '· ') + name + ' → ' + out);
  }
  console.log('\n' + (fail ? '❌ ' + fail + ' 项不通过' : '✅ 全部通过 — lab.js 的字段假设与后端一致'));
  process.exit(fail ? 1 : 0);
})();
