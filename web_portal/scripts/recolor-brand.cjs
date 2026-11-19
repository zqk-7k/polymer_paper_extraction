/** Hue-only brand update: retains pixel positions, alpha and tonal detail. */
const fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/Administrator/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
(async()=>{
 const source=process.argv[2];if(!source)throw Error('Provide the original logo PNG as the source argument');
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'C:/Users/Administrator/AppData/Local/ms-playwright/chromium_headless_shell-1200/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 const page=await browser.newPage();
 const output=await page.evaluate(async source=>{
  const img=new Image();img.src=source;await img.decode();
  const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;const x=c.getContext('2d');x.drawImage(img,0,0);const data=x.getImageData(0,0,c.width,c.height),original=new Uint8ClampedArray(data.data);
  const hue=222.85714285714286/360,saturation=.7058823529411765,baseLightness=.4666666666666667;
  function hueToRgb(p,q,t){if(t<0)t++;if(t>1)t--;if(t<1/6)return p+(q-p)*6*t;if(t<1/2)return q;if(t<2/3)return p+(q-p)*(2/3-t)*6;return p}
  for(let i=0;i<data.data.length;i+=4){if(!data.data[i+3])continue;const r=data.data[i]/255,g=data.data[i+1]/255,b=data.data[i+2]/255,max=Math.max(r,g,b),min=Math.min(r,g,b),l=(max+min)/2;if(max-min<.025)continue;
   const light=l<=.5?l*baseLightness/.5:baseLightness+(l-.5)*(1-baseLightness)/.5;
   const q=light<.5?light*(1+saturation):light+saturation-light*saturation,p=2*light-q;
   data.data[i]=Math.round(hueToRgb(p,q,hue+1/3)*255);data.data[i+1]=Math.round(hueToRgb(p,q,hue)*255);data.data[i+2]=Math.round(hueToRgb(p,q,hue-1/3)*255);
  }
  let alphaChanged=0;for(let i=3;i<original.length;i+=4)if(original[i]!==data.data[i])alphaChanged++;
  if(alphaChanged)throw Error('Alpha mask changed');x.putImageData(data,0,0);
  const sizes={original:c.toDataURL('image/png')};for(const size of [32,180,192]){const a=document.createElement('canvas');a.width=a.height=size;const ctx=a.getContext('2d');ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(c,0,0,size,size);sizes[size]=a.toDataURL('image/png')}
  return {sizes,width:c.width,height:c.height,alphaChanged};
 },'data:image/png;base64,'+fs.readFileSync(source).toString('base64'));
 const save=(p,data)=>fs.writeFileSync(p,Buffer.from(data.split(',')[1],'base64'));
 save('web_portal/src/assets/logo2.png',output.sizes.original);save('web_portal/public/logo2.png',output.sizes.original);
 save('web_portal/public/favicon-32.png',output.sizes[32]);save('web_portal/public/favicon.png',output.sizes[192]);save('web_portal/public/apple-touch-icon.png',output.sizes[180]);
 console.log({width:output.width,height:output.height,alphaChanged:output.alphaChanged});await browser.close();
})();
