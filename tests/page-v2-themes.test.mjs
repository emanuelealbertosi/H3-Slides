import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep} from 'node:path';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,fitSlide,themeFor} from '../static/deck.mjs';
import {resolveV2Theme,resolveV2Node,resolveV2Role,themeV2Contrast,themeV2PreviewHTML} from '../static/theme-v2.mjs';

const presets=JSON.parse(await readFile(new URL('../static/theme-presets.json',import.meta.url),'utf8'));
// These are the schema defaults, not an abbreviated unvalidated page.
const style=extra=>({flow:'stack',columns:[1,1],gap:24,padding:0,surface:'none',radius:0,shadow:false,border:false,font_size:24,bold:false,align:'left',span:1,min_height:0,...extra});
const node=(id,kind,text,role='auto',parent='root',extra={})=>({id,kind,text,role,parent,style:style(extra)});
const makeProject=values=>({id:'theme-fixture',title:'Identità e componenti',engine:'v2',theme:'paper',font:'Arial',canvas_mode:'adaptive',sources:[],visual_assets:[],...structuredClone(values),slides:[{id:'one',revision:1,status:'ready',content:{title:'Una pagina aperta',blocks:[],bullets:[],sources:[],diagram:{kind:'none'},page:{version:2,style:style({gap:28}),nodes:[
  node('eyebrow','text','Prospettive in comune','eyebrow'),
  node('title','heading','Idee che prendono forma'),
  node('lead','text','Una gerarchia chiara rende leggibili anche contenuti articolati.','lead'),
  node('columns','group','','auto','root',{flow:'columns',columns:[1.4,1],gap:28}),
  node('example','group','','example','columns',{gap:16}),
  node('example-heading','heading','Un esempio concreto','auto','example'),
  node('example-body','text','Ogni elemento rimane indipendente e modificabile.','body','example'),
  node('nested','group','','auto','example',{gap:12}),
  node('nested-body','text','Anche nelle sezioni annidate il colore segue lo sfondo.','body','nested'),
  node('stat','text','82%','stat','columns'),
  node('callout','text','Un punto importante da ricordare, senza forzare un layout fisso.','callout'),
  node('quote','text','«La forma aiuta il lettore a trovare il significato.»','quote'),
  node('step','text','1. Osserva le relazioni prima dei dettagli.','step'),
  node('body','text','Il testo di base segue le dimensioni del tema.','body'),
  node('override','text','Una modifica manuale resta esplicita.','body','root',{font_size:31,padding:17,radius:9,surface:'key'}),
  {...node('code','code','const idea = "testo letterale";'),language:'javascript'},
  node('caption','text','Fonte: fixture locale, senza immagini o servizi esterni.','caption'),
]}}}]});
const rgbHex=value=>'#'+value.match(/\d+/g).slice(0,3).map(v=>Number(v).toString(16).padStart(2,'0')).join('');
const blend=(a,b,t)=>'#'+[1,3,5].map(i=>Math.round(parseInt(a.slice(i,i+2),16)*(1-t)+parseInt(b.slice(i,i+2),16)*t).toString(16).padStart(2,'0')).join('');

