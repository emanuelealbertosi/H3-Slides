import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// Real editor interactions against an in-memory API, never user projects or LLMs.
const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const code=n=>Array.from({length:n},(_,i)=>'    print('+i+')').join('\n');
const base={title:'Codice e spiegazione',subtitle:'',layout:'freeform',layout_locked:true,canvas_height:720,
  freeform_base:'editorial',bullets:[],sources:[],notes:'',diagram:{kind:'none'},
  blocks:[{kind:'code',language:'python',heading:'Python',text:code(3),source:''},
    {kind:'explanation',heading:'Spiegazione',text:'Il codice mantiene ogni riga e la sua indentazione.',source:''}],
  freeform:{heading:{x:48,y:60,w:1184,h:100},'block-0':{x:48,y:200,w:1184,h:200},'block-1':{x:48,y:430,w:1184,h:170}}};
let project={id:'adaptive-editor',title:'Test layout',prompt:'Test sintetico',count:1,theme:'paper',font:'Arial',
  canvas_mode:'fixed',graphic_style:'studio',text_density:'detailed',sources:[],visual_assets:[],
  use_manim_diagrams:false,use_source_images:true,use_web_images:false,web_enabled:false,revision:1,
  slides:[{id:'slide',revision:1,status:'ready',content:structuredClone(base)}]};
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1500,height:1200}});
page.setDefaultTimeout(15000);
const patches=[],formatChanges=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('dialog',dialog=>dialog.accept());
const frame=page.locator('#slide-slide .slide-frame');
const ready=async()=>{await frame.waitFor();await page.waitForFunction(()=>document.querySelector('#slide-slide .slide-frame')?.dataset.overflow==='false')};
const geometry=()=>frame.evaluate(element=>({height:element.offsetHeight,
  placements:Object.fromEntries([...element.querySelectorAll('[data-free-key]')].map(e=>[e.dataset.freeKey,
    Object.fromEntries(['x','y','w','h'].map(key=>[key,Number(e.dataset['free'+key.toUpperCase()])]))]))}));
