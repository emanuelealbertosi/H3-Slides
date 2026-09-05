import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,layouts,layoutCandidates,fitSlide,visualAnchorAt,visualFor} from '../static/deck.mjs';
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
  const visual={...p,use_manim_diagrams:true};
  const content=make('visual-left');content.diagram={kind:'manim',labels:[],brief:'',scene:{}};
  assert.equal(layoutCandidates(visual,content,0,true)[0],'visual-left');
  content.layout='visual-top';
  assert.equal(layoutCandidates(visual,content,0,true)[0],'visual-top');
  content.layout='visual-bottom';content.layout_locked=true;
  assert.deepEqual(layoutCandidates(visual,content,0,true),['visual-bottom']);
});

test('invisible visual anchors cover compact, wide, top and bottom placements',()=>{
  assert.equal(visualAnchorAt(500,20,1000,600),'visual-top');
  assert.equal(visualAnchorAt(500,590,1000,600),'visual-bottom');
  assert.equal(visualAnchorAt(50,300,1000,600),'visual-left-wide');
  assert.equal(visualAnchorAt(300,300,1000,600),'visual-left');
  assert.equal(visualAnchorAt(700,300,1000,600),'visual-right');
  assert.equal(visualAnchorAt(950,300,1000,600),'visual-right-wide');
});

test('heading placement is persisted as renderer classes',()=>{
  const content=make('editorial');content.heading_position='bottom';content.heading_align='right';
  const html=slideHTML({title:'Test',theme:'paper'},{content},0);
  assert.match(html,/heading-bottom heading-align-right/);
});

test('diagram and photo visibility are independent, including placeholders and legacy URLs',()=>{
  const content={...make('content'),image_id:'photo.jpg',diagram:{kind:'manim',scene:{}}};
  const slide={content,diagram_render:{engine:'manim',asset:'manim-test.png'}};
  const project={title:'Due media',theme:'paper',use_manim_diagrams:true,use_source_images:true};
  const visual=visualFor(project,content,slide);
  assert.equal(visual.image,'manim-test.png');assert.equal(visual.photo,'photo.jpg');
  assert.equal(visual.diagramAsset,'manim-test.png');
  const html=slideHTML(project,slide,0,{diagram:'diagram.png',image:'photo.jpg'});
  assert.match(html,/data-visual-kind="diagram"/);assert.match(html,/data-visual-kind="image"/);
  assert.match(html,/data-free-key="image"/);assert.match(html,/has-multiple-visuals/);
  assert.equal(visualFor({...project,use_source_images:false},content,slide).photo,'');
  assert.equal(visualFor({...project,use_manim_diagrams:false},content,slide).photo,'photo.jpg');
  assert.equal(visualFor({...project,use_manim_diagrams:false},content,slide).diagramAsset,'');
  const hiddenDiagram={...slide,content:{...content,layout:'freeform',freeform:{visual:{x:48,y:200,w:500,h:220},image:{x:700,y:200,w:500,h:220}}}};
  const photoOnly=slideHTML({...project,use_manim_diagrams:false},hiddenDiagram,0,{image:'photo.jpg'});
  assert.match(photoOnly,/data-visual-kind="image" data-free-key="image"/,'Hiding a diagram keeps the independent photo key');
  const web={...content,image_origin:'web'};
  assert.equal(visualFor({...project,use_source_images:false,use_web_images:true},web,slide).photo,'photo.jpg');
  assert.equal(visualFor({...project,use_web_images:false},web,slide).photo,'photo.jpg','The web search option does not hide saved photos');
  assert.equal(visualFor({...project,use_source_images:false,use_web_images:false},{...content,image_origin:'upload'},slide).photo,'photo.jpg');
  const pending={...slide,content:{...content,image_id:'',image_placeholder:true}};
  assert.match(slideHTML(project,pending,0,{diagram:'diagram.png'}),/image-placeholder/);
  assert.equal(visualFor(project,pending.content,pending).photoPlaceholder,true);
  assert.match(slideHTML(project,slide,0,'legacy.png'),/src="legacy.png"/);
  assert.equal(content.image_id,'photo.jpg');
});

