// 把多张图按列/行拼成一张对比图:node compose.mjs <out.png> <cols> <in1.png> <in2.png> ...
// 所有输入必须同尺寸;不足的格子留白。
import { decode, save } from './png.mjs';
const [outp, colsArg, ...files] = process.argv.slice(2);
const cols = Math.max(1, Number(colsArg) || 1);
const imgs = files.map(decode);
const W = Math.max(...imgs.map(i => i.w)), H = Math.max(...imgs.map(i => i.h));
const ch = imgs[0].ch;
const rows = Math.ceil(imgs.length / cols);
const gap = 6;
const OW = cols * W + (cols + 1) * gap, OH = rows * H + (rows + 1) * gap;
const data = Buffer.alloc(OW * OH * ch, 235);
imgs.forEach((img, i) => {
  const cx = (i % cols) * (W + gap) + gap, cy = Math.floor(i / cols) * (H + gap) + gap;
  for (let y = 0; y < img.h; y++) for (let x = 0; x < img.w; x++) {
    const si = (y * img.w + x) * img.ch, di = ((cy + y) * OW + cx + x) * ch;
    for (let c = 0; c < ch; c++) data[di + c] = img.data[si + c];
  }
});
save(outp, OW, OH, ch, data);
console.log(`${outp} ${OW}x${OH}  ${imgs.length} tiles`);
