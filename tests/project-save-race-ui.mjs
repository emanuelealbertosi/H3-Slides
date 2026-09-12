import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// Delayed in-memory PATCH only: no real server, model or user project is used.
const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const project=(id,title)=>({id,title,prompt:'Istruzioni originali di '+title,count:3,theme:'paper',font:'Arial',
  canvas_mode:'adaptive',graphic_style:'studio',template:'auto',text_density:'detailed',sources:[],visual_assets:[],
  use_manim_diagrams:false,use_source_images:true,use_web_images:false,web_enabled:false,revision:1,slides:[]});
const projects=[project('project-a','Progetto A'),project('project-b','Progetto B')];
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1500,height:1100}});
page.setDefaultTimeout(15000);
const errors=[],patches=[],confirmations=[];
let releaseA,dismissNextDialog=false;
const firstSaveGate=new Promise(resolve=>{releaseA=resolve});
page.on('pageerror',error=>errors.push(error.message));
page.on('dialog',async dialog=>{
  confirmations.push(dialog.message());
  if(dismissNextDialog){dismissNextDialog=false;await dialog.dismiss()}
  else await dialog.accept();
});
const selected=async(id,title)=>{
  await page.waitForFunction(({id,title})=>document.querySelector('#project-list').value===id&&
    document.querySelector('#title').value===title&&localStorage.getItem('h3slides-project')===id,{id,title});
};
try{
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    try{
      assert.equal(url.origin,origin,'No external requests');
      if(url.pathname.startsWith('/api/')){
        const detail=url.pathname.match(/^\/api\/projects\/([^/]+)$/);
        if(detail){
          const target=projects.find(item=>item.id===detail[1]);assert.ok(target,'Known project');
          if(method==='PATCH'){
            const payload=route.request().postDataJSON();patches.push({id:target.id,payload:structuredClone(payload)});
            if(target.id==='project-a')await firstSaveGate;
            const {slide_layouts,...values}=payload;
            assert.deepEqual(slide_layouts,[],'Zero-slide fixture must not invent geometry');
            Object.assign(target,values,{revision:target.revision+1});
          }else assert.equal(method,'GET','No generation or unexpected mutation');
          return route.fulfill({json:target});
        }
        assert.equal(method,'GET','No generation or unexpected mutation');
        const model={id:'mock',name:'Simulato',size_gb:1,vision:true};
        const responses={'/api/projects':projects.map(item=>({...item,slide_count:0,ready_count:0})),
          '/api/jobs':[],'/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},
          '/api/models':{models:[model],default_model:'mock',runtime_available:true,status:{running:false}},
          '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
          '/api/admin/llm':{models:[model],profiles:{},status:{running:false},loading_schema:{properties:{}},inference_schema:{properties:{}}}};
        assert.ok(Object.hasOwn(responses,url.pathname),url.pathname);return route.fulfill({json:responses[url.pathname]});
      }
      const file=resolve(root,['/','/create','/editor','/library'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));
      assert.ok(file.startsWith(root.endsWith(sep)?root:root+sep));
      try{return route.fulfill({body:await readFile(file),contentType:({'.mjs':'text/javascript','.css':'text/css',
        '.html':'text/html','.json':'application/json','.woff2':'font/woff2','.woff':'font/woff'})[extname(file)]||'application/octet-stream'})}
      catch{return route.fulfill({status:404,body:''})}
    }catch(error){errors.push(error.message);return route.fulfill({status:500,json:{error:error.message}})}
  });
  await page.goto(origin+'/create?project=project-a');await selected('project-a','Progetto A');
  const aTitle='A salvato mentre visito B',aPrompt='Solo istruzioni del progetto A';
  await page.locator('#title').fill(aTitle);await page.locator('#prompt').fill(aPrompt);
  const aRequested=page.waitForRequest(request=>request.method()==='PATCH'&&new URL(request.url()).pathname==='/api/projects/project-a');
  await page.locator('#save-project').click();await aRequested;
  assert.equal(patches.length,1);assert.equal(patches[0].id,'project-a');
  // Switch while the first save is still unresolved, then start a different draft.
  await page.locator('#project-list').selectOption('project-b');await selected('project-b','Progetto B');
  const bTitle='Bozza B da conservare',bPrompt='Nuove istruzioni indipendenti per B';
  await page.locator('#title').fill(bTitle);await page.locator('#prompt').fill(bPrompt);
  assert.equal(await page.locator('#save-status').textContent(),'Brief non salvato');
  releaseA();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('progetto di origine'));
  await selected('project-b',bTitle);
  assert.equal(await page.locator('#prompt').inputValue(),bPrompt);
  assert.equal(await page.locator('#save-status').textContent(),'Brief non salvato');
  assert.equal(projects[0].title,aTitle);assert.equal(projects[0].prompt,aPrompt);
  assert.equal(projects[1].title,'Progetto B','The pending save must not silently save B');
  assert.deepEqual(patches.map(item=>item.id),['project-a'],'No cascading PATCH to the selected project');
  // Cancelling New proves the B draft flag was not cleared by A's response.
  const priorConfirmations=confirmations.length;dismissNextDialog=true;
  await page.locator('#new').click();
  assert.equal(confirmations.length,priorConfirmations+1);
  assert.match(confirmations.at(-1),/modifiche non salvate/);await selected('project-b',bTitle);
  // Explicitly saving B afterwards still uses the B draft and B endpoint.
  const bResponse=page.waitForResponse(response=>response.request().method()==='PATCH'&&
    new URL(response.url()).pathname==='/api/projects/project-b');
  await page.locator('#save-project').click();await bResponse;
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Salvato sul PC');
  await selected('project-b',bTitle);assert.equal(await page.locator('#prompt').inputValue(),bPrompt);
  assert.deepEqual(patches.map(item=>item.id),['project-a','project-b']);
  assert.equal(patches[1].payload.title,bTitle);assert.equal(patches[1].payload.prompt,bPrompt);
  assert.equal(projects[0].title,aTitle);assert.equal(projects[0].prompt,aPrompt);
  assert.equal(projects[1].title,bTitle);assert.equal(projects[1].prompt,bPrompt);
  assert.deepEqual(errors,[]);
  console.log('Project save race: delayed A response preserves B selection, draft and explicit save; no cascading requests');
}finally{releaseA();await browser.close()}
