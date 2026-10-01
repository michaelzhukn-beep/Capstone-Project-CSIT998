// v26 烘焙版白模城市:网页加载真实三维模型,光照来自 Cycles 烘焙贴图(不在网页里实时算光)。
// experimental。资产由 blender/bake_v26_city.py → export_v26_web.py、render_v26_trees.py 生成,见 LIGHTING_V24_EXPERIMENTS.md。
//
// 画面是锁定机位、不可交互的,所以允许「作弊」,但画面必须由模型绘制:
// - 楼 / 地形 / 道路 / 河 / 桥 / 地灯:无光照材质,颜色 = 烘焙贴图(已含 AgX 显示变换与曝光)
// - 树:4 个原型网格 × 1,394 个实例,颜色按锁定机位的画面位置从树木渲染层取色
// 色彩链路只有一处:贴图 sRGB 解码 → 线性 → 输出 sRGB;不做色调映射(烘焙时已做)。
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';

const q = new URLSearchParams(location.search);
const BASE = 'bake-v26/';
const WEBDIR = q.get('assets') || 'web';           // ?assets=web-partial 用于测试部分烘焙结果
const viewport = document.getElementById('viewport');
const workspace = document.getElementById('workspace');
const loading = document.getElementById('loading');
const loadingCopy = document.getElementById('loading-copy');
const report = window.__v26 = { stage: 'boot' };

function convert([x, y, z]) { return new THREE.Vector3(x, z, -y); }   // 设计坐标 Z 向上 → 网页 Y 向上(与 glTF 导出一致)

const TREE_VERT = /* glsl */`
  #include <common>
  void main() {
    vec4 wp = instanceMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * viewMatrix * modelMatrix * wp;
  }`;
const TREE_FRAG = /* glsl */`
  uniform sampler2D uLayer;
  uniform vec2 uSize;
  void main() {
    vec4 c = texture2D(uLayer, gl_FragCoord.xy / uSize);
    if (c.a < .5) discard;                  // 渲染层里此处不是树(例如树冠边缘外),交给后面的几何
    gl_FragColor = vec4(c.rgb, 1.0);
    #include <colorspace_fragment>
  }`;

