import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const host = document.querySelector('#viewport');
const workspace = document.querySelector('#workspace');
const loading = document.querySelector('#loading');
const loadingCopy = document.querySelector('#loading-copy');
const retry = document.querySelector('#retry');
const cyclesPane = document.querySelector('#cycles-pane');
const cyclesImage = document.querySelector('#cycles-image');
const viewLabel = document.querySelector('#view-label');
const detail = document.querySelector('#detail');
const labels = {
  studio: ['灯光效果 · 三维模型', '白色柔光与局部暖光 · 材质、灯光效果待确认'],
  clay: ['白模对照 · 三维模型', '同一机位的基础白模 · 用于比较明暗与边缘过渡'],
  cycles: ['Cycles 对照 · 离线渲染', '同一模型、同一机位的离线渲染 · 此页对照为静态画面'],
};
let mode = 'studio';
let scene, renderer, composer, bloom, camera, cameraSpec, plan, bake;
let frames = 0, pendingFrame = 0, stateRevision = 0;
let cyclesReady = false;
const models = new Map();
const pendingModels = new Map();
const validation = {};
const convert = ([x, y, z]) => new THREE.Vector3(x, z, -y);
const draco = new DRACOLoader().setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/');
const loader = new GLTFLoader().setDRACOLoader(draco);

// ---------------------------------------------------------------- v22 灯光层
// 四层叠加:① 烘焙的顶部大面积柔光 + 白色环境光(Cycles 实测)② 暗部整体抬亮,阴影极浅
// ③ 藏在高楼竖向灯带、低层建筑底部、桥边缘的暖白偏金自发光 ④ 暖光向邻近白墙的柔和扩散 + 只作用于暖光的轻微辉光。
// URL 参数可临时覆盖,例如 ?lift=.5&exposure=1.1&warm=1,便于对比调参。
const query = new URLSearchParams(location.search);
const num = (key, fallback) => (query.has(key) && Number.isFinite(Number(query.get(key))) ? Number(query.get(key)) : fallback);
const LOOK = {
  exposure: num('exposure', 1.1),     // 线性曝光倍数(Neutral 色调映射前)
  white: num('white', 1.0),            // 暗部抬亮的目标白电平(烘焙线性亮度)
  lift: num('lift', .2),              // 0 = 原始烘焙明暗,1 = 暗部完全抬到白电平;留住结构边缘
  sat: num('sat', .45),                // 烘焙白面的饱和度保留比例:去掉水面、凹窗带来的青绿偏色
  warm: num('warm', 1.0),              // 暖光总强度倍数
  spill: num('spill', 1.0),            // 暖光染到邻近白墙的强度倍数
  bloom: num('bloom', .16),
};
const WARM = new THREE.Color().setRGB(1.0, .76, .47, THREE.LinearSRGBColorSpace);   // 淡香槟 / 暖白偏金,不是橙色
const MAX_SPILL = 48;
const MAX_BANDS = 64;
// 立面光带:暖光只染在指定立面的指定高度范围内,边界清楚,窗框明暗保留 —— 像从玻璃里透出来
const bandA = Array.from({ length: MAX_BANDS }, () => new THREE.Vector4());
const bandB = Array.from({ length: MAX_BANDS }, () => new THREE.Vector4(0, 0, 1e5, 1e5 + 1));
const bandC = Array.from({ length: MAX_BANDS }, () => new THREE.Vector4());   // x 横向柔化比例 y 强度 z 竖向曲线(0 底亮 1 两端渐隐)
const spillPoints = Array.from({ length: MAX_SPILL }, () => new THREE.Vector4(0, -1e5, 0, 1));
const shared = {
  uLift: { value: LOOK.lift }, uWhite: { value: LOOK.white }, uSat: { value: LOOK.sat },
  uWarm: { value: new THREE.Vector3(WARM.r, WARM.g, WARM.b) }, uSpill: { value: .55 * LOOK.spill * LOOK.warm },
  uSpillPoints: { value: spillPoints }, uSpillCount: { value: 0 },
  uBandA: { value: bandA }, uBandB: { value: bandB }, uBandC: { value: bandC }, uBandCount: { value: 0 }, uBand: { value: 2.3 * LOOK.warm },
};

