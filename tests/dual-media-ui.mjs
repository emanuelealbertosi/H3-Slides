import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// The complete app is served from intercepted files; every API operation is in memory.
const staticRoot=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const pixels=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XMG8WQAAAABJRU5ErkJggg==','base64');
const diagramAsset='manim-'+'a'.repeat(64)+'.png',photo='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg';
const baseContent={title:'Immagine e diagramma',subtitle:'',layout:'freeform',layout_locked:true,freeform_base:'editorial',
  blocks:[{kind:'explanation',heading:'Spiegazione',text:'Il testo rimane invariato.',source:''}],bullets:[],sources:[],notes:'',
  image_id:photo,image_origin:'source',image_placeholder:false,
  diagram:{kind:'manim',brief:'Diagramma di prova',scene:{}},
  freeform:{heading:{x:48,y:65,w:1184,h:100},'block-0':{x:48,y:200,w:620,h:430},
    visual:{x:700,y:180,w:500,h:240},image:{x:700,y:450,w:500,h:180}}};
const project={id:'dual-ui',title:'Due media',prompt:'Un testo con una foto e un diagramma',count:6,theme:'paper',
  use_manim_diagrams:true,use_source_images:true,use_web_images:false,web_enabled:false,
  sources:[{id:'manual',name:'Manuale.md',kind:'md',images:[{id:photo,label:'Foto dal documento'}],warnings:[]}],visual_assets:[],
  slides:[{id:'dual-slide',revision:1,status:'ready',content:structuredClone(baseContent),diagram_render:{engine:'manim',asset:diagramAsset}}]};
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1600,height:1100}});
page.setDefaultTimeout(10000);
const errors=[],patches=[],generated=[],uploads=[];
const searches=[],selections=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('dialog',dialog=>dialog.accept(dialog.type()==='prompt'?'Rendi leggibili le etichette':undefined));
try{
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    assert.equal(url.origin,origin,'No external requests');
    if(url.pathname.startsWith('/api/assets/'))return route.fulfill({body:pixels,contentType:'image/png'});
    if(url.pathname.startsWith('/api/')){
      if(url.pathname.endsWith('/preview')&&url.pathname.includes('/image-search/'))return route.fulfill({body:pixels,contentType:'image/png'});
      if(url.pathname.endsWith('/image-search')&&method==='POST'){
        const payload=route.request().postDataJSON();searches.push(payload);
        if(payload.source==='document')return route.fulfill({json:{search_id:'doc-session',page:0,has_more:false,
          message:'Manuale.md · immagini del documento',results:[{id:'local-photo',label:'Foto dal documento',
            document:'Manuale.md',kind:'image',source:'Manuale.md',image_provider:'Documento locale',license:'',author:''}]}});
        return route.fulfill({json:{search_id:'session',page:payload.page||0,has_more:!payload.page,
          results:Array.from({length:10},(_,i)=>({id:'result-'+((payload.page||0)*10+i),label:'Odysseus '+i,
            source:'https://commons.wikimedia.org/wiki/File:Test',author:'Artist',license:'CC BY 4.0',image_provider:'Wikimedia Commons'}))}});
      }
      if(url.pathname.endsWith('/image-search/select')&&method==='POST'){
        selections.push(route.request().postDataJSON());
        if(selections.at(-1).search_id==='doc-session'){
          project.slides[0].content={...project.slides[0].content,image_id:photo,image_origin:'source',image_placeholder:false};
          project.slides[0].revision++;project.use_source_images=true;
          return route.fulfill({json:{slide:project.slides[0],source_image:{id:photo,label:'Foto dal documento'},use_source_images:true}});
        }
        const visual_asset={id:'cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee.jpg',origin:'web',label:'Scelta dal web',image_provider:'Wikimedia Commons'};
        project.visual_assets.push(visual_asset);
        project.slides[0].content={...project.slides[0].content,image_id:visual_asset.id,image_origin:'web',image_placeholder:false};
        project.slides[0].revision++;
        return route.fulfill({json:{slide:project.slides[0],visual_asset}});
      }
      if(url.pathname==='/api/projects/dual-ui/slides/dual-slide'&&method==='PATCH'){
        const payload=route.request().postDataJSON();patches.push(structuredClone(payload));
        project.slides[0]={...project.slides[0],content:payload.content,revision:project.slides[0].revision+1};
        if(payload.content.diagram.kind==='none')project.slides[0].diagram_render=null;
        return route.fulfill({json:project.slides[0]});
      }
      if(url.pathname==='/api/projects/dual-ui/slides/dual-slide/image'&&method==='POST'){
        uploads.push(route.request().postDataBuffer());
        const visual_asset={id:'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee.jpg',origin:'upload',label:'Caricata'};
        project.visual_assets.push(visual_asset);
        project.slides[0].content={...project.slides[0].content,image_id:visual_asset.id,image_origin:'upload',image_placeholder:false};
        project.slides[0].revision++;
        return route.fulfill({json:{slide:project.slides[0],visual_asset}});
      }
      if(url.pathname==='/api/projects/dual-ui/generate'&&method==='POST'){
        generated.push(route.request().postDataJSON());
        return route.fulfill({json:{id:'mock-job',project_id:project.id,status:'completed',progress:1,events:[]}});
      }
      if(url.pathname==='/api/projects/dual-ui'&&method==='PATCH'){
        Object.assign(project,route.request().postDataJSON());return route.fulfill({json:project});
      }
      assert.equal(method,'GET','Only explicit mocked mutations are allowed');
      const responses={
        '/api/projects':[{...project,slide_count:1}],'/api/projects/dual-ui':project,'/api/jobs':[],
        '/api/models':{models:[{id:'mock',name:'gemma test',size_gb:1,vision:true}],default_model:'mock',runtime_available:true,status:{running:false}},
        '/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},
        '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
      };
      assert.ok(Object.hasOwn(responses,url.pathname),'Unexpected API '+url.pathname);
      return route.fulfill({json:responses[url.pathname]});
    }
    const file=resolve(staticRoot,['/','/editor','/create'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));
    assert.ok(file.startsWith(staticRoot.endsWith(sep)?staticRoot:staticRoot+sep));
    return route.fulfill({body:await readFile(file),contentType:{'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript',
      '.css':'text/css','.json':'application/json','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream'});
  });
  await page.addInitScript(()=>localStorage.setItem('h3slides-project','dual-ui'));
  const frame=page.locator('#slide-dual-slide .slide-frame'),card=page.locator('#slide-dual-slide');
  const media=kind=>frame.locator('.visual[data-visual-kind="'+kind+'"]');
  const actions=kind=>frame.locator('.visual-actions[data-visual-kind="'+kind+'"]');
  const ready=async()=>{
    await frame.waitFor();
    if(await page.locator('#create-page').isHidden())await page.locator('#open-create').click();
    await frame.scrollIntoViewIfNeeded();
    await page.waitForFunction(()=>[...document.querySelectorAll('.visual img,img.visual')].every(img=>img.naturalWidth>0));
  };
  const saved=async revision=>page.waitForFunction(value=>document.querySelector('#slide-dual-slide')?.dataset.saving===undefined&&
    JSON.parse(document.querySelector('#slide-dual-slide').dataset.signature)[0].revision>value,revision);
  await page.goto(origin+'/editor?project=dual-ui');await ready();
  assert.equal(await frame.locator('.visual').count(),2);
  await media('diagram').hover();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.visual-actions[data-visual-kind="diagram"]')).opacity==='1');
  assert.equal(await actions('image').evaluate(e=>getComputedStyle(e).opacity),'0','Photo controls stay hidden on diagram hover');
  await media('image').hover();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.visual-actions[data-visual-kind="image"]')).opacity==='1');
  assert.equal(await actions('diagram').evaluate(e=>getComputedStyle(e).opacity),'0','Diagram controls stay hidden on photo hover');
  await actions('image').locator('[data-action="search-image"]').click();
  const picker=page.locator('#image-search-dialog');await picker.locator('.image-search-result').first().waitFor();
  assert.equal(await picker.locator('[name="query"]').inputValue(),baseContent.title,'Automatic query from slide title');
  assert.equal(searches[0].source,'document','Attached document is searched first, without a web request');
  assert.equal(await picker.locator('.image-search-result').count(),1);
  assert.equal(await picker.locator('.image-search-result strong').textContent(),'Foto dal documento');
  await picker.locator('.image-search-result button').click();await picker.waitFor({state:'hidden'});
  assert.equal(project.slides[0].content.image_origin,'source');assert.equal(project.visual_assets.length,0,'Original asset is reused');
  assert.deepEqual(project.slides[0].content.freeform,baseContent.freeform);
  assert.equal(await frame.locator('.visual').count(),2,'Local selection leaves the diagram visible');
  await page.reload();await ready();
  assert.equal(await media('image').locator('img').getAttribute('alt'),'Foto dal documento','Local selection persists after reload');
  await media('image').hover();await actions('image').locator('[data-action="search-image"]').click();
  await picker.locator('.image-search-result').first().waitFor();
  await picker.locator('[name="source"]').selectOption('web');
  await page.waitForFunction(()=>document.querySelectorAll('.image-search-result').length===10);
  assert.equal(searches.find(search=>search.source!=='document').openverse,false,'Openverse remains optional');
  assert.equal(await picker.locator('.image-search-result').count(),10);
  await picker.locator('[data-more]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.image-search-result').length===20);
  assert.equal(await picker.locator('[data-more]').isHidden(),true);
  await picker.locator('[name="query"]').fill('Odysseus');await picker.locator('button[type="submit"]').click();
  await picker.locator('.image-search-result').first().waitFor();
  assert.equal(await picker.locator('.image-search-result').count(),10,'New query replaces previous results');
  await picker.locator('.image-search-result button').first().click();await picker.waitFor({state:'hidden'});
  assert.equal(selections.length,2);assert.equal(selections[0].revision,1);assert.equal(selections[1].revision,2);
  assert.equal(project.slides[0].content.image_origin,'web');
  assert.deepEqual(project.slides[0].content.blocks,baseContent.blocks);
  assert.deepEqual(project.slides[0].content.freeform,baseContent.freeform);
  assert.equal(await frame.locator('.visual').count(),2,'Selected image leaves the Manim diagram visible');
  // Manual document selection remains usable when automatic source images are disabled.
  project.use_source_images=false;await page.reload();await ready();
  assert.equal(await page.locator('#source-images').isChecked(),false);
  await media('image').hover();await actions('image').locator('[data-action="search-image"]').click();
  await picker.locator('.image-search-result').first().waitFor();
  await picker.locator('.image-search-result button').click();await picker.waitFor({state:'hidden'});
  assert.equal(await page.locator('#source-images').isChecked(),true);
  assert.equal(project.slides[0].content.image_origin,'source');assert.equal(project.use_source_images,true);
  assert.equal(project.visual_assets.length,1,'A manual source choice creates no extra visual assets');
  assert.equal(await frame.locator('.visual').count(),2);
  await media('diagram').hover();await actions('diagram').locator('[data-action="diagram-live"]').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Generazione avviata');
  assert.equal(generated.length,1);assert.equal(generated[0].diagram_only,true);
  assert.match(generated[0].prompt,/500 × 240 px/,'Redesign measures the diagram rectangle');
  let revision=project.slides[0].revision;
  await media('image').hover();await actions('image').locator('[data-action="delete-element"]').click();await saved(revision);
  assert.equal(project.slides[0].content.image_id,'');assert.equal(project.slides[0].content.diagram.kind,'manim');
  assert.deepEqual(project.slides[0].content.freeform.visual,baseContent.freeform.visual);
  assert.equal(await media('diagram').count(),1);assert.equal(await media('image').count(),0);
  revision=project.slides[0].revision;
  await card.locator('[data-live-image]').selectOption(photo);await saved(revision);
  assert.equal(project.slides[0].content.diagram.kind,'manim','Choosing an image preserves the diagram');
  assert.equal(await frame.locator('.visual').count(),2);
  // Restored explicit geometry makes movement of one object easy to compare.
  project.slides[0].content=structuredClone(baseContent);project.slides[0].revision++;
  await page.reload();await ready();revision=project.slides[0].revision;
  let photoBox=await media('image').boundingBox();
  await page.mouse.move(photoBox.x+photoBox.width/2,photoBox.y+photoBox.height/2);await page.mouse.down();
  await page.mouse.move(photoBox.x+photoBox.width/2-20,photoBox.y+photoBox.height/2+5,{steps:8});await page.mouse.up();await saved(revision);
  assert.deepEqual(project.slides[0].content.freeform.visual,baseContent.freeform.visual,'Photo drag does not move the diagram');
  assert.notDeepEqual(project.slides[0].content.freeform.image,baseContent.freeform.image);
  revision=project.slides[0].revision;
  await media('image').click({position:{x:16,y:40}});
  assert.equal(await media('image').evaluate(e=>e.classList.contains('is-selected')),true);
  assert.equal(await frame.locator('[data-free-resize="image"]:visible').count(),8);
  const handle=await frame.locator('[data-free-resize="image"][data-resize-edge="se"]').boundingBox();
  assert.ok(handle,'The selected image exposes its southeast resize handle');
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down();
  await page.mouse.move(handle.x+handle.width/2-20,handle.y+handle.height/2-10,{steps:8});await page.mouse.up();await saved(revision);
  assert.deepEqual(project.slides[0].content.freeform.visual,baseContent.freeform.visual,'Photo resize preserves the diagram');
  revision=project.slides[0].revision;
  await media('diagram').hover();await actions('diagram').locator('[data-action="delete-element"]').click();await saved(revision);
  assert.equal(project.slides[0].content.diagram.kind,'none');assert.equal(project.slides[0].content.image_id,photo);
  assert.equal(await media('diagram').count(),0);assert.equal(await media('image').count(),1);
  // Upload into a photo placeholder beside an existing diagram.
  project.slides[0]={...project.slides[0],content:{...structuredClone(baseContent),image_id:'',image_placeholder:true},
    diagram_render:{engine:'manim',asset:diagramAsset},revision:project.slides[0].revision+1};
  await page.reload();await ready();await media('image').hover();
  assert.equal(await actions('image').locator('[data-action="search-image"]').isVisible(),true,'Search exists on empty placeholders');
  const chooser=page.waitForEvent('filechooser');await actions('image').locator('[data-action="upload-image"]').click();
  await (await chooser).setFiles({name:'sample.png',mimeType:'image/png',buffer:pixels});
  await frame.locator('.photo-visual img').waitFor();
  assert.equal(uploads.length,1);assert.equal(project.slides[0].content.diagram.kind,'manim');
  await media('image').hover();
  assert.equal(await actions('image').locator('[data-action="search-image"]').isVisible(),true,'Search exists on manual uploads');
  assert.deepEqual(project.slides[0].content.freeform.visual,baseContent.freeform.visual);
  // Each object can also be moved directly from an adaptive composition.
  project.slides[0].content={...structuredClone(baseContent),layout:'visual-right',layout_locked:true,freeform:{}};
  project.slides[0].revision++;await page.reload();await ready();revision=project.slides[0].revision;
  const before=await frame.evaluate(element=>{
    const root=element.getBoundingClientRect(),box=element.querySelector('[data-visual-kind="diagram"]').getBoundingClientRect(),scale=root.width/1280;
    return {x:Math.round((box.left-root.left)/scale),y:Math.round((box.top-root.top)/scale),w:Math.round(box.width/scale),h:Math.round(box.height/scale)};
  });
  photoBox=await media('image').boundingBox();
  await page.mouse.move(photoBox.x+photoBox.width/2,photoBox.y+photoBox.height/2);await page.mouse.down();
  await page.mouse.move(photoBox.x+photoBox.width/2-12,photoBox.y+photoBox.height/2,{steps:8});await page.mouse.up();await saved(revision);
  assert.equal(project.slides[0].content.layout,'freeform');
  assert.deepEqual(project.slides[0].content.freeform.visual,before,'Adaptive photo drag freezes the other media in place');
  assert.ok(project.slides[0].content.freeform.image);assert.ok(project.slides[0].content.freeform['block-0']);
  revision=project.slides[0].revision;
  const savedPhoto=structuredClone(project.slides[0].content.freeform.image),diagramBox=await media('diagram').boundingBox();
  await page.mouse.move(diagramBox.x+diagramBox.width/2,diagramBox.y+diagramBox.height/2);await page.mouse.down();
  await page.mouse.move(diagramBox.x+diagramBox.width/2+12,diagramBox.y+diagramBox.height/2,{steps:8});await page.mouse.up();await saved(revision);
  assert.deepEqual(project.slides[0].content.freeform.image,savedPhoto,'Diagram drag preserves the photo rectangle');
  // Hiding Manim must not make the photo reuse and overwrite the hidden diagram slot.
  const savedDiagram=structuredClone(project.slides[0].content.freeform.visual);
  project.use_manim_diagrams=false;await page.reload();await ready();revision=project.slides[0].revision;
  assert.equal(await media('image').getAttribute('data-free-key'),'image');
  photoBox=await media('image').boundingBox();
  await page.mouse.move(photoBox.x+photoBox.width/2,photoBox.y+photoBox.height/2);await page.mouse.down();
  await page.mouse.move(photoBox.x+photoBox.width/2-12,photoBox.y+photoBox.height/2,{steps:8});await page.mouse.up();await saved(revision);
  assert.deepEqual(project.slides[0].content.freeform.visual,savedDiagram,'Dragging the photo preserves hidden diagram placement');
  project.use_manim_diagrams=true;
  for(const legacyKey of ['visual','image']){
    project.slides[0].content={...structuredClone(baseContent),freeform:{heading:baseContent.freeform.heading,
      'block-0':baseContent.freeform['block-0'],[legacyKey]:{x:700,y:200,w:500,h:430}}};
    project.slides[0].revision++;await page.reload();await ready();revision=project.slides[0].revision;
    photoBox=await media('image').boundingBox();
    await page.mouse.move(photoBox.x+photoBox.width/2,photoBox.y+photoBox.height/2);await page.mouse.down();
    await page.mouse.move(photoBox.x+photoBox.width/2-12,photoBox.y+photoBox.height/2,{steps:8});await page.mouse.up();await saved(revision);
    const positions=project.slides[0].content.freeform;
    assert.ok(positions.visual&&positions.image,'First drag persists both virtual slots');
    assert.ok(positions.visual.y+positions.visual.h<positions.image.y,'Saving the photo must not restore the entire legacy diagram rectangle');
  }
  // New studio navigation and adaptive text resizing are tested without a model.
  assert.equal(new URL(page.url()).pathname,'/editor');
  assert.equal(await page.locator('.settings').isVisible(),false);
  await page.locator('#editor-menu > summary').click();
  await page.locator('#editor-settings').click();
  assert.equal(new URL(page.url()).pathname,'/create');
  assert.ok(await page.locator('.theme-swatch').count()>=8);
  await page.locator('.theme-swatch').first().click();
  assert.equal(await page.locator('#background-color').inputValue(),'#172e73');
  await page.locator('#save-project').click();
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Salvato sul PC');
  await page.locator('#setup-back').click();await ready();
  project.canvas_mode='adaptive';
  project.slides[0].content={...structuredClone(baseContent),layout:'visual-right',layout_locked:true,freeform:{}};
  project.slides[0].revision++;await page.reload();await ready();revision=project.slides[0].revision;
  const textBox=frame.locator('[data-free-key="block-0"]');await textBox.click({position:{x:16,y:40}});
  assert.equal(await textBox.evaluate(e=>e.classList.contains('is-selected')),true);
  assert.equal(await frame.locator('[data-free-resize="block-0"]:visible').count(),8);
  const textHandle=await frame.locator('[data-free-resize="block-0"][data-resize-edge="se"]').boundingBox();
  assert.ok(textHandle,'Selected text has a southeast resize handle before switching to freeform');
  const startWidth=await textBox.evaluate(n=>n.offsetWidth);
  await page.mouse.move(textHandle.x+textHandle.width/2,textHandle.y+textHandle.height/2);await page.mouse.down();
  await page.mouse.move(textHandle.x+textHandle.width/2-24,textHandle.y+textHandle.height/2-10,{steps:8});await page.mouse.up();await saved(revision);
  assert.equal(project.slides[0].content.layout,'freeform');
  assert.ok(project.slides[0].content.freeform['block-0'].w<startWidth);
  assert.ok(project.slides[0].content.freeform.visual&&project.slides[0].content.freeform.image);
  assert.equal(project.slides[0].content.blocks[0].text,baseContent.blocks[0].text);
  await page.reload();await ready();
  assert.equal(await textBox.evaluate(n=>n.offsetWidth),project.slides[0].content.freeform['block-0'].w,'Text size persists after reload');
  assert.deepEqual(errors,[]);
  console.log('Dual media UI: distinct hover controls, measured redesign, independent deletion, source selection, upload, drag, resize and adaptive placement passed.');
}finally{await page.unrouteAll({behavior:'wait'});await browser.close()}
