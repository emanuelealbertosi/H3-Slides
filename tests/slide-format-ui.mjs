import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';
const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const base={title:'Formati V2',prompt:'Un breve esempio',count:2,engine:'v2',canvas_mode:'adaptive',theme:'paper',font:'Arial',sources:[],visual_assets:[]};
const makeSlide=id=>({id,status:'ready',revision:1,content:{title:'Pagina '+id,layout:'content',blocks:[],bullets:[],notes:'',sources:[],diagram:{kind:'none'},page:{style:{},nodes:[{id:'title',parent:'root',kind:'heading',text:'Una pagina leggibile',style:{}},{id:'body',parent:'root',kind:'text',text:'Il formato rimane uniforme.',style:{}}]}}});
const browser=await chromium.launch({headless:true});
try{for(const viewport of [{width:1500,height:1000},{width:390,height:844}]){
  const page=await browser.newPage({viewport});page.setDefaultTimeout(12000);
  const errors=[],patches=[],generations=[],exports=[];
  const projects=[{...structuredClone(base),id:'legacy',slides:[makeSlide('one'),makeSlide('two')]},
    {...structuredClone(base),id:'snapshot',count:4,slide_format:'1:1',slides:[makeSlide('old')],generation_settings:{project:{...base,count:3,slide_format:'4:3',canvas_mode:'fixed'}}},
    {...structuredClone(base),id:'classic',engine:'classic',slides:[]}];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',dialog=>dialog.accept());
  await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    try{
      assert.equal(url.origin,origin,'Only mocked local requests');
      if(url.pathname.startsWith('/api/')){
        if(method!=='GET')assert.equal(request.headers()['x-h3-slides'],'1');
        const match=url.pathname.match(/^\/api\/projects\/([^/]+)(.*)$/);
        if(match){const project=projects.find(p=>p.id===match[1]);assert(project);const tail=match[2];
          if(!tail){if(method==='PATCH'){patches.push({id:project.id,...request.postDataJSON()});Object.assign(project,request.postDataJSON())}return route.fulfill({json:project})}
          if(tail==='/generate'){
            const body=request.postDataJSON();generations.push(body);assert.equal(body.new_version,true);
            const created={...structuredClone(project),...body.project_settings,id:project.id+'-new',version_number:2};projects.push(created);
            return route.fulfill({json:{id:'fixture-job',project_id:created.id,status:'completed',progress:1,events:[]}});
          }
          if(tail.startsWith('/export/')){exports.push(tail);return route.fulfill({status:400,json:{error:'Unexpected export request'}})}
          throw Error('Unexpected project mutation '+tail);
        }
        const data={'/api/projects':projects.map(p=>({...p,slide_count:p.slides.length})), '/api/jobs':[], '/api/documents':[], '/api/themes':[], '/api/library':{folders:[],order:[],assignments:{}},
          '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'}, '/api/models':{models:[{id:'mock',name:'Modello simulato',size_gb:1,vision:true}],default_model:'mock',runtime_available:true,status:{running:false}}};
        assert(Object.hasOwn(data,url.pathname),url.pathname);return route.fulfill({json:data[url.pathname]});
      }
      const file=resolve(root,['/','/create','/editor','/new'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));assert(file.startsWith(root.endsWith(sep)?root:root+sep));
      return route.fulfill({body:await readFile(file),contentType:{'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream'});
    }catch(error){errors.push(error.message);return route.fulfill({status:500,json:{error:error.message}})}
  });
  const noOverflow=async label=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),label+' '+viewport.width);
  async function saveBrief(){const response=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/api/projects/'));await page.locator('#save-project').click();await response}
  await page.goto(origin+'/create?project=legacy');await page.waitForFunction(()=>document.querySelector('#title').value==='Formati V2'&&document.querySelector('#save-status').textContent==='Salvato sul PC');
  assert.equal(await page.locator('#slide-format').inputValue(),'16:9');assert.equal(await page.locator('#slide-format').isDisabled(),false);
  assert.match(await page.locator('#slide-count-help').innerText(),/fino a 2 slide/);assert.match(await page.locator('#slide-format-help').innerText(),/15%/);
  assert.match(await page.locator('#canvas-mode option[value=adaptive]').textContent(),/massimo \+15%/);
  await page.locator('#slide-format').selectOption('4:3');await saveBrief();assert.equal(patches.at(-1).slide_format,'4:3');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('h3slides-settings'))['slide-format']),'4:3');
  await page.reload();await page.waitForFunction(()=>document.querySelector('#slide-format').value==='4:3');
  await page.locator('#creation-engine').selectOption('classic');assert.equal(await page.locator('#slide-format').inputValue(),'16:9');assert.equal(await page.locator('#slide-format').isDisabled(),true);
  assert.match(await page.locator('#toast').innerText(),/Classico.*16:9/);await saveBrief();assert.equal(patches.at(-1).slide_format,'16:9');
  await page.locator('#creation-engine').selectOption('v2');await page.locator('#slide-format').selectOption('16:10');await saveBrief();await noOverflow('Brief format controls');
  await page.locator('#setup-back').click();await page.locator('.page-v2').first().waitFor();await page.locator('#editor-menu>summary').click();
  assert.equal(await page.locator('#editor-slide-format').inputValue(),'16:10');
  for(const format of ['4:3','1:1']){
    const response=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/api/projects/'));
    await page.locator('#editor-slide-format').selectOption(format);await response;
    assert.equal(patches.at(-1).slide_format,format);assert.equal(projects[0].slide_format,format);assert.equal(projects[0].slides[0].content.page.nodes[1].text,'Il formato rimane uniforme.');
  }
  const modeResponse=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/api/projects/'));await page.locator('#editor-canvas-mode').selectOption('fixed');await modeResponse;
  assert.equal(projects[0].canvas_mode,'fixed');assert.equal(projects[0].slide_format,'1:1');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('h3slides-settings'))['slide-format']),'1:1');
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('h3slides-settings'))['canvas-mode']),'fixed');
  await page.waitForFunction(()=>document.querySelector('#slide-navigator-status').textContent.includes('1:1'));
  assert.match(await page.locator('#slide-navigator-status').textContent(),/2 \/ 2 slide pronte.*obiettivo 2.*1:1/);
  await noOverflow('Editor format controls');

  await page.goto(origin+'/editor?project=snapshot');await page.locator('.page-v2').waitFor();await page.locator('#editor-menu>summary').click();await page.locator('#editor-settings').click();
  assert.equal(await page.locator('#slide-format').inputValue(),'4:3','Original request restores its format, not current 1:1');assert.equal(await page.locator('#canvas-mode').inputValue(),'fixed');assert.equal(await page.locator('#count').inputValue(),'3');
  await page.locator('#slide-format').selectOption('16:10');await page.locator('#generate-top').click();await page.waitForFunction(()=>document.querySelector('#editor-project-meta').textContent.includes('Versione 2'));
  assert.equal(generations.length,1);assert.equal(generations[0].project_settings.slide_format,'16:10');assert.equal(generations[0].project_settings.canvas_mode,'fixed');assert.equal(generations[0].count,3);
  projects[1].generation_settings.project.slide_format=undefined;
  await page.goto(origin+'/editor?project=snapshot');await page.locator('.page-v2').waitFor();await page.locator('#editor-menu>summary').click();await page.locator('#editor-settings').click();
  assert.equal(await page.locator('#slide-format').inputValue(),'16:9','Legacy original request defaults to 16:9, not current 1:1');

  projects[0].slide_format='16:9';projects[0].canvas_mode='adaptive';projects[0].count=1;
  projects[0].slides[0].content.page.nodes=Array.from({length:20},(_,i)=>({id:'long-'+i,parent:'root',kind:'text',text:('Testo da ridurre o distribuire in altre slide. ').repeat(40),style:{font_size:28}}));
  await page.goto(origin+'/editor?project=legacy');await page.locator('#slide-one .v2-format-warning').waitFor({state:'visible'});
  assert.match(await page.locator('#slide-one .v2-format-warning').innerText(),/non entra nel formato 16:9/);
  assert.equal(await page.locator('#slide-one [data-page-node]').count(),20,'Incompatible content is preserved');
  assert.equal(await page.locator('#slide-one .v2-format-warning [data-action=regenerate]').count(),1);
  const bounds=await page.locator('#slide-one').evaluate(card=>{const frame=card.querySelector('.page-v2'),preview=card.querySelector('.slide-preview'),scale=preview.clientWidth/1280;return {height:frame.offsetHeight,max:Number(frame.dataset.pageMaxHeight),needed:Number(frame.dataset.neededHeight),previewHeight:preview.offsetHeight,scale,overflow:getComputedStyle(preview).overflow,nextTop:card.nextElementSibling.getBoundingClientRect().top,cardBottom:card.getBoundingClientRect().bottom}});
  assert(bounds.height<=bounds.max+1);assert(bounds.needed>bounds.max);assert(bounds.previewHeight>=bounds.needed*bounds.scale-2);assert.equal(bounds.overflow,'visible');assert(bounds.nextTop>=bounds.cardBottom);
  await page.locator('#editor-menu>summary').click();await page.locator('[data-export="pdf"]').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('supera il formato'));
  assert.equal(exports.length,0,'UI refuses an export that would clip incompatible pages');
  assert.match(await page.locator('#slide-count').textContent(),/2 slide.*obiettivo 1/);
  await noOverflow('Incompatible content warning');
  await page.goto(origin+'/create?project=classic');await page.waitForFunction(()=>document.querySelector('#creation-engine').value==='classic');assert.equal(await page.locator('#slide-format').isDisabled(),true);assert.match(await page.locator('#slide-format-help').textContent(),/Classico.*16:9/);
  assert.deepEqual(errors,[]);console.log('Slide format '+viewport.width+': legacy, brief/editor, preferences, snapshots/new version, classic guard, overflow warning/export gate passed');await page.close();
}}finally{await browser.close()}