function studioMaterial(radianceScale) {
  const material = new THREE.MeshBasicMaterial({
    color: new THREE.Color().setRGB(radianceScale, radianceScale, radianceScale, THREE.LinearSRGBColorSpace),
    vertexColors: true, toneMapped: true, side: THREE.FrontSide,
  });
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, shared);
    shader.vertexShader = shader.vertexShader
      // 噪点根源:MSAA 在极细三角形上把顶点色插值「外推」到三角形外,算出负值,色调映射后成了蓝/紫/黑点。
      // centroid 插值让采样点始终落在三角形内部。
      .replace('#include <color_pars_vertex>', '#include <color_pars_vertex>\n#if defined( USE_COLOR_ALPHA )\ncentroid out vec4 vStudioColor;\n#endif\nout vec3 vStudioPos;\nout vec3 vStudioNormal;')
      .replace('#include <color_vertex>', '#include <color_vertex>\n#if defined( USE_COLOR_ALPHA )\nvStudioColor = vColor;\n#endif')
      .replace('#include <project_vertex>', '#include <project_vertex>\nvStudioPos = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;\nvStudioNormal = normalize( mat3( modelMatrix ) * normal );');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <color_pars_fragment>', `#include <color_pars_fragment>
#if defined( USE_COLOR_ALPHA )
centroid in vec4 vStudioColor;
#endif
in vec3 vStudioPos;
in vec3 vStudioNormal;
uniform float uLift;
uniform float uWhite;
uniform float uSat;
uniform vec3 uWarm;
uniform float uSpill;
uniform vec4 uSpillPoints[ ${MAX_SPILL} ];
uniform int uSpillCount;
uniform vec4 uBandA[ ${MAX_BANDS} ];
uniform vec4 uBandB[ ${MAX_BANDS} ];
uniform vec4 uBandC[ ${MAX_BANDS} ];
uniform int uBandCount;
uniform float uBand;`)
      .replace('#include <color_fragment>', `
#if defined( USE_COLOR_ALPHA )
  // 仍做一次钳位:centroid 之外的数值误差不许再产生负值
  diffuseColor.rgb *= clamp( vStudioColor.rgb, 0.0, 1.0 );