test('eight identities use semantic palettes with readable flat and gradient paint, without mutating input',()=>{
  assert.equal(presets.length,8);
  const signatures=new Set(),miniatures=new Set();
  for(const preset of presets){
    const project=makeProject(preset.values),before=structuredClone(project),theme=resolveV2Theme(project,themeFor(project));
    assert.equal(theme.enabled,true,preset.name);
    assert.equal(theme.headingFont,preset.values.theme_design.heading_font);
    assert.equal(theme.titleSize,preset.values.theme_design.title_size);
    assert.equal(theme.bodySize,preset.values.theme_design.body_size||(['editorial','modern','playful'].includes(theme.family)?25:24));
    signatures.add(JSON.stringify([theme.family,theme.canvas,theme.headingFont,theme.radius,theme.decoration]));
    miniatures.add(themeV2PreviewHTML(project));
    for(const paint of [theme.canvas,...Object.values(theme.surfaces)])for(let sample=0;sample<=20;sample++){
      const bg=blend(...paint.stops,sample/20);
      assert(themeV2Contrast(bg,paint.foreground)>=4.5,preset.name+': foreground contrast '+JSON.stringify(paint));
    }
    const paintById=new Map([['root',theme.canvas]]);
    for(const item of project.slides[0].content.page.nodes){
      const role=resolveV2Role(item,'title'),appearance=resolveV2Node(theme,item,role,paintById.get(item.parent));
      paintById.set(item.id,appearance.paint);
      for(const bg of appearance.paint.stops)assert(themeV2Contrast(bg,appearance.color)>=4.5,preset.name+': '+item.id);
      if(item.id==='title')assert.equal(appearance.style.font_size,theme.titleSize);
      if(item.id==='body')assert.equal(appearance.style.font_size,theme.bodySize);
      if(item.id==='example')assert.equal(appearance.ownPaint.background,preset.values.theme_design.example_color);
      if(item.id==='quote')assert.equal(appearance.ownPaint.background,preset.values.theme_design.quote_color);
      if(item.id==='override')assert.deepEqual([appearance.style.font_size,appearance.style.padding,appearance.style.radius],[31,17,9]);
    }
    const plain=resolveV2Node(theme,node('plain','text','Senza riquadro','callout','root',{surface:'plain'}),'callout');
    assert.equal(plain.ownPaint,null,'Explicit transparent surface overrides semantic fill');
    assert.equal(plain.surface,'none');
    assert.deepEqual(project,before,'Rendering must not rewrite saved choices');
  }
  assert.equal(signatures.size,8);assert.equal(miniatures.size,8);
  for(const background of ['#000000','#ffffff','#777777','#0000ff']){
    const theme=resolveV2Theme({background_color:background,accent_color:background,theme_design:{visual_family:'modern',background_style:'gradient',secondary_color:'#ffffff',text_color:background}});
    for(const paint of [theme.canvas,theme.surfaces.gradient])for(let sample=0;sample<=20;sample++)assert(themeV2Contrast(blend(...paint.stops,sample/20),paint.foreground)>=4.5,'Extreme generated palettes remain readable');
  }
});

test('legacy V2 and classic pages keep their renderer until the new visual identity is selected',()=>{
  const legacy=makeProject({theme_design:{title_size:65,body_size:29,example_color:'#eeddaa'}}),slide=legacy.slides[0];
  const defaults={visual_family:'classic',background_style:'flat',secondary_color:'',heading_font:'',shadow_style:'soft',decoration:'none',design_note:''};
  const normalized={...legacy,theme_design:{...legacy.theme_design,...defaults}};
  assert.equal(resolveV2Theme(legacy).enabled,false);assert.equal(resolveV2Theme(normalized).enabled,false);
  assert.equal(slideHTML(legacy,slide,0),slideHTML(normalized,slide,0));
  assert.doesNotMatch(slideHTML(normalized,slide,0),/data-visual-family|data-v2-decoration/);
  const classicSlide=structuredClone(slide);delete classicSlide.content.page;
  classicSlide.content.blocks=[{kind:'explanation',heading:'Stile esistente',text:'Nessuna migrazione grafica automatica.',source:''}];
  assert.equal(slideHTML(legacy,classicSlide,0),slideHTML({...legacy,theme_design:{...legacy.theme_design,...defaults,visual_family:'modern',heading_font:'Georgia',decoration:'stripe'}},classicSlide,0));
});

