import './browser-env.mjs';
import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,fitSlide} from '../static/deck.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import JSZip from 'jszip';
import {buildExports} from '../scripts/export.mjs';

let browser;
before(async()=>{browser=await chromium.launch({headless:true})});
after(async()=>{await browser?.close()});
const svg=(w,h)=>'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="#608ab0"/></svg>`);
const project={title:'Media leggibili',theme:'paper',font:'Arial',template:'auto',canvas_mode:'adaptive',use_manim_diagrams:true,use_source_images:true};
const slide={diagram_render:{asset:'manim.png',engine:'manim',report:{display_min_width:747,display_min_height:498}},content:{
  title:'Diagramma e fotografia hanno spazio sufficiente',layout:'visual-right',diagram:{kind:'manim',scene:{}},image_id:'photo.jpg',
  blocks:[{heading:'Prima parte',text:'Il contenuto deve rimanere leggibile senza perdere parole. '.repeat(4)},
          {heading:'Seconda parte',text:'Le immagini sono parte del contenuto, non elementi decorativi da rimpicciolire. '.repeat(3)}]}};

async function render({value=slide,settings=project,photo=[900,600],scale=1}={}){
  const page=await browser.newPage();
  await page.setContent('<style>'+slideCSS+`.slide-frame{transform:scale(${scale});transform-origin:top left}</style>`+
    slideHTML(settings,value,0,{diagram:svg(1800,1200),image:svg(...photo)}));
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()))});
  return {page,frame:page.locator('.slide-frame')};
}
function dimensions(frame){
  const root=frame.getBoundingClientRect(),scale=root.width/1280;
  return [...frame.querySelectorAll('.visual')].map(e=>{
    const img=e.matches('img')?e:e.querySelector('img'),b=img.getBoundingClientRect(),r=img.naturalWidth/img.naturalHeight;
    const w=Math.min(b.width/scale,b.height/scale*r),h=w/r;
    return {kind:e.dataset.visualKind,w,h,ratio:r,fit:getComputedStyle(img).objectFit,
      inside:b.left>=root.left-1&&b.right<=root.right+1&&b.top>=root.top-1&&b.bottom<=root.bottom+1};
  });
}

for(const photo of [[900,600],[500,1000],[1600,400]])for(const scale of [1,.43]){
  test(`diagram and ${photo[0]}x${photo[1]} photo remain readable at scale ${scale}`,async()=>{
    const {page,frame}=await render({photo,scale});
    try{
      const text=await frame.textContent(),result=await frame.evaluate(fitSlide),media=await frame.evaluate(dimensions);
      assert.equal(result.overflow,false,JSON.stringify(result));
      assert.ok(result.height>=720&&result.height<=1440);
      assert.equal(await frame.textContent(),text);
      const chart=media.find(m=>m.kind==='diagram'),image=media.find(m=>m.kind==='image');
      assert.ok(chart.w>=746&&chart.h>=497,JSON.stringify(chart));
      assert.ok(image.w*image.h>=89000,JSON.stringify(image));
      assert.equal(image.fit,'contain');assert.equal(chart.fit,'contain');
      assert.ok(media.every(m=>m.inside));
      const again=await frame.evaluate(fitSlide);assert.equal(again.height,result.height);assert.equal(again.layout,result.layout);
    }finally{await page.close()}
  });
}

test('media can stack vertically instead of being squeezed side by side',async()=>{
  const value=structuredClone(slide);value.diagram_render.report={display_min_width:920,display_min_height:614};
  value.content.blocks=value.content.blocks.slice(0,1);value.content.blocks[0].text='Un testo breve accompagna due immagini leggibili.';
  const {page,frame}=await render({value});
  try{
    const result=await frame.evaluate(fitSlide),media=await frame.evaluate(dimensions);
    assert.equal(result.overflow,false,JSON.stringify(result));
    assert.ok(await frame.evaluate(e=>e.classList.contains('media-stacked')));
    assert.ok(media.find(m=>m.kind==='diagram').w>=919);
  }finally{await page.close()}
});