#endif
  vec3 radiance = max( diffuseColor.rgb, vec3( 0.0 ) );
  float lum = dot( radiance, vec3( 0.2126, 0.7152, 0.0722 ) );
  // 白模要白:压掉烘焙里的青绿偏色,统一成略偏暖的乳白
  radiance = mix( vec3( lum ), radiance, uSat ) * vec3( 1.0, 0.992, 0.972 );
  // 极浅阴影:越暗抬得越多,亮面基本不动;抬向略偏暖的乳白而不是纯灰
  float shade = 1.0 - smoothstep( 0.0, uWhite, lum );
  radiance = mix( radiance, uWhite * vec3( 0.985, 0.975, 0.955 ), uLift * shade );
  // 暖光扩散:每个暖光点按距离平方衰减,背对光源的面只接收很少
  vec3 spill = vec3( 0.0 );
  vec3 n = normalize( vStudioNormal );
  for ( int i = 0; i < ${MAX_SPILL}; i++ ) {
    if ( i >= uSpillCount ) break;
    vec3 d = uSpillPoints[ i ].xyz - vStudioPos;
    float r = uSpillPoints[ i ].w;
    float dist2 = dot( d, d );
    float atten = 0.0;
    // 地面光晕:只落在朝上的水平面(地面、步道),墙面的暖光由立面光带负责
    // 半径为负:任意朝向都接收(桥下水面、桥墩);为正:只落在朝上的地面
    float facing = r < 0.0 ? 1.0 : smoothstep( 0.55, 0.85, n.y );
    r = abs( r );
    atten = 1.0 / ( 1.0 + dist2 / ( r * r ) );
    atten *= atten * ( 1.0 - smoothstep( r * 2.2, r * 3.0, sqrt( dist2 ) ) );
    spill += atten * facing;
  }
  // 立面光带:A = 边起点 xz、边终点 xz;B = 外法线 xz、底高、顶高
  float band = 0.0;
  for ( int i = 0; i < ${MAX_BANDS}; i++ ) {
    if ( i >= uBandCount ) break;
    vec2 a = uBandA[ i ].xy;
    vec2 e = uBandA[ i ].zw - a;
    float len = length( e );
    vec2 q = vStudioPos.xz - a;
    float t = dot( q, e ) / ( len * len );
    float out_ = dot( q, uBandB[ i ].xy );
    float y0 = uBandB[ i ].z, y1 = uBandB[ i ].w;
    float h = ( vStudioPos.y - y0 ) / max( y1 - y0, 1e-3 );
    float soft = max( uBandC[ i ].x, 0.02 );
    float edge = smoothstep( 0.0, soft, t ) * ( 1.0 - smoothstep( 1.0 - soft, 1.0, t ) );
    float depth = smoothstep( -3.0, -1.6, out_ ) * ( 1.0 - smoothstep( 0.35, 0.9, out_ ) );
    // 底部最亮,向上柔和减弱;顶端不留硬边
    float vertical = uBandC[ i ].z > 0.5
      ? smoothstep( 0.0, 0.06, h ) * ( 1.0 - smoothstep( 0.86, 1.0, h ) )
      : step( 0.0, h ) * ( 1.0 - smoothstep( 0.55, 1.0, h ) ) * ( 1.0 - 0.45 * h );
    // 只染竖向的立面(屋顶、地面不染)
    float wall = 1.0 - smoothstep( 0.35, 0.6, abs( n.y ) );
    band = max( band, edge * depth * vertical * wall * uBandC[ i ].y );
  }
  // 暖光乘以烘焙亮度:窗框、凹面自然更暗,结构保留
  // 暖光从内部透出:凸出的白框、竖条(烘焙亮)基本保持白色,凹进去的缝隙和玻璃(烘焙暗)才发暖光
  float recess = 1.0 - smoothstep( 0.55 * uWhite, 1.05 * uWhite, lum );
  // 立面竖条之间的明暗差:相邻像素亮度变化大的地方是竖条边缘,光从缝里出来
  recess = max( recess, clamp( fwidth( lum ) * 6.0, 0.0, 1.0 ) * 0.6 );
  diffuseColor.rgb = radiance + uWarm * ( uSpill * spill * max( lum, 0.35 ) + uBand * band * ( 0.12 + 0.88 * recess ) );
