/** Deterministic raster artwork. A sparse composition of small, real molecular
 * models — benzene, ethane, water and a short all-trans oligomer — rendered as
 * translucent spherical atoms and cylindrical bonds with an orthographic camera
 * and per-pixel depth testing. No generated topology.
 * Run from repository root: node web_portal/scripts/render-molecular-art.cjs
 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/Administrator/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
function withProvenance(png) {
  const text=Buffer.from('Source\0Real small-molecule geometries (benzene D6h, ethane D3d, water C2v, idealized all-trans C6H14). Bond lengths and angles follow NIST CCCBDB experimental values and standard geometry; rendered locally as spherical atoms and cylindrical bonds with rigid rotations and uniform orthographic scale. Decorative artwork only. https://cccbdb.nist.gov/','utf8');
  const data=Buffer.concat([Buffer.from('tEXt'),text]);let crc=0xffffffff;
  for(const byte of data){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
  const size=Buffer.alloc(4);size.writeUInt32BE(text.length);const sum=Buffer.alloc(4);sum.writeUInt32BE((crc^0xffffffff)>>>0);
  return Buffer.concat([png.subarray(0,-12),size,data,sum,png.subarray(-12)]);
}
const load = (file) => JSON.parse(fs.readFileSync(path.join('web_portal/src/data/molecules', file), 'utf8').replace(/^\uFEFF/, ''));
const molecules = {
  benzene: load('benzene.json'),
  ethane: load('ethane.json'),
  water: load('water.json'),
  hexane: load('hexane.json'),
  octane: load('octane.json')
};
/** Each placement is one complete molecule: position, uniform scale (px/angstrom),
 * rigid Euler rotation, and a decorative opacity multiplier. */
