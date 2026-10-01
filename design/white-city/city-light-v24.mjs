// v23 城市柔光:实时 PBR 白模。不再使用烘焙顶点色 —— 白模质感由材质、主光、环境光、阴影直接建立。
//
// 阶段(?stage=):
//   neutral  中性白模:无暖光、无 Bloom
//   warm     加入藏在凹槽里的灯片 + 少量真实暖灯承光,仍无 Bloom
//   final    再加只作用于灯片的轻微 Bloom(默认)
// 视图(?view=):
//   city     锁定机位的完整城市(默认)
//   sample   同方向、推近到一组低/中/高楼与地面的调试相机,只改相机,不改比例
// 单项调试:?exposure=0.8  ?ao=0  ?shadow=0  ?env=0  ?fill=0  ?key=0
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

// ---------------------------------------------------------------- 集中参数
const q = new URLSearchParams(location.search);
const num = (k, d) => (q.has(k) && Number.isFinite(Number(q.get(k))) ? Number(q.get(k)) : d);
const STAGE = ['neutral', 'warm', 'final'].includes(q.get('stage')) ? q.get('stage') : 'final';
const VIEW = q.get('view') === 'sample' ? 'sample' : 'city';

export const PARAMS = {
  // 色彩输出:只有一条路径 —— 场景线性 HDR → (Bloom 合成) → OutputPass 一次性做色调映射 + sRGB
  toneMapping: { neutral: THREE.NeutralToneMapping, agx: THREE.AgXToneMapping, aces: THREE.ACESFilmicToneMapping }[q.get('tonemap') || 'neutral'],
  pixelRatio: num('pr', 1),
  exposure: num('exposure', 1.0),
  materials: {
    building: { color: '#F2F2F0', roughness: .70 },
    roof:     { color: '#F4F4F1', roughness: .74 },
    panel:    { color: '#ECECE9', roughness: .66 },   // 凹窗面板:略低一档,窗格才读得出
    ground:   { color: '#F5F5F2', roughness: .88 },
    road:     { color: '#F0F0EC', roughness: .90 },
    water:    { color: '#EDEFEE', roughness: .55 },   // 浅,不做镜面
    crown:    { color: '#F3F3F0', roughness: .85 },
    branch:   { color: '#E4E4DF', roughness: .85 },
  },
  // 主光从右上前方来。提示词起点 (-.35,.75,.45) 在本机位下同时正对镜头看到的两组立面,两面受光相同、
  // 城市显得平(小样实测顶面 250 / 正面 248,只差 2 级);右上前方让朝左的立面落进柔和背光,体积立住。
  key:  { offset: (q.get('keydir') || '.35,.75,.45').split(',').map(Number), color: '#FFFFFF', intensity: num('key', 2.5) },
  // 弱填光放在主光对侧,只负责把背光立面从灰提到浅灰白(小样实测最暗 5% 从 180 → 211)
  fill: { offset: (q.get('filldir') || '-.5,.35,.3').split(',').map(Number), color: '#FFFFFF', intensity: num('fill', .9) },
  environment: num('env', .9),
  shadow: { enabled: num('shadow', 1) === 1, mapSize: num('shadowmap', 4096), bias: -.0004, normalBias: .04, radius: 3 },
  ao: { enabled: num('ao', 1) === 1, radius: num('aoradius', 2.2), thickness: num('aothick', 1.5), blend: num('aoblend', .45) },
  // 暖光方式实验:plane = 玻璃后平板灯片(v23);up = 楼前地面朝上的洗墙灯;upglow = 洗墙灯 + 自下而上渐弱的玻璃透光
  warmMode: q.get('warmmode') || 'plane',
  uplight: { intensity: num('up', 400), angle: num('upangle', .42), reach: num('upreach', .55) },
  warm: {
    color: '#FFF0DC',
    emitter: num('emit', 1.4),          // 灯片线性强度。过高(3.2)会被色调映射冲成白色,暖色反而看不出
    lights: 3,                           // 实时暖灯预算
    lightColor: '#FFE7C8',
    lightIntensity: num('lamp', 1500),   // SpotLight 发光强度(坎德拉),小样校准
    lightDistance: 11,
  },
  bloom: { strength: num('bloom', .12), radius: .08, threshold: 0 },   // 只渲染灯片层,阈值无需依赖亮度
};
const BLOOM_LAYER = 1;

