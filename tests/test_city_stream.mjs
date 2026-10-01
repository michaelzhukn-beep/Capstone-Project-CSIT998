import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CHUNK_WIDTH,chunkIds,makeChunk,riverY,landHeight,createJourneyClock} from '../design/white-city/city-stream-layout.mjs';
const assets=JSON.parse(readFileSync(new URL('../design/white-city/blender/city-04-assets.json',import.meta.url))).assets;
let checked=0,minRepeat=Infinity;
for(const center of [-10000,-21,-1,0,1,25,10000,520833]){
  const chunks=chunkIds(center*CHUNK_WIDTH).map(i=>makeChunk(i,assets));
  for(const c of chunks){
    assert.deepEqual(makeChunk(c.index,assets),c,'Revisiting a coordinate must produce the same district');
    const seam=(c.index+1)*CHUNK_WIDTH;
    assert.ok(Math.abs(riverY(seam-1e-5)-riverY(seam+1e-5))<.00001,'River seam continuous');
    assert.ok(Math.abs(landHeight(seam-1e-5,80)-landHeight(seam+1e-5,80))<.00001,'Terrain seam continuous');
    for(const b of c.buildings){
      for(let x=b.x-b.w/2;x<=b.x+b.w/2;x+=.5)
        assert.ok(Math.abs(b.y-riverY(x))>b.d/2+26,`Waterfront overlap ${c.index}/${b.slot}/${b.row}`);
      if(c.bridge!==null&&Math.abs(b.y-riverY(c.bridge))<40+b.d/2)
        assert.ok(Math.abs(b.x-c.bridge)>b.w/2+8,'Bridge approach must stay clear');
      checked++;
    }
  }
  const all=chunks.flatMap(c=>c.buildings);
  for(let i=0;i<all.length;i++)for(const b of all.slice(i+1)){
    const a=all[i],dx=Math.abs(a.x-b.x),dy=Math.abs(a.y-b.y);
    assert.ok(dx>(a.w+b.w)/2+1||dy>(a.d+b.d)/2+1,'Buildings must not overlap');
    if(a.form===b.form&&a.lod==='near'&&b.lod==='near'){
      const d=Math.hypot(dx,dy);minRepeat=Math.min(d,minRepeat);
      assert.ok(d>60,`Repeated foreground form too close: ${a.form}, ${d}`);
    }
  }
}
// Ring stays bounded and shifts without a camera-space discontinuity, including negative travel.
for(const d of [-192.001,-192,191.999,192,100000000]){
  assert.equal(chunkIds(d).length,9);
  const index=Math.floor(d/CHUNK_WIDTH),origin=index*CHUNK_WIDTH;
  for(const chunk of chunkIds(d)){
    const local=(chunk-index)*CHUNK_WIDTH-(d-origin);
    assert.ok(Math.abs(local)<CHUNK_WIDTH*5);
    assert.ok(Math.abs(local-(chunk*CHUNK_WIDTH-d))<1e-7);
  }
}
const clock=createJourneyClock();clock.tick(0);clock.tick(100);assert.equal(clock.distance,.24);
clock.playing=false;clock.tick(200);assert.equal(clock.distance,.24,'Pause freezes travel');
clock.playing=true;clock.tick(300,false);assert.equal(clock.distance,.24,'Hidden page freezes travel');
clock.tick(1000000);assert.ok(clock.distance<1,'Resume must not jump by hidden wall time');
clock.seek(3000);clock.tick(1000100);assert.equal(clock.distance,3000,'Seek resets time integration');
console.log(`CITY_STREAM_PASS ${checked} building footprints; minimum near repeat spacing ${minRepeat.toFixed(1)}m; deterministic seams, bounded chunks, clock lifecycle`);