const scenes = {
  portal: {
    size: [2560, 1440],
    fade: [980, 1250],
    deep: true,
    placements: [
      { m: 'water', x: 1238, y: 50, s: 20, rx: -0.7, ry: 0.3, rz: 0.2, a: 0.5 },
      { m: 'benzene', x: 1404, y: 98, s: 30, rx: -0.62, ry: 0.4, rz: 0.55, a: 0.6 },
      { m: 'octane', x: 1626, y: 148, s: 31, rx: -0.85, ry: 0.2, rz: -0.5, a: 0.9 },
      { m: 'ethane', x: 1858, y: 88, s: 36, rx: -0.42, ry: 0.34, rz: 0.55, a: 0.95 },
      { m: 'benzene', x: 2124, y: 128, s: 52, rx: -0.55, ry: 0.24, rz: 0.1, a: 1 },
      { m: 'water', x: 2356, y: 78, s: 27, rx: -0.7, ry: 0.3, rz: 0.2, a: 0.8 },
      { m: 'ethane', x: 2414, y: 174, s: 25, rx: -0.55, ry: 0.35, rz: -0.45, a: 0.7 }
    ]
  },
  faq: {
    size: [1600, 480],
    focus: [1330, 64, 310],
    placements: [
      { m: 'benzene', x: 1398, y: 64, s: 22, rx: -0.55, ry: 0.26, rz: 0.15, a: 1 },
      { m: 'hexane', x: 1166, y: 56, s: 15, rx: -0.9, ry: 0.2, rz: -0.5, a: 0.8 },
      { m: 'ethane', x: 1272, y: 78, s: 20, rx: -0.45, ry: 0.34, rz: 0.5, a: 0.95 },
      { m: 'water', x: 1488, y: 92, s: 17, rx: -0.7, ry: 0.3, rz: 0.2, a: 0.8 }
    ]
  }
};
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium_headless_shell-1200/chrome-headless-shell-win64/chrome-headless-shell.exe'});
  const page = await browser.newPage();
  for (const [variant, scene] of Object.entries(scenes)) {
    const png = await page.evaluate(({ molecules, scene }) => {
      const [W, H] = scene.size;
      const canvas = document.createElement('canvas'); canvas.width=W; canvas.height=H;
      const ctx = canvas.getContext('2d');
      const image = ctx.createImageData(W,H), depth = new Float32Array(W*H).fill(-Infinity);
      const pixels=image.data;
      const normalize=a=>{const l=Math.hypot(...a);return a.map(v=>v/l)};
      const dot=(a,b)=>a.reduce((v,n,i)=>v+n*b[i],0);
      const light=normalize([-.55,-.8,1]), half=normalize([light[0],light[1],light[2]+1]);
      const palette=scene.deep
        ? {style:{C:{r:.41,color:[58,124,187]},H:{r:.20,color:[168,206,236]},O:{r:.41,color:[68,136,194]}},bond:[102,154,201]}
        : {style:{C:{r:.40,color:[88,150,205]},H:{r:.19,color:[190,219,242]},O:{r:.40,color:[100,162,210]}},bond:[136,180,214]};
      const style=palette.style;
      const primitives=[];
      for(const p of scene.placements){
        const source=molecules[p.m];
        const atoms=source.atoms.map(a=>{
          const [x,y,z]=a.position;
          const y1=y*Math.cos(p.rx)-z*Math.sin(p.rx),z1=y*Math.sin(p.rx)+z*Math.cos(p.rx);
          const rx=x*Math.cos(p.ry)+z1*Math.sin(p.ry),rz=-x*Math.sin(p.ry)+z1*Math.cos(p.ry);
          const st=style[a.element]||style.C;
          return {x:p.x+(rx*Math.cos(p.rz)-y1*Math.sin(p.rz))*p.s,y:p.y+(rx*Math.sin(p.rz)+y1*Math.cos(p.rz))*p.s,z:rz*p.s,r:p.s*st.r,color:st.color,alpha:p.a};
        });
        atoms.forEach(a=>primitives.push({...a,kind:'sphere'}));
        source.bonds.forEach(([i,j])=>{const a=atoms[i],b=atoms[j];const vec=[b.x-a.x,b.y-a.y,b.z-a.z],length=Math.hypot(...vec);primitives.push({kind:'cylinder',a,b,v:normalize(vec),length,r:p.s*.056,color:palette.bond,alpha:p.a})});
      }
      for(const q of primitives){
        const r=q.r;
        const x0=Math.max(0,Math.floor(q.kind==='sphere'?q.x-r:Math.min(q.a.x,q.b.x)-r));
        const x1=Math.min(W-1,Math.ceil(q.kind==='sphere'?q.x+r:Math.max(q.a.x,q.b.x)+r));
        const y0=Math.max(0,Math.floor(q.kind==='sphere'?q.y-r:Math.min(q.a.y,q.b.y)-r));
        const y1=Math.min(H-1,Math.ceil(q.kind==='sphere'?q.y+r:Math.max(q.a.y,q.b.y)+r));
        if(x0<=4||y0<=4||x1>=W-5||y1>=H-5)throw Error('Molecule exceeds image safe bounds');
        for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
          let z,normal,coverage=1;
          if(q.kind==='sphere'){
            const dx=x+.5-q.x,dy=y+.5-q.y,d2=dx*dx+dy*dy;
            if(d2>r*r)continue;const dz=Math.sqrt(r*r-d2);z=q.z+dz;normal=[dx/r,dy/r,dz/r];coverage=Math.min(1,(r-Math.sqrt(d2))*1.5);
          }else{
            const oc=[x+.5-q.a.x,y+.5-q.a.y,-q.a.z],dv=dot(oc,q.v),A=1-q.v[2]**2,B=2*(oc[2]-dv*q.v[2]),C=dot(oc,oc)-dv*dv-r*r;
            const disc=B*B-4*A*C;if(disc<0||A<1e-8)continue;
            z=(-B+Math.sqrt(disc))/(2*A);const along=dv+z*q.v[2];if(along<0||along>q.length)continue;
            normal=normalize([oc[0]-along*q.v[0],oc[1]-along*q.v[1],z+oc[2]-along*q.v[2]]);
          }
          const k=y*W+x;if(z<depth[k])continue;depth[k]=z;
          const diffuse=Math.max(0,dot(normal,light)),spec=Math.pow(Math.max(0,dot(normal,half)),72),rim=Math.pow(1-normal[2],2);
          const shade=.87+.16*diffuse-.1*rim;
          for(let c=0;c<3;c++)pixels[k*4+c]=Math.min(255,q.color[c]*shade+46*spec+10*normal[2]**4);
          const density=q.kind==='sphere'
            ? (scene.deep?.52+.38*rim+.05*spec:.36+.42*rim+.07*spec)
            : (scene.deep?.86:.64);
          pixels[k*4+3]=Math.round(255*q.alpha*coverage*density);
        }
      }
      ctx.putImageData(image,0,0);
      // Dissolve the composition into the host surface instead of ending on a hard edge.
      ctx.globalCompositeOperation='destination-in';
      let mask;
      if(scene.fade){
        const [x0,x1]=scene.fade;
        mask=ctx.createLinearGradient(x0,0,x1,0);
        mask.addColorStop(0,'rgba(0,0,0,0)');mask.addColorStop(.65,'rgba(0,0,0,.86)');mask.addColorStop(1,'rgba(0,0,0,1)');
      }else{
        const [fx,fy,fr]=scene.focus;
        mask=ctx.createRadialGradient(fx,fy,fr*.18,fx,fy,fr);
        mask.addColorStop(0,'rgba(0,0,0,1)');mask.addColorStop(.6,'rgba(0,0,0,.98)');mask.addColorStop(1,'rgba(0,0,0,0)');
      }
      ctx.fillStyle=mask;ctx.fillRect(0,0,W,H);
      // A soft wash on the shaded geometry suggests translucent studio glass.
      ctx.globalCompositeOperation='source-atop';
      const wash=ctx.createLinearGradient(0,0,W,H);
      wash.addColorStop(0,scene.deep?'rgba(245,251,255,.16)':'rgba(245,251,255,.3)');
      wash.addColorStop(1,scene.deep?'rgba(224,242,255,.02)':'rgba(224,242,255,.05)');
      ctx.fillStyle=wash;ctx.fillRect(0,0,W,H);
      return canvas.toDataURL('image/png').split(',')[1];
    }, {molecules,scene});
    const target=path.join('web_portal/public/upload-art',`molecular-${variant}-large.png`);
    fs.writeFileSync(target,withProvenance(Buffer.from(png,'base64')));console.log(target,fs.statSync(target).size);
  }
  await browser.close();
})();
