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
      object.material = new THREE.MeshBasicMaterial({
        color: new THREE.Color().setRGB(radianceScale, radianceScale, radianceScale, THREE.LinearSRGBColorSpace),
        vertexColors: true,
        toneMapped: true,
        side: THREE.FrontSide,
      });
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
  renderer.toneMapping = mode === 'clay' ? THREE.ACESFilmicToneMapping : THREE.AgXToneMapping;
  renderer.toneMappingExposure = mode === 'clay' ? 1.10 : 2 ** Number(plan.studio?.exposure ?? 1.0);
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
  bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), .07, .2, 1.5);
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
