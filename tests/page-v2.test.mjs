import './browser-env.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright-chromium';
import JSZip from 'jszip';
import {slideHTML,slideCSS,fitSlide} from '../static/deck.mjs';
import {buildExports} from '../scripts/export.mjs';
import {movePageNode} from '../static/page-v2-editor.mjs';

const content={title:'Una pagina progettata',blocks:[],bullets:[],diagram:{kind:'none'},page:{version:2,style:{gap:26},nodes:[
  {id:'title',parent:'root',kind:'heading',text:'Sette idee, non quattro box',style:{font_size:48,bold:true}},
  {id:'columns',parent:'root',kind:'group',style:{flow:'columns',columns:[2,1],gap:30}},
  ...Array.from({length:7},(_,i)=>({id:'text'+i,parent:'columns',kind:'text',text:'Paragrafo '+i+'\n'+('Una spiegazione che rimane leggibile e mantiene gli accapi. '.repeat(5)),style:{font_size:26,padding:22,surface:i%2?'soft':'none',radius:20}})),
  {id:'code',parent:'root',kind:'code',language:'python',text:'def esempio(x):\n    return x + 1',style:{font_size:22,padding:24,surface:'dark',radius:16}},
]}};
const project={id:'test',title:'V2 test',theme:'paper',font:'Arial',canvas_mode:'adaptive',engine:'v2',sources:[],visual_assets:[],slides:[{id:'s',revision:1,status:'ready',content}]};

test('V2 retains an overfull nested page and reports the bounded height honestly',async()=>{
  const browser=await chromium.launch({headless:true});try{
    const page=await browser.newPage();
    await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(project,project.slides[0],0));
    const report=await page.locator('.slide-frame').evaluate(fitSlide);
    assert.equal(report.overflow,true);assert.equal(report.height,828);assert(report.neededHeight>report.maxHeight);
    assert.equal(await page.locator('.v2-node').count(),10);
    assert.equal(await page.locator('[data-page-node="code"] .v2-text').innerText(),'def esempio(x):\n    return x + 1');
    const sizes=await page.locator('#nothing').count();assert.equal(sizes,0);
    const safe=structuredClone(project.slides[0]);safe.content.page.nodes[2].text='<script>alert(1)</script>';
    await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(project,safe,0));
    assert.equal(await page.locator('script').count(),0);
    assert.match(await page.locator('[data-page-node="text0"]').innerText(),/<script>/);
  }finally{await browser.close()}
});

test('V2 drag order retains a valid tree',()=>{
  const page=structuredClone(content.page);movePageNode(page,'text0','code');
  assert.equal(page.nodes.find(n=>n.id==='text0').parent,'root');
  assert.equal(page.nodes.at(-2).id,'text0');
  assert.throws(()=>movePageNode(structuredClone(content.page),'columns','text1'),/sé stesso/);
});

test('V2 diagram failures stay empty and readable without blocking later pages',async()=>{
  const p=structuredClone(project),slide=p.slides[0];p.use_manim_diagrams=true;
  slide.content.page.nodes=[{id:'chart',parent:'root',kind:'diagram',asset_id:'',text:'Diagramma richiesto',style:{}}];
  const error='<em>Composizione incompleta</em> & dettagli';
  slide.page_diagrams={chart:{status:'failed',error}};
  const next={...structuredClone(slide),id:'next',content:{...structuredClone(slide.content),page:{style:{},nodes:[{id:'next-text',parent:'root',kind:'text',text:'La slide successiva è pronta',style:{}}]}}};
  const browser=await chromium.launch({headless:true});try{
    const page=await browser.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(p,slide,0)+slideHTML(p,next,1));
    const placeholder=page.locator('[data-page-node="chart"] .v2-placeholder');
    assert.match(await placeholder.innerText(),/Diagramma non disponibile/);
    assert.match(await placeholder.innerText(),/Riprogetta per riprovare/);
    assert((await placeholder.innerText()).includes(error));
    assert.equal(await placeholder.locator('em,script,img').count(),0,'Error detail is escaped; no replacement image or generated HTML');
    assert.equal(await page.locator('[data-page-text="next-text"]').textContent(),'La slide successiva è pronta');
    delete slide.page_diagrams;
    await page.setContent(slideHTML(p,slide,0));
    assert.equal(await placeholder.innerText(),'Diagramma da creare');
    slide.status='generating';await page.setContent(slideHTML(p,slide,0));
    assert.equal(await placeholder.innerText(),'Diagramma Manim in preparazione');
    slide.page_diagrams={chart:{status:'disabled'}};await page.setContent(slideHTML(p,slide,0));
    assert.equal(await placeholder.innerText(),'Diagrammi Manim disattivati');
    delete slide.page_diagrams;p.use_manim_diagrams=false;await page.setContent(slideHTML(p,slide,0));
    assert.equal(await placeholder.innerText(),'Diagrammi Manim disattivati');
    assert.deepEqual(errors,[]);
  }finally{await browser.close()}
});

test('V2 expands a narrow visual instead of reducing it to a thumbnail',async()=>{
  const p=structuredClone(project),id='manim-'+'b'.repeat(64)+'.png';
  p.slides[0].content.page.nodes=[{id:'columns',parent:'root',kind:'group',style:{flow:'columns',columns:[1,1,1,1,1,1]}},
    {id:'chart',parent:'columns',kind:'diagram',asset_id:id,style:{}}];
  const browser=await chromium.launch({headless:true});try{
    const page=await browser.newPage();
    const svg='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700"></svg>');
    await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(p,p.slides[0],0,{assets:{[id]:svg}}));
    await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
    const report=await page.locator('.slide-frame').evaluate(fitSlide);
    assert.equal(report.overflow,false);
    assert((await page.locator('.v2-media').boundingBox()).width>=600);
  }finally{await browser.close()}
});

test('V2 PDF and editable native PowerPoint export',async()=>{
  const dir=await fs.mkdtemp(path.resolve('logs/qa-page-v2-'));
  const square={...project,slide_format:'1:1'};
  const pdf=await buildExports(square,dir,dir,'pdf');
  assert((await fs.stat(pdf)).size>1000);
  const pptx=await buildExports(square,dir,dir,'pptx');
  const zip=await JSZip.loadAsync(await fs.readFile(pptx));
  const xml=await zip.file('ppt/slides/slide1.xml').async('string');
  for(let i=0;i<7;i++)assert.match(xml,new RegExp('Paragrafo '+i));
  assert.match(xml,/def esempio/);assert.match(xml,/Consolas/);
});
