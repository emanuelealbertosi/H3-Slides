import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';
const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const browser=await chromium.launch({headless:true});
try{for(const viewport of [{width:1500,height:1000},{width:390,height:844}]){
  const page=await browser.newPage({viewport});page.setDefaultTimeout(15000);
  const errors=[],generations=[];let sequence=0,job=null,library={folders:[{id:'folder',name:'Lezioni'}],order:[],assignments:{saved:'folder'}};
  const source={id:'source-original',library_id:'document-one',name:'Appunti precedenti.md',kind:'text',images:[],warnings:[]};
  const old={id:'saved',title:'Una creazione conservata',prompt:'Una storia',count:2,theme:'paper',font:'Arial',engine:'v2',canvas_mode:'adaptive',sources:[source],slides:[],updated_at:new Date().toISOString()};
  const projects=[old],documents=[{library_id:'document-one',project_id:'saved',source_id:'source-original',project_title:old.title,name:source.name,kind:'text',viewable:true}];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',dialog=>dialog.accept());
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),method=req.method();
    try{
      assert.equal(url.origin,origin,'No actual external service');
      if(url.pathname.startsWith('/api/')){
        if(method!=='GET')assert.equal(req.headers()['x-h3-slides'],'1');
        if(url.pathname==='/api/projects'&&method==='POST'){
          const p={...req.postDataJSON(),id:'new-'+(++sequence),sources:[],slides:[],revision:1,updated_at:new Date().toISOString()};projects.push(p);return route.fulfill({json:p});
        }
        if(url.pathname==='/api/library'&&method==='POST'){library=req.postDataJSON();return route.fulfill({json:library})}
        const match=url.pathname.match(/^\/api\/projects\/([^/]+)(.*)$/);
        if(match){const p=projects.find(p=>p.id===match[1]);assert(p,'Known project');const tail=match[2];
          if(!tail){if(method==='PATCH')Object.assign(p,req.postDataJSON());return route.fulfill({json:p})}
          if(tail==='/sources'){
            assert.match(req.headers()['content-type'],/multipart\/form-data/);
            await new Promise(r=>setTimeout(r,100));
            p.sources.push({...source,id:'uploaded-'+p.sources.length,library_id:'uploaded-'+p.id,name:'Contenuto caricato.md'});return route.fulfill({json:p});
          }
          if(tail==='/sources/reuse'){p.sources.push({...source,id:'reused'});return route.fulfill({json:p})}
          if(tail==='/sources/url'){
            const {url:source_url}=req.postDataJSON();
            if(source_url.includes('invalid'))return route.fulfill({status:400,json:{error:'Pagina non raggiungibile'}});
            p.sources.push({...source,id:'url-'+p.id,library_id:'url-'+p.id,name:'Una pagina pubblica',source_url,kind:'url'});return route.fulfill({json:p});
          }
          if(tail.startsWith('/sources/')&&method==='DELETE'){p.sources=p.sources.filter(s=>s.id!==tail.split('/').at(-1));return route.fulfill({json:p})}
          if(tail==='/generate'){
            const payload=req.postDataJSON();generations.push(payload);let target=p;
            if(payload.new_version){target={...structuredClone(p),...payload.project_settings,id:p.id+'-v2',version_number:2};projects.push(target)}
            target.generation_settings={project:structuredClone({...target,slides:undefined,sources:undefined})};
            job={id:'job-'+generations.length,project_id:target.id,status:'running',progress:.1,events:[{at:Date.now()/1000,message:'Progettazione pagina in streaming'}]};
            target.slides=[{id:'live',status:'generating',revision:1,content:{title:'Slide live',layout:'content',blocks:[],bullets:[],diagram:{kind:'none'},notes:'',sources:[]},page_draft:{style:{},nodes:[{id:'h',kind:'heading',parent:'root',text:'Inizio della presentazione',style:{}}]}}];
            return route.fulfill({json:job});
          }
          throw Error('Unhandled API '+url.pathname);
        }
        const data={'/api/projects':projects.map(p=>({...p,slide_count:p.slides.length})), '/api/documents':documents,'/api/jobs':job?[job]:[],
          '/api/library':library,'/api/themes':[],
          '/api/models':{models:[{id:'mock',name:'Modello di prova',size_gb:1,vision:true}],default_model:'mock',runtime_available:true,status:{running:false}},
          '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'}};
        assert(Object.hasOwn(data,url.pathname),'Handled API '+url.pathname);return route.fulfill({json:data[url.pathname]});
      }
      const file=resolve(root,['/','/new','/import','/brief','/create','/editor','/library'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));assert(file.startsWith(root.endsWith(sep)?root:root+sep));
      return route.fulfill({body:await readFile(file),contentType:{'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream'});
    }catch(e){errors.push(e.message);return route.fulfill({status:500,json:{error:e.message}})}
  });
  await page.addInitScript(()=>localStorage.setItem('h3slides-project','saved'));
  await page.goto(origin+'/');await page.locator('[data-open-project="saved"]').waitFor();
  assert.equal(await page.locator('body').getAttribute('data-view'),'library','Root opens Home, not old project');
  assert.equal(await page.locator('#floating-generation').isVisible(),false);
  async function noOverflow(where){const sizes=await page.evaluate(()=>[innerWidth,document.documentElement.scrollWidth]);if(sizes[1]>sizes[0]+1)console.log(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().width,e.getBoundingClientRect().right])));assert(sizes[1]<=sizes[0]+1,where+': '+sizes)}
  await noOverflow('Home');
  await page.locator('#home-search').fill('inesistente');assert.equal(await page.locator('[data-open-project]').count(),0);
  await page.locator('#home-search').fill('conservata');assert.equal(await page.locator('[data-open-project]').count(),1);await page.locator('#home-search').fill('');
  await page.locator('[data-home-layout="list"]').click();assert.equal(await page.locator('#library').getAttribute('data-home-layout'),'list');await noOverflow('Home list');
  await page.locator('[data-home-layout="grid"]').click();
  await page.locator('#home-folder-links [data-home-folder="folder"]').click();assert.equal(await page.locator('[data-open-project="saved"]').count(),1);
  await page.locator('#home-folder-links [data-home-folder="all"]').click();
  if(viewport.width>800){const moved=page.waitForResponse(r=>r.url().endsWith('/api/library')&&r.request().method()==='POST');await page.locator('[data-project="saved"]').dragTo(page.locator('#home-folder-links [data-folder-id=""]'));await moved;assert.equal(library.assignments.saved,undefined,'Sidebar drop persists folder change')}
  await page.locator('#open-create').click();await page.locator('#creation-start').waitFor({state:'visible'});
  assert.equal(await page.locator('[data-start-method]').count(),4);await noOverflow('Choice');
  await page.locator('[data-start-method="import"]').click();await page.locator('#import-page').waitFor({state:'visible'});
  await page.locator('[data-reuse-source="source-original"]').waitFor();
  await page.locator('#files').setInputFiles({name:'Lezione.md',mimeType:'text/markdown',buffer:Buffer.from('Un testo da trasformare in slide.')});
  await page.waitForFunction(()=>!document.querySelector('#import-continue').disabled&&document.querySelector('#sources').textContent.includes('Contenuto caricato'));
  assert.match(new URL(page.url()).search,/project=new-1/,'Upload can be recovered after reload');
  await page.locator('[data-reuse-source="source-original"]').click();await page.waitForFunction(()=>document.querySelectorAll('#sources .source').length===2);
  await noOverflow('Import');
  await page.reload();await page.locator('#import-page').waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelectorAll('#sources .source').length===2);
  await page.locator('#import-continue').click();await page.waitForFunction(()=>document.body.dataset.view==='create');
  await page.locator('#prompt').fill('Spiega i concetti in italiano con esempi, usando le fonti.');await page.locator('#count').fill('20');
  await page.locator('#title').fill('Una lezione accurata');await page.locator('#save-project').click();await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Salvato sul PC');
  assert.equal(projects[1].count,20);assert.match(projects[1].prompt,/fonti/);assert.equal(projects[1].engine,'v2');
  await noOverflow('Brief');
  const checkboxState=()=>page.locator('.settings input[type=checkbox]').evaluateAll(inputs=>inputs.map(el=>[el.id,el.checked,el.disabled]));
  const selectedOptions=await checkboxState();
  const panelStates=await page.locator('.brief-column details').evaluateAll(panels=>panels.map(el=>{const opened=el.open;el.open=true;return opened}));
  await noOverflow('Brief with all option panels open');
  const readability=await page.locator('.settings').evaluate(root=>{
    const visible=el=>el.getClientRects().length&&el.getBoundingClientRect().width>0&&el.getBoundingClientRect().height>0;
    const elements=selector=>[...root.querySelectorAll(selector)].filter(visible);
    const size=el=>parseFloat(getComputedStyle(el).fontSize),identify=el=>el.id||el.textContent.trim().slice(0,60);
    const rgb=value=>(value.match(/[\d.]+/g)||[]).slice(0,3).map(Number);
    const luminance=color=>rgb(color).map(n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4}).reduce((sum,n,i)=>sum+n*[.2126,.7152,.0722][i],0);
    const contrast=el=>{
      let background='#ffffff';for(let ancestor=el;ancestor;ancestor=ancestor.parentElement){const color=getComputedStyle(ancestor).backgroundColor;if(color.startsWith('rgb(')){background=color;break}}
      const a=luminance(getComputedStyle(el).color),b=luminance(background);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    };
    const labels=elements('.brief-column label'),descriptions=elements('.brief-column small,.brief-column .hint,.brief-column .flow-description,.brief-save-note'),summaries=elements('.brief-column summary');
    const fields=elements('.brief-column input:not([type=checkbox]):not([type=radio]):not([type=hidden]),.brief-column select,.brief-column textarea');
    return {
      labels:labels.filter(el=>size(el)<16).map(identify),descriptions:descriptions.filter(el=>size(el)<14).map(identify),
      fields:fields.filter(el=>size(el)<18||el.getBoundingClientRect().height<44).map(identify),
      summaries:summaries.filter(el=>size(el)<17||el.getBoundingClientRect().height<44).map(identify),
      headings:elements('.brief-column h2').filter(el=>size(el)<20||size(el)>24).map(identify),
      checkboxes:elements('.brief-column input[type=checkbox]').filter(el=>{const r=el.getBoundingClientRect();return r.width<20||r.height<20||el.closest('label').getBoundingClientRect().height<44}).map(identify),
      contrast:[...labels,...descriptions,...summaries,...fields].filter(el=>contrast(el)<4.5).map(el=>[identify(el),contrast(el)]),
      options:[...root.querySelectorAll('.brief-column select option')].filter(el=>size(el)<18).map(identify),
      minimums:{label:Math.min(...labels.map(size)),description:Math.min(...descriptions.map(size)),field:Math.min(...fields.map(size)),summary:Math.min(...summaries.map(size))}
    };
  });
  for(const [category,failures]of Object.entries(readability))if(category!=='minimums')assert.deepEqual(failures,[],category+' readability at '+viewport.width);
  assert.match(await page.locator('label:has(#manim-diagrams)').innerText(),/Diagrammi Manim automatici/);
  assert.match(await page.locator('#manim-diagrams-help').innerText(),/anche senza citarli nel prompt/);
  assert.match(await page.locator('#manim-diagrams-help').innerText(),/Se disattivo, la generazione non crea diagrammi Manim/);
  assert.deepEqual(await checkboxState(),selectedOptions,'Readable controls preserve selected preferences');
  await page.locator('.brief-column details').evaluateAll((panels,states)=>panels.forEach((el,i)=>{el.open=states[i]}),panelStates);
  console.log('Brief readability '+viewport.width+': '+JSON.stringify(readability.minimums)+', contrast >= 4.5 and no horizontal overflow');
  await page.locator('#open-create').click();await page.locator('[data-start-method="paste"]').click();
  await page.locator('#paste-content').fill('Testo incollato con una scaletta\n1. Inizio\n2. Sviluppo');
  await page.locator('#import-paste-submit').click();await page.waitForFunction(()=>!document.querySelector('#import-continue').disabled);
  assert.equal(projects[2].sources.length,1);
  await page.locator('[data-import-mode="url"]').click();await page.locator('#import-url').fill('https://invalid.example/page');await page.locator('#import-url-submit').click();
  await page.locator('#import-error').waitFor({state:'visible'});assert.match(await page.locator('#import-error').textContent(),/non raggiungibile/);
  await page.locator('#import-url').fill('https://public.example/page');await page.locator('#import-url-submit').click();
  await page.waitForFunction(()=>document.querySelectorAll('#sources .source').length===2&&!document.querySelector('#import-continue').disabled);
  await page.locator('#import-continue').click();await page.locator('#prompt').fill('Crea una spiegazione del contenuto');
  await page.locator('#generate-top').click();await page.waitForFunction(()=>document.body.dataset.view==='editor');
  await page.locator('.page-v2').waitFor();assert.equal(generations.length,1);assert.equal(generations[0].provider.mode,'local');
  assert.match(await page.locator('#slide-navigator-list').textContent(),/Slide live/);assert.equal(await page.locator('#job-panel').isVisible(),true);
  assert.equal(await page.locator('.settings').isVisible(),false,'Creation opens editor, not settings');await noOverflow('Editor');
  const original=projects[2],originalBrief=structuredClone(original.generation_settings.project);
  original.slides[0].content.page=original.slides[0].page_draft;delete original.slides[0].page_draft;original.slides[0].status='ready';job.status='completed';job.progress=1;
  original.prompt='Metadati modificati dopo la creazione';
  await page.waitForFunction(()=>document.querySelector('#job-percent').textContent.includes('completed'));
  await page.locator('#editor-menu>summary').click();await page.locator('#editor-settings').click();
  assert.equal(await page.locator('#prompt').inputValue(),originalBrief.prompt,'Original generation request restored');
  await page.locator('#prompt').fill('Nuovo prompt per una versione indipendente');await page.locator('#count').fill('12');
  await page.locator('#generate-top').click();await page.waitForFunction(()=>new URLSearchParams(location.search).get('project')?.endsWith('-v2'));
  assert.equal(generations.at(-1).new_version,true);assert.equal(generations.at(-1).project_settings.count,12);
  assert.equal(original.prompt,'Metadati modificati dopo la creazione','New version leaves source untouched');
  assert.equal(original.slides[0].status,'ready');assert.equal(projects.at(-1).sources.length,2);
  assert.deepEqual(errors,[]);await page.close();
  console.log('Creation flow '+viewport.width+': Home → choice → upload/history/reuse → briefing → live V2, reload and link errors passed');
}}finally{await browser.close()}