`);
  };
  return material;
}

function buildWarmAccents(model) {
  const spill = [];
  const view = new THREE.Vector3().subVectors(convert(cameraSpec.target), convert(cameraSpec.position));
  // 设计坐标里的水平视线方向(X 东,Y 北)
  const v2 = new THREE.Vector2(cameraSpec.target[0] - cameraSpec.position[0], cameraSpec.target[1] - cameraSpec.position[1]).normalize();
  const project = p => convert(p).project(camera);
  const facade = b => {
    const fp = b.footprint;
    const cx = fp.reduce((s, q) => s + q[0], 0) / fp.length, cy = fp.reduce((s, q) => s + q[1], 0) / fp.length;
    let best = null;
    for (let i = 0; i < fp.length; i++) {
      const a = fp[i], c = fp[(i + 1) % fp.length];
      const ex = c[0] - a[0], ey = c[1] - a[1], len = Math.hypot(ex, ey);
      let nx = ey / len, ny = -ex / len;
      const mx = (a[0] + c[0]) / 2, my = (a[1] + c[1]) / 2;
      if (nx * (mx - cx) + ny * (my - cy) < 0) { nx = -nx; ny = -ny; }
      const facing = -(nx * v2.x + ny * v2.y);
      if (!best || facing > best.facing) best = { a, c, len, nx, ny, facing };
    }
    return best;
  };
  const bands = [];
  const band = (f, t0, t1, z0, z1, soft = .06, strength = 1, profile = 0) => {
    const a = convert([f.a[0] + (f.c[0] - f.a[0]) * t0, f.a[1] + (f.c[1] - f.a[1]) * t0, 0]);
    const c = convert([f.a[0] + (f.c[0] - f.a[0]) * t1, f.a[1] + (f.c[1] - f.a[1]) * t1, 0]);
    const n = convert([f.nx, f.ny, 0]);
    bands.push([a.x, a.z, c.x, c.z, n.x, n.z, z0, z1, soft, strength, profile]);
  };
  const onScreen = (b, top = 0) => { const q = project([b.x, b.y, b.z + top]); return q.x > -1.05 && q.x < 1.05 && q.y > -1.05 && q.y < 1.0; };

  // ① 高楼竖向灯带:最高的几座塔楼,朝向镜头的立面中段一条柔和的竖向光带(藏在立面竖条之间,不外挂灯管)
  const towers = plan.buildings.filter(b => b.h >= 38 && onScreen(b, b.h * .5)).sort((a, b) => b.h - a.h).slice(0, 9);
  for (const b of towers) {
    const f = facade(b);
    if (f.facing < .1) continue;
    // 一道窄竖缝:宽约立面的 6%,边缘清楚,强度克制
    band(f, .47, .53, b.z + b.h * .14, b.z + b.h * .9, .22, .75, 1);
  }
  // ② 低层建筑底部:沿岸、靠近镜头的一串,彼此拉开距离,不全亮
  const low = plan.buildings.filter(b => b.h < 26 && !['gable'].includes(b.kind) && onScreen(b, 2))
    .map(b => ({ b, q: project([b.x, b.y, b.z]) }))
    .sort((a, b) => a.q.y - b.q.y);
  const chosen = [];
  for (const { b } of low) {
    if (chosen.every(c => Math.hypot(c.x - b.x, c.y - b.y) > 26)) chosen.push(b);
    if (chosen.length >= 22) break;
  }
  for (const b of chosen) {
    const f = facade(b);
    if (f.facing < .15) continue;
    band(f, .06, .94, b.z + .1, b.z + Math.min(4.6, Math.max(3.2, b.h * .28)), .12, 1.0, 0);
    const mx = (f.a[0] + f.c[0]) / 2 + f.nx * 3.5, my = (f.a[1] + f.c[1]) / 2 + f.ny * 3.5;
    spill.push([mx, my, b.z + .6, Math.max(3.5, f.len * .22)]);
  }
  // ③ 桥:桥面下方一串柔和暖光,落在水面和桥墩上;桥面高度用射线在桥面网格上实测
  const deck = [];
  model.traverse(o => { if (o.isMesh && o.name.includes('deck')) deck.push(o); });
  const bridge = plan.bridges?.[0];
  if (bridge && deck.length) {
    const ray = new THREE.Raycaster();
    const pts = [];
    for (let i = 0; i < bridge.path.length; i += 2) {
      const [x, y] = bridge.path[i];
      ray.set(convert([x, y, 400]), new THREE.Vector3(0, -1, 0));
      const hit = ray.intersectObjects(deck, false)[0];
      if (hit) pts.push([x, y, hit.point.y]);
    }
    const half = (bridge.width ?? 7) / 2;
    for (let i = 0; i + 1 < pts.length; i++) {
      const [x0, y0, z0] = pts[i], [x1, y1, z1] = pts[i + 1];
      const ex = x1 - x0, ey = y1 - y0, len = Math.hypot(ex, ey);
      if (len < .1) continue;
      // 朝镜头那一侧的桥边
      let nx = ey / len, ny = -ex / len;
      if (-(nx * v2.x + ny * v2.y) < 0) { nx = -nx; ny = -ny; }
      if (i % 3 === 0) spill.push([(x0 + x1) / 2 + nx * half * .6, (y0 + y1) / 2 + ny * half * .6, (z0 + z1) / 2 - 2.2, -5]);
    }
  }
  bands.slice(0, MAX_BANDS).forEach((v, i) => { bandA[i].set(v[0], v[1], v[2], v[3]); bandB[i].set(v[4], v[5], v[6], v[7]); bandC[i].set(v[8], v[9], v[10], 0); });
  shared.uBandCount.value = Math.min(bands.length, MAX_BANDS);
  spill.slice(0, MAX_SPILL).forEach((p, i) => spillPoints[i].set(...convert(p.slice(0, 3)).toArray(), p[3]));
  // 不再添加任何发光几何体:暖光只在建筑表面的着色里出现
  shared.uSpillCount.value = Math.min(spill.length, MAX_SPILL);
  window.__v22 = { bands: bands.length, towers: towers.length, low: chosen.length,  spill: spill.length, look: LOOK, view: view.toArray() };
}

function status(message, failed = false) {
  loadingCopy.textContent = message;
  retry.hidden = !failed;
  loading.hidden = false;
  host.dataset.loaded = failed ? 'error' : 'false';
}

async function json(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Unavailable asset: ${url} (${response.status})`);
  return response.json();
}

