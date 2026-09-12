import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// Only synthetic data and an in-memory API. No screenshots or real model/server.
const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const code=Array.from({length:28},(_,i)=>i===10?'x'.repeat(40)+' = 1':'print('+i+')').join('\n');
const original={title:'Schede adattive',subtitle:'',layout:'freeform',layout_locked:true,
  canvas_height:936,freeform_base:'cards',freeform_compact:true,image_id:'photo.png',image_origin:'source',
  image_placeholder:false,bullets:[],sources:[],notes:'Note da conservare',diagram:{kind:'none'},
  blocks:[{kind:'code',language:'python',heading:'Esempio Python',text:code,source:''},
    {kind:'explanation',heading:'',text:'Una spiegazione collega i dati e le operazioni attraverso un esempio leggibile e verificabile. '.repeat(4),
      source:'Esempio generato, pagina 12'}],
  freeform:{heading:{x:48,y:53,w:1184,h:72},'block-0':{x:48,y:139,w:434,h:737},
    'block-1':{x:496,y:139,w:434,h:737},visual:{x:948,y:139,w:284,h:737}}};
let project={id:'resize-editor',title:'Ridimensionamento sintetico',prompt:'Nessuna generazione',count:1,
  theme:'paper',font:'Arial',canvas_mode:'adaptive',graphic_style:'studio',text_density:'detailed',
  sources:[{id:'document',name:'Documento sintetico',warnings:[],images:[{id:'photo.png',label:'Immagine sintetica'}]}],visual_assets:[],
  use_manim_diagrams:false,use_source_images:true,use_web_images:false,web_enabled:false,revision:1,
  slides:[{id:'slide',revision:1,status:'ready',content:structuredClone(original)}]};
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#bddbd3"/></svg>';
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1500,height:1200}});
page.setDefaultTimeout(15000);
const patches=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('dialog',dialog=>dialog.accept());
const card=page.locator('#slide-slide'),frame=card.locator('.slide-frame');
const ready=async()=>{
  await frame.waitFor();
  await page.waitForFunction(()=>document.querySelector('#slide-slide .slide-frame')?.dataset.overflow==='false');
  await frame.evaluate(async element=>{await document.fonts.ready;await Promise.all([...element.querySelectorAll('img')].map(img=>img.decode()))});
};
const geometry=()=>frame.evaluate(element=>({height:element.offsetHeight,overflow:element.dataset.overflow,
  placements:Object.fromEntries([...element.querySelectorAll('[data-free-key]')].map(item=>[item.dataset.freeKey,
    Object.fromEntries(['x','y','w','h'].map(key=>[key,Number(item.dataset['free'+key.toUpperCase()])]))])),
  text:[...element.querySelectorAll('[data-edit-field="block-text"]')].map(item=>item.textContent),
  fonts:[...element.querySelectorAll('h1,h2,p')].map(item=>getComputedStyle(item).fontSize),
  code:[...element.querySelectorAll('.kind-code p')].map(item=>({width:item.clientWidth,scroll:item.scrollWidth})),
}));
const valid=async(reference=original)=>{
  const result=await geometry();assert.equal(result.overflow,'false');assert.equal(result.height,936,'Shrinking does not grow the canvas');
  assert.deepEqual(result.text,reference.blocks.map(block=>block.text));
  assert.ok(result.code.every(item=>item.scroll<=item.width+2),'Code never clips or acquires a scrollbar');
  const boxes=Object.values(result.placements);
  for(let i=0;i<boxes.length;i++){
    const a=boxes[i];assert.ok(a.x>=0&&a.y>=0&&a.x+a.w<=1280&&a.y+a.h<=896);
    for(let j=i+1;j<boxes.length;j++){
      const b=boxes[j];assert.ok(Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)<=1||
        Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)<=1,'Elements must not overlap');
    }
  }
  return result;
};
const selectBlock=async key=>{
  await frame.locator('[data-free-key="'+key+'"]').click({position:{x:4,y:4}});
  const visible=card.locator('[data-free-resize]:visible');
  assert.equal(await visible.count(),8,'Only the selected block exposes eight handles');
  assert.deepEqual((await visible.evaluateAll(items=>items.map(item=>item.dataset.resizeEdge))).sort(),
    ['n','ne','e','se','s','sw','w','nw'].sort());
  assert.ok((await visible.evaluateAll(items=>items.map(item=>item.dataset.freeResize))).every(value=>value===key));
};
const beginResize=async(key,target,edge='se')=>{
  await selectBlock(key);
  const handle=card.locator('[data-free-resize="'+key+'"][data-resize-edge="'+edge+'"]');
  await handle.scrollIntoViewIfNeeded();
  const hit=await handle.boundingBox(),bounds=await frame.boundingBox(),scale=bounds.width/1280;
  const start=(await geometry()).placements[key];
  assert.ok(hit,'Resize handle exists');
  await page.keyboard.down('Alt'); // exact one-pixel target, independent of the user's grid preference
  // Side grips work along the transparent border, not only on their tiny mark.
  const hitX=hit.x+hit.width*(edge==='n'||edge==='s'?.25:.5);
  const hitY=hit.y+hit.height*(edge==='w'||edge==='e'?.25:.5);
  await page.mouse.move(hitX,hitY);await page.mouse.down();
  const dx=edge.includes('w')?target.x-start.x:edge.includes('e')?target.x+target.w-start.x-start.w:0;
  const dy=edge.includes('n')?target.y-start.y:edge.includes('s')?target.y+target.h-start.y-start.h:0;
  const endpoint={x:hitX+dx*scale,y:hitY+dy*scale};
  await page.mouse.move(endpoint.x,endpoint.y,{steps:8});
  return endpoint;
};
const commitResize=async(expected,prefix,reference=original)=>{
  const count=patches.length;
  const response=page.waitForResponse(response=>response.request().method()==='PATCH'&&
    new URL(response.url()).pathname==='/api/projects/resize-editor/slides/slide');
  await page.mouse.up();await page.keyboard.up('Alt');await response;
  await page.waitForFunction(prefix=>document.querySelector('#toast').textContent.startsWith(prefix),prefix);
  assert.equal(patches.length,count+1,'Drop produces exactly one geometry save');
  assert.deepEqual(project.slides[0].content.freeform,expected.placements,'Saved geometry equals the live preview');
  assert.equal(project.slides[0].content.canvas_height,936);
  assert.deepEqual(project.slides[0].content.blocks,reference.blocks);
  assert.equal(project.slides[0].content.image_id,reference.image_id);
  assert.equal(project.slides[0].content.notes,reference.notes);
  await page.reload();await ready();
  const reloaded=await valid(reference);assert.deepEqual(reloaded.placements,expected.placements,'Reload must not restore the old size');
  assert.deepEqual(reloaded.fonts,expected.fonts,'Resize does not shrink typography');return reloaded;
};
try{
  await page.addInitScript(()=>{
    window.__resizeHandlerDurations=[];let started=null;
    document.addEventListener('pointermove',event=>{started=event.buttons&1?performance.now():null},true);
    document.addEventListener('pointermove',()=>{
      if(started!==null)window.__resizeHandlerDurations.push(performance.now()-started);
    });
  });
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    try{
      assert.equal(url.origin,origin,'No external requests');
      if(url.pathname==='/api/assets/resize-editor/photo.png')return route.fulfill({body:svg,contentType:'image/svg+xml'});
      if(url.pathname.startsWith('/api/')){
        if(url.pathname==='/api/projects/resize-editor/slides/slide'&&method==='PATCH'){
          const payload=route.request().postDataJSON();patches.push(structuredClone(payload));
          assert.equal(payload.revision,project.slides[0].revision);
          project.slides[0]={...project.slides[0],content:payload.content,revision:payload.revision+1};
          return route.fulfill({json:project.slides[0]});
        }
        assert.equal(method,'GET','No generation or unexpected mutation');
        const model={id:'mock',name:'Simulato',vision:true};
        const responses={'/api/projects':[{...project,slide_count:1}],'/api/projects/resize-editor':project,'/api/jobs':[],
          '/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},
          '/api/models':{models:[model],default_model:'mock',runtime_available:true,status:{running:false}},
          '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
          '/api/admin/llm':{models:[model],profiles:{},status:{running:false},loading_schema:{properties:{}},inference_schema:{properties:{}}}};
        assert.ok(Object.hasOwn(responses,url.pathname),url.pathname);return route.fulfill({json:responses[url.pathname]});
      }
      const file=resolve(root,['/','/create','/editor'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));
      assert.ok(file.startsWith(root.endsWith(sep)?root:root+sep));
      try{return route.fulfill({body:await readFile(file),contentType:({'.mjs':'text/javascript','.css':'text/css','.html':'text/html',
        '.json':'application/json','.woff2':'font/woff2','.woff':'font/woff'})[extname(file)]||'application/octet-stream'})}
      catch{return route.fulfill({status:404,body:''})}
    }catch(error){errors.push(error.message);return route.fulfill({status:500,json:{error:error.message}})}
  });
  await page.goto(origin+'/editor?project=resize-editor');await ready();
  const initial=await valid();
  assert.equal(await card.locator('[data-free-resize]:visible').count(),0,'No handles before selecting a block');
  assert.equal(initial.placements['block-1'].h,737,'The explanation begins with removable empty height');
  assert.ok(initial.placements['block-0'].w>434&&initial.placements['block-0'].w<=448,
    'The pre-existing small code overflow is repaired without a large layout change');
  assert.deepEqual(patches,[],'Opening a project does not silently write corrected geometry');
  const target={...initial.placements['block-1'],h:537};
  await beginResize('block-1',target);
  const live=await valid();
  assert.deepEqual(live.placements['block-1'],target,'The explanation gets shorter before releasing the mouse');
  assert.deepEqual(live.fonts,initial.fonts);
  const indicator=card.locator('.anchor-indicator');
  assert.equal(await indicator.isVisible(),true);
  assert.match(await indicator.textContent(),/rilascio per salvare/);
  assert.doesNotMatch(await indicator.textContent(),/annulla|minimo/);
  const firstTimings=await page.evaluate(()=>window.__resizeHandlerDurations);
  const first=await commitResize(live,'Disposizione salvata');
  for(const key of ['heading','block-0','visual'])assert.deepEqual(first.placements[key],initial.placements[key]);
  // A too-small request is visibly clamped to the real content height, not reset.
  const tooSmall={...first.placements['block-1'],h:100};
  await beginResize('block-1',tooSmall);
  const clamped=await valid();
  assert.ok(clamped.placements['block-1'].h>100&&clamped.placements['block-1'].h<537);
  assert.match(await indicator.textContent(),/minimo per il contenuto/);
  assert.match(await indicator.textContent(),/rilascio per salvare/);
  assert.doesNotMatch(await indicator.textContent(),/annulla/);
  const timings=[...firstTimings,...await page.evaluate(()=>window.__resizeHandlerDurations)];
  const second=await commitResize(clamped,'Dimensioni salvate al minimo');
  assert.ok(second.placements['block-1'].h<first.placements['block-1'].h);
  // Large neighbouring columns prevent the requested width. Keep the closest
  // usable enlargement instead of resetting the gesture to its starting size.
  project.slides[0].content=structuredClone(original);
  Object.assign(project.slides[0].content.freeform['block-1'],{w:400,h:537});
  project.slides[0].revision++;
  await page.reload();await ready();
  const beforeLimit=await valid(),requestedWide={...beforeLimit.placements['block-1'],w:760};
  assert.equal(beforeLimit.placements['block-1'].w,400);
  await beginResize('block-1',requestedWide);
  const limited=await valid(),effective=limited.placements['block-1'];
  assert.ok(effective.w>400&&effective.w<760,'Impossible resize keeps a valid intermediate width, not the original 400px');
  assert.equal(effective.x,requestedWide.x);assert.equal(effective.y,requestedWide.y);
  assert.equal(effective.h,requestedWide.h);
  assert.match(await indicator.textContent(),/rilascio per salvare/);
  assert.match(await indicator.textContent(),/limite dello spazio disponibile/);
  assert.doesNotMatch(await indicator.textContent(),/annulla/);
  timings.push(...await page.evaluate(()=>window.__resizeHandlerDurations));
  console.log('Geometric resize clamp: '+JSON.stringify({originalWidth:400,requestedWidth:760,effectiveWidth:effective.w}));
  await commitResize(limited,'Dimensioni salvate');
  // Every side and corner is interactive; north/west preserve the opposite edge.
  const simple={...structuredClone(original),image_id:'',freeform_base:'editorial',freeform_compact:false,
    blocks:[{kind:'explanation',heading:'Un box',text:'Contenuto breve da conservare.',source:''}],
    freeform:{heading:{x:48,y:53,w:1184,h:72},'block-0':{x:400,y:280,w:400,h:300}}};
  for(const edge of ['n','ne','e','se','s','sw','w','nw']){
    project.slides[0].content=structuredClone(simple);project.slides[0].revision++;
    await page.reload();await ready();
    const baseline=await valid(simple),start=baseline.placements['block-0'];
    await selectBlock('block-0');
    const sizes=await card.locator('[data-free-resize]:visible').evaluateAll(items=>items.map(item=>{
      const marker=getComputedStyle(item,'::after'),scale=item.closest('.slide-frame').getBoundingClientRect().width/1280;
      return {w:parseFloat(marker.width)*scale,h:parseFloat(marker.height)*scale,
        content:marker.content,background:getComputedStyle(item).backgroundColor};
    }));
    assert.ok(sizes.every(size=>size.content!=='none'&&size.w>0&&size.h>0&&size.w<=12.5&&size.h<=12.5),
      'Visible resize marks stay small; generous hit targets are separate');
    assert.ok(sizes.every(size=>size.background==='rgba(0, 0, 0, 0)'),'Side hit strips are transparent');
    const empty=await frame.boundingBox();await page.mouse.click(empty.x+5,empty.y+5);
    assert.equal(await card.locator('[data-free-resize]:visible').count(),0,'Clicking outside hides handles');
    const target={x:start.x-(edge.includes('w')?40:0),y:start.y-(edge.includes('n')?40:0),
      w:start.w+(/[ew]/.test(edge)?40:0),h:start.h+(/[ns]/.test(edge)?40:0)};
    await beginResize('block-0',target,edge);
    const preview=await valid(simple),actual=preview.placements['block-0'];
    assert.deepEqual(actual,target,edge+' handle changes the intended edges only');
    if(edge.includes('w'))assert.equal(actual.x+actual.w,start.x+start.w,'West keeps the east edge fixed');
    if(edge.includes('n'))assert.equal(actual.y+actual.h,start.y+start.h,'North keeps the south edge fixed');
    await commitResize(preview,'Disposizione salvata',simple);
  }
  // A valid clamped resize still belongs to its original card when the mouse
  // is released outside the canvas. Do not silently cancel the enlargement.
  project.slides[0].content=structuredClone(simple);project.slides[0].revision++;
  await page.reload();await ready();
  const beforeOutside=await valid(simple),westStart=beforeOutside.placements['block-0'];
  const beforeOutsideBounds=await frame.boundingBox(),outsideScale=beforeOutsideBounds.width/1280;
  const outsideTargetX=-Math.min(40,Math.max(1,(beforeOutsideBounds.x-2)/outsideScale));
  const outside=await beginResize('block-0',{...westStart,x:outsideTargetX,w:westStart.x+westStart.w-outsideTargetX},'w');
  const outsideBounds=await frame.boundingBox();
  assert.ok(outside.x>=0&&outside.y>=0&&outside.x<1500&&outside.y<1200,
    'Release stays in the browser viewport: '+JSON.stringify({outside,bounds:outsideBounds}));
  assert.ok(outside.x<outsideBounds.x,'The pointer is outside the canvas');
  assert.equal(await page.evaluate(point=>Boolean(document.elementFromPoint(point.x,point.y)?.closest('#slide-slide')),outside),false,
    'The drop target is outside the original card, exercising resize ownership rather than hit testing');
  const outsidePreview=await valid(simple),outsideBox=outsidePreview.placements['block-0'];
  assert.equal(outsideBox.x,0);assert.equal(outsideBox.w,westStart.x+westStart.w);
  assert.equal(outsideBox.y,westStart.y);assert.equal(outsideBox.h,westStart.h);
  assert.ok(outsideBox.w>westStart.w,'The usable enlargement is preserved at the left canvas boundary');
  await commitResize(outsidePreview,'Disposizione salvata',simple);
  // Escape cancels an active gesture locally, without sending a geometry PATCH
  // or leaving selected handles visible after the captured pointer is released.
  project.slides[0].content=structuredClone(simple);project.slides[0].revision++;
  await page.reload();await ready();
  const beforeEscape=await valid(simple),storedBeforeEscape=structuredClone(project.slides[0]),patchesBeforeEscape=patches.length;
  await beginResize('block-0',{...beforeEscape.placements['block-0'],w:520,h:380});
  assert.notDeepEqual((await valid(simple)).placements,beforeEscape.placements,'The gesture has a changed live preview');
  await page.keyboard.press('Escape');
  await page.mouse.up();await page.keyboard.up('Alt');
  await page.waitForFunction(()=>!document.querySelector('#slide-slide')?.classList.contains('component-dragging'));
  assert.equal(await card.locator('[data-free-resize]:visible').count(),0,'Escape cancels selection as well as the active resize');
  assert.deepEqual((await valid(simple)).placements,beforeEscape.placements,'Escape restores the original visible geometry');
  assert.equal(patches.length,patchesBeforeEscape,'Cancellation sends no PATCH');
  assert.deepEqual(project.slides[0],storedBeforeEscape,'Cancellation preserves stored content and revision');
  await page.reload();await ready();
  assert.deepEqual((await valid(simple)).placements,beforeEscape.placements);
  assert.equal(patches.length,patchesBeforeEscape,'No delayed save follows the canceled pointerup');
  assert.deepEqual(errors,[]);
  const ordered=[...timings].sort((a,b)=>a-b);
  console.log('Resize pointermove handler timing (indicative, no flaky threshold): '+JSON.stringify({
    samples:timings.length,medianMs:ordered[Math.floor(ordered.length/2)],maxMs:Math.max(...timings)}));
  console.log('Resize editor: narrow-code repair, live shrink, persisted minimum/geometric clamps, eight selected-only handles, anchored north/west resize, release outside canvas and Escape cancellation passed');
}catch(error){
  console.error(JSON.stringify({errors,state:await page.evaluate(()=>({view:document.body.dataset.view,
    toast:document.querySelector('#toast')?.textContent,slides:document.querySelector('#slides')?.childElementCount}))}));
  throw error;
}finally{await page.keyboard.up('Alt').catch(()=>{});await browser.close()}
