import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
const chain=JSON.parse(await readFile(new URL('../src/data/molecules/polyethylene-chain.json',import.meta.url),'utf8'));

test('polyethylene artwork is one saturated C48H98 chain with consistent 3D bond geometry',()=>{
 assert.equal(chain.atoms.filter(a=>a.element==='C').length,48);
 assert.equal(chain.atoms.filter(a=>a.element==='H').length,98);
 assert.equal(chain.bonds.length,145);
 const adjacent=chain.atoms.map(()=>[]),seenBonds=new Set();
 for(const [a,b] of chain.bonds){
  assert.notEqual(a,b);assert.ok(chain.atoms[a]&&chain.atoms[b]);
  const key=[a,b].sort((x,y)=>x-y).join(':');assert.ok(!seenBonds.has(key));seenBonds.add(key);
  adjacent[a].push(b);adjacent[b].push(a);
  const distance=Math.hypot(...chain.atoms[a].position.map((v,i)=>v-chain.atoms[b].position[i]));
  const expected=chain.atoms[a].element===chain.atoms[b].element?1.54:1.091;
  assert.ok(Math.abs(distance-expected)<1e-8,`incorrect bond length ${key}: ${distance}`);
 }
 chain.atoms.forEach((a,i)=>assert.equal(adjacent[i].length,a.element==='C'?4:1));
 const visited=new Set([0]),queue=[0];for(let j=0;j<queue.length;j++)for(const next of adjacent[queue[j]])if(!visited.has(next)){visited.add(next);queue.push(next)}
 assert.equal(visited.size,146,'the artwork must be a single connected molecule');
 const vector=(a,b)=>chain.atoms[a].position.map((v,i)=>v-chain.atoms[b].position[i]);
 for(let i=1;i<47;i++){const a=vector(i-1,i),b=vector(i+1,i);const cosine=a.reduce((s,v,k)=>s+v*b[k],0)/(Math.hypot(...a)*Math.hypot(...b));assert.ok(Math.abs(Math.acos(cosine)*180/Math.PI-112)<1e-8)}
});
