import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,fitSlide} from '../static/deck.mjs';

const node=(id,text,extra={})=>({id,parent:'root',kind:'text',text,style:{font_size:26},...extra});
const heading=node('title','Una gerarchia leggibile',{kind:'heading',style:{font_size:64}});
const content=nodes=>({title:'Formato scelto',blocks:[],bullets:[],sources:[],diagram:{kind:'none'},page:{version:2,style:{gap:40},nodes}});
const project=(nodes,extra={})=>({id:'bounded',title:'Impaginazione locale',engine:'v2',theme:'paper',font:'Arial',canvas_mode:'adaptive',slide_format:'16:9',...extra,slides:[{id:'one',status:'ready',content:content(nodes)}]});
const prose='Una spiegazione completa collega cause, relazioni e conseguenze senza perdere informazioni. ';
const density=count=>[heading,node('group','',{kind:'group',style:{gap:32}}),...Array.from({length:count},(_,i)=>node('p'+i,prose.repeat(4),{parent:'group',style:{font_size:32,padding:24}}))];
async function render(page,p,urls={}){
  await page.setContent('<style>'+slideCSS+'html,body{margin:0}</style>'+slideHTML(p,p.slides[0],0,urls));
  await page.evaluate(()=>Promise.all([document.fonts.ready,...[...document.images].map(image=>image.decode())]));
  return page.locator('.page-v2').evaluate(fitSlide);
}
async function browserTest(run){const browser=await chromium.launch({headless:true});try{const page=await browser.newPage({viewport:{width:1500,height:1000}});await run(page)}finally{await browser.close()}}

test('a final orphan in two columns uses the full last row only when that saves measured space',()=>browserTest(async page=>{
  const nodes=[node('title','Contenuti da distribuire',{kind:'heading',role:'title',style:{font_size:24}}),
    node('columns','',{kind:'group',style:{flow:'columns',columns:[1,1],gap:24}}),
    ...Array.from({length:7},(_,i)=>node('p'+i,'Concetto '+i+'. '+'Una spiegazione completa con parole e frasi leggibili. '.repeat(6),
      {parent:'columns',source:'Manuale, pagina 3',style:{font_size:24}}))];
  const p=project(nodes,{theme:'ink'});p.slides[0].content.page.style.gap=28;
  const before=structuredClone(p),report=await render(page,p);
  assert.equal(report.overflow,false);assert(report.height<=828);assert(report.neededHeight<=828);
  const measured=await page.locator('.page-v2').evaluate(frame=>{
    const group=frame.querySelector('[data-page-node="columns"]'),last=frame.querySelector('[data-page-node="p6"]'),previous=frame.querySelector('[data-page-node="p5"]');
    return {span:last.style.gridColumn,lastWidth:last.clientWidth,groupWidth:group.clientWidth,previousWidth:previous.clientWidth,
      text:[...frame.querySelectorAll('[data-page-text]')].map(element=>({id:element.dataset.pageText,text:element.textContent})),sources:[...frame.querySelectorAll('.v2-source')].map(element=>element.textContent)};
  });
  assert.equal(measured.span,'1 / -1');assert(Math.abs(measured.lastWidth-measured.groupWidth)<=1);assert(measured.previousWidth<measured.lastWidth*.6);
  assert.deepEqual(measured.text,nodes.filter(item=>item.kind!=='group').map(item=>({id:item.id,text:item.text})));
  assert.deepEqual(measured.sources,Array(7).fill('Manuale, pagina 3'));assert.deepEqual(p,before);
  for(let pass=0;pass<3;pass++)assert.deepEqual(await page.locator('.page-v2').evaluate(fitSlide),report,'Orphan fitting resets its baseline on every pass');
}));

