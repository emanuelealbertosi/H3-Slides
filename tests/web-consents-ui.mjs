import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// Requests are mocked, including generation: no LLM/search or real app data.
const staticRoot=fileURLToPath(new URL('../static/',import.meta.url));
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
const project={id:'consent-ui',title:'Consenso di prova',prompt:'Spiega la fotocamera',count:6,
  theme:'paper',slides:[],sources:[{id:'manuale',name:'Manuale.md',images:[],warnings:[]}],
  web_enabled:true,web_provider:'wikipedia',web_query:'',source_priority:'documents'};
let endpoint='http://127.0.0.1:8080',holdSettings=false,releaseSettings;
const generated=[];
const normalize=value=>{const url=new URL(value);return url.origin+url.pathname.replace(/\/+$/,'')};
try{
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    assert.equal(url.hostname,'127.0.0.1','No external network in this test');
    if(url.pathname.startsWith('/api/')){
      if(url.pathname==='/api/admin/search'){
        if(method==='POST')endpoint=normalize(route.request().postDataJSON().searxng_url);
        else if(holdSettings)await new Promise(resolve=>{releaseSettings=resolve});
        return route.fulfill({json:{searxng_url:endpoint}});
      }
      if(url.pathname==='/api/projects/consent-ui'&&method==='PATCH'){
        Object.assign(project,route.request().postDataJSON());return route.fulfill({json:project});
      }
      if(url.pathname==='/api/projects/consent-ui/generate'&&method==='POST'){
        generated.push(route.request().postDataJSON());
        return route.fulfill({json:{id:'mock-job',status:'completed',progress:1,events:[]}});
      }
      assert.equal(method,'GET','Unexpected mutation '+url.pathname);
      const responses={
        '/api/projects':[{...project,slide_count:0}],'/api/projects/consent-ui':project,
        '/api/models':{models:[{id:'mock',name:'gemma test',size_gb:1,vision:true}],default_model:'mock',
          runtime_available:true,status:{running:false}},
        '/api/jobs':[], '/api/documents':[], '/api/themes':[],
        '/api/library':{folders:[],order:[],assignments:{}},
      };
      assert.ok(Object.hasOwn(responses,url.pathname),'Unexpected API '+url.pathname);
      return route.fulfill({json:responses[url.pathname]});
    }
    const file=resolve(staticRoot,url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,''));
    assert.ok(file.startsWith(staticRoot.endsWith(sep)?staticRoot:staticRoot+sep));
    const contentType={'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript',
      '.css':'text/css','.json':'application/json','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream';
    await route.fulfill({body:await readFile(file),contentType});
  });
  await page.addInitScript(()=>{
    localStorage.setItem('h3slides-project','consent-ui');
    if(!localStorage.getItem('h3slides-settings'))localStorage.setItem('h3slides-settings',
      JSON.stringify({remote_consents:{'https://remote.example/v1':true}}));
  });
  const ready=()=>page.waitForFunction(()=>document.querySelector('#sources').textContent.includes('Manuale.md'));
  const save=async()=>{
    await page.locator('#save-project').click();
    await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Salvato sul PC');
  };
  const consent=page.locator('#web-consent'),engine=page.locator('#web-provider');
  const reload=async()=>{await page.reload();await ready()};
  await page.goto('http://127.0.0.1:9876/');await ready();
  assert.equal(await consent.isChecked(),false,'First use needs explicit consent');
  assert.equal(await page.locator('#web-always-search').isChecked(),false,'Legacy projects do not force web search');
  await consent.check();
  await page.locator('#web-always-search').check();
  assert.equal(await page.locator('#source-priority').inputValue(),'documents','Forced web does not change source priority');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('h3slides-settings'))['web-always-search']),true);
  await page.locator('#web-query').fill('Fotocamera');
  await page.locator('#web-max-sources').selectOption('5');
  assert.equal(await consent.isChecked(),true,'Query and source limit edits retain consent');
  await engine.selectOption('duckduckgo');
  assert.equal(await consent.isChecked(),false,'A different engine does not inherit consent');
  await engine.selectOption('wikipedia');
  assert.equal(await consent.isChecked(),true,'Returning to an approved engine restores consent');
  await save();await reload();
  assert.equal(await consent.isChecked(),true,'Consent survives reload');
  assert.equal(await page.locator('#web-always-search').isChecked(),true,'Forced search survives project save and reload');
  assert.equal(project.web_always_search,true);
  await consent.uncheck();await reload();
  assert.equal(await consent.isChecked(),false,'Revocation survives reload');
  await consent.check();
  const submission=page.waitForResponse(response=>response.url().endsWith('/generate'));
  await page.locator('#generate-top').click();await submission;
  await page.waitForFunction(()=>!document.querySelector('#generate-top').disabled);
  assert.equal(generated.length,1);assert.equal(generated[0].web_consent,true);
  assert.equal(await consent.isChecked(),true,'Successful generation does not reset consent');
  await page.locator('#new').click();
  assert.equal(await page.locator('#web-enabled').isChecked(),false,'Consent never enables web for a new project');
  assert.equal(await page.locator('#web-always-search').isChecked(),true,'New projects remember the option without enabling web');
  assert.equal(await consent.isChecked(),true);
  await page.locator('#project-list').selectOption('consent-ui');await ready();
  assert.equal(await consent.isChecked(),true,'Opening a project restores engine-specific consent');
  await engine.selectOption('searxng');
  await page.waitForFunction(()=>!document.querySelector('#web-consent').disabled);
  assert.equal(await consent.isChecked(),false,'SearXNG needs its own consent');
  await consent.check();
  await page.getByText('Configura SearXNG su questo computer',{exact:true}).click();
  await page.locator('#searxng-url').fill('HTTP://127.0.0.1:8080///');
  assert.equal(await consent.isChecked(),true,'Equivalent normalized endpoint retains consent');
  await page.locator('#searxng-url').fill('http://127.0.0.1:9090/');
  assert.equal(await consent.isChecked(),false,'New endpoint must not inherit consent');
  assert.equal(await consent.isDisabled(),true,'Unsaved destination cannot authorize the old backend address');
  await page.locator('#save-search-settings').click();
  await page.waitForFunction(()=>!document.querySelector('#web-consent').disabled);
  assert.equal(await consent.isChecked(),false);
  await consent.check();await save();
  holdSettings=true;
  await reload();
  assert.equal(await consent.isChecked(),false,'Wait for actual endpoint settings before restore');
  assert.equal(await consent.isDisabled(),true);
  holdSettings=false;releaseSettings();
  await page.waitForFunction(()=>!document.querySelector('#web-consent').disabled);
  assert.equal(await consent.isChecked(),true,'Async settings restore consent for the matching saved endpoint');
  endpoint='http://127.0.0.1:10000';
  await reload();await page.waitForFunction(()=>!document.querySelector('#web-consent').disabled);
  assert.equal(await consent.isChecked(),false,'Externally changed endpoint is not auto-approved');
  await engine.selectOption('wikipedia');
  assert.equal(await consent.isChecked(),true,'Remote/provider consent remains independent');
  const preferences=await page.evaluate(()=>JSON.parse(localStorage.getItem('h3slides-settings')));
  assert.deepEqual(preferences.remote_consents,{'https://remote.example/v1':true});
  assert.deepEqual(preferences.web_consents,{wikipedia:true,'searxng|http://127.0.0.1:8080':true,
    'searxng|http://127.0.0.1:9090':true});
  assert.equal(Object.hasOwn(preferences,'api-key'),false);
  await page.locator('#web-always-search').uncheck();
  await save();await reload();
  assert.equal(await page.locator('#web-always-search').isChecked(),false,'Forced search can be revoked persistently');
  delete project.web_always_search;
  await page.evaluate(()=>{
    const value=JSON.parse(localStorage.getItem('h3slides-settings'));
    value['web-always-search']=true;localStorage.setItem('h3slides-settings',JSON.stringify(value));
  });
  await reload();
  assert.equal(await page.locator('#web-always-search').isChecked(),false,'Legacy project default wins over browser forced-search preference');
  assert.deepEqual(errors,[]);
  console.log('Web consent UI: persistence, revocation, generation, engine/endpoint isolation, async restore and no automatic web activation passed.');
}finally{await page.unrouteAll({behavior:'wait'});await browser.close()}