// ---------------------------------------------------------------- 页面
const host = document.querySelector('#viewport');
const workspace = document.querySelector('#workspace');
const loading = document.querySelector('#loading');
const loadingCopy = document.querySelector('#loading-copy');
const retry = document.querySelector('#retry');
const status = (msg, failed = false) => { loadingCopy.textContent = msg; retry.hidden = !failed; loading.hidden = false; host.dataset.loaded = failed ? 'error' : 'false'; };
retry.addEventListener('click', () => location.reload());
const convert = ([x, y, z]) => new THREE.Vector3(x, z, -y);   // 设计坐标 Z 向上 → three Y 向上
const report = window.__v23 = { stage: STAGE, view: VIEW, params: PARAMS };

let renderer, scene, camera, cameraSpec, plan, composer, bloomComposer, city, bounds;
const disposables = [];

async function json(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`Unavailable: ${url}`);
  return r.json();
}

// ---------------------------------------------------------------- 相机
function frameCamera() {
  const w = host.clientWidth, h = host.clientHeight;
  if (!w || !h) return;
  const aspect = w / h;
  const span = VIEW === 'sample' ? cameraSpec.sampleSpan
    : cameraSpec.scale * Math.max(1, aspect / (cameraSpec.reference_aspect ?? 1600 / 1100));
  Object.assign(camera, { left: -span / 2, right: span / 2, top: span / aspect / 2, bottom: -span / aspect / 2 });
  camera.updateProjectionMatrix();
}

// ---------------------------------------------------------------- 材质:实心白色非金属 PBR
function standard(spec) {
  const m = new THREE.MeshStandardMaterial({ color: new THREE.Color(spec.color), roughness: spec.roughness, metalness: 0 });
  disposables.push(m);
  return m;
}

function applyMaterials(model) {
  const M = Object.fromEntries(Object.entries(PARAMS.materials).map(([k, v]) => [k, standard(v)]));
  const byName = {
    '13 White clay': 'building', '13 Recessed white panels': 'panel', '13 Pavement': 'road',
    '13 Still water': 'water', '13 Tree crowns': 'crown', '13 Branches': 'branch',
  };
  const used = {};
  model.traverse(o => {
    if (!o.isMesh) return;
    const list = Array.isArray(o.material) ? o.material : [o.material];
    const next = list.map(old => {
      let key = byName[old.name];
      // 「Roof and stone」同时被地形和屋顶使用:按网格区分
      if (old.name === '13 Roof and stone') key = /terrain|lake|road/i.test(o.name) ? 'ground' : 'roof';
      key ??= 'building';
      used[`${o.name} / ${old.name}`] = key;
      old.dispose();
      return M[key];
    });
    o.material = Array.isArray(o.material) ? next : next[0];
    o.castShadow = !/lake/i.test(o.name);
    o.receiveShadow = true;
  });
  report.materialMap = used;
}

// ---------------------------------------------------------------- 灯光:主光 + 弱填光 + 中性棚拍环境
function buildLights() {
  const size = bounds.getSize(new THREE.Vector3()), center = bounds.getCenter(new THREE.Vector3());
  const W = size.x;
  const place = (spec, shadow) => {
    const light = new THREE.DirectionalLight(new THREE.Color(spec.color), spec.intensity);
    light.position.copy(center).add(new THREE.Vector3(...spec.offset).multiplyScalar(W));
    light.target.position.copy(center);      // 方向由位置与 target 决定
    scene.add(light, light.target);
    if (shadow) fitShadow(light);
    return light;
  };
  const key = place(PARAMS.key, PARAMS.shadow.enabled);
  const fill = place(PARAMS.fill, false);
  // 中性环境:RoomEnvironment 经 PMREM 预过滤,只生成一次
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTarget = pmrem.fromScene(new RoomEnvironment(), .04);
  pmrem.dispose();
  disposables.push(envTarget);
  scene.environment = envTarget.texture;
  scene.environmentIntensity = PARAMS.environment;
  scene.background = null;                   // 背景交给页面,不参与曝光
  report.lights = { W: +W.toFixed(1), center: center.toArray().map(v => +v.toFixed(1)), key: key.position.toArray().map(v => +v.toFixed(1)), fill: fill.position.toArray().map(v => +v.toFixed(1)) };
}