test('two media fit without overlaps and preserve independent freeform rectangles',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    const data='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XMG8WQAAAABJRU5ErkJggg==';
    const project={title:'Due media',theme:'paper',use_manim_diagrams:true,use_source_images:true};
    const slides=['content','visual-left','visual-right','visual-top','visual-bottom','cover','cards','freeform'].map(layout=>({
      content:{...make(layout),image_id:'photo.jpg',diagram:{kind:'manim',scene:{}}},
      diagram_render:{engine:'manim',asset:'manim-test.png'}}));
    const free=slides.at(-1).content;free.freeform={visual:{x:710,y:200,w:500,h:240},image:{x:710,y:465,w:500,h:185}};
    await page.setContent('<style>'+slideCSS+'body{margin:0}</style>'+slides.map((s,i)=>slideHTML(project,s,i,{diagram:data,image:data})).join(''));
    const measured=await measureLayouts(page);
    assert.ok(measured.every(m=>!m.overflow),JSON.stringify(measured.map(m=>({layout:m.layout,overflow:m.overflow}))));
    assert.ok(measured.every(m=>m.visuals.length===2));
    const collisions=await page.locator('.slide-frame').evaluateAll(frames=>frames.flatMap((frame,index)=>{
      const nodes=[...frame.querySelectorAll('.heading,.prose-box,.visual')];
      return nodes.flatMap((a,i)=>nodes.slice(i+1).flatMap(b=>{
        const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();
        return Math.min(x.right,y.right)-Math.max(x.left,y.left)>1&&Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top)>1?
          [{index,a:a.className,b:b.className}]:[];
      }));
    }));
    assert.deepEqual(collisions,[]);
    const rectangles=await page.locator('.slide-frame').last().locator('.visual').evaluateAll(nodes=>nodes.map(e=>({
      key:e.dataset.freeKey,x:e.offsetLeft,y:e.offsetTop,w:e.offsetWidth,h:e.offsetHeight})));
    assert.deepEqual(rectangles,[{key:'visual',...free.freeform.visual},{key:'image',...free.freeform.image}]);
    for(const frame of await page.locator('.slide-frame').all())assert.ok(Number.parseFloat(await frame.locator('.prose-box p').first().evaluate(e=>getComputedStyle(e).fontSize))>=20);
  }finally{await browser.close()}
});

test('adding either media to a legacy freeform slot keeps both inside its column',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    const project={title:'Colonna libera',theme:'paper',use_manim_diagrams:true,use_source_images:true};
    const original={x:449,y:200,w:381,h:450};
    const slides=['visual','image'].map(key=>({content:{...make('freeform'),image_id:'photo.jpg',diagram:{kind:'manim',scene:{}},
      freeform:{'block-0':{x:48,y:200,w:381,h:450},'block-1':{x:850,y:200,w:381,h:450},[key]:original}},
      diagram_render:{engine:'manim',asset:'manim-test.png'}}));
    const unchanged=JSON.stringify(slides),pixel='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
    await page.setContent('<style>'+slideCSS+'body{margin:0}</style>'+slides.map((slide,index)=>slideHTML(project,slide,index,{diagram:pixel,image:pixel})).join(''));
    const measured=await measureLayouts(page);assert.ok(measured.every(layout=>!layout.overflow));
    const geometries=await page.locator('.slide-frame').evaluateAll(frames=>frames.map(frame=>[...frame.querySelectorAll('.visual')].map(element=>({
      x:element.offsetLeft,y:element.offsetTop,w:element.offsetWidth,h:element.offsetHeight}))));
    for(const [diagram,image] of geometries){
      assert.equal(diagram.x,original.x);assert.equal(diagram.y,original.y);assert.equal(diagram.w,original.w);
      assert.equal(image.x,original.x);assert.equal(image.w,original.w);
      assert.ok(diagram.y+diagram.h<image.y);assert.equal(image.y+image.h,original.y+original.h);
    }
    assert.equal(JSON.stringify(slides),unchanged,'Rendering must not rewrite the saved legacy coordinates');
  }finally{await browser.close()}
});

test('all compositions fit and native exports use the same measured layouts',async()=>{
  const browser=await chromium.launch();
  const manimAsset='manim-'+'0'.repeat(64)+'.png';
  const data='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XMG8WQAAAABJRU5ErkJggg==';
  const project={title:'Verifica composer',theme:'paper',font:'Segoe UI',template:'auto',text_density:'detailed',use_manim_diagrams:true,slides:[]};
  for(const layout of Object.keys(layouts)){
    const c=make(layout,layout==='cover'?1:layout==='cards'||layout==='timeline'?3:2);
    const slide={content:c};
    if(layout.startsWith('visual-')||layout==='freeform'){
      c.diagram={kind:'manim',labels:[],brief:'Sorgente e risultato',scene:{}};
      slide.diagram_render={engine:'manim',asset:manimAsset};
    }
    project.slides.push(slide);
  }
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    await page.setContent('<!doctype html><style>'+slideCSS+'body{margin:0}</style>'+
      project.slides.map((s,i)=>slideHTML(project,s,i,s.diagram_render?.asset?data:'')).join(''));
    await page.evaluate(()=>document.fonts.ready);
    const measured=await measureLayouts(page);
    assert.deepEqual(measured.map(m=>m.layout),Object.keys(layouts));
    assert.ok(measured.every(m=>!m.overflow));
    const freeFrame=page.locator('.slide-frame').nth(Object.keys(layouts).indexOf('freeform'));
    const freeOrder=await freeFrame.locator('[data-free-key="block-0"],[data-free-key="visual"],[data-free-key="block-1"]')
      .evaluateAll(elements=>Object.fromEntries(elements.map(element=>[element.dataset.freeKey,element.getBoundingClientRect().x])));
    assert.ok(freeOrder['block-0']<freeOrder.visual&&freeOrder.visual<freeOrder['block-1'],
      'The freeform default with two texts and one diagram must be left-center-right');
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
