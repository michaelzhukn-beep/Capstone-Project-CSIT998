// 实地跑一次真实问答，把 SSE 事件和 metric 字段原样抓下来。
// 这一步是为了让 lab.js 接的字段名有依据，而不是猜。
const fs = require('fs');
const OUT = [];
const log = (...a) => { OUT.push(a.join(' ')); };

(async () => {
  const meta = await (await fetch('http://127.0.0.1:8000/api/meta')).json();
  log('=== META KEYS ===');
  log(Object.keys(meta).join(', '));
  log('\n=== meta.sort_labels ===');
  log(JSON.stringify(meta.sort_labels, null, 1).slice(0, 1200));
  log('\n=== meta.attributes (前 20) ===');
  log(Object.entries(meta.attributes).slice(0, 20).map(([k, v]) => k + '=' + v).join(', '));
  log('\n=== meta.evidence_labels (前 20) ===');
  log(Object.entries(meta.evidence_labels || {}).slice(0, 20).map(([k, v]) => k + '=' + JSON.stringify(v)).join('\n'));
  log('\n=== meta 其余键的类型 ===');
  for (const [k, v] of Object.entries(meta)) {
    log('  ' + k + ' : ' + (Array.isArray(v) ? 'array[' + v.length + ']' : typeof v));
  }

  const thread = 'lab-probe-' + Date.now();
  const body = JSON.stringify({ thread_id: thread, message: '100 万以内、离火车站近的三房' });
  const r = await fetch('http://127.0.0.1:8000/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body
  });
  log('\n=== SSE 事件序列 (event 名 + data 顶层键) ===');
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  let firstMetric = null;
  let evCount = 0;
  const t0 = Date.now();
  while (true) {
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
      let obj = null; try { obj = JSON.parse(data); } catch {}
      evCount++;
      const keys = obj && typeof obj === 'object' ? Object.keys(obj) : [];
      log(`  +${String(Date.now() - t0).padStart(5)}ms  ${ev.padEnd(9)} keys=[${keys.join(',')}]` + (ev === 'token' ? ' len=' + (obj && obj.t || '').length : ''));
      if (ev === 'results' && obj && obj.metrics && obj.metrics.length && !firstMetric) {
        firstMetric = obj.metrics[0];
        log('\n=== 第 1 套 metric 全文 ===');
        log(JSON.stringify(firstMetric, null, 1));
      }
      if (ev === 'ranking' && obj) log('       ranking=' + (obj.ranking || '').replace(/\n/g, ' | ') + '  count=' + obj.count);
      if (ev === 'params' && obj) {
        log('\n=== params 全文 ===');
        log(JSON.stringify(obj.params, null, 1));
        log('  intent=' + obj.intent);
      }
    }
  }
  log('\n总事件数 ' + evCount + '，总耗时 ' + (Date.now() - t0) + 'ms');
  fs.writeFileSync('D:/projects/Capstone-Project-CSIT998/_ui-lab/_probe_out.txt', OUT.join('\n'), 'utf8');
  console.log('written, events=' + evCount);
})();
