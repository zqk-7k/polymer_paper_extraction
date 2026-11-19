/** Idealized all-trans, hydrogen-capped polyethylene segment; not an
 * experimentally refined structure or a polymer identified in an uploaded PDF. */
const fs=require('node:fs');
const count=Number(process.argv[2]||48);
const target=process.argv[3]||'web_portal/src/data/molecules/polyethylene-chain.json';
const cc=1.54,ch=1.091,angle=112*Math.PI/180,turn=(Math.PI-angle)/2;
const normalize=v=>{const n=Math.hypot(...v);return v.map(x=>x/n)};
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const atoms=[],bonds=[];
for(let i=0;i<count;i++)atoms.push({element:'C',position:[(i-(count-1)/2)*cc*Math.cos(turn),(i%2?1:-1)*cc*Math.sin(turn)/2,0]});
for(let i=1;i<count;i++)bonds.push([i-1,i]);
for(let i=0;i<count;i++){
 const p=atoms[i].position;
 const direction=j=>normalize(atoms[j].position.map((x,k)=>x-p[k]));
 const addH=v=>{bonds.push([i,atoms.length]);atoms.push({element:'H',position:p.map((x,k)=>x+ch*v[k])})};
 if(i>0&&i<count-1){
  const u=direction(i-1),v=direction(i+1),bisector=normalize(u.map((x,k)=>x+v[k])),normal=normalize(cross(u,v));
  const a=1/(3*Math.cos(angle/2)),b=Math.sqrt(1-a*a);
  for(const sign of [-1,1])addH(bisector.map((x,k)=>-a*x+sign*b*normal[k]));
 }else{
  const u=direction(i===0?1:i-1),e1=normalize(cross(u,[0,0,1])),e2=cross(u,e1);
  for(let j=0;j<3;j++){const phi=2*Math.PI*j/3;addH(u.map((x,k)=>-x/3+Math.sqrt(8/9)*(Math.cos(phi)*e1[k]+Math.sin(phi)*e2[k])))}
 }
}
const long=count===48;
const data={name:long?'Hydrogen-capped all-trans polyethylene segment':'Hydrogen-capped all-trans alkane segment',formula:`C${count}H${2*count+2}`,units:'angstrom',model:long?'Idealized finite chain, 24 ethylene repeat units with hydrogen end caps; not experimental Cartesian data':'Idealized finite zigzag alkane with hydrogen end caps; not experimental Cartesian data',parameters:{carbonCount:count,ccLength:cc,chLength:ch,cccAngleDegrees:112},references:['https://dasher.wustl.edu/bio5357/readings/rubinstein-chapter2.pdf','https://cccbdb.nist.gov/exp2x.asp?casno=74840&charge=0'],atoms,bonds};
fs.writeFileSync(target,JSON.stringify(data,null,2)+'\n');console.log(target,data.formula,atoms.length,'atoms',bonds.length,'bonds');
