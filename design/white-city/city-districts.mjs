import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {CHUNK_WIDTH,chunkIds,makeChunk,riverY,landHeight,hash} from './city-district-layout.mjs?v=06.2';
import {prepareLocalLight,prepareStudioGround} from './city-local-light.mjs';

// Reuse actual Blender geometry. Only transforms and district terrain are generated here.
export async function createDistrictStream({studio=false,assetVersion='07'}={}){
  if(!['07','08'].includes(assetVersion))throw new Error('Unsupported city light assets');
  const [gltf,metadata]=await Promise.all([
    new GLTFLoader().loadAsync(studio?`blender/city-${assetVersion}-assets.glb`:'blender/city-04-assets.glb'),
    fetch('blender/city-04-assets.json').then(r=>{if(!r.ok)throw new Error('Asset manifest unavailable');return r.json();})
  ]);
  const root=new THREE.Group(),chunks=new Map(),templates=new Map();
  const dummy=new THREE.Object3D();let currentCenter=null;
  gltf.scene.updateMatrixWorld(true);
  for(const asset of metadata.assets){
    const parent=gltf.scene.getObjectByName(asset.id);
    if(!parent)throw new Error(`Missing Blender asset: ${asset.id}`);
    const inverse=parent.matrixWorld.clone().invert(),parts=new Map();
    parent.traverse(obj=>{if(!obj.isMesh)return;
      const geometry=obj.geometry.clone();geometry.applyMatrix4(inverse.clone().multiply(obj.matrixWorld));
      if(studio)prepareLocalLight(geometry,obj.material,assetVersion==='08'?64:16);
      const key=obj.material.uuid;if(!parts.has(key))parts.set(key,{material:obj.material,geometries:[]});
      parts.get(key).geometries.push(geometry);
    });
    templates.set(asset.id,[...parts.values()].map(p=>{
      const geometry=mergeGeometries(p.geometries,false);
      if(!geometry)throw new Error(`Cannot merge ${asset.id}`);
      p.geometries.forEach(g=>g.dispose());
      // Imported real glazing retains material parameters; no image plane or screenshot.
      return {geometry,material:p.material};
    }));
  }
  const mats={
    earth:new THREE.MeshStandardMaterial({color:0xdeddd4,roughness:.72}),
    stone:new THREE.MeshStandardMaterial({color:0xdedfd7,roughness:.5}),
    ceramic:new THREE.MeshStandardMaterial({color:0xe2e4db,roughness:.42}),
    water:new THREE.MeshStandardMaterial({color:0xa4b8b0,roughness:.23,metalness:.13}),
  };
  mats.road=new THREE.MeshStandardMaterial({color:0xc7c9c2,roughness:.86});
  mats.garden=new THREE.MeshStandardMaterial({color:0xd4d6cc,roughness:.9});
  mats.foliage=new THREE.MeshStandardMaterial({color:0xdcded4,roughness:.78});
  mats.water.name='Continuous river surface';
  if(studio)prepareStudioGround(mats.earth);
  if(studio&&assetVersion==='08'){
    mats.earth.color.setRGB(.90,.895,.87);mats.stone.color.setRGB(.86,.855,.83);
    mats.ceramic.color.setRGB(.88,.875,.85);mats.road.color.setRGB(.81,.815,.79);
    mats.garden.color.setRGB(.80,.815,.77);mats.foliage.color.setRGB(.86,.865,.84);
  }
  const box=new THREE.BoxGeometry(1,1,1);
  const shrubParts=[];
  for(let i=0;i<5;i++){const g=new THREE.SphereGeometry(1,6,4);g.scale(.7,.55,.6);g.translate(Math.cos(i*2.4)*.55,.35+hash(i,0,19)*.3,Math.sin(i*2.4)*.45);shrubParts.push(g);}
  const shrubGeometry=mergeGeometries(shrubParts,false);shrubParts.forEach(g=>g.dispose());
  const benchParts=[];
  for(const [pos,scale] of [[[0,.5,0],[2.4,.12,.65]],[[-.8,.23,0],[.16,.46,.5]],[[.8,.23,0],[.16,.46,.5]],[[0,.8,.28],[2.4,.12,.1]]]){
    const g=box.clone();g.scale(...scale);g.translate(...pos);benchParts.push(g);
  }
  const benchGeometry=mergeGeometries(benchParts,false);benchParts.forEach(g=>g.dispose());
  function instances(group,geometry,material,items){
    if(!items.length)return;const mesh=new THREE.InstancedMesh(geometry,material,items.length);
    items.forEach((p,i)=>{dummy.position.set(p.x,p.z,-p.y);dummy.rotation.set(0,p.yaw||0,0);dummy.scale.set(p.w||p.scale||1,p.h||p.scale||1,p.d||p.scale||1);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);});
    mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);
  }
  function crossStreet(group,start,edge,from,to,width,material){
    const verts=[],indices=[],steps=Math.ceil((to-from)/8);
    for(let i=0;i<=steps;i++)for(const x of [edge-width/2,edge+width/2]){
      const clipped=Math.max(start,Math.min(start+CHUNK_WIDTH,x)),y=riverY(clipped)+from+(to-from)*i/steps;
      verts.push(clipped-start,landHeight(clipped,y)+(material===mats.road?.045:.025),-y);
    }
    for(let i=0;i<steps;i++){const k=i*2;indices.push(k,k+1,k+2,k+1,k+3,k+2);}
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));g.setIndex(indices);g.computeVertexNormals();
    const mesh=new THREE.Mesh(g,material);mesh.userData.ownedGeometry=true;mesh.receiveShadow=true;mesh.material.side=THREE.DoubleSide;group.add(mesh);
  }
  let disposed=0,totalCreated=0;
  function batch(group,key,placements){
    for(const part of templates.get(key)){
      const mesh=new THREE.InstancedMesh(part.geometry,part.material,placements.length);
      placements.forEach((p,i)=>{
        dummy.position.set(p.x,p.z,-p.y);dummy.rotation.set(0,p.yaw||0,0);
        dummy.scale.set(p.sx||p.scale||1,p.sy||p.scale||1,p.sz||p.scale||1);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);
      });
      mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();mesh.castShadow=true;mesh.receiveShadow=true;
      group.add(mesh);
    }
  }
  function ribbon(group,start,a,b,height,material){
    const points=[],indices=[],groundFade=[];
    for(let i=0;i<=CHUNK_WIDTH/4;i++){
      const wx=start+i*4;
      for(const offset of [a,b]){
        const y=riverY(wx)+offset;
        points.push(wx-start,height(wx,y),-y);
        groundFade.push(Math.max(THREE.MathUtils.smoothstep(-offset,180,240),THREE.MathUtils.smoothstep(offset,360,580)));
      }
      if(i<CHUNK_WIDTH/4){const k=i*2;indices.push(k,k+2,k+1,k+1,k+2,k+3);}
    }
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(points,3));g.setIndex(indices);g.computeVertexNormals();
    if(studio&&material===mats.earth)g.setAttribute('groundFade',new THREE.Float32BufferAttribute(groundFade,1));
    const mesh=new THREE.Mesh(g,material);mesh.userData.ownedGeometry=true;mesh.receiveShadow=material!==mats.water;group.add(mesh);
  }
  function build(index){
    const plan=makeChunk(index,metadata.assets),group=new THREE.Group(),start=index*CHUNK_WIDTH;
    const buckets=new Map();
    const add=(id,p)=>{if(!buckets.has(id))buckets.set(id,[]);buckets.get(id).push({...p,x:(p.modelX??p.x)-start,y:p.modelY??p.y});};
    const foundations=[],podiums=[];
    for(const b of plan.buildings){
      if(b.lod==='far')continue;
      add(b.asset,b);
      // Foundations absorb slope changes below the original level ground floor.
      foundations.push({x:b.x-start,y:b.y,z:b.z-.3,w:b.w,h:.6,d:b.d});
      if(b.tall)podiums.push({x:b.x-start,y:b.y,z:b.z+1.4,w:b.w*.98,h:2.8,d:b.d*.98});
    }
    // Far buildings have coarse but varied volumes, sharing one draw call per material.
    const far=[];
    for(const b of plan.buildings.filter(b=>b.lod==='far')){
      const a=metadata.assets.find(a=>a.id===b.asset),height=Math.min(23,a.height*b.sy);
      far.push({x:b.x-start,y:b.y,z:b.z+height/2,w:b.w,d:b.d,h:height});
      far.push({x:b.x-start-b.w*.09,y:b.y+b.d*.08,z:b.z+height+.45,w:b.w*.74,d:b.d*.73,h:.9});
    }
    const distant=new THREE.InstancedMesh(box,mats.ceramic,far.length);
    far.forEach((b,i)=>{dummy.position.set(b.x,b.z,-b.y);dummy.rotation.set(0,0,0);dummy.scale.set(b.w,b.h,b.d);dummy.updateMatrix();distant.setMatrixAt(i,dummy.matrix);});
    distant.instanceMatrix.needsUpdate=true;distant.computeBoundingSphere();distant.castShadow=true;distant.receiveShadow=true;group.add(distant);
    instances(group,box,mats.stone,foundations);
    instances(group,box,mats.ceramic,podiums);
    plan.trees.forEach(p=>add(p.asset,p));
    instances(group,shrubGeometry,mats.foliage,plan.shrubs.map(p=>({...p,x:p.x-start})));
    instances(group,benchGeometry,mats.stone,plan.benches.map(p=>({...p,x:p.x-start})));
    for(const p of plan.gardens){
      const corners=[[-1,-1],[1,-1],[1,1],[-1,1]].map(([a,b])=>[p.x+a*p.w/2,p.y+b*p.d/2]);
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(corners.flatMap(([x,y])=>[x-start,landHeight(x,y)+.025,-y]),3));
      g.setIndex([0,1,2,0,2,3]);g.computeVertexNormals();const mesh=new THREE.Mesh(g,mats.garden);mesh.userData.ownedGeometry=true;mesh.receiveShadow=true;group.add(mesh);
    }
    for(const [key,items] of buckets)batch(group,key,items);
    ribbon(group,start,-22,22,()=>.10,mats.water);
    for(const side of [-1,1]){
      const limits=side<0?[-250,-26]:[26,650];
      // Rows of terrain give far hills a gradual rise and perfectly matching edge vertices.
      for(let offset=limits[0];offset<limits[1];offset+=8)
        ribbon(group,start,offset,Math.min(offset+8,limits[1]),landHeight,mats.earth);
      ribbon(group,start,side<0?-26:22,side<0?-22:26,(x,y)=>landHeight(x,y)+.04,mats.stone);
      ribbon(group,start,side<0?-22.35:22,side<0?-22:22.35,(x,y)=>landHeight(x,y)+.12,mats.ceramic);
      // Quay face closes the vertical gap between land and water, continuous at chunk seams.
      const vertices=[],indices=[];
      for(let i=0;i<=CHUNK_WIDTH/4;i++){
        const x=start+i*4,y=riverY(x)+side*22;
        vertices.push(x-start,.08,-y,x-start,landHeight(x,y)+.12,-y);
        if(i<CHUNK_WIDTH/4){const k=i*2;indices.push(k,k+1,k+2,k+2,k+1,k+3);}
      }
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));g.setIndex(indices);g.computeVertexNormals();
      const wall=new THREE.Mesh(g,mats.stone);wall.material.side=THREE.DoubleSide;wall.userData.ownedGeometry=true;group.add(wall);
    }
    for(const street of plan.streets){
      ribbon(group,start,street.offset-street.width/2-1.4,street.offset+street.width/2+1.4,(x,y)=>landHeight(x,y)+.025,mats.stone);
      ribbon(group,start,street.offset-street.width/2,street.offset+street.width/2,(x,y)=>landHeight(x,y)+.045,mats.road);
    }
    for(const edge of [start,start+CHUNK_WIDTH])for(const [a,b] of [[-250,-25],[25,650]]){
      crossStreet(group,start,edge,a,b,12,mats.stone);crossStreet(group,start,edge,a,b,8,mats.road);
    }
    if(plan.bridge!==null){
      const x=plan.bridge-start,y=riverY(plan.bridge),vertices=[],indices=[];
      for(let i=0;i<=32;i++){
        const t=i/32,yy=y+(t-.5)*58,zz=landHeight(plan.bridge,yy)+.12+3.1*Math.sin(Math.PI*t);
        vertices.push(x-2.4,zz,-yy,x+2.4,zz,-yy);
        if(i<32){const k=i*2;indices.push(k,k+1,k+2,k+1,k+3,k+2);}
        if(i%4===0)for(const s of [-1,1]){
          const rail=new THREE.Mesh(box,mats.ceramic);rail.position.set(x+s*2.4,zz+.45,-yy);rail.scale.set(.08,.9,.08);group.add(rail);
        }
      }
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));g.setIndex(indices);g.computeVertexNormals();
      const deck=new THREE.Mesh(g,mats.ceramic);deck.userData.ownedGeometry=true;deck.castShadow=true;group.add(deck);
    }
    // Terrain strips share a material: merge them to avoid a draw call per cross-section.
    for(const material of Object.values(mats)){
      const pieces=group.children.filter(o=>o.isMesh&&!o.isInstancedMesh&&o.userData.ownedGeometry&&o.material===material);
      if(pieces.length<2)continue;
      const geometry=mergeGeometries(pieces.map(o=>o.geometry),false);
      pieces.forEach(o=>{group.remove(o);o.geometry.dispose();});
      const mesh=new THREE.Mesh(geometry,material);mesh.userData.ownedGeometry=true;mesh.receiveShadow=material!==mats.water;group.add(mesh);
    }
    group.userData.plan=plan;root.add(group);chunks.set(index,group);totalCreated++;
  }
  function remove(index){
    const group=chunks.get(index);root.remove(group);
    group.traverse(o=>{if(o.isInstancedMesh)o.dispose();if(o.userData.ownedGeometry)o.geometry.dispose();});
    chunks.delete(index);disposed++;
  }
  let lastRadius=null;
  function update(distance,aspect=16/9){
    // Include the complete visible width before recycling; wide monitors receive more chunks.
    const radius=Math.max(4,Math.ceil((800*Math.tan(THREE.MathUtils.degToRad(18))*aspect+55)/CHUNK_WIDTH)+1);
    const center=Math.floor(distance/CHUNK_WIDTH);
    if(center!==currentCenter||radius!==lastRadius){
      const wanted=new Set(chunkIds(distance,radius));
      for(const index of [...chunks.keys()])if(!wanted.has(index))remove(index);
      for(const index of wanted)if(!chunks.has(index))build(index);
      currentCenter=center;lastRadius=radius;
    }
    // Logical coordinates grow; GPU coordinates stay near zero. No jump when origin rebases.
    const origin=center*CHUNK_WIDTH,local=distance-origin;
    for(const [index,group] of chunks){group.position.set((index-center)*CHUNK_WIDTH-local,0,riverY(distance));}
    return {distance,center,chunks:chunks.size,created:totalCreated,recycled:disposed,origin,
      buildings:[...chunks.values()].reduce((n,c)=>n+c.userData.plan.buildings.length,0)};
  }
  return {root,update,dispose(){for(const i of [...chunks.keys()])remove(i);for(const p of templates.values())p.forEach(x=>x.geometry.dispose());box.dispose();shrubGeometry.dispose();benchGeometry.dispose();Object.values(mats).forEach(m=>m.dispose());}};
}
