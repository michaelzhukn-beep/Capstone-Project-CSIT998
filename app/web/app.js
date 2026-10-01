/* 筑明AI(Nestwise)· 单页前端。V8。
 *
 * 只做三件事:把对话发给 /api/chat、把条件卡的改动发给 /api/refine、把事件流
 * 画出来。所有中文名、口径、假设都从 /api/meta 取,前端不硬编码。
 *
 * 数字的三种来源在视觉上分开(这是整个项目的主张,不是装饰):
 *   实测 / 法定  黑色
 *   基于假设     灰色 + 点状下划线 + 前缀 ~
 *   模型预测     蓝色 + 菱形
 */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  const state = {
    threadId: null, meta: null, params: null, intent: null,
    metrics: [], ranking: '', count: 0, answer: '', running: false,
    selectedId: null, map: null, mapRO: null, pins: [],
    // 「换一批」用的翻页。pool 是排序后的前 20 套(后端一次给全,已经算好了),
    // metrics 是最新结果的那 5 套,offset 是它们在 pool 里的起点;历史展示独立读取 historyView。
    pool: [], offset: 0, moreBuf: null,
    lang: 'zh', requestSerial: 0, resultNotice: '', historyView: null,
    // 详情窗:compare 是并排中的房源(空 = 单开);detailMetric 是单开的那套;
    // detailToken 标记这次详情是谁打开的(房源编号或 'compare'),关闭时告诉收藏模块
    compare: [], detailMetric: null, detailToken: null, cmpDiff: false,
    measure: null,        // 距离测算画在地图上的那一层(图钉 + 线 + 标签)
    measureBounds: null,  // 那两个端点的包围盒 —— 详情窗关掉后要按整幅地图重新取景
    measureOff: null,     // 解绑测距那层挂在地图上的监听,擦除时要调
    focusTimer: null,     // focusOnMap 的补位定时器,取景被别人接手时要取消
  };

  /** 当前语言的文案表。切换时整个换掉,渲染函数一律读 T.xxx ——
   *  这样"哪些字要跟着语言变"这件事,在代码里是看得见的。
   *  **叫 T 不叫 L:Leaflet 的全局就是 L。** 在这个 IIFE 里再声明一个 L,
   *  会把 Leaflet 整个遮住,renderMap 里的 L.map / L.tileLayer 全部失效 ——
   *  而且报的错是「L.map is not a function」,和语言功能看不出任何关系。 */
  let T = window.I18N.zh;

  // 搜索状态始终留在 state;回看只切换展示层,不能把历史条件写回会话。
  const answerSnapshots = new WeakMap(), referenceTargets = new WeakMap();
  const resultView = () => state.historyView || state;
  const resultKey = view => JSON.stringify([view.offset, view.metrics.map(m => String(m.id))]);
  function snapshotResults() {
    const snapshot = structuredClone({ metrics: state.metrics, params: state.params,
      offset: state.offset, ranking: state.ranking, count: state.count });
    snapshot.key = resultKey(snapshot); snapshot.createdAt = new Date();
    return snapshot;
  }
  function showResultSnapshot(snapshot) {
    if (state.running) return;
    const next = snapshot && snapshot.key !== resultKey(state) ? snapshot : null;
    if (state.historyView === next) return;
    closeSheet(); state.selectedId = null; state.historyView = next;
    renderResults();
  }
  function returnToLatest() { showResultSnapshot(null); }

  const money = v => (v == null || isNaN(v)) ? '—' : '$' + Math.round(v).toLocaleString('en-AU');
  const pct = (v, digits = 1) => (v == null || isNaN(v)) ? '—' : (v * 100).toFixed(digits) + '%';
  const dist = m => (m == null || isNaN(m)) ? '—' : (Math.round(m) >= 1000 ? (m / 1000).toFixed(1) + ' km' : Math.round(m) + ' m');
  const ptZh = t => (state.meta && state.meta.property_types[t]) || t || '';
  // 数据集里 house 这一类的官方口径是 house/cottage/villa/semi/terrace ——
  // 后三种常写成「1/28 X St」这样带单元号的地址,统统叫「独立屋」会误导人:
  // 实测这批房的中位价只有典型独栋的 0.66,和联排的 0.67 是一档的。
  // 判据只看地址本身(门牌带斜杠单元号 = 不是独立地块),不是猜房型。
  const UNIT_ADDR = /^\s*[A-Za-z]?\d+[A-Za-z]?\s*\//;
  const isUnitAddr = m => UNIT_ADDR.test(m && m.address || '');
  const typeZh = m => (m.property_type === 'house' && isUnitAddr(m)) ? T.semiDetached : ptZh(m.property_type);
  const attrZh = a => (state.meta && state.meta.attributes[a]) || a;
  const kindZh = k => (state.meta && state.meta.kinds[k]) || k;
  const DIAMOND = '<svg width="8" height="8" viewBox="0 0 8 8"><path d="M4 0l4 4-4 4-4-4z" fill="currentColor"></path></svg>';
  const DOT = '<svg width="7" height="7" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3.5" fill="currentColor"></circle></svg>';
  const X = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M6 6l12 12"></path><path d="M18 6L6 18"></path></svg>';
  const PENCIL = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"></path></svg>';
  // 图标只表示类别;未来新增的偏好仍用 tag,不按每个属性维护图标。
  const CATEGORY_PATHS = {
    budget: '<rect x="3" y="5" width="18" height="15" rx="3"/><path d="M3 9h18m-6 5h3"/>',
    rooms: '<path d="M3 18V8m18 10V8M3 15h18M3 11h18v4H3zm3 0V7h5v4m2 0V7h5v4"/>',
    home: '<path d="m3 10 9-7 9 7M5 9v12h14V9m-9 12v-8h4v8"/>',
    location: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    tag: '<path d="M3 4h8l10 10-7 7L3 10Z"/><circle cx="7.5" cy="8" r="1"/>',
    person: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2Z"/>',
  };
  const categoryIcon = name => '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (CATEGORY_PATHS[name] || CATEGORY_PATHS.tag) + '</svg>';
  // 各节点的进度文案在 i18n.js 的 T.nodes 里

  // 断点直接引用 CSS 里的同两个值。写死数字的话,改了 CSS 忘了改 JS,
  // 抽屉和栏式布局会各按各的规矩来 —— 而且不报错。
  const twoColumn = () => matchMedia('(min-width: 900px)').matches;    // 对话与结果分栏,各自滚动
  const detailIsSheet = () => !matchMedia('(min-width: 1280px)').matches;  // 详情是底部抽屉,不是第三栏

  // ---------------------------------------------------------------- 会话
  function newThread() {
    state.threadId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/-/g, '');
    sessionStorage.setItem('threadId', state.threadId);
  }
  /** 布局形态。welcome:单列居中,不摆空栏;working:分栏。
   *  没有结果却摆着三个空栏,页面就有 80% 是空的 —— 那是没内容,不是留白。 */
  function setStage(s) {
    $('#app').dataset.stage = s;
    $('#brand-home').disabled = s === 'welcome';      // 首页上 logo 不可点(已经在首页了)
    $('#input').placeholder = s === 'working' ? T.workingPlaceholder : T.inputPlaceholder;
    $('#input').setAttribute('aria-label', $('#input').placeholder);
    if (s === 'welcome') renderDrift(); else stopDrift();
  }

  function resetAll() {
    clearTimeout(state.focusTimer); state.focusTimer = null;
    state.requestSerial++; // 已发出的旧会话响应不能再写进新页面。
    state.resultNotice = ''; setRunning(false);
    newThread();
    Object.assign(state, { params: null, intent: null, metrics: [], ranking: '', count: 0,
                           answer: '', selectedId: null, pool: [], offset: 0, moreBuf: null, historyView: null });
    $('#chat').innerHTML = '';        // 引导语在 #welcome 里,不再往对话里塞一条
    $('#condition-dock').replaceChildren(); condCard = null; editingConditions = false;
    $('#input').value = '';
    $('#results').innerHTML = '';
    closeSheet();
    $('#detail').innerHTML = '';
    setDetailPos(0, 0);          // 浮窗拖到哪都归位
    if (state.map) { state.map.remove(); state.map = null; }
    if (state.mapRO) { state.mapRO.disconnect(); state.mapRO = null; }
    setStage('welcome');
  }

  // ---------------------------------------------------------------- SSE
  async function streamPost(url, body, on) {
    const request = ++state.requestSerial, thread = state.threadId;
    const current = () => request === state.requestSerial && thread === state.threadId;
    let finished = false;
    const fail = payload => { if (current() && !finished) { finished = true; on.error?.(payload); } };
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok || !res.body) { fail({ message: await res.text() }); return; }
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (!current()) { await reader.cancel(); return; }
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const raw = buf.slice(0, idx); buf = buf.slice(idx + 2);
          let ev = 'message', data = '';
          for (const line of raw.split('\n')) {
            if (line.startsWith('event:')) ev = line.slice(6).trim();
            else if (line.startsWith('data:')) data += line.slice(5).trim();
          }
          let payload = {}; try { payload = JSON.parse(data || '{}'); } catch (_) { /* ignore */ }
          if (finished) continue;
          if (ev === 'error') { fail(payload); continue; }
          if (ev === 'done') finished = true;
          on[ev] && on[ev](payload);
        }
      }
      if (!finished) fail({ message: T.incompleteStream });
    } catch (error) { fail({ message: error.message || String(error) }); }
  }

  // ---------------------------------------------------------------- 对话区
  function addMessage(kind, text) {
    const row = h('article', 'msg-row msg-row-' + kind);
    const avatar = h('div', 'msg-avatar'); avatar.setAttribute('aria-hidden', 'true');
    if (kind === 'user') avatar.innerHTML = categoryIcon('person'); else avatar.textContent = 'AI';
    const main = h('div', 'msg-main'), body = h('div', 'msg-' + kind, text);
    const now = new Date(), time = h('time', 'msg-time', now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }));
    time.dateTime = now.toISOString(); main.append(body, time); row.append(avatar, main);
    $('#chat').appendChild(row); return body;
  }
  function addUser(text) { const e = addMessage('user', text); scrollChat(); return e; }
  function addStatus() { const e = h('div', 'msg-status'); e.innerHTML = '<span class="dot"></span><span class="t"></span>'; e.querySelector('.t').textContent = T.statusInit; $('#chat').appendChild(e); scrollChat(); return e; }
  function scrollChat() { const c = $('#chat'); if (twoColumn()) c.scrollTop = c.scrollHeight; else c.lastElementChild?.scrollIntoView({ block: 'nearest' }); }

  let condCard = null;
  let editingConditions = false;
  function ensureCondCard() {
    if (!condCard) condCard = h('div', 'conditions');
    $('#condition-dock').appendChild(condCard); // 条件与输入框留在栏底,消息独立滚动
    return condCard;
  }

  function runHandlers(statusEl, assistantEl) {
    let tokens = '', finalAnswer = '';
    const staged = {};
    return {
      node: ({ node }) => { const t = statusEl.querySelector('.t'); if (t) t.textContent = T.nodeStatus(T.nodes[node] || node); },
      params: ({ intent, params }) => {
        staged.intent = intent; staged.params = params;
      },
      ranking: ({ ranking, count }) => { staged.ranking = ranking || ''; staged.count = count || 0; },
      // more 比 results 先到(rank 在 present 之前),先接住,等 results 到了再拼
      more: ({ metrics }) => { staged.pool = metrics || []; },
      results: ({ metrics }) => {
        staged.metrics = metrics || [];
      },
      // 说明现在是对话流里的一条普通消息,不需要显隐/折叠那套逻辑了 ——
      // 空的就是空的,零高度,没人看得见。
      token: ({ t }) => { hideSkeleton(); tokens += t; assistantEl.classList.add('streaming'); assistantEl.textContent = tokens; scrollChat(); },
      answer: ({ answer }) => { finalAnswer = answer || tokens; },
      done: ({ params, ranking, count, intent, notice, batch_offset }) => {
        params ??= staged.params; ranking ??= staged.ranking; count ??= staged.count; intent ??= staged.intent;
        if (params) state.params = params; if (ranking != null) state.ranking = ranking; if (count != null) state.count = count; if (intent) state.intent = intent;
        if (staged.metrics) {
          state.metrics = staged.metrics; state.pool = staged.pool || staged.metrics;
          state.offset = batch_offset || 0; state.moreBuf = null; state.selectedId = null; closeSheet();
        }
        state.resultNotice = notice || '';
        hideSkeleton(); statusEl.remove(); setRunning(false); renderConditions();
        if (staged.metrics) renderResults(); else renderResultsHead();
        state.answer = finalAnswer || tokens; assistantEl.classList.remove('streaming');
        renderAnswer(assistantEl, state.answer);
        if (state.intent === 'new_search' || state.intent === 'refine') ensureCondCard();
        scrollChat();
      },
      error: ({ message }) => { hideSkeleton(); statusEl.remove(); setRunning(false); const e = h('div', 'msg-error', T.errPrefix + message); $('#chat').appendChild(e); },
    };
  }

  /** 这一轮的助手发言。**每轮新建一条,追加到左侧对话流** —— 旧的留在上面,
   *  这才是对话该有的样子。
   *
   *  以前它是结果区里的一个单例 `#answer`:近千字的说明顶在中间栏最上面,
   *  5 张房源卡被挤到屏幕外,于是又得加"收起 3 行 + 展开全文"去补救 ——
   *  那个折叠本身就是放错位置的症状。放回对话流,中间栏就只剩卡片,
   *  说明想多长有多长,跟着对话一起滚。 */
  function answerHost() {
    setStage('working');
    renderResultsHead();
    const a = addAssistantMsg();
    showSkeleton();
    scrollChat();
    return a;
  }

  /** 往对话流里加一条空的助手发言(等着流式写入)。 */
  function addAssistantMsg() {
    const a = addMessage('assistant');
    // 手机上收起来:只有一条滚动流,说明不收就把地图和卡片顶到一千多像素以下。
    // 宽屏不需要 —— 对话是独立一栏、自己滚,再长也不挡别人。
    if (!twoColumn()) {
      const more = h('button', 'msg-more', T.expand); more.type = 'button';
      const toggle = () => {
        const on = a.classList.toggle('clamped');
        more.textContent = on ? T.expand : T.collapse;
      };
      a.classList.add('clamped');
      a.addEventListener('click', e => { if (!e.target.closest('button, a')) toggle(); });
      more.addEventListener('click', toggle);
      a.after(more);
    }
    return a;
  }

  /** 把说明排成「一句话结论 + 要点」。
   *
   *  流式过程中就是纯文本(一个字一个字出来才有在写的感觉),
   *  收到完整 answer 时再排版一次 —— 结论加粗、"- "开头的行变成要点。
   *
   *  模型不按格式来也不会坏:认不出结构就整段当正文渲染,和以前一样。
   *  提示词能约束,但不能保证,所以这里必须能兜住。 */
  /** 洗掉模型偶尔冒出来的 Markdown 和"结论:"这类标签。
   *  提示词里已经禁了,但**提示词只能约束、不能保证** —— 实测换一批那条路径上
   *  它就吐过 `**结论:…**`,不洗的话星号会原样显示在界面上。 */
  function cleanLine(s) {
    return s.replace(/\*\*/g, '').replace(/^#{1,6}\s*/, '')
            .replace(/^\s*(结论|总结|建议)\s*[:：]\s*/, '')
            .trim();
  }

  function renderAnswer(el, text) {
    // 完整响应提交后才保存,此后这条回答的引用永远使用同一份结果。
    let snapshot = answerSnapshots.get(el);
    if (!snapshot) {
      snapshot = snapshotResults(); answerSnapshots.set(el, snapshot);
      if (snapshot.metrics.length) {
        const link = h('button', 'msg-results'); link.type = 'button';
        referenceTargets.set(link, { snapshot });
        link.addEventListener('click', () => {
          if (state.running) return;
          showResultSnapshot(snapshot);
          $('#results').scrollIntoView({ block: 'start' });
          const col = $('#results').closest('.col-results'); if (col) scrollTo(col, 0);
        });
        el.closest('.msg-main').appendChild(link);
      }
    }
    const lines = String(text || '').split('\n').map(s => cleanLine(s)).filter(Boolean);
    const bullets = lines.filter(l => /^[-•·]\s+/.test(l));
    // 认不出结构就整段按原样出(但星号照样要洗掉)
    if (!bullets.length) { el.textContent = ''; el.appendChild(withRefs(lines.join('\n'), snapshot)); refreshRefs(); return; }
    const lead = lines.find(l => !/^[-•·]\s+/.test(l)) || '';
    const rest = lines.filter(l => !/^[-•·]\s+/.test(l) && l !== lead);
    el.textContent = '';
    if (lead) { const d = h('div', 'msg-lead'); d.appendChild(withRefs(lead, snapshot)); el.appendChild(d); }
    const ul = h('div', 'msg-bullets');
    for (const b of bullets) {
      const d = h('div', 'msg-bullet'); d.appendChild(withRefs(b.replace(/^[-•·]\s+/, ''), snapshot)); ul.appendChild(d);
    }
    el.appendChild(ul);
    // 模型多写了的段落照样留着,不丢内容
    for (const r of rest) { const d = h('div', 'msg-extra'); d.appendChild(withRefs(r, snapshot)); el.appendChild(d); }
    refreshRefs();   // 说明是在卡片渲染完之后才到的,这里再判一次哪些引用指不到
  }

  // 「第 N 套」→ 可点的引用。用户反馈说明里说"第 3 套"却对不上是哪张卡片 ——
  // 现在卡片左上角有同一个号,地图标记也是同一个号,点一下还会滚过去闪一下。
  //
  // 模型经常把几套并起来写:「第 2、3 套同为 Tarneit」「第 1 和 4 套」。
  // 只认「第N套」的话这种整句都不可点 —— 实测第 1、5 套能跳,第 2、3 套跳不了。
  // 所以要匹配**整个"第 … 套"短语**,再把里面每个号分别做成可点的。
  // 「两」必须有 —— 中文里说"前两套""后两套"远比"前二套"自然,漏了它整句都不可点。
  const CN_NUM = { 一: 1, 两: 2, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
  const NUM_SRC = '(?:\\d{1,2}|[一两二三四五六七八九十]{1,3})';
  const SEP_LIST = '[、,，和及与]';                       // 列举:第 2、3 套
  const SEP_RANGE = '(?:[-–—~～]|至|到)';                 // 区间:第 5-8 套 / 第 5 至 8 套
  // 三种写法都要认。只认列举的话,「第 5-8 套」「前四套」整句都不可点 ——
  // 而"前三套/前四套"恰恰是模型最爱用的说法之一。
  const REF_RE = new RegExp(
    '第\\s*' + NUM_SRC + '(?:\\s*(?:' + SEP_LIST + '|' + SEP_RANGE + ')\\s*(?:第\\s*)?' + NUM_SRC + ')*\\s*套'
    + '|[前后]\\s*' + NUM_SRC + '\\s*套', 'g');
  const NUM_RE = new RegExp(NUM_SRC, 'g');
  // 英文说明里模型被要求写成 "Property 1" / "Properties 2 and 3" / "Properties 2-4"
  // (见 graph.py 的 _EXPLAIN_LANG_EN)。形式固定,才认得出来 ——
  // 认不出来的后果不是报错,是那句话变成不可点的普通文字,而没人会发现。
  const EN_N = '\\d{1,2}';
  const EN_REF_RE = new RegExp('\\bPropert(?:y|ies)\\s+' + EN_N
    + '(?:\\s*(?:,|and|&|-|–|—|to)\\s*(?:and\\s+)?' + EN_N + ')*', 'gi');
  const EN_NUM_RE = new RegExp(EN_N, 'g');
  const EN_RANGE_RE = new RegExp('^Propert(?:y|ies)\\s+(' + EN_N + ')\\s*(?:-|–|—|to)\\s*(' + EN_N + ')$', 'i');
  const REFS = {
    zh: () => ({ phrase: REF_RE, num: NUM_RE, range: RANGE_RE, headtail: HEADTAIL_RE }),
    en: () => ({ phrase: EN_REF_RE, num: EN_NUM_RE, range: EN_RANGE_RE, headtail: null }),
  };
  const refSet = () => (REFS[state.lang] || REFS.zh)();
  const RANGE_RE = new RegExp('^第\\s*(' + NUM_SRC + ')\\s*' + SEP_RANGE + '\\s*(?:第\\s*)?(' + NUM_SRC + ')\\s*套$');
  const HEADTAIL_RE = new RegExp('^([前后])\\s*(' + NUM_SRC + ')\\s*套$');
  /** 「12」「五」「十二」「二十」都要能读。翻到第二批之后编号就上两位数了,
   *  模型偶尔会写"第十二套"而不是"第12套"。 */
  function toNum(t) {
    if (/^\d+$/.test(t)) return parseInt(t, 10);
    if (CN_NUM[t]) return CN_NUM[t];
    let m = t.match(/^十([一两二三四五六七八九])$/);          // 十一 … 十九
    if (m) return 10 + CN_NUM[m[1]];
    m = t.match(/^([一两二三四五六七八九])十([一两二三四五六七八九])?$/);  // 二十、二十一 …
    if (m) return CN_NUM[m[1]] * 10 + (m[2] ? CN_NUM[m[2]] : 0);
    return undefined;
  }
  const seq = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);

  function withRefs(text, snapshot) {
    const frag = document.createDocumentFragment();
    const s = String(text || '');
    let last = 0, m;
    const RE = refSet().phrase;
    RE.lastIndex = 0;
    while ((m = RE.exec(s))) {
      if (m.index > last) frag.appendChild(document.createTextNode(s.slice(last, m.index)));
      frag.appendChild(refPhrase(m[0], snapshot));
      last = m.index + m[0].length;
    }
    if (last < s.length) frag.appendChild(document.createTextNode(s.slice(last)));
    return frag;
  }

  /** 把一处指代变成可点的东西。三种形态分开处理:
   *    列举「第 2、3 套」—— 每个号各自可点(点 2 跳 2,点 3 跳 3)
   *    区间「第 5-8 套」—— 整个短语一个按钮,点了把 5~8 全部闪一遍
   *    「前三套」「后两套」—— 同上,号从当前这一批算出来
   *  区间和"前N套"必须整块处理:它们指的是一组,拆开点没有意义。 */
  function refPhrase(phrase, snapshot) {
    // 前 N 套 / 后 N 套 —— 相对这条回答保存的批次,不会随当前页面换批而改变。
    const R = refSet();
    let m = R.headtail && phrase.match(R.headtail);
    if (m) {
      const k = toNum(m[2]);
      const lo = snapshot.offset + 1, hi = snapshot.offset + snapshot.metrics.length;
      if (k && hi >= lo) {
        const nums = m[1] === '前' ? seq(lo, Math.min(lo + k - 1, hi))
                                   : seq(Math.max(hi - k + 1, lo), hi);
        return groupRef(phrase, nums, snapshot);
      }
    }
    // 第 5-8 套 / 第 5 至 8 套
    m = phrase.match(R.range);
    if (m) {
      const a = toNum(m[1]), b = toNum(m[2]);
      if (a && b && b >= a && b - a <= 20) return groupRef(phrase, seq(a, b), snapshot);
    }
    // 列举:每个号各自可点,顿号和"第""套"保持原样
    const wrap = h('span', 'ref-group');
    let last = 0, x;
    const NRE = R.num;
    NRE.lastIndex = 0;
    while ((x = NRE.exec(phrase))) {
      const n = toNum(x[0]);
      if (x.index > last) wrap.appendChild(document.createTextNode(phrase.slice(last, x.index)));
      wrap.appendChild(n ? refBtn(x[0], [n], T.jumpTo(n), snapshot)
                         : document.createTextNode(x[0]));
      last = x.index + x[0].length;
    }
    if (last < phrase.length) wrap.appendChild(document.createTextNode(phrase.slice(last)));
    return wrap;
  }

  /** 整个短语一个按钮,指向一组房源。 */
  function groupRef(phrase, nums, snapshot) {
    const wrap = h('span', 'ref-group');
    wrap.appendChild(refBtn(phrase, nums, T.jumpRange(nums[0], nums[nums.length - 1]), snapshot));
    return wrap;
  }

  function refBtn(label, nums, title, snapshot) {
    const b = h('button', 'ref', label); b.type = 'button'; b.title = title;
    const targets = nums.map(no => ({ no, id: snapshot.metrics[no - snapshot.offset - 1]?.id }));
    referenceTargets.set(b, { snapshot, targets, title });
    b.dataset.no = nums.join(',');
    b.dataset.propertyIds = targets.map(t => t.id ?? '').join(',');
    b.addEventListener('click', e => {
      e.stopPropagation();
      if (state.running || targets.some(t => t.id == null)) return;
      showResultSnapshot(snapshot);
      // 最后再核对 ID,序号绝不能被另一套房接管。
      focusCards(targets.filter(t => document.querySelector('.card[data-no="' + t.no + '"]')?.dataset.id === String(t.id)).map(t => t.no));
    });
    return b;
  }

  const cardExists = n => !!document.querySelector('.card[data-no="' + n + '"]');

  /** 把容器滚到指定位置。
   *
   *  两条都不能单独指望:
   *    · `scrollIntoView({behavior:'smooth'})` —— 浏览器可以合法地忽略平滑滚动
   *      (系统开了"减少动态效果"时就会),被忽略时**一点都不滚**。
   *    · `requestAnimationFrame` —— 标签页被节流/不在出帧时压根不触发。
   *  实测两种情况都遇到过:点了引用,卡片闪了但页面纹丝不动。
   *
   *  所以:动画走 rAF,**同时挂一个定时器兜底**。动画能播就播,播不了也一定滚到位。
   *  「滚没滚到」和「滚得好不好看」是两件事,前者不能赌。 */
  function scrollTo(el, top, ms = 320) {
    const from = el.scrollTop;
    const max = el.scrollHeight - el.clientHeight;
    const to = Math.min(Math.max(top, 0), Math.max(max, 0));
    if (Math.abs(to - from) < 2) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { el.scrollTop = to; return; }

    let done = false;
    const t0 = performance.now();
    const ease = p => 1 - Math.pow(1 - p, 3);    // ease-out,和 CSS 里那条同一个手感
    const step = now => {
      if (done) return;
      const p = Math.min((now - t0) / ms, 1);
      el.scrollTop = from + (to - from) * ease(p);
      if (p < 1) requestAnimationFrame(step); else done = true;
    };
    requestAnimationFrame(step);
    // 定时器即使在 rAF 被节流时也会走。到点还没到位就直接落位。
    setTimeout(() => { if (!done) { done = true; el.scrollTop = to; } }, ms + 60);
  }

  /** 一次点亮一组(区间和「前三套」会指向多套)。滚到第一张,全部闪一遍。 */
  function focusCards(nums) {
    const found = nums.filter(cardExists);
    if (!found.length) return;
    focusCard(found[0]);
    for (const n of found.slice(1)) {
      const c = document.querySelector('.card[data-no="' + n + '"]');
      c.classList.remove('flash'); void c.offsetWidth; c.classList.add('flash');
    }
  }

  function focusCard(no) {
    const card = document.querySelector('.card[data-no="' + no + '"]');
    if (!card) return;
    const col = card.closest('.col-results');
    if (col && col.scrollHeight > col.clientHeight + 1) {
      // 用 rect 算,别用 offsetTop —— offsetTop 是相对 offsetParent 的,而这里的
      // offsetParent 是 BODY(.col-results 没有 position),算出来会差好几百像素。
      const cr = card.getBoundingClientRect(), colr = col.getBoundingClientRect();
      // 把卡片摆到容器中间,而不是贴着顶 —— 上下都露出一点,看得出它在列表里的位置
      scrollTo(col, col.scrollTop + (cr.top - colr.top) - (col.clientHeight - cr.height) / 2);
    } else {
      card.scrollIntoView({ block: 'center' });   // 窄屏:整页滚,没有独立滚动容器
    }
    // 先摘掉再强制回流再加上 —— 不然连点同一个引用时动画不会重播
    card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash');
  }

  /** 等待期间占位。空白盒子和骨架屏的区别在于:前者看着像坏了,后者看着像在加载。 */
  function showSkeleton() {
    if ($('#skeleton')) return;
    const s = h('div', 'skeleton'); s.id = 'skeleton';
    for (let i = 0; i < 3; i++) s.appendChild(h('i'));
    $('#results').appendChild(s);      // 骨架屏占的是卡片的位置,不是说明的
  }
  function hideSkeleton() { const s = $('#skeleton'); if (s) s.remove(); }

  async function send(text) {
    if (state.running) return;
    returnToLatest();
    setRunning(true);   // 先上锁再等 meta,否则等待期间连点会发两次
    state.resultNotice = '';
    await metaReady;
    addUser(text);
    const status = addStatus();
    const answerEl = answerHost();   // 已在内部清空并同步显隐
    await streamPost('/api/chat', { thread_id: state.threadId, message: text, lang: state.lang }, runHandlers(status, answerEl));
  }

  async function refine(params, statusText) {
    if (state.running) return;
    returnToLatest();
    const thread = state.threadId;
    setRunning(true);
    await metaReady;
    if (thread !== state.threadId) return;
    const active = new Set((params.abstract_needs || []).map(n => n.attribute));
    const removed = (state.params?.abstract_needs || []).map(n => n.attribute).filter(a => !active.has(a));
    params = JSON.parse(JSON.stringify(params));
    if (removed.includes(params.sort_by)) params.sort_by = null;
    const previousIds = state.metrics.map(m => m.id);
    state.resultNotice = statusText || T.statusRefine;
    renderResultsHead();
    const status = addStatus();
    status.querySelector('.t').textContent = statusText || T.statusRefine;
    const answerEl = answerHost();
    $('#results').setAttribute('aria-busy', 'true');
    const staged = { metrics: [], pool: [], tokens: '', answer: '', ranking: '' };
    // 成功后一次换上,避免新条件套在旧房卡上,或新说明指向旧编号。
    await streamPost('/api/refine', { thread_id: state.threadId, params, removed_attributes: removed, lang: state.lang }, {
      node: ({ node }) => { status.querySelector('.t').textContent = T.nodeStatus(T.nodes[node] || node); },
      ranking: ({ ranking }) => { staged.ranking = ranking || ''; },
      more: ({ metrics }) => { staged.pool = metrics || []; },
      results: ({ metrics }) => { staged.metrics = metrics || []; },
      token: ({ t }) => { staged.tokens += t; },
      answer: ({ answer }) => { staged.answer = answer || ''; },
      done: data => {
        const same = previousIds.length === staged.metrics.length && previousIds.every((id, i) => id === staged.metrics[i].id);
        Object.assign(state, { params: data.params || params, intent: data.intent || 'refine',
          ranking: data.ranking ?? staged.ranking, count: data.count ?? staged.metrics.length,
          metrics: staged.metrics, pool: staged.pool.length ? staged.pool : staged.metrics,
          moreBuf: null, offset: data.batch_offset || 0, selectedId: null, answer: staged.answer || staged.tokens,
          resultNotice: data.notice || (same ? T.resultsUnchanged : T.resultsUpdated) });
        hideSkeleton(); status.remove(); setRunning(false); closeSheet();
        $('#results').removeAttribute('aria-busy');
        renderConditions(); renderResults(); renderAnswer(answerEl, state.answer); scrollChat();
      },
      error: ({ message, rollback_failed }) => {
        hideSkeleton(); status.remove(); answerEl.closest('.msg-row').remove(); setRunning(false);
        $('#results').removeAttribute('aria-busy');
        state.resultNotice = rollback_failed ? T.refineRecoveryFailed : T.refineFailed;
        renderConditions(); renderResultsHead();
        const e = h('div', 'msg-error'); e.appendChild(h('span', null, state.resultNotice));
        const retry = h('button', 'btn small', T.retry); retry.type = 'button';
        retry.addEventListener('click', () => { if (state.running) return; e.remove(); refine(params, statusText); });
        e.appendChild(retry); e.title = message || ''; $('#chat').appendChild(e); scrollChat();
      },
    });
  }

  function setRunning(v) {
    state.running = v; $('#composer .send').disabled = v;
    document.querySelectorAll('#condition-dock .chip button').forEach(el => { el.disabled = v; });
    const sort = $('#result-sort'); if (sort) sort.disabled = v || !!state.historyView;
    document.querySelectorAll('.more-batch button').forEach(el => { el.disabled = v; });
    refreshRefs();
  }

  // ---------------------------------------------------------------- 条件卡
  function chip(label, opts = {}) {
    const c = h('div', 'chip' + (opts.cls ? ' ' + opts.cls : ''));
    const main = h(opts.onClick ? 'button' : 'span', 'chip-main');
    const icon = h('span', 'chip-icon'); icon.innerHTML = categoryIcon(opts.icon);
    main.append(icon, h('span', 'chip-text', label)); main.title = label;
    if (opts.onClick) { main.type = 'button'; main.disabled = state.running; main.addEventListener('click', opts.onClick); }
    c.appendChild(main);
    if (opts.onRemove) {
      const x = h('button', 'chip-remove'); x.type = 'button'; x.innerHTML = X;
      x.setAttribute('aria-label', T.remove + ' ' + label); x.title = T.remove; x.disabled = state.running;
      x.addEventListener('click', opts.onRemove); c.appendChild(x);
    }
    return c;
  }

  function renderConditions() {
    const p = state.params; if (!p) return;
    const card = ensureCondCard(); card.innerHTML = '';
    const meta = state.meta;
    const apply = (mut, statusText) => { if (state.running) return; const next = JSON.parse(JSON.stringify(state.params)); mut(next); refine(next, statusText); };

    card.classList.toggle('is-editing', editingConditions);
    const head = h('div', 'cond-head'); head.appendChild(h('strong', null, T.condHead));
    const edit = h('button', 'cond-edit', editingConditions ? T.closeConditions : T.editConditions); edit.type = 'button';
    edit.setAttribute('aria-expanded', String(editingConditions)); edit.setAttribute('aria-controls', 'condition-options');
    edit.addEventListener('click', () => { editingConditions = !editingConditions; renderConditions(); card.querySelector('.cond-edit').focus({ preventScroll: true }); });
    head.appendChild(edit); card.appendChild(head);
    const legend = h('div', 'cond-legend');
    legend.append(h('span', 'legend-required', T.requiredShort), h('span', 'legend-preferred', T.preferredShort));
    card.appendChild(legend);
    const options = h('div', 'condition-options'); options.id = 'condition-options'; card.appendChild(options);

    // ---- 必须(硬条件,进 SQL)----
    const g1 = h('div', 'cond-group cond-required'); g1.title = T.mustLabel;
    g1.appendChild(h('div', 'cond-label', T.requiredShort));
    const c1 = h('div', 'chips');
    const numChip = (key, label, fmt, unitHint) => {
      const v = p[key];
      const icon = key.includes('price') ? 'budget' : 'rooms';
      if (v == null) c1.appendChild(chip(T.unset(label), { icon, cls: 'unset', onClick: () => editNumber(label, v, unitHint, val => apply(n => { n[key] = val; })) }));
      else c1.appendChild(chip(fmt(v), { icon, cls: 'hard', onClick: () => editNumber(label, v, unitHint, val => apply(n => { n[key] = val; })), onRemove: () => apply(n => { n[key] = null; }) }));
    };
    numChip('max_price', T.budgetMax, v => '≤ ' + money(v), T.aud);
    if (p.min_price != null) numChip('min_price', T.budgetMin, v => '≥ ' + money(v), T.aud);
    numChip('bedrooms', T.bedroomsLabel, v => T.beds(v), T.roomsUnit);
    if (p.bathrooms != null) numChip('bathrooms', T.bathroomsLabel, v => T.baths(v), T.roomsUnit);
    if (p.property_type) c1.appendChild(chip(ptZh(p.property_type), { icon: 'home', cls: 'hard', onClick: () => editSelect(T.typeLabel, p.property_type, meta.property_types, val => apply(n => { n.property_type = val; })), onRemove: () => apply(n => { n.property_type = null; }) }));
    else c1.appendChild(chip(T.typeAny, { icon: 'home', cls: 'unset', onClick: () => editSelect(T.typeLabel, '', meta.property_types, val => apply(n => { n.property_type = val || null; })) }));
    if (p.suburb) c1.appendChild(chip(p.suburb, { icon: 'location', cls: 'hard', onClick: () => editText(T.suburbLabel, p.suburb, val => apply(n => { n.suburb = val || null; })), onRemove: () => apply(n => { n.suburb = null; }) }));
    else c1.appendChild(chip(T.suburbAny, { icon: 'location', cls: 'unset', onClick: () => editText(T.suburbLabel, '', val => apply(n => { n.suburb = val || null; })) }));
    g1.classList.toggle('no-active', !c1.querySelector('.hard'));
    g1.appendChild(c1); options.appendChild(g1);

    // ---- 偏好条件:无交集时说明取舍,不自动删除----
    const g2 = h('div', 'cond-group cond-preferred'); g2.title = T.wishLabel;
    g2.appendChild(h('div', 'cond-label', T.preferredShort));
    const c2 = h('div', 'chips'); let soft = 0;
    (p.abstract_needs || []).forEach((need, i) => {
      const required = need.strength === 'required'; if (!required) soft++;
      const score = chip(T.scoreChip(attrZh(need.attribute), need.min_score, scoreSymbol(need.operator)), {
        cls: required ? 'hard' : '',
        onClick: () => editScore(need, (op, score) => apply(n => {
          Object.assign(n.abstract_needs[i], { operator: op, min_score: score, value_source: 'explicit' });
          n.relative_preferences = (n.relative_preferences || []).filter(g => g.field !== need.attribute);
        })),
        onRemove: () => apply(n => { n.abstract_needs.splice(i, 1); }, T.removingPreference(attrZh(need.attribute))) });
      score.title = need.value_source === 'inferred' ? T.inferredScore : T.relativeScoreOrigin;
      (required ? c1 : c2).appendChild(score);
    });
    g1.classList.toggle('no-active', !c1.querySelector('.hard'));
    (p.amenity_needs || []).forEach((need, i) => { soft++; c2.appendChild(chip(T.distChip(kindZh(need.kind), dist(need.max_distance_m)), { icon: 'location',
      onClick: () => editNumber(T.distTitle(kindZh(need.kind)), need.max_distance_m, T.metres, val => apply(n => { n.amenity_needs[i].max_distance_m = val; })),
      onRemove: () => apply(n => { n.amenity_needs.splice(i, 1); }) })); });
    if (p.near_place) { soft++; const np = p.near_place; c2.appendChild(chip(T.nearPlaceChip(np.name, np.max_distance_m ? dist(np.max_distance_m) : ''), { icon: 'location',
      onClick: () => editNumber(T.nearPlaceTitle(np.name), np.max_distance_m, T.metres, val => apply(n => { n.near_place.max_distance_m = val || null; })),
      onRemove: () => apply(n => { n.near_place = null; if (n.sort_by === 'near_place_distance') n.sort_by = null; }) })); }
    if (p.school_zone) { soft++; c2.appendChild(chip(T.schoolZoneChip(p.school_zone.school), { icon: 'location', onRemove: () => apply(n => { n.school_zone = null; }) })); }
    (p.planning_needs || []).forEach((need, i) => { soft++; c2.appendChild(chip(meta.planning_needs[need] || need, { onRemove: () => apply(n => { n.planning_needs.splice(i, 1); }) })); });
    if (p.min_gross_yield != null) { soft++; c2.appendChild(chip(T.yieldChip(pct(p.min_gross_yield)), { icon: 'budget',
      onClick: () => editNumber(T.yieldTitle, p.min_gross_yield * 100, '%', val => apply(n => { n.min_gross_yield = val / 100; })),
      onRemove: () => apply(n => { n.min_gross_yield = null; }) })); }
    if (!soft) c2.appendChild(h('div', 'cond-unsupported', T.noSoft));
    g2.classList.toggle('no-active', !soft);
    g2.appendChild(c2); options.appendChild(g2);
    if (p.relative_preferences?.length) {
      const adjustments = h('div', 'cond-adjustments'); adjustments.appendChild(h('span', 'cond-adjustments-label', T.adjustmentLabel));
      const items = h('div', 'chips');
      p.relative_preferences.forEach((goal, i) => {
        const label = meta.attributes[goal.field] || (goal.field === 'price' ? T.relativePrice : meta.sort_labels[goal.field]) || goal.field;
        const item = chip(T.relativeGoal(label, goal.direction, goal.degree), { cls: 'relative-goal',
          onRemove: () => apply(n => { n.relative_preferences.splice(i, 1); }) });
        item.title = T.relativeGoalHint; items.appendChild(item);
      });
      adjustments.appendChild(items); options.appendChild(adjustments);
    }
    if (!c1.querySelector('.hard') && !soft) options.appendChild(h('div', 'cond-hint', T.noFilters));

    const add = h('button', 'cond-add'); add.type = 'button';
    const plus = h('span', null, '+'); plus.setAttribute('aria-hidden', 'true'); add.append(plus, document.createTextNode(T.addCondition));
    add.addEventListener('click', () => { $('#input').focus(); }); card.appendChild(add);

    if (p.unsupported_asks && p.unsupported_asks.length) card.appendChild(h('div', 'cond-unsupported', T.unsupportedNote(p.unsupported_asks.map(a => (meta.unsupported_key || {})[a] || a))));

    if (state.count || state.metrics.length) {
      const st = h('div', 'cond-status');
      st.appendChild(h('span', null, state.metrics.length ? T.foundN(state.metrics.length) : T.foundNone));
      if (state.metrics.length) { const b = h('button', 'btn small', T.seeResults); b.type = 'button'; b.addEventListener('click', () => { returnToLatest(); $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' }); }); st.appendChild(b); }
      card.appendChild(st);
    }
  }

  // ---- 小编辑框 ----
  function openPopover(title, fields, onApply, hint, cssClass = '') {
    const pop = $('#popover'); pop.innerHTML = ''; pop.appendChild(h('h4', null, title));
    pop.classList.toggle('score-editor', cssClass === 'score-editor');
    pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-modal', 'true'); pop.setAttribute('aria-label', title);
    const inputs = [];
    for (const f of fields) {
      const lab = h('label'); lab.appendChild(h('span', null, f.label));
      let inp;
      if (f.type === 'select') { inp = h('select'); for (const [k, v] of Object.entries(f.options)) { const o = h('option', null, v); o.value = k; if (k === f.value) o.selected = true; inp.appendChild(o); } if (f.allowEmpty) { const o = h('option', null, T.any); o.value = ''; if (!f.value) o.selected = true; inp.prepend(o); } }
      else { inp = h('input'); inp.type = f.type || 'text'; if (f.value != null) inp.value = f.value; if (f.type === 'number') { inp.inputMode = 'decimal'; inp.step = 'any'; } }
      for (const key of ['min', 'max', 'step', 'required']) if (f[key] != null) inp[key] = f[key];
      lab.appendChild(inp); pop.appendChild(lab); inputs.push(inp);
    }
    if (hint) pop.appendChild(h('div', 'hint', hint));
    const act = h('div', 'actions'); const left = h('div'); const right = h('div', 'right');
    const cancel = h('button', 'btn ghost small', T.cancel); cancel.type = 'button'; cancel.addEventListener('click', closePopover);
    const ok = h('button', 'btn small', T.apply); ok.type = 'button'; ok.addEventListener('click', () => {
      const invalid = inputs.find(i => !i.checkValidity());
      if (invalid) { invalid.reportValidity(); return; }
      closePopover(); onApply(inputs.map(i => i.value));
    });
    right.appendChild(cancel); right.appendChild(ok); act.appendChild(left); act.appendChild(right); pop.appendChild(act);
    pop.classList.add('is-open'); $('#backdrop').classList.add('is-open');
    $('#backdrop').onclick = closePopover;
    inputs[0] && inputs[0].focus();
    pop.onkeydown = ev => { if (ev.key === 'Enter') { ev.preventDefault(); ok.click(); } if (ev.key === 'Escape') closePopover(); };
  }
  function closePopover() { $('#popover').classList.remove('is-open'); if (!$('#detail').classList.contains('open')) $('#backdrop').classList.remove('is-open'); }
  function editNumber(title, value, unit, cb) { openPopover(title, [{ label: unit, type: 'number', value }], ([v]) => { const n = parseFloat(v); if (!isNaN(n) && n > 0) cb(n); else if (v === '') cb(null); }); }
  const scoreSymbol = op => ({ gte: '≥', gt: '>', lte: '≤', lt: '<', eq: '=' }[op] || '≥');
  function editScore(need, cb) {
    openPopover(T.scoreTitle(attrZh(need.attribute)), [
      { label: T.scoreComparison, type: 'select', value: need.operator || 'gte', options: T.scoreOperators },
      { label: T.scoreValue, type: 'number', value: need.min_score, min: 0, max: 100, step: 1, required: true },
    ], ([op, value]) => cb(op, Number(value)), T.scoreHint, 'score-editor');
  }
  function editText(title, value, cb) { openPopover(title, [{ label: '', type: 'text', value }], ([v]) => cb(v.trim())); }
  function editSelect(title, value, options, cb) { openPopover(title, [{ label: '', type: 'select', value, options, allowEmpty: true }], ([v]) => cb(v)); }

  // ---------------------------------------------------------------- 结果区
  function renderResultsHead() {
    const r = $('#results');
    const view = resultView();
    $('#results-history')?.remove();
    if (state.historyView) {
      const banner = h('div', 'results-history'); banner.id = 'results-history'; banner.setAttribute('role', 'status');
      const text = h('div');
      const time = view.createdAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
      text.append(h('strong', null, T.historyTitle(time)), h('div', 'history-note', T.historyNote));
      const back = h('button', 'btn small', T.returnLatest); back.type = 'button';
      back.addEventListener('click', returnToLatest); banner.append(text, back); r.prepend(banner);
    }
    let head = $('#res-head'); if (!head) { head = h('div', 'res-head'); head.id = 'res-head'; r.prepend(head); }
    head.innerHTML = '';
    // 翻过页就要说清楚现在看的是第几到第几套,否则用户不知道自己在哪一批
    const range = view.offset > 0
      ? T.range(view.offset + 1, view.offset + view.metrics.length)
      : T.count(view.metrics.length);
    const left = h('div'); left.appendChild(h('div', 'res-title', view.metrics.length ? range : (view.count === 0 && view.ranking ? T.noResultsTitle : T.resultsTitle)));
    head.appendChild(left);
    if (view.params && state.meta) {
      const label = h('label', 'result-sort'); label.appendChild(h('span', null, T.sortGroup));
      const select = h('select'); select.id = 'result-sort'; select.disabled = state.running || !!state.historyView;
      if (state.historyView) select.title = T.historySort;
      for (const [key, text] of [['', view.params.relative_preferences?.length ? T.relativeSort : T.sortDefault], ...Object.entries(state.meta.sort_labels)]) {
        const option = h('option', null, text); option.value = key; option.selected = (view.params.sort_by || '') === key; select.appendChild(option);
      }
      select.addEventListener('change', () => {
        const value = select.value; select.value = state.params.sort_by || '';
        refine({ ...state.params, sort_by: value || null, relative_preferences: null }, T.statusSort);
      });
      label.appendChild(select); head.appendChild(label);
    }
    let notice = $('#results-notice');
    if (!notice) { notice = h('div', 'results-notice'); notice.id = 'results-notice'; notice.setAttribute('role', 'status'); head.after(notice); }
    notice.textContent = state.historyView ? '' : state.resultNotice; notice.hidden = !notice.textContent;
    // 「列表/地图」切换已经去掉 —— 地图现在是常驻的一栏,不需要切换才能看见
    let notes = $('#res-notes'); if (!notes) { notes = h('div', 'res-notes'); notes.id = 'res-notes'; head.after(notes); }
    notes.innerHTML = '';
    for (const n of (view.ranking || '').split(';').map(s => s.trim()).filter(Boolean)) notes.appendChild(h('div', null, n));
  }

  function headline(m) {
    const p = resultView().params || {};
    const s = p.relative_preferences?.[0]?.field || p.sort_by; const meta = state.meta;
    if (s && meta.attributes[s] && m.context_scores && m.context_scores[s] != null) {
      return { v: m.context_scores[s], l: T.attrDegree(attrZh(s)), cls: '', sub: evidenceLine(m, s, 2) };
    }
    if (s === 'near_place_distance' && m.near_place) return { v: dist(m.near_place.distance_m), l: T.toPlace(m.near_place.name), cls: '', sub: '' };
    if (s === 'cap_rate') return { v: '~' + pct(m.cap_rate), l: 'Cap Rate', cls: 'assume', sub: T.byOpexAssumption };
    if (s === 'roi') return { v: '~' + pct(m.roi), l: 'ROI', cls: 'assume', sub: T.byOpexAssumption };
    if (s === 'predicted_gap') return { v: (m.predicted_gap > 0 ? '+' : '') + pct(m.predicted_gap), l: T.valGap, cls: 'model', sub: T.modelValueSub(money(m.predicted_price)) };
    return { v: pct(m.gross_yield), l: T.grossYieldShort, cls: '', sub: T.annualRentSub(money(m.annual_rent)) };
  }

  /** 用户点名要的、但不是排序依据的那些属性 —— 返回 [中文名, 分数, 属性键]。
   *  排序那个属性不在里面:它是右上角的大数字,不重复。 */
  function otherScores(m) {
    const p = resultView().params || {}, s = p.relative_preferences?.[0]?.field || p.sort_by, out = [];
    const attrs = new Set([...(p.abstract_needs || []).map(n => n.attribute), ...(p.relative_preferences || []).map(g => g.field)]);
    for (const a of attrs) {
      if (a === s) continue;
      const sc = m.context_scores && m.context_scores[a];
      if (sc == null) continue;
      out.push([attrZh(a), sc, a]);
    }
    return out.slice(0, 3);      // 再多就该改条件了,卡片不是仪表盘
  }

  function evidenceLine(m, attr, limit) {
    const parts = (state.meta.attribute_parts[attr] || []); const ev = m.context_evidence || {}; const out = [];
    for (const k of parts) { if (ev[k] == null) continue; const [label, unit] = state.meta.evidence_labels[k] || [k, '']; out.push(label + ' ' + fmtEvidence(ev[k], unit)); if (out.length >= limit) break; }
    return out.join(' · ');
  }
  function fmtEvidence(v, unit) { if (unit === '米' || unit === 'm') return dist(v); if (typeof v === 'number') return (Number.isInteger(v) ? v : v.toFixed(1)) + (unit ? ' ' + unit : ''); return String(v); }

  /** 详情页里的证据行,**把拖低分数的那一项标出来**。
   *
   *  起因:一套"安静 65"的房子离次干道只有 43 米。证据行确实写了 43 米,
   *  但它埋在五个数字中间,读者不知道 43 算近还是远 —— 于是上面那句
   *  "分数高 = 远离主干道与次干道"读起来就像在说这套房远离道路。
   *
   *  分项强度(context_parts)是各项**各自**的 0~100,方向已归一化(越大越有利)。
   *  低于 25 的标成橙色并注明它在全库的位置,"为什么是这个分"才追溯得到。 */
  const WEAK = 25;
  function evidenceNodes(m, attr, limit) {
    const frag = document.createDocumentFragment();
    const parts = (state.meta.attribute_parts[attr] || []);
    const ev = m.context_evidence || {};
    const strength = ((m.context_parts || {})[attr]) || {};
    let n = 0;
    for (const k of parts) {
      if (ev[k] == null) continue;
      if (n >= limit) break;
      const [label, unit] = state.meta.evidence_labels[k] || [k, ''];
      if (n) frag.appendChild(document.createTextNode(' · '));
      const s = strength[k];
      const txt = label + ' ' + fmtEvidence(ev[k], unit);
      if (s != null && s <= WEAK) {
        const span = h('span', 'ev-weak', txt + T.weakNote(s));
        frag.appendChild(span);
      } else {
        frag.appendChild(document.createTextNode(txt));
      }
      n++;
    }
    return frag;
  }

  /** 证据标签的紧凑写法。"距最近购物中心" → "购物中心";"800 米内商店餐饮" → "商店餐饮"。
   *  半径和完整措辞在详情页里有,标签行要的是一眼能读完。 */
  // 英文侧同理:证据标签在卡片上只要中心词,「Nearest train station」
  // 和「Late-night venues within 300 m」都得剃掉修饰,否则一行放不下。
  const shortLabel = l => l.replace(/^距最近/, '')
    .replace(/^\d+\s*米内/, '')
    .replace(/^Nearest\s+/i, '')
    .replace(/\s+within\s+\d+\s*m$/i, '');

  /** 某个属性的首要证据,已格式化。拿不到就空字符串。 */
  function topEvidence(m, attr) {
    const parts = (state.meta.attribute_parts[attr] || []); const ev = m.context_evidence || {};
    for (const k of parts) {
      if (ev[k] == null) continue;
      const [label, unit] = state.meta.evidence_labels[k] || [k, ''];
      return shortLabel(label) + ' ' + fmtEvidence(ev[k], unit);
    }
    return '';
  }

  /** 卡片标签。返回 { asked, risk } 两组,分两行渲染。
   *
   *  改这个函数的起因:原来是一串**固定优先级**(毛回报 → 设施 → 估值差 → 叠加层 → 学区),
   *  跟用户问了什么完全无关。搜"方便购物、热闹",标签给的是毛回报和土壤污染 ——
   *  用户会莫名其妙,因为那不是他问的。
   *
   *  现在:asked 按**用户点名的顺序**来,没点名任何具体需求时才退回通用投资信号。
   *  risk 单独一行、永远显示 —— 买家没问不等于不该知道,如实披露是这个系统的立论,
   *  不能因为"他没问"就藏起来。降级不删除。 */
  function badges(m) {
    const p = resultView().params || {}; const s = p.sort_by;
    const asked = [], risk = [], extra = [];

    // 1. 抽象需求(热闹/购物方便/安静……),按用户说的顺序。
    //    排序用的那个属性跳过 —— 它已经是右上角的大字了,重复一遍是浪费。
    // 分数已经在右上角的分数栈里了,这里只放**证据** —— 同一个数字不说两遍。
    for (const [, , attr] of otherScores(m).map(x => [x[0], x[1], x[2]])) {
      const ev = topEvidence(m, attr);
      if (ev) asked.push([attrZh(attr) + ' · ' + ev, 'ask']);   // 属性名来自 meta,已随语言切换
    }
    // 2. 设施距离、具名地点、学区 —— 都是用户明确提过的
    for (const need of (p.amenity_needs || [])) {
      const a = m.amenities && m.amenities[need.kind];
      if (a && a.distance_m != null) asked.push([kindZh(need.kind) + ' ' + dist(a.distance_m), 'ask']);
    }
    if (m.near_place && s !== 'near_place_distance') asked.push([T.nearPlaceBadge(m.near_place.name, dist(m.near_place.distance_m)), 'ask']);
    if (p.school_zone && m.school_zones && m.school_zones.primary) asked.push([T.primaryZoneBadge(m.school_zones.primary.replace(/ Primary School$/, '')), 'ask']);
    if (p.min_gross_yield != null) asked.push([T.yieldBadge(pct(m.gross_yield)), 'ask']);

    // 3. 通用投资信号。只在还有位置时补,不跟用户点名要的抢。
    if (s !== 'gross_yield' && p.min_gross_yield == null) extra.push([T.yieldBadge(pct(m.gross_yield)), '']);
    // 门槛用**这类房型自己的**典型误差,不是写死的 10%。
    // 写死 10% 时,一套公寓差 11.6% 会挂上"估值低于售价 11.6%"的标,
    // 而详情窗按公寓的真实误差 ±12.0% 判定"价格正常" —— 同一套房,
    // 卡片和详情窗说反话。两处必须用同一条线。
    const vgap = m.predicted_gap, verr = m.valuation_error_pct;
    if (vgap != null && verr != null && Math.abs(vgap) > verr) {
      extra.push([(vgap > 0 ? T.gapAbove : T.gapBelow)(pct(Math.abs(vgap))), 'accent']);
    }
    if (!asked.length && m.school_zones && m.school_zones.primary) extra.push([T.primaryZoneBadge(m.school_zones.primary.replace(/ Primary School$/, '')), '']);

    // 4. 风险披露。独立一行,不参与上面的名额竞争。
    const pl = m.planning || {};
    for (const o of (pl.overlays || [])) { if (o.effect === 'risk') risk.push([o.label, 'warn']); }
    if ((pl.overlays || []).some(o => o.family === 'HO')) risk.push([T.heritageOverlay, 'warn']);
    if (pl.nearby_total && !pl.nearby_high && pl.nearby_low) risk.push([T.lowDensityAround, 'warn']);

    const head = asked.slice(0, 4);
    return { asked: head.concat(extra.slice(0, Math.max(0, 4 - head.length))), risk: risk.slice(0, 3) };
  }

  function renderResults() {
    const r = $('#results');
    const view = resultView();
    renderResultsHead();
    const keep = new Set(['res-head', 'res-notes', 'results-notice', 'results-history']);
    for (const el of [...r.children]) if (!keep.has(el.id)) el.remove();
    renderMap();
    if (!view.metrics.length) { if (view.count === 0 && view.ranking) r.appendChild(h('div', 'empty', T.emptyMsg)); refreshRefs(); return; }
    // 错峰 45ms 依次浮起。封顶 8 个,否则长列表的尾巴要等将近一秒才出齐 ——
    // 错峰是装饰,不能让它拖慢"结果已经到了"这件事本身。
    let idx = 0;
    for (const m of view.metrics) {
      // 号在翻页时**继续往下数**(第二批是 6–10),不从 1 重来 ——
      // 从 1 重来的话,对话里旧的「第 3 套」会指到一套完全不同的房子,
      // 那比指不到还糟。指不到是明摆着的,指错是悄悄的。
      const no = view.offset + idx + 1;
      const c = h('div', 'card' + (m.id === state.selectedId ? ' selected' : '')); c.dataset.id = m.id;
      c.classList.toggle('has-relative', !!view.params?.relative_preferences?.length);
      c.dataset.no = no;
      c.style.setProperty('--d', Math.min(idx++, 8) * 45 + 'ms');
      const top = h('div', 'card-top'); const id = h('div', 'card-id');
      const addr = h('div', 'card-addr');
      addr.appendChild(h('span', 'card-no', String(no)));
      addr.appendChild(document.createTextNode((m.suburb || '') + ' · ' + (m.address || '')));
      id.appendChild(addr);
      id.appendChild(h('div', 'card-price', money(m.price)));
      id.appendChild(h('div', 'card-meta', [T.beds(m.bedrooms), T.baths(m.bathrooms), typeZh(m)].filter(Boolean).join(' · ')));
      // 指标区:每个指标一列,**统一"标签在上、数值在下"**,横着排。
      // 之前是竖着叠:主指标数值在上标签在下、次指标标签在前数值在后 ——
      // 两种阅读顺序混在一列 62px 宽的地方,还被挤到换行,当然分不清哪个数配哪个名。
      // 排序用的那个放最右边、字最大,一列卡片扫下来它始终在同一条竖线上。
      const hl = headline(m);
      const met = h('div', 'metrics');
      for (const [name, sc] of otherScores(m)) {
        const col = h('div', 'metric');
        col.appendChild(h('div', 'ml', name));
        col.appendChild(h('div', 'mv', String(sc)));
        met.appendChild(col);
      }
      const pm = h('div', 'metric primary');
      pm.appendChild(h('div', 'ml', hl.l));
      const pv = h('div', 'mv ' + hl.cls); pv.textContent = hl.v; pm.appendChild(pv);
      met.appendChild(pm);
      const hd = met;
      top.appendChild(id); top.appendChild(hd); c.appendChild(top);
      if (hl.sub) c.appendChild(h('div', 'card-sub', hl.sub));
      const bg = badges(m);
      if (bg.asked.length) { const bs = h('div', 'badges'); for (const [t, cls] of bg.asked) bs.appendChild(h('span', 'badge ' + cls, t)); c.appendChild(bs); }
      // 风险单独一行,前面加"提醒",让它读起来是披露而不是卖点
      if (bg.risk.length) {
        const rs = h('div', 'badges risks'); rs.appendChild(h('span', 'risk-lead', T.riskLead));
        for (const [t] of bg.risk) rs.appendChild(h('span', 'badge warn', t));
        c.appendChild(rs);
      }
      c.addEventListener('click', () => openDetail(m));
      if (window.nwFav) c.appendChild(window.nwFav.button(m));   // 右下角收藏(favorites.js)
      r.appendChild(c);
    }
    renderMoreBtn(r);
    refreshRefs();
  }

  /** 「换一批」。翻的是**已经算好**的第 6 名往后,不查库、不重算指标;后续调用 LLM 重写说明。
   *  翻完了就说翻完了,并且提示改条件比继续翻更有用。 */
  function renderMoreBtn(r) {
    if (state.historyView) return;
    const left = state.pool.length - (state.offset + state.metrics.length);
    if (state.pool.length <= state.metrics.length) return;    // 本来就只有这几套
    const box = h('div', 'more-batch');
    if (left > 0) {
      const b = h('button', 'btn ghost small', T.nextBatch(left)); b.type = 'button';
      b.disabled = state.running;
      b.addEventListener('click', nextBatch);
      box.appendChild(b);
    } else {
      const b = h('button', 'btn ghost small', T.backToFirst); b.type = 'button';
      b.disabled = state.running;
      b.addEventListener('click', () => { if (state.running) return; state.offset = -state.metrics.length; nextBatch(); });
      box.appendChild(b);
      box.appendChild(h('div', 'more-note', T.batchDone));
    }
    r.appendChild(box);
  }

  async function nextBatch() {
    if (state.running || state.historyView) return;
    const next = state.offset + state.metrics.length;
    state.offset = next >= state.pool.length ? 0 : next;
    state.metrics = state.pool.slice(state.offset, state.offset + 5);
    state.selectedId = null;
    closeSheet();
    renderResults();                       // 卡片立刻换 —— 这批数据本来就在本地
    const col = document.querySelector('.col-results');
    if (col) scrollTo(col, 0);

    // 说明也必须重写。旧说明讲的是"第几套怎么样",而那几套已经不在屏幕上了 ——
    // 挂着一段对不上号的描述,比没有说明更容易让人误解。
    // 后端只重跑 explain:不重新检索、不重算指标,那些早就做完了。
    setRunning(true);
    const status = addStatus();
    status.querySelector('.t').textContent = T.statusRebatch;
    const a = addAssistantMsg();
    scrollChat();
    await streamPost('/api/rebatch', { thread_id: state.threadId, offset: state.offset, lang: state.lang },
                     runHandlers(status, a));
  }

  /** 引用有效性由当轮保存的 ID 决定,不再拿当前的 1–5 判断旧引用。 */
  function refreshRefs() {
    const currentKey = resultKey(resultView()), latestKey = resultKey(state);
    for (const b of document.querySelectorAll('.ref, .msg-results')) {
      const binding = referenceTargets.get(b); if (!binding) continue;
      const { snapshot, targets, title } = binding;
      const valid = !targets || targets.every(t => t.id != null);
      b.disabled = state.running || !valid;
      b.classList.toggle('stale', !valid);
      if (targets) {
        b.title = !valid ? T.referenceUnavailable : (snapshot.key !== currentKey ? T.viewHistorical + ' · ' : '') + title;
      } else {
        const viewing = !!state.historyView && snapshot === state.historyView;
        b.textContent = viewing ? T.viewingHistorical : snapshot.key === latestKey ? T.currentResults : T.viewHistorical;
        b.setAttribute('aria-pressed', String(viewing));
        b.closest('.msg-row').classList.toggle('viewing-history', viewing);
      }
    }
  }

  /** 地图现在是常驻的一栏(不再是「列表/地图」二选一),每次有新结果就重画。 */
  function renderMap() {
    const box = $('#map'); if (!box) return;
    const view = resultView();
    clearTimeout(state.focusTimer); state.focusTimer = null;
    // Leaflet 不能在同一节点上初始化两次。观察器也要一起断开 ——
    // 下面有两条提前 return 的路径,留在那儿会盯着一张已经拆掉的地图。
    if (state.map) { state.map.remove(); state.map = null; }
    if (state.mapRO) { state.mapRO.disconnect(); state.mapRO = null; }
    state.pins = []; state.mapFit = null;   // 地图拆了,图钉和「显示全部」的引用也跟着作废
    state.measure = null;                 // 测距那一层也随地图一起没了
    box.innerHTML = '';
    setMapCount(view.metrics.length);
    if (typeof L === 'undefined') { box.innerHTML = '<div class="map-empty"></div>'; box.firstChild.textContent = T.mapOffline; return; }
    const pts = view.metrics.filter(m => m.latitude != null && m.longitude != null);
    if (!pts.length) { box.innerHTML = '<div class="map-empty"></div>'; box.firstChild.textContent = T.mapNoCoords; return; }

    // attributionControl 关掉 —— 署名自己画在右下角(index.html),
    // 免得被边缘渐隐糊掉。ODbL 要求署名可见,这是法律要求。
    // 历史回看可在点击图钉后立即替换地图。Leaflet 的延迟缩放回调会访问已拆除
    // 的图层;这里直接完成缩放,保留拖拽/平移,避免旧地图动画跨过结果切换。
    // 缩放按钮是面板自己画的毛玻璃竖条(index.html .map-ctl),Leaflet 自带的关掉。
    const map = L.map(box, { zoomControl: false, attributionControl: false, zoomAnimation: false });
    addBasemap(map);
    const group = [];
    const pins = [];
    // 同一栋楼的不同单元坐标几乎重合(实测两个单元只差 2.6 米),图钉会叠在一起 ——
    // 看上去就像"这个号的图钉跑到别人身上了"。按坐标分组,重合的横向岔开。
    const cluster = new Map();
    for (const m of pts) {
      const key = m.latitude.toFixed(4) + ',' + m.longitude.toFixed(4);   // ≈11 米一格
      if (!cluster.has(key)) cluster.set(key, []);
      cluster.get(key).push(m);
    }
    const nudgeOf = m => {
      const arr = cluster.get(m.latitude.toFixed(4) + ',' + m.longitude.toFixed(4)) || [];
      if (arr.length < 2) return 0;
      const i = arr.indexOf(m);
      return (i - (arr.length - 1) / 2) * 26;    // 徽章宽 22,间距要 >22 才真的分得开
    };
    pts.forEach(m => {
      // 编号必须和卡片完全一致,两处都容易错:
      //   · 不能用 pts 的下标 —— pts 过滤掉了没坐标的房源,缺一套就整体错位,
      //     而且只在缺坐标时才出错,极难发现。
      //   · 必须加 offset —— 换一批之后卡片是 6–10,只算批内下标会得到 1–5。
      const no = view.offset + view.metrics.indexOf(m) + 1;
      // 图钉:**尖端对准坐标,号码浮在上方**。
      // 原来是个直径 20 的圆点扣在坐标正中央 —— 而坐标那一点正是要看的东西
      // (门牌号、这栋楼本身),等于用标记盖住了它要标记的对象。
      // 水滴形图钉之所以是通用做法,就是为了这个。
      const mk = L.marker([m.latitude, m.longitude], {
        icon: L.divIcon({
          className: 'pin',
          // 岔开量加在**内层**。外层 .pin 是 Leaflet 用 transform 定位的,
          // 在它身上再写 transform 会把定位覆盖掉,图钉会飞到地图角落。
          html: '<span class="pin-in" style="--nx:' + nudgeOf(m) + 'px">'
              + '<span class="pin-badge">' + no + '</span><span class="pin-tip"></span></span>',
          // 22(徽章) + 7(尖端) − 1(负边距) = 28,容器高度必须正好等于它 ——
          // 多 2px 尖端就悬在坐标点上方 2 像素,而"尖端精确指向坐标"正是这次改动的全部意义。
          iconSize: [26, 28], iconAnchor: [13, 28],
        }),
        keyboard: false,
      }).addTo(map);
      pins.push({ no, mk });
      mk.on('click', () => openDetail(m));
      group.push([m.latitude, m.longitude]);
    });
    state.pins = pins;
    // 兜底视野:墨尔本。fitBounds 万一算不准,至少不会露出半个澳洲。
    map.setView([-37.81, 144.96], 11);
    // padding 从 30 加到 56:边缘有一圈渐隐 + 颗粒,标记落进去就看不清了
    const fit = () => {
      if (!box.clientWidth || !box.clientHeight) return;   // 容器还没尺寸,取景必错
      map.invalidateSize();
      // 结果切换可能很快再次销毁地图,初次取景不启动延迟缩放动画。
      // 内边距 = 磨砂圈宽度(左边最厚):房源落在中间通透的那块,不压进边上的磨砂和上下两行字;右边还有控制条。
      map.fitBounds(group, { paddingTopLeft: [170, 96], paddingBottomRight: [96, 104], maxZoom: 14, animate: false });
    };
    fit();
    state.map = map;
    // 面板上沿的坐标跟着地图中心走
    const coord = () => { const c = map.getCenter(), e = $('#map-coord'); if (e) e.textContent = c.lat.toFixed(4) + ', ' + c.lng.toFixed(4); };
    map.on('move', coord); coord();

    // 谁在控制视野:用户一旦自己拖过/滚过,就不再自动取景 ——
    // 否则他放大看某一片,栏宽一变就被拽回全局。
    let userTook = false;
    const mark = () => { userTook = true; };
    box.addEventListener('pointerdown', mark, { passive: true });
    box.addEventListener('wheel', mark, { passive: true });
    // 「显示全部」= 交还取景权并重新框住这一批;放大/缩小算用户接管。
    state.mapFit = () => { userTook = false; fit(); };
    state.mapTook = mark;
    map.on('unload', () => {
      box.removeEventListener('pointerdown', mark);
      box.removeEventListener('wheel', mark);
    });

    // Leaflet 不会自己发现容器尺寸变了,只会留下一片灰、或者只画出两块瓦片。
    // 用 ResizeObserver 而不是 window.resize:栏宽变化不一定伴随窗口变化
    // (欢迎态切到工作态、栅格重排都会改容器尺寸而窗口没动)。
    //
    // 之前写成"只在第一次拿到尺寸时取景",而初值取的是 `box.clientWidth > 0` ——
    // 建图那一刻宽度已经非零、但高度还是 0,于是判定"已取过景"再也不修正,
    // 地图就停在那个算歪的缩放上(实测显示成整个维州加塔斯马尼亚)。
    // 现在改成:只要用户还没接管,尺寸每变一次就重新取一次景。
    state.mapRO = new ResizeObserver(() => {
      if (state.map !== map) return;
      map.invalidateSize();
      if (!userTook) fit();
    });
    state.mapRO.observe(box);
  }

  // ---------------------------------------------------------------- 详情
  function kv(k, v, cls, s) { const e = h('div', 'kv'); e.appendChild(h('div', 'k', k)); const vv = h('div', 'v' + (cls ? ' ' + cls : '')); vv.textContent = v; e.appendChild(vv); if (s) e.appendChild(h('div', 's', s)); return e; }
  // ---------------------------------------------------------------- 点卡片 → 地图跟过去
  /** 选中的那枚图钉加一圈光晕并浮到最上层。 */
  function markPin(no) {
    for (const { no: n, mk } of (state.pins || [])) {
      const el = mk.getElement && mk.getElement();
      if (el) el.classList.toggle('on', n === no);
    }
  }

  /** 点了哪套房,地图就飞到哪套房,并高亮它的图钉。 */
  function focusOnMap(m) {
    const map = state.map;
    const view = resultView();
    const at = view.metrics.findIndex(item => item.id === m.id);
    markPin(at >= 0 ? view.offset + at + 1 : 0);        // 不在当前结果里(收藏夹打开)就不高亮任何编号
    if (!map || typeof L === 'undefined' || m.latitude == null || m.longitude == null) return;
    const ll = [m.latitude, m.longitude];
    const zoom = Math.max(map.getZoom(), 15);
    map.setView(ll, zoom, { animate: false });
    // 等详情窗布局稳定后校正遮挡位置。计时器必须可取消,并验证仍是同一张地图、
    // 同一套房;历史切换或距离测算接管后不能访问已拆除的地图或把新视图拽回去。
    clearTimeout(state.focusTimer);
    state.focusTimer = setTimeout(() => {
      if (state.map !== map || state.selectedId !== m.id) return;
      const c = map.getCenter();
      if (Math.abs(c.lat - ll[0]) > 1e-4 || Math.abs(c.lng - ll[1]) > 1e-4) {
        map.setView(ll, zoom, { animate: false });
      }
      nudgeForPanel(map);
    }, 800);
  }

  /** 底图:优先毛玻璃矢量底图(map-glass.js),拿不到就退回 OSM 栅格瓦片。
   *  矢量库是懒加载的,第一次要等它到位;等的时候地图可能已经被换掉,所以先核对是不是同一张。 */
  function addBasemap(map) {
    const raster = () => L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, className: 'osm-raster' }).addTo(map);
    const attr = vector => { const e = document.querySelector('.attr-vector'); if (e) e.hidden = !vector; };
    if (!window.nwGlassBase) { raster(); attr(false); return; }
    window.nwGlassBase().then(style => {
      if (state.map !== map) return;
      if (style) { L.maplibreGL({ style, attributionControl: false, interactive: false }).addTo(map); attr(true); }
      else { raster(); attr(false); }
    });
  }

  // ---------------------------------------------------------------- 地图面板:控制条 / 城市 / 计数
  function setMapCount(n) { const e = $('#map-count'); if (e) e.textContent = T.mapCount(n); }

  /** 城市只做演示:只有墨尔本有数据。其余列出名字、标「即将支持」、不可选 ——
   *  不给它们放地图,也不假装能搜。 */
  const CITIES = [['MELBOURNE', true], ['SYDNEY'], ['BRISBANE'], ['ADELAIDE'], ['PERTH'], ['CANBERRA'], ['HOBART']];
  function renderCityMenu() {
    const menu = $('#city-menu'); if (!menu) return;
    menu.replaceChildren(...CITIES.map(([name, live]) => {
      const li = h('li', 'city-opt' + (live ? ' on' : ''));
      li.setAttribute('role', 'option'); li.setAttribute('aria-selected', live ? 'true' : 'false');
      if (!live) li.setAttribute('aria-disabled', 'true');
      li.append(h('span', 'city-opt-name', name), h('span', 'city-opt-tag', live ? '' : T.citySoon));
      if (live) li.addEventListener('click', () => closeCityMenu());
      return li;
    }));
  }
  function closeCityMenu() {
    const menu = $('#city-menu'); if (!menu || menu.hidden) return false;
    menu.hidden = true; $('#city-btn').setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', cityOutside, true);
    return true;
  }
  function cityOutside(ev) { if (!ev.target.closest('.city')) closeCityMenu(); }
  function initMapPanel() {
    $('#city-btn').addEventListener('click', () => {
      if (closeCityMenu()) return;
      renderCityMenu();
      $('#city-menu').hidden = false; $('#city-btn').setAttribute('aria-expanded', 'true');
      setTimeout(() => document.addEventListener('pointerdown', cityOutside, true), 0);
    });
    $('#map-fit').addEventListener('click', () => { if (state.mapFit) state.mapFit(); });
    $('#map-zin').addEventListener('click', () => { if (state.map) { state.mapTook && state.mapTook(); state.map.zoomIn(); } });
    $('#map-zout').addEventListener('click', () => { if (state.map) { state.mapTook && state.mapTook(); state.map.zoomOut(); } });
  }

  /** 详情浮窗就盖在地图上,而点卡片的目的正是"看它在哪" ——
   *  居中等于把它藏到窗子底下。把视图往右推,让标记落在窗子左边那片还看得见的地方。 */
  function nudgeForPanel(map) {
    const d = $('#detail');
    if (!d || !d.classList.contains('open') || !twoColumn()) return;
    const wrap = document.querySelector('.map-wrap');
    if (!wrap) return;
    const mr = wrap.getBoundingClientRect(), dr = d.getBoundingClientRect();
    const cut = Math.max(mr.left, Math.min(dr.left, mr.right));   // 窗子左边缘在地图上的位置
    const visible = cut - mr.left;
    if (visible < 160) return;                     // 剩下的地方太窄,推了也没用
    const dx = (mr.left + mr.width / 2) - (mr.left + visible / 2);
    if (dx > 20) map.panBy([dx, 0], { animate: false });
  }

  // ---------------------------------------------------------------- 详情浮窗的拖动
  /** 位置只存在 --dx / --dy 两个自定义属性上,不改 left/top ——
   *  改 left/top 每帧都要重排;只动 transform 才跑得动。
   *  拖过的位置会保留(换一套房还在原处),「新对话」时归位。 */
  let dragOff = { x: 0, y: 0 };
  function setDetailPos(x, y) {
    dragOff = { x, y };
    const d = $('#detail');
    d.style.setProperty('--dx', x + 'px');
    d.style.setProperty('--dy', y + 'px');
  }

  function makeDraggable(bar) {
    bar.addEventListener('pointerdown', ev => {
      if (ev.target.closest('.d-close')) return;      // 点关闭不是拖窗
      if (!twoColumn()) return;                       // 窄屏是底部抽屉,不拖
      const d = $('#detail');
      const r = d.getBoundingClientRect();
      // 去掉当前位移,得到"没被拖过时"的位置,夹取范围据此算
      const baseLeft = r.left - dragOff.x, baseTop = r.top - dragOff.y;
      const startX = ev.clientX, startY = ev.clientY;
      const base = { x: dragOff.x, y: dragOff.y };
      // 无论拖到哪,至少留 140px 宽在屏内、标题栏不许钻到顶栏上面 ——
      // 否则窗子一拖出界就再也抓不回来了。
      const minX = -(baseLeft + r.width - 140), maxX = innerWidth - baseLeft - 140;
      const minY = 57 - baseTop, maxY = innerHeight - baseTop - 56;
      const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

      bar.setPointerCapture(ev.pointerId);
      d.classList.add('dragging');
      const move = e => setDetailPos(clamp(base.x + e.clientX - startX, minX, maxX),
                                     clamp(base.y + e.clientY - startY, minY, maxY));
      const up = () => {
        d.classList.remove('dragging');
        try { bar.releasePointerCapture(ev.pointerId); } catch (_) { /* 已经放开了 */ }
        bar.removeEventListener('pointermove', move);
        bar.removeEventListener('pointerup', up);
        bar.removeEventListener('pointercancel', up);
      };
      bar.addEventListener('pointermove', move);
      bar.addEventListener('pointerup', up);
      bar.addEventListener('pointercancel', up);
      ev.preventDefault();
    });
  }

  /** 距离测算:两个输入框,量出来的东西同时画在地图上。
   *
   *  **起点默认就是这套房**,因为九成的问题是"这套房到我上班/上学的地方多远"。
   *  要它先填一遍自己的地址,等于让每个人都先做一遍无意义的复制粘贴。
   */
  function measureBlock(m) {
    const box = h('div', 'measure');
    const head = h('div', 'measure-head');
    head.appendChild(h('span', 'mh-t', T.measureTitle));
    head.appendChild(h('span', 'mh-k', T.measureKind));
    box.appendChild(head);

    const mkRow = (tag, label) => {
      const r = h('div', 'measure-row');
      r.appendChild(h('span', 'm-tag ' + tag, tag.toUpperCase()));
      r.appendChild(h('span', 'm-lab', label));
      const inp = h('input', 'm-in'); inp.type = 'text';
      r.appendChild(inp);
      return { row: r, inp };
    };

    const from = mkRow('a', T.measureFrom);
    from.inp.value = (m.suburb || '') + ' · ' + (m.address || '');
    // 起点默认是这套房本身,所以带着它的坐标走;用户改成别的名字之后
    // 坐标就作废,交给服务端按名字重新解析 —— 否则会拿旧坐标配新名字。
    let originCoords = { lat: m.latitude, lon: m.longitude };
    from.inp.addEventListener('input', () => { originCoords = null; });

    const to = mkRow('b', T.measureTo);
    to.inp.placeholder = T.measureToPlaceholder;

    const go = h('button', 'btn small m-go', T.measureGo); go.type = 'button';
    to.row.appendChild(go);
    box.appendChild(from.row); box.appendChild(to.row);

    const result = h('div', 'measure-out'); result.hidden = true;
    const big = h('div', 'm-dist');
    const pair = h('div', 'm-pair');
    // 详情窗盖住了地图的大半边:1440 宽的窗口下地图栏 577px、窗子压掉 461px,
    // 只剩 116px 的缝。17 公里的连线塞进那条缝里只有几十像素,画得再准也没用。
    // 所以给一个"看地图"的出口 —— 关掉窗子,整幅地图就腾出来了,
    // 而测算结果本来就留在地图上不会消失。
    const look = h('button', 'link m-look', T.measureLook); look.type = 'button';
    look.addEventListener('click', () => closeSheet());       // 去看地图:不算「关掉详情回收藏」
    // 有画上去的东西,就得有擦掉的办法。之前只能靠"换一套房"顺带清掉 ——
    // 那不是一个出口,那是副作用。
    const wipe = h('button', 'link m-wipe', T.measureClear); wipe.type = 'button';
    wipe.addEventListener('click', () => {
      clearMeasure();
      to.inp.value = '';
      result.hidden = true; err.hidden = true;
      to.inp.focus();
    });
    const acts = h('div', 'm-acts');
    acts.appendChild(look); acts.appendChild(wipe);
    result.appendChild(big); result.appendChild(pair); result.appendChild(acts);
    box.appendChild(result);
    const err = h('div', 'measure-err'); err.hidden = true;
    box.appendChild(err);
    box.appendChild(h('div', 'caveat', T.measureNote));

    async function run() {
      const q = to.inp.value.trim();
      if (!q) { to.inp.focus(); return; }
      go.disabled = true; go.textContent = T.measureBusy; err.hidden = true;
      const origin = originCoords && originCoords.lat != null
        ? { lat: originCoords.lat, lon: originCoords.lon, label: from.inp.value.trim() }
        : { q: from.inp.value.trim() };
      let res;
      try {
        res = await fetch('/api/measure', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ origin, target: { q } }),
        });
      } catch (_) {
        go.disabled = false; go.textContent = T.measureGo; return;
      }
      go.disabled = false; go.textContent = T.measureGo;
      if (!res.ok) {
        let msg = '';
        try { msg = (await res.json()).detail || ''; } catch (_) { msg = await res.text(); }
        err.textContent = msg; err.hidden = false; result.hidden = true;
        return;
      }
      const j = await res.json();
      result.hidden = false;
      pair.textContent = T.measurePair(j.origin.name, j.target.name);
      // 先把最终值写上,再让动画从 0 数上来落在同一个数上。
      // 这个顺序很要紧:预览里 rAF 被节流过好几次,动画不跑的时候
      // 数字**已经是对的**,而不是停在 0。
      big.textContent = dist(j.distance_m);
      countUp(big, j.distance_m);
      drawMeasure(j);
    }
    go.addEventListener('click', run);
    to.inp.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); run(); } });
    return box;
  }

  /** 数字从 0 滚上去,最后定格。
   *  调用方**必须先把最终值写好**再调它 —— 见 measureBlock 里那条注释。 */
  function countUp(el, meters, ms) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const total = ms || 620, t0 = performance.now();
    const step = now => {
      const k = Math.min(1, (now - t0) / total);
      // easeOutCubic:开头快、末尾慢,读起来像"冲上去然后稳住"
      el.textContent = dist(Math.round(meters * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(step); else el.textContent = dist(meters);
    };
    requestAnimationFrame(step);
  }

  /** 把测算结果画到地图上:两枚图钉 + 一根线 + 悬在线上方的距离。
   *
   *  视觉上是"情报板上钉一根线"那套语言:深色图钉 + 一根绷紧的红线。
   *  **但线是笔直的,不做垂坠感。** 弯的绳子好看,可这个功能量的就是直线距离
   *  (系统没有路网数据),画成弧线等于用画面撒谎。造型可以借,语义不能借。
   *
   *  线画两条叠在一起:底下一条宽而淡的当纸面上的洇痕,上面一条细而实的当线本身。
   *  单一笔画在地图这种花底子上会显得很薄。
   */
  function drawMeasure(j) {
    const map = state.map; if (!map) return;
    // 抢过取景权:focusOnMap 的补位定时器会在 800ms 后把视图拽回这套房,
    // 那正好落在"刚画完测算"的时间窗里。
    clearTimeout(state.focusTimer);
    clearMeasure();
    const a = [j.origin.latitude, j.origin.longitude];
    const b = [j.target.latitude, j.target.longitude];
    const layer = L.layerGroup().addTo(map);
    state.measure = layer;

    // 整层都不接受点击。测距是"看"的东西,不是"点"的东西 ——
    // 而且可点的覆盖层会截住地图本身的拖拽和缩放,那才是真的碍事。
    const line = L.polyline([a, b], { className: 'mline-halo', weight: 7,
                                      interactive: false }).addTo(layer);
    const core = L.polyline([a, b], { className: 'mline', weight: 1.75,
                                      interactive: false }).addTo(layer);
    drawStroke(core.getElement());
    // 缩放前把虚线属性抹掉,双保险。
    //
    // dasharray 是按**当时那一段路径的长度**设的,而缩放会让 Leaflet 重算路径;
    // 旧长度配新路径 = 线变断续、甚至整段看不见 —— 用户报的"一缩放线就没了"
    // 就是这个。drawStroke 里已经用定时器清了一次,这里再挂一道:
    // 定时器万一没跑(标签页被节流、动画没播),缩放这条路也能把它清掉。
    // 同一件事宁可清两遍,也不要留一条只在别人机器上才犯的 bug。
    const strip = () => {
      const el = core.getElement();
      if (!el) return;
      el.style.transition = '';
      el.style.strokeDasharray = '';
      el.style.strokeDashoffset = '';
    };
    map.on('zoomstart', strip);
    state.measureOff = () => map.off('zoomstart', strip);

    // 图钉沿用房源图钉的水滴造型(尖端对准坐标),只换颜色和里面的字母 ——
    // 同一张地图上两种标记该是一家人,不该一个水滴一个圆片。
    const pin = (cls, text) => L.divIcon({
      className: 'mpin ' + cls,
      html: '<span class="mpin-in"><span class="mpin-badge">' + text + '</span>'
          + '<span class="mpin-tip"></span></span>',
      iconSize: [26, 28], iconAnchor: [13, 28],
    });
    L.marker(a, { icon: pin('a', 'A'), keyboard: false, interactive: false }).addTo(layer);
    L.marker(b, { icon: pin('b', 'B'), keyboard: false, interactive: false }).addTo(layer);

    state.measureBounds = L.latLngBounds([a, b]);
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    // 读数挂在中点上,下面拖一根细引线接到那条线上 —— 有引线它才是"这根线的读数",
    // 没有引线就只是一块飘在地图上的牌子。
    const label = L.marker(mid, {
      icon: L.divIcon({
        className: 'mlabel',
        html: '<span class="ml-chip"><b class="ml-num"></b></span><i class="ml-stem"></i>',
        iconSize: [0, 0], iconAnchor: [0, 0],
      }),
      keyboard: false, interactive: false,
    }).addTo(layer);
    const num = label.getElement().querySelector('.ml-num');
    // 和面板里那个大号数字一样:先写好最终值,再让它从 0 滚上来。
    num.textContent = dist(j.distance_m);
    countUp(num, j.distance_m);

    fitAvoidingPanel(map, state.measureBounds);
    return line;
  }

  /** 让一条 SVG 线"画"出来,画完**把虚线属性清掉**。
   *
   *  清掉这一步是必须的,不是收尾洁癖:dasharray 是按当时那一段路径的长度设的,
   *  而缩放地图会重算路径。旧的 dasharray 配新的路径长度,线会变成断续的甚至
   *  整段看不见 —— 实测就是"一缩放线就没了"。动画结束后线就该是一条普通的实线。
   */
  function drawStroke(path) {
    if (!path) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const len = path.getTotalLength();
    path.style.strokeDasharray = len;
    path.style.strokeDashoffset = len;
    void path.getBoundingClientRect();             // 强制一次布局,否则过渡不触发
    path.style.transition = 'stroke-dashoffset 620ms cubic-bezier(0.23,1,0.32,1)';
    path.style.strokeDashoffset = '0';
    // 用定时器兜底而不是只听 transitionend:过渡在被节流的标签页里可能一次都不触发,
    // 那时 transitionend 永远不来,虚线属性就永久留在了线上。
    setTimeout(() => {
      path.style.transition = '';
      path.style.strokeDasharray = '';
      path.style.strokeDashoffset = '';
    }, 700);
  }

  /** 取景时把详情窗盖住的那块地图算作"看不见的边距"。
   *
   *  不这么做的话,fitBounds 会按整个地图容器取景,而容器右边七成被详情窗盖着 ——
   *  两个图钉和那根线正好落在窗子底下,画得再好也看不见。实测第一版就是这样:
   *  只有 A 图钉的一角露在左边缘。 */
  function fitAvoidingPanel(map, bounds) {
    const wrap = document.querySelector('.map-wrap');
    const d = $('#detail');
    let right = 56;
    if (wrap && d && d.classList.contains('open') && twoColumn()) {
      const mr = wrap.getBoundingClientRect(), dr = d.getBoundingClientRect();
      const overlap = Math.max(0, mr.right - Math.max(dr.left, mr.left));
      // 留至少 90px 的可视宽度。padding 逼近容器宽度时 fitBounds 会算出
      // 荒唐的缩放级别,宁可让窗子压掉一点。
      // 1440 宽的窗口下地图栏 577px、详情窗压掉 461px,只剩 116px ——
      // 门槛定在 160 就等于这个功能在最常见的窗口尺寸下完全不生效。
      if (mr.width - overlap > 90) right = overlap + 16;
    }
    // 只剩一条窄缝时上下左右都别再留大边距,不然可用面积会被吃光
    const tight = right > 56 ? 16 : 56;
    // **不带动画。** 这是本项目第四次踩同一个坑:Leaflet 的缩放动画走 rAF,
    // 而预览里的 rAF 会被节流。上一次动画没播完就再调一次 fitBounds,
    // Leaflet 的 _animatingZoom 还挂着 true,第二次取景被整个吞掉 ——
    // 不报错,视图停在上一次的缩放级别上(实测卡在 z9,应该是 z11)。
    // 取景是"到没到位"的事,不是"好不好看"的事,不值得为动画赌它。
    map.invalidateSize();
    map.fitBounds(bounds, { animate: false,
                            paddingTopLeft: [tight, tight], paddingBottomRight: [right, tight] });
  }

  function clearMeasure() {
    if (state.measureOff) { state.measureOff(); state.measureOff = null; }
    if (state.measure) { state.measure.remove(); state.measure = null; }
    state.measureBounds = null;
  }

  function row(k, v, cls, small) { const e = h('div', 'row'); e.appendChild(h('span', 'k', k)); const vv = h('span', 'v' + (cls ? ' ' + cls : '')); vv.textContent = v; if (small) { const sm = h('small', null, ' ' + small); vv.appendChild(sm); } e.appendChild(vv); return e; }

  /** 一行「账」:左边一句人话,右边一个数,数底下小字说这数是谁定的、怎么来的。
   *  用它替掉原来的四格并排 —— 并排的四个术语没有先后,读的人不知道该先看哪个;
   *  竖着一行行加下来,是所有人从小学就会读的那种账。 */
  function payRow(label, value, note, cls) {
    const e = h('div', 'pay' + (cls ? ' ' + cls : ''));
    const left = h('div'); left.appendChild(h('div', 'pk', label));
    if (note) left.appendChild(h('div', 'pn', note));
    e.appendChild(left); e.appendChild(h('div', 'pv', value));
    return e;
  }

  /** 一行「账」,但右边那个数是**可以改的**。
   *
   *  假设原来摆在详情窗最底下,和它影响的那几个数隔着两屏。可用户是在盯着
   *  「合计 $585,370」的时候才想到"杂费能不能改成 3000",这时候要他滚到底、
   *  改完再滚回来核对 —— 中间隔着的那几屏已经把上下文冲没了。
   *  数字和调它的旋钮必须挨在一起,这是这次改动的全部理由。
   */
  /** 一个可编辑的假设字段:边框 + 铅笔。
   *
   *  第一版把它做成"数字底下一条虚线"。杂费那个在 17px 的数值列里还看得见,
   *  运营支出那个在 11px 的灰色注解里 —— 虚线几乎不可见,实测有人**根本没发现
   *  第二个能改**。两个字段用同一套外壳之后,认出一个就认得出另一个。
   *
   *  铅笔不是装饰:条件卡上"点一下改"的芯片用的就是同一个图标,
   *  在这个界面里铅笔已经等于"可点击修改"。复用已有的约定,比再发明一个便宜。
   */
  function assumeField(inp, big) {
    const box = h('span', 'assume-field' + (big ? ' big' : ''));
    box.appendChild(inp);
    const pen = h('span', 'af-pen'); pen.innerHTML = PENCIL;
    box.appendChild(pen);
    // 点边框任何地方都进输入框 —— 只有数字本身可点的话,那个铅笔就成了摆设
    box.addEventListener('click', ev => { if (ev.target !== inp) inp.focus(); });
    return box;
  }

  function payRowNum(label, note, opts) {
    const e = h('div', 'pay assume editable');
    const left = h('div'); left.appendChild(h('div', 'pk', label));
    if (note) left.appendChild(note.nodeType ? note : h('div', 'pn', note));
    e.appendChild(left);
    const val = h('div', 'pv');
    val.appendChild(h('span', 'pv-pre', opts.prefix || ''));
    const inp = h('input', 'pv-in'); inp.type = 'number'; inp.step = opts.step || '1';
    inp.value = opts.value; inp.inputMode = 'decimal';
    if (opts.min != null) inp.min = opts.min;
    if (opts.max != null) inp.max = opts.max;
    val.appendChild(assumeField(inp, true));
    if (opts.suffix) val.appendChild(h('span', 'pv-pre', opts.suffix));
    e.appendChild(val);
    // change 而不是 input:每敲一个字符就发一次请求,既浪费也会在中间态
    // (比如刚删空)算出一堆没意义的数。回车或者点到别处才算改完。
    // 宽度跟着内容走。固定宽度加右对齐会在 $ 和数字之间留一大段空白,
    // 读起来像两个东西,而它们是一个数。ch 单位配 tabular-nums 正好等于字符宽。
    const fit = () => { inp.style.width = Math.max(2, String(inp.value).length) + 0.6 + 'ch'; };
    fit();
    inp.addEventListener('input', fit);
    inp.addEventListener('change', () => opts.onChange(parseFloat(inp.value)));
    inp.addEventListener('keydown', ev => { if (ev.key === 'Enter') inp.blur(); });
    return e;
  }

  /** 行话对照,默认收起来。
   *  术语一个都没删:要拿这些词写作业、和中介对话的人,点开就找得到;
   *  只是不让它们挡在第一眼。原来的问题不是有术语,是术语站在了最前面。 */
  function jargon(title, pairs) {
    const dt = document.createElement('details'); dt.className = 'jargon';
    const sm = document.createElement('summary'); sm.textContent = title;
    dt.appendChild(sm);
    for (const [term, plain] of pairs) {
      if (!plain) continue;
      const r = h('div', 'jrow');
      r.appendChild(h('span', 'jt', term)); r.appendChild(h('span', 'jp', plain));
      dt.appendChild(r);
    }
    return dt;
  }

  /** 把 0~100 的属性分说成人话。
   *  分数本身没有参照物 ——「安静 92」好到什么程度?读者答不上来。
   *  排位是 enrich 时用全库分布算好的(context.score_rank),这里只负责措辞。
   *  保留合法的 0,只封顶 99:不说「超过全库 100% 的房源」。 */
  function rankText(m, attr) {
    const r = (m.context_ranks || {})[attr];
    if (r == null) return '';
    return T.rank(Math.min(Math.max(r, 0), 99));
  }

  /** 详情窗的内容顺序 = 一个人看房时真会问的问题的顺序:
   *    这价合不合理 -> 住着怎么样 -> 一共要掏多少 -> 租出去收得回来吗 -> 有什么要留神的
   *  原来打头的是「投资账」,四个术语并排(毛租金回报率 / 印花税 / NOI / Cap Rate·ROI),
   *  第一眼就要同时消化四个不认识的词。信息没错,顺序错了。 */
  /** keepToken:并排收缩回一套时用 —— 保留原来的来源令牌、不再广播「打开」,
   *  这样从收藏进来的并排,缩成一套后关掉照样回收藏。 */
  function openDetail(m, { keepToken = false } = {}) {
    // 上一套房的测算结果要擦掉:那根线量的是**上一套**到某地的距离,
    // 留着会被当成当前这套的。
    if (state.selectedId !== m.id) clearMeasure();
    state.selectedId = m.id;
    for (const c of document.querySelectorAll('.card')) c.classList.toggle('selected', c.dataset.id == m.id);
    focusOnMap(m);
    const d = $('#detail'); d.innerHTML = ''; d.classList.remove('compare');
    state.compare = []; state.detailMetric = m;           // 单开:并排状态清空
    if (!keepToken) state.detailToken = m.id;             // 关闭时按这个令牌告诉收藏模块是谁打开的
    d.appendChild(h('div', 'grabber'));            // 窄屏抽屉的下拉条
    // 宽屏:标题栏兼拖动把手
    const bar = h('div', 'd-bar');
    bar.appendChild(h('div', 'd-bar-title', (m.suburb || '') + ' · ' + (m.address || '')));
    const close = h('button', 'd-close'); close.type = 'button'; close.title = T.closeEsc;
    close.setAttribute('aria-label', T.close); close.innerHTML = X;
    close.addEventListener('click', () => closeSheet({ user: true }));
    bar.appendChild(compareButton(T.cmpAdd));            // 「+ 并排对比」:再开一套放在右边
    bar.appendChild(close); d.appendChild(bar);
    makeDraggable(bar);

    renderDetailInto(d, m);
    openSheet();
    if (!keepToken) window.dispatchEvent(new CustomEvent('nw:detail', { detail: { open: true, id: state.detailToken } }));
  }

  /** 把一套房的详情内容(头部 + 五段 + 图例)画进容器 d。
   *  单独打开时画进详情窗;并排对比时每套画进一列,compact 时不画距离测算。
   *  每段带 data-sec,并排时按段对齐(见 renderCompare)。 */
  function renderDetailInto(d, m, { compact = false } = {}) {
    const meta = state.meta;
    // ---- 头部 ----
    // 地址宽屏时标题栏里已经有一份了,这里的那份用 CSS 藏掉(窄屏没有标题栏,留着)。
    // 原来两处都显示,详情窗一打开顶上就是同一行字写两遍。
    const head = h('div', 'd-head'); const l = h('div');
    l.appendChild(h('div', 'd-addr', (m.suburb || '') + ' · ' + (m.address || '')));
    l.appendChild(h('div', 'd-price', money(m.price)));
    l.appendChild(h('div', 'd-meta', [T.beds(m.bedrooms), T.baths(m.bathrooms), typeZh(m), m.distance_cbd != null ? T.toCbd(m.distance_cbd) : null].filter(Boolean).join(' · ')));
    head.appendChild(l);
    // 和卡片用同一套指标列(标签在上、数值在下),两处看起来才是一件东西
    const hl = headline(m);
    const hd = h('div', 'metrics');
    const pm = h('div', 'metric primary');
    pm.appendChild(h('div', 'ml', hl.l));
    const pv = h('div', 'mv ' + hl.cls); pv.textContent = hl.v; pm.appendChild(pv);
    const sortAttr = resultView().params?.sort_by;
    if (sortAttr && meta.attributes[sortAttr]) {
      const rt = rankText(m, sortAttr);
      if (rt) pm.appendChild(h('div', 'ms', rt));
    }
    hd.appendChild(pm); head.appendChild(hd);
    head.dataset.sec = 'head'; d.appendChild(head);

    // ---- 一、这个价合不合理 ----
    // 放在最前面,因为这是所有人点开一套房时脑子里的第一个问题。
    if (m.predicted_price != null) {
      const s = h('div', 'sec');
      s.appendChild(h('div', 'sec-title', T.sec1));
      const cmp = h('div', 'cmp');
      cmp.appendChild(kv(T.askingPrice, money(m.price)));
      cmp.appendChild(kv(T.modelEstimate, money(m.predicted_price), 'model'));
      s.appendChild(cmp);

      // 差异必须和"这个模型能准到多少"写在同一句里。分开写的话,
      // "低于指导价 4%"会被读成"便宜了 4%",而 4% 根本没超过模型自身的误差。
      //
      // 正常的情况只报结论。价格正常是绝大多数房源的状态,把它展开成一整段,
      // 等于让人每点开一套就重读一遍同样的话;真正需要解释的是不正常的那些。
      // 判断看"售价在不在模型的把握区间里",不看差了几个百分点。
      // 区间是在模型没见过的成交上校准并验证过的:说 80% 就真有约 80% 的成交价落在里面。
      // 在区间里的差距就是正常波动,哪怕差 15% 也不许说成便宜或贵。
      const gap = m.predicted_gap, pos = m.valuation_position;
      const iv = m.valuation_interval || [], lvl = m.valuation_interval_level;
      if (iv[0] != null && lvl) {
        cmp.appendChild(kv(T.intervalLabel(pct(lvl, 0)), money(iv[0]) + ' – ' + money(iv[1]), 'model'));
      }
      let verdict = '';
      if (gap != null && pos) {
        if (pos === 'within') verdict = T.verdictWithin(pct(lvl, 0));
        else if (pos === 'below') verdict = T.verdictBelowRange(pct(gap), pct(lvl, 0));
        else verdict = T.verdictAboveRange(pct(-gap), pct(lvl, 0));
      }
      if (verdict) s.appendChild(h('div', 'plain', verdict));
      if (iv[0] != null && lvl) {
        s.appendChild(h('div', 'caveat', T.intervalNote(pct(lvl, 0), pct(m.valuation_interval_coverage, 0))));
      }
      s.dataset.sec = 'price'; d.appendChild(s);
    }

    // ---- 二、住在这儿是什么体验 ----
    const s2 = h('div', 'sec'); s2.appendChild(h('div', 'sec-title', T.sec2));
    const am = m.amenities || {}; const g4 = h('div', 'grid4'); let n4 = 0;
    for (const [k, v] of Object.entries(am)) { if (v && v.distance_m != null && n4 < 8) { g4.appendChild(kv(kindZh(k), dist(v.distance_m))); n4++; } }
    if (n4 || m.near_place) {
      s2.appendChild(g4);
      // 说清楚这是什么距离。地图上量的直线距离和真要走的路差得不少,
      // 不写出来,读者会默认它是"走过去要多久"。
      s2.appendChild(h('div', 'caveat', T.straightLine));
    }
    // ---- 距离测算 ----
    // 原来这儿摆的是 near_place 的距离(「The University of Melbourne,
    // Werribee Campus」8.0 km)。它有三个问题:卡片上已经有同一个数;
    // 长机构名在窄栏里折成四行;而且它是**上一轮检索条件的副产物**,
    // 不是用户此刻想问的东西。换成一个能自己动手量的工具。
    if (!compact) s2.appendChild(measureBlock(m));   // 并排时不画:它在唯一的地图上画线,多列会互相覆盖

    const scores = m.context_scores || {};
    const viewParams = resultView().params || {};
    const asked = new Set((viewParams.abstract_needs || []).map(a => a.attribute));
    for (const goal of viewParams.relative_preferences || []) if (meta.attributes[goal.field]) asked.add(goal.field);
    if (viewParams.sort_by && meta.attributes[viewParams.sort_by]) asked.add(viewParams.sort_by);
    for (const a of asked) {
      if (scores[a] == null) continue;
      const eb = h('div', 'evbox'); const t = h('div', 't');
      const rt = rankText(m, a);
      t.appendChild(h('b', null, attrZh(a) + ' ' + scores[a]));
      t.appendChild(h('span', null, rt || T.score0100));
      eb.appendChild(t);
      const evl = h('div');
      evl.appendChild(document.createTextNode(T.scoreBasis));
      evl.appendChild(evidenceNodes(m, a, 6));
      eb.appendChild(evl);
      // 注解是**属性的定义**,不是对这套房的判断 —— 它对每套房都一样显示。
      // 原来直接写"远离主干道与次干道…",一套安静度 20 分的房子也会看到这句,
      // 读起来就成了"系统说它远离主干道",而实际可能紧挨着路。
      // 加上"分数高 =",它才读得出是在解释这个分数怎么来的。
      if (meta.attribute_notes[a]) eb.appendChild(h('div', 'ev-note', T.highMeans + meta.attribute_notes[a]));
      s2.appendChild(eb);
    }
    s2.dataset.sec = 'living'; d.appendChild(s2);

    // ---- 三、买下来一共要付多少 ----
    // 印花税原来是四格里的一格,一个孤零零的术语。放进这列加法里,它就自动
    // 变成了"房价之外还要多付的一笔" —— 不用解释术语,位置本身就解释了。
    // 这一屏自己的假设。**改它只影响这一套房的这一屏** —— 是"如果杂费按 3000
    // 算会怎样"的试算,不是把全局默认改掉。要改全局,下面另有一个按钮。
    const a0 = m.assumptions || meta.assumptions.snapshot;
    const live = { opex_rate: a0.opex_rate, other_acquisition_costs: a0.other_acquisition_costs };
    const now = Object.assign({}, m);        // 当前显示的数,随试算更新
    const out = {};                          // 要跟着变的那几个节点

    /** 改完一个假设:后端按同一份公式重算,回来只刷会变的那几个数。
     *  整屏重画会把滚动位置和展开的折叠块一起冲掉,而用户正盯着某一行看。 */
    async function recalc() {
      let res;
      try {
        res = await fetch('/api/recalc', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ price: m.price, annual_rent: m.annual_rent,
                                 opex_rate: live.opex_rate,
                                 other_acquisition_costs: live.other_acquisition_costs }),
        });
      } catch (_) { return; }                // 断网就保持原样,不要把数字清空
      if (!res.ok) { alert(await res.text()); return; }
      Object.assign(now, await res.json());
      if (out.total) out.total.textContent = money(now.total_cost);
      if (out.noi) out.noi.textContent = '~' + money(now.noi);
      if (out.roi) out.roi.textContent = '~' + pct(now.roi);
      if (out.jg) {
        out.jg.noi.textContent = T.jgNoiF(money(now.noi));
        out.jg.cap.textContent = T.jgCapF(pct(now.cap_rate));
        out.jg.roi.textContent = T.jgRoiF(pct(now.roi));
      }
    }

    if (m.price != null && m.stamp_duty != null) {
      const s3 = h('div', 'sec'); s3.appendChild(h('div', 'sec-title', T.sec3));
      const box = h('div', 'paybox');
      box.appendChild(payRow(T.rowPrice, money(m.price), T.rowPriceNote));
      box.appendChild(payRow(T.rowDuty, money(m.stamp_duty), T.rowDutyNote(pct(m.stamp_duty / m.price))));
      box.appendChild(payRowNum(T.rowFees, T.rowFeesNoteEditable, {
        prefix: '~$', value: Math.round(live.other_acquisition_costs), step: '100', min: 0,
        onChange: v => { if (!isNaN(v) && v >= 0) { live.other_acquisition_costs = v; recalc(); } },
      }));
      if (m.total_cost != null) {
        const totalRow = payRow(T.rowTotal, money(m.total_cost), T.rowTotalNote, 'total');
        out.total = totalRow.querySelector('.pv');
        box.appendChild(totalRow);
      }
      s3.appendChild(box);
      s3.dataset.sec = 'cost'; d.appendChild(s3);
    }

    // ---- 四、如果租出去 ----
    if (m.annual_rent != null) {
      const s4 = h('div', 'sec'); s4.appendChild(h('div', 'sec-title', T.sec4));
      const box = h('div', 'paybox');
      // 注解里写明租金的匹配粒度:这个数是片区中位租金,不是这套房自己的租金
      box.appendChild(payRow(T.rowRent, money(m.annual_rent),
        [m.gross_yield != null ? T.rowRentNote(pct(m.gross_yield)) : '', T.rentScope[m.rent_source] || '']
          .filter(Boolean).join(' · ')));

      // 运营支出比例摆在它自己那句注解里 —— 那句话本来就在解释这个数怎么来的,
      // 把百分比换成输入框,读起来仍然是一句完整的话。
      const opexNote = h('div', 'pn');
      // 显示本轮快照里的运营支出比例,不再取整成 28(NOI/ROI 是按 28.4% 算的,旁边写 28% 就对不上)。
      // 做法:把后端发来的数的最短往返十进制文本小数点右移两位(0.284 -> 28.4,0 -> 0,1e-7 -> 0.00001,
      // 0.9999999999999999 -> 99.99999999999999),**不做浮点乘法、不四舍五入**,所以 <1 的比例不会被显示成 100,也没有 28.399999 这类尾巴。
      // 保证的只是「JSON 解析后这个数的最短往返十进制文本右移两位」;不保留原始 JSON 文本,也不是任意精度小数。
      const pctText = r => {
        let [mant, exp = '0'] = String(r).toLowerCase().split('e');
        let [ip, fp = ''] = mant.split('.'); let digits = ip + fp, point = ip.length + Number(exp) + 2;
        if (point <= 0) { digits = '0'.repeat(1 - point) + digits; point = 1; }
        if (point > digits.length) digits += '0'.repeat(point - digits.length);
        const whole = digits.slice(0, point).replace(/^0+(?=\d)/, ''), frac = digits.slice(point).replace(/0+$/, '');
        return frac ? whole + '.' + frac : whole;
      };
      // 输入框与下面 change 处理(v < 100)一致:step=any 允许小数;max 取「小于 100 的最大 16 位文本」,所以 100 会被浏览器判为越界,
      // 而合法的极端比例 0.9999999999999999 (显示 99.99999999999999) 仍然有效。
      const oi = h('input', 'pn-in'); oi.type = 'number'; oi.step = 'any'; oi.min = '0'; oi.max = '99.99999999999999';
      oi.value = pctText(live.opex_rate); oi.inputMode = 'decimal';
      const fitOi = () => { oi.style.width = Math.max(2, String(oi.value).length) + 0.6 + 'ch'; };
      fitOi(); oi.addEventListener('input', fitOi);
      oi.addEventListener('change', () => {
        const v = parseFloat(oi.value);
        if (!isNaN(v) && v >= 0 && v < 100) { live.opex_rate = v / 100; recalc(); }
      });
      oi.addEventListener('keydown', ev => { if (ev.key === 'Enter') oi.blur(); });
      const oiBox = assumeField(oi, false);
      T.opexNoteParts.forEach((part, i) => {
        if (i === 1) opexNote.appendChild(oiBox);
        opexNote.appendChild(document.createTextNode(part));
      });

      const noiRow = payRow(T.rowNoi, '~' + money(m.noi), null, 'assume');
      noiRow.firstChild.appendChild(opexNote);
      out.noi = noiRow.querySelector('.pv');
      box.appendChild(noiRow);

      const roiRow = payRow(T.rowRoi, '~' + pct(m.roi), T.rowRoiNote, 'assume');
      out.roi = roiRow.querySelector('.pv');
      box.appendChild(roiRow);
      s4.appendChild(box);

      const jg = jargon(T.jargonTitle, [
        [T.jgYield, T.jgYieldF(pct(m.gross_yield))],
        [T.jgNoi, T.jgNoiF(money(m.noi))],
        [T.jgCap, T.jgCapF(pct(m.cap_rate))],
        [T.jgRoi, T.jgRoiF(pct(m.roi))],
      ]);
      const jp = jg.querySelectorAll('.jp');
      out.jg = { noi: jp[1], cap: jp[2], roi: jp[3] };
      s4.appendChild(jg);
      s4.appendChild(h('div', 'caveat', T.rentCaveat));

      // 「以当前假设重算全部房源」那个按钮拿掉了:改条件本来就是在对话框和
      // 条件卡里做的事,这个按钮是同一件事的第二个入口,而且代价大得多
      // (重跑整张图 + 一次 LLM)。上面那两个字段做的是"这一套房如果按 X 算
      // 会怎样"的试算,那才是详情窗该干的事。
      s4.dataset.sec = 'rent'; d.appendChild(s4);
    }

    // ---- 五、买之前要留意的 ----
    const s5 = h('div', 'sec'); s5.appendChild(h('div', 'sec-title', T.sec5)); const rows = h('div', 'rows');
    const sz = m.school_zones || {};
    rows.appendChild(row(T.primaryZone, sz.primary || T.notInZone));
    rows.appendChild(row(T.secondaryZone, sz.secondary || T.notInZone));
    const pl = m.planning || {};
    if (pl.zone) {
      rows.appendChild(row(T.planningZone, pl.zone_label || pl.zone));
      const ovs = pl.overlays || [];
      rows.appendChild(row(T.overlays, ovs.length ? ovs.map(o => o.code + ' ' + o.label).join(state.lang === 'en' ? ', ' : '、') : T.none,
        ovs.some(o => o.effect === 'risk' || o.effect === 'build') ? 'warn' : ''));
      if (pl.nearby_total) rows.appendChild(row(T.nearbyRadius(pl.radius_m), T.nearbyLots(pl.nearby_total, pl.nearby_low, pl.nearby_high, pl.nearby_open)));
    } else rows.appendChild(row(T.planningZone, T.noZoneData));
    if (m.crime) rows.appendChild(row(T.crimeLabel(m.crime.lga), T.crimeRate(Math.round(m.crime.rate_per_100k).toLocaleString('en-AU')), '', T.crimeScope + (meta.crime_year ? ' · ' + meta.crime_year : '')));
    s5.appendChild(rows);
    s5.appendChild(h('div', 'caveat', T.sec5Caveat));
    s5.dataset.sec = 'watch'; d.appendChild(s5);

    // ---- 数字的来源 ----
    // 图例挪到最后:它原来在所有数字之前,读者还没见过任何一个符号,
    // 先被要求记三种记号 —— 那时候它是负担,看完再读它才是解释。
    const lgw = h('div', 'sec');
    lgw.appendChild(h('div', 'sec-title', T.legendTitle));
    const lg = h('div', 'legend');
    lg.innerHTML = '<span>' + DOT + ' <i></i></span>'
      + '<span><b style="color:#8A8A8E">~</b> <i></i></span>'
      + '<span style="color:#226B8E">' + DIAMOND + '<i style="color:#6E6E73"> </i></span>';
    const li = lg.querySelectorAll('i');
    li[0].textContent = ' ' + T.legendMeasured;
    li[1].textContent = ' ' + T.legendAssume;
    li[2].textContent = ' ' + T.legendModel;
    lgw.dataset.sec = 'legend'; lgw.appendChild(lg); d.appendChild(lgw);

    // 底部那个「可调假设」框拆掉了 —— 它的两个输入框已经搬到它们各自
    // 影响的那一行旁边(段三的杂费、段四的运营支出比例)。留着就是同一件事
    // 有两个入口,而且下面那个还离得更远。

  }

  // 遮罩/浮层改用 is-open —— .hidden 是 display:none,display 不可过渡,
  // 用它开关等于放弃一切淡入淡出。
  // ---------------------------------------------------------------- 并排对比
  // 最多 3 套并排。每一列就是一份完整详情(renderDetailInto, compact),按段落放进同一个网格:
  // 「价格区间」挨着「价格区间」,整体只有一根滚动条。顶部一行关键数字,只对方向没有争议的三项
  // (毛回报越高越好、印花税越低越好、离火车站越近越好)标「最优」;房价高低因人而异,不标。
  // 数字的来源标记与单开详情一致 —— 列里画的就是同一份详情,不另起对比口径。
  const CMP_MAX = 3;
  const CMP_SECS = ['head', 'price', 'living', 'cost', 'rent', 'watch'];
  const sameId = (a, b) => String(a) === String(b);

  /** 可展示的详情数据:当前结果里有就用它(本轮刚算的),否则向后端按编号现算。 */
  async function metricFor(id) {
    const hit = [...(resultView().metrics || []), ...(state.compare || []), state.detailMetric].find(x => x && sameId(x.id, id));
    if (hit) return hit;
    const r = await fetch(`/api/property/${id}?lang=${state.lang}`, { credentials: 'same-origin' });
    if (!r.ok) throw new Error(String(r.status));
    return (await r.json()).metric;
  }

  /** announce:从收藏多选打开时广播「打开」(令牌 compare),关闭后才会回收藏;
   *  从单开详情里「+ 并排对比」扩成并排时不广播,沿用原来的令牌。 */
  function openCompare(list, { announce = false } = {}) {
    state.compare = list.slice(0, CMP_MAX);
    if (announce) state.detailToken = 'compare';
    state.selectedId = state.compare[0] ? state.compare[0].id : null;
    for (const c of document.querySelectorAll('.card')) c.classList.toggle('selected', state.compare.some(x => sameId(x.id, c.dataset.id)));
    clearMeasure();
    const wasOpen = $('#detail').classList.contains('open');
    renderCompare();
    if (!wasOpen) openSheet();
    if (announce) window.dispatchEvent(new CustomEvent('nw:detail', { detail: { open: true, id: 'compare' } }));
  }

  function compareButton(label) {
    const b = h('button', 'cmp-add', label); b.type = 'button';
    b.setAttribute('aria-haspopup', 'dialog'); b.setAttribute('aria-expanded', 'false');
    b.addEventListener('click', ev => { ev.stopPropagation(); togglePicker(b); });
    return b;
  }

  /** 关键数字:同一组字段,各列一格。best:方向没有争议的才标。 */
  function summaryCells(list) {
    const rows = [
      { k: T.askingPrice, v: m => m.price, f: money },
      { k: T.modelEstimate, v: m => m.predicted_price, f: money, cls: 'model' },
      { k: T.cmpYield, v: m => m.gross_yield, f: v => pct(v), best: 'max' },
      { k: T.rowDuty, v: m => m.stamp_duty, f: money, best: 'min' },
      { k: kindZh('train_station'), v: m => (m.amenities || {}).train_station?.distance_m, f: dist, best: 'min' },
    ];
    const cells = list.map(() => { const c = h('div', 'sec cmp-cell cmp-sum'); c.dataset.sec = 'summary'; return c; });
    for (const r of rows) {
      const vals = list.map(m => { const v = r.v(m); return typeof v === 'number' && isFinite(v) ? v : null; });
      const known = vals.filter(v => v != null);
      const pick = r.best && list.length > 1 && known.length > 1 && new Set(known).size > 1
        ? (r.best === 'max' ? Math.max(...known) : Math.min(...known)) : null;
      vals.forEach((v, i) => {
        const e = kv(r.k, v == null ? '—' : r.f(v), r.cls);
        if (pick != null && v === pick) { e.classList.add('best'); e.querySelector('.v').appendChild(h('span', 'best-tag', T.cmpBest)); }
        cells[i].appendChild(e);
      });
    }
    return cells;
  }

  /** 「只看不同」:同一段里标签相同、各列数值也相同的行收起来(可编辑的假设行永远保留)。 */
  function markSame(groups) {
    const rowsOf = cell => [...cell.querySelectorAll('.kv, .pay:not(.editable), .row')].map(r => ({
      r, k: (r.querySelector('.k, .pk') || {}).textContent?.trim(), v: (r.querySelector('.v, .pv') || {}).textContent?.trim() }));
    for (const cells of groups) {
      if (cells.some(c => !c || c.classList.contains('cmp-missing'))) continue;
      const cols = cells.map(rowsOf);
      for (const { r, k, v } of cols[0]) {
        if (!k) continue;
        const peers = cols.slice(1).map(rows => rows.find(x => x.k === k));
        if (peers.every(p => p && p.v === v)) { r.classList.add('same'); peers.forEach(p => p.r.classList.add('same')); }
      }
      // 整段都一样:只看不同时这一段只剩标题,标注「各项相同」,免得看起来像数据丢了
      const rows0 = cols[0];
      if (rows0.length && rows0.every(x => x.r.classList.contains('same')) && !cells[0].querySelector('.plain, .evbox')) {
        cells.forEach(c => { c.classList.add('all-same'); c.querySelector('.sec-title')?.setAttribute('data-same-note', T.cmpAllSame); });
      }
    }
  }

  function renderCompare() {
    const d = $('#detail'), list = state.compare;
    closePicker();
    if (list.length <= 1) {                               // 只剩一套:变回普通详情,来源令牌不变
      if (list.length) openDetail(list[0], { keepToken: true }); else closeSheet();
      return;
    }
    const top = d.scrollTop;
    d.innerHTML = ''; d.classList.add('compare'); d.style.setProperty('--n', list.length);
    d.appendChild(h('div', 'grabber'));
    const bar = h('div', 'd-bar cmp-bar');
    bar.appendChild(h('div', 'd-bar-title', T.cmpTitle(list.length)));
    const diff = h('button', 'cmp-diff' + (state.cmpDiff ? ' on' : ''), T.cmpDiffOnly); diff.type = 'button';
    diff.setAttribute('aria-pressed', String(!!state.cmpDiff));
    diff.addEventListener('click', () => { state.cmpDiff = !state.cmpDiff; renderCompare(); });
    bar.appendChild(diff);
    if (list.length < CMP_MAX) bar.appendChild(compareButton(T.cmpAddMore));
    const close = h('button', 'd-close'); close.type = 'button'; close.title = T.closeEsc;
    close.setAttribute('aria-label', T.close); close.innerHTML = X;
    close.addEventListener('click', () => closeSheet({ user: true }));
    bar.appendChild(close); d.appendChild(bar);
    makeDraggable(bar);

    const grid = h('div', 'cmp-grid' + (state.cmpDiff ? ' diff-only' : ''));
    const cols = list.map(m => { const c = document.createElement('div'); renderDetailInto(c, m, { compact: true }); return c; });
    list.forEach(m => {                                   // 每列固定表头:地址 + 移出对比
      const hd = h('div', 'cmp-colhead');
      hd.appendChild(h('div', 'cmp-coladdr', (m.suburb || '') + ' · ' + (m.address || '')));
      const rm = h('button', 'cmp-remove'); rm.type = 'button'; rm.innerHTML = X;
      rm.title = T.cmpRemove; rm.setAttribute('aria-label', T.cmpRemove + ':' + (m.address || ''));
      rm.addEventListener('click', () => { state.compare = state.compare.filter(x => x !== m); renderCompare(); });
      hd.appendChild(rm); grid.appendChild(hd);
    });
    summaryCells(list).forEach(c => grid.appendChild(c));
    const groups = [];
    for (const key of CMP_SECS) {                         // 按段落对齐;某套缺这一段就放占位格
      const cells = cols.map(c => c.querySelector(`:scope > [data-sec="${key}"]`));
      if (cells.every(x => !x)) continue;
      const placed = cells.map(x => x || h('div', 'sec cmp-missing', T.cmpMissing));
      placed.forEach(x => { x.classList.add('cmp-cell'); grid.appendChild(x); });
      groups.push(placed);
    }
    markSame(groups);
    const legend = cols[0].querySelector(':scope > [data-sec="legend"]');
    if (legend) { legend.classList.add('cmp-span'); grid.appendChild(legend); }
    d.appendChild(grid);
    d.scrollTop = top;
  }

  // ---- 「选一套加入」:当前结果 + 我的收藏,已在对比里的不列 ----
  let picker = null;
  function closePicker() {
    if (!picker) return;
    picker.el.remove(); picker.btn.setAttribute('aria-expanded', 'false'); picker = null;
    document.removeEventListener('pointerdown', pickerOutside, true);
  }
  function pickerOutside(ev) { if (picker && !picker.el.contains(ev.target) && ev.target !== picker.btn) closePicker(); }
  function togglePicker(btn) {
    if (picker) { const same = picker.btn === btn; closePicker(); if (same) return; }
    const open = state.compare.length ? state.compare : [state.detailMetric].filter(Boolean);
    const taken = id => open.some(x => sameId(x.id, id));
    const el = h('div', 'cmp-picker'); el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', T.cmpPickTitle);
    el.appendChild(h('div', 'cmp-pick-title', T.cmpPickTitle));
    const groups = [
      [T.cmpFromResults, (resultView().metrics || []).filter(m => !taken(m.id)).map(m => ({ id: m.id, suburb: m.suburb, address: m.address, price: m.price }))],
      [T.cmpFromFavs, ((window.nwFav && window.nwFav.list && window.nwFav.list()) || []).filter(it => !taken(it.id))
        .map(it => ({ id: it.id, suburb: it.snapshot.suburb, address: it.snapshot.address, price: it.snapshot.price }))],
    ];
    let any = false;
    for (const [title, items] of groups) {
      const seen = new Set(), uniq = items.filter(x => !seen.has(String(x.id)) && seen.add(String(x.id)));
      if (!uniq.length) continue;
      any = true;
      el.appendChild(h('div', 'cmp-pick-group', title));
      for (const it of uniq) {
        const b = h('button', 'cmp-pick-item'); b.type = 'button';
        b.appendChild(h('span', 'cmp-pick-addr', (it.suburb || '') + ' · ' + (it.address || '')));
        b.appendChild(h('span', 'cmp-pick-price', it.price != null ? money(it.price) : ''));
        b.addEventListener('click', async () => {
          b.disabled = true; b.classList.add('busy');
          try {
            const m = await metricFor(it.id);
            closePicker();
            openCompare([...open, m]);
          } catch (_) { b.disabled = false; b.classList.remove('busy'); b.title = T.cmpFailed; b.classList.add('failed'); }
        });
        el.appendChild(b);
      }
    }
    if (!any) el.appendChild(h('div', 'cmp-pick-empty', T.cmpNone));
    const d = $('#detail'); d.appendChild(el);
    const br = btn.getBoundingClientRect(), dr = d.getBoundingClientRect();
    el.style.top = (br.bottom - dr.top + d.scrollTop + 6) + 'px';
    el.style.right = Math.max(8, dr.right - br.right) + 'px';
    btn.setAttribute('aria-expanded', 'true');
    picker = { el, btn };
    setTimeout(() => document.addEventListener('pointerdown', pickerOutside, true), 0);
  }

  /** 收藏夹多选「并排打开」:按编号取数据(当前结果里有就直接用),凑齐后一起打开。 */
  async function compareIds(ids) {
    const list = [];
    for (const id of ids.slice(0, CMP_MAX)) {
      try { list.push(await metricFor(id)); }
      catch (err) { console.warn('compare: skipped', id, err); }   // 取不到的跳过,但留下记录,代码错误不能被悄悄吞掉
    }
    if (list.length >= 2) openCompare(list, { announce: true });
    else if (list.length === 1) openDetail(list[0]);
    return list.length;
  }

  function openSheet() { const d = $('#detail'); d.classList.add('open'); if (detailIsSheet()) { $('#backdrop').classList.add('is-open'); $('#backdrop').onclick = () => closeSheet({ user: true }); } d.scrollTop = 0; }
  /** user:true 只给「用户主动关掉详情」(×、Esc、点遮罩)。新对话、回首页、换一批这类
   *  程序顺手收起不算 —— 收藏抽屉只在前者之后重新打开(见 favorites.js)。 */
  function closeSheet({ user = false } = {}) {
    const wasOpen = $('#detail').classList.contains('open');
    $('#detail').classList.remove('open'); $('#backdrop').classList.remove('is-open');
    closePicker();
    if (wasOpen) window.dispatchEvent(new CustomEvent('nw:detail', { detail: { open: false, id: state.detailToken ?? state.selectedId, user: user === true } }));
    // 窗子一让开,整幅地图就腾出来了 —— 把测算的连线按全宽重新取一次景。
    // 等 400ms 是让滑出动画走完,不然算的还是被盖住时的可视区域。
    if (state.measureBounds && state.map) {
      clearTimeout(state.focusTimer);
      state.focusTimer = setTimeout(() => {
        if (state.measureBounds && state.map) fitAvoidingPanel(state.map, state.measureBounds);
      }, 400);
    }
  }

  // ---------------------------------------------------------------- 首屏:玻璃建筑 + 嵌入词条

  // 词云的生命周期与 CSS/rAF 时钟无关。仅在淡入淡出期间以约 30fps 改 opacity/transform,
  // 计时到点直接恢复可见基线;预览器暂停 CSS 动画也不会变成静止或永久隐藏的卡片。
  const drift = { cycle: null, timers: new Set(), paused: false, lastSlot: -1, bag: [], size: '', anchors: [] };
  const driftNarrow = matchMedia('(max-width: 599px)');
  const driftReduced = matchMedia('(prefers-reduced-motion: reduce)');
  const driftPointer = matchMedia('(hover: hover) and (pointer: fine)');

  function driftLater(fn, delay) {
    const id = setTimeout(() => { drift.timers.delete(id); fn(); }, delay);
    drift.timers.add(id);
  }

  function stopDrift() {
    clearTimeout(drift.cycle);
    drift.cycle = null;
    drift.timers.forEach(clearTimeout);
    drift.timers.clear();
    document.querySelectorAll('.drift-slot').forEach(slot => {
      slot.style.opacity = '';
      slot.style.transform = '';
    });
  }

  function driftCanRotate() {
    const host = $('#driftfield');
    // 宽屏首屏换成城市沙盘后(showroom/showroom.mjs),SVG 词条层被隐藏,不再轮换
    if ($('#app').dataset.showroom === 'ready' && matchMedia('(min-width: 900px)').matches) return false;
    return host && $('#app').dataset.stage === 'welcome' && !document.hidden &&
      !drift.paused && !(driftPointer.matches && host.querySelector('.drift-chip:hover')) &&
      !host.contains(document.activeElement) && !$('#input').value.trim();
  }

  function animateDrift(slot, entering, done = () => {}) {
    const reduced = driftReduced.matches;
    const duration = reduced ? 220 : entering ? 1200 : 900;
    const start = performance.now();
    function frame() {
      const t = Math.min(1, (performance.now() - start) / duration);
      slot.style.opacity = String(entering ? t : 1 - t);
      // 只做轻微上浮 + 缩放,始终不旋转;透明度匀速变化,避免一下闪走。
      const travel = entering ? Math.pow(1 - t, 3) : t * t * t;
      slot.style.transform = reduced ? '' :
        'translate3d(0,' + ((entering ? 8 : -5) * travel) + 'px,0) scale(' + (1 - .03 * travel) + ')';
      if (t < 1) driftLater(frame, 32);
      else {
        if (entering) { slot.style.opacity = ''; slot.style.transform = ''; }
        done();
      }
    }
    frame();
  }

  function shuffleDrift(items) {
    const result = items.slice();
    for (let i = result.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  }

  /** 词条是嵌在玻璃面上的两行标注:第一段一行,其余一行(「100万内 / 近车站 · 3房」)。 */
  function fillDriftSlot(slot, text) {
    slot.dataset.query = text;
    const btn = h('button', 'drift-chip');
    btn.type = 'button';
    btn.setAttribute('aria-label', text);
    const parts = text.split(' · ');
    btn.appendChild(h('span', 'dc-l1', parts[0]));
    if (parts.length > 1) btn.appendChild(h('span', 'dc-l2', parts.slice(1).join(' · ')));
    btn.addEventListener('click', () => send(text));
    slot.replaceChildren(btn);
  }

  function driftRect(slot) {
    return { x: slot.offsetLeft, y: slot.offsetTop, w: slot.offsetWidth, h: slot.offsetHeight };
  }

  /** 带 data-drift-avoid 的元素(标题区、输入栏、轮换开关)词条不许盖住。换算到 #driftfield 坐标系。 */
  function driftAvoidRects(host) {
    const base = host.getBoundingClientRect();
    return Array.from(document.querySelectorAll('#app [data-drift-avoid]'))
      .filter(el => el.offsetParent !== null)
      .map(el => el.getBoundingClientRect())
      .map(r => ({ x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height }));
  }

  // ---- 玻璃建筑:等轴测投影,程序生成。固定种子,所以每次打开是同一座"城",只是词条在换。
  function cityRandom(seed) {
    return () => {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  const CITY = (() => {
    const rnd = cityRandom(20260914), towers = [];
    for (let gy = 0; gy < 7; gy++) for (let gx = 0; gx < 7; gx++) {
      if (rnd() < .4) continue;
      // 一半是薄玻璃幕墙片(fin),一半是方塔;越靠后越高,形成向右上抬升的天际线
      const fin = rnd() < .5, back = Math.max(0, 10 - gx - gy);
      towers.push({
        x: gx + rnd() * .25, y: gy + rnd() * .25,
        w: fin ? .16 + rnd() * .12 : .55 + rnd() * .3,
        d: fin ? .8 + rnd() * .8 : .55 + rnd() * .3,
        h: 1.6 + rnd() * 2.2 + back * (.75 + rnd() * .35),
        lit: rnd() < .24,
      });
    }
    towers.sort((a, b) => (a.x + a.w / 2 + a.y + a.d / 2) - (b.x + b.w / 2 + b.y + b.d / 2));
    return towers;
  })();

  const ISO_C = Math.cos(Math.PI / 6), ISO_S = .5;

  /** 画城并返回词条可停靠的锚点(各塔可见立面上的点)。 */
  function drawCity() {
    const svg = $('#city-svg'), host = $('#driftfield');
    if (!svg || !host || !host.clientWidth) return;
    const W = host.clientWidth, H = host.clientHeight, narrow = driftNarrow.matches;
    const iso = (x, y, z) => [(x - y) * ISO_C, (x + y) * ISO_S - z];
    let minX = Infinity, maxX = -Infinity, maxY = -Infinity;
    CITY.forEach(t => [[t.x, t.y], [t.x + t.w, t.y], [t.x + t.w, t.y + t.d], [t.x, t.y + t.d]].forEach(([x, y]) => {
      const [sx, sy] = iso(x, y, 0);
      minX = Math.min(minX, sx); maxX = Math.max(maxX, sx); maxY = Math.max(maxY, sy);
    }));
    // 按宽度铺满并略微出血,底边落在容器底部;太高的塔顶被上沿裁掉,读起来像"楼延伸出画面"
    const k = W * (narrow ? 1.02 : 1.08) / (maxX - minX);
    const tx = W * (narrow ? .5 : .56) - (minX + maxX) / 2 * k, ty = H * .97 - maxY * k;
    const P = (x, y, z) => { const [sx, sy] = iso(x, y, z); return [tx + sx * k, ty + sy * k]; };
    const pts = arr => arr.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const line = (a, b, cls) => '<line class="' + cls + '" x1="' + a[0].toFixed(1) + '" y1="' + a[1].toFixed(1) +
      '" x2="' + b[0].toFixed(1) + '" y2="' + b[1].toFixed(1) + '"></line>';

    let out = '<defs>' +
      '<linearGradient id="cg-face" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".58"/>' +
        '<stop offset=".55" stop-color="#FFFFFF" stop-opacity=".22"/><stop offset="1" stop-color="#FBF7EF" stop-opacity=".06"/></linearGradient>' +
      '<linearGradient id="cg-side" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#DCD3C4" stop-opacity=".62"/>' +
        '<stop offset="1" stop-color="#D8CFBF" stop-opacity=".12"/></linearGradient>' +
      '<linearGradient id="cg-lit" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF6E6" stop-opacity=".7"/>' +
        '<stop offset=".5" stop-color="#F4DDB6" stop-opacity=".42"/><stop offset="1" stop-color="#EFD3A4" stop-opacity=".1"/></linearGradient>' +
      '<radialGradient id="cg-glow"><stop offset="0" stop-color="#F2D6A6" stop-opacity=".38"/>' +
        '<stop offset=".45" stop-color="#F3DFBF" stop-opacity=".16"/><stop offset="1" stop-color="#F5EBDD" stop-opacity="0"/></radialGradient>' +
      '<filter id="cf-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="' + (narrow ? 10 : 16) + '"/></filter>' +
      '<linearGradient id="cg-base" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#D9D1C3" stop-opacity="0"/>' +
        '<stop offset=".55" stop-color="#D6CDBD" stop-opacity=".2"/><stop offset="1" stop-color="#CFC5B3" stop-opacity=".34"/></linearGradient>' +
      '<linearGradient id="cg-mist" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F4F1EB" stop-opacity="0"/>' +
        '<stop offset="1" stop-color="#F4F1EB" stop-opacity=".92"/></linearGradient>' +
      '</defs>';
    // 底色:右下略深的暖灰,白玻璃才有东西可以"透";纯纸白底上玻璃会读成白盒子
    out += '<rect fill="url(#cg-base)" width="' + W + '" height="' + H + '"></rect>';
    // 光:一团很淡的暖光在城中偏后,外加两道柔化的竖向光带。强度刻意压低。
    out += '<ellipse fill="url(#cg-glow)" cx="' + (W * .5).toFixed(0) + '" cy="' + (H * .46).toFixed(0) +
      '" rx="' + (W * .46).toFixed(0) + '" ry="' + (H * .5).toFixed(0) + '"></ellipse>';
    const anchors = [];
    CITY.forEach((t, order) => {
      const A0 = P(t.x, t.y, 0), B0 = P(t.x + t.w, t.y, 0), C0 = P(t.x + t.w, t.y + t.d, 0), D0 = P(t.x, t.y + t.d, 0);
      const A1 = P(t.x, t.y, t.h), B1 = P(t.x + t.w, t.y, t.h), C1 = P(t.x + t.w, t.y + t.d, t.h), D1 = P(t.x, t.y + t.d, t.h);
      // 空气透视:越靠后越淡
      out += '<g class="tw' + (t.lit ? ' lit' : '') + '" opacity="' + (.55 + .45 * order / (CITY.length - 1)).toFixed(2) + '">';
      // 背面棱线先画、很淡 —— 透过玻璃看得见后面的结构,这是"玻璃"而不是"白盒子"的关键
      out += line(A0, A1, 'e-back') + line(A1, B1, 'e-back') + line(A1, D1, 'e-back');
      out += '<polygon class="f-left" fill="url(#' + (t.lit ? 'cg-lit' : 'cg-face') + ')" points="' + pts([D0, C0, C1, D1]) + '"></polygon>';
      out += '<polygon class="f-right" fill="url(#cg-side)" points="' + pts([B0, C0, C1, B1]) + '"></polygon>';
      out += '<polygon class="f-top" points="' + pts([A1, B1, C1, D1]) + '"></polygon>';
      // 宽面上的一道斜向反光带(u 沿面宽,v 沿高度)
      const faceW = Math.hypot(C0[0] - D0[0], C0[1] - D0[1]);
      const on = (u, v) => [D0[0] + (C0[0] - D0[0]) * u, D0[1] + (C0[1] - D0[1]) * u + (D1[1] - D0[1]) * v];
      if (faceW > 26) {
        const u = .08 + ((t.x * 7 + t.y * 3) % 1) * .4;
        out += '<polygon class="refl" points="' + pts([on(u, .18), on(Math.min(1, u + .14), .18),
          on(Math.min(1, u + .44), .92), on(Math.min(1, u + .3), .92)]) + '"></polygon>';
      }
      // 竖向窗棂,只画在宽的那一面
      const n = Math.min(9, Math.floor(faceW / 11));
      for (let i = 1; i < n; i++) {
        const f = i / n, lerp = (a, b) => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
        out += line(lerp(D0, C0), lerp(D1, C1), 'mull');
      }
      // 玻璃板厚度:前棱内侧再压一条亮线,右立面紧挨前棱一条暗线
      const inset = (a, b, f) => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
      const th = Math.min(.12, 4 / Math.max(faceW, 1));
      out += line(inset(C0, D0, th), inset(C1, D1, th), 'e-inner');
      out += line(inset(C0, B0, .1), inset(C1, B1, .1), 'e-shade');
      out += line(B0, B1, 'e-side') + line(D0, D1, 'e-side') + line(C0, C1, 'e-front');
      out += '<polyline class="e-top" points="' + pts([D1, C1, B1]) + '"></polyline>';
      out += '</g>';
      // 锚点:左立面(宽面)与右立面中线上,从塔身中段到上段取三档
      [[D0, C0, D1, C1], [B0, C0, B1, C1]].forEach(([g0, g1, u0, u1]) => {
        [.42, .6, .78].forEach(zf => {
          const bx = (g0[0] + g1[0]) / 2, by = (g0[1] + g1[1]) / 2, ux = (u0[0] + u1[0]) / 2, uy = (u0[1] + u1[1]) / 2;
          anchors.push({ x: bx + (ux - bx) * zf, y: by + (uy - by) * zf });
        });
      });
    });
    out += '<rect class="shaft" filter="url(#cf-soft)" x="' + (W * .47).toFixed(0) + '" y="' + (H * .05).toFixed(0) +
      '" width="' + (narrow ? 10 : 18) + '" height="' + (H * .7).toFixed(0) + '"></rect>';
    out += '<rect class="shaft dim" filter="url(#cf-soft)" x="' + (W * .63).toFixed(0) + '" y="' + (H * .18).toFixed(0) +
      '" width="' + (narrow ? 8 : 12) + '" height="' + (H * .55).toFixed(0) + '"></rect>';
    // 底部薄雾,让楼脚化进纸面
    out += '<rect fill="url(#cg-mist)" y="' + (H * .72).toFixed(0) + '" width="' + W + '" height="' + (H * .28).toFixed(0) + '"></rect>';
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.innerHTML = out;
    drift.anchors = anchors;
  }

  /** 从玻璃立面锚点里抽一个放词条:整张卡片在容器内、不压别的词条、不压标题/输入栏,
   *  换位时离开原位足够远。锚点来自 drawCity,所以词条总是"长"在楼上。 */
  function findDriftPosition(slot, previous = null) {
    const host = $('#driftfield');
    const W = host.clientWidth, H = host.clientHeight, w = slot.offsetWidth, ht = slot.offsetHeight;
    const pad = 12, gap = driftNarrow.matches ? 10 : 16;
    const occupied = Array.from(host.children)
      .filter(other => other !== slot && other.dataset.placed === 'true').map(driftRect);
    const blocked = occupied.concat(driftAvoidRects(host));
    // 左侧 22% 是渐隐带,词条放进去会半透明、读不清
    const minX = driftNarrow.matches ? pad : W * .22;
    const candidates = [];
    for (const a of shuffleDrift(drift.anchors)) {
      const x = a.x - w * .35, y = a.y - ht / 2;
      if (x < minX || y < pad || x + w > W - pad || y + ht > H - pad) continue;
      if (blocked.some(r => x < r.x + r.w + gap && x + w + gap > r.x &&
        y < r.y + r.h + gap && y + ht + gap > r.y)) continue;
      if (previous && Math.hypot(x - previous.x, y - previous.y) < Math.min(90, W * .18)) continue;
      // 离已有词条越远分越高,避免几张挤在同一栋楼上
      const spread = occupied.length ? Math.min(...occupied.map(r =>
        Math.hypot((x + w / 2 - r.x - r.w / 2) / W, (y + ht / 2 - r.y - r.h / 2) / H))) : Math.random();
      candidates.push({ x, y, spread });
    }
    // 在分布最开的几个候选里抽签:既散开,又不是每次同一个位置
    candidates.sort((a, b) => b.spread - a.spread);
    return candidates[Math.floor(Math.random() * Math.min(6, candidates.length))] || null;
  }

  function placeDriftSlot(slot, position) {
    slot.style.left = Math.round(position.x) + 'px';
    slot.style.top = Math.round(position.y) + 'px';
    slot.dataset.placed = 'true';
  }

  function layoutDrift() {
    const host = $('#driftfield');
    if (!host.clientWidth) return;
    let slots = Array.from(host.children);
    let fitted = false;
    for (;;) {
      const largestFirst = slots.slice().sort((a, b) =>
        b.offsetWidth * b.offsetHeight - a.offsetWidth * a.offsetHeight);
      for (let attempt = 0; attempt < 12 && !fitted; attempt++) {
        slots.forEach(slot => { slot.dataset.placed = 'false'; });
        fitted = largestFirst.every(slot => {
          const position = findDriftPosition(slot);
          if (!position) return false;
          placeDriftSlot(slot, position);
          return true;
        });
      }
      if (fitted || !slots.length) break;
      // 楼面上放不下就少放一张,词回到待轮换的袋子里 —— 宁可少,不压标题、不压输入栏。
      const drop = slots.pop();
      drift.bag.push(drop.dataset.query);
      drop.remove();
    }
    drift.size = host.clientWidth + ':' + host.clientHeight;
  }

  function scheduleDrift() {
    clearTimeout(drift.cycle);
    drift.cycle = null;
    if (!driftCanRotate()) return;
    drift.cycle = setTimeout(rotateDrift, (driftReduced.matches ? 5000 : 1800) + Math.random() * 1400);
  }

  function rotateDrift() {
    drift.cycle = null;
    if (!driftCanRotate()) return;
    const slots = Array.from($('#driftfield').children);
    const visible = new Set(slots.map(slot => slot.dataset.query));
    drift.bag = drift.bag.filter(text => !visible.has(text));
    if (!drift.bag.length) drift.bag = shuffleDrift(T.chips.filter(text => !visible.has(text)));
    if (!drift.bag.length || !slots.length) return;
    const choices = slots.map((_, i) => i).filter(i => i !== drift.lastSlot || slots.length === 1);
    const index = choices[Math.floor(Math.random() * choices.length)];
    const slot = slots[index];
    const previous = driftRect(slot);
    animateDrift(slot, false, () => {
      driftLater(() => {
        if (!driftCanRotate()) { stopDrift(); return; }
        const oldText = slot.dataset.query;
        fillDriftSlot(slot, drift.bag[0]);
        const position = findDriftPosition(slot, previous);
        if (position) {
          placeDriftSlot(slot, position);
          drift.bag.shift();
        } else {
          // 空间不足时保留原卡片,不把新词硬塞进会重叠的位置。
          fillDriftSlot(slot, oldText);
        }
        drift.lastSlot = index;
        animateDrift(slot, true);
        scheduleDrift();
      }, driftReduced.matches ? 80 : 180);
    });
  }

  function renderDrift() {
    stopDrift();
    const host = $('#driftfield');
    if (!host) return;
    host.replaceChildren();
    if ($('#app').dataset.stage !== 'welcome') return;
    const pool = shuffleDrift(T.chips || []);
    const count = Math.min(driftNarrow.matches ? 3 : 4, pool.length);
    drift.bag = pool.slice(count);
    drift.lastSlot = -1;
    pool.slice(0, count).forEach(text => {
      const slot = h('div', 'drift-slot');
      fillDriftSlot(slot, text);
      host.appendChild(slot);
    });
    drawCity();
    layoutDrift();
    if (driftCanRotate()) Array.from(host.children).forEach(slot => animateDrift(slot, true));
    scheduleDrift();
  }

  function updateDriftControl() {
    const btn = $('#btn-drift');
    btn.textContent = drift.paused ? T.driftResume : T.driftPause;
    btn.setAttribute('aria-pressed', String(drift.paused));
  }

  driftNarrow.addEventListener('change', renderDrift);
  driftReduced.addEventListener('change', () => { stopDrift(); scheduleDrift(); });
  document.addEventListener('visibilitychange', () => { stopDrift(); scheduleDrift(); });
  new ResizeObserver(() => {
    const host = $('#driftfield');
    const size = host.clientWidth + ':' + host.clientHeight;
    if ($('#app').dataset.stage !== 'welcome' || size === drift.size) return;
    stopDrift();
    drawCity();
    layoutDrift();
    scheduleDrift();
  }).observe($('#driftfield'));

  // ---------------------------------------------------------------- 语言切换

  /** 静态节点上的字。index.html 里那几处不经过渲染函数,只能在这里刷。 */
  function applyStaticText() {
    document.documentElement.lang = T.htmlLang;
    document.title = T.title;
    const set = (sel, text) => { const e = $(sel); if (e) e.textContent = text; };
    set('.brand-name', T.brandName);
    $('#brand-home').setAttribute('aria-label', `${T.brand} · ${T.brandHome}`);
    $('#brand-home').title = T.brandHome;
    set('#btn-new', T.btnNew);
    // 文案表是本地常量(含 <br>),不是用户输入,可以走 innerHTML
    const wh = $('.welcome-h'); if (wh) wh.innerHTML = T.welcomeH;
    (T.rail || []).forEach((label, i) => set('#rail-' + (i + 1), label));
    set('#hero-foot', T.heroFoot);
    $('#city-btn').setAttribute('aria-label', T.cityPick); $('#city-btn').title = T.cityPick;
    $('.map-ctl').setAttribute('aria-label', T.mapControls);
    for (const [id, k] of [['#map-fit', 'mapFit'], ['#map-zin', 'zoomIn'], ['#map-zout', 'zoomOut']]) { $(id).setAttribute('aria-label', T[k]); $(id).title = T[k]; }
    if (!$('#city-menu').hidden) renderCityMenu();
    if ($('#map-count').textContent) setMapCount(resultView().metrics.length);
    set('#drift-label', T.driftLabel);
    updateDriftControl();
    const wp = $('.welcome-p'); if (wp) wp.innerHTML = T.welcomeP;
    renderDrift();
    const inp = $('#input'); if (inp) { inp.placeholder = $('#app').dataset.stage === 'working' ? T.workingPlaceholder : T.inputPlaceholder; inp.setAttribute('aria-label', inp.placeholder); }
    $('#chat').setAttribute('role', 'region'); $('#chat').setAttribute('aria-label', T.conversationAria); $('#chat').tabIndex = 0;
    $('#condition-dock').setAttribute('role', 'region'); $('#condition-dock').setAttribute('aria-label', T.filterAria);
    const followUps = $('#follow-ups'); followUps.replaceChildren(h('span', 'follow-label', T.tryFollowUp + ':'));
    for (const text of T.followUps) {
      const b = h('button', 'follow-up', text); b.type = 'button';
      // 只是填入草稿,由用户确认发送,不自动覆盖已经写好的需求。
      b.addEventListener('click', () => { inp.value = inp.value.trim() ? inp.value.trim() + (state.lang === 'zh' ? '，' : ', ') + text : text; inp.focus(); });
      followUps.appendChild(b);
    }
    const snd = $('#composer .send'); if (snd) snd.setAttribute('aria-label', T.sendAria);
    const det = $('#detail'); if (det) det.setAttribute('aria-label', T.detailAria);
    const lb = $('#btn-lang'); if (lb) { lb.textContent = T.switchTo; lb.title = T.switchTitle; }
  }

  /** 切语言。
   *
   *  界面上的字分三类,来源不同,所以处理方式也不同:
   *    ① 静态节点(欢迎语、按钮)—— applyStaticText 直接刷
   *    ② 渲染函数生成的(卡片、条件卡、详情窗)—— 换掉 L 再重画
   *    ③ 服务端给的标签(属性名、设施名、排序口径、规划分区)—— 重取一次 meta
   *
   *  还有第四类:**已经生成好的那段说明和排序口径**。它们是上一次 LLM 和
   *  上一次 rank 的产物,不重跑就换不了语言。所以有结果在屏幕上时,这里会
   *  顺带重跑一次 refine —— 参数原样不动,只是让后端用新语言把说明和口径重写一遍。
   *  不这么做的话,英文界面上会挂着一段中文说明,那比不给切换还难看。
   */
  async function setLang(lang) {
    if (lang === state.lang || state.running) return;
    returnToLatest();
    state.lang = lang;
    T = window.I18N[lang] || window.I18N.zh;
    try { localStorage.setItem('lang', lang); } catch (_) { /* 隐私模式下会抛,不影响功能 */ }
    applyStaticText();
    window.dispatchEvent(new CustomEvent('nw:lang', { detail: lang }));   // 首屏沙盘的信息牌跟着换语言
    state.meta = await fetch('/api/meta?lang=' + lang).then(r => r.json());
    if (state.params) renderConditions();
    if (state.metrics.length) renderResults(); else renderResultsHead();
    // 对话里已有的文字先原样留着 —— 下面这一趟回来会把说明换成新语言。
    if (state.params && state.metrics.length) refine(state.params, T.statusRefine);
  }

  // ---------------------------------------------------------------- 启动
  /** meta(所有中文名与口径)到位的信号。渲染离不开它,但监听器不该等它 ——
   *  监听器挂在 await 后面的话,首屏那几百毫秒里点示例、按回车全都掉进空里,
   *  而且一声不响。实测点得中。 */
  let metaReady = null;

  async function init() {
    // 上次选的语言。读不到就按中文 —— 这是这个项目的母语,也是数据的语言。
    try { state.lang = localStorage.getItem('lang') === 'en' ? 'en' : 'zh'; } catch (_) { /* 忽略 */ }
    T = window.I18N[state.lang];
    initMapPanel();
    applyStaticText();
    metaReady = fetch('/api/meta?lang=' + state.lang).then(r => r.json()).then(j => { state.meta = j; });
    newThread();
    $('#composer').addEventListener('submit', ev => { ev.preventDefault(); const t = $('#input').value.trim(); if (!t) return; $('#input').value = ''; send(t); });
    // 首屏沙盘信息牌:点击即按该问句搜索(与首屏词条同一条路径)
    window.addEventListener('nw:query', e => { if (state.running || !e.detail) return; $('#input').value = ''; send(e.detail); });
    window.addEventListener('nw:showroom', stopDrift);
    $('#btn-new').addEventListener('click', resetAll);
    $('#brand-home').addEventListener('click', () => { if ($('#app').dataset.stage !== 'welcome') resetAll(); });
    // 收藏夹(favorites.js)打开任意一套的详情:数据由 /api/property/{id} 现算,与搜索结果同一口径
    window.nwOpenDetail = m => openDetail(m);
    window.nwCompareIds = compareIds;                 // 收藏夹多选「并排打开」
    $('#btn-lang').addEventListener('click', () => setLang(state.lang === 'zh' ? 'en' : 'zh'));
    $('#btn-drift').addEventListener('click', () => {
      drift.paused = !drift.paused;
      updateDriftControl();
      stopDrift();
      scheduleDrift();
    });
    const driftHost = $('#driftfield');
    driftHost.addEventListener('pointerover', e => {
      if (driftPointer.matches && e.target.closest('.drift-chip')) stopDrift();
    });
    driftHost.addEventListener('pointerout', e => {
      if (driftPointer.matches && e.target.closest('.drift-chip') &&
        !e.target.closest('.drift-chip').contains(e.relatedTarget)) scheduleDrift();
    });
    driftHost.addEventListener('focusin', stopDrift);
    driftHost.addEventListener('focusout', () => driftLater(scheduleDrift, 0));
    $('#input').addEventListener('input', () => { stopDrift(); scheduleDrift(); });
    document.fonts.ready.then(() => {
      if ($('#app').dataset.stage !== 'welcome') return;
      stopDrift();
      layoutDrift();
      scheduleDrift();
    });
    // Esc 现在任何宽度都能关详情 —— 它已经是覆盖层了,窄屏抽屉、宽屏右侧滑出,
    // 两种都需要一个键盘出口
    document.addEventListener('keydown', ev => { if (ev.key !== 'Escape') return; if (closeCityMenu()) return; if (picker) { closePicker(); return; } closePopover(); closeSheet({ user: true }); });
    await metaReady;
  }
  init();
})();
