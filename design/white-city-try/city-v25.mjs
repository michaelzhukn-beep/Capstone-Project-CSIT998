// v25 洁净白模城市:在 v24 的实时 PBR 管线上,只改"光从哪来"这一件事。
//
// 诊断依据(见 NOTES.md 第 2 节,全部为本机实拍测量):
//   · ?env=0 时城市均值 240 → 162,环境照明在扛几乎全部亮度
//   · 只留环境光(关主光/填光)时,城市 5% 分位仍是 182 —— 暗部完全由环境产生
//   · 开/关 AO 均值只差 1.2 级,开/关阴影只差 1.1 级 —— 两者都不是"灰"的成因
//   · 原环境贴图是 RoomEnvironment(一个"房间",辐照度强方向性),它按法线方向逐面变化,
//     于是每根竖梃、每块凹窗面板各拿一个不同的值 —— 幕墙网格因此被画出来
//
// 改法:把主导光换成"只随高度变化"的中性棚拍环境(垂直渐变 equirect → PMREM)。
// 这样任意两个竖直面(幕墙 / 竖梃 / 凹窗侧壁)拿到完全相同的辐照度,网格在光里消失;
// 而屋顶(朝上)、墙面(竖直)、檐下(朝下)仍然分得开,体积由朝向而不是由细节提供。
// 不需要改几何、不需要改模型、不需要 shader 特技。
//
// 阶段(?stage=):neutral 中性白模 / warm 加暖光无辉光 / final 加极轻辉光(默认)
// 视图(?view=):city 锁定机位全城(默认) / sample 同方向推近的低中高楼+地面小样
// 单项调试:?exposure= ?key= ?fill= ?env= ?envTop= ?envHorizon= ?envBottom=
//          ?shadow= ?shadowmap= ?ao= ?haze= ?panel= ?entint= ?bloom= ?warm=0
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
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';

// ---------------------------------------------------------------- 集中参数
const q = new URLSearchParams(location.search);
const num = (k, d) => (q.has(k) && Number.isFinite(Number(q.get(k))) ? Number(q.get(k)) : d);
// 阶段默认值:按新版提示词,第一阶段禁止暖光主导 —— 默认就是 neutral(无灯片、无暖地反射、无 Bloom)
const STAGE = ['neutral', 'warm', 'final'].includes(q.get('stage')) ? q.get('stage') : 'neutral';
const VIEW = q.get('view') === 'sample' ? 'sample' : 'city';

