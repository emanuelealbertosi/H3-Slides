import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// Fully intercepted browser traffic: no real app, documents or image searches.
const staticRoot=fileURLToPath(new URL('../static/',import.meta.url));
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
const project={id:'openverse-ui',title:'Immagini di prova',prompt:'Spiega la fotocamera',count:6,
  theme:'paper',slides:[],sources:[{id:'manuale',name:'Manuale.md',kind:'md',images:[],warnings:[]}],
  web_enabled:true,source_priority:'documents',use_source_images:true,use_web_images:false};
const saves=[];
try{
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1')throw new Error('Unexpected external request: '+url.hostname);
    if(url.pathname.startsWith('/api/')){
      if(url.pathname==='/api/projects/openverse-ui'&&route.request().method()==='PATCH'){
        const payload=route.request().postDataJSON();saves.push(payload);Object.assign(project,payload);
        return route.fulfill({json:project});
      }
      assert.equal(route.request().method(),'GET','No generation or upload in this UI test');
      const responses={
        '/api/projects':[{...project,slide_count:0}], '/api/projects/openverse-ui':project,
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
  await page.addInitScript(()=>localStorage.setItem('h3slides-project','openverse-ui'));
  const ready=()=>page.waitForFunction(()=>document.querySelector('#sources').textContent.includes('Manuale.md'));
  const save=async()=>{
    await page.locator('#save-project').click();
    await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Salvato sul PC');
  };
  await page.goto('http://127.0.0.1:9876/');
  await ready();
  const openverse=page.locator('#openverse-images'),web=page.locator('#web-images');
  assert.equal(await openverse.isChecked(),false,'Legacy project does not opt in');
  assert.equal(await openverse.isDisabled(),true,'Extension needs image search');
  assert.equal(await page.locator('#source-images').isChecked(),true);
  await web.check();
  assert.equal(await openverse.isDisabled(),false);
  assert.equal(await openverse.isChecked(),false,'Image search must not opt in automatically');
  await openverse.check();
  assert.equal(await page.locator('#source-images').isChecked(),true);
  assert.equal(await page.locator('#web-enabled').isChecked(),true);
  assert.equal(await page.locator('#source-priority').inputValue(),'documents');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('h3slides-settings'))['openverse-images']),true);
  await save();
  assert.equal(saves.at(-1).use_openverse_images,true);
  await page.reload();await ready();
  assert.equal(await openverse.isChecked(),true,'Project opt-in survives reload');
  assert.equal(await openverse.isDisabled(),false);
  await web.uncheck();
  assert.equal(await openverse.isDisabled(),true,'Turning image search off disables the extension');
  await save();
  assert.equal(saves.at(-1).use_web_images,false);
  assert.equal(saves.at(-1).use_openverse_images,true,'Remembered option remains gated by image search');
  await page.reload();await ready();
  assert.equal(await openverse.isDisabled(),true);
  assert.equal(await web.isChecked(),false);
  assert.equal(await page.locator('#source-images').isChecked(),true,'Document images remain independent');
  assert.equal(await page.locator('#source-priority').inputValue(),'documents');
  delete project.use_openverse_images;project.use_web_images=true;
  await page.reload();await ready();
  assert.equal(await openverse.isChecked(),false,'Legacy default beats another project/browser opt-in');
  assert.deepEqual(errors,[]);
  console.log('Openverse UI: optional opt-in, project/preferences persistence, web gating, legacy default and document independence passed.');
}finally{await page.unrouteAll({behavior:'wait'});await browser.close()}
