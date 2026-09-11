/* lab.js 的真冒烟:把 send() 跑通,而不是只测"能装载"。
 *
 * 上一版测试的失职:它只验证了脚本能 init,就宣布"字段假设一致"。
 * 但页面上的报错发生在**事件回调**里,而回调要真的调一次 send() 才会执行。
 * 这个版本用真 fetch 打真服务,把整条 卡片渲染 + 地图跳过 + 条件卡 路径走一遍。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const DIR = 'D:/projects/Capstone-Project-CSIT998/_ui-lab/';
const BASE = process.env.LAB_BASE || 'http://127.0.0.1:8137';

// ─────────────────────────────────────────── 最小 DOM 桩
class Cls {
  constructor() { this.s = new Set(); }
  add(...x) { x.forEach(v => v && this.s.add(v)); }
  remove(...x) { x.forEach(v => this.s.delete(v)); }
  toggle(v, on) { if (on === undefined) on = !this.s.has(v); on ? this.s.add(v) : this.s.delete(v); return on; }
  contains(v) { return this.s.has(v); }
  set className(v) { this.s = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this.s].join(' '); }
}
class El extends Cls {
  constructor(tag) {
    super();
    this.tagName = String(tag || 'div').toUpperCase();
    this.children = []; this.parentNode = null; this._text = '';
    this.dataset = {}; this.attrs = {}; this._html = '';
    this.style = { setProperty() {} };
    this.listeners = {};
    this._value = '';
  }
  set id(v) { this._id = v; } get id() { return this._id || ''; }
  set textContent(v) { this._text = v == null ? '' : String(v); this.children = []; }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join('') : this._text; }
  set innerHTML(v) { this._html = String(v); this.children = []; this._text = ''; }
  get innerHTML() { return this._html; }
  set value(v) { this._value = String(v); } get value() { return this._value; }
  appendChild(c) {
    if (!c) throw new Error('appendChild(null) on <' + this.tagName + '>');
    c.parentNode = this; this.children.push(c); return c;
  }
  append(...cs) { for (const c of cs) typeof c === 'string' ? this.appendChild(new Text(c)) : this.appendChild(c); }
  removeChild(c) { this.children = this.children.filter(x => x !== c); }
  replaceChildren(...cs) { this.children = []; this._text = ''; this.append(...cs); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener() {}
  fire(t, ev = {}) { for (const fn of (this.listeners[t] || [])) fn({ preventDefault() {}, ...ev }); }
  focus() {} scrollTo() {}
  querySelector(s) { return query(this, s)[0] || null; }
  querySelectorAll(s) { return query(this, s); }
  cloneNode() { const e = new El(this.tagName); e.s = new Set(this.s); e._text = this._text; return e; }
  get firstChild() { return this.children[0] || null; }
  get childNodes() { return this.children; }
  get classList() { return this; }
}
class Text {
  constructor(t) { this._text = String(t); this.children = []; }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
}
function matches(el, sel) {
  // 文本节点没有 tagName / classList —— 不挡住就会抛 "Cannot read properties of
  // undefined (reading 'contains')",而这个异常会一路冒到 await 链里被静默吞掉。
  // 之前几轮诊断全被这一行废掉了。
  if (!el || !el.tagName) return false;
  sel = sel.trim();
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  if (sel.startsWith('.')) return !!(el.classList && el.classList.contains(sel.slice(1)));
  return el.tagName === sel.toUpperCase();
}
/** 支持 `#id .cls` / `#id tag` 两段后代选择器 ——
 *  上一版只支持单段,于是 '#composer .send' 永远返回 null,
 *  测出来的错误是桩的错,不是代码的错。 */
function query(root, sel) {
  const out = [];
  const DBG = sel === '#composer .send';
  for (const part of sel.split(',').map(s => s.trim())) {
    const bits = part.split(/\s+/).filter(Boolean);
    let cands = [root];
    for (let k = 0; k < bits.length; k++) {
      const last = k === bits.length - 1;
      const next = [];
      for (const c of cands) {
        for (const d of allDesc(c)) {
          if (!matches(d, bits[k])) continue;
          if (last) next.push(d);
          // 不是最后一段:这个匹配元素的后代继续参与下一段
          else next.push(...allDesc(d));
        }
      }
      cands = [...new Set(next)];
      if (DBG) console.log('   [query] bit=' + JSON.stringify(bits[k]) + ' last=' + last + ' → ' + cands.length + ' 个候选');
    }
    out.push(...(bits.length === 1 ? cands.filter(x => matches(x, bits[0])) : cands));
  }
  return [...new Set(out)];
}
function allDesc(n, acc = []) {
  for (const c of n.children || []) { acc.push(c); allDesc(c, acc); }
  return acc;
}

const registry = new Map();
const TRACE = [];
const document = {
  createElement: t => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: t => new Text(t),
  createDocumentFragment: () => new El('fragment'),
  querySelector(s) {
    // #id 也必须在树里找:元素可能由 JS 动态创建并挂到树上(如 #cond),
    // 只查静态 registry 会漏掉它们 —— 上一版就因此误报"条件卡没建出来"。
    const byId = s.startsWith('#') ? allDesc(document.body).find(e => e.id === s.slice(1)) : null;
    const hit = byId || (registry.get(s.slice(1)) || null) || (query(document.body, s)[0] || null);
    TRACE.push(s + ' → ' + (hit ? 'HIT<' + (hit.id || hit.className) + '>' : 'NULL'));
    return hit;
  },
  querySelectorAll(s) { const r = query(document.body, s); TRACE.push(s + ' → ' + r.length + ' 个'); return r; },
  addEventListener() {}, body: new El('body'), hidden: false,
};
for (const id of ['lab', 'chat-scroll', 'chat', 'examples', 'composer', 'input', 'send', 'btn-new',
                  'btn-assume', 'res-head', 'res-hint', 'results', 'detail', 'popover',
                  'map', 'map-empty', 'map-hint', 'scrim']) {
  const e = new El('div'); e.id = id; registry.set(id, e); document.body.appendChild(e);
}
registry.get('send').tagName = 'BUTTON';