// 模型表:默认就是 v24 在用的那座城市(164 栋)。其余是同一条设计线的其它 LOD,仅供对照。
const MODELS = {
  '13smooth': { glb: '../white-city/blender/city-13-smooth.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  // 体块化重导出:同一布局、同一相机,只把立面的肋/凹窗/倒角推平(见 blender/massing.py)
  'massing15': { glb: 'blender/city-massing-1.5.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  'massing08': { glb: 'blender/city-massing-0.8.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  'massing04': { glb: 'blender/city-massing-0.4.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  // 几何可见性烘焙:逐面射线遮挡写进顶点色(blender/bake_occlusion.py)
  'ao': { glb: 'blender/city-ao2.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  // Cycles 间接光烘焙(只烘 indirect 通道)写进顶点色,见 blender/bake_gi.py
  'gi': { glb: 'blender/city-gi.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  // 立面分格"减弱深度"(不推平):分格仍在,缝的明暗差按比例变小,见 blender/shrink_facades.py
  'shrink30': { glb: 'blender/city-shrink30.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  'shrink12': { glb: 'blender/city-shrink12.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  'shrink25': { glb: 'blender/city-shrink25.glb', plan: '../white-city/blender/city-14-studio-plan.json', cam: 'composition_camera' },
  '13layout': { glb: '../white-city/blender/city-13-layout.glb', plan: '../white-city/blender/city-13-layout-plan.json', cam: 'composition_camera' },
  '12master': { glb: '../white-city/blender/city-12-master.glb', plan: '../white-city/blender/city-12-master-plan.json', cam: 'cameras.front' },
};
const MODEL = MODELS[q.get('model')] ? q.get('model') : 'gi';

export const PARAMS = {
  model: MODEL,
  // 顶点色承载烘焙好的几何可见性(逐面遮挡);只有烘过的模型才有 COLOR_0。
  // 默认跟着模型走 —— 给没有顶点色的模型开 vertexColors 会把它整个涂黑(踩过)。
  vertexColors: num('vcol', MODEL === 'ao' || MODEL === 'gi' ? 1 : 0) === 1,
  // 烘焙出来的间接光是"物理量",不能直接当乘数:它的量级(mean≈0.11)远低于 1,
  // 直接乘会把整座城压到 11% 亮度。这里按全局分布归一化后重映射到一个乘数区间。
  gi: { lo: num('gilo', .88), hi: num('gihi', 1.02), gamma: num('gigamma', 1) },
  toneMapping: { neutral: THREE.NeutralToneMapping, agx: THREE.AgXToneMapping, aces: THREE.ACESFilmicToneMapping }[q.get('tonemap') || 'neutral'],
  pixelRatio: num('pr', 1),
  exposure: num('exposure', 1.0),

  // 实心白色非金属 PBR。凹窗面板默认与主体同色 —— 面板比主体深一档会把幕墙网格重新画出来。
  materials: {
    building: { color: '#F4F4F1', roughness: .72 },
    roof:     { color: '#F6F6F3', roughness: .78 },
    panel:    { color: q.get('panel') || '#F3F3F0', roughness: .70 },
    ground:   { color: '#F5F5F2', roughness: .90 },
    road:     { color: '#F2F2EE', roughness: .92 },
    water:    { color: '#EFF1F0', roughness: .62 },
    crown:    { color: '#F5F5F2', roughness: .86 },
    branch:   { color: '#E8E8E3', roughness: .86 },
  },

  // 主导光:垂直渐变的中性棚拍环境。只随高度变化 ⇒ 竖直面之间无差异。
  // 下半球带一点暖:参考图的暖不是几根灯带,而是街面暖光自下而上的反弹(R−B≈9)。
  studio: {
    top: num('envTop', 1.35),          // 天顶辐亮度(线性)
    horizon: num('envHorizon', 1.00),  // 地平线
    bottom: num('envBottom', .78),     // 地面反射:街面暖光自下而上反弹的强度
    topColor: q.get('envTopColor') || '#FFFFFF',
    horizonColor: q.get('envHorizonColor') || '#FFFDFA',
    bottomColor: q.get('envBottomColor') || '#FFEEDA',
    sharp: num('envSharp', .55),       // 渐变指数:越小越接近均匀
    intensity: num('env', .58),
    legacy: q.get('envmap') === 'room',  // 回退到 v24 的 RoomEnvironment,用于对照
  },

  // 主光只负责"正立面 vs 侧立面"的浅浅区别。实测:压低到 0.85 网格几乎消失但城市变平,
  // 提到 2.4 体量和接地关系立住、网格也只回到很轻的程度 —— 取 2.4。
  key:  { offset: (q.get('keydir') || '.35,.72,.5').split(',').map(Number), color: '#FFFFFF', intensity: num('key', 2.2) },
  fill: { offset: (q.get('filldir') || '-.55,.3,.35').split(',').map(Number), color: '#FFFFFF', intensity: num('fill', .70) },

  // 主页构图候选:锁定机位不动,只调"后撤/画面内垂直位置/机位高度"这三个自由度。
  // zoom<1 = 后撤(城市变小);pan>0 = 画面窗口上移(城市在画面里下沉);eye<1 = 机位降低。
  // 主页构图:所有者用 ?tune=1 滑杆现场定稿 —— zoom 0.75 / pan 0.06。
  // 正交相机 + 容器 aspect-ratio 锁比例 ⇒ 整幅画面是分辨率无关的图,等比例缩放构图不变。
  camera: { zoom: num('zoom', .75), pan: num('pan', .06), eye: num('eye', 1) },

  // 后撤之后地形前场会在画面底部露出硬边。用画布自身的 alpha 遮罩把它淡出:
  // 遮罩淡的是画布透明度,底下页面背景(任意渐变)自然透出来 ⇒ 按构造就无缝,不用配色。
  // 后撤之后地形前场边界会在画面约 76% 高度处露出,用很轻的底部渐隐收口。
  fade: { start: num('fadestart', 91), end: num('fadeend', 100) },

  shadow: { enabled: num('shadow', 1) === 1, mapSize: num('shadowmap', 4096), bias: num('bias', -.0004), normalBias: num('nbias', .05), radius: num('sradius', 2.5) },
  // AO 只用来补"楼群内部与楼底的接触关系"。v24 的 2.2 半径在本尺度下等于没有(开关均值只差 1.2 级);
  // 10 个设计单位才够到楼与楼之间的缝。体块化之后几何变平,靠它把层次找回来。
  ao: { enabled: num('ao', 1) === 1, radius: num('aoradius', 10), thickness: num('aothick', 2), blend: num('aoblend', .35) },

  // 空气感:向页面背景色淡出,压掉远景对比。这一项是**把中间调做出来的主力** ——
  // 实测中间调 215-231 从 8.6% 提到 24.1%,而 Cycles 间接光烘焙两轮加起来只买到 4.6 个点。
  haze: { amount: num('haze', 1.0), near: num('hazenear', 400), far: num('hazefar', 2400), color: q.get('hazecolor') || '#F8F7F4' },

  warm: {
    enabled: num('warm', 1) === 1,
    count: num('warmcount', 22),
    color: '#FFF1DE',        // 低饱和暖白
    emitter: num('emit', 2.2),   // 灯片线性强度(带竖直渐变,不再是一块平板)
    inset: num('inset', .35),    // 灯片退进立面的距离(没有探测到凹窗深度时用)
    lightColor: '#FFE9CE',
    lightIntensity: num('lamp', 1500),
    lightDistance: num('lampdist', 26),
    lights: num('warmlights', 8),
  },
  bloom: { strength: num('bloom', .09), radius: .08, threshold: 0 },
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
const report = window.__v25 = { stage: STAGE, view: VIEW, model: MODEL, params: PARAMS };

let renderer, scene, camera, cameraSpec, plan, composer, bloomComposer, city, bounds;
const disposables = [];

async function json(url) { const r = await fetch(url, { cache: 'no-store' }); if (!r.ok) throw new Error(`Unavailable: ${url}`); return r.json(); }
const pick = (obj, path) => path.split('.').reduce((o, k) => o?.[k], obj);

// ---------------------------------------------------------------- 相机
function frameCamera() {
  const w = host.clientWidth, h = host.clientHeight;
  if (!w || !h) return;
  const aspect = w / h;
  const span = VIEW === 'sample' ? cameraSpec.sampleSpan
    : cameraSpec.scale * Math.max(1, aspect / (cameraSpec.reference_aspect ?? 1600 / 1100));
  const halfW = span / 2, halfH = span / aspect / 2;
  const py = PARAMS.camera.pan * halfH * 2;      // 窗口上移 ⇒ 城市在画面里下沉
  camera.zoom = VIEW === 'sample' ? 1 : (cameraSpec.zoom ?? 1) * PARAMS.camera.zoom;
  Object.assign(camera, { left: -halfW, right: halfW, top: halfH + py, bottom: -halfH + py });
  camera.updateProjectionMatrix();
}

// ---------------------------------------------------------------- 中性棚拍环境
// 一个只随仰角变化的辐亮度球壳 → PMREM。没有颜色倾向,没有窗口形状,
// 因此不产生任何"按法线方向逐面变化"的假细节。
// 用场景球壳而不是 DataTexture:PMREM 对 float 贴图的线性过滤在本机拿不到值(实测环境全黑)。
function studioEnvironment(renderer, spec) {
  const envScene = new THREE.Scene();
  const geo = new THREE.SphereGeometry(50, 32, 24);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    uniforms: {
      top: { value: new THREE.Color(spec.topColor).multiplyScalar(spec.top) },
      horizon: { value: new THREE.Color(spec.horizonColor).multiplyScalar(spec.horizon) },
      bottom: { value: new THREE.Color(spec.bottomColor).multiplyScalar(spec.bottom) },
      sharp: { value: spec.sharp },
    },
    vertexShader: 'varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: [
      'uniform vec3 top; uniform vec3 horizon; uniform vec3 bottom; uniform float sharp;',
      'varying vec3 vDir;',
      'void main(){',
      '  float e = clamp(vDir.y, -1.0, 1.0);',
      '  vec3 c = e >= 0.0 ? mix(horizon, top, pow(e, sharp)) : mix(horizon, bottom, pow(-e, sharp));',
      '  gl_FragColor = vec4(c, 1.0);',
      '}',
    ].join('\n'),
  });
  envScene.add(new THREE.Mesh(geo, mat));
  const pmrem = new THREE.PMREMGenerator(renderer);
  const target = pmrem.fromScene(envScene, 0);
  pmrem.dispose(); geo.dispose(); mat.dispose();
  return target;
}

// ---------------------------------------------------------------- 体块化着色(可选)
// 幕墙竖梃与玻璃面板的法线互相垂直,任何"能区分立面朝向"的光同时也会区分竖梃朝向,
// 于是窗格网格被画出来 —— 这跟立面的明暗层次是同一个量,靠调光分不开。
// 这里按容差合并同位置顶点后重算法线:容差取窗格尺度时,一根竖梃的顶点会和它背后的
// 玻璃面板合并,法线被平均掉;而 30 单位开外的楼角不会合并,轮廓保持锐利。
// 不改几何形状、不改布局、不改模型文件,只是一个可关的着色开关。
function massingNormals(meshes, report, tol) {
  const t0 = performance.now();
  let before = 0, after = 0;
  for (const o of meshes) {
    const g = o.geometry;
    before += g.attributes.position.count;
    const c = g.clone();
    c.deleteAttribute('normal');
    if (c.attributes.uv) c.deleteAttribute('uv');
    if (c.attributes.tangent) c.deleteAttribute('tangent');
    const m = mergeVertices(c, tol);
    m.computeVertexNormals();
    after += m.attributes.position.count;
    c.dispose(); g.dispose();
    o.geometry = m;
  }
  report.massing = { meshes: meshes.length, before, after, ms: Math.round(performance.now() - t0), tol };
}

// ---------------------------------------------------------------- 材质
function standard(spec) {
  // 这里**不要**开 vertexColors:开了以后所有网格一起生效,没有 COLOR_0 的网格会被涂黑。
  // 顶点色只在 applyMaterials 里按网格有无属性挑选 Mvc 变体。
  const m = new THREE.MeshStandardMaterial({ color: new THREE.Color(spec.color), roughness: spec.roughness, metalness: 0 });
  disposables.push(m);
  return m;
}

function applyMaterials(model) {
  const M = Object.fromEntries(Object.entries(PARAMS.materials).map(([k, v]) => [k, standard(v)]));
  // ?side=1 关背面剔除 —— 用来判别"细黑线"是不是缝隙里露出的背面
  if (num('side', 0) === 1) for (const m of Object.values(M)) { m.side = THREE.DoubleSide; m.needsUpdate = true; }
  // 顶点色必须"按网格"开关:没有 COLOR_0 的网格(地形/道路/水面/树)若也开 vertexColors,
  // WebGL 对缺失属性取默认 (0,0,0),材质颜色会被乘成黑色 —— 实测把整个前景涂黑了。
  const Mvc = {};
  if (PARAMS.vertexColors) {
    for (const [k, m] of Object.entries(M)) { const c = m.clone(); c.vertexColors = true; disposables.push(c); Mvc[k] = c; }
  }
  const byName = {
    '13 White clay': 'building', '13 Recessed white panels': 'panel', '13 Pavement': 'road',
    '13 Still water': 'water', '13 Tree crowns': 'crown', '13 Branches': 'branch',
  };
  const used = {};
  const facadeMeshes = [];
  model.traverse(o => {
    if (!o.isMesh) return;
    const list = Array.isArray(o.material) ? o.material : [o.material];
    if (list.some(m => /White clay|Recessed/.test(m.name))) facadeMeshes.push(o);
    const next = list.map(old => {
      let key = byName[old.name];
      if (old.name === '13 Roof and stone') key = /terrain|lake|road/i.test(o.name) ? 'ground' : 'roof';
      key ??= 'building';
      used[`${o.name} / ${old.name}`] = key;
      old.dispose();
      return (PARAMS.vertexColors && o.geometry.attributes.color) ? Mvc[key] : M[key];
    });
    o.material = Array.isArray(o.material) ? next : next[0];
    o.castShadow = !/lake/i.test(o.name);
    // 凹窗面板不接收阴影:退进立面里的面板若吃到自阴影,幕墙网格会再次显出来
    o.receiveShadow = !/Recessed/i.test(o.name);
  });
  report.materialMap = used;
  // 归一化重映射:raw 间接光 → 乘数 [lo, hi]。先扫全局最大值,再逐顶点映射。
  if (PARAMS.vertexColors && MODEL === 'gi') {
    let mx = 1e-6;
    model.traverse(o => { const a = o.isMesh && o.geometry.attributes.color; if (a) for (let i = 0; i < a.count; i++) mx = Math.max(mx, a.getX(i)); });
    const { lo, hi, gamma } = PARAMS.gi;
    model.traverse(o => {
      const a = o.isMesh && o.geometry.attributes.color;
      if (!a) return;
      for (let i = 0; i < a.count; i++) {
        const t = Math.min(1, a.getX(i) / mx);
        a.setX(i, lo + (hi - lo) * Math.pow(t, gamma));
        a.setY(i, lo + (hi - lo) * Math.pow(t, gamma));
        a.setZ(i, lo + (hi - lo) * Math.pow(t, gamma));
      }
      a.needsUpdate = true;
    });
    report.giRemap = { max: +mx.toFixed(4), lo, hi, gamma };
  }
  // 诊断:核对顶点色到底有没有、值域多少、材质是否真的开了 vertexColors
  const cs = { meshes: 0, withColor: 0, min: 9, max: -9, sum: 0, n: 0, vcMaterials: 0 };
  model.traverse(o => {
    if (!o.isMesh) return;
    cs.meshes++;
    const list = Array.isArray(o.material) ? o.material : [o.material];
    if (list.some(m => m.vertexColors)) cs.vcMaterials++;
    const a = o.geometry.attributes.color;
    if (!a) return;
    cs.withColor++;
    for (let i = 0; i < a.count; i++) {
      const v = a.getX(i);
      if (v < cs.min) cs.min = v;
      if (v > cs.max) cs.max = v;
      cs.sum += v; cs.n++;
    }
  });
  cs.mean = cs.n ? +(cs.sum / cs.n).toFixed(3) : null;
  cs.min = cs.n ? +cs.min.toFixed(3) : null;
  cs.max = cs.n ? +cs.max.toFixed(3) : null;
  delete cs.sum; delete cs.n;
  report.colorStats = cs;
  return facadeMeshes;
}

// ---------------------------------------------------------------- 灯光
function buildLights() {
  const size = bounds.getSize(new THREE.Vector3()), center = bounds.getCenter(new THREE.Vector3());
  const W = size.x;
  const place = (spec, shadow) => {
    const light = new THREE.DirectionalLight(new THREE.Color(spec.color), spec.intensity);
    light.position.copy(center).add(new THREE.Vector3(...spec.offset).multiplyScalar(W));
    light.target.position.copy(center);
    scene.add(light, light.target);
    if (shadow) fitShadow(light);
    return light;
  };
  const key = place(PARAMS.key, PARAMS.shadow.enabled);
  const fill = place(PARAMS.fill, false);

  if (PARAMS.studio.legacy) {
    const pmrem = new THREE.PMREMGenerator(renderer);
    const t = pmrem.fromScene(new RoomEnvironment(), .04);
    pmrem.dispose();
    disposables.push(t);
    scene.environment = t.texture;
  } else {
    // 阶段 neutral 强制用中性地面反射:它要证明的是"没有任何暖光时,白模自身依然成立"。
    // warm / final 才启用暖地面反射 —— 参考图的暖主要来自街面自下而上的反弹,不是灯带。
    const spec = STAGE === 'neutral' ? { ...PARAMS.studio, bottomColor: '#FFFFFF' } : PARAMS.studio;
    const t = studioEnvironment(renderer, spec);
    disposables.push(t);
    scene.environment = t.texture;
    report.studio = { top: spec.top, horizon: spec.horizon, bottom: spec.bottom, topColor: spec.topColor, horizonColor: spec.horizonColor, bottomColor: spec.bottomColor, intensity: spec.intensity };
  }
  scene.environmentIntensity = PARAMS.studio.intensity;
  scene.background = null;                    // 背景交给页面:标题与输入框不受后期影响

  if (PARAMS.haze.amount > 0) {
    const col = new THREE.Color(PARAMS.haze.color);
    scene.fog = new THREE.Fog(col, PARAMS.haze.near, PARAMS.haze.near + (PARAMS.haze.far - PARAMS.haze.near) / Math.max(.01, PARAMS.haze.amount));
  }
  report.lights = { W: +W.toFixed(1), center: center.toArray().map(v => +v.toFixed(1)), key: key.position.toArray().map(v => +v.toFixed(1)) };
}

function fitShadow(light) {
  light.castShadow = true;
  const s = light.shadow;
  s.mapSize.set(PARAMS.shadow.mapSize, PARAMS.shadow.mapSize);
  s.bias = PARAMS.shadow.bias;
  s.normalBias = PARAMS.shadow.normalBias;
  s.radius = PARAMS.shadow.radius;
  const cam = s.camera;
  cam.position.copy(light.position);
  cam.lookAt(light.target.position);
  cam.updateMatrixWorld();
  const box = new THREE.Box3();
  for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
    box.expandByPoint(new THREE.Vector3(x, y, z).applyMatrix4(cam.matrixWorldInverse));
  }
  cam.left = box.min.x - 2; cam.right = box.max.x + 2; cam.bottom = box.min.y - 2; cam.top = box.max.y + 2;
  cam.near = Math.max(.5, -box.max.z - 5); cam.far = -box.min.z + 5;
  cam.updateProjectionMatrix();
  report.shadow = { map: PARAMS.shadow.mapSize, width: +(box.max.x - box.min.x).toFixed(1), texel: +((box.max.x - box.min.x) / PARAMS.shadow.mapSize).toFixed(3) };
}

// ---------------------------------------------------------------- 暖光:A 灯片 / B 少量真实暖灯
function buildWarm() {
  const W_ = PARAMS.warm;
  const v2 = new THREE.Vector2(cameraSpec.target[0] - cameraSpec.position[0], cameraSpec.target[1] - cameraSpec.position[1]).normalize();
  const project = p => convert(p).project(camera);
  const facade = b => {
    const fp = b.footprint, cx = fp.reduce((s, p) => s + p[0], 0) / fp.length, cy = fp.reduce((s, p) => s + p[1], 0) / fp.length;
    let best = null;
    fp.forEach((a, i) => {
      const c = fp[(i + 1) % fp.length], len = Math.hypot(c[0] - a[0], c[1] - a[1]);
      if (!len) return;
      let nx = (c[1] - a[1]) / len, ny = -(c[0] - a[0]) / len;
      if (nx * ((a[0] + c[0]) / 2 - cx) + ny * ((a[1] + c[1]) / 2 - cy) < 0) { nx = -nx; ny = -ny; }
      const facing = -(nx * v2.x + ny * v2.y);
      if (!best || facing > best.facing) best = { a, c, len, nx, ny, facing };
    });
    return best;
  };
  const buildingsMesh = [];
  city.traverse(o => { if (o.isMesh && /^B\d{3}/.test(o.name)) buildingsMesh.push(o); });
  const ray = new THREE.Raycaster();

  // 灯片用"下亮上透"的竖直渐变 + 普通透明混合,而不是一块不透明的均匀平板。
  // 均匀平板无论调多暗都读成"贴在墙上的黄板子";渐变才读成"光从楼底溢上来"。
  const cv = document.createElement('canvas'); cv.width = 4; cv.height = 64;
  const g2 = cv.getContext('2d');
  const grd = g2.createLinearGradient(0, 64, 0, 0);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(.40, 'rgba(255,255,255,0.55)');
  grd.addColorStop(.78, 'rgba(255,255,255,0.14)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g2.fillStyle = grd; g2.fillRect(0, 0, 4, 64);
  const gradTex = new THREE.CanvasTexture(cv);
  gradTex.colorSpace = THREE.NoColorSpace;   // 只有 alpha 起作用,颜色由材质 color 给
  const emitterMat = new THREE.MeshBasicMaterial({
    color: new THREE.Color(W_.color).multiplyScalar(W_.emitter),
    map: gradTex, transparent: true, depthWrite: false, side: THREE.DoubleSide,
  });
  const fixtureMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(W_.color).multiplyScalar(1.15) });
  disposables.push(emitterMat, fixtureMat, gradTex);
  const warmGroup = new THREE.Group();
  warmGroup.name = 'v25 warm emitters';

  const low = (plan.buildings || []).filter(b => b.h < 30 && b.kind !== 'gable' && b.footprint?.length)
    .map(b => ({ b, q: project([b.x, b.y, b.z + 1]) }))
    .filter(({ q }) => q.x > -.95 && q.x < .95 && q.y > -.95 && q.y < .75)
    .sort((a, b) => a.q.y - b.q.y);
  const chosen = [];
  for (const { b } of low) {
    if (chosen.every(c => Math.hypot(c.x - b.x, c.y - b.y) > 34)) chosen.push(b);
    if (chosen.length >= W_.count) break;
  }

  const depthAt = (f, t, z) => {
    if (!buildingsMesh.length) return null;
    const x = f.a[0] + (f.c[0] - f.a[0]) * t, y = f.a[1] + (f.c[1] - f.a[1]) * t;
    ray.set(convert([x + f.nx * 6, y + f.ny * 6, z]), convert([-f.nx, -f.ny, 0]).normalize());
    ray.far = 14;
    const hit = ray.intersectObjects(buildingsMesh, false)[0];
    return hit ? hit.distance - 6 : null;
  };

  let placed = 0;
  const candidates = [];
  for (const b of chosen) {
    const f = facade(b);
    if (!f || f.facing < .2) continue;
    const samples = [.3, .5, .7].map(t => depthAt(f, t, b.z + 1.3)).filter(v => v !== null);
    const lower = samples.length ? Math.max(...samples) : null;
    // 灯片退进立面的距离:探测到凹窗就用实测深度,否则用保守默认值
    const d = lower !== null && lower > .3 ? lower - .04 : W_.inset;
    const t0 = .08, t1 = .92;
    const p0 = [f.a[0] + (f.c[0] - f.a[0]) * t0 - f.nx * d, f.a[1] + (f.c[1] - f.a[1]) * t0 - f.ny * d];
    const p1 = [f.a[0] + (f.c[0] - f.a[0]) * t1 - f.nx * d, f.a[1] + (f.c[1] - f.a[1]) * t1 - f.ny * d];
    const width = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]);
    const height = Math.min(2.4, b.h * .18);
    if (width < 4) continue;
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(width, height), emitterMat);
    disposables.push(plane.geometry);
    plane.position.copy(convert([(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, b.z + .3 + height / 2]));
    plane.rotation.y = Math.atan2(p1[1] - p0[1], p1[0] - p0[0]);
    plane.layers.enable(BLOOM_LAYER);
    plane.castShadow = false; plane.receiveShadow = false;
    warmGroup.add(plane);
    placed++;
    candidates.push({ b, f, q: project([b.x, b.y, b.z]) });
  }
  scene.add(warmGroup);

  // B:只给画面最显眼的几处开口配真实暖灯。自发光不会照亮邻居 —— 承光必须来自真灯。
  const lamps = candidates.sort((a, b) => Math.abs(a.q.x) - Math.abs(b.q.x)).slice(0, W_.lights);
  for (const { b, f } of lamps) {
    const mx = (f.a[0] + f.c[0]) / 2 + f.nx * .7, my = (f.a[1] + f.c[1]) / 2 + f.ny * .7;
    const lamp = new THREE.SpotLight(new THREE.Color(W_.lightColor), W_.lightIntensity, W_.lightDistance, 1.0, .85, 2);
    lamp.position.copy(convert([mx, my, b.z + 2.4]));
    lamp.target.position.copy(convert([mx + f.nx * 1.6, my + f.ny * 1.6, b.z]));
    scene.add(lamp, lamp.target);
    const fixture = new THREE.Mesh(new THREE.BoxGeometry(.6, .07, .6), fixtureMat);
    disposables.push(fixture.geometry);
    fixture.position.copy(convert([mx, my, b.z + 2.36]));
    fixture.layers.enable(BLOOM_LAYER);
    warmGroup.add(fixture);
  }
  report.warm = { candidates: chosen.length, emitters: placed, lamps: lamps.length };
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
    // 选择性辉光:单独一套 composer 只看灯片层;其余网格临时换黑材质以保留遮挡
    bloomComposer = new EffectComposer(renderer, rt());
    bloomComposer.renderToScreen = false;
    bloomComposer.addPass(new RenderPass(scene, camera));
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), PARAMS.bloom.strength, PARAMS.bloom.radius, PARAMS.bloom.threshold);
    bloomComposer.addPass(bloomPass);
    const mix = new ShaderPass(new THREE.ShaderMaterial({
      // 只取辉光本身,不取 composer 输出(否则灯片原色被加两遍,暖色会被色调映射冲白)
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
    scene.traverse(o => { if (o.isMesh && !o.layers.isEnabled(BLOOM_LAYER)) { stash.set(o, o.material); o.material = black; } });
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
  const M = MODELS[MODEL];
  plan = await json(M.plan);
  cameraSpec = { ...(pick(plan, M.cam) || plan.composition_camera) };
  if (!cameraSpec?.position) throw new Error('plan 里没有可用相机: ' + M.cam);
  cameraSpec.scale ??= 736.7;
  workspace.style.aspectRatio = `${cameraSpec.captured_viewport?.[0] ?? 1883} / ${cameraSpec.captured_viewport?.[1] ?? 1054}`;
  if (VIEW === 'sample') {
    const tower = (plan.buildings || []).find(b => b.id === (q.get('building') || 'B004')) || plan.buildings?.[0];
    const dir = cameraSpec.target.map((v, i) => v - cameraSpec.position[i]);
    const target = [tower.x - 10, tower.y - 22, tower.z + 14];
    cameraSpec.target = target;
    cameraSpec.position = target.map((v, i) => v - dir[i]);
    cameraSpec.sampleSpan = num('span', 150);
  }
  camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 8000);
  const eyePos = convert(cameraSpec.position), eyeTgt = convert(cameraSpec.target);
  if (VIEW !== 'sample' && PARAMS.camera.eye !== 1) {
    // 只缩放相机相对目标的高度差 ⇒ 改变俯角,不动水平位置
    eyePos.y = eyeTgt.y + (eyePos.y - eyeTgt.y) * PARAMS.camera.eye;
  }
  camera.position.copy(eyePos);
  camera.up.set(0, 1, 0);
  // 锁定机位自带 zoom;主页构图候选在它之上再乘一个后撤系数(调试小样不受构图参数影响)
  camera.zoom = VIEW === 'sample' ? 1 : (cameraSpec.zoom ?? 1) * PARAMS.camera.zoom;
  camera.lookAt(eyeTgt);
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
  // 底部渐隐:只作用于画布,页面文字与输入框都在画布之外,不受影响
  if (PARAMS.fade.end > PARAMS.fade.start) {
    const g = `linear-gradient(180deg, #000 0%, #000 ${PARAMS.fade.start}%, rgba(0,0,0,0) ${PARAMS.fade.end}%)`;
    host.style.maskImage = g; host.style.webkitMaskImage = g;
  }
  scene = new THREE.Scene();

  const draco = new DRACOLoader().setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/');
  const gltf = await new GLTFLoader().setDRACOLoader(draco).loadAsync(M.glb, p => {
    if (p.total) loadingCopy.textContent = `正在加载白模… ${Math.round(p.loaded / p.total * 100)}%`;
  });
  draco.dispose();
  city = gltf.scene;
  const facadeMeshes = applyMaterials(city);
  if (num('massing', 0) > 0) massingNormals(facadeMeshes, report, num('massing', 0));
  scene.add(city);
  city.updateMatrixWorld(true);

  const modelBounds = new THREE.Box3().setFromObject(city);
  bounds = new THREE.Box3();
  for (const b of plan.buildings || []) for (const [x, y] of b.footprint || []) {
    bounds.expandByPoint(convert([x, y, b.z - 2]));
    bounds.expandByPoint(convert([x, y, b.z + b.h]));
  }
  bounds.expandByVector(new THREE.Vector3(60, 0, 60));
  bounds.min.y = modelBounds.min.y;
  report.modelBounds = { min: modelBounds.min.toArray().map(v => +v.toFixed(1)), max: modelBounds.max.toArray().map(v => +v.toFixed(1)) };
  report.buildings = (plan.buildings || []).length;
  let tris = 0; city.traverse(o => { if (o.isMesh) tris += (o.geometry.index?.count ?? o.geometry.attributes.position.count) / 3; });
  report.triangles = tris;

  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w, h, false);
  frameCamera();
  buildLights();
  if (STAGE !== 'neutral' && PARAMS.warm.enabled) buildWarm();
  buildPost();

  const t0 = performance.now();
  renderFrame();
  renderer.getContext().finish();
  report.firstFrameMs = Math.round(performance.now() - t0);
  new ResizeObserver(() => {
    const W = host.clientWidth, H = host.clientHeight;
    if (!W || !H) return;
    renderer.setSize(W, H, false); composer.setSize(W, H); bloomComposer?.setSize(W, H);
    requestAnimationFrame(renderFrame);
  }).observe(workspace);
  loading.hidden = true;
  host.dataset.loaded = 'true';
  // 机位微调面板:?tune=1 打开。拖到与目标构图重合后读出数字即可定稿。
  if (q.get('tune')) {
    const box = document.querySelector('#tune');
    const zoom = document.querySelector('#t-zoom'), zoomv = document.querySelector('#t-zoomv');
    const pan = document.querySelector('#t-pan'), panv = document.querySelector('#t-panv');
    const fade = document.querySelector('#t-fade'), fadev = document.querySelector('#t-fadev');
    zoom.value = String(PARAMS.camera.zoom); pan.value = String(PARAMS.camera.pan); fade.value = String(PARAMS.fade.start);
    const sync = () => {
      PARAMS.camera.zoom = Number(zoom.value); PARAMS.camera.pan = Number(pan.value); PARAMS.fade.start = Number(fade.value);
      zoomv.textContent = PARAMS.camera.zoom.toFixed(2);
      panv.textContent = PARAMS.camera.pan.toFixed(2);
      fadev.textContent = String(PARAMS.fade.start);
      const g = `linear-gradient(180deg, #000 0%, #000 ${PARAMS.fade.start}%, rgba(0,0,0,0) 100%)`;
      host.style.maskImage = g; host.style.webkitMaskImage = g;
      requestAnimationFrame(renderFrame);
    };
    [zoom, pan, fade].forEach(el => el.addEventListener('input', sync));
    sync();
    box.hidden = false;
    report.tune = true;
  }
  const summary = document.querySelector('#summary');
  if (summary) summary.textContent = `${report.buildings} 栋建筑 · 中性棚拍环境主导 · 阶段 ${STAGE}${VIEW === 'sample' ? ' · 调试小样' : ''}`;
} catch (error) {
  console.error(error);
  report.error = String(error?.stack || error);
  status('城市场景暂时无法加载，请重试。', true);
}