test('fixed slides report insufficient media space instead of claiming a readable fit',async()=>{
  const value=structuredClone(slide);value.diagram_render.report={display_min_width:1200,display_min_height:800};
  const {page,frame}=await render({value,settings:{...project,canvas_mode:'fixed'}});
  try{
    const result=await frame.evaluate(fitSlide);
    assert.equal(result.height,720);assert.equal(result.overflow,true);
    assert.equal(await frame.getAttribute('data-media-overflow'),'true');
  }finally{await page.close()}
});

test('PDF, native PowerPoint and frozen Slidev keep full-size diagram and portrait photo',async()=>{
  const root=fileURLToPath(new URL('..',import.meta.url));
  const out=await fs.mkdtemp(path.join(root,'logs/media-export-'));
  const ids={diagram:'manim-'+'b'.repeat(64)+'.png',image:'12345678-1234-1234-1234-123456789012.jpg'};
  const page=await browser.newPage();
  try{
    const urls={};
    for(const [kind,w,h] of [['diagram',1800,1200],['image',500,1000]]){
      urls[kind]=await page.evaluate(({w,h,kind})=>{
        const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
        const ctx=canvas.getContext('2d');ctx.fillStyle='#608ab0';ctx.fillRect(0,0,w,h);
        return canvas.toDataURL(kind==='diagram'?'image/png':'image/jpeg');
      },{w,h,kind});
      await fs.writeFile(path.join(out,ids[kind]),Buffer.from(urls[kind].split(',')[1],'base64'));
    }
    const value=structuredClone(slide);value.diagram_render.asset=ids.diagram;value.content.image_id=ids.image;
    const deck={...project,slides:[value],_media_dimensions:{[ids.diagram]:{width:1800,height:1200},[ids.image]:{width:500,height:1000}}};
    await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(deck,value,0,urls));
    await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
    const preview=await page.locator('.slide-frame').evaluate(fitSlide);
    assert.equal(preview.overflow,false);
    for(const format of ['pdf','pptx']){
      const file=await buildExports(deck,out,path.join(out,format),format);
      const [report]=JSON.parse(await fs.readFile(path.join(out,format,'layout-report.json'),'utf8'));
      assert.equal(report.overflow,false);assert.equal(report.height,preview.height);
      if(format==='pptx'){
        const zip=await JSZip.loadAsync(await fs.readFile(file)),xml=await zip.file('ppt/slides/slide1.xml').async('string');
        const sizes=[...xml.matchAll(/<p:pic>[\s\S]*?<a:ext cx="(\d+)" cy="(\d+)"\/>[\s\S]*?<\/p:pic>/g)]
          .map(m=>({w:Number(m[1])/9525,h:Number(m[2])/9525}));
        assert.equal(sizes.length,2);assert.ok(sizes[0].w>=746&&sizes[0].h>=497);
        assert.ok(sizes[1].w*sizes[1].h>=89000);assert.ok(Math.abs(sizes[1].w/sizes[1].h-.5)<.001);
      }
    }
    const frozen=JSON.parse(execFileSync(process.execPath,[path.join(root,'scripts/slidev_source.mjs')],
      {input:JSON.stringify(deck),encoding:'utf8',windowsHide:true}));
    assert.deepEqual(frozen.overflow,[]);
    assert.match(frozen.markdown,new RegExp('data-canvas-height="'+preview.height+'"'));
    const html=frozen.markdown.match(/<article\b[\s\S]*?<\/article>/)[0]
      .replace('./assets/'+ids.diagram,urls.diagram).replace('./assets/'+ids.image,urls.image);
    await page.setContent('<style>'+frozen.css+'</style>'+html);
    await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
    const sizes=await page.locator('.slide-frame').evaluate(dimensions);
    assert.ok(sizes[0].w>=746&&sizes[0].h>=497);assert.ok(sizes[1].w*sizes[1].h>=89000);
  }finally{await page.close()}
});
