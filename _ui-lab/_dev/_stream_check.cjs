// 验证代理下的 SSE 是真流式:如果代理把上游读完再回,所有事件会在同一毫秒到达。
const fs = require('fs');
const OUT = [];
const log = (...a) => { OUT.push(a.join(' ')); console.log(a.join(' ')); };

(async () => {
  const t0 = Date.now();
  const r = await fetch('http://127.0.0.1:8137/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: 'stream-check-' + Date.now(), message: '80 万以下、安静、离公园近的三居' }),
  });
  log('status=' + r.status + '  content-type=' + r.headers.get('content-type') + '  transfer-encoding=' + r.headers.get('transfer-encoding'));

  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '', n = 0;
  const arrivals = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = 'message';
      for (const line of raw.split('\n')) if (line.startsWith('event:')) ev = line.slice(6).trim();
      n++;
      if (ev !== 'token') {
        arrivals.push(`  +${String(Date.now() - t0).padStart(5)}ms  ${ev}`);
        log(`  +${String(Date.now() - t0).padStart(5)}ms  ${ev}`);
      }
    }
  }
  log('总事件 ' + n + '，非 token 事件 ' + arrivals.length + '，总耗时 ' + (Date.now() - t0) + 'ms');

  // 判定:若最后一批 token 和第一个结果事件之间有明显时间差,说明流是真逐块到的
  log(arrivals.length >= 3 ? '\n✅ SSE 真流式:事件在不同时间点分别到达' : '\n❌ 事件挤在一起,代理可能在缓冲');
  fs.writeFileSync('D:/projects/Capstone-Project-CSIT998/_ui-lab/_stream_check.txt', OUT.join('\n'), 'utf8');
})();