function cameraAspect() {
  const width = host.clientWidth, height = host.clientHeight;
  if (!width || !height) return;
  // This is the captured v20 projection. Do not fit model bounds or retarget.
  const aspect = width / height;
  const span = cameraSpec.scale * Math.max(1, aspect / (cameraSpec.reference_aspect ?? (1600 / 1100)));
  camera.left = -span / 2;
  camera.right = span / 2;
  camera.top = span / aspect / 2;
  camera.bottom = -span / aspect / 2;
  camera.updateProjectionMatrix();
  host.dataset.camera = JSON.stringify({ ...cameraSpec, actual_viewport: [width, height], frustum: { left: camera.left, right: camera.right, top: camera.top, bottom: camera.bottom }, automatic_motion: false });
  host.dataset.compositionCamera = JSON.stringify(cameraSpec);
}

function draw() {
  if (!renderer || mode === 'cycles' || !models.has(mode)) return;
  cameraAspect();
  // Keep the baked scene linear until OutputPass applies AgX and sRGB once.
  if (mode === 'studio') composer.render();
  else renderer.render(scene, camera);
  host.dataset.frames = String(++frames);
}

function schedule() {
  if (!pendingFrame) pendingFrame = requestAnimationFrame(() => { pendingFrame = 0; draw(); });
}

function resize() {
  if (!renderer) return;
  const width = host.clientWidth, height = host.clientHeight;
  if (!width || !height) return;
  renderer.setSize(width, height, false);
  composer.setSize(width, height);
  cameraAspect();
  schedule();
}

