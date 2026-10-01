import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {CHUNK_WIDTH,chunkIds,makeChunk,riverY,landHeight,hash} from './city-stream-layout.mjs';

// Reuse actual Blender geometry. Only transforms and district terrain are generated here.
export async function createCityStream(){
  const [gltf,metadata]=await Promise.all([
    new GLTFLoader().loadAsync('blender/city-04-assets.glb'),
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
  mats.water.name='Continuous river surface';
  const box=new THREE.BoxGeometry(1,1,1);
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
    const points=[],indices=[];
    for(let i=0;i<=48;i++){
      const wx=start+i*4;
      for(const offset of [a,b]){
        const y=riverY(wx)+offset;
        points.push(wx-start,height(wx,y),-y);
      }
      if(i<48){const k=i*2;indices.push(k,k+2,k+1,k+1,k+2,k+3);}
    }
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(points,3));g.setIndex(indices);g.computeVertexNormals();
    const mesh=new THREE.Mesh(g,material);mesh.userData.ownedGeometry=true;mesh.receiveShadow=material!==mats.water;group.add(mesh);
  }
  function build(index){
    const plan=makeChunk(index,metadata.assets),group=new THREE.Group(),start=index*CHUNK_WIDTH;
    const buckets=new Map();
    const add=(id,p)=>{if(!buckets.has(id))buckets.set(id,[]);buckets.get(id).push({...p,x:p.x-start});};
    for(const b of plan.buildings){
      if(b.lod==='far')continue;
      add(b.asset,b);
      // Foundations absorb slope changes below the original level ground floor.
      const base=new THREE.Mesh(box,mats.stone);
      base.position.set(b.x-start,b.z-.35,-b.y);base.scale.set(b.w,.7,b.d);base.receiveShadow=true;group.add(base);
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
    plan.trees.forEach((p,i)=>add(p.far?'tree_2':`tree_${i%4===0?Math.floor(hash(index,i,90)*2):2}`,p));
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
      for(let i=0;i<=48;i++){
        const x=start+i*4,y=riverY(x)+side*22;
        vertices.push(x-start,.08,-y,x-start,landHeight(x,y)+.12,-y);
        if(i<48){const k=i*2;indices.push(k,k+1,k+2,k+2,k+1,k+3);}
      }
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));g.setIndex(indices);g.computeVertexNormals();
      const wall=new THREE.Mesh(g,mats.stone);wall.material.side=THREE.DoubleSide;wall.userData.ownedGeometry=true;group.add(wall);
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
  return {root,update,dispose(){for(const i of [...chunks.keys()])remove(i);for(const p of templates.values())p.forEach(x=>x.geometry.dispose());box.dispose();Object.values(mats).forEach(m=>m.dispose());}};
}
