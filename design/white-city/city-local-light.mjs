import * as THREE from 'three';

// Shared uniforms keep all recycled instances in sync without recompiling materials.
export const localLight={visibility:{value:1},warm:{value:1}};
export function prepareLocalLight(geometry,material,scale=16){
  const color=geometry.getAttribute('color');
  if(!color)return;
  geometry.setAttribute('localLight',color);geometry.deleteAttribute('color');
  material.vertexColors=false;material.transparent=false;material.opacity=1;
  if(material.userData.localLight07)return;
  material.userData.localLight07=true;
  material.onBeforeCompile=shader=>{
    shader.uniforms.localVisibility=localLight.visibility;shader.uniforms.localWarm=localLight.warm;
    shader.uniforms.localScale={value:scale};shader.uniforms.localFloor={value:scale===64?.45:.3};
    shader.vertexShader='attribute vec4 localLight; varying vec4 vLocalLight;\n'+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nvLocalLight=localLight;');
    shader.fragmentShader='varying vec4 vLocalLight; uniform float localVisibility; uniform float localWarm; uniform float localScale; uniform float localFloor;\n'+shader.fragmentShader;
    shader.fragmentShader=shader.fragmentShader.replace('#include <lights_fragment_end>',`#include <lights_fragment_end>
      // Only diffuse environment is occluded. Direct key shadows stay realtime.
      reflectedLight.indirectDiffuse *= mix(1., localFloor+(1.-localFloor)*vLocalLight.a, localVisibility);
      // Cycles DIFFUSE direct+indirect without COLOR is outgoing radiance/albedo.
      // Decode linear data; do not multiply it into the base color or apply gamma twice.
      reflectedLight.indirectDiffuse += material.diffuseColor * vLocalLight.rgb * localScale * localWarm;
    `);
  };
  material.customProgramCacheKey=()=> 'city-local-light-07';material.needsUpdate=true;
}

// Ground alone dissolves into the page outside the occupied district. Buildings retain
// their contrast at every distance. This is not distance fog or an image background.
export const groundWhite={value:new THREE.Vector3(1,1,1)};
export function prepareStudioGround(material){
  material.name='07 seamless studio ground';
  material.onBeforeCompile=shader=>{
    shader.uniforms.groundWhite=groundWhite;
    shader.vertexShader='attribute float groundFade; varying float vGroundFade;\n'+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nvGroundFade=groundFade;');
    shader.fragmentShader='varying float vGroundFade; uniform vec3 groundWhite;\n'+shader.fragmentShader;
    shader.fragmentShader=shader.fragmentShader.replace('#include <opaque_fragment>','outgoingLight=mix(outgoingLight,groundWhite,vGroundFade);\n#include <opaque_fragment>');
  };
  material.customProgramCacheKey=()=> 'city-studio-ground-07';
}

// Invert Three r170's AgX display transform once, for a precisely matched page edge.
// Constant background radiance never contributes light to models or to warm-only bloom.
const multiply=(m,v)=>m.map(row=>row.reduce((n,x,i)=>n+x*v[i],0));
function agx(v){
  v=multiply([[.6274,.3293,.0433],[.0691,.9195,.0113],[.0164,.088,.8956]],v);
  v=multiply([[.8566271533,.0951212405,.0482516061],[.1373189729,.7612419906,.1014390365],[.111898213,.0767994186,.8113023684]],v);
  v=v.map(x=>{x=Math.min(1,Math.max(0,(Math.log2(Math.max(x,1e-10))+12.47393)/16.499999));return 15.5*x**6-40.14*x**5+31.96*x**4-6.868*x**3+.4298*x*x+.1191*x-.00232;});
  v=multiply([[1.1271005818,-.1106066431,-.0164939387],[-.1413297635,1.1578237022,-.0164939387],[-.1413297635,-.1106066431,1.2519364066]],v).map(x=>Math.max(0,x)**2.2);
  return multiply([[1.6605,-.5876,-.0728],[-.1246,1.1329,-.0083],[-.0182,-.1006,1.1187]],v);
}
export function matchGroundWhite(exposure){
  const target=new THREE.Color('#f5f4f0').toArray(),v=[4,4,4];
  for(let iteration=0;iteration<18;iteration++){
    const actual=agx(v),matrix=new THREE.Matrix3();
    const columns=v.map((_,i)=>{const p=[...v];p[i]+=.001;return agx(p).map((x,k)=>(x-actual[k])/.001);});
    matrix.set(...[0,1,2].flatMap(row=>columns.map(col=>col[row]))).invert();
    const error=new THREE.Vector3(...target.map((x,i)=>x-actual[i])).applyMatrix3(matrix);
    v.forEach((_,i)=>{v[i]=Math.max(.05,v[i]+error.getComponent(i));});
  }
  groundWhite.value.set(...v.map(x=>x/exposure));
}