const noOverlap=async()=>{
  const result=await geometry(),objects=Object.values(result.placements);
  for(let i=0;i<objects.length;i++)for(let j=i+1;j<objects.length;j++){
    const a=objects[i],b=objects[j];assert.ok(Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)<=1||
      Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)<=1,'No objects overlap');
  }
  assert.equal(await frame.getAttribute('data-overflow'),'false');return result;
};
const openMenu=async()=>{await page.evaluate(()=>window.scrollTo(0,0));await page.locator('#editor-menu summary').click()};
try{
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    assert.equal(url.origin,origin,'No external requests');
    if(url.pathname.startsWith('/api/')){
      if(url.pathname==='/api/projects/adaptive-editor/slides/slide'&&method==='PATCH'){
        const payload=route.request().postDataJSON();patches.push(structuredClone(payload));
        assert.equal(payload.revision,project.slides[0].revision);
        project.slides[0]={...project.slides[0],content:payload.content,revision:payload.revision+1};
        return route.fulfill({json:project.slides[0]});
      }
      if(url.pathname==='/api/projects/adaptive-editor'&&method==='PATCH'){
        const payload=route.request().postDataJSON();formatChanges.push(structuredClone(payload));
        for(const update of payload.slide_layouts||[]){
          assert.equal(update.revision,project.slides[0].revision);
          Object.assign(project.slides[0].content,{canvas_height:update.canvas_height,freeform:update.freeform});
          project.slides[0].revision++;
        }
        project.canvas_mode=payload.canvas_mode;project.revision++;
        return route.fulfill({json:project});
      }
      assert.equal(method,'GET','No generation or unexpected mutation');
      const model={id:'mock',name:'Simulato',vision:true};
      const responses={'/api/projects':[project],'/api/projects/adaptive-editor':project,'/api/jobs':[],
        '/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},
        '/api/models':{models:[model],default_model:'mock',runtime_available:true,status:{running:false}},
        '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
        '/api/admin/llm':{models:[model],profiles:{},status:{running:false},loading_schema:{properties:{}},inference_schema:{properties:{}}}};
      assert.ok(Object.hasOwn(responses,url.pathname),url.pathname);return route.fulfill({json:responses[url.pathname]});
    }
    const file=resolve(root,['/','/create','/editor'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));
    assert.ok(file.startsWith(root.endsWith(sep)?root:root+sep));
    try{return route.fulfill({body:await readFile(file),contentType:({'.mjs':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.woff2':'font/woff2','.woff':'font/woff'})[extname(file)]||'application/octet-stream'})}
    catch{return route.fulfill({status:404,body:''})}
  });
  await page.goto(origin+'/editor?project=adaptive-editor');await ready();
  await openMenu();await page.locator('#editor-canvas-mode').selectOption('adaptive');
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.startsWith('Formato applicato'));
  assert.equal(project.canvas_mode,'adaptive');assert.equal(formatChanges.length,1);
  assert.deepEqual(project.slides[0].content.blocks,base.blocks);
  await page.locator('#editor-menu summary').click();
  // Enlarge the first box into its neighbour: live layout and committed geometry must match.
  await frame.scrollIntoViewIfNeeded();
  const resizeTarget=frame.locator('[data-free-key="block-0"]');
  await resizeTarget.click({position:{x:16,y:40}});
  assert.equal(await resizeTarget.evaluate(e=>e.classList.contains('is-selected')),true);
  assert.equal(await frame.locator('[data-free-resize="block-0"]:visible').count(),8);
  const before=await geometry(),handle=await frame.locator('[data-free-resize="block-0"][data-resize-edge="se"]').boundingBox();
  assert.ok(handle,'The selected box exposes its southeast resize handle');
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down();
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2+75,{steps:6});
  const during=await noOverlap();assert.notDeepEqual(during.placements['block-1'],before.placements['block-1']);
  const prior=patches.length;await page.mouse.up();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.startsWith('Disposizione salvata'));
  assert.equal(patches.length,prior+1);
  const persisted=structuredClone(project.slides[0].content.freeform);
  assert.deepEqual(persisted,during.placements,'Drop saves all preview positions, including neighbours');
  await page.reload();await ready();assert.deepEqual((await geometry()).placements,persisted);
  // Editing code grows the card before blur, and keeps all lines after reload.
  project.slides[0].content=structuredClone(base);project.slides[0].revision++;
  await page.reload();await ready();
  const text=frame.locator('[data-edit-field="block-text"]').first();
  const initialEdit=await geometry(),beforeCancel=patches.length;
  await text.dblclick();await text.fill(code(20));assert.ok((await geometry()).height>initialEdit.height);
  await text.fill(code(3));assert.deepEqual(await geometry(),initialEdit,'Shortening live text resets the temporary expansion');
  await text.fill(code(20));await text.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('[contenteditable="plaintext-only"]'));
  assert.deepEqual(await geometry(),initialEdit,'Escape restores all positions and height');
  assert.equal(patches.length,beforeCancel,'Cancelled edits do not write');
  await text.dblclick();await text.fill(code(20));
  const live=await noOverlap();assert.ok(live.height>720,'Text edit grows live');
  await text.press('Tab');await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Testo salvato');
  assert.equal(project.slides[0].content.blocks[0].text,code(20));
  const saved=structuredClone(project.slides[0].content);
  await page.reload();await ready();assert.equal((await geometry()).height,saved.canvas_height);
  assert.equal(await text.textContent(),code(20));await noOverlap();
  // Impossible fixed conversion is rejected before any API mutation.
  const changesBefore=formatChanges.length;await openMenu();await page.locator('#editor-canvas-mode').selectOption('fixed');
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('non è stata salvata'));
  assert.equal(formatChanges.length,changesBefore);assert.equal(project.canvas_mode,'adaptive');
  // A shorter slide can return to 16:9 without stale tall freeform metadata.
  project.slides[0].content={...structuredClone(base),canvas_height:936};project.slides[0].revision++;
  await page.reload();await ready();await openMenu();await page.locator('#editor-canvas-mode').selectOption('fixed');
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.startsWith('Formato applicato'));
  assert.equal(project.canvas_mode,'fixed');assert.equal(project.slides[0].content.canvas_height,720);
  assert.equal((await noOverlap()).height,720);assert.deepEqual(errors,[]);
  console.log('Adaptive editor: live resize/reflow, persisted neighbours, inline code growth, reload and atomic format change passed');
}finally{await browser.close()}
