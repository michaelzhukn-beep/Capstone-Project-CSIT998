// Export the very same deterministic parcels used by the browser for a Cycles comparison.
import {readFileSync,writeFileSync} from 'node:fs';
import {CHUNK_WIDTH,makeChunk,riverY,landHeight,STREETS} from '../city-district-layout.mjs';
const root=new URL('./',import.meta.url),assets=JSON.parse(readFileSync(new URL('city-04-assets.json',root))).assets;
const chunks=Array.from({length:7},(_,i)=>makeChunk(i-3,assets));
const surfaces=new Map();
function quad(mat,vertices){
  if(!surfaces.has(mat))surfaces.set(mat,{material:mat,vertices:[],faces:[]});
  const mesh=surfaces.get(mat),base=mesh.vertices.length;mesh.vertices.push(...vertices);mesh.faces.push(vertices.map((_,i)=>base+i));
}
function ribbon(start,a,b,height,mat){
  for(let dx=0;dx<CHUNK_WIDTH;dx+=4){
    const corners=[[start+dx,a],[start+dx,b],[start+dx+4,b],[start+dx+4,a]];
    quad(mat,corners.map(([x,offset])=>{const y=riverY(x)+offset;return [x,y,height(x,y)];}));
  }
}
for(const c of chunks){const start=c.index*CHUNK_WIDTH;
  ribbon(start,-22,22,()=>.1,'water');
  for(const [lo,hi] of [[-250,-26],[26,650]])for(let o=lo;o<hi;o+=8)ribbon(start,o,Math.min(o+8,hi),landHeight,'earth');
  for(const side of [-1,1]){
    ribbon(start,side<0?-26:22,side<0?-22:26,(x,y)=>landHeight(x,y)+.04,'stone');
    ribbon(start,side<0?-22.35:22,side<0?-22:22.35,(x,y)=>landHeight(x,y)+.12,'ceramic');
    for(let dx=0;dx<CHUNK_WIDTH;dx+=4){const x=start+dx,xx=x+4,y=riverY(x)+side*22,yy=riverY(xx)+side*22;
      quad('stone',[[x,y,.08],[xx,yy,.08],[xx,yy,landHeight(xx,yy)+.12],[x,y,landHeight(x,y)+.12]]);
    }
  }
  for(const s of STREETS){
    ribbon(start,s.offset-s.width/2-1.4,s.offset+s.width/2+1.4,(x,y)=>landHeight(x,y)+.025,'stone');
    ribbon(start,s.offset-s.width/2,s.offset+s.width/2,(x,y)=>landHeight(x,y)+.045,'road');
  }
  for(const edge of [start,start+CHUNK_WIDTH])for(const [from,to] of [[-250,-25],[25,650]])for(const [width,mat] of [[12,'stone'],[8,'road']]){
    for(let o=from;o<to;o+=8){const corners=[[edge-width/2,o],[edge+width/2,o],[edge+width/2,Math.min(o+8,to)],[edge-width/2,Math.min(o+8,to)]];
      quad(mat,corners.map(([xx,offset])=>{const x=Math.max(start,Math.min(start+CHUNK_WIDTH,xx)),y=riverY(x)+offset;return [x,y,landHeight(x,y)+(mat==='road'?.045:.025)];}));
    }
  }
  for(const p of c.gardens)quad('garden',[[-1,-1],[1,-1],[1,1],[-1,1]].map(([a,b])=>{const x=p.x+a*p.w/2,y=p.y+b*p.d/2;return [x,y,landHeight(x,y)+.025];}));
  if(c.bridge!==null){const x=c.bridge,cy=riverY(x),span=[];
    for(let i=0;i<=32;i++){const t=i/32,y=cy+(t-.5)*58,z=landHeight(x,y)+.12+3.1*Math.sin(Math.PI*t);span.push([[x-2.4,y,z],[x+2.4,y,z]]);}
    for(let i=0;i<32;i++)quad('ceramic',[...span[i],...span[i+1].toReversed()]);
    c.bridgeRail=span.filter((_,i)=>i%4===0).flatMap(p=>p);
  }
}
const plan={source:'city-district-layout.mjs',seed:404,view:JSON.parse(readFileSync(new URL('../city-view.json',root))),assets,chunks,surfaces:[...surfaces.values()]};
writeFileSync(new URL('city-06-plan.json',root),JSON.stringify(plan));
console.log('DISTRICT_PLAN_EXPORTED',chunks.reduce((s,c)=>s+c.buildings.length,0),'buildings',chunks.reduce((s,c)=>s+c.trees.length,0),'trees');
