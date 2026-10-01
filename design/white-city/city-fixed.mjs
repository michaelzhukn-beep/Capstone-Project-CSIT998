import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {DRACOLoader} from 'three/addons/loaders/DRACOLoader.js';

const host=document.querySelector('#viewport'),stage=document.querySelector('#stage'),status=document.querySelector('#status'),loading=document.querySelector('#loading');
const asset=document.body.dataset.asset??'city-09-fixed';
const bake=document.body.dataset.bake??asset;
const [plan,bakeInfo]=await Promise.all([`${asset}-plan`,`${bake}-bake`].map(name=>fetch(`./blender/${name}.json`,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Fixed scene metadata unavailable');return r.json();})));
const radianceScale=Number(bakeInfo.radiance_scale??32);
if(!Number.isFinite(radianceScale)||radianceScale<=0)throw Error('Invalid lighting encoding');
const scene=new THREE.Scene();
const width=plan.camera.ortho_width,height=width?width*941/1672:undefined;
const camera=plan.camera.type==='PERSP'?new THREE.PerspectiveCamera():new THREE.OrthographicCamera(-width/2,width/2,height/2,-height/2,.1,1600);
if(plan.camera.type==='PERSP'){
    // Carry Blender's complete shifted frustum, rather than guessing a matching FOV.
    camera.projectionMatrix.set(...plan.camera.projection_matrix.flat());
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
}
const convert=([x,y,z])=>new THREE.Vector3(x,z,-y);
camera.position.copy(convert(plan.camera.position));camera.lookAt(convert(plan.camera.target));camera.updateMatrixWorld();
const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0,0);renderer.toneMapping=THREE.AgXToneMapping;renderer.toneMappingExposure=2**1.75;host.append(renderer.domElement);
let model=null,mode='live',frame=0,wire=false;
function draw(){renderer.render(scene,camera);frame++;host.dataset.frames=String(frame);}
function resize(){renderer.setSize(stage.clientWidth,stage.clientHeight);if(model)draw();}
new ResizeObserver(resize).observe(stage);resize();
const start=performance.now();
const draco=new DRACOLoader();draco.setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/');
new GLTFLoader().setDRACOLoader(draco).load(`./blender/${bake}-baked.glb?v=${document.body.dataset.revision??7}`,gltf=>{
    model=gltf.scene;let triangles=0,meshes=0,missing=0;
    model.traverse(ob=>{
        if(!ob.isMesh)return;
        meshes++;const color=ob.geometry.getAttribute('color');if(!color)missing++;
        triangles+=(ob.geometry.index?.count??ob.geometry.attributes.position.count)/3;
        const ground=ob.name.startsWith('Fixed_studio_ground')||ob.material?.name==='09 White studio terrain';
        const material=new THREE.MeshBasicMaterial({color:0xffffff,vertexColors:true,transparent:ground,depthWrite:!ground});
        material.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>\ndiffuseColor.rgb *= ${radianceScale.toFixed(1)};`);};
        ob.material=material;ob.renderOrder=ground?1:0;
    });
    scene.add(model);host.dataset.loaded='true';host.dataset.validation=JSON.stringify({meshes,triangles,missingColors:missing,source:bakeInfo.engine,cameraFixed:true,cruise:false,loadedMs:Math.round(performance.now()-start)});
    host.dataset.camera=JSON.stringify({type:camera.type,position:camera.position.toArray(),quaternion:camera.quaternion.toArray(),width,projection:camera.projectionMatrix.toArray()});
    if(plan.projection_checks)host.dataset.projectionChecks=JSON.stringify(plan.projection_checks.map(p=>{const q=convert(p.world).project(camera);return {name:p.name,expected:p.screen,actual:[(q.x+1)/2,(1-q.y)/2]};}));
    loading.hidden=true;draw();setMode(mode);draco.dispose();
},e=>{if(e.total)loading.textContent=`正在加载固定场景真实模型… ${Math.round(e.loaded/e.total*100)}%`;},e=>{host.dataset.loaded='error';loading.textContent='模型加载失败；Cycles 与目标参考仍可单独查看。';console.error(e);});
function setMode(next){
    mode=next;host.hidden=mode!=='live';document.querySelector('#still').hidden=mode!=='cycles';document.querySelector('#reference').hidden=mode!=='reference';
    document.body.classList.toggle('compare',mode==='reference');document.querySelector('#wire').disabled=mode!=='live';
    for(const b of document.querySelectorAll('[data-mode]'))b.setAttribute('aria-pressed',String(b.dataset.mode===mode));
    loading.hidden=mode!=='live'||!!model;
    status.textContent=mode==='live'?(bakeInfo.view_from==='ACTIVE_CAMERA'?'真实网格 · 固定机位 · 含反射与透射的固定视角烘焙；细节仍与 Cycles 有差异':'真实网格 · 固定机位 · 整场景顶点光照烘焙；细小反射仍可能与 Cycles 不同'):mode==='cycles'?'同一模型的实际 Cycles 对照 · 不是网页实时渲染':'目标参考原图 · 仅用于对照，没有贴到模型上';
    if(mode==='live'&&model)draw();
}
for(const b of document.querySelectorAll('[data-mode]'))b.addEventListener('click',()=>setMode(b.dataset.mode));
document.querySelector('#clean').addEventListener('click',e=>{const active=document.body.classList.toggle('clean');e.currentTarget.setAttribute('aria-pressed',String(active));});
document.querySelector('#wire').addEventListener('click',e=>{wire=!wire;e.currentTarget.setAttribute('aria-pressed',String(wire));model?.traverse(o=>{if(o.isMesh)o.material.wireframe=wire;});draw();});
// Intentionally no rAF, timers, pointer parallax, orbit controls, camera path or streaming.
