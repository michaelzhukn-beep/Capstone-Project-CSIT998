// 两张同尺寸截图逐像素比较:node diff.mjs <a.png> <b.png> [x,y,w,h]
// 输出:b 相对 a 有多少比例的像素灰度变化超过 5 级 / 10 级,以及平均绝对差。
import { decode } from './png.mjs';
const [fa, fb, ...rest] = process.argv.slice(2);
const A = decode(fa), B = decode(fb);
if (A.w !== B.w || A.h !== B.h) { console.error(`size mismatch ${A.w}x${A.h} vs ${B.w}x${B.h}`); process.exit(2); }
let [x0, y0, w0, h0] = rest.length === 4 ? rest.map(Number) : [0, 0, A.w, A.h];
const X1 = Math.min(A.w, x0 + w0), Y1 = Math.min(A.h, y0 + h0);
const lum = (img, i) => 0.2126 * img.data[i] + 0.7152 * img.data[i + 1] + 0.0722 * img.data[i + 2];
let n = 0, over5 = 0, over10 = 0, sum = 0, max = 0;
for (let y = Math.max(0, y0); y < Y1; y++) for (let x = Math.max(0, x0); x < X1; x++) {
  const i = (y * A.w + x) * A.ch;
  const d = Math.abs(lum(A, i) - lum(B, i));
  n++; sum += d; if (d > 5) over5++; if (d > 10) over10++; if (d > max) max = d;
}
console.log(`${fb} vs ${fa}: >5级 ${(over5 / n * 100).toFixed(2)}%  >10级 ${(over10 / n * 100).toFixed(2)}%  平均差 ${(sum / n).toFixed(2)}  最大 ${max.toFixed(0)}`);
