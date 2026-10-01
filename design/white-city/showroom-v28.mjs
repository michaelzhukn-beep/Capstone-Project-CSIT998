// 【已冻结:正式实现在 app/web/showroom/showroom.mjs】
// 本文件是接入主站前的原型页(v28-showroom.html)。主站版本后续新增了鼠标视差、左右转场箭头、
// 与主站首屏的联动(nw:query / nw:lang / nw:showroom),两边不同步。改功能请改主站那份。
//
// v28 主页背景原型:城市沙盘 + 户型样板。网页加载真实三维模型,光照全部来自 Cycles 烘焙 / 投影渲染贴图。
// experimental。资产由 blender/bake_v28_showroom.py → post_v28_layers.py → export_v26_web.py --bakedir bake-v28 生成。
//
// 交互:点击输入框 → 镜头(固定朝向的正交相机)向右平移并略微拉近到 4 栋户型;失焦且输入为空 → 回到城市。
// 静止时不重绘;只在平移动画期间逐帧绘制。prefers-reduced-motion 时直接切换。
// 信息牌文字是真实 DOM 文字,每帧按牌面四角做透视(matrix3d)贴到模型牌面上,可点击。
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';

const BASE = 'bake-v28/';
const q = new URLSearchParams(location.search);
const $ = s => document.querySelector(s);
const stage = $('#stage'), viewport = $('#viewport'), signLayer = $('#signs'), input = $('#query');
const report = window.__v28 = { stage: 'boot' };

// 牌面文案:示意,上线前逐条用解析器验证能解析出房型与条件
const SIGNS = {                                             // 牌面只写词条 + 查看房源(所有者要求不写房型)
  'v28 cottage': { lines: ['带私家庭院', '3 房 · 近学校'] },
  'v28 villa': { lines: ['安静街区', '4 房 · 100万内'] },
  'v28 terrace': { lines: ['近车站', '3 房 · 80万内'] },
  'v28 apartment': { lines: ['墨大周边', '2 房 · 通勤方便'] },
};

const Z_UP_TO_Y_UP = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1);
const toThree = p => new THREE.Vector3(p[0], p[2], -p[1]);
const PAGE_BG = new THREE.Color('#f6f5f2');
const json = async url => (await fetch(url, { cache: 'no-store' })).json();

/** 投影取色材质:片元按宽幅烘焙机位投影到贴图(树木着色层、桌面影子层)。 */
function projectedMaterial(tex, wideVP, { instanced = false, shadow = false } = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { uTex: { value: tex }, uVP: { value: wideVP } },
    transparent: shadow, depthWrite: !shadow,
    vertexShader: `
      uniform mat4 uVP; varying vec2 vUv;
      void main() {
        vec4 wp = modelMatrix * ${instanced ? 'instanceMatrix * ' : ''}vec4(position, 1.0);
        vec4 c = uVP * wp; vUv = c.xy / c.w * .5 + .5;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }`,
    fragmentShader: `
      uniform sampler2D uTex; varying vec2 vUv;
      void main() {
        vec4 c = texture2D(uTex, vUv);
        ${shadow ? 'gl_FragColor = vec4(0.0, 0.0, 0.0, c.a);' : 'if (c.a < .5) discard; gl_FragColor = vec4(c.rgb, 1.0);'}
        #include <colorspace_fragment>
      }`,
  });
}

/** 移轴:画面纵向以 focus 为中心的清晰带,上下逐渐虚化;strength 随平移进度渐入。
 *  离屏目标是 sRGB 格式,采样时 GPU 已解码成线性,输出前必须再编码回 sRGB(否则整幅画面变暗)。 */
