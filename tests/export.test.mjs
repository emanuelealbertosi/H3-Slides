import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {slideHTML,themeFor,blockColors,autoText,contrast,slideCSS,mathHTML} from '../static/deck.mjs';
import {diagramGeometry,diagramSVG} from '../static/diagram.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
test('slide renderer escapes source text and HTML',()=>{
  const html=slideHTML({title:'Project',theme:'ink'},{content:{layout:'content',title:'<script>alert(1)</script>',subtitle:'',bullets:['<img onerror=x>']}},0);
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
});
test('mathematical formulas render with KaTeX, preserve source and export to PowerPoint',async()=>{
  const formula='La funzione \\(f(x)=1/x\\) non è definita per \\(x=0\\).';
  const html=slideHTML({title:'Analisi',theme:'paper'},{content:{
    layout:'content',title:'y=1/x',subtitle:'',bullets:[formula]}},0);
  assert.ok(html.includes('class="katex"'));
  assert.ok(html.includes('data-edit-raw="La funzione'));
  assert.ok(!html.includes('<script>'));
  assert.ok(mathHTML('\\[x^2+1\\]').includes('katex-display'));
  const {buildExports}=await import('../scripts/export.mjs');
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-math-'));
  const project={title:'Analisi',theme:'paper',slides:[{content:{
    layout:'content',title:'y=1/x',subtitle:'',bullets:[formula],blocks:[],sources:[]}}]};
  const output=await buildExports(project,out,out,'pptx');
  assert.ok((await fs.stat(output)).size>500);
});
test('visual toggles apply to old slides without losing references',()=>{
  const content={layout:'content',title:'Title',subtitle:'',bullets:['A'],image_id:'abc.jpg',diagram:{kind:'flow',labels:['A','B']}};
  const project={title:'Project',theme:'paper',use_source_images:false};
  assert.ok(!slideHTML(project,{content},0,'private.jpg').includes('<img'));
  const html=slideHTML({...project,use_manim_diagrams:true,background_color:'#123456',font:'Georgia'},
    {content:{...content,diagram:{kind:'manim',labels:[],brief:'A verso B',scene:{}}},
     diagram_render:{engine:'manim',asset:'manim-test.png'}},0,'manim-test.png');
  assert.ok(html.includes('<img'));
  assert.ok(html.includes('diagram-render'));
  assert.ok(html.includes('--bg:#123456'));
  assert.ok(html.includes('--font:Georgia'));
  assert.ok(!html.includes('<svg'));
});
test('all diagram presets stay inside the canvas and escape labels',()=>{
  for(const kind of ['flow','cycle','comparison'])for(const count of [2,3,4,5]){
    const g=diagramGeometry({kind,labels:Array(count).fill('<script>')});
    for(const n of g.nodes){assert.ok(n.x-n.w/2>=0);assert.ok(n.x+n.w/2<=560);assert.ok(n.y-n.h/2>=0);assert.ok(n.y+n.h/2<=400)}
    assert.ok(!diagramSVG({kind,labels:['<script>','&']}).includes('<script>'));
  }
});

test('detailed text beside a diagram fits the exported PDF',async()=>{
  process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));
  const {buildExports}=await import('../scripts/export.mjs');
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-slides-layout-'));
  const project={title:'Prova solo argomento',theme:'paper',font:'Segoe UI',
    template:'auto',text_density:'detailed',use_manim_diagrams:true,slides:[{content:{
      title:'Una spiegazione con un diagramma',
      subtitle:'Quattro punti approfonditi affiancati da un confronto visuale.',
      layout:'content',bullets:Array(4).fill('Una spiegazione sufficientemente articolata descrive relazioni e conseguenze, mantenendo il testo leggibile nella slide.'),
      sources:[],image_id:'',diagram:{kind:'comparison',labels:['Prima','Dopo']}
    }}]};
  const output=await buildExports(project,out,out,'pdf');
  assert.ok((await fs.stat(output)).size>500);
});

