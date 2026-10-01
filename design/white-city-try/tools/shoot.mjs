// Headless GPU Chrome via CDP:打开页面,等 #viewport[data-loaded=true],截图。
// 用法:node shoot.mjs <url> <out.png> [x,y,w,h,scale] [readyExprMillis]
// 环境变量:CHROME_PORT(默认 9560)、EXPR(截图前求值并打印的表达式)、SHOT_BG(页面背景色)
import { writeFileSync } from 'node:fs';

const [url, out, crop, waitReady] = process.argv.slice(2);
const port = Number(process.env.CHROME_PORT || 9560);
const sleep = ms => new Promise(r => setTimeout(r, ms));

let ws;
let targetId;
for (let i = 0; i < 60; i++) {
  try {
    const p = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
    if (p?.webSocketDebuggerUrl) { ws = new WebSocket(p.webSocketDebuggerUrl); targetId = p.id; break; }
  } catch {}
  await sleep(300);
}
if (!ws) { console.error('NO CHROME on port ' + port); process.exit(3); }

await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('ws error')); });

let id = 0; const pending = new Map(); const logs = [];
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === 'Runtime.consoleAPICalled') logs.push(m.params.args.map(a => a.value ?? a.description).join(' '));
  if (m.method === 'Runtime.exceptionThrown') logs.push('EXC ' + JSON.stringify(m.params.exceptionDetails).slice(0, 500));
};
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });

await send('Runtime.enable');
await send('Page.enable');
await send('Network.enable');
await send('Network.setCacheDisabled', { cacheDisabled: true });
await send('Emulation.setDeviceMetricsOverride', { width: 2200, height: 1500, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url });

let state = 'none';
const spins = Number(waitReady || 240);
for (let i = 0; i < spins; i++) {
  const r = await send('Runtime.evaluate', { expression: `(() => { const v=document.querySelector('#viewport'); return v ? v.dataset.loaded + '|' + (v.dataset.frames||0) : 'none'; })()`, returnByValue: true });
  state = r.result?.result?.value ?? 'none';
  if (String(state).startsWith('true') || String(state).startsWith('error')) break;
  await sleep(1000);
}
await sleep(2500);

const extra = await send('Runtime.evaluate', { expression: process.env.EXPR || 'JSON.stringify(window.__v23 || {})', returnByValue: true });
if (process.env.SHOT_BG) {
  await send('Runtime.evaluate', { expression: `(() => { const c=${JSON.stringify(process.env.SHOT_BG)}; for (const sel of ['html','body','#workspace']) { const e=document.querySelector(sel); if(e){ e.style.background=c; e.style.backgroundImage='none'; } } return 'ok'; })()`, returnByValue: true });
  await sleep(300);
}
let clip;
if (crop === 'auto') {
  // 自动裁到 #viewport 的实际位置与大小,画面尺寸与 CSS 解耦
  const r = await send('Runtime.evaluate', { expression: `(() => { const v=document.querySelector('#viewport'); if(!v) return null; const b=v.getBoundingClientRect(); return [b.x,b.y,b.width,b.height].map(n=>Math.round(n)).join(','); })()`, returnByValue: true });
  const v = String(r.result?.result?.value || '');
  if (v) { const [x, y, w, h] = v.split(',').map(Number); clip = { x, y, width: w, height: h, scale: 1 }; console.log('AUTOCROP', v); }
} else if (crop) { const [x, y, w, h, s] = crop.split(',').map(Number); clip = { x, y, width: w, height: h, scale: s || 1 }; }
const shot = await send('Page.captureScreenshot', { format: 'png', ...(clip ? { clip } : {}), captureBeyondViewport: false });
if (!shot?.result?.data) { console.error('NO SHOT', JSON.stringify(shot).slice(0, 400)); process.exit(4); }
writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
console.log('STATE', state);
console.log('EXTRA', String(extra.result?.result?.value ?? '').slice(0, 2000));
if (logs.length) console.log('LOGS', logs.slice(-10).join('\n'));
if (targetId) await fetch(`http://127.0.0.1:${port}/json/close/${targetId}`).catch(() => {});
try { ws.close(); } catch {}
// 直接 process.exit 会撞上 node 的 UV_HANDLE_CLOSING 断言(退出码 1),让事件循环自然结束
setTimeout(() => process.exit(0), 200).unref();
