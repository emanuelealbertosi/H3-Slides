import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// All API calls and generation outcomes are in memory. No server, LLM or user data.
const staticRoot=fileURLToPath(new URL('../static/',import.meta.url));
const origin='http://127.0.0.1:9876';
const browser=await chromium.launch({headless:true});
const baseContent=title=>({title,subtitle:'',layout:'content',bullets:[],
  blocks:[{kind:'explanation',heading:'Contenuto conservato',text:'Questo testo è già stato salvato e non deve essere rigenerato.',source:''}],
  diagram:{kind:'none'},sources:[],notes:''});
const slide=(id,status='ready')=>({id,status,revision:status==='ready'?3:0,content:baseContent(id)});
const project=(id,title,slides=[])=>({id,title,prompt:'Spiega il ciclo dell’acqua con esempi semplici.',
  count:3,theme:'paper',template:'auto',text_density:'detailed',canvas_mode:'adaptive',graphic_style:'studio',
  slides,sources:[],visual_assets:[],web_enabled:false,use_source_images:true,use_web_images:false,
  use_openverse_images:false,use_manim_diagrams:false,updated_at:Date.now()/1000});

async function testViewport(viewport){
  const page=await browser.newPage({viewport});page.setDefaultTimeout(15000);
  const errors=[],generated=[],mutations=[],confirmations=[];
  const projects=[project('failed-empty','Fallito prima della scaletta'),
    project('failed-partial','Presentazione parziale',[slide('pronta-1'),slide('pronta-2'),slide('da-completare','pending')]),
    project('interrupted-empty','Interrotto dal riavvio'),project('cancelled-empty','Annullato conservato'),
    project('failed-version','Versione fallita prima della nuova scaletta',[slide('copiata-1'),slide('copiata-2')]),
    project('completed','Presentazione completata',[slide('completa-1'),slide('completa-2')])];
  const readyBefore=structuredClone(projects[1].slides.slice(0,2));
  const makeJob=(pid,status,error,sequence=1)=>({id:pid+'-job-'+sequence,project_id:pid,status,
    progress:status==='completed'?1:pid==='failed-partial'?.67:0,error:error||null,
    events:[{at:Date.now()/1000,message:error||'Generazione completata'}],created_at:Date.now()/1000+sequence});
  let jobs=[makeJob('failed-empty','failed','Errore simulato: documento non ancora elaborato'),
    makeJob('failed-partial','failed','Errore simulato: terza slide interrotta'),
    makeJob('interrupted-empty','interrupted','App riavviata: il progetto è conservato'),
    makeJob('cancelled-empty','cancelled','Generazione annullata dal test'),
    makeJob('failed-version','failed','Errore simulato: nuova scaletta non ancora creata'),
    makeJob('completed','completed')];
  const model={id:'mock',name:'Modello simulato',size_gb:1,vision:true};
  page.on('pageerror',error=>errors.push(error.message));
  page.on('dialog',async dialog=>{confirmations.push(dialog.message());await dialog.accept()});
  const waitJob=async(pid,status)=>{
    await page.waitForFunction(({pid,status})=>new URLSearchParams(location.search).get('project')===pid&&
      document.querySelector('#job-percent').textContent.endsWith(status),{pid,status});
    await page.locator('#job-panel').waitFor({state:'visible'});
    assert.equal(await page.locator('#job-panel').isVisible(),true,'Current job and log remain visible');
  };
  const openRecovery=async()=>{
    const recovery=page.locator('#recovery-projects');await recovery.waitFor({state:'visible'});
    if(!await recovery.evaluate(element=>element.open))await recovery.locator('summary').click();
    return recovery;
  };
  const noOverflow=async where=>{
    const sizes=await page.evaluate(()=>({width:innerWidth,html:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
    assert.ok(sizes.html<=sizes.width+1&&sizes.body<=sizes.width+1,
      where+' has no horizontal overflow: '+JSON.stringify(sizes));
  };
  const submit=async()=>{
    const response=page.waitForResponse(response=>response.url().endsWith('/generate')&&response.request().method()==='POST');
    await page.locator('#generate-top').click();await response;
    await page.waitForFunction(()=>!document.querySelector('#generate-top').disabled);
    return generated.at(-1);
  };
  try{
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url()),method=route.request().method();
      try{
        assert.equal(url.origin,origin,'This test must never send external requests');
        if(url.pathname.startsWith('/api/')){
          const generation=url.pathname.match(/^\/api\/projects\/([^/]+)\/generate$/);
          if(generation&&method==='POST'){
            const payload=route.request().postDataJSON(),original=projects.find(p=>p.id===generation[1]);
            assert.ok(original,'Generation targets an existing fixture');
            generated.push({project_id:original.id,payload:structuredClone(payload)});
            let target=original;
            if(payload.new_version){
              target={...structuredClone(original),...payload.project_settings,id:original.id+'-v2',title:original.title+' (v2)'};
              projects.push(target);
            }
            if(!target.slides.length)target.slides=[slide(target.id+'-new')];
            else for(const item of target.slides){
              if(payload.regenerate_all||item.status!=='ready'){
                item.content=baseContent('Completata nel test');item.status='ready';item.revision++;
              }
            }
            const result=makeJob(target.id,'completed',null,generated.length+1);jobs.unshift(result);
            return route.fulfill({json:result});
          }
          const detail=url.pathname.match(/^\/api\/projects\/([^/]+)$/);
          if(detail){
            const selected=projects.find(p=>p.id===detail[1]);assert.ok(selected,'Known project');
            if(method==='PATCH'){
              mutations.push({project_id:selected.id,payload:route.request().postDataJSON()});
              Object.assign(selected,route.request().postDataJSON());
            }else assert.equal(method,'GET','Only project metadata PATCH is allowed');
            return route.fulfill({json:selected});
          }
          assert.equal(method,'GET','Unexpected mutation '+url.pathname);
          const responses={
            '/api/projects':projects.map(p=>({...p,slide_count:p.slides.length,ready_count:p.slides.filter(s=>s.status==='ready').length})),
            '/api/jobs':jobs,'/api/models':{models:[model],default_model:'mock',runtime_available:true,status:{running:false}},
            '/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},
            '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
            '/api/admin/llm':{models:[model],profiles:{},status:{running:false},loading_schema:{properties:{}},inference_schema:{properties:{}}},
          };
          assert.ok(Object.hasOwn(responses,url.pathname),'Unexpected API '+url.pathname);
          return route.fulfill({json:responses[url.pathname]});
        }
        const file=resolve(staticRoot,['/','/create','/editor','/library'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));
        assert.ok(file.startsWith(staticRoot.endsWith(sep)?staticRoot:staticRoot+sep),'Static paths stay inside the fixture');
        const contentType={'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css',
          '.json':'application/json','.woff2':'font/woff2','.ttf':'font/ttf'}[extname(file)]||'application/octet-stream';
        return route.fulfill({body:await readFile(file),contentType});
      }catch(error){errors.push(error.message);return route.fulfill({status:500,json:{error:error.message}})}
    });
    await page.goto(origin+'/create?project=failed-empty');
    await waitJob('failed-empty','failed');
    assert.equal(await page.locator('body').getAttribute('data-view'),'create');
    assert.match(await page.locator('#job-status').textContent(),/documento non ancora elaborato/);
    assert.match(await page.locator('#events').textContent(),/documento non ancora elaborato/);
    assert.match(await page.locator('#generate-top').textContent(),/Riprova generazione/);
    const metrics=await page.evaluate(()=>({
      hint:parseFloat(getComputedStyle(document.querySelector('.generation-actions .hint')).fontSize),
      labels:[...document.querySelectorAll('.settings label')].map(element=>parseFloat(getComputedStyle(element).fontSize)),
      controls:[...document.querySelectorAll('.settings input:not([type=hidden]),.settings select,.settings textarea')]
        .map(element=>parseFloat(getComputedStyle(element).fontSize)),
    }));
    assert.ok(metrics.hint>=15,'Generation instructions are at least 15px');
    assert.ok(metrics.labels.every(value=>value>=14),'Settings labels are at least 14px');
    assert.ok(metrics.controls.every(value=>value>=16),'Settings inputs are at least 16px');
    await noOverflow('Empty failed project');
    const recovery=await openRecovery();
    for(const id of ['failed-empty','failed-partial','interrupted-empty','cancelled-empty','failed-version'])
      assert.equal(await recovery.locator('[data-recover-project="'+id+'"]').isVisible(),true,id+' can be recovered from Crea');

    // The archive must not hide failed/empty projects or label them as completed decks.
    await page.locator('#open-library').click();await page.locator('#library').waitFor({state:'visible'});
    for(const id of ['failed-empty','failed-partial','interrupted-empty','cancelled-empty','failed-version'])
      assert.match(await page.locator('[data-open-project="'+id+'"]').textContent(),/Recupera progetto/);
    assert.doesNotMatch(await page.locator('[data-open-project="completed"]').textContent(),/Recupera/);
    await noOverflow('Project archive');
    await page.locator('[data-open-project="failed-empty"]').click();await waitJob('failed-empty','failed');
    const retried=await submit();
    assert.equal(retried.project_id,'failed-empty');
    for(const flag of ['regenerate_all','rebuild_outline','new_version'])assert.equal(retried.payload[flag],false,'Retry does not '+flag);
    assert.equal(retried.payload.slide_id,null);
    assert.equal(projects.filter(p=>p.id.startsWith('failed-empty')).length,1,'Retry creates no extra version');
    await waitJob('failed-empty','completed');

    // Starting a new project must immediately stop showing a previous project's job.
    await page.locator('#open-create').click();
    await page.waitForFunction(()=>!new URLSearchParams(location.search).has('project'));
    assert.equal(await page.locator('#job-panel').isVisible(),false,'New project does not expose stale job logs');
    const pendingRecovery=await openRecovery();
    await pendingRecovery.locator('[data-recover-project="interrupted-empty"]').click();
    await waitJob('interrupted-empty','interrupted');
    assert.match(await page.locator('#job-status').textContent(),/App riavviata/);
    assert.doesNotMatch(await page.locator('#job-status').textContent(),/documento non ancora elaborato/);
    assert.match(await page.locator('#generate-top').textContent(),/Riprova generazione/);
    await page.locator('#project-list').selectOption('cancelled-empty');await waitJob('cancelled-empty','cancelled');
    assert.match(await page.locator('#job-status').textContent(),/annullata dal test/);
    assert.doesNotMatch(await page.locator('#job-status').textContent(),/App riavviata/);

    // Continue an existing outline, retaining every byte and revision of its ready slides.
    await page.goto(origin+'/create?project=failed-partial');await waitJob('failed-partial','failed');
    assert.match(await page.locator('#generate-top').textContent(),/Riprendi generazione/);
    const resumed=await submit();assert.equal(resumed.project_id,'failed-partial');
    for(const flag of ['regenerate_all','rebuild_outline','new_version'])assert.equal(resumed.payload[flag],false,'Resume does not '+flag);
    assert.equal(resumed.payload.slide_id,null);
    assert.deepEqual(projects.find(p=>p.id==='failed-partial').slides.slice(0,2),readyBefore,'Ready content and revisions remain unchanged');
    assert.equal(projects.find(p=>p.id==='failed-partial').slides[2].status,'ready');
    assert.equal(projects.filter(p=>p.id.startsWith('failed-partial')).length,1,'Resume uses the same project');
    await waitJob('failed-partial','completed');await noOverflow('Recovered editor');

    // A failed new version may still contain inherited ready slides: retry that version,
    // explicitly rebuilding its outline instead of accidentally creating v3.
    await page.goto(origin+'/create?project=failed-version');await waitJob('failed-version','failed');
    assert.match(await page.locator('#generate-top').textContent(),/Riprova generazione/);
    const retryVersion=await submit();assert.equal(retryVersion.project_id,'failed-version');
    assert.equal(retryVersion.payload.regenerate_all,true);
    assert.equal(retryVersion.payload.rebuild_outline,true);
    assert.equal(retryVersion.payload.new_version,false);
    assert.equal(projects.filter(p=>p.id.startsWith('failed-version')).length,1,'An unsuccessful version is retried in place');

    // Completed projects still use the deliberate new-version workflow.
    await page.goto(origin+'/create?project=completed');await waitJob('completed','completed');
    assert.match(await page.locator('#generate-top').textContent(),/Rigenera presentazione/);
    const completeBefore=structuredClone(projects.find(p=>p.id==='completed'));
    const regenerated=await submit();assert.equal(regenerated.project_id,'completed');
    for(const flag of ['regenerate_all','rebuild_outline','new_version'])assert.equal(regenerated.payload[flag],true,'Full regeneration keeps '+flag);
    assert.deepEqual(projects.find(p=>p.id==='completed'),completeBefore,'The previous complete version is retained');
    assert.equal(projects.filter(p=>p.id==='completed-v2').length,1);
    assert.equal(confirmations.length,2,'Retrying inherited ready slides and creating a new version require explicit confirmation');
    assert.equal(generated.length,4,'Each explicit click sends exactly one generation request');
    assert.deepEqual(mutations,[],'Opening and recovering saved projects does not silently PATCH settings');

    // A running job is recoverable from the home page even before the first slide exists.
    const activeProject=project('active-empty','Generazione in corso senza slide');projects.push(activeProject);
    const activeJob=makeJob(activeProject.id,'running',null,20);
    activeJob.progress=.42;activeJob.events=[...Array.from({length:60},(_,i)=>({at:Date.now()/1000,message:'Evento precedente '+i})),
      {at:Date.now()/1000,message:'Preparazione delle fonti in corso'}];
    jobs.unshift(activeJob);
    await page.evaluate(()=>localStorage.removeItem('h3slides-project'));
    await page.goto(origin+'/create');
    const activeBanner=page.locator('#active-generation-home');await activeBanner.waitFor({state:'visible'});
    const activeLink=page.locator('#active-generation-list [data-open-active-project="active-empty"]');
    await activeLink.waitFor({state:'visible'});
    assert.equal(await page.locator('body').getAttribute('data-view'),'create');
    assert.equal(new URL(page.url()).searchParams.has('project'),false,'The active-job link is available with no current project');
    assert.equal(await activeLink.getAttribute('href'),'/editor?project=active-empty','Active job has a directly reopenable editor URL');
    assert.match(await activeBanner.textContent(),/Generazione in corso senza slide/);
    assert.match(await activeBanner.textContent(),/42/);
    assert.match(await activeBanner.textContent(),/Preparazione delle fonti/);
    await noOverflow('Active generation home banner');
    const beforeOpening=generated.length;
    await activeLink.click();await waitJob('active-empty','running');
    assert.equal(await page.locator('body').getAttribute('data-view'),'editor','A zero-slide job opens the live editor, not settings');
    assert.equal(new URL(page.url()).pathname,'/editor');
    assert.match(await page.locator('#events').textContent(),/Preparazione delle fonti/);
    assert.equal(generated.length,beforeOpening,'Reopening a job never launches generation');
    const log=page.locator('#events');
    await log.evaluate(e=>{e.closest('details').open=true});
    const waitLogBottom=()=>page.waitForFunction(()=>{
      const e=document.querySelector('#events');return e.clientHeight>0&&e.scrollHeight>e.clientHeight&&e.scrollHeight-e.clientHeight-e.scrollTop<=1;
    });
    await waitLogBottom();
    activeJob.events.push({at:Date.now()/1000,message:'Nuova riga arrivata dal polling'});
    await page.waitForFunction(()=>document.querySelector('#events').textContent.includes('Nuova riga arrivata dal polling'));
    await waitLogBottom();
    await log.evaluate(e=>{e.scrollTop=0});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    activeJob.events.push({at:Date.now()/1000,message:'Aggiornamento durante lettura dello storico'});
    await page.waitForFunction(()=>document.querySelector('#events').textContent.includes('Aggiornamento durante lettura dello storico'));
    assert.equal(await log.evaluate(e=>e.scrollTop),0,'Polling does not interrupt manual history reading');

    // Opening the live log may scroll down and collapse the navigation; scroll up as a user would.
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.locator('#open-create').click();await activeBanner.waitFor({state:'visible'});
    assert.equal(await page.locator('#job-panel').isVisible(),false,'Home clears the editor selection but retains its active-job shortcut');
    await activeLink.waitFor({state:'visible'});
    activeJob.status='paused';activeJob.events.push({at:Date.now()/1000,message:'Generazione in pausa'});
    await page.waitForFunction(()=>document.querySelector('#active-generation-home').textContent.includes('Generazione in pausa'));
    assert.equal(await activeLink.isVisible(),true,'Paused jobs remain accessible from home');
    await activeLink.click();await waitJob('active-empty','paused');
    assert.equal(await page.locator('body').getAttribute('data-view'),'editor');
    assert.equal(generated.length,beforeOpening,'Opening a paused job does not resume it implicitly');
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.locator('#open-create').click();await activeBanner.waitFor({state:'visible'});
    activeJob.status='completed';activeJob.progress=1;
    activeJob.events.push({at:Date.now()/1000,message:'Generazione conclusa'});
    await activeBanner.waitFor({state:'hidden'});
    assert.equal(generated.length,beforeOpening,'Polling terminal status sends no generation request');
    // A completed text generation can still expose a truthful, actionable
    // missing-diagram warning. Opening it must not start a model request.
    const incomplete=projects.find(p=>p.id==='completed');
    incomplete.use_manim_diagrams=true;
    incomplete.slides[0].content.diagram={kind:'manim',brief:'Mappa concettuale',scene:null};
    incomplete.slides[0].diagram_error='Diagramma non completato: nessun riepilogo sostitutivo. Usa Progetta Manim per riprovare.';
    await page.goto(origin+'/editor?project=completed');
    await page.locator('.diagram-pending').waitFor({state:'visible'});
    assert.match(await page.locator('.diagram-pending').textContent(),/nessun riepilogo sostitutivo/);
    assert.ok(await page.getByRole('button',{name:'Progetta Manim',exact:true}).count());
    assert.equal(generated.length,beforeOpening);
    assert.deepEqual(errors,[]);
    console.log(`Project recovery UI ${viewport.width}x${viewport.height}: failed/interrupted archive, logs, retry, resume, versioning, active-job home links, typography and no overflow passed.`);
  }finally{await page.unrouteAll({behavior:'wait'});await page.close()}
}

try{for(const viewport of [{width:1440,height:1000},{width:390,height:844}])await testViewport(viewport)}
finally{await browser.close()}
