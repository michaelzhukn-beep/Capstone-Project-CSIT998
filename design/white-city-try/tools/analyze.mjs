// 无依赖 PNG(8bit, 色彩类型 2/6)解码 + 灰度分位统计。
// 用法:node analyze.mjs <img.png> [x,y,w,h]   —— 可给多个,逐个输出
import { readFileSync } from 'node:fs';
import { inflateSync } from 'node:zlib';

function decode(file) {
  const buf = readFileSync(file);
  let off = 8, w = 0, h = 0, depth = 0, type = 0;
  const idat = [];
  while (off < buf.length) {
    const len = buf.readUInt32BE(off);
    const name = buf.toString('ascii', off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (name === 'IHDR') {
      w = data.readUInt32BE(0); h = data.readUInt32BE(4);
      depth = data[8]; type = data[9];
      if (depth !== 8) throw new Error('only bit depth 8 supported, got ' + depth);
      if (type !== 2 && type !== 6) throw new Error('only color type 2/6 supported, got ' + type);
      if (data[12] !== 0) throw new Error('interlaced PNG not supported');
    } else if (name === 'IDAT') idat.push(data);
    else if (name === 'IEND') break;
    off += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const ch = type === 6 ? 4 : 3;
  const stride = w * ch;
  const out = Buffer.alloc(h * stride);
  let p = 0;
  for (let y = 0; y < h; y++) {
    const f = raw[p++];
    const line = raw.subarray(p, p + stride); p += stride;
    const cur = out.subarray(y * stride, (y + 1) * stride);
    const prev = y > 0 ? out.subarray((y - 1) * stride, y * stride) : null;
    for (let x = 0; x < stride; x++) {
      const a = x >= ch ? cur[x - ch] : 0;
      const b = prev ? prev[x] : 0;
      const c = (prev && x >= ch) ? prev[x - ch] : 0;
      let v = line[x];
      if (f === 1) v += a; else if (f === 2) v += b; else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) { const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c); v += (pa <= pb && pa <= pc) ? a : (pb <= pc ? b : c); }
      cur[x] = v & 255;
    }
  }
  return { w, h, ch, data: out };
}

const pct = (sorted, q) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * q)))];

function stats(img, box) {
  const [x0, y0, w0, h0] = box ?? [0, 0, img.w, img.h];
  const X0 = Math.max(0, x0), Y0 = Math.max(0, y0);
  const X1 = Math.min(img.w, x0 + w0), Y1 = Math.min(img.h, y0 + h0);
  const g = [], warm = [];
  let rSum = 0, gSum = 0, bSum = 0, n = 0;
  const hist = new Uint32Array(256);
  for (let y = Y0; y < Y1; y++) for (let x = X0; x < X1; x++) {
    const i = (y * img.w + x) * img.ch;
    const r = img.data[i], gg = img.data[i + 1], b = img.data[i + 2];
    const lum = Math.round(0.2126 * r + 0.7152 * gg + 0.0722 * b);
    g.push(lum); hist[lum]++;
    rSum += r; gSum += gg; bSum += b;
    if (r - b > 6) warm.push(lum);
    n++;
  }
  g.sort((a, b) => a - b);
  const brightFrac = g.filter(v => v >= 250).length / g.length;
  const darkFrac = g.filter(v => v < 200).length / g.length;
  // 六级亮度分布:用来判断"层次关系"对不对,而不是只看均值
  const TIERS = [[248, 256, 'sky/247+'], [242, 248, 'roof242-247'], [232, 242, 'lit232-241'], [215, 232, 'shade215-231'], [195, 215, 'gap195-214'], [175, 195, 'contact175-194'], [0, 175, 'deep<175']];
  const tiers = {};
  for (const [lo, hi, name] of TIERS) {
    let c = 0;
    for (const v of g) if (v >= lo && v < hi) c++;
    tiers[name] = +(c / g.length * 100).toFixed(1);
  }
  const p10 = pct(g, .10), p90 = pct(g, .90);
  return {
    px: n,
    gray: [0.01, .05, .10, .25, .50, .75, .90, .95, .99].map(q => pct(g, q)),
    mean: +(g.reduce((s, v) => s + v, 0) / g.length).toFixed(1),
    localContrast_p90_p10: p90 - p10,
    rgb: [+(rSum / n).toFixed(1), +(gSum / n).toFixed(1), +(bSum / n).toFixed(1)],
    warmPx: warm.length, warmFrac: +(warm.length / n * 100).toFixed(2),
    overexposedFrac: +(brightFrac * 100).toFixed(2), darkFrac: +(darkFrac * 100).toFixed(2),
    tiers,
  };
}

const [file, ...rest] = process.argv.slice(2);
const img = decode(file);
if (rest[0] === '--framing') {
  // 城市在画面里的垂直占位。配合灰色页面底(SHOT_BG)使用:亮于阈值即算城市。
  const thr = Number(rest[1] || 243);
  const rows = [];
  for (let y = 0; y < img.h; y++) {
    let lit = 0;
    for (let x = 0; x < img.w; x++) {
      const i = (y * img.w + x) * img.ch;
      if (Math.max(img.data[i], img.data[i + 1], img.data[i + 2]) > thr) lit++;
    }
    rows.push(lit / img.w);
  }
  const first = rows.findIndex(v => v > 0.02);
  const last = rows.length - 1 - [...rows].reverse().findIndex(v => v > 0.02);
  console.log(`${file} ${img.w}x${img.h}  thr=${thr}  city top ${(first / img.h * 100).toFixed(1)}%  bottom ${(last / img.h * 100).toFixed(1)}%  height ${((last - first) / img.h * 100).toFixed(1)}%`);
  process.exit(0);
}
let box;
if (rest.length === 4) box = rest.map(Number);
console.log(file, `${img.w}x${img.h}`, 'box=' + (box ? box.join(',') : 'full'));
console.log(JSON.stringify(stats(img, box)));