test('all eight themes preserve nested geometry, typography and literal editable text at desktop and mobile widths',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
    for(const preset of presets){
      const project=makeProject(preset.values),slide=project.slides[0];
      slide.content.page.nodes.find(n=>n.id==='nested-body').text='<img src=x onerror="window.executed=true"> & testo letterale';
      await page.setContent('<style>'+slideCSS+'html,body{margin:0}.fixture-card{padding:16px;max-width:1312px}.slide-preview{aspect-ratio:16/9;overflow:hidden}</style><section class="fixture-card"><div class="slide-preview">'+slideHTML(project,slide,0)+'</div></section>');
      await page.evaluate(()=>document.fonts.ready);
      const frame=page.locator('.page-v2'),report=await frame.evaluate(fitSlide);
      assert.equal(report.overflow,false,preset.name);assert(report.height>=720&&report.height<=828);
      assert.equal(await page.locator('.v2-node').count(),slide.content.page.nodes.length);
      assert.equal(await page.locator('[data-page-text][data-edit-field="page-text"][data-edit-raw]').count(),slide.content.page.nodes.filter(n=>n.kind!=='group').length);
      assert.equal(await page.locator('[data-page-node="example"] > [data-page-node="nested"] > [data-page-node="nested-body"]').count(),1);
      assert.equal(await page.locator('.v2-root script,.v2-root img').count(),0);
      assert.equal(await page.locator('[data-page-text="nested-body"]').textContent(),slide.content.page.nodes.find(n=>n.id==='nested-body').text);
      const metrics=await frame.evaluate(el=>{
        const values=id=>{const node=el.querySelector('[data-page-node="'+id+'"]'),text=node.querySelector('.v2-text'),s=getComputedStyle(text||node),ns=getComputedStyle(node);return {font:s.fontFamily,size:parseFloat(s.fontSize),color:s.color,background:ns.backgroundColor,padding:parseFloat(ns.paddingLeft),radius:parseFloat(ns.borderRadius)}};
        const bounds=el.getBoundingClientRect();
        return {title:values('title'),body:values('body'),example:values('example'),nested:values('nested-body'),override:values('override'),
          outside:[...el.querySelectorAll('.v2-node,.v2-text')].filter(node=>{const r=node.getBoundingClientRect();return r.left<bounds.left-1||r.right>bounds.right+1||r.bottom>bounds.bottom+1}).map(node=>node.dataset.pageNode||node.dataset.pageText),
          decorations:[...el.querySelectorAll('[data-v2-decoration]')].map(node=>({name:node.dataset.v2Decoration,hidden:node.getAttribute('aria-hidden'),pointer:getComputedStyle(node).pointerEvents})),
          gradients:[...el.querySelectorAll('[data-v2-gradient]'),...(el.matches('[data-v2-gradient]')?[el]:[])].map(node=>getComputedStyle(node).backgroundImage)};
      });
      assert.equal(metrics.title.font.replaceAll('"',''),preset.values.theme_design.heading_font);
      assert(metrics.title.size>=32&&metrics.title.size<=preset.values.theme_design.title_size);
      assert(metrics.body.size>=20&&metrics.body.size<=resolveV2Theme(project).bodySize);
      assert(metrics.override.size>=20&&metrics.override.size<=31);assert(metrics.override.padding>=8&&metrics.override.padding<=17);assert.equal(metrics.override.radius,9);
      assert.deepEqual([slide.content.page.nodes.find(n=>n.id==='override').style.font_size,slide.content.page.nodes.find(n=>n.id==='override').style.padding],[31,17],'Fitting never rewrites manual JSON settings');
      assert.equal(rgbHex(metrics.example.background),preset.values.theme_design.example_color);
      assert(themeV2Contrast(rgbHex(metrics.example.background),rgbHex(metrics.nested.color))>=4.5,'Nested text inherits its actual parent paint');
      assert.deepEqual(metrics.outside,[],preset.name+': node bounds');
      const decoration=preset.values.theme_design.decoration;
      assert.deepEqual(metrics.decorations,decoration==='none'?[]:[{name:decoration,hidden:'true',pointer:'none'}]);
      for(const gradient of metrics.gradients)assert.match(gradient,/^linear-gradient\(135deg,/);
      assert.equal(Boolean(await frame.getAttribute('data-v2-gradient')),preset.values.theme_design.background_style==='gradient');
      for(const width of [1500,390,1500]){
        await page.setViewportSize({width,height:1000});
        const geometry=await frame.evaluate(el=>{const preview=el.parentElement,scale=preview.clientWidth/1280;el.style.transform='scale('+scale+')';el.style.transformOrigin='top left';preview.style.height=el.offsetHeight*scale+'px';const p=preview.getBoundingClientRect(),card=preview.parentElement.getBoundingClientRect(),f=el.getBoundingClientRect();return {preview:p.width,card:card.width,frame:f.width,height:p.height,frameHeight:f.height,scroll:document.documentElement.scrollWidth,width:innerWidth}});
        assert(geometry.preview<=geometry.card&&geometry.preview>0,preset.name+': preview bounds');
        assert(Math.abs(geometry.frame-geometry.preview)<1);assert(Math.abs(geometry.height-geometry.frameHeight)<1);
        assert(geometry.scroll<=geometry.width,preset.name+': horizontal overflow');
      }
    }
    assert.deepEqual(errors,[]);
  }finally{await browser.close()}
});

