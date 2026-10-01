// Read-only asset isolation: http://127.0.0.1:8522/?pan=1&part=cottage&isolate=flat
// isolate=all|no-trees|no-lawn|flat. Production assets and source stay untouched.
import http from 'node:http';
const upstream = 'http://127.0.0.1:8520';
const inspection = `
  const inspectPart = q.get('part') || 'cottage';
  const inspectMode = q.get('isolate') || 'all';
  if (inspectMode === 'no-floor') floors.forEach(o => o.visible = false);
  if (inspectMode === 'no-city') { cityObjs.forEach(o => o.visible = false); floors[0].visible = false; }
  const inspectStatus = document.createElement('pre');
  inspectStatus.style.cssText = 'position:fixed;top:0;left:0;z-index:9999;background:white;color:black;font:12px monospace';
  inspectStatus.textContent = JSON.stringify(houseObjs.map(o => ({name:o.name, source:o.userData?.name, alphaTest:o.material.alphaTest})), null, 2);
  document.body.append(inspectStatus);
  const originalName = o => o.userData.name || o.name.replaceAll('_', ' ');
  const inspectBounds = boxInCameraPlane(houseObjs.filter(o => originalName(o) === 'v28 ' + inspectPart));
  Object.assign(F1, { cu: (inspectBounds.u0 + inspectBounds.u1) / 2, cv: (inspectBounds.v0 + inspectBounds.v1) / 2,
    w: (inspectBounds.u1 - inspectBounds.u0) * 1.25 });
  for (const o of houseParts) {
    if (o.isInstancedMesh) { if (inspectMode === 'no-trees') o.visible = false; }
    else {
      if (!originalName(o).startsWith('v28 ' + inspectPart)) o.visible = false;
      if (inspectMode === 'no-lawn' && originalName(o).endsWith(' lawn')) o.visible = false;
      if (inspectMode === 'flat' && !originalName(o).endsWith(' lawn')) { o.material.map = null; o.material.color.set('#EDEBE5'); o.material.needsUpdate = true; }
    }
  }
`;
http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, upstream), response = await fetch(url);
    res.statusCode = response.status;
    res.setHeader('content-type', response.headers.get('content-type') || 'application/octet-stream');
    res.setHeader('cache-control', 'no-store');
    if (url.pathname === '/static/showroom/showroom.mjs') {
      const code = await response.text();
      res.end(code.replace('  // 离屏目标 + 移轴后处理', inspection + '\n  // 离屏目标 + 移轴后处理'));
    } else if (url.pathname === '/') {
      res.end((await response.text()).replace('</head>', '<style>.hero-copy,.composer,header,#showroom-signs,.sr-arrow{visibility:hidden!important}</style></head>'));
    } else res.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) { res.statusCode = 502; res.end(String(error)); }
}).listen(8522, '127.0.0.1', () => console.log('Asset isolation: http://127.0.0.1:8522/?pan=1&tilt=0&part=cottage&isolate=all'));
