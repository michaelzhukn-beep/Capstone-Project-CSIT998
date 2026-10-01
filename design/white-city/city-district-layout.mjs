// Deterministic urban parcels, not a random transform of a copied city tile.
import {hash,createJourneyClock} from './city-stream-layout.mjs';
export {hash,createJourneyClock};
export const CHUNK_WIDTH=216,STREAM_RADIUS=4;
export const ROW_OFFSETS=[-190,-155,-120,-85,-46,47,82,117,152,187,222,264,306,348,394,442];
export const STREETS=[{offset:-65.5,width:6},{offset:64.5,width:5.5},{offset:134.5,width:6},{offset:243,width:8},{offset:370,width:8}];
const mod=(n,d)=>((n%d)+d)%d;
const LOW=['colonnade','terrace','court_pavilion','courtyard','pavilion','cascading','slab','gallery','gabled','corner','sawtooth'];
const TALL=['tower','rounded','blade','stepped'];
export function riverY(x){return 26*Math.sin(x/330)+13*Math.sin(x/151);}
export function landHeight(x,y){const d=y-riverY(x);return .7+Math.max(0,d-32)*(.032+.007*Math.sin(x/380));}
export function bridgeX(index){return mod(index,4)===0?index*CHUNK_WIDTH+108:null;}
export function chunkIds(distance,radius=STREAM_RADIUS){const c=Math.floor(distance/CHUNK_WIDTH);return Array.from({length:2*radius+1},(_,i)=>c+i-radius);}
export function districtStrength(x){return .5+.32*Math.sin(x/225)+.18*Math.sin(x/97+1.3);}
export function makeChunk(index,assets){
  const buildings=[],trees=[],gardens=[],shrubs=[],benches=[];
  const usable=assets.filter(a=>a.kind==='building'),byForm=new Map(LOW.concat(TALL).map(f=>[f,usable.filter(a=>a.form===f)]));
  const bridge=bridgeX(index),start=index*CHUNK_WIDTH;
  function waterSafe(x,y,w,d,clear=27){
    for(let xx=x-w/2;xx<=x+w/2+.001;xx+=Math.max(1,w/8))if(Math.abs(y-riverY(xx))<d/2+clear)return false;
    return true;
  }
  for(let row=0;row<ROW_OFFSETS.length;row++)for(let col=0;col<6;col++){
    const slot=index*6+col,offset=ROW_OFFSETS[row],front=row<8;
    const x=slot*36+18+(col===0?3.1:col===5?-3.1:0)+(hash(slot,row,104)-.5)*5;
    const y=riverY(x)+offset+(hash(slot,row,105)-.5)*3;
    const park=front&&(hash(Math.floor(slot/2),row,106)>(row===4||row===5?.82:.94));
    const onBridge=bridge!==null&&Math.abs(x-bridge)<25&&Math.abs(offset)<73;
    if(park||onBridge){if(!onBridge)gardens.push({x,y,w:25,d:23,z:landHeight(x,y),row});continue;}
    // Towers occur in a few deeper clusters, with mid-rise shoulders and low river fronts.
    const cluster=districtStrength(x),skyline=row>=8&&row<=13;
    const tall=skyline&&hash(slot,row,109)<Math.max(.06,(cluster-.1)*.78);
    const form=tall?TALL[mod(slot+2*row,4)]:LOW[mod(3*slot+4*row,11)];
    const pool=byForm.get(form);if(!pool?.length)throw new Error(`Missing district form ${form}`);
    const a=pool[Math.floor(hash(slot,row,103)*pool.length)];
    const edge=col===0||col===5;
    // Parcel widths bound complete asset extents, including stairs and awnings.
    const sx=Math.min((edge?25:29)/a.width,.89+hash(slot,row,110)*.21);
    const sz=Math.min(25/a.depth,.85+hash(slot,row,111)*.21);
    const w=a.width*sx,d=a.depth*sz;
    if(!waterSafe(x,y,w,d))continue;
    // A road bends across the entire footprint; its centre alone is insufficient.
    if(STREETS.some(s=>Array.from({length:9},(_,i)=>x-w/2+i*w/8)
      .some(xx=>Math.abs(y-riverY(xx)-s.offset)<d/2+s.width/2+.8)))continue;
    const sy=tall?(.65+.5*cluster)*(.87+hash(slot,row,112)*.24):.84+hash(slot,row,112)*.35;
    const z=Math.max(...[-w/2,0,w/2].flatMap(dx=>[-d/2,d/2].map(dy=>landHeight(x+dx,y+dy))));
    const sign=offset<0?1:-1;
    const modelX=x-sign*(a.bounds_min[0]+a.bounds_max[0])*sx/2;
    const modelY=y-sign*(a.bounds_min[1]+a.bounds_max[1])*sz/2;
    buildings.push({slot,row,asset:a.id,form,x,y,z,w,d,sx,sy,sz,yaw:offset<0?0:Math.PI,
      modelX,modelY,lod:row>=14?'far':row>=11?'mid':'near',height:a.height*sy,tall});
  }
  function clearOfBuildings(x,y,r=2.1){return !buildings.some(b=>Math.abs(x-b.x)<b.w/2+r&&Math.abs(y-b.y)<b.d/2+r);}
  function tree(x,y,scale,key,far=false){
    if(!waterSafe(x,y,2,2,25.5)||!clearOfBuildings(x,y,2))return;
    if(bridge!==null&&Math.abs(x-bridge)<7&&Math.abs(y-riverY(x))<40)return;
    if(STREETS.some(s=>Math.abs(y-riverY(x)-s.offset)<s.width/2+1.2))return;
    // Keep both neighbouring cross-streets clear without consulting other chunks.
    if(x-start<6||start+CHUNK_WIDTH-x<6)return;
    trees.push({x,y,z:landHeight(x,y),scale,far,asset:far?'tree_2':`tree_${hash(key,0,201)>.5?1:0}`});
  }
  // River gardens come in irregular groups. Paths remain open along both banks.
  for(let i=0;i<24;i++)for(const side of [-1,1]){
    const x=start+7+i*8.5+(hash(index,i,120+side)-.5)*3;
    const y=riverY(x)+side*(30+hash(index,i,130+side)*3);
    tree(x,y,1.02+hash(index,i,140+side)*.44,index*100+i+side);
    if(i%3===0&&clearOfBuildings(x,y+side*3))shrubs.push({x,y:y+side*3,z:landHeight(x,y+side*3),scale:.65+hash(index,i,150)*.5});
    if(i%6===2&&(bridge===null||Math.abs(x-bridge)>10)){const by=riverY(x)+side*25.5;benches.push({x,y:by,z:landHeight(x,by)+.05});}
  }
  for(const g of gardens){
    for(let n=0;n<7;n++){
      const x=g.x+(hash(index,g.row*100+n,161)-.5)*20,y=g.y+(hash(index,g.row*100+n,162)-.5)*18;
      tree(x,y,.95+hash(index,n+g.row*20,163)*.5,index*1000+g.row*10+n,g.row>9);
    }
    shrubs.push({...g,scale:1.5});
  }
  // Street trees and planted courtyard edges link buildings into blocks.
  for(const b of buildings){
    const side=b.row<5?-1:1;
    const x=b.x+(hash(b.slot,b.row,171)-.5)*b.w*.6,y=b.y+side*(b.d/2+3.1);
    tree(x,y,.88+hash(b.slot,b.row,172)*.42,b.slot*100+b.row,b.row>9);
    if(b.row<10&&clearOfBuildings(x+2,y,1.1))shrubs.push({x:x+2,y,z:landHeight(x+2,y),scale:.6+hash(b.slot,b.row,173)*.5});
  }
  return {index,buildings,trees,gardens,shrubs,benches,bridge,streets:STREETS};
}
