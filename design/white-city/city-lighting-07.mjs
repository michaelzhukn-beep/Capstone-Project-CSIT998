import * as THREE from 'three';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {RectAreaLightUniformsLib} from 'three/addons/lights/RectAreaLightUniformsLib.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {GTAOPass} from 'three/addons/postprocessing/GTAOPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {ShaderPass} from 'three/addons/postprocessing/ShaderPass.js';
import {Reflector} from 'three/addons/objects/Reflector.js';
import {localLight,matchGroundWhite} from './city-local-light.mjs';

// Local diffuse Cycles data supplements realtime direct shadows, environment and GTAO.
// This is asset-local light transport, not a full-scene realtime path tracer.
export function createCityLighting(renderer,scene,camera){
  RectAreaLightUniformsLib.init();
  const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();
  const environment=pmrem.fromScene(room,.04);scene.environment=environment.texture;
  room.dispose();pmrem.dispose();
  const hemi=new THREE.HemisphereLight(0xf4f7ff,0xd7cebd,.65);scene.add(hemi);
  const key=new THREE.DirectionalLight(0xfff7e9,2.3);
  key.position.set(-155,210,95);key.target.position.set(0,8,-55);key.castShadow=true;
  key.shadow.mapSize.set(4096,4096);Object.assign(key.shadow.camera,{left:-330,right:330,top:330,bottom:-330,near:1,far:900});
  key.shadow.normalBias=.10;key.shadow.bias=-.00008;key.shadow.radius=10;key.shadow.blurSamples=16;
  scene.add(key,key.target);
  const fill=new THREE.DirectionalLight(0xeaf1ff,.38);fill.position.set(110,90,-130);scene.add(fill);
  // A fixed pool avoids increasing shader/light counts as continuous districts recycle.
  // Dim residual spill for unbaked terrain. Interior surfaces use their baked radiance.
  const warmPool=Array.from({length:6},()=>{
    const light=new THREE.RectAreaLight(0xffd39b,0,1,1);scene.add(light);return light;
  });
  // One planar render target for the entire river, including all streamed chunks.
  // Only the existing river geometry samples it: no fullscreen/background image plane.
  const reflection=new Reflector(new THREE.PlaneGeometry(1,1),{textureWidth:768,textureHeight:768,multisample:0,clipBias:.003});
  reflection.position.y=.1;reflection.rotation.x=-Math.PI/2;reflection.updateMatrixWorld(true);
  const reflectionMatrix=new THREE.Matrix4(),inversePlane=reflection.matrixWorld.clone().invert();
  const waterMaterial=new THREE.ShaderMaterial({name:'Soft planar river reflection',side:THREE.DoubleSide,uniforms:{
    reflectionMap:{value:reflection.getRenderTarget().texture},worldToReflection:{value:reflectionMatrix},
  },vertexShader:`uniform mat4 worldToReflection;varying vec4 reflectedUv;varying vec3 worldPoint;
    void main(){vec4 p=modelMatrix*vec4(position,1.);worldPoint=p.xyz;reflectedUv=worldToReflection*p;gl_Position=projectionMatrix*viewMatrix*p;}`,
  fragmentShader:`uniform sampler2D reflectionMap;varying vec4 reflectedUv;varying vec3 worldPoint;
    void main(){vec2 uv=reflectedUv.xy/reflectedUv.w;vec3 reflected=vec3(0.);float total=0.;
      for(int x=-1;x<=1;x++)for(int y=-1;y<=1;y++){float weight=(x==0&&y==0)?4.:1.;
        reflected+=texture2D(reflectionMap,clamp(uv+vec2(float(x),float(y))*0.0025,vec2(.001),vec2(.999))).rgb*weight;total+=weight;}
      reflected=min(reflected/total,vec3(1.6));float grazing=1.-abs(normalize(cameraPosition-worldPoint).y);
      float fresnel=.08+.12*pow(grazing,3.);
      gl_FragColor=vec4(mix(vec3(.22,.27,.255),reflected,fresnel),1.);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`});
  const originalWater=new WeakMap();let waters=[];
  const composer=new EffectComposer(renderer,new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,samples:4}));
  composer.addPass(new RenderPass(scene,camera));
  function makeAO(){
    const pass=new GTAOPass(scene,camera,innerWidth,innerHeight);
    pass.updateGtaoMaterial({radius:2.1,distanceExponent:1.5,thickness:1.1,scale:1,samples:16,distanceFallOff:1,screenSpaceRadius:false});
    pass.updatePdMaterial({lumaPhi:10,depthPhi:2,normalPhi:3,radius:4,rings:2,samples:16});
    return pass;
  }
  let ao=makeAO();composer.addPass(ao);
  // HDR threshold prevents the white clay itself from being turned into a luminous fog.
  const bloom=new UnrealBloomPass(new THREE.Vector2(innerWidth,innerHeight),.13,.32,1.8);
  // Select warm HDR sources, excluding neutral bright ground and clay highlights.
  bloom.materialHighPassFilter.fragmentShader=bloom.materialHighPassFilter.fragmentShader.replace(
    'float alpha = smoothstep( luminosityThreshold, luminosityThreshold + smoothWidth, v );',
    'float warmth=smoothstep(.14,.32,(texel.r-texel.b)/max(texel.r,.001)); float alpha=smoothstep(luminosityThreshold,luminosityThreshold+smoothWidth,v)*warmth;');
  composer.addPass(bloom);
  composer.addPass(new OutputPass());
  const background=new ShaderPass({
    uniforms:{tDiffuse:{value:null},tDepth:{value:ao.depthTexture}},
    vertexShader:'varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader:`
      varying vec2 vUv;uniform sampler2D tDiffuse;uniform sampler2D tDepth;
      void main(){vec4 c=texture2D(tDiffuse,vUv);float d=texture2D(tDepth,vUv).x;
        float fade=d>=.99999?1.:0.;
        gl_FragColor=vec4(mix(c.rgb,vec3(245./255.,244./255.,240./255.),fade),c.a);}`
  });composer.addPass(background);
  let refined=true,warm=true,contacts=true,baked=true,source=null,anchors=[],journey=false;
  const savedMaterials=new Map(),savedMeshes=new WeakMap(),matrix=new THREE.Matrix4(),box=new THREE.Box3(),center=new THREE.Vector3(),size=new THREE.Vector3();
  function prepare(root){
    root.traverse(obj=>{if(!obj.isMesh)return;
      if(!savedMeshes.has(obj))savedMeshes.set(obj,{cast:obj.castShadow,receive:obj.receiveShadow});
      for(const mat of Array.isArray(obj.material)?obj.material:[obj.material]){
        if(!savedMaterials.has(mat))savedMaterials.set(mat,{emissive:mat.emissive?.clone(),intensity:mat.emissiveIntensity,roughness:mat.roughness,transmission:mat.transmission});
      }
    });
  }
  function setSource(root,isJourney=false){
    for(const obj of waters)obj.material=originalWater.get(obj);
    waters=[];source=root;journey=isJourney;anchors=[];prepare(root);root.updateMatrixWorld(true);
    root.traverse(obj=>{if(obj.isMesh&&['Pale river - physical reflection','Continuous river surface'].includes(obj.material?.name)){
      originalWater.set(obj,obj.material);waters.push(obj);
    }});
    root.traverse(obj=>{if(obj.isMesh&&obj.material?.name==='Recessed warm ceiling - real emission')anchors.push(obj);});
    apply();
  }
  function apply(){
    renderer.toneMapping=THREE.AgXToneMapping;renderer.toneMappingExposure=refined?2.0:1.8;
    matchGroundWhite(renderer.toneMappingExposure);
    localLight.visibility.value=baked&&refined?1:0;localLight.warm.value=baked&&warm&&refined?1:0;
    const shadowType=refined?THREE.VSMShadowMap:THREE.PCFSoftShadowMap;
    if(renderer.shadowMap.type!==shadowType){
      renderer.shadowMap.type=shadowType;
      for(const light of [key]){light.shadow.map?.dispose();light.shadow.map=null;light.shadow.mapPass?.dispose();light.shadow.mapPass=null;}
      for(const mat of savedMaterials.keys())mat.needsUpdate=true;
    }
    scene.environmentIntensity=refined?.38:.3;
    hemi.intensity=refined?.32:.45;hemi.color.set(refined?0xf4f7ff:0xffffff);hemi.groundColor.set(refined?0xd7cebd:0xb2b7a8);
    key.intensity=refined?3.25:2.1;key.color.set(refined?0xfff8ee:0xfffaf2);
    key.shadow.normalBias=refined?.10:.18;key.shadow.bias=refined?-.00008:-.00015;
    key.position.set(...(refined?[-220,190,-80]:[-150,220,100]));key.target.position.set(...(refined?[0,8,-55]:[0,0,-60]));
    fill.intensity=refined?.14:0;
    // Keep depth alive when contacts are disabled: empty background pixels still need it.
    ao.blendIntensity=contacts&&refined?.48:0;bloom.enabled=refined&&warm;
    for(const [mat,original] of savedMaterials){
      if(mat.name==='Recessed warm ceiling - real emission'){
        mat.emissive.copy(refined?new THREE.Color().setRGB(1,.56,.27):original.emissive);
        mat.emissiveIntensity=warm?(refined?3.2:original.intensity):0;
      }
      if(mat.name==='Ivory white architectural ceramic')mat.roughness=refined?.48:original.roughness;
    }
    // Glass must transmit daylight rather than casting an opaque black wall shadow.
    if(source)source.traverse(obj=>{if(!obj.isMesh)return;const old=savedMeshes.get(obj);if(!old)return;
      const mats=Array.isArray(obj.material)?obj.material:[obj.material];
      obj.castShadow=refined&&mats.every(m=>(m.transmission||0)>.2)?false:old.cast;
      obj.receiveShadow=old.receive;
    });
    for(const obj of waters)obj.material=refined?waterMaterial:originalWater.get(obj);
    renderer.shadowMap.needsUpdate=true;
  }
  function updateWarm(){
    const candidates=[];
    if(refined&&warm&&source){source.updateMatrixWorld(true);
      for(const obj of anchors){
        if(!obj.geometry.boundingBox)obj.geometry.computeBoundingBox();
        const count=obj.isInstancedMesh?obj.count:1;
        for(let i=0;i<count;i++){
          if(obj.isInstancedMesh){obj.getMatrixAt(i,matrix);matrix.premultiply(obj.matrixWorld);}else matrix.copy(obj.matrixWorld);
          box.copy(obj.geometry.boundingBox).applyMatrix4(matrix);box.getCenter(center);box.getSize(size);
          if(center.distanceTo(camera.position)>420)continue;
          candidates.push({position:center.clone(),width:Math.max(1,size.x*.7),depth:Math.max(1,size.z*.65),distance:center.distanceToSquared(camera.position)});
        }
      }
    }
    candidates.sort((a,b)=>a.distance-b.distance);
    // At the sixth/seventh-nearest boundary both contributions reach zero before
    // exchanging slots; moving the camera cannot abruptly relocate a lit emitter.
    const cutoff=candidates[6]?Math.sqrt(candidates[6].distance):444;
    warmPool.forEach((light,i)=>{const c=candidates[i];
      light.intensity=c?.25*THREE.MathUtils.smoothstep(cutoff-Math.sqrt(c.distance),0,24)*THREE.MathUtils.smoothstep(420-Math.sqrt(c.distance),0,50):0;
      if(c){light.position.copy(c.position);light.position.y-=.12;light.width=c.width;light.height=c.depth;light.lookAt(c.position.x,c.position.y-1,c.position.z);}
    });
  }
  function render(){
    updateWarm();camera.updateMatrixWorld(true);
    if(refined&&waters.length){
      const visibility=waters.map(o=>o.visible);waters.forEach(o=>o.visible=false);
      try{reflection.onBeforeRender(renderer,scene,camera);reflectionMatrix.copy(reflection.material.uniforms.textureMatrix.value).multiply(inversePlane);}
      finally{waters.forEach((o,i)=>o.visible=visibility[i]);}
    }
    if(refined||journey)composer.render();else renderer.render(scene,camera);
  }
  let viewportWidth=0,viewportHeight=0;
  function resize(w,h){
    if(w!==viewportWidth||h!==viewportHeight){
      // Rebuild the G-buffer and every depth consumer together. Retaining the old
      // attachment produced displaced AO/fog silhouettes after an aspect change.
      const old=ao,index=composer.passes.indexOf(old);
      ao=makeAO();ao.blendIntensity=contacts&&refined?.48:0;
      composer.passes[index]=ao;background.uniforms.tDepth.value=ao.depthTexture;
      old.dispose();old.blendMaterial.dispose();old.depthTexture.dispose();
      viewportWidth=w;viewportHeight=h;
    }
    composer.setSize(w,h);
  }
  function setOptions(options){if('refined'in options)refined=options.refined;if('warm'in options)warm=options.warm;if('contacts'in options)contacts=options.contacts;if('baked'in options)baked=options.baked;apply();}
  function stats(){return {revision:'07.1',refined,warm,contacts,baked,depthFog:false,toneMapping:'AgX',exposure:renderer.toneMappingExposure,areaLights:warmPool.filter(l=>l.intensity>0).length,reflectionTargets:1,riverMeshes:waters.length,shadow:refined?'VSM 4096 / 16 samples':'PCFSoft 4096'};}
  renderer.shadowMap.enabled=true;renderer.shadowMap.autoUpdate=false;resize(innerWidth,innerHeight);apply();
  return {setSource,setOptions,render,resize,stats};
}
