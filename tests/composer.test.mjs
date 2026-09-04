import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,layouts,layoutCandidates,fitSlide} from '../static/deck.mjs';
import {buildExports,measureLayouts} from '../scripts/export.mjs';
process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));
const text='Un concetto diventa più chiaro quando colleghiamo la spiegazione a un esempio concreto. Le relazioni tra le parti aiutano a capire il risultato.';
const make=(layout,count=2)=>({title:'Una struttura adatta al contenuto',subtitle:'Spiegazioni, esempi e relazioni.',layout,
  bullets:[],sources:[],image_id:'',diagram:{kind:'none',labels:[]},
  blocks:Array.from({length:count},(_,i)=>({heading:['Il concetto','Un caso concreto','La conseguenza','Da ricordare'][i],
    text,kind:i?'example':layout==='quote'?'quote':'explanation',source:layout==='quote'?'Documento allegato, pagina 2':''}))});

test('old prose can change layout; recomposition is stable and preserves input',()=>{
  const c=make('content'),before=JSON.stringify(c),p={template:'auto'};
  const a=layoutCandidates(p,c,0),b=layoutCandidates(p,{...c,layout_variant:1},0);
  assert.notEqual(a[0],b[0]);assert.deepEqual(a,layoutCandidates(p,c,0));assert.equal(JSON.stringify(c),before);
  assert.equal(layoutCandidates(p,make('comparison'),0)[0],'comparison');
  assert.equal(layoutCandidates(p,make('steps'),0)[0],'steps');
  assert.ok(!layoutCandidates(p,make('visual-left'),0).includes('visual-left'));
});

test('all twelve compositions fit and native exports use the same measured layouts',async()=>{
  const browser=await chromium.launch();
  const manimAsset='manim-'+'0'.repeat(64)+'.png';
  const project={title:'Verifica composer',theme:'paper',font:'Segoe UI',template:'auto',text_density:'detailed',use_manim_diagrams:true,slides:[]};
  for(const layout of Object.keys(layouts)){
    const c=make(layout,layout==='cover'?1:layout==='cards'||layout==='timeline'?3:2);
    const slide={content:c};
    if(layout.startsWith('visual-')){
      c.diagram={kind:'manim',labels:[],brief:'Sorgente e risultato',scene:{}};
      slide.diagram_render={engine:'manim',asset:manimAsset};
    }
    project.slides.push(slide);
  }
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent('<!doctype html><style>'+slideCSS+'body{margin:0}</style>'+
      project.slides.map((s,i)=>slideHTML(project,s,i)).join(''));
    await page.evaluate(()=>document.fonts.ready);
    const measured=await measureLayouts(page);
    assert.deepEqual(measured.map(m=>m.layout),Object.keys(layouts));
    assert.ok(measured.every(m=>!m.overflow));
    const silhouettes=new Set(measured.map(m=>m.boxes.map(b=>[Math.round(b.x*96),Math.round(b.y*96),Math.round(b.w*96),Math.round(b.h*96)]).join(';')));
    assert.ok(silhouettes.size>=8,'Expected materially different silhouettes');
    const before=await page.locator('.slide-frame').allTextContents();
    for(const f of await page.locator('.slide-frame').all())await f.evaluate(fitSlide);
    assert.deepEqual(await page.locator('.slide-frame').allTextContents(),before);
    // Scaled preview and full-size export choose identical compositions.
    await page.addStyleTag({content:'.slide-frame{transform:scale(.43);transform-origin:top left}'});
    const scaled=await measureLayouts(page);
    assert.deepEqual(scaled.map(m=>[m.layout,m.overflow]),measured.map(m=>[m.layout,m.overflow]));
    const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-adaptive-export-'));
    await fs.writeFile(path.join(out,manimAsset),Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XMG8WQAAAABJRU5ErkJggg==','base64'));
    for(const format of ['pdf','pptx']){
      await buildExports(project,out,path.join(out,format),format);
      const report=JSON.parse(await fs.readFile(path.join(out,format,'layout-report.json'),'utf8'));
      assert.deepEqual(report.map(r=>r.layout),measured.map(m=>m.layout));
    }
  }finally{await browser.close()}
});

test('adaptive fallback conserves long paragraphs and respects custom font size',async()=>{
  const browser=await chromium.launch();
  try{
    const page=await browser.newPage();
    const c=make('timeline',4);c.blocks.forEach(b=>b.text=text.repeat(2));
    const project={title:'Paragrafi',theme:'paper',text_density:'complete',theme_design:{body_size:22}};
    const original=JSON.stringify(c);
    await page.setContent('<!doctype html><style>'+slideCSS+'</style>'+slideHTML(project,{content:c},0));
    const fitted=await page.locator('.slide-frame').evaluate(fitSlide);
    assert.equal(fitted.overflow,false);
    assert.equal(await page.locator('.prose-box p').first().evaluate(e=>getComputedStyle(e).fontSize),'22px');
    assert.equal(JSON.stringify(c),original);
    assert.deepEqual(await page.locator('.prose-box p').allTextContents(),c.blocks.map(b=>b.text));
  }finally{await browser.close()}
});