function fitShadow(light) {
  light.castShadow = true;
  const s = light.shadow;
  s.mapSize.set(PARAMS.shadow.mapSize, PARAMS.shadow.mapSize);
  s.bias = PARAMS.shadow.bias;
  s.normalBias = PARAMS.shadow.normalBias;
  s.radius = PARAMS.shadow.radius;
  // 阴影相机紧贴城市包围盒(含最高建筑):把包围盒 8 个角点变换到光源视空间求范围
  const cam = s.camera;
  cam.position.copy(light.position);
  cam.lookAt(light.target.position);
  cam.updateMatrixWorld();
  const box = new THREE.Box3();
  const c = bounds;
  for (const x of [c.min.x, c.max.x]) for (const y of [c.min.y, c.max.y]) for (const z of [c.min.z, c.max.z]) {
    box.expandByPoint(new THREE.Vector3(x, y, z).applyMatrix4(cam.matrixWorldInverse));
  }
  cam.left = box.min.x - 2; cam.right = box.max.x + 2; cam.bottom = box.min.y - 2; cam.top = box.max.y + 2;
  cam.near = Math.max(.5, -box.max.z - 5); cam.far = -box.min.z + 5;
  cam.updateProjectionMatrix();
  report.shadow = { map: PARAMS.shadow.mapSize, width: +(box.max.x - box.min.x).toFixed(1), height: +(box.max.y - box.min.y).toFixed(1), texel: +((box.max.x - box.min.x) / PARAMS.shadow.mapSize).toFixed(3) };
}

