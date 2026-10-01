// Rebuild the homepage's clean lawn overrides from the original isolated renders.
// No pixel editing, rebake, or mutation of the GLB / Blender source is involved.
// Run from any directory: node design/white-city/blender/copy_showroom_lawns.mjs
import { copyFile, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const source = new URL('../bake-v28/raw/', import.meta.url);
const target = new URL('../../../app/web/showroom/', import.meta.url);
for (const key of ['cottage', 'villa', 'terrace', 'apartment']) {
  const from = new URL(`v28_${key}_lawn.png`, source), to = new URL(`lawn-${key}.png`, target);
  await copyFile(from, to);
  const hash = data => createHash('sha256').update(data).digest('hex');
  if (hash(await readFile(from)) !== hash(await readFile(to))) throw new Error(`Copy verification failed: ${key}`);
  console.log(`Verified lawn-${key}.png`);
}