test('rich nested components retain real editor controls and save role, surface and text locally',async()=>{
  const root=fileURLToPath(new URL('../static/',import.meta.url)),origin='http://127.0.0.1:9876';
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',error=>errors.push(error.message));page.setDefaultTimeout(8000);
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());assert.equal(url.origin,origin);assert.equal(route.request().method(),'GET');
      if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<style>'+slideCSS+'</style><section id="card"></section>'});
      const file=resolve(root,url.pathname.replace(/^\/static\//,''));assert(file.startsWith(root.endsWith(sep)?root:root+sep));
      return route.fulfill({contentType:'text/javascript',body:await readFile(file)});
    });
    await page.goto(origin);
    await page.evaluate(async project=>{
      const {renderPageCard}=await import('/static/page-v2-editor.mjs');window.fixture=project;window.saved=0;window.messages=[];
      const render=()=>renderPageCard(document.querySelector('#card'),project,project.slides[0],0,{observe:()=>{},toast:message=>window.messages.push(message),save:async mutate=>{mutate(project.slides[0].content);window.saved++;render()}});render();
    },makeProject(presets[6].values));
    assert.equal(await page.locator('[data-page-node="nested-body"] > .v2-tools [data-v2-edit]').count(),1);
    await page.locator('[data-v2-edit="nested-body"]').evaluate(button=>button.click());
    await page.locator('.v2-editor textarea[name="text"]').fill('Testo modificato <script>window.executed=true</script>');
    await page.locator('.v2-editor select[name="role"]').selectOption('callout');
    await page.locator('.v2-editor select[name="surface"]').selectOption('gradient');
    await page.locator('.v2-editor button[value="save"]').click();
    await page.waitForFunction(()=>window.saved===1);
    assert.equal(await page.locator('[data-page-node="nested-body"]').getAttribute('data-v2-role'),'callout');
    assert.equal(await page.locator('[data-page-node="nested-body"]').getAttribute('data-v2-gradient'),'true');
    assert.equal(await page.locator('[data-page-text="nested-body"] script').count(),0);
    const saved=await page.evaluate(()=>({node:window.fixture.slides[0].content.page.nodes.find(n=>n.id==='nested-body'),messages:window.messages,executed:Boolean(window.executed)}));
    assert.equal(saved.node.parent,'nested');assert.equal(saved.node.role,'callout');assert.equal(saved.node.style.surface,'gradient');
    assert.equal(saved.node.text,'Testo modificato <script>window.executed=true</script>');assert.equal(saved.executed,false);assert.deepEqual(saved.messages,[]);
    await page.locator('[data-v2-edit="nested"]').evaluate(button=>button.click());
    await page.locator('.v2-editor select[name="flow"]').selectOption('columns');
    await page.locator('.v2-editor input[name="columns"]').fill('2, 1');
    await page.locator('.v2-editor button[value="save"]').click();await page.waitForFunction(()=>window.saved===2);
    assert.match(await page.locator('[data-page-node="nested"]').getAttribute('style'),/minmax\(0(?:px)?,\s*2fr\)/);
    assert.deepEqual(errors,[]);
  }finally{await browser.close()}
});