// ---------------------------------------------------------------- 暖光:A 灯片 / B 少量真实暖灯
function buildWarm() {
  const v2 = new THREE.Vector2(cameraSpec.target[0] - cameraSpec.position[0], cameraSpec.target[1] - cameraSpec.position[1]).normalize();
  const project = p => convert(p).project(camera);
  const facade = b => {
    const fp = b.footprint, cx = fp.reduce((s, p) => s + p[0], 0) / fp.length, cy = fp.reduce((s, p) => s + p[1], 0) / fp.length;
    let best = null;
    fp.forEach((a, i) => {
      const c = fp[(i + 1) % fp.length], len = Math.hypot(c[0] - a[0], c[1] - a[1]);
      let nx = (c[1] - a[1]) / len, ny = -(c[0] - a[0]) / len;
      if (nx * ((a[0] + c[0]) / 2 - cx) + ny * ((a[1] + c[1]) / 2 - cy) < 0) { nx = -nx; ny = -ny; }
      const facing = -(nx * v2.x + ny * v2.y);
      if (!best || facing > best.facing) best = { a, c, len, nx, ny, facing };
    });
    return best;
  };
  // 立面上真实的凹入深度:从外侧水平射线打到建筑网格,取最远一档命中(凹窗面板),灯片放在面板前 3 cm
  const buildingsMesh = [];
  city.traverse(o => { if (o.isMesh && /^B\d{3}/.test(o.name)) buildingsMesh.push(o); });
  const ray = new THREE.Raycaster();
  let emitterMat;
  if (PARAMS.warmMode === 'upglow') {
    // 玻璃里的暖光:底部最亮、向上约 70% 高度内柔和减弱,不是一整块均匀颜色
    const c = document.createElement('canvas'); c.width = 4; c.height = 128;
    const g = c.getContext('2d'), grad = g.createLinearGradient(0, 128, 0, 0);
    grad.addColorStop(0, '#ffffff'); grad.addColorStop(.35, '#8a8a8a'); grad.addColorStop(.75, '#1c1c1c'); grad.addColorStop(1, '#000000');
    g.fillStyle = grad; g.fillRect(0, 0, 4, 128);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.NoColorSpace;
    disposables.push(tex);
    // 叠加混合:渐变暗的部分不遮挡后面的玻璃(不透明时会出现黑条)
    emitterMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(PARAMS.warm.color).multiplyScalar(PARAMS.warm.emitter * 1.4), map: tex, side: THREE.DoubleSide,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
  } else {
    emitterMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(PARAMS.warm.color).multiplyScalar(PARAMS.warm.emitter), side: THREE.DoubleSide });
  }
  const fixtureMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(PARAMS.warm.color).multiplyScalar(2.2) });
  disposables.push(emitterMat, fixtureMat);
  const uplights = [];
  disposables.push(emitterMat);
  const warmGroup = new THREE.Group();
  warmGroup.name = 'v23 warm emitters';
  const lampCandidates = [];

  const low = plan.buildings.filter(b => b.h < 26 && b.kind !== 'gable')
    .map(b => ({ b, q: project([b.x, b.y, b.z + 1]) }))
    .filter(({ q }) => q.x > -.95 && q.x < .95 && q.y > -.9 && q.y < .6)
    .sort((a, b) => a.q.y - b.q.y);
  const chosen = [];
  for (const { b } of low) {
    if (chosen.every(c => Math.hypot(c.x - b.x, c.y - b.y) > 30)) chosen.push(b);
    if (chosen.length >= 8) break;
  }
  let placed = 0, probes = 0;
  for (const b of chosen) {
    const f = facade(b);
    if (f.facing < .2) continue;
    // 从下往上探测立面深度:一层是否比上层立面缩进(檐下空间),以及檐口在多高
    const depthAt = (t, z) => {
      const x = f.a[0] + (f.c[0] - f.a[0]) * t, y = f.a[1] + (f.c[1] - f.a[1]) * t;
      ray.set(convert([x + f.nx * 6, y + f.ny * 6, z]), convert([-f.nx, -f.ny, 0]).normalize());
      ray.far = 14;
      probes++;
      const hit = ray.intersectObjects(buildingsMesh, false)[0];
      return hit ? hit.distance - 6 : null;       // 相对占地边界向内为正
    };
    // 一层凹窗面板的深度:几处水平采样取最深值;外框/竖梃比它浅,会自然遮住一部分灯片
    const samples = [.3, .5, .7].map(t => depthAt(t, b.z + 1.3)).filter(v => v !== null);
    const lower = samples.length ? Math.max(...samples) : null;
    (report.depthProbe ??= []).push({ id: b.id, lower: lower && +lower.toFixed(2) });
    if (lower === null || lower < .3) continue;   // 没有足够深的凹窗:不贴灯片
    // A. 薄灯片:一层凹窗面板前 4 cm,高度只到一层窗顶
    const d = lower - .04;
    const t0 = .06, t1 = .94;
    const p0 = [f.a[0] + (f.c[0] - f.a[0]) * t0 - f.nx * d, f.a[1] + (f.c[1] - f.a[1]) * t0 - f.ny * d];
    const p1 = [f.a[0] + (f.c[0] - f.a[0]) * t1 - f.nx * d, f.a[1] + (f.c[1] - f.a[1]) * t1 - f.ny * d];
    const width = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), height = Math.min(2.5, b.h * .2);
    const soffit = b.z + .25 + height;
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(width, height), emitterMat);
    disposables.push(plane.geometry);
    plane.position.copy(convert([(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, b.z + .25 + height / 2]));
    plane.rotation.y = Math.atan2(p1[1] - p0[1], p1[0] - p0[0]);
    plane.layers.enable(BLOOM_LAYER);
    plane.castShadow = false; plane.receiveShadow = false;
    if (PARAMS.warmMode !== 'up') { warmGroup.add(plane); placed++; }
    if (PARAMS.warmMode !== 'plane') {
      // 洗墙灯:立面前 0.35 m 的地面上,朝上照向本立面;灯具是地面上一个很小的发光块
      for (const t of [.25, .75]) {
        const gx = f.a[0] + (f.c[0] - f.a[0]) * t, gy = f.a[1] + (f.c[1] - f.a[1]) * t;
        const spot = new THREE.SpotLight(new THREE.Color(PARAMS.warm.lightColor), PARAMS.uplight.intensity, b.h * 1.2, PARAMS.uplight.angle, 1, 2);
        spot.position.copy(convert([gx + f.nx * .35, gy + f.ny * .35, b.z + .12]));
        spot.target.position.copy(convert([gx - f.nx * .2, gy - f.ny * .2, b.z + b.h * PARAMS.uplight.reach]));
        scene.add(spot, spot.target);
        const fixture = new THREE.Mesh(new THREE.BoxGeometry(.5, .06, .5), fixtureMat);
        disposables.push(fixture.geometry);
        fixture.position.copy(convert([gx + f.nx * .35, gy + f.ny * .35, b.z + .03]));
        fixture.layers.enable(BLOOM_LAYER);
        warmGroup.add(fixture);
        uplights.push(b.id);
      }
    }
    lampCandidates.push({ b, f, q: project([b.x, b.y, b.z]), lower, soffit });
  }
  scene.add(warmGroup);

  // B:只给画面中部最显眼的几处开口配真实暖灯,放在开口外 0.8 m、一层高度,照向路面与相邻墙面
  const lamps = lampCandidates.sort((a, b) => Math.abs(a.q.x) - Math.abs(b.q.x)).slice(0, PARAMS.warm.lights);
  for (const { b, f } of lamps) {
    // 檐下向下的聚光灯:外框前 0.6 m、离地 2.3 m,照向门前 2.5 m 的地面;锥角以外(包括上层墙面)不受光
    const mx = (f.a[0] + f.c[0]) / 2 + f.nx * .6, my = (f.a[1] + f.c[1]) / 2 + f.ny * .6;
    const lamp = new THREE.SpotLight(new THREE.Color(PARAMS.warm.lightColor), PARAMS.warm.lightIntensity, PARAMS.warm.lightDistance, .95, .85, 2);
    lamp.position.copy(convert([mx, my, b.z + 2.3]));
    lamp.target.position.copy(convert([mx + f.nx * 1.9, my + f.ny * 1.9, b.z]));
    scene.add(lamp, lamp.target);
  }
  report.uplights = uplights.length;
  report.warm = { candidates: chosen.length, emitters: placed, probes, lamps: lamps.map(l => l.b.id) };
}

