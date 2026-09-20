import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';
const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const details={visual_family:'editorial',background_style:'gradient',secondary_color:'#d9bd8c',heading_font:'Georgia',shadow_style:'lifted',decoration:'corner',design_note:'Una nota visiva conservata',box_radius:7,border_width:1,title_size:52,body_size:25};
const candidate={name:'Carta <em>speciale</em>',values:{theme:'paper',font:'Segoe UI',template:'editorial',graphic_style:'editorial',background_color:'#f8f2e5',accent_color:'#226352',theme_design:{...details,visual_family:'technical',heading_font:'Consolas',decoration:'stripe',design_note:'Esempi chiari e titoli leggibili.'}}};
const browser=await chromium.launch({headless:true});
try{for(const viewport of [{width:1500,height:1000},{width:390,height:844}]){
  const page=await browser.newPage({viewport});page.setDefaultTimeout(10000);
  const errors=[],designs=[],patches=[],savedThemes=[],jobs=[];
  let releaseDesign,holdDesign=true,rejectDesign=false;
  const projects=[{id:'legacy',title:'Un tema precedente',prompt:'Contenuto privato del progetto, da non inviare al tema AI',count:2,theme:'paper',font:'Arial',engine:'v2',canvas_mode:'adaptive',background_color:'#ede2cf',accent_color:'#5e4222',theme_preset:'Oceano · blu elettrico',sources:[],slides:[],theme_design:{box_radius:13}},
    {id:'rich',title:'Un tema completo',prompt:'Contenuto del progetto',count:2,theme:'paper',font:'Arial',engine:'v2',canvas_mode:'adaptive',background_color:'#ede2cf',accent_color:'#5e4222',sources:[],slides:[],theme_design:{...details}}];
  page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept());
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    try{
      assert.equal(url.origin,origin,'All traffic is mocked; no actual model or service');
      if(url.pathname.startsWith('/api/')){
        if(method!=='GET')assert.equal(request.headers()['x-h3-slides'],'1');
        if(url.pathname==='/api/themes/design'){
          designs.push(request.postDataJSON());
          if(holdDesign)await new Promise(resolve=>{releaseDesign=resolve});
          return route.fulfill(rejectDesign?{status:409,json:{error:'Un altro lavoro è già in corso'}}:{json:candidate});
        }
        if(url.pathname==='/api/themes'&&method==='POST'){savedThemes.push(request.postDataJSON());return route.fulfill({json:request.postDataJSON()})}
        if(url.pathname==='/api/remote-models')return route.fulfill({json:{models:[{id:'remote-fixture',name:'Modello API di prova'}]}});
        const match=url.pathname.match(/^\/api\/projects\/([^/]+)$/);
        if(match){const project=projects.find(p=>p.id===match[1]);assert(project);if(method==='PATCH'){patches.push(request.postDataJSON());Object.assign(project,request.postDataJSON())}return route.fulfill({json:project})}
        const data={'/api/projects':projects.map(p=>({...p,slide_count:0})), '/api/documents':[], '/api/jobs':jobs, '/api/themes':savedThemes,
          '/api/library':{folders:[],order:[],assignments:{}}, '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
          '/api/admin/llm':{models:[],profiles:{},loading_schema:{properties:{}},inference_schema:{properties:{}},status:{running:false}},
          '/api/models':{models:[{id:'mock',name:'Modello di prova',size_gb:1,vision:true}],default_model:'mock',runtime_available:true,status:{running:false}}};
        assert(Object.hasOwn(data,url.pathname),'Unexpected endpoint (generation/runtime mutation forbidden): '+url.pathname);return route.fulfill({json:data[url.pathname]});
      }
      const file=resolve(root,['/','/create','/admin','/editor','/library'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));assert(file.startsWith(root.endsWith(sep)?root:root+sep));
      return route.fulfill({body:await readFile(file),contentType:{'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream'});
    }catch(error){errors.push(error.message);return route.fulfill({status:500,json:{error:error.message}})}
  });
  const noOverflow=async label=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),label+' at '+viewport.width);
  const state=()=>page.evaluate(()=>({background:document.querySelector('#background-color').value,accent:document.querySelector('#accent-color').value,font:document.querySelector('#font').value,
    choices:Object.fromEntries([...document.querySelectorAll('[data-theme-choice]')].map(e=>[e.dataset.themeChoice,e.value])),note:document.querySelector('[data-theme-note]').value}));
  async function saveBrief(){const previous=patches.length,response=page.waitForResponse(r=>r.url().includes('/api/projects/')&&r.request().method()==='PATCH');await page.locator('#save-project').click();await response;assert.equal(patches.length,previous+1)}
  await page.goto(origin+'/create?project=legacy');await page.waitForFunction(()=>document.querySelector('#title').value==='Un tema precedente');
  await page.waitForFunction(()=>document.querySelectorAll('#theme-gallery .theme-swatch').length===8);
  assert.equal(await page.locator('#theme-gallery .theme-v2-mini').count(),8);
  assert.equal(await page.locator('#theme-gallery img').count(),0,'HTML previews do not need generated images');
  const clipped=await page.locator('#theme-gallery .theme-v2-mini').evaluateAll(items=>items.filter(e=>e.scrollHeight>e.clientHeight+1).map(e=>[e.clientWidth,e.clientHeight,e.scrollHeight]));
  assert.deepEqual(clipped,[],'Miniature contents are not clipped');
  assert.equal((await state()).background,'#ede2cf','A legacy preset name never reapplies changed builtins');
  assert.equal((await state()).choices.shadow_style,'soft','Missing legacy field keeps the renderer default');
  assert.equal((await state()).choices.visual_family,'classic');
  assert.equal(await page.locator('#theme-current-preview .theme-v2-mini').evaluate(e=>e.style.backgroundColor),'rgb(237, 226, 207)');
  await saveBrief();assert.equal(patches.at(-1).theme_design.shadow_style,'soft');assert.equal(patches.at(-1).theme_design.box_radius,13);
  assert.equal(await page.evaluate(async d=>(await import('/static/theme-v2.mjs')).resolveV2Theme({theme_design:d}).enabled,patches.at(-1).theme_design),false,'Legacy fill/read does not activate the new renderer');
  await noOverflow('Legacy gallery');

  await page.goto(origin+'/create?project=rich');await page.waitForFunction(()=>document.querySelector('#title').value==='Un tema completo');
  await page.locator('.theme-details>summary').click();
  await page.locator('[data-theme-number="body_size"]').fill('26');await saveBrief();
  for(const [key,value]of Object.entries(details))assert.equal(patches.at(-1).theme_design[key],key==='body_size'?26:value,'Roundtrip '+key);
  await page.locator('.theme-details>summary').click();await page.locator('.theme-ai-panel>summary').click();
  await page.locator('#theme-ai-prompt').fill('Una rivista tecnica, colori caldi ed esempi evidenti');
  await page.locator('#theme-ai-generate').click();await page.waitForFunction(()=>document.querySelector('#theme-ai-generate').disabled);
  for(let attempt=0;!designs.length&&attempt<200;attempt++)await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(designs.length,1);
  assert.equal(await page.locator('#generate-top').isDisabled(),true);
  assert.equal(await page.locator('#admin').evaluate(e=>e.inert),true,'Runtime configuration is locked during the theme request');
  await page.locator('#theme-ai-generate').evaluate(e=>e.click());assert.equal(designs.length,1,'Repeated click cannot start concurrent requests');
  await page.locator('#theme-gallery .theme-swatch').first().click();const beforeCandidate=await state();
  holdDesign=false;releaseDesign();await page.locator('#theme-ai-result').waitFor({state:'visible'});
  assert.deepEqual(await state(),beforeCandidate,'Completing AI does not apply its proposal');
  assert.equal(await page.locator('#theme-ai-name').textContent(),candidate.name);
  assert.equal(await page.locator('#theme-ai-name em').count(),0,'AI name is literal text');
  assert.equal(await page.locator('#generate-top').isDisabled(),false);
  assert.equal(await page.locator('#admin').evaluate(e=>e.inert),false);
  assert.equal(designs[0].provider.mode,'local');assert.equal(designs[0].provider.model,'mock');
  assert.deepEqual(Object.keys(designs[0]).sort(),['prompt','provider']);assert.equal(designs[0].prompt,'Una rivista tecnica, colori caldi ed esempi evidenti');
  assert(!JSON.stringify(designs[0]).includes(projects[0].prompt),'Private project brief is not sent');
  await page.locator('#theme-ai-save').click();await page.waitForFunction(()=>document.querySelectorAll('#theme-gallery .theme-swatch').length===9);
  assert.deepEqual(savedThemes[0],candidate,'Saving uses the existing theme endpoint');assert.deepEqual(await state(),beforeCandidate,'Saving does not apply');
  await page.locator('#theme-ai-apply').click();await saveBrief();
  for(const [key,value]of Object.entries(candidate.values.theme_design))assert.equal(patches.at(-1).theme_design[key],value,'AI field persists: '+key);
  assert.equal(patches.at(-1).theme_preset,candidate.name);
  await noOverflow('AI proposal');
  rejectDesign=true;await page.locator('#theme-ai-generate').click();await page.waitForFunction(()=>document.querySelector('#theme-ai-status').textContent.includes('occupato'));
  assert.equal(await page.locator('#generate-top').isDisabled(),false,'Rejected request releases the lock');rejectDesign=false;
  jobs.push({id:'active',project_id:'rich',status:'running',progress:.2,events:[]});
  await page.waitForFunction(()=>document.querySelector('#generate-top').disabled);const previous=designs.length;
  await page.locator('#theme-ai-generate').click();assert.equal(designs.length,previous,'Active generation blocks AI before sending');
  assert.match(await page.locator('#theme-ai-status').textContent(),/occupato|sta già lavorando/);
  await page.locator('#theme-gallery .theme-swatch').last().click();assert.equal((await state()).choices.visual_family,'technical','Preset selection remains available during generation');
  jobs.length=0;await page.waitForFunction(()=>!document.querySelector('#generate-top').disabled);

  if(viewport.width>800){
    await page.locator('#open-admin').click();await page.locator('#provider').selectOption('remote');
    await page.locator('#api-url').fill('https://configured.example/v1');await page.locator('#api-key').fill('test-only-theme-key');await page.locator('#api-key').press('Tab');
    await page.waitForFunction(()=>document.querySelector('#api-model').options.length===2&&!document.querySelector('#api-model').disabled);
    await page.locator('#api-model').selectOption('remote-fixture');await page.locator('#api-max-tokens').fill('7000');await page.locator('#api-temperature').fill('0.6');
    await page.locator('#close-admin').click();const old=designs.length;await page.locator('#theme-ai-generate').click();
    await page.locator('#admin').waitFor({state:'visible'});assert.equal(designs.length,old,'Actual remote consent is required');
    assert.match(await page.locator('#toast').textContent(),/autorizza l’invio/);
    await page.locator('#consent').check();await page.locator('#close-admin').click();await page.locator('#theme-ai-generate').click();
    await page.waitForFunction(()=>document.querySelector('#theme-ai-status').textContent.startsWith('Anteprima pronta'));
    assert.equal(designs.at(-1).provider.mode,'remote');assert.equal(designs.at(-1).provider.model,'remote-fixture');
    assert.equal(designs.at(-1).provider.remote_consent,true);assert.equal(designs.at(-1).provider.base_url,'https://configured.example/v1');
    assert.equal(designs.at(-1).provider.inference.max_tokens,7000);assert.equal(designs.at(-1).provider.inference.temperature,.6);
    assert.equal(designs.at(-1).provider.api_key,'test-only-theme-key');assert(!await page.evaluate(()=>localStorage.getItem('h3slides-settings').includes('test-only-theme-key')));
  }

  for(const surface of ['quote','plain']){const edited=await page.evaluate(async surface=>{
    const {renderPageCard}=await import('/static/page-v2-editor.mjs');
    const project={id:'test',theme:'paper',font:'Arial',theme_design:{visual_family:'modern'},sources:[]};
    const content={title:'Test',page:{style:{},nodes:[{id:'one',parent:'root',kind:'text',role:'quote',text:'Citazione',style:{surface,font_size:24}}]}};
    const card=document.createElement('section');document.body.append(card);
    renderPageCard(card,project,{id:'slide',status:'ready',content},0,{observe:()=>{},toast:message=>{throw Error(message)},save:async update=>update(content)});
    card.querySelector('[data-v2-edit="one"]').click();const dialog=document.querySelector('dialog.v2-editor');
    const options=[...dialog.querySelector('[name=surface]').options].map(o=>o.value),role=dialog.querySelector('[name=role]').value;
    dialog.querySelector('[name=text]').value='Citazione corretta';dialog.close('save');await new Promise(resolve=>setTimeout(resolve,20));card.remove();
    return {node:content.page.nodes[0],options,role};
  },surface);
  assert.equal(edited.role,'quote');assert.equal(edited.node.role,'quote');assert.equal(edited.node.style.surface,surface);assert.equal(edited.node.text,'Citazione corretta');
  for(const option of ['plain','gradient','example','key','quote'])assert(edited.options.includes(option));}
  assert.deepEqual(errors,[]);console.log('Theme studio '+viewport.width+': legacy, fields, mock AI preview/apply/save, consent, busy, editor roles passed');await page.close();
}}finally{await browser.close()}