test('V2 uses the four selected aspect ratios, fixed dimensions and at most fifteen percent adaptive growth',()=>browserTest(async page=>{
  for(const [format,base] of Object.entries({'16:9':720,'4:3':960,'16:10':800,'1:1':1280}))for(const mode of ['fixed','adaptive']){
    const p=project([heading,node('body','Due elementi non richiedono una pagina lunga.')],{slide_format:format,canvas_mode:mode});
    const report=await render(page,p);
    assert.equal(report.baseHeight,base);assert.equal(report.maxHeight,mode==='fixed'?base:Math.ceil(base*1.15));
    assert.equal(report.height,base);assert.equal(report.overflow,false);assert.equal(report.fontScale,1);
    assert.equal(await page.locator('.page-v2').getAttribute('data-page-base-height'),String(base));
    const imposed=await page.locator('.page-v2').evaluate((frame,source)=>new Function('return ('+source+')(arguments[0],{targetHeight:99999})')(frame),fitSlide.toString());
    assert.equal(imposed.height,report.maxHeight,'A requested export height cannot bypass the format cap');
  }
}));

test('V2 compacts independent content and fonts before growing; repeated and hidden fits never shrink cumulatively',()=>browserTest(async page=>{
  const p=project(density(6)),before=structuredClone(p),report=await render(page,p);
  assert.equal(report.overflow,false);assert(report.height>=720&&report.height<=828);assert(report.compact>0);assert(report.fontScale<1);
  const baseline=await page.locator('.page-v2').evaluate(frame=>({height:frame.offsetHeight,fonts:[...frame.querySelectorAll('.v2-text')].map(node=>getComputedStyle(node).fontSize),order:[...frame.querySelectorAll('[data-page-text]')].map(node=>node.dataset.pageText)}));
  assert.equal(parseFloat(baseline.fonts[0])>=32,true);for(const value of baseline.fonts.slice(1))assert(parseFloat(value)>=20);
  for(const width of [390,1500,390,1500]){
    await page.setViewportSize({width,height:1000});
    await page.locator('.page-v2').evaluate((frame,w)=>{frame.style.transform='scale('+Math.min(1,w/1280)+')';frame.style.transformOrigin='top left'},width);
    for(let pass=0;pass<3;pass++)assert.deepEqual(await page.locator('.page-v2').evaluate(fitSlide),report);
  }
  await page.locator('.page-v2').evaluate(frame=>frame.style.display='none');
  const hidden=await page.locator('.page-v2').evaluate(fitSlide);assert.equal(hidden.deferred,true);
  await page.locator('.page-v2').evaluate(frame=>frame.style.display='flex');
  assert.deepEqual(await page.locator('.page-v2').evaluate(fitSlide),report);
  const after=await page.locator('.page-v2').evaluate(frame=>({height:frame.offsetHeight,fonts:[...frame.querySelectorAll('.v2-text')].map(node=>getComputedStyle(node).fontSize),order:[...frame.querySelectorAll('[data-page-text]')].map(node=>node.dataset.pageText)}));
  assert.deepEqual(after,baseline);assert.deepEqual(p,before,'All fitting stays derived; original manual settings remain JSON');
}));

test('independent siblings can reflow without reordering or squeezing code into tiny columns',()=>browserTest(async page=>{
  const nodes=[heading,...Array.from({length:9},(_,i)=>node('card'+i,'Idea '+i+': '+prose,{role:'callout',style:{font_size:28,padding:24,surface:'soft'}})),node('code','const example = "ancora modificabile";',{kind:'code',style:{font_size:24}})];
  const p=project(nodes),report=await render(page,p);assert.equal(report.overflow,false);assert.equal(report.reflowed,true);assert(report.height<=828);
  const result=await page.locator('.page-v2').evaluate(frame=>({order:[...frame.querySelectorAll('[data-page-text]')].map(node=>node.dataset.pageText),
    code:frame.querySelector('[data-page-node="code"]').getBoundingClientRect().width/(frame.getBoundingClientRect().width/1280),
    overlaps:[...frame.querySelectorAll('.v2-node')].flatMap((a,i,all)=>all.slice(i+1).filter(b=>{const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return Math.min(x.right,y.right)-Math.max(x.left,y.left)>1&&Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top)>1}).map(b=>a.dataset.pageNode+'/'+b.dataset.pageNode))}));
  assert.deepEqual(result.order,nodes.map(n=>n.id));assert(result.code>=1100);assert.deepEqual(result.overlaps,[]);
}));

