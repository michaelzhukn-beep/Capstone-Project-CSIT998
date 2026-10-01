// 裁剪/缩放 PNG:node crop.mjs <in.png> <out.png> <x> <y> <w> <h> [scale]
// scale >= 1 走最近邻放大(看单像素);scale < 1 走盒式降采样(出拼图)。
import { decode, encode } from './png.mjs';
import { writeFileSync } from 'node:fs';
const [inp, outp, x, y, w, h, s] = process.argv.slice(2);
const img = decode(inp);
const scale = Number(s || 1);
const x0 = Math.max(0, Math.min(img.w - 1, +x)), y0 = Math.max(0, Math.min(img.h - 1, +y));
const cw = Math.max(1, Math.min(img.w - x0, +w)), chh = Math.max(1, Math.min(img.h - y0, +h));

let out;
if (scale >= 1) {
  const k = Math.round(scale);
  out = { w: cw * k, h: chh * k, ch: img.ch, data: Buffer.alloc(cw * k * chh * k * img.ch) };
  for (let yy = 0; yy < chh * k; yy++) for (let xx = 0; xx < cw * k; xx++) {
    const sx = x0 + Math.floor(xx / k), sy = y0 + Math.floor(yy / k);
    const si = (sy * img.w + sx) * img.ch, di = (yy * out.w + xx) * img.ch;
    for (let c = 0; c < img.ch; c++) out.data[di + c] = img.data[si + c];
  }
} else {
  const ow = Math.max(1, Math.round(cw * scale)), oh = Math.max(1, Math.round(chh * scale));
  out = { w: ow, h: oh, ch: img.ch, data: Buffer.alloc(ow * oh * img.ch) };
  const bx = cw / ow, by = chh / oh;
  for (let yy = 0; yy < oh; yy++) for (let xx = 0; xx < ow; xx++) {
    const sx0 = Math.floor(x0 + xx * bx), sx1 = Math.max(sx0 + 1, Math.floor(x0 + (xx + 1) * bx));
    const sy0 = Math.floor(y0 + yy * by), sy1 = Math.max(sy0 + 1, Math.floor(y0 + (yy + 1) * by));
    const acc = new Float64Array(img.ch), di = (yy * ow + xx) * img.ch;
    let n = 0;
    for (let sy = sy0; sy < Math.min(sy1, img.h); sy++) for (let sx = sx0; sx < Math.min(sx1, img.w); sx++) {
      const si = (sy * img.w + sx) * img.ch;
      for (let c = 0; c < img.ch; c++) acc[c] += img.data[si + c];
      n++;
    }
    for (let c = 0; c < img.ch; c++) out.data[di + c] = Math.round(acc[c] / Math.max(1, n));
  }
}
writeFileSync(outp, encode(out.w, out.h, out.ch, out.data));
console.log(`${inp} ${img.w}x${img.h} -> ${outp} ${out.w}x${out.h}`);

