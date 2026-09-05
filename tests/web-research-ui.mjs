import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// Every request is fulfilled locally: no app data, LLM or search service is used.
const staticRoot=fileURLToPath(new URL('../static/',import.meta.url));
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
const baseResearch={provider:'Wikipedia diretta',query:'OM-5 Mark II',query_mode:'automatic',
  attempted_queries:['OM-5 Mark II funzioni computazionali','OM-5 Mark II'],created_at:1750000000,
  sources:[{id:'W1',title:'Fotocamera',url:'https://it.wikipedia.org/wiki/Fotocamera'}],warnings:[]};
let research,projectOverrides={};
const document={id:'document-ui',name:'Manuale.md',kind:'md',images:[],warnings:[]};
const project=()=>({id:'research-ui',title:'Ricerca di prova',prompt:'Spiega la fotocamera',count:6,
  theme:'paper',slides:[],sources:[document],web_enabled:true,use_source_images:true,use_web_images:true,
  web_research:research,...projectOverrides});
try{
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1')return route.abort();
    if(url.pathname.startsWith('/api/')){
      if(url.pathname==='/api/projects/research-ui'&&route.request().method()==='PATCH'){
        projectOverrides={...projectOverrides,...route.request().postDataJSON()};
        return route.fulfill({json:project()});
      }
      assert.equal(route.request().method(),'GET','UI review must not mutate application state');
      const responses={
        '/api/projects':[{...project(),slide_count:0}],
        '/api/projects/research-ui':project(),
        '/api/models':{models:[{id:'mock',name:'gemma test',size_gb:1,vision:true}],default_model:'mock',
          runtime_available:true,status:{running:false}},
        '/api/jobs':[], '/api/documents':[], '/api/themes':[],
        '/api/library':{folders:[],order:[],assignments:{}},
        '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
      };
      assert.ok(Object.hasOwn(responses,url.pathname),'Unexpected API '+url.pathname);
      return route.fulfill({json:responses[url.pathname]});
    }
    const relative=url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,'');
    const file=resolve(staticRoot,relative);
    assert.ok(file.startsWith(staticRoot.endsWith(sep)?staticRoot:staticRoot+sep));
    const contentType={'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript',
      '.css':'text/css','.json':'application/json','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream';
    await route.fulfill({body:await readFile(file),contentType});
  });
  await page.addInitScript(()=>localStorage.setItem('h3slides-project','research-ui'));
  for(const status of [undefined,'completed','document_fallback','failed']){
    research={...baseResearch,...(status?{status}:{}),
      sources:status==='document_fallback'||status==='failed'?[]:baseResearch.sources};
    await page.goto('http://127.0.0.1:9876/');
    const panel=page.locator('#web-sources');
    await panel.locator('details').waitFor();
    assert.equal(await panel.locator('details').getAttribute('data-research-status'),status||'completed');
    assert.deepEqual(await panel.locator('ol li').allTextContents(),baseResearch.attempted_queries);
    const text=await panel.textContent();
    if(status==='document_fallback'){
      assert.match(text,/Solo documenti allegati, nessuna fonte web usata/);
      assert.doesNotMatch(text,/Ultima ricerca completata/);
      assert.match(await page.locator('#source-mode').textContent(),/Documenti allegati · nessuna integrazione web/);
      assert.equal(await panel.locator('a').count(),0);
    }else if(status==='failed'){
      assert.match(text,/Senza allegati la generazione si è fermata/);
      assert.doesNotMatch(text,/Ultima ricerca completata/);
      assert.equal(await panel.locator('a').count(),0);
    }else{
      assert.match(text,/Ultima ricerca completata/);
      assert.equal(await panel.locator('a').count(),1);
    }
    assert.equal(await page.locator('#source-images').isChecked(),true);
    assert.equal(await page.locator('#web-images').isChecked(),true);
    assert.equal(await page.locator('#source-priority').inputValue(),'documents','Legacy projects are document-first');
    assert.equal(await page.locator('#source-priority-option').isVisible(),true);
  }
  research={...baseResearch,status:'completed'};
  await page.reload();
  await page.locator('#web-sources [data-research-status="completed"]').waitFor();
  assert.match(await page.locator('#source-mode').textContent(),/Prima i documenti allegati/);
  await page.locator('#source-priority').selectOption('web');
  assert.match(await page.locator('#source-mode').textContent(),/Priorità al web, scelta esplicita/);
  await page.locator('#save-project').click();
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Salvato sul PC');
  assert.equal(projectOverrides.source_priority,'web');
  await page.reload();
  await page.locator('#web-sources [data-research-status="completed"]').waitFor();
  assert.equal(await page.locator('#source-priority').inputValue(),'web','Explicit project choice survives reload');
  await page.locator('#new').click();
  assert.equal(await page.locator('#source-priority').inputValue(),'documents','New projects reset priority');
  await page.locator('#project-list').selectOption('research-ui');
  await page.locator('#web-sources [data-research-status="completed"]').waitFor();
  assert.equal(await page.locator('#source-priority').inputValue(),'web','Reopened project preserves choice');
  projectOverrides={sources:[]};
  await page.reload();
  await page.locator('#web-sources [data-research-status="completed"]').waitFor();
  assert.equal(await page.locator('#source-priority-option').isHidden(),true,'Priority control requires attachments');
  projectOverrides={};
  research={...baseResearch,status:'document_fallback',attempted_queries:['<img src=x onerror=alert(1)>'],
    warnings:['<script>alert(1)</script>'],sources:baseResearch.sources};
  await page.reload();
  await page.locator('#web-sources [data-research-status="document_fallback"]').waitFor();
  assert.equal(await page.locator('#web-sources img,#web-sources script,#web-sources a').count(),0);
  assert.equal(await page.locator('#web-sources li').textContent(),research.attempted_queries[0]);
  assert.deepEqual(errors,[]);
  console.log('Research UI: statuses, document-first defaults, explicit persisted priority, queries, safe metadata and image flags passed.');
}finally{await page.unrouteAll({behavior:'wait'});await browser.close()}