// ─────────────────────────────────────────── 运行
const ERRORS = [];
const TRACE_LOG = [];
const LOG = m => { TRACE_LOG.push(m); console.log(m); };
process.on('exit', () => {
  fs.writeFileSync('D:/projects/Capstone-Project-CSIT998/_ui-lab/_smoke2_trace.txt', TRACE_LOG.join('\n'), 'utf8');
});
(async () => {
 try {
  const src = fs.readFileSync(path.join(DIR, 'lab.js'), 'utf8');
  const realFetch = globalThis.fetch;

  // 真打服务,但记录每一次请求 —— 如果一次请求都没有,说明 send() 在更早的地方就挂了
  const REQS = [];
  const fetchStub = async (url, opt) => {
    REQS.push(String(url) + ' ' + (opt?.method || 'GET'));
    const abs = String(url).startsWith('http') ? url : BASE + url;
    return realFetch(abs, opt);
  };

  const win = {
    document, fetch: fetchStub,
    performance: { now: () => Number(process.hrtime.bigint() / 1000000n) },
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    requestAnimationFrame: cb => setImmediate(() => cb(0)),
    cancelAnimationFrame() {}, addEventListener() {}, setTimeout, clearTimeout,
    setInterval, clearInterval, console,
  };

  // 未捕获的 Promise / 异常都记进 ERRORS
  const origErr = console.error;
  console.error = (...a) => { ERRORS.push('console.error: ' + a.map(String).join(' ')); origErr(...a); };
  process.on('unhandledRejection', e => ERRORS.push('unhandledRejection: ' + (e && e.message || e)));

  try {
    new Function('window', 'document', 'fetch', 'performance', 'L',
      'requestAnimationFrame', 'setTimeout', 'setInterval', 'clearInterval', 'console', 'Math',
      src)(win, document, fetchStub, win.performance, undefined,
           win.requestAnimationFrame, setTimeout, setInterval, clearInterval, console, Math);
  } catch (e) {
    ERRORS.push('装载抛错: ' + e.message);
  }

  // 等 meta 的 await 落地
  await new Promise(r => setTimeout(r, 400));

// ─── 关键:真的发一次请求,把整条回调路径走完 ───
  console.log('桩自检: #send → ' + (document.querySelector('#send') ? '有' : '无')
    + ' · #results → ' + (document.querySelector('#results') ? '有' : '无')
    + ' · body.children=' + document.body.children.length);
  console.log('调用 send() …');
  const input = registry.get('input');
  input.value = process.argv[2] || '100 万以内、离火车站近的三房';
  try {
    registry.get('composer').fire('submit');
    console.log('submit 已触发(同步部分走完)');
  } catch (e) {
    ERRORS.push('submit 同步抛错: ' + e.message + '\n' + e.stack);
  }

  // 等到结果渲染出来(最多 45 秒)
  const res = registry.get('results');
  const t0 = Date.now();
  while (Date.now() - t0 < 45000) {
    await new Promise(r => setTimeout(r, 250));
    if (query(res, '.card').length || ERRORS.length) break;
  }

  console.log('\n───────── 结果 ─────────');
  console.log('渲染出的卡片数: ' + query(res, '.card').length);
  console.log('发出的请求: ' + (REQS.length ? REQS.join(' | ') : '(一次都没有 —— send() 在发请求前就挂了)'));
  console.log('结果栏标头: "' + registry.get('res-head').textContent.slice(0, 120) + '"');
  console.log('条件卡存在: ' + (document.querySelector('#cond') ? '是' : '否'));
  console.log('左栏对话节点数: ' + registry.get('chat').children.length);
  console.log('左栏节点明细:');
  registry.get('chat').children.forEach((c, i) => {
    console.log('   [' + i + '] <' + c.tagName + '> id=' + JSON.stringify(c.id)
      + ' class=' + JSON.stringify(c.className)
      + ' text=' + JSON.stringify(c.textContent.slice(0, 60)));
  });
  console.log('#cond 查得到吗: ' + (document.querySelector('#cond') ? '是' : '否 —— renderConditions 没建出来'));
  console.log('params 事件是否到过: ' + (registry.get('chat').children.some(c => c.id === 'cond') ? '是' : '否'));
  console.log('详情面板 open: ' + registry.get('detail').classList.contains('open'));
  console.log('DOM 里的错误面板内容: ' + (() => {
    const f = registry.get('fatal');
    return f ? JSON.stringify(f.textContent.slice(0, 600)) : '(没有 #fatal,说明页面级错误没触发)';
  })());

  if (ERRORS.length) {
    console.log('\n❌ 捕获 ' + ERRORS.length + ' 个错误:');
    ERRORS.forEach(e => console.log('   ' + e));
    process.exit(1);
  }
  console.log('\n✅ send() 全路径无错误');
 } catch (e) {
  console.log('\n❌ 测试骨架自己抛错(说明错误发生在 await 链里,以前被静默吞掉了):');
  console.log(e && (e.stack || e.message || String(e)));
  process.exit(2);
 }
})();
