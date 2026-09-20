import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';
const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const project={id:'v2-ui',title:'Prova V2',prompt:'Una pagina flessibile',count:1,engine:'v2',theme:'paper',font:'Arial',canvas_mode:'adaptive',sources:[],visual_assets:[],
  slides:[{id:'page',revision:1,status:'ready',content:{title:'Prova',blocks:[],bullets:[],layout:'content',notes:'',sources:[],diagram:{kind:'none'},page:{style:{gap:24},nodes:[
    {id:'title',parent:'root',kind:'heading',text:'Titolo V2',style:{font_size:48}},
    {id:'group',parent:'root',kind:'group',style:{flow:'columns',columns:[1,1]}},
    ...Array.from({length:7},(_,i)=>({id:'p'+i,parent:'group',kind:'text',text:'Paragrafo numero '+i,style:{font_size:26}}))]}}}]};
const finishedSlide=structuredClone(project.slides[0]);
project.slides[0].status='generating';delete project.slides[0].content.page;
project.slides[0].page_stream={phase:'waiting',characters:0,nodes:0};
const jobs=[{id:'v2-job',project_id:project.id,status:'running',progress:0,events:[]}];
const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1500,height:1100}});
const errors=[],patches=[];page.on('pageerror',e=>errors.push(e.message));
try{
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();assert.equal(url.origin,origin);
    if(url.pathname==='/api/projects/v2-ui/slides/page'&&method==='PATCH'){
      const body=route.request().postDataJSON();patches.push(body);assert.equal(body.revision,project.slides[0].revision);
      project.slides[0]={...project.slides[0],content:body.content,revision:body.revision+1};return route.fulfill({json:project.slides[0]});
    }
    if(url.pathname.startsWith('/api/')){
      assert.equal(method,'GET');
      const data={'/api/projects':[{...project,slide_count:project.slides.length}],'/api/projects/v2-ui':project,'/api/jobs':jobs,
        '/api/models':{models:[{id:'mock',name:'Fixture',vision:true,size_gb:1}],default_model:'mock',runtime_available:true,status:{running:false}},
        '/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},'/api/admin/search':{searxng_url:'http://127.0.0.1:8080'}};
      assert(Object.hasOwn(data,url.pathname),url.pathname);return route.fulfill({json:data[url.pathname]});
    }
    const file=resolve(root,['/','/editor','/create','/library'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));assert(file.startsWith(root.endsWith(sep)?root:root+sep));
    return route.fulfill({body:await readFile(file),contentType:{'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream'});
  });
  await page.addInitScript(()=>{
    localStorage.setItem('h3slides-project','v2-ui');
    const timeout=window.setTimeout;window.pollDelays=[];
    window.setTimeout=function(callback,delay,...args){if(callback?.name==='poll')window.pollDelays.push(delay);return timeout.call(this,callback,delay,...args)};
  });
  await page.goto(origin+'/editor');await page.locator('.v2-waiting-preview').waitFor();
  assert.equal(await page.locator('#creation-engine').inputValue(),'v2');
  assert.match(await page.locator('.v2-waiting-preview').innerText(),/In attesa del testo/);
  assert.equal(await page.locator('#slide-page button').count(),0,'No finished-page controls on a waiting draft');
  await page.waitForFunction(()=>window.pollDelays.at(-1)===500);

  // A validated first node is rendered while its text is still arriving.
  project.slides[0].content.page={style:{gap:24},nodes:[{...finishedSlide.content.page.nodes[0],text:'Tit'}]};
  project.slides[0].page_stream={phase:'writing',characters:3,nodes:1};
  await page.waitForFunction(()=>document.querySelector('[data-page-text="title"]')?.textContent==='Tit');
  assert.match(await page.locator('.composition-status').innerText(),/Scrittura in corso/);
  await page.locator('[data-page-text="title"]').dblclick();
  assert.equal(await page.locator('[contenteditable]').count(),0,'Streaming text is not editable');
  const growingText='Titolo che cresce: <em>testo letterale</em> e una spiegazione';
  project.slides[0].page_draft=structuredClone(project.slides[0].content.page);
  project.slides[0].page_draft.nodes[0].text=growingText;
  project.slides[0].page_stream.characters=growingText.length;
  await page.waitForFunction(text=>document.querySelector('[data-page-text="title"]')?.textContent===text,growingText);
  assert.equal(await page.locator('.v2-root em').count(),0,'Partial model text remains literal text');
  const incompleteFormula='Formula: \\(\\frac{a}{b',incompleteCode='const value = "parziale\\';
  project.slides[0].page_draft.nodes.push({id:'formula',parent:'root',kind:'text',text:incompleteFormula,style:{}},
    {id:'code',parent:'root',kind:'code',text:incompleteCode,language:'javascript',style:{}});
  project.slides[0].page_stream.nodes=3;
  await page.waitForFunction(text=>document.querySelector('[data-page-text="formula"]')?.textContent===text,incompleteFormula);
  assert.equal(await page.locator('[data-page-text="code"]').textContent(),incompleteCode,'Unfinished code and trailing backslashes are preserved');
  project.slides[0].page_draft.nodes.find(n=>n.id==='formula').text='Formula: \\(\\frac{a}{b}\\)';
  await page.locator('[data-page-text="formula"] .katex').waitFor();
  await page.reload();await page.waitForFunction(text=>document.querySelector('[data-page-text="title"]')?.textContent===text,growingText);
  assert.equal(await page.locator('#slide-page').getAttribute('data-stream-phase'),'writing','Reload retains the persisted draft');

  await page.locator('#prompt').evaluate(el=>{el.value='Brief ancora non salvato';el.dispatchEvent(new Event('input',{bubbles:true}))});
  project.slides[0].page_stream.phase='media';
  await page.waitForFunction(()=>document.querySelector('#slide-page')?.dataset.streamPhase==='media');
  assert.match(await page.locator('.composition-status').innerText(),/Preparazione immagini e diagrammi/);
  assert.equal(await page.locator('#prompt').inputValue(),'Brief ancora non salvato');
  assert.equal(await page.locator('#slide-page button').count(),0);
  project.slides[0].status='failed';jobs[0].status='failed';
  await page.locator('#slide-page [data-action="regenerate"]').waitFor();
  assert.equal(await page.locator('#slide-page [data-v2-add]').count(),0,'Interrupted drafts offer recovery without final editing controls');
  assert.equal(await page.locator('[data-page-text="title"]').textContent(),growingText);

  // One page becomes editable while the following page is still being written.
  jobs[0].status='running';
  project.slides[0]=structuredClone(finishedSlide);
  project.slides[0].content.page.nodes.push({id:'failed-chart',parent:'root',kind:'diagram',asset_id:'',text:'Un diagramma utile',style:{}});
  project.slides[0].page_diagrams={'failed-chart':{status:'failed',error:'<em>Composizione incompleta</em>'}};
  project.slides.push({id:'next',revision:1,status:'generating',content:{...structuredClone(finishedSlide.content),title:'Pagina successiva',page:{style:{},nodes:[{id:'next-title',parent:'root',kind:'heading',text:'La seconda pagina',style:{}}]}},page_stream:{phase:'writing',characters:17,nodes:1}});
  await page.waitForFunction(()=>document.querySelectorAll('.page-v2').length===2&&document.querySelector('#slide-page')?.dataset.streamPhase==='ready');
  assert.equal(jobs[0].status,'running');
  assert.equal(await page.locator('#slide-page [data-v2-add="text"]').count(),1);
  assert.equal(await page.locator('#slide-next button').count(),0);
  const failedDiagram=page.locator('[data-page-node="failed-chart"]');
  assert.match(await failedDiagram.innerText(),/Diagramma non disponibile/);
  assert.equal(await failedDiagram.locator('em,img,script').count(),0);
  await failedDiagram.hover();await failedDiagram.locator('[data-v2-diagram="failed-chart"]').click();
  assert.match(await page.locator('#toast').innerText(),/Attiva “Diagrammi Manim automatici” nel brief/);
  assert.equal(await page.locator('#manim-diagrams').isChecked(),false,'Retry never silently enables Manim');
  const retry=await page.evaluate(async fixture=>{
    const {renderPageCard}=await import('/static/page-v2-editor.mjs'),card=document.createElement('section'),calls=[],messages=[];
    document.body.append(card);
    renderPageCard(card,{...fixture,use_manim_diagrams:true},fixture.slides[0],0,{observe:()=>{},toast:message=>messages.push(message),diagram:id=>calls.push(id)});
    card.querySelector('[data-v2-diagram="failed-chart"]').click();await Promise.resolve();card.remove();return {calls,messages};
  },project);
  assert.deepEqual(retry,{calls:['failed-chart'],messages:[]},'Enabled recovery targets only the selected diagram');
  const focused=page.locator('#slide-page [data-page-text="title"]');
  await focused.dblclick();await focused.fill('Titolo in modifica manuale');
  project.slides[1].content.page.nodes[0].text='La seconda pagina continua a crescere';
  await page.waitForFunction(()=>document.querySelector('[data-page-text="next-title"]')?.textContent==='La seconda pagina continua a crescere');
  assert.equal(await focused.innerText(),'Titolo in modifica manuale');
  assert.equal(await focused.evaluate(el=>document.activeElement===el),true,'Polling preserves the focused editor');
  await focused.press('Escape');
  project.slides[0].content.page.nodes=project.slides[0].content.page.nodes.filter(node=>node.id!=='failed-chart');delete project.slides[0].page_diagrams;
  project.slides.pop();jobs[0].status='completed';
  await page.waitForFunction(()=>document.querySelectorAll('.page-v2').length===1&&window.pollDelays.at(-1)===1500);
  assert.equal(await page.locator('.v2-node').count(),9);
  const field=page.locator('[data-page-text="p0"]');await field.dblclick();await field.fill('Modifica diretta salvata');await field.press('Enter');
  await page.waitForFunction(()=>document.querySelector('[data-page-text="p0"]')?.textContent==='Modifica diretta salvata'&&!document.querySelector('[contenteditable]'));
  await page.locator('[data-v2-add="text"]').click();await page.waitForFunction(()=>document.querySelectorAll('.v2-node').length===10);
  assert.equal(patches.length,2,'No duplicate handlers after rendering');
  await page.locator('[data-page-node="p0"]').hover();
  await page.locator('[data-page-node="p0"] [data-v2-drag]').dragTo(page.locator('[data-page-node="p3"]'));
  await page.waitForFunction(()=>{const s=document.querySelector('#slide-page').dataset.signature;return s&&JSON.parse(s)[0].revision>=4});
  assert(project.slides[0].content.page.nodes.findIndex(n=>n.id==='p0')>project.slides[0].content.page.nodes.findIndex(n=>n.id==='p2'));
  await page.locator('[data-page-node="p1"]').hover();await page.locator('[data-v2-delete="p1"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.v2-node').length===9);
  await page.reload();await page.locator('.page-v2').waitFor();
  assert.equal(await page.locator('[data-page-text="p0"]').innerText(),'Modifica diretta salvata');
  assert.equal(await page.locator('[data-page-node="p1"]').count(),0);
  await page.locator('[data-v2-edit="root"]').click();await page.locator('.v2-editor select[name="flow"]').selectOption('columns');
  await page.locator('.v2-editor input[name="columns"]').fill('2, 1');await page.locator('.v2-editor button[value="save"]').click();
  await page.waitForFunction(()=>document.querySelector('.v2-root')?.style.gridTemplateColumns.includes('2fr'));
  assert.equal(project.slides[0].content.page.style.flow,'columns');
  jobs[0].status='running';project.engine='classic';
  await page.waitForFunction(()=>document.querySelector('#job-percent').textContent.includes('running')&&window.pollDelays.at(-1)===1500);
  project.engine='v2';await page.goto(origin+'/library');
  await page.waitForFunction(()=>window.pollDelays.at(-1)===1500);
  assert.equal(await page.locator('#slides .slide-card').count(),0,'No selected project uses the normal polling interval');
  assert.deepEqual(errors,[]);
  console.log('V2 full app: waiting/writing/media drafts, growing literal text, draft reload, next slide before completion, active polling, focus preservation, >4 blocks, inline edit, add/delete, drag/drop, layout settings and revision passed');
}finally{await browser.close()}