function inspectModel(model, name) {
  let meshes = 0, triangles = 0, coloredMeshes = 0;
  model.traverse(object => {
    if (!object.isMesh) return;
    meshes++;
    triangles += (object.geometry.index?.count ?? object.geometry.attributes.position.count) / 3;
    if (object.geometry.attributes.color) coloredMeshes++;
    if (name === 'studio') {
      if (!object.geometry.attributes.color) throw new Error(`Baked mesh has no radiance colors: ${object.name}`);
      const radianceScale = Number(bake.radiance_scale ?? bake.encoding?.radiance_scale);
      if (!Number.isFinite(radianceScale) || radianceScale <= 0) throw new Error('Invalid baked radiance scale');
      const previous = Array.isArray(object.material) ? object.material : [object.material];
      object.material = studioMaterial(radianceScale);
      previous.forEach(material => material.dispose());
      object.castShadow = false;
      object.receiveShadow = false;
    } else {
      let group = object;
      while (group.parent && group.parent !== model) group = group.parent;
      object.castShadow = ['04', '05', '06', '07'].includes(group.name.slice(0, 2));
      object.receiveShadow = true;
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        material.roughness = .82;
        material.metalness = 0;
      }
    }
  });
  validation[name] = { meshes, triangles, coloredMeshes, model: name === 'studio' ? 'city-14-studio-baked.glb' : 'city-13-smooth.glb' };
  host.dataset.validation = JSON.stringify({ ...validation, fixedCamera: true, automaticCameraMotion: false, bakedRadianceScale: bake?.radiance_scale ?? bake?.encoding?.radiance_scale, buildingCount: plan.buildings?.length, phase: 'experimental-lighting' });
}

function loadModel(name) {
  if (models.has(name)) return Promise.resolve(models.get(name));
  if (pendingModels.has(name)) return pendingModels.get(name);
  const request = (async () => {
    if (name === 'studio' && !bake) bake = await json('./blender/city-14-studio-bake.json');
    const url = name === 'studio'
      ? `./blender/city-14-studio-baked.glb?v=${bake.output_sha256}`
      : './blender/city-13-smooth.glb?v=1';
    const gltf = await loader.loadAsync(url, progress => {
      if (mode === name && progress.total) loadingCopy.textContent = `正在加载${name === 'studio' ? '城市灯光' : '白模对照'}… ${Math.round(progress.loaded / progress.total * 100)}%`;
    });
    inspectModel(gltf.scene, name);
    if (name === 'studio') buildWarmAccents(gltf.scene);
    gltf.scene.visible = false;
    models.set(name, gltf.scene);
    scene.add(gltf.scene);
    return gltf.scene;
  })().finally(() => pendingModels.delete(name));
  pendingModels.set(name, request);
  return request;
}

function applyModelMode() {
  for (const [name, model] of models) model.visible = mode === name;
  // Neutral 色调映射保住白色不发灰(AgX 会把高亮白压成灰);曝光单独可调
  renderer.toneMapping = mode === 'clay' ? THREE.ACESFilmicToneMapping : THREE.NeutralToneMapping;
  renderer.toneMappingExposure = mode === 'clay' ? 1.10 : LOOK.exposure;
  renderer.shadowMap.enabled = mode === 'clay';
  renderer.shadowMap.needsUpdate = mode === 'clay';
  // The page white is not scene radiance: keep it out of exposure and bloom.
  scene.background = mode === 'clay' ? new THREE.Color('#f4f5ef') : null;
  schedule();
}

async function setMode(next) {
  const revision = ++stateRevision;
  mode = next;
  host.dataset.mode = mode;
  for (const button of document.querySelectorAll('[data-mode]')) button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  viewLabel.textContent = labels[mode][0];
  detail.textContent = labels[mode][1];
  host.style.visibility = mode === 'cycles' ? 'hidden' : 'visible';
  cyclesPane.hidden = mode !== 'cycles';
  if (mode === 'cycles') {
    loading.hidden = cyclesReady;
    if (!cyclesReady) {
      status('正在加载 Cycles 离线对照…');
      cyclesImage.src = './blender/renders/city-14-studio.png?v=1';
    } else host.dataset.loaded = 'true';
    return;
  }
  if (!scene) return;
  status(`正在加载${mode === 'studio' ? '城市灯光' : '白模对照'}…`);
  try {
    await loadModel(mode);
    if (revision !== stateRevision) return;
    applyModelMode();
    loading.hidden = true;
    host.dataset.loaded = 'true';
  } catch (error) {
    console.error(error);
    if (revision === stateRevision) status('模型暂时无法加载，请重试。', true);
  }
}

