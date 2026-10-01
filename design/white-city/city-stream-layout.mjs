// Shared, deterministic world coordinates. This module has no browser or Three.js dependency.
export const CHUNK_WIDTH=192;
export const SLOT_WIDTH=48;
export const STREAM_RADIUS=4;
export const ROW_OFFSETS=[-144,-92,-40,48,100,152,204,260,320,392];
const mod=(n,d)=>((n%d)+d)%d;
export function hash(a,b=0,salt=0){
  let n=(Math.imul(a|0,374761393)^Math.imul(b|0,668265263)^Math.imul(salt|0,1442695041)^404)>>>0;
  n=Math.imul(n^(n>>>13),1274126177);return ((n^(n>>>16))>>>0)/4294967296;
}
// Bounded, smooth river and terrain: adjoining chunks evaluate the same world coordinate.
export function riverY(x){return 19*Math.sin(x/260)+9*Math.sin(x/97);}
export function landHeight(x,y){
  const offset=y-riverY(x);
  return .7+Math.max(0,offset-35)*.026+Math.max(0,offset)*.007*(1+Math.sin(x/340));
}
export function bridgeX(chunk){return mod(chunk,5)===0?chunk*CHUNK_WIDTH+96:null;}
export function chunkIds(distance,radius=STREAM_RADIUS){
  const center=Math.floor(distance/CHUNK_WIDTH);
  return Array.from({length:radius*2+1},(_,i)=>center+i-radius);
}
const lowPalettes=[['pavilion','colonnade'],['terrace','courtyard','corner','gabled'],['gallery','court_pavilion','cascading','slab','sawtooth']];
const towerPalettes=[['tower'],['rounded'],['blade'],['stepped']];
export function makeChunk(index,assets){
  const buildings=[],trees=[];
  const usable=assets.filter(a=>a.kind==='building');
  const bridge=bridgeX(index);
  for(let row=0;row<ROW_OFFSETS.length;row++)for(let column=0;column<4;column++){
    const slot=index*4+column;
    // Three disjoint palettes make immediate neighbours different without cross-chunk state.
    const skyline=row===5||row===6;
    const palettes=skyline?towerPalettes:lowPalettes;
    const palette=palettes[mod(slot+row,palettes.length)].filter(f=>usable.some(a=>a.form===f));
    if(!palette.length)throw new Error('The asset library is missing a required architectural palette');
    const form=palette[Math.floor(hash(slot,row,2)*palette.length)];
    const pool=usable.filter(a=>a.form===form);
    const asset=pool[Math.floor(hash(slot,row,3)*pool.length)];
    const x=slot*SLOT_WIDTH+24+(hash(slot,row,4)-.5)*3;
    const y=riverY(x)+ROW_OFFSETS[row]+(hash(slot,row,5)-.5)*2;
    const scale=.82+hash(slot,row,6)*.24;
    const sx=scale*(.9+hash(slot,row,9)*.16),sz=scale*(.94+hash(slot,row,10)*.12);
    // Distant skyline is quieter; variation is bounded so entrances and windows stay believable.
    const sy=(.83+hash(slot,row,7)*.29)*(skyline?(.55+.45*(.5+.5*Math.sin(x/285))):1);
    const w=asset.width*sx,d=asset.depth*sz;
    const yaw=hash(slot,row,8)>.5?Math.PI:0;
    if(bridge!==null&&Math.abs(x-bridge)<w/2+11&&Math.abs(ROW_OFFSETS[row])<80)continue;
    // Check complete footprint against the analytic river, not just the centre point.
    const samples=[x-w/2,x,x+w/2];
    if(samples.some(px=>Math.abs(y-riverY(px))<d/2+28))continue;
    // Terrain rises smoothly; seat the base on its highest footprint corner.
    const z=Math.max(...samples.flatMap(px=>[landHeight(px,y-d/2),landHeight(px,y+d/2)]));
    buildings.push({slot,row,asset:asset.id,form,x,y,z,w,d,sx,sy,sz,yaw,lod:row>=8?'far':row===7?'mid':'near'});
  }
  for(let i=0;i<16;i++)for(const side of [-1,1]){
    const x=index*CHUNK_WIDTH+(i+.5)*12;
    if(bridge!==null&&Math.abs(x-bridge)<10)continue;
    const y=riverY(x)+side*(34+hash(index,i,side+20)*3);
    trees.push({x,y,z:landHeight(x,y),scale:1.2+hash(index,i,side+30)*.45});
  }
  for(const b of buildings.filter(b=>b.row<8))for(const side of [-1,1]){
    const x=b.x+side*(b.w/2+4),y=b.y-b.d/2-4;
    if(Math.abs(y-riverY(x))<29)continue;
    if(bridge!==null&&Math.abs(x-bridge)<10&&Math.abs(y-riverY(x))<45)continue;
    if(buildings.some(o=>Math.abs(x-o.x)<o.w/2+3&&Math.abs(y-o.y)<o.d/2+3))continue;
    trees.push({x,y,z:landHeight(x,y),scale:1.05+hash(b.slot,b.row,50+side)*.45,far:b.row>=6});
  }
  // Background parks break up the street-wall density without exposing the ground's edge.
  for(let i=0;i<18;i++){
    const x=index*CHUNK_WIDTH+hash(index,i,40)*CHUNK_WIDTH;
    const y=riverY(x)+85+hash(index,i,41)*295;
    if(buildings.some(b=>Math.abs(x-b.x)<b.w/2+4&&Math.abs(y-b.y)<b.d/2+4))continue;
    trees.push({x,y,z:landHeight(x,y),scale:.65+hash(index,i,42)*.4,far:true});
  }
  return {index,buildings,trees,bridge};
}

export function createJourneyClock(){
  return {distance:0,playing:true,last:null,
    tick(now,active=true,speed=2.4){
      if(this.last===null){this.last=now;return this.distance;}
      const dt=Math.min(.1,Math.max(0,(now-this.last)/1000));this.last=now;
      if(active&&this.playing)this.distance+=dt*speed;
      return this.distance;
    },
    seek(distance){this.distance=distance;this.last=null;}
  };
}