// ---------------------------------------------------------------- 后处理:只有一次色调映射
function buildPost() {
  const w = host.clientWidth, h = host.clientHeight;
  const rt = () => new THREE.WebGLRenderTarget(w, h, { type: THREE.HalfFloatType, samples: 4 });
  composer = new EffectComposer(renderer, rt());
  composer.addPass(new RenderPass(scene, camera));
  if (PARAMS.ao.enabled) {
    const ao = new GTAOPass(scene, camera, w, h);
    ao.updateGtaoMaterial({ radius: PARAMS.ao.radius, thickness: PARAMS.ao.thickness, distanceExponent: 1.5, scale: 1, samples: 16 });
    ao.blendIntensity = PARAMS.ao.blend;
    composer.addPass(ao);
    report.ao = { blend: PARAMS.ao.blend, radius: PARAMS.ao.radius };
  }
  if (STAGE === 'final') {
    // 选择性 Bloom:单独一套 composer 只看得见灯片,其余网格临时换成黑色材质(保留遮挡)
    bloomComposer = new EffectComposer(renderer, rt());
    bloomComposer.renderToScreen = false;
    bloomComposer.addPass(new RenderPass(scene, camera));
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), PARAMS.bloom.strength, PARAMS.bloom.radius, PARAMS.bloom.threshold);
    bloomComposer.addPass(bloomPass);
    const mix = new ShaderPass(new THREE.ShaderMaterial({
      // 只取辉光本身(UnrealBloomPass 内部合成好的模糊层),不取 composer 输出 ——
      // composer 输出里还带着灯片原色,再加到主画面上等于灯片亮度翻倍,暖色会被色调映射冲成白色
      uniforms: { baseTexture: { value: null }, bloomTexture: { value: bloomPass.renderTargetsHorizontal[0].texture } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: 'uniform sampler2D baseTexture; uniform sampler2D bloomTexture; varying vec2 vUv; void main(){ vec4 b = texture2D(baseTexture, vUv); gl_FragColor = vec4(b.rgb + texture2D(bloomTexture, vUv).rgb, b.a); }',
    }), 'baseTexture');
    mix.needsSwap = true;
    composer.addPass(mix);
  }
  composer.addPass(new OutputPass());          // 唯一的色调映射 + sRGB 转换
}

const black = new THREE.MeshBasicMaterial({ color: 0x000000 });
const stash = new Map();
function renderFrame() {
  frameCamera();
  if (bloomComposer) {
    scene.traverse(o => {
      if (o.isMesh && !o.layers.isEnabled(BLOOM_LAYER)) { stash.set(o, o.material); o.material = black; }
    });
    const env = scene.environment; scene.environment = null;
    renderer.shadowMap.autoUpdate = false;
    bloomComposer.render();
    renderer.shadowMap.autoUpdate = true;
    scene.environment = env;
    for (const [o, m] of stash) o.material = m;
    stash.clear();
  }
  composer.render();
  host.dataset.frames = String(Number(host.dataset.frames || 0) + 1);
}

