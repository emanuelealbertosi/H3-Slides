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
      const data={'/api/projects':[{...project,slide_count:1}],'/api/projects/v2-ui':project,'/api/jobs':[],
        '/api/models':{models:[{id:'mock',name:'Fixture',vision:true,size_gb:1}],default_model:'mock',runtime_available:true,status:{running:false}},
        '/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},'/api/admin/search':{searxng_url:'http://127.0.0.1:8080'}};
      assert(Object.hasOwn(data,url.pathname),url.pathname);return route.fulfill({json:data[url.pathname]});
    }
    const file=resolve(root,['/','/editor','/create'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));assert(file.startsWith(root.endsWith(sep)?root:root+sep));
    return route.fulfill({body:await readFile(file),contentType:{'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream'});
  });
  await page.addInitScript(()=>localStorage.setItem('h3slides-project','v2-ui'));
  await page.goto(origin+'/editor');await page.locator('.page-v2').waitFor();
  assert.equal(await page.locator('#creation-engine').inputValue(),'v2');
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
  assert.deepEqual(errors,[]);
  console.log('V2 full app: >4 blocks, inline edit, add/delete, drag/drop, layout settings, revision and reload passed');
}finally{await browser.close()}