async function main() {
  const spec = await (await fetch('blender/city-14-locked-camera.json', { cache: 'no-store' })).json();
  // Blender 相机的镜头偏移(export_v26_web.py 导出):单位是画面宽度的比例,烘焙贴图按带偏移的画框生成
  const bcam = await (await fetch(BASE + WEBDIR + '/camera.json', { cache: 'no-store' })).json().catch(() => ({ shift_x: -0.005787863861769438, shift_y: 0.019713403657078743 }));
  const [vw, vh] = bcam.resolution || spec.captured_viewport;     // 画框比例与烘焙用的 Blender 渲染分辨率一致
  workspace.style.aspectRatio = `${vw} / ${vh}`;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.setClearColor(0x000000, 0);
  viewport.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 6000);
  // 直接使用 Blender 相机的世界矩阵(Z 向上 → Y 向上),保证与烘焙画框逐像素一致
  if (bcam.matrix_world) {
    const m = bcam.matrix_world, C = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1);
    const B = new THREE.Matrix4().set(...m[0], ...m[1], ...m[2], ...m[3]);
    C.multiply(B).decompose(camera.position, camera.quaternion, camera.scale);
  } else {
    camera.position.copy(convert(spec.position)); camera.up.set(0, 1, 0); camera.lookAt(convert(spec.target));
  }

  const draco = new DRACOLoader().setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/');
  const loader = new GLTFLoader().setDRACOLoader(draco);
  const texLoader = new THREE.TextureLoader();
  const t0 = performance.now();
  loadingCopy.textContent = '正在加载烘焙模型…';
  const [cityGltf, treeGltf, layer] = await Promise.all([
    loader.loadAsync(BASE + WEBDIR + '/city-v26-baked.glb'),
    loader.loadAsync(BASE + WEBDIR + '/trees-v26.glb'),
    texLoader.loadAsync(BASE + 'trees-2x.png').catch(() => null),     // 树木层尚未生成时退回浅灰
  ]);
  report.loadMs = Math.round(performance.now() - t0);

  // 城市:所有材质换成无光照贴图材质
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  let meshes = 0, tris = 0;
  cityGltf.scene.traverse(o => {
    if (!o.isMesh) return;
    const map = o.material.map;
    if (map) { map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = maxAniso; if (q.get('nomip') === '1') { map.minFilter = THREE.LinearFilter; map.generateMipmaps = false; } }
    o.material = new THREE.MeshBasicMaterial({ map, color: map ? 0xffffff : 0xff00ff });
    meshes++; tris += o.geometry.index ? o.geometry.index.count / 3 : o.geometry.attributes.position.count / 3;
  });
  scene.add(cityGltf.scene);

  // 树:同一几何的节点合并成 InstancedMesh
  const size = new THREE.Vector2();
  let treeMat;
  if (layer) {
    layer.colorSpace = THREE.SRGBColorSpace;
    layer.minFilter = THREE.LinearFilter; layer.generateMipmaps = false;
    treeMat = new THREE.ShaderMaterial({ uniforms: { uLayer: { value: layer }, uSize: { value: size } }, vertexShader: TREE_VERT, fragmentShader: TREE_FRAG });
  } else {
    treeMat = new THREE.MeshBasicMaterial({ color: 0xdddddb });
  }
  report.treeLayer = !!layer;
  treeGltf.scene.updateMatrixWorld(true);
  const groups = new Map();
  treeGltf.scene.traverse(o => { if (o.isMesh) { const g = groups.get(o.geometry) || []; g.push(o.matrixWorld.clone()); groups.set(o.geometry, g); } });
  let treeCount = 0, treeTris = 0;
  for (const [geo, mats] of groups) {
    const inst = new THREE.InstancedMesh(geo, treeMat, mats.length);
    mats.forEach((m, i) => inst.setMatrixAt(i, m));
    inst.frustumCulled = false;
    scene.add(inst);
    treeCount += mats.length; treeTris += (geo.index ? geo.index.count : geo.attributes.position.count) / 3 * mats.length;
  }
  Object.assign(report, { meshes, tris, treePrototypes: groups.size, treeCount, treeTris });

  function resize() {
    const w = workspace.clientWidth, h = workspace.clientHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio, Number(q.get('pr')) || 2));
    renderer.setSize(w, h, false);
    renderer.getDrawingBufferSize(size);
    const span = bcam.ortho_scale || spec.captured_frustum_width / spec.zoom, aspect = w / h;   // 正交宽度(世界单位),不再另设 zoom
    const sx = bcam.shift_x * span, sy = bcam.shift_y * span;
    Object.assign(camera, { left: -span / 2 + sx, right: span / 2 + sx, top: span / aspect / 2 + sy, bottom: -span / aspect / 2 + sy });
    report.shift = [bcam.shift_x, bcam.shift_y];
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);        // 静态画面:只在尺寸变化时重绘
    report.drawCalls = renderer.info.render.calls;
    report.buffer = [size.x, size.y];
  }
  // 调试:画面像素 (x, y) 处命中的物体与 UV,用于核对烘焙贴图问题
  report.pick = (x, y) => {
    const ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(x / workspace.clientWidth * 2 - 1, 1 - y / workspace.clientHeight * 2), camera);
    return ray.intersectObjects(scene.children, true).slice(0, 3).map(h => ({ name: h.object.name, d: +h.distance.toFixed(1), uv: h.uv && [+h.uv.x.toFixed(4), +h.uv.y.toFixed(4)], face: h.face && +(h.face.normal.dot(ray.ray.direction)).toFixed(2) }));
  };
  report.project = p => { const v = convert(p).project(camera); return [+(v.x * .5 + .5).toFixed(4), +(v.y * .5 + .5).toFixed(4)]; };   // 调试:设计坐标 → 画面比例坐标(左下原点,同 Blender)
  new ResizeObserver(resize).observe(workspace);
  resize();
  viewport.dataset.loaded = 'true';
  loading.hidden = true;
  report.stage = 'ready';
}

main().catch(err => {
  console.error(err);
  report.stage = 'error'; report.error = String(err);
  loadingCopy.textContent = '烘焙资产加载失败:' + err.message;
});