// ---------------------------------------------------------------- 启动
try {
  plan = await json('./blender/city-14-studio-plan.json');
  cameraSpec = { ...plan.composition_camera };
  workspace.style.aspectRatio = `${cameraSpec.captured_viewport[0]} / ${cameraSpec.captured_viewport[1]}`;
  if (VIEW === 'sample') {
    // 调试小样:同一视线方向,推近到一座塔楼及其周边的中/低层建筑与地面
    const tower = plan.buildings.find(b => b.id === (q.get('building') || 'B004'));
    const dir = cameraSpec.target.map((v, i) => v - cameraSpec.position[i]);
    const target = [tower.x - 10, tower.y - 22, tower.z + 14];
    cameraSpec.target = target;
    cameraSpec.position = target.map((v, i) => v - dir[i]);
    cameraSpec.sampleSpan = num('span', 150);
  }
  camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 6000);
  camera.position.copy(convert(cameraSpec.position));
  camera.up.set(0, 1, 0);
  camera.zoom = VIEW === 'sample' ? 1 : (cameraSpec.zoom ?? 1);   // 锁定机位自带缩放,漏掉会让城市缩成一小块
  camera.lookAt(convert(cameraSpec.target));
  camera.updateMatrixWorld();

  renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, premultipliedAlpha: false, powerPreference: 'high-performance' });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(PARAMS.pixelRatio);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = PARAMS.toneMapping;
  renderer.toneMappingExposure = PARAMS.exposure;
  renderer.shadowMap.enabled = PARAMS.shadow.enabled;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  host.append(renderer.domElement);
  scene = new THREE.Scene();

  const draco = new DRACOLoader().setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/');
  const gltf = await new GLTFLoader().setDRACOLoader(draco).loadAsync('./blender/city-13-smooth.glb?v=1', p => {
    if (p.total) loadingCopy.textContent = `正在加载白模… ${Math.round(p.loaded / p.total * 100)}%`;
  });
  draco.dispose();
  city = gltf.scene;
  applyMaterials(city);
  scene.add(city);
  city.updateMatrixWorld(true);
  // 城市包围盒:用 164 栋建筑的占地与高度求,不用整个网格 —— 地形前景一直延伸到镜头后方,
  // 用它会让灯光位置和阴影范围大一个数量级、阴影精度被浪费
  const modelBounds = new THREE.Box3().setFromObject(city);
  bounds = new THREE.Box3();
  for (const b of plan.buildings) for (const [x, y] of b.footprint) {
    bounds.expandByPoint(convert([x, y, b.z - 2]));
    bounds.expandByPoint(convert([x, y, b.z + b.h]));
  }
  bounds.expandByVector(new THREE.Vector3(60, 0, 60));
  bounds.min.y = modelBounds.min.y;
  report.modelBounds = { min: modelBounds.min.toArray().map(v => +v.toFixed(1)), max: modelBounds.max.toArray().map(v => +v.toFixed(1)) };
  report.bounds = { min: bounds.min.toArray().map(v => +v.toFixed(1)), max: bounds.max.toArray().map(v => +v.toFixed(1)) };
  let tris = 0; city.traverse(o => { if (o.isMesh) tris += (o.geometry.index?.count ?? o.geometry.attributes.position.count) / 3; });
  report.triangles = tris;

  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w, h, false);
  frameCamera();
  buildLights();
  if (STAGE !== 'neutral') buildWarm();
  buildPost();

  const t0 = performance.now();
  renderFrame();
  renderer.getContext().finish();
  report.firstFrameMs = Math.round(performance.now() - t0);
  const t1 = performance.now();
  renderFrame();
  renderer.getContext().finish();
  report.frameMs = Math.round(performance.now() - t1);
  report.info = { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles, geometries: renderer.info.memory.geometries, textures: renderer.info.memory.textures };
  new ResizeObserver(() => {
    const W = host.clientWidth, H = host.clientHeight;
    if (!W || !H) return;
    renderer.setSize(W, H, false); composer.setSize(W, H); bloomComposer?.setSize(W, H);
    requestAnimationFrame(renderFrame);
  }).observe(workspace);
  loading.hidden = true;
  host.dataset.loaded = 'true';
  document.querySelector('#summary').textContent = `${plan.buildings.length} 栋建筑 · 实时 PBR 白模 · 阶段 ${STAGE}${VIEW === 'sample' ? ' · 调试小样' : ''}`;
} catch (error) {
  console.error(error);
  report.error = String(error?.stack || error);
  status('城市场景暂时无法加载，请重试。', true);
}