cyclesImage.addEventListener('load', () => {
  cyclesReady = true;
  if (mode === 'cycles') { loading.hidden = true; host.dataset.loaded = 'true'; }
});
cyclesImage.addEventListener('error', () => {
  cyclesReady = false;
  if (mode === 'cycles') status('离线对照暂时无法加载，请重试。', true);
});
for (const button of document.querySelectorAll('[data-mode]')) button.addEventListener('click', () => setMode(button.dataset.mode));
retry.addEventListener('click', () => scene ? setMode(mode) : location.reload());

try {
  plan = await json('./blender/city-14-studio-plan.json');
  cameraSpec = plan.composition_camera;
  if (!cameraSpec?.scale || !cameraSpec?.position || !cameraSpec?.target) throw new Error('Missing locked camera specification');
  const captured = cameraSpec.captured_viewport ?? [1883.3333740234375, 1054];
  // Identical panel aspect across all three modes preserves the approved crop.
  workspace.style.aspectRatio = `${captured[0]} / ${captured[1]}`;
  camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 6000);
  camera.position.copy(convert(cameraSpec.position));
  camera.up.copy(convert(cameraSpec.up ?? [0, 0, 1]));
  camera.zoom = cameraSpec.zoom ?? 1;
  camera.lookAt(convert(cameraSpec.target));
  camera.updateMatrixWorld();
  scene = new THREE.Scene();
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, premultipliedAlpha: false });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.AgXToneMapping;
  renderer.toneMappingExposure = 2 ** Number(plan.studio?.exposure ?? 1.0);
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;
  host.append(renderer.domElement);
  renderer.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); status('预览暂时中断，请刷新恢复。', true); });
  renderer.domElement.addEventListener('webglcontextrestored', () => location.reload());
  const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
  composer = new EffectComposer(renderer, target);
  composer.addPass(new RenderPass(scene, camera));
  // 辉光阈值高于白墙的亮度,只截暖光;半径小、强度低,不形成明显光晕
  bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), LOOK.bloom, .18, 3.4);
  // Add only glow RGB. Preserve the original coverage alpha so an empty sky
  // remains the page background instead of becoming an opaque grey rectangle.
  bloom.blendMaterial.blending = THREE.CustomBlending;
  bloom.blendMaterial.blendSrc = THREE.OneFactor;
  bloom.blendMaterial.blendDst = THREE.OneFactor;
  bloom.blendMaterial.blendSrcAlpha = THREE.ZeroFactor;
  bloom.blendMaterial.blendDstAlpha = THREE.OneFactor;
  composer.addPass(bloom);
  composer.addPass(new OutputPass());
  // These lights serve the separate clay comparison only; the studio model
  // carries its measured Cycles surface radiance and does not get lit twice.
  scene.add(new THREE.HemisphereLight(0xffffff, 0xd0d1c4, 1.3));
  const key = new THREE.DirectionalLight(0xfffdf5, 2.5);
  key.position.set(-260, 620, 330);
  key.castShadow = true;
  key.shadow.mapSize.set(4096, 4096);
  Object.assign(key.shadow.camera, { left: -480, right: 480, top: 410, bottom: -410, near: 1, far: 1500 });
  key.shadow.normalBias = .25;
  key.shadow.bias = -.000001;
  scene.add(key, key.target);
  const fill = new THREE.DirectionalLight(0xf3f7ff, .55);
  fill.position.set(350, 220, -250);
  scene.add(fill);
  document.querySelector('#summary').textContent = `${plan.buildings?.length ?? 164} 栋建筑 · 固定机位 · 白色柔光`;
  new ResizeObserver(resize).observe(workspace);
  resize();
  await setMode(mode);
} catch (error) {
  console.error(error);
  status('城市场景暂时无法加载，请重试。', true);
}