const tiltMaterial = new THREE.ShaderMaterial({
  uniforms: { uTex: { value: null }, uTexel: { value: new THREE.Vector2() }, uFocus: { value: .55 }, uStrength: { value: 0 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
  fragmentShader: `
    uniform sampler2D uTex; uniform vec2 uTexel; uniform float uFocus, uStrength; varying vec2 vUv;
    void main() {
      float d = clamp((abs(vUv.y - uFocus) - .12) / .3, 0.0, 1.0);
      float r = pow(d, 1.4) * 7.0 * uStrength;
      vec4 acc = vec4(0.0); float w = 0.0;
      for (int i = 0; i < 16; i++) {
        float a = float(i) * 2.39996; float rr = sqrt(float(i) / 16.0) * r;
        vec2 o = vec2(cos(a), sin(a)) * rr * uTexel;
        acc += texture2D(uTex, vUv + o); w += 1.0;
      }
      gl_FragColor = acc / w;
      #include <colorspace_fragment>
    }`,
  depthTest: false, depthWrite: false,
});

/** 四边形 → CSS matrix3d(把 w×h 的元素映射到屏幕四角 tl, tr, br, bl)。 */
function quadMatrix(w, h, [tl, tr, br, bl]) {
  const sys = (s, d) => {
    const A = [], B = [];
    for (let i = 0; i < 4; i++) {
      const [x, y] = s[i], [u, v] = d[i];
      A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.push(u);
      A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); B.push(v);
    }
    for (let c = 0; c < 8; c++) {                       // 高斯消元
      let p = c; for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
      [A[c], A[p]] = [A[p], A[c]]; [B[c], B[p]] = [B[p], B[c]];
      for (let r = 0; r < 8; r++) if (r !== c) { const f = A[r][c] / A[c][c]; for (let k = c; k < 8; k++) A[r][k] -= f * A[c][k]; B[r] -= f * B[c]; }
    }
    return B.map((b, i) => b / A[i][i]);
  };
  const [a, b, c, d, e, f, g, hh] = sys([[0, 0], [w, 0], [w, h], [0, h]], [tl, tr, br, bl]);
  return `matrix3d(${a},${d},0,${g},${b},${e},0,${hh},0,0,1,0,${c},${f},0,1)`;
}

async function main() {
  const [camStart, camEnd, camWide, signs3d] = await Promise.all(['cam-start', 'cam-end', 'cam-wide', 'cam-start-signs3d'].map(n => json(BASE + 'web/' + n + '.json')));
  const [RX, RY] = camStart.resolution;
  stage.style.aspectRatio = `${RX} / ${RY}`;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.NoToneMapping; renderer.setClearColor(0, 0);
  viewport.appendChild(renderer.domElement);
  const scene = new THREE.Scene();

  // 相机:固定朝向,位置固定在起点机位;平移 / 缩放通过正交视锥的 left/right/top/bottom 表达
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 20000);
  const M0 = Z_UP_TO_Y_UP.clone().multiply(new THREE.Matrix4().set(...camStart.matrix_world.flat()));
  M0.decompose(camera.position, camera.quaternion, camera.scale);
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion), up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
  const frameOf = c => {
    const m = Z_UP_TO_Y_UP.clone().multiply(new THREE.Matrix4().set(...c.matrix_world.flat()));
    const p = new THREE.Vector3().setFromMatrixPosition(m).sub(camera.position);
    return { cu: p.dot(right) + c.shift_x * c.ortho_scale, cv: p.dot(up) + c.shift_y * c.ortho_scale, w: c.ortho_scale };
  };
  const F0 = frameOf(camStart), F1 = frameOf(camEnd);

  // 宽幅烘焙机位的 view-projection(投影取色用)
  const wideCam = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 20000);
  Z_UP_TO_Y_UP.clone().multiply(new THREE.Matrix4().set(...camWide.matrix_world.flat())).decompose(wideCam.position, wideCam.quaternion, wideCam.scale);
  { const W = camWide.ortho_scale, H = W * camWide.resolution[1] / camWide.resolution[0], sx = camWide.shift_x * W, sy = camWide.shift_y * W;
    Object.assign(wideCam, { left: -W / 2 + sx, right: W / 2 + sx, top: H / 2 + sy, bottom: -H / 2 + sy }); }
  wideCam.updateMatrixWorld(); wideCam.updateProjectionMatrix();
  const wideVP = new THREE.Matrix4().multiplyMatrices(wideCam.projectionMatrix, wideCam.matrixWorldInverse);

  const draco = new DRACOLoader().setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/');
  const loader = new GLTFLoader().setDRACOLoader(draco), texLoader = new THREE.TextureLoader();
  const t0 = performance.now();
  const [city, trees, treeTex, shadowTex] = await Promise.all([
    loader.loadAsync(BASE + 'web/city-v26-baked.glb'), loader.loadAsync(BASE + 'web/trees-v26.glb'),
    texLoader.loadAsync(BASE + 'layer-trees.png'), texLoader.loadAsync(BASE + 'floor-shadow.png'),
  ]);
  report.loadMs = Math.round(performance.now() - t0);

  const aniso = renderer.capabilities.getMaxAnisotropy();
  let tris = 0;
  city.scene.traverse(o => {
    if (!o.isMesh) return;
    const map = o.material.map;
    if (map) { map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = aniso; }
    o.material = new THREE.MeshBasicMaterial({ map, color: map ? 0xffffff : 0xff00ff });
    tris += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3;
  });
  scene.add(city.scene);

  treeTex.colorSpace = THREE.SRGBColorSpace; treeTex.generateMipmaps = false; treeTex.minFilter = THREE.LinearFilter;
  const treeMat = projectedMaterial(treeTex, wideVP, { instanced: true });
  trees.scene.updateMatrixWorld(true);
  const groups = new Map(); let treeCount = 0;
  trees.scene.traverse(o => { if (o.isMesh) { const g = groups.get(o.geometry) || []; g.push(o.matrixWorld.clone()); groups.set(o.geometry, g); } });
  for (const [geo, mats] of groups) {
    const inst = new THREE.InstancedMesh(geo, treeMat, mats.length); mats.forEach((m, i) => inst.setMatrixAt(i, m));
    inst.frustumCulled = false; scene.add(inst); treeCount += mats.length;
  }

  // 桌面影子:宽幅画框范围的水平面,位于台底高度
  shadowTex.generateMipmaps = false; shadowTex.minFilter = THREE.LinearFilter;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(8000, 8000).rotateX(-Math.PI / 2), projectedMaterial(shadowTex, wideVP, { shadow: true }));
  floor.position.y = -40.02; floor.renderOrder = -1; scene.add(floor);        // 台底 z = −40(render_v27_plinth.py BASE)

  Object.assign(report, { tris, treeCount });

  // 离屏目标 + 移轴后处理
  const rt = new THREE.WebGLRenderTarget(1, 1, { samples: 4, colorSpace: THREE.SRGBColorSpace });
  const postScene = new THREE.Scene(), postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  postScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), tiltMaterial));

  // 信息牌 DOM
  const cards = Object.entries(SIGNS).map(([name, s]) => {
    const el = document.createElement('button');
    const query = s.lines.join(' · ');
    el.className = 'sign'; el.type = 'button'; el.setAttribute('aria-label', `${query},查看房源`);
    el.innerHTML = `<span class="sign-in"><i class="dash"></i><b>${s.lines[0]}</b><span class="ln">${s.lines.slice(1).join('<br>')}</span><span class="go">查看房源 <em>→</em></span></span>`;
    el.addEventListener('click', () => { input.value = query; input.focus(); report.clicked = query; });
    signLayer.appendChild(el);
    return { el, corners: signs3d[name].map(toThree) };
  });
  const CW = 390, CH = 620;                                  // 牌面 7.8 : 12.4

  let pan = 0, from = 0, to = 0, startT = 0, raf = 0;
  const size = new THREE.Vector2();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  function frameAt(t) {
    const e = t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    const cu = F0.cu + (F1.cu - F0.cu) * e, cv = F0.cv + (F1.cv - F0.cv) * e, w = F0.w + (F1.w - F0.w) * e;
    return { cu, cv, w, e };
  }

  function draw() {
    const W = stage.clientWidth, H = stage.clientHeight;
    const { cu, cv, w, e } = frameAt(pan);
    const h = w * H / W;
    Object.assign(camera, { left: cu - w / 2, right: cu + w / 2, top: cv + h / 2, bottom: cv - h / 2 });
    camera.updateProjectionMatrix(); camera.updateMatrixWorld();
    // 离屏目标用不透明页面底色:透明底在移轴模糊时会在轮廓外出现亮边
    renderer.setRenderTarget(rt); renderer.setClearColor(PAGE_BG, 1); renderer.clear(); renderer.render(scene, camera);
    tiltMaterial.uniforms.uTex.value = rt.texture; tiltMaterial.uniforms.uStrength.value = q.get('tilt') === '0' ? 0 : e;
    tiltMaterial.uniforms.uTexel.value.set(1 / rt.width, 1 / rt.height);
    renderer.setRenderTarget(null); renderer.setClearColor(0, 0); renderer.render(postScene, postCam);
    // 信息牌:角点顺序见 build_v28_houses.py(牌子本地 +x 在画面左侧)
    const v = new THREE.Vector3();
    const px = p => { v.copy(p).project(camera); return [(v.x * .5 + .5) * W, (-v.y * .5 + .5) * H]; };
    let focus = 0;
    for (const c of cards) {
      const [bl0, br0, tr0, tl0] = c.corners.map(px);
      c.el.style.transform = quadMatrix(CW, CH, [tr0, tl0, bl0, br0]);
      c.el.style.opacity = String(Math.max(0, (e - .55) / .45));
      c.el.tabIndex = e > .9 ? 0 : -1;
      focus += (tr0[1] + bl0[1]) / 2 / H;
    }
    tiltMaterial.uniforms.uFocus.value = 1 - focus / cards.length;
    report.pan = +pan.toFixed(3); report.drawCalls = renderer.info.render.calls;
  }

  function animate(now) {
    const dur = reduced.matches ? 1 : 1300;
    const t = Math.min(1, (now - startT) / dur);
    pan = from + (to - from) * t;
    draw();
    raf = t < 1 ? requestAnimationFrame(animate) : 0;
    stage.dataset.pan = pan > .5 ? 'houses' : 'city';
  }
  function goTo(target) {
    if (to === target && raf) return;
    from = pan; to = target; startT = performance.now();
    cancelAnimationFrame(raf); raf = requestAnimationFrame(animate);
  }
  report.goTo = goTo;
  report.setPan = p => { pan = to = p; draw(); };

  input.addEventListener('focus', () => goTo(1));
  input.addEventListener('blur', () => setTimeout(() => {
    if (!input.value.trim() && !signLayer.contains(document.activeElement)) goTo(0);
  }, 120));
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') { input.value = ''; input.blur(); goTo(0); } });

  function resize() {
    renderer.setPixelRatio(Math.min(devicePixelRatio, Number(q.get('pr')) || 2));
    renderer.setSize(stage.clientWidth, stage.clientHeight, false);
    renderer.getDrawingBufferSize(size); rt.setSize(size.x, size.y);
    draw();
  }
  new ResizeObserver(resize).observe(stage);
  resize();
  if (q.get('pan')) report.setPan(Number(q.get('pan')));
  viewport.dataset.loaded = 'true';
  $('#loading').hidden = true;
  report.stage = 'ready';
}

main().catch(err => { console.error(err); report.stage = 'error'; report.error = String(err); $('#loading').textContent = '资产加载失败:' + err.message; });
