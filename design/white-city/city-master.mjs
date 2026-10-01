import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {DRACOLoader} from 'three/addons/loaders/DRACOLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

const host=document.querySelector('#viewport'),workspace=document.querySelector('#workspace'),loading=document.querySelector('#loading');
const plan=await fetch('./blender/city-12-master-plan.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Model plan unavailable');return r.json();});
const scene=new THREE.Scene();scene.background=new THREE.Color('#f4f5ef');
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.10;
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.shadowMap.autoUpdate=false;host.append(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff,0xd0d1c4,1.3));
const key=new THREE.DirectionalLight(0xfffdf5,2.5);key.position.set(-260,620,330);key.castShadow=true;key.shadow.mapSize.set(4096,4096);Object.assign(key.shadow.camera,{left:-480,right:480,top:410,bottom:-410,near:1,far:1500});key.shadow.normalBias=.25;key.shadow.bias=-.000001;scene.add(key,key.target);
const fill=new THREE.DirectionalLight(0xf3f7ff,.55);fill.position.set(350,220,-250);scene.add(fill);
const convert=([x,y,z])=>new THREE.Vector3(x,z,-y);
let mode='grid',model=null,frames=0,request=0,wire=false;
function makeCamera(spec){const c=new THREE.OrthographicCamera(-spec.scale/2,spec.scale/2,spec.scale/2,-spec.scale/2,.1,2500);c.position.copy(convert(spec.position));c.up.copy(convert(spec.up));c.lookAt(convert(spec.target));c.userData.width=spec.scale;return c;}
const cameras=Object.fromEntries(Object.entries(plan.cameras).map(([k,v])=>[k,makeCamera(v)]));
// Frame all sides of the entire model, rather than cutting a tall eastern tower
// out of a narrow side panel. Bounds come from the same authored world plan.
const framePoints=[];
for(const b of plan.buildings)for(const [x,y] of b.footprint)for(const z of [b.base,b.z+b.h+1])framePoints.push(convert([x,y,z]));
for(const poly of plan.site)for(const [x,y] of poly.outer)for(const z of [-7.5,35])framePoints.push(convert([x,y,z]));
for(const camera of Object.values(cameras)){
 camera.updateMatrixWorld();const bounds=new THREE.Box3().setFromPoints(framePoints.map(p=>p.clone().applyMatrix4(camera.matrixWorldInverse)));
 camera.userData.frame={x:(bounds.min.x+bounds.max.x)/2,y:(bounds.min.y+bounds.max.y)/2,w:bounds.max.x-bounds.min.x,h:bounds.max.y-bounds.min.y};
}
const orbit=makeCamera(plan.cameras.overview);const controls=new OrbitControls(orbit,renderer.domElement);controls.target.copy(convert(plan.cameras.overview.target));controls.enableDamping=false;controls.enableRotate=true;controls.minZoom=.4;controls.maxZoom=9;controls.maxPolarAngle=Math.PI*.98;controls.enabled=false;controls.update();
controls.addEventListener('change',schedule);
function schedule(){if(!request)request=requestAnimationFrame(()=>{request=0;draw();});}
function cameraAspect(camera,width,height){const f=camera.userData.frame;const w=f?Math.max(f.w,f.h*width/height)*1.12:camera.userData.width*Math.max(1,(width/height)/(1600/1100));const x=f?.x??0,y=f?.y??0;camera.left=x-w/2;camera.right=x+w/2;camera.top=y+w*height/width/2;camera.bottom=y-w*height/width/2;camera.updateProjectionMatrix();}
function view(camera,rect){const base=host.getBoundingClientRect();const x=rect.left-base.left,y=base.bottom-rect.bottom;cameraAspect(camera,rect.width,rect.height);renderer.setViewport(x,y,rect.width,rect.height);renderer.setScissor(x,y,rect.width,rect.height);renderer.render(scene,camera);}
function draw(){
 if(!model||mode==='reference')return;
 const rect=host.getBoundingClientRect();renderer.setScissorTest(false);renderer.setViewport(0,0,rect.width,rect.height);renderer.setClearColor('#f5f5f1');renderer.clear();renderer.setScissorTest(true);
 if(mode==='grid')for(const pane of document.querySelectorAll('.pane'))view(cameras[pane.dataset.camera],pane.getBoundingClientRect());else view(orbit,rect);
 renderer.setScissorTest(false);host.dataset.frames=String(++frames);host.dataset.mode=mode;
 host.dataset.cameraState=JSON.stringify(Object.fromEntries(Object.entries(cameras).map(([k,c])=>[k,{position:c.position.toArray(),quaternion:c.quaternion.toArray()}])));
}
function resize(){renderer.setSize(host.clientWidth,host.clientHeight);schedule();}
new ResizeObserver(resize).observe(workspace);resize();
function setMode(next){mode=next;controls.enabled=mode==='orbit';document.querySelector('#grid').hidden=mode!=='grid';document.querySelector('#orbit-pane').hidden=mode!=='orbit';document.querySelector('#reference-pane').hidden=mode!=='reference';host.hidden=mode==='reference';loading.hidden=!!model||mode==='reference';document.querySelector('.layers').style.visibility=mode==='reference'?'hidden':'visible';for(const b of document.querySelectorAll('[data-mode]'))b.setAttribute('aria-pressed',String(b.dataset.mode===mode));schedule();}
for(const b of document.querySelectorAll('[data-mode]'))b.addEventListener('click',()=>setMode(b.dataset.mode));
for(const b of document.querySelectorAll('[data-preset]'))b.addEventListener('click',()=>{const p=plan.cameras[b.dataset.preset];orbit.position.copy(convert(p.position));orbit.up.copy(convert(p.up));orbit.userData.width=p.scale;orbit.zoom=1;controls.target.copy(convert(p.target));orbit.lookAt(controls.target);controls.update();schedule();});
document.querySelector('#wire').addEventListener('click',e=>{wire=!wire;e.currentTarget.setAttribute('aria-pressed',String(wire));model?.traverse(o=>{if(o.isMesh)for(const m of Array.isArray(o.material)?o.material:[o.material])m.wireframe=wire;});schedule();});
const layers={buildings:['04'],streets:['02','03','05'],trees:['07'],terrain:['01','06']};
for(const input of document.querySelectorAll('[data-layer]'))input.addEventListener('change',()=>{if(!model)return;model.traverse(o=>{if(layers[input.dataset.layer].some(prefix=>o.name.startsWith(prefix)))o.visible=input.checked;});renderer.shadowMap.needsUpdate=true;schedule();});
const draco=new DRACOLoader().setDecoderPath('https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/');
new GLTFLoader().setDRACOLoader(draco).load('./blender/city-12-master.glb?v=3',gltf=>{
 model=gltf.scene;let triangles=0,meshes=0;
 model.traverse(o=>{if(o.isMesh){meshes++;triangles+=(o.geometry.index?.count??o.geometry.attributes.position.count)/3;let parent=o;while(parent.parent&&parent.parent!==model)parent=parent.parent;const layer=parent.name.slice(0,2);o.castShadow=['04','05','06','07'].includes(layer);o.receiveShadow=true;for(const m of Array.isArray(o.material)?o.material:[o.material]){m.wireframe=wire;m.roughness=.82;m.metalness=0;}}});
 scene.add(model);renderer.shadowMap.needsUpdate=true;loading.hidden=true;host.dataset.loaded='true';host.dataset.validation=JSON.stringify({meshes,triangles,buildings:plan.buildings.length,landmarks:plan.buildings.filter(b=>b.landmark).length,trees:plan.trees.length,sameModelAcrossViews:true,automaticCameraMotion:false,phase:'geometry'});
 document.querySelector('#summary').textContent=`${plan.buildings.length} 栋建筑 · ${plan.buildings.filter(b=>b.landmark).length} 个重点建筑 · 同一个完整模型`;
 document.querySelector('#detail').textContent='平面、体块、桥梁与地形核对 · 设计尺度，非测绘模型';draco.dispose();schedule();
},e=>{if(e.total)loading.textContent=`正在加载完整城市模型… ${Math.round(e.loaded/e.total*100)}%`;},error=>{host.dataset.loaded='error';loading.textContent='模型加载失败，请刷新重试。';console.error(error);});