test('prose boxes are escaped, coloured, and export as editable text',async()=>{
  process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));
  const {buildExports}=await import('../scripts/export.mjs');
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-prose-'));
  const prose=('Una spiegazione completa collega il concetto alle sue cause e alle conseguenze. '+
    'Un esempio concreto permette al lettore di capire il ragionamento e applicarlo a una nuova situazione. ');
  for(const visual of [false,true])for(const density of ['detailed','complete']){
    const length=visual?(density==='complete'?480:370):(density==='complete'?800:650);
    const project={title:'Prova paragrafi',theme:'ink',font:'Segoe UI',template:'auto',
      text_density:density,use_manim_diagrams:visual,slides:[{content:{
        title:'Due paragrafi spiegano davvero il concetto',subtitle:'Definizioni, relazioni ed esempi rimangono visibili nella presentazione.',
        layout:'content',bullets:[],notes:'Note',sources:[],image_id:'',
        blocks:[{heading:'La spiegazione completa',text:prose.repeat(8).slice(0,length),kind:'explanation',source:''},
          {heading:'Un esempio da ricordare',text:prose.repeat(8).slice(0,length),kind:'example',source:''}],
        diagram:{kind:'flow',labels:['Prima','Dopo']}
      }}]};
    const html=slideHTML(project,project.slides[0],0);
    assert.ok(html.includes('prose-box'));
    assert.ok(html.includes('kind-example'));
    assert.ok(!html.includes('<ul>'));
    for(const format of ['pdf','pptx']){
      const output=await buildExports(project,out,path.join(out,String(visual)+density+format),format);
      assert.ok((await fs.stat(output)).size>500);
    }
    project.slides[0].content.blocks[0].kind='quote';
    project.slides[0].content.blocks[0].source='Informatica con Python.pdf, pagina PDF 22, pagina stampata 2';
    await buildExports(project,out,path.join(out,String(visual)+density+'quote'),'pdf');
  }
  const unsafe={content:{title:'Titolo',subtitle:'',bullets:[],blocks:[{heading:'<script>',text:'<img onerror="x">',kind:'quote',source:'<b>fonte</b>'}]}};
  const html=slideHTML({theme:'paper',title:'Test'},unsafe,0);
  assert.ok(!html.includes('<script>')&&!html.includes('<img'));
  assert.ok(html.includes('&lt;img'));
});

test('oversized prose is reported rather than silently cropped in exports',async()=>{
  const {buildExports}=await import('../scripts/export.mjs');
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-prose-overflow-'));
  const project={title:'Overflow',theme:'paper',text_density:'detailed',slides:[{content:{
    title:'Troppo testo',subtitle:'',bullets:[],sources:[],blocks:[{heading:'Paragrafo',
    text:'Una frase lunga che deve essere conservata senza sparire. '.repeat(100),kind:'explanation',source:''}]}}]};
  for(const format of ['pdf','pptx'])await assert.rejects(()=>buildExports(project,out,out,format),/Testo/);
});

test('automatic text contrast works across backgrounds and per-box fills',()=>{
  for(let r=0;r<=255;r+=17)for(let g=0;g<=255;g+=17)for(let b=0;b<=255;b+=17){
    const bg='#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');
    assert.ok(contrast(bg,autoText(bg))>=4.5,bg);
  }
  const project={theme:'paper',background_color:'#123456',theme_design:{example_color:'#162038',title_color:'#aaddff'}};
  assert.equal(themeFor(project).heading,'#aaddff');
  assert.equal(blockColors(project,{kind:'example'}).fg,'#ffffff');
});

test('every distributed theme renders and exports with its fonts, boxes and borders',async()=>{
  process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));
  const {buildExports}=await import('../scripts/export.mjs');
  const {chromium}=await import('playwright-chromium');
  const presets=JSON.parse(await fs.readFile(new URL('../static/theme-presets.json',import.meta.url),'utf8'));
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-themes-'));
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    for(const preset of presets){
      const project={...preset.values,title:'Tema '+preset.name,text_density:'complete',slides:[{content:{
        title:'Un tema personalizzato per spiegare un concetto con chiarezza',subtitle:'Una gerarchia leggibile tra titolo e paragrafi.',
        bullets:[],sources:[],image_id:'',blocks:['explanation','example'].map(kind=>({kind,heading:'Il concetto',
          text:'Una spiegazione mette in relazione il concetto con un esempio concreto. I colori separano le informazioni senza sostituire il ragionamento.',source:''}))
      }}]};
      project.theme_design={...project.theme_design,body_size:23};
      const html=slideHTML(project,project.slides[0],0);
      await page.setContent('<style>'+slideCSS+'</style>'+html);
      assert.equal(await page.locator('.prose-box p').first().evaluate(e=>getComputedStyle(e).fontSize),'23px');
      assert.equal(await page.locator('.prose-box').first().evaluate(e=>getComputedStyle(e).borderTopWidth),project.theme_design.border_width+'px');
      for(const format of ['pdf','pptx']){
        const output=await buildExports(project,out,path.join(out,preset.name+format),format);
        assert.ok((await fs.stat(output)).size>500);
      }
    }
  }finally{await browser.close()}
});
