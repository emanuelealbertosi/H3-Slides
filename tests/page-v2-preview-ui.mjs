import './browser-env.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
import {chromium} from 'playwright-chromium';

const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
const widthFix='.slide-preview:has(>.page-v2){width:100%;max-width:100%;aspect-ratio:auto}';
// Diagnostic red run: remove only the fix from the mocked module response.
const legacyCSS=process.env.H3_V2_PREVIEW_LEGACY_CSS==='1';
const nodes=count=>Array.from({length:count},(_,i)=>({id:'text'+i,parent:'root',kind:'text',
  text:'Paragrafo '+i+': una spiegazione completa resta leggibile anche quando la pagina adattiva contiene molte sezioni.',style:{font_size:26}}));
const content=count=>({title:'Pagina alta',layout:'content',blocks:[],bullets:[],notes:'',sources:[],diagram:{kind:'none'},page:{style:{gap:20},nodes:nodes(count)}});

test('Overfull V2 previews retain a capped frame and visible error content through growth, resize and reopening',async()=>{
  const project={id:'geometry',title:'Geometria V2',prompt:'Fixture locale',count:2,engine:'v2',theme:'paper',font:'Arial',canvas_mode:'adaptive',sources:[],visual_assets:[],
    slides:[{id:'ready',revision:1,status:'ready',content:content(35)},
      {id:'draft',revision:1,status:'generating',content:{...content(0),page:undefined},page_draft:content(1).page,page_stream:{phase:'writing',characters:100,nodes:1}}]};
  const job={id:'geometry-job',project_id:project.id,status:'running',progress:.5,events:[]};
  const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[];
  page.setDefaultTimeout(8000);page.on('pageerror',error=>errors.push(error.message));
  try{
    await page.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      assert.equal(url.origin,origin);assert.equal(request.method(),'GET','No real or simulated mutations');
      if(url.pathname.startsWith('/api/')){
        const data={'/api/projects':[{...project,slide_count:2}],'/api/projects/geometry':project,'/api/jobs':[job],
          '/api/models':{models:[{id:'mock',name:'Fixture',vision:true,size_gb:1}],default_model:'mock',runtime_available:true,status:{running:false}},
          '/api/documents':[],'/api/themes':[],'/api/library':{folders:[],order:[],assignments:{}},'/api/admin/search':{searxng_url:'http://127.0.0.1:8080'}};
        assert(Object.hasOwn(data,url.pathname),url.pathname);return route.fulfill({json:data[url.pathname]});
      }
      const file=resolve(root,['/','/editor','/create'].includes(url.pathname)?'index.html':url.pathname.replace(/^\/static\//,''));
      assert(file.startsWith(root.endsWith(sep)?root:root+sep));let body=await readFile(file);
      if(legacyCSS&&file.endsWith(sep+'page-v2.mjs')){assert(body.toString().includes(widthFix));body=Buffer.from(body.toString().replace(widthFix,''))}
      return route.fulfill({body,contentType:{'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2'}[extname(file)]||'application/octet-stream'});
    });
    await page.addInitScript(()=>localStorage.setItem('h3slides-project','geometry'));
    async function bounded(stage,tallCount){
      await page.evaluate(()=>document.fonts.ready);
      const samples=await page.evaluate(async()=>{
        const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));await frame();await frame();const result=[];
        for(let i=0;i<10;i++){
          await frame();result.push({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,cards:[...document.querySelectorAll('#slides .slide-card')].map(card=>{
            const preview=card.querySelector('.slide-preview'),page=preview.querySelector('.page-v2'),p=preview.getBoundingClientRect(),f=page.getBoundingClientRect(),c=card.getBoundingClientRect();
            return {id:card.dataset.id,cardWidth:c.width,previewWidth:p.width,previewHeight:p.height,frameWidth:f.width,frameHeight:f.height,naturalHeight:page.offsetHeight,neededHeight:Number(page.dataset.neededHeight),overflow:page.dataset.overflow==='true',previewRight:p.right,cardRight:c.right,cardBottom:c.bottom,contentBottom:Math.max(...[...page.querySelectorAll('.v2-node,.footer')].map(node=>node.getBoundingClientRect().bottom))};
          })});
        }return result;
      });
      for(const sample of samples){
        for(const card of sample.cards){
          assert(card.previewWidth>0&&card.previewWidth<=card.cardWidth+2,stage+': preview exceeds card '+JSON.stringify(card));
          assert(card.previewRight<=card.cardRight+2,stage+': preview extends outside card');
          assert(Math.abs(card.frameWidth-card.previewWidth)<=2,stage+': transformed frame must match preview width');
          assert(card.naturalHeight>=720&&card.naturalHeight<=828,stage+': the frame is capped by its format');
          if(card.overflow){assert(card.neededHeight>828);assert(card.previewHeight>=card.frameHeight);assert(card.contentBottom<=card.cardBottom+2,stage+': invalid content stays visible inside its error card')}
          else assert(Math.abs(card.frameHeight-card.previewHeight)<=2,stage+': valid preview matches its bounded frame');
        }
        assert(sample.documentWidth<=sample.viewport+1,stage+': horizontal document overflow');
        assert.equal(sample.cards.filter(card=>card.overflow).length,tallCount,stage+': impossible pages must not be reported as fitted');
      }
      const final=samples.at(-1);
      for(const sample of samples.slice(-5))for(const card of sample.cards){
        const last=final.cards.find(item=>item.id===card.id);
        for(const key of ['previewWidth','previewHeight','frameWidth','frameHeight'])assert(Math.abs(card[key]-last[key])<=1,stage+': dimensions must settle across animation frames');
      }
      console.log(stage+': '+final.cards.map(card=>card.id+' '+Math.round(card.previewWidth)+'px / natural height '+card.naturalHeight+'px').join(', '));
    }
    await page.goto(origin+'/editor');await page.locator('#slide-ready .page-v2').waitFor();await page.locator('#slide-draft .page-v2').waitFor();
    await bounded('Desktop ready page and initial draft',1);
    project.slides[1].page_draft=content(35).page;project.slides[1].page_stream={phase:'writing',characters:4000,nodes:35};
    await page.waitForFunction(()=>document.querySelectorAll('#slide-draft .v2-node').length===35);
    await bounded('Desktop growing draft',2);
    await page.setViewportSize({width:390,height:844});await bounded('Mobile tall pages',2);
    await page.locator('#editor-menu>summary').click();await page.locator('#editor-settings').click();
    await page.waitForFunction(()=>document.body.dataset.view==='create');
    assert.equal(await page.locator('.workspace').isVisible(),false);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.locator('#setup-back').click();await page.waitForFunction(()=>document.body.dataset.view==='editor');
    await bounded('Mobile editor reopened',2);
    await page.setViewportSize({width:1500,height:1100});await bounded('Desktop after resize',2);
    project.slides[1].content.page=project.slides[1].page_draft;delete project.slides[1].page_draft;delete project.slides[1].page_stream;
    project.slides[1].status='ready';job.status='completed';job.progress=1;
    await page.waitForFunction(()=>document.querySelector('#slide-draft')?.dataset.streamPhase==='ready');
    await bounded('Both pages ready',2);assert.deepEqual(errors,[]);
  }finally{await browser.close()}
});