test('impossible text is capped and reported, never cropped, hidden, scrolled internally or reduced below readable minima',()=>browserTest(async page=>{
  const code=Array.from({length:150},(_,i)=>'riga '+i+' <script>testo letterale</script>').join('\n');
  const p=project([...density(35),node('code',code,{kind:'code',style:{font_size:24}}),node('caption','Didascalia ancora leggibile',{role:'caption',style:{font_size:18}})]);
  const report=await render(page,p);assert.equal(report.height,828);assert.equal(report.overflow,true);assert(report.neededHeight>2000);assert(report.overflowNodes.length>0);
  const values=await page.locator('.page-v2').evaluate(frame=>({height:frame.offsetHeight,overflow:frame.dataset.overflow,needed:Number(frame.dataset.neededHeight),
    text:[...frame.querySelectorAll('[data-page-text]')].map(element=>({id:element.dataset.pageText,text:element.textContent,size:parseFloat(getComputedStyle(element).fontSize)})),
    hidden:[frame,...frame.querySelectorAll('.v2-root,.v2-node,.v2-text')].filter(element=>{const style=getComputedStyle(element);return ['hidden','clip','scroll','auto'].includes(style.overflowY)||style.display==='none'||style.visibility==='hidden'||style.textOverflow==='ellipsis'}).length}));
  assert.equal(values.height,828);assert.equal(values.overflow,'true');assert.equal(values.needed,report.neededHeight);assert.equal(values.hidden,0);
  assert.equal(values.text.find(n=>n.id==='code').text,code);assert(values.text.find(n=>n.id==='code').size>=18);assert(values.text.find(n=>n.id==='caption').size>=14);
  for(const item of values.text.filter(n=>n.id.startsWith('p')))assert(item.size>=20);assert(values.text.find(n=>n.id==='title').size>=32);
  assert.equal(await page.locator('script').count(),0);assert.equal(values.text.length,p.slides[0].content.page.nodes.filter(n=>n.kind!=='group').length);
  const fixed=await render(page,{...p,canvas_mode:'fixed'});assert.equal(fixed.height,720);assert.equal(fixed.maxHeight,720);assert.equal(fixed.overflow,true);
}));

test('media preserve their aspect ratios and legible minimum sizes; a portrait diagram is not squeezed to fake success',()=>browserTest(async page=>{
  const asset='manim-'+'a'.repeat(64)+'.png',svg=(w,h)=>'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="'+w+'" height="'+h+'"></svg>');
  const nodes=[heading,node('columns','',{kind:'group',style:{flow:'columns',columns:[1.5,1],gap:28}}),
    node('diagram','',{kind:'diagram',parent:'columns',asset_id:asset,style:{}}),node('photo','Foto senza ritaglio',{kind:'image',parent:'columns',asset_id:'photo.png',style:{}})];
  const p=project(nodes),report=await render(page,p,{assets:{[asset]:svg(1200,700),'photo.png':svg(800,600)}});
  assert.equal(report.overflow,false);assert.equal(report.mediaOverflow,false);assert(report.height<=828);
  const media=await page.locator('.v2-media img').evaluateAll(images=>images.map(image=>{const r=image.getBoundingClientRect(),aspect=image.naturalWidth/image.naturalHeight,w=Math.min(r.width,r.height*aspect);return {width:w,height:w/aspect,fit:getComputedStyle(image).objectFit}}));
  assert(media[0].width>=598&&media[0].height>=218);assert(media[1].width>=280&&media[1].height>=160);for(const image of media)assert.equal(image.fit,'contain');
  p.slides[0].content.page.nodes=[heading,node('portrait','',{kind:'diagram',asset_id:asset,style:{}})];
  const portrait=await render(page,p,{assets:{[asset]:svg(600,1600)}});assert.equal(portrait.overflow,true);assert.equal(portrait.height,828);assert(portrait.neededHeight>portrait.maxHeight);
}));
