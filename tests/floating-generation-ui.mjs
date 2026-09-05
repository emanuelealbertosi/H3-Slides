import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

// Every request, including generation, is mocked. No server, LLM or real project data.
const staticRoot=fileURLToPath(new URL('../static/',import.meta.url));
const origin='http://127.0.0.1:9876';
const browser=await chromium.launch({headless:true});
const buttonIds=['generate-top','generate','generate-floating'];

async function testViewport(viewport){
  const page=await browser.newPage({viewport});
  page.setDefaultTimeout(10000);
  const errors=[],generated=[],confirmations=[];
  page.on('pageerror',error=>errors.push(error.message));
  const project={id:'floating-ui',title:'Generazione simulata',prompt:'Descrivi il ciclo dell’acqua',
    count:6,theme:'paper',slides:[],sources:[{id:'sample',name:'Testo mock.md',images:[],warnings:[]}],
    web_enabled:false,use_web_images:false,use_openverse_images:false,use_manim_diagrams:false};
  const model={id:'mock',name:'gemma test',size_gb:1,vision:true};
  let jobs=[],holdGeneration=false,releaseGeneration;
  const floating=page.locator('#generate-floating');
  const waitFloating=visible=>page.waitForFunction(expected=>{
    const wrapper=document.querySelector('#floating-generation');
    return wrapper&&wrapper.hidden===!expected;
  },visible);
  const fullyVisible=id=>page.evaluate(value=>{
    const element=document.getElementById(value),rect=element.getBoundingClientRect();
    return !element.closest('[hidden]')&&rect.width>0&&rect.height>0&&
      rect.top>=0&&rect.left>=0&&rect.bottom<=innerHeight&&rect.right<=innerWidth;
  },id);
  const scrollMiddle=async()=>{
    await page.evaluate(()=>window.scrollTo(0,(document.documentElement.scrollHeight-innerHeight)/2));
    await waitFloating(true);
    assert.equal(await fullyVisible('generate-top'),false,'Top inline action is outside the middle viewport');
    assert.equal(await fullyVisible('generate'),false,'Bottom inline action is outside the middle viewport');
  };
  const assertAccessibleFloating=async()=>{
    assert.equal(await floating.isVisible(),true);
    assert.equal(await floating.getAttribute('data-generate-presentation'),'');
    const rect=await floating.boundingBox();
    assert.ok(rect&&rect.width>=44&&rect.height>=44,'Floating action has a 44px minimum touch target');
    assert.ok(rect.x>=0&&rect.y>=0&&rect.x+rect.width<=viewport.width&&rect.y+rect.height<=viewport.height,
      'Floating action stays completely inside the viewport');
    assert.ok(rect.x+rect.width>viewport.width-80&&rect.y+rect.height>viewport.height-100,
      'Floating action is anchored near the bottom right');
    assert.equal(await floating.evaluate(element=>{
      const r=element.getBoundingClientRect();
      return element.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2));
    }),true,'Floating action receives pointer hits');
    await floating.click({trial:true});
    await floating.focus();
    assert.equal(await floating.evaluate(element=>element===document.activeElement),true,
      'Floating action remains keyboard focusable');
  };
  const assertButtons=async(disabled,label)=>{
    await page.waitForFunction(({ids,disabled,label})=>ids.every(id=>{
      const element=document.getElementById(id);
      return element.disabled===disabled&&(id!=='generate-floating'||element.textContent===label);
    }),{ids:buttonIds,disabled,label});
    assert.equal(await floating.textContent(),label);
  };
  try{
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url()),method=route.request().method();
      try{
        assert.equal(url.origin,origin,'No external network in this test');
        if(url.pathname.startsWith('/api/')){
          if(url.pathname==='/api/projects/floating-ui'&&method==='PATCH'){
            Object.assign(project,route.request().postDataJSON());
            return route.fulfill({json:project});
          }
          if(url.pathname==='/api/projects/floating-ui/generate'&&method==='POST'){
            generated.push(route.request().postDataJSON());
            if(holdGeneration)await new Promise(resolve=>{releaseGeneration=resolve});
            return route.fulfill({json:{id:'mock-job',project_id:project.id,status:'completed',progress:1,events:[]}});
          }
          assert.equal(method,'GET','Unexpected mutation '+url.pathname);
          const responses={
            '/api/projects':[{...project,slide_count:project.slides.length}],
            '/api/projects/floating-ui':project,
            '/api/models':{models:[model],default_model:'mock',runtime_available:true,status:{running:false}},
            '/api/jobs':jobs,'/api/documents':[],'/api/themes':[],
            '/api/library':{folders:[],order:[],assignments:{}},
            '/api/admin/search':{searxng_url:'http://127.0.0.1:8080'},
            '/api/admin/llm':{models:[model],profiles:{},status:{running:false},
              loading_schema:{properties:{}},inference_schema:{properties:{}}},
          };
          assert.ok(Object.hasOwn(responses,url.pathname),'Unexpected API '+url.pathname);
          return route.fulfill({json:responses[url.pathname]});
        }
        const file=resolve(staticRoot,url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,''));
        assert.ok(file.startsWith(staticRoot.endsWith(sep)?staticRoot:staticRoot+sep));
        const contentType={'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript',
          '.css':'text/css','.json':'application/json','.woff2':'font/woff2','.ttf':'font/ttf'}[extname(file)]||'application/octet-stream';
        return route.fulfill({body:await readFile(file),contentType});
      }catch(error){
        errors.push(error.message);
        return route.fulfill({status:500,json:{error:error.message}});
      }
    });
    await page.addInitScript(()=>localStorage.setItem('h3slides-project','floating-ui'));
    await page.goto(origin+'/');
    await page.waitForFunction(()=>document.querySelector('#sources').textContent.includes('Testo mock.md')&&
      document.querySelector('#connection').textContent.includes('Locale'));
    await waitFloating(false);
    assert.equal(await fullyVisible('generate-top'),true,'Top inline action is fully visible on entry');
    await assertButtons(false,'Genera →');

    await scrollMiddle();
    await assertAccessibleFloating();
    await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));
    await waitFloating(false);
    assert.equal(await fullyVisible('generate'),true,'Bottom inline action replaces the floating action');

    // A partially visible inline button must not remove the fully usable action.
    await page.evaluate(()=>{
      const rect=document.querySelector('#generate').getBoundingClientRect();
      window.scrollTo(0,scrollY+rect.top-innerHeight+rect.height/2);
    });
    await waitFloating(true);
    assert.equal(await fullyVisible('generate'),false);
    await assertAccessibleFloating();

    for(const destination of ['library','admin']){
      await page.locator('#open-'+destination).click();
      await page.waitForFunction(id=>!document.getElementById(id).hidden,destination);
      await waitFloating(false);
      assert.equal(await floating.isVisible(),false,'Floating action is hidden on '+destination);
      await page.locator('#open-create').click();
      await scrollMiddle();
      await assertAccessibleFloating();
    }

    const prompt='Spiega evaporazione e condensazione con esempi semplici';
    await page.locator('#prompt').fill(prompt);
    await page.locator('#count').fill('8');
    await scrollMiddle();
    holdGeneration=true;
    const submission=page.waitForRequest(request=>request.url().endsWith('/generate')&&request.method()==='POST');
    await floating.click();await submission;
    await assertButtons(true,'Preparazione…');
    assert.equal(generated.length,1,'A floating click submits generation exactly once');
    assert.equal(generated[0].prompt,prompt);
    assert.equal(generated[0].count,8);
    assert.equal(generated[0].regenerate_all,false);
    assert.equal(generated[0].rebuild_outline,false);
    assert.equal(generated[0].slide_id,null);
    assert.equal(generated[0].diagram_only,false);
    assert.equal(generated[0].provider.model,'mock');
    assert.equal(project.prompt,prompt,'The same handler saves the current brief');
    assert.equal(project.count,8);
    await floating.evaluate(element=>{element.click();element.click()});
    assert.equal(generated.length,1,'Repeated activation while preparing cannot duplicate the POST');
    const completion=page.waitForResponse(response=>response.url().endsWith('/generate'));
    holdGeneration=false;releaseGeneration();releaseGeneration=undefined;
    await completion;await assertButtons(false,'Genera →');
    await waitFloating(true);
    assert.equal(await page.locator('#toast').isVisible(),true);
    const toastRect=await page.locator('#toast').boundingBox(),floatingRect=await floating.boundingBox();
    assert.ok(toastRect.y+toastRect.height<=floatingRect.y,'Generation toast sits above the floating action');

    project.slides=[{id:'mock-slide',status:'ready',revision:1,content:{title:'Il ciclo dell’acqua',
      subtitle:'Contenuto simulato',layout:'content',bullets:['Evaporazione','Condensazione'],blocks:[],
      diagram:{kind:'none'},sources:[],notes:''}}];
    await assertButtons(false,'Rigenera ↻');
    await scrollMiddle();
    const beforeCancel=generated.length;
    const cancelDialog=page.waitForEvent('dialog').then(async dialog=>{
      confirmations.push(dialog.message());await dialog.dismiss();
    });
    await floating.click();await cancelDialog;
    await assertButtons(false,'Rigenera ↻');
    assert.equal(generated.length,beforeCancel,'Cancelling regeneration sends no generation request');
    assert.match(confirmations.at(-1),/Rigenerare la presentazione con prompt e parametri attuali/);

    const regeneratePrompt='Riorganizza il ciclo dell’acqua in quattro passaggi';
    await page.locator('#prompt').fill(regeneratePrompt);
    await page.locator('#count').fill('4');
    await scrollMiddle();
    const acceptDialog=page.waitForEvent('dialog').then(async dialog=>{
      confirmations.push(dialog.message());await dialog.accept();
    });
    const regeneration=page.waitForResponse(response=>response.url().endsWith('/generate'));
    await floating.click();await acceptDialog;await regeneration;
    await assertButtons(false,'Rigenera ↻');
    assert.equal(generated.length,beforeCancel+1,'Accepted regeneration submits exactly one POST');
    assert.equal(generated.at(-1).prompt,regeneratePrompt);
    assert.equal(generated.at(-1).count,4);
    assert.equal(generated.at(-1).regenerate_all,true);
    assert.equal(generated.at(-1).rebuild_outline,true);
    assert.equal(generated.at(-1).slide_id,null);
    assert.equal(generated.at(-1).diagram_only,false);
    assert.equal(confirmations.length,2,'Both regeneration attempts preserve the existing confirmation');

    for(const status of ['queued','running','paused']){
      jobs=[{id:'mock-job',project_id:project.id,status,progress:.25,events:[]}];
      await page.waitForFunction(expected=>document.querySelector('#job-percent').textContent.endsWith(expected),status);
      await assertButtons(true,'In corso…');
      await scrollMiddle();
      assert.equal(await floating.isVisible(),true,'Active generation retains the visible status action');
      await floating.evaluate(element=>element.click());
      assert.equal(generated.length,2,'No duplicate generation while '+status);
    }
    jobs=[{id:'mock-job',project_id:project.id,status:'completed',progress:1,events:[]}];
    await page.waitForFunction(()=>document.querySelector('#job-percent').textContent.endsWith('completed'));
    await assertButtons(false,'Rigenera ↻');
    await scrollMiddle();await assertAccessibleFloating();
    assert.deepEqual(errors,[]);
    console.log(`Floating generation UI ${viewport.width}×${viewport.height}: visibility, navigation, touch target, toast, generation, confirmation and job states passed.`);
  }finally{
    releaseGeneration?.();
    await page.unrouteAll({behavior:'wait'});await page.close();
  }
}

try{
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}])await testViewport(viewport);
}finally{await browser.close()}
