// Regression for the owner's oblique view: independent landmark projection, not a
// screenshot hash. Protects camera direction/scale when the light rig is edited.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const root=new URL('../design/white-city/',import.meta.url);
const view=JSON.parse(readFileSync(new URL('city-view.json',root)));
const buildings=JSON.parse(readFileSync(new URL('blender/city-04-manifest.json',root))).buildings_layout;
const sub=(a,b)=>a.map((v,i)=>v-b[i]),dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
const unit=a=>a.map(v=>v/Math.hypot(...a));
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const forward=unit(sub(view.target,view.position)),right=unit(cross(forward,[0,1,0])),up=cross(right,forward);
const focal=566/Math.tan(view.verticalFov*Math.PI/360);
const observations=[[0,1,155,425],[0,0,164,835],[1,1,394,486],[1,0,401,805],[11,1,1094,314],[11,0,1090,609],[14,1,1407,268],[14,0,1407,547],[15,1,1446,188],[16,1,1517,232],[17,1,1634,297]];
let sum=0;
for(const [i,top,x,y] of observations){
  const b=buildings[i],p=sub([b.x,b.z+top*b.h,-b.y],view.position),depth=dot(p,forward);
  assert.ok(depth>0,'Landmark behind camera');
  const actual=[1024+focal*dot(p,right)/depth,566-focal*dot(p,up)/depth];
  const error=Math.hypot(actual[0]-x,actual[1]-y);
  assert.ok(error<25,`${b.tag}: changed reference framing (${error.toFixed(1)} px)`);sum+=error**2;
}
assert.ok(view.position[0]<-100&&view.position[1]<80,'Preserve left oblique low perspective');
const verified=JSON.parse(readFileSync(new URL('blender/lighting-verification-city-05.json',root)));
assert.deepEqual(verified.reference_camera,view,'Cycles and real-time must use the same camera preset');
assert.equal(verified.geometry_unchanged,true);
console.log(`CITY_VIEW_PASS ${observations.length} reference landmarks; RMS ${Math.sqrt(sum/observations.length).toFixed(1)} px at 2048 x 1132; shared Cycles/WebGL preset`);
