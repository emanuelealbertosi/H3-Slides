import './browser-env.mjs';
import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,fitSlide} from '../static/deck.mjs';

// DOM-only synthetic fixtures. No export, screenshots, model, network or user project.
let browser;
before(async()=>{browser=await chromium.launch({headless:true})});
after(async()=>{await browser?.close()});
const paragraph=(heading='Concetto',text='Un esempio breve conserva il significato e resta leggibile.')=>({kind:'explanation',heading,text,source:''});
const content=overrides=>({title:'Schede adattive',subtitle:'',layout:'freeform',layout_locked:true,freeform_base:'editorial',
  canvas_height:720,blocks:[paragraph('Primo'),paragraph('Secondo')],bullets:[],sources:[],notes:'',diagram:{kind:'none'},
  freeform:{heading:{x:48,y:60,w:1184,h:120},'block-0':{x:48,y:220,w:550,h:180},'block-1':{x:682,y:220,w:550,h:180}},...overrides});
const code=lines=>({kind:'code',language:'python',heading:'Esempio Python',
  text:Array.from({length:lines},(_,i)=>'    print('+i+')').join('\n'),source:''});
async function render(c,{scale=1,mode='adaptive',media=false}={}){
  const page=await browser.newPage({viewport:{width:1400,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{errors.push('Unexpected request: '+route.request().url());return route.abort()});
  const project={title:'Test sintetico',theme:'paper',font:'Arial',canvas_mode:mode,graphic_style:'studio',
    use_manim_diagrams:media,use_source_images:true,visual_assets:[]};
  const s={content:c,...(media?{diagram_render:{engine:'manim',asset:'diagram.png'}}:{})};
  const svg='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#bddbd3"/></svg>');
  await page.setContent('<!doctype html><style>'+slideCSS+'body{margin:0}.slide-frame{transform:scale('+scale+');transform-origin:top left}</style>'+slideHTML(project,s,0,media?{diagram:svg,image:svg}:''));
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(img=>img.decode()))});
  return {page,frame:page.locator('.slide-frame'),errors};
}
function geometry(frame){
  const root=frame.getBoundingClientRect(),scale=root.width/1280;
  const rect=e=>{const r=e.getBoundingClientRect();return {x:(r.left-root.left)/scale,y:(r.top-root.top)/scale,w:r.width/scale,h:r.height/scale}};
  const objects=[...frame.querySelectorAll('[data-free-key]')].filter(e=>e.getClientRects().length);
  const placements=Object.fromEntries(objects.map(e=>[e.dataset.freeKey,rect(e)]));
  const issues=[],bottom=(frame.querySelector('.footer').getBoundingClientRect().top-root.top)/scale;
  const within=(p,owner)=>p.x>=owner.x-1&&p.y>=owner.y-1&&p.x+p.w<=owner.x+owner.w+1&&p.y+p.h<=owner.y+owner.h+1;
  for(const element of objects){
    const box=rect(element),key=element.dataset.freeKey;
    if(!within(box,{x:0,y:0,w:1280,h:bottom}))issues.push(key+' leaves the usable canvas');
    if(!element.matches('.visual'))for(const child of element.querySelectorAll('h1,h2,p,.subtitle,.prose-source,.bullet-text')){
      if(!child.getClientRects().length)continue;
      if(!within(rect(child),box))issues.push(key+' clips '+child.tagName);
      if(child.scrollWidth>child.clientWidth+2||child.scrollHeight>child.clientHeight+2)issues.push(key+' has overflowing text');
    }
  }
  for(let i=0;i<objects.length;i++)for(let j=i+1;j<objects.length;j++){
    const a=rect(objects[i]),b=rect(objects[j]);
    if(Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)>1&&Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)>1)
      issues.push(objects[i].dataset.freeKey+' collides with '+objects[j].dataset.freeKey);
  }
  return {height:frame.offsetHeight,placements,issues,fonts:[...frame.querySelectorAll('h1,h2,p')].map(e=>getComputedStyle(e).fontSize)};
}
async function assertValid(frame,result){
  assert.equal(result.overflow,false,JSON.stringify(result));
  const actual=await frame.evaluate(geometry);assert.deepEqual(actual.issues,[]);
  assert.equal(actual.height,result.height);
  for(const [key,p] of Object.entries(result.placements||{}))for(const coordinate of ['x','y','w','h'])
    assert.ok(Math.abs(actual.placements[key][coordinate]-p[coordinate])<=1,key+' '+coordinate+' matches the returned placement');
  return actual;
}

async function resizeBox(frame,key,placement,options={}){
  await frame.evaluate((element,{key,placement})=>{
    const target=element.querySelector('[data-free-key="'+key+'"]');
    for(const [axis,value] of Object.entries(placement)){
      target.dataset['free'+axis.toUpperCase()]=String(value);target.style.setProperty('--free-'+axis,value+'px');
    }
  },{key,placement});
  return frame.evaluate(fitSlide,{resizeKey:key,...options});
}

test('valid freeform stays unchanged at normal and scaled preview sizes',async()=>{
  for(const scale of [1,.43]){
    const c=content(),original=structuredClone(c),{page,frame,errors}=await render(c,{scale});
    try{
      const before=await frame.evaluate(geometry),result=await frame.evaluate(fitSlide),after=await assertValid(frame,result);
      assert.equal(result.adjusted,false);assert.deepEqual(result.placements,c.freeform);
      assert.deepEqual(after.placements,before.placements);assert.deepEqual(after.fonts,before.fonts);
      const second=await frame.evaluate(fitSlide);assert.deepEqual(second.placements,result.placements);assert.equal(second.height,result.height);
      assert.deepEqual(c,original);assert.deepEqual(errors,[]);
    }finally{await page.close()}
  }
});

test('switching a measured automatic layout to freeform preserves its geometry',async()=>{
  const c=content({layout:'editorial',layout_locked:false,freeform:{}}),{page,frame}=await render(c);
  try{
    const initial=await frame.evaluate(fitSlide);
    const placements=await frame.evaluate((element,base)=>{
      const root=element.getBoundingClientRect(),scale=root.width/1280,placements={};
      for(const child of element.querySelectorAll('[data-free-key]')){
        const r=child.getBoundingClientRect(),p={x:Math.round((r.left-root.left)/scale),y:Math.round((r.top-root.top)/scale),w:Math.round(r.width/scale),h:Math.round(r.height/scale)};
        placements[child.dataset.freeKey]=p;
        for(const key of ['x','y','w','h']){child.dataset['free'+key.toUpperCase()]=String(p[key]);child.style.setProperty('--free-'+key,p[key]+'px')}
      }
      element.dataset.candidates='["freeform"]';element.dataset.freeBase=base.layout;element.dataset.freeCompact=String(base.compact);
      element.dataset.canvasHeight=String(base.height);return placements;
    },initial);
    const result=await frame.evaluate(fitSlide);await assertValid(frame,result);
    assert.deepEqual(result.placements,placements);assert.equal(result.height,initial.height);
  }finally{await page.close()}
});

test('a 44px title expands for title and subtitle without shrinking fonts or clipping',async()=>{
  const c=content({subtitle:'Un sottotitolo deve rimanere completamente visibile'});c.freeform.heading.h=44;
  const {page,frame}=await render(c);
  try{
    const text=await frame.textContent(),fonts=(await frame.evaluate(geometry)).fonts;
    const result=await frame.evaluate(fitSlide);const measured=await assertValid(frame,result);
    assert.ok(result.placements.heading.h>44);assert.deepEqual(measured.fonts,fonts);assert.equal(await frame.textContent(),text);
  }finally{await page.close()}
});

test('comparison to freeform ignores editor buttons taller than the subtitle',async()=>{
  const c=content({layout:'comparison',subtitle:'Un progetto locale, pronto da modificare',freeform:{},
    title:'Modifica verificata nel browser',heading_align:'center',blocks:[paragraph('Uno'),paragraph('Due'),paragraph('Tre')]});
  const {page,frame}=await render(c,{mode:'fixed'});
  try{
    await page.addStyleTag({content:'.deletable-element{position:relative}.element-delete{position:absolute;right:7px;top:7px;width:34px;height:34px;padding:0;opacity:0;pointer-events:none}'});
    await frame.evaluate(element=>{
      for(const target of element.querySelectorAll('h1,.subtitle,.prose-box')){
        target.classList.add('deletable-element');const button=document.createElement('button');
        button.className='element-delete';button.textContent='Remove';target.append(button);
      }
    });
    const chromeBefore=await frame.locator('.element-delete').evaluateAll(nodes=>nodes.map(n=>n.outerHTML));
    const fitted=await frame.evaluate(fitSlide);assert.equal(fitted.overflow,false);
    const before=await frame.evaluate((element,base)=>{
      const root=element.getBoundingClientRect(),scale=root.width/1280,placements={};
      for(const child of element.querySelectorAll('[data-free-key]')){
        const r=child.getBoundingClientRect(),p={x:Math.round((r.left-root.left)/scale),y:Math.round((r.top-root.top)/scale),w:Math.round(r.width/scale),h:Math.round(r.height/scale)};
        placements[child.dataset.freeKey]=p;
        for(const key of ['x','y','w','h']){child.dataset['free'+key.toUpperCase()]=String(p[key]);child.style.setProperty('--free-'+key,p[key]+'px')}
      }
      element.dataset.candidates='["freeform"]';element.dataset.freeBase=base.layout;element.dataset.freeCompact=String(base.compact);
      element.dataset.canvasHeight=String(base.height);return placements;
    },fitted);
    const converted=await frame.evaluate(fitSlide);
    assert.equal(converted.overflow,false,'Editor controls cannot turn a valid slide into an overflow');
    assert.deepEqual(converted.placements,before,'Every valid rectangle, including heading height, remains unchanged');
    assert.equal(converted.height,fitted.height);
    assert.deepEqual(await frame.locator('.element-delete').evaluateAll(nodes=>nodes.map(n=>n.outerHTML)),chromeBefore,'Controls are restored byte for byte');
    assert.deepEqual((await frame.evaluate(fitSlide)).placements,before,'Repeated live fit cannot accumulate button height');
  }finally{await page.close()}
});

test('overlapping rectangles are repaired deterministically while unrelated geometry is preserved',async()=>{
  const c=content();c.freeform['block-1']={...c.freeform['block-0']};
  const {page,frame}=await render(c);
  try{
    assert.ok((await frame.evaluate(geometry)).issues.some(issue=>issue.includes('collides')));
    const result=await frame.evaluate(fitSlide);await assertValid(frame,result);
    assert.deepEqual(result.placements.heading,c.freeform.heading);assert.deepEqual(result.placements['block-0'],c.freeform['block-0']);
    assert.notDeepEqual(result.placements['block-1'],c.freeform['block-1']);
    assert.deepEqual((await frame.evaluate(fitSlide)).placements,result.placements);
  }finally{await page.close()}
});

test('a resized anchor stays pinned and displaces only the necessary boxes',async()=>{
  const c=content();c.freeform['block-0']={x:48,y:220,w:1184,h:240};c.freeform['block-1'].h=220;
  const {page,frame}=await render(c);
  try{
    const result=await frame.evaluate(fitSlide,{anchorKey:'block-0'});await assertValid(frame,result);
    assert.deepEqual(result.placements['block-0'],c.freeform['block-0']);assert.deepEqual(result.placements.heading,c.freeform.heading);
    assert.ok(result.placements['block-1'].y>=460);assert.ok(result.height>720);
  }finally{await page.close()}
});

test('explicit resize removes unused height across layout bases and scaled previews',async()=>{
  for(const base of ['editorial','comparison','cards','steps','stack','focus'])for(const scale of [1,.43]){
    const c=content({freeform_base:base,blocks:[{...paragraph(),source:'Libro, pagina 2'}]});
    c.freeform['block-0']={x:48,y:220,w:700,h:420};
    const {page,frame}=await render(c,{scale});
    try{
      await frame.evaluate(fitSlide);const before=await frame.evaluate(geometry);
      const requested={x:48,y:220,w:700,h:220};
      const result=await resizeBox(frame,'block-0',requested),actual=await assertValid(frame,result);
      assert.deepEqual(result.placements['block-0'],requested,base+' may remove empty vertical space');
      assert.equal(result.resize.constrained,false);assert.ok(result.resize.minHeight<220);
      assert.deepEqual(actual.fonts,before.fonts);assert.deepEqual(result.resize.requested,requested);
      const reload=await frame.evaluate(fitSlide);assert.deepEqual(reload.placements,result.placements,'Ordinary saved fit retains the reduced rectangle');
    }finally{await page.close()}
  }
});

test('narrow text wraps at constant font size and reports its true minimum height',async()=>{
  const c=content({blocks:[paragraph('Concetto','Una spiegazione accurata collega le cause agli effetti attraverso un esempio leggibile. '.repeat(3))]});
  c.freeform['block-0']={x:48,y:200,w:900,h:420};
  const {page,frame}=await render(c);
  try{
    const fonts=(await frame.evaluate(geometry)).fonts,text=await frame.locator('.prose-box').textContent();
    const requested={x:48,y:200,w:350,h:100},narrow=await resizeBox(frame,'block-0',requested);
    await assertValid(frame,narrow);
    assert.equal(narrow.placements['block-0'].w,350);assert.equal(narrow.placements['block-0'].x,48);assert.equal(narrow.placements['block-0'].y,200);
    assert.equal(narrow.resize.constrained,true);assert.equal(narrow.resize.reason,'content-minimum');
    assert.deepEqual(narrow.resize.constraints,['height']);assert.ok(narrow.resize.minHeight>100);
    assert.equal(narrow.placements['block-0'].h,narrow.resize.minHeight);
    const wide=await resizeBox(frame,'block-0',{...requested,w:1000,h:200});await assertValid(frame,wide);
    assert.equal(wide.placements['block-0'].w,1000);assert.equal(wide.placements['block-0'].h,200);
    assert.ok(wide.placements['block-0'].h<narrow.placements['block-0'].h,'Widening and shortening do not retain old wrapped height');
    assert.deepEqual((await frame.evaluate(geometry)).fonts,fonts);assert.equal(await frame.locator('.prose-box').textContent(),text);
  }finally{await page.close()}
});

test('code resize clamps to the measured line width without wrapping, clipping or silent reset',async()=>{
  const c=content({blocks:[{...code(2),text:'print("Un esempio di codice non deve essere tagliato")\nprint(2)'}]});
  c.freeform['block-0']={x:48,y:200,w:1100,h:330};
  const {page,frame}=await render(c);
  try{
    const text=await frame.locator('.kind-code p').textContent(),before=await frame.evaluate(geometry);
    const requested={x:48,y:200,w:180,h:180},result=await resizeBox(frame,'block-0',requested);
    await assertValid(frame,result);assert.equal(result.resize.constrained,true);
    assert.ok(result.resize.minWidth>180);assert.equal(result.placements['block-0'].w,result.resize.minWidth);
    assert.ok(result.placements['block-0'].w<1100,'Fits at the real minimum, not the previous width');
    assert.equal(result.placements['block-0'].h,180);assert.ok(result.resize.constraints.includes('width'));
    assert.deepEqual((await frame.evaluate(geometry)).fonts,before.fonts);assert.equal(await frame.locator('.kind-code p').textContent(),text);
  }finally{await page.close()}
});

test('a pre-existing narrow code line cannot veto shrinking a neighbouring roomy explanation',async()=>{
  // Reproduces the real failure geometry with synthetic code/text: the code
  // spills horizontally by about 11px before any edit to the blue prose box.
  const text=Array.from({length:28},(_,index)=>index===10?'x'.repeat(40)+' = 1':'print('+index+')').join('\n');
  const c=content({canvas_height:936,freeform_base:'cards',freeform_compact:true,image_id:'photo.png',
    blocks:[{...code(28),text},{...paragraph('',
      'Una spiegazione collega i dati e le operazioni attraverso un esempio leggibile e verificabile. '.repeat(4)),source:'Esempio generato, pagina 12'}],
    freeform:{heading:{x:48,y:53,w:1184,h:72},'block-0':{x:48,y:139,w:434,h:737},
      'block-1':{x:496,y:139,w:434,h:737},visual:{x:948,y:139,w:284,h:737}}});
  const {page,frame}=await render(c,{media:true});
  try{
    const before=await frame.locator('.kind-code p').evaluate(element=>({width:element.clientWidth,scroll:element.scrollWidth,text:element.textContent}));
    assert.ok(before.scroll>before.width+2,'Overflow predates the resize gesture');
    const prepared=await frame.evaluate(fitSlide);await assertValid(frame,prepared);
    assert.equal(prepared.height,936,'No taller canvas is needed to fix a line width');
    assert.ok(prepared.placements['block-0'].w>434&&prepared.placements['block-0'].w<=448);
    assert.deepEqual({...prepared.placements['block-0'],w:434},c.freeform['block-0']);
    for(const key of ['heading','block-1','visual'])assert.deepEqual(prepared.placements[key],c.freeform[key]);
    const requested={...prepared.placements['block-1'],h:537};
    const reduced=await resizeBox(frame,'block-1',requested);await assertValid(frame,reduced);
    assert.deepEqual(reduced.placements['block-1'],requested);assert.equal(reduced.height,936);
    assert.equal(reduced.resize.constrained,false);assert.ok(reduced.resize.minHeight<537);
    for(const key of ['heading','block-0','visual'])assert.deepEqual(reduced.placements[key],prepared.placements[key]);
    assert.equal(await frame.locator('.kind-code p').textContent(),before.text);
    assert.deepEqual((await frame.evaluate(fitSlide)).placements,reduced.placements,'Saving/reloading fit keeps the narrower geometry');
  }finally{await page.close()}
});

test('west and north resize keep the opposite edge fixed at intrinsic limits',async()=>{
  for(const handle of ['w','nw','n','ne','sw']){
    const c=content({blocks:[{...code(2),heading:'Esempio di codice',text:'print("Il codice resta leggibile")\nprint(2)'}]});
    c.freeform['block-0']={x:48,y:220,w:900,h:250};
    const {page,frame}=await render(c);
    try{
      const requested={...c.freeform['block-0']};
      if(handle.includes('w')){requested.x=848;requested.w=100}
      if(handle.includes('n')){requested.y=426;requested.h=44}
      const result=await resizeBox(frame,'block-0',requested,{resizeHandle:handle});await assertValid(frame,result);
      const effective=result.placements['block-0'];assert.equal(result.resize.handle,handle);
      if(handle.includes('w')){assert.equal(effective.x+effective.w,948);assert.ok(effective.w>100)}
      else assert.equal(effective.x,requested.x);
      if(handle.includes('n')){assert.equal(effective.y+effective.h,470);assert.ok(effective.h>44)}
      else assert.equal(effective.y,requested.y);
      assert.equal(result.resize.reason,'content-minimum');
    }finally{await page.close()}
  }
});

test('oversized resize settles near the legal space limit instead of reverting to the starting box',async()=>{
  const c=content(),{page,frame}=await render(c,{mode:'fixed'});
  try{
    const baseline=await frame.evaluate(fitSlide);await assertValid(frame,baseline);
    const requested={x:48,y:220,w:1184,h:460};
    const result=await resizeBox(frame,'block-0',requested,{resizeFallback:baseline});await assertValid(frame,result);
    assert.equal(result.resize.reason,'space-limit');assert.equal(result.resize.constrained,true);
    assert.equal(result.resize.requested.h,460);assert.equal(result.height,720);
    assert.equal(result.placements['block-0'].w,1184);assert.ok(result.placements['block-0'].h>250&&result.placements['block-0'].h<460);
    assert.notDeepEqual(result.placements['block-0'],baseline.placements['block-0'],'The result is not a reset to gesture start');
    const onePixelPast=await resizeBox(frame,'block-0',{...result.placements['block-0'],h:result.placements['block-0'].h+1});
    assert.equal(onePixelPast.overflow,true,'The constrained rectangle reaches the legal limit within one pixel');
    const repeat=await resizeBox(frame,'block-0',{...requested,h:600},{resizeFallback:result});await assertValid(frame,repeat);
    assert.equal(repeat.resize.reason,'space-limit');assert.equal(repeat.placements['block-0'].w,1184);
    assert.ok(repeat.placements['block-0'].h>=result.placements['block-0'].h-1,'An overshooting pointer remains at the current legal edge');
    const final=await frame.evaluate(fitSlide);assert.deepEqual(final.placements,repeat.placements,'The constrained result survives ordinary saved layout fitting');
  }finally{await page.close()}
});

test('northward collision clamp preserves the bottom edge and does not hide title overlap',async()=>{
  const {page,frame}=await render(content(),{mode:'fixed'});
  try{
    const baseline=await frame.evaluate(fitSlide),original=baseline.placements['block-0'];
    const requested={...original,y:0,h:original.y+original.h};
    const result=await resizeBox(frame,'block-0',requested,{resizeHandle:'n',resizeFallback:baseline});await assertValid(frame,result);
    const p=result.placements['block-0'];assert.equal(p.y+p.h,original.y+original.h);
    assert.ok(p.y>0&&p.y<original.y);assert.equal(result.resize.reason,'space-limit');
    assert.ok(result.placements.heading.y>=p.y+p.h||result.placements.heading.y+result.placements.heading.h<=p.y+1,
      'The title may reflow, but never remains underneath the resized box');
  }finally{await page.close()}
});

test('canvas limits clamp immediately and an invalid fallback cannot authorize overflow',async()=>{
  const c=content({blocks:[paragraph()]});c.freeform['block-0']={x:48,y:220,w:700,h:250};
  const {page,frame}=await render(c,{mode:'fixed'});
  try{
    const boundary=await resizeBox(frame,'block-0',{x:48,y:220,w:700,h:850});await assertValid(frame,boundary);
    const usable=await frame.evaluate(el=>el.querySelector('.footer').getBoundingClientRect().top-el.getBoundingClientRect().top);
    assert.equal(boundary.placements['block-0'].h,Math.floor(usable)-220);assert.equal(boundary.resize.reason,'canvas-limit');
    const impossible={x:48,y:0,w:1184,h:680};
    const result=await resizeBox(frame,'block-0',impossible,{resizeFallback:{height:720,
      placements:{heading:{x:48,y:60,w:1184,h:120},'block-0':impossible}}});
    assert.equal(result.overflow,true,'Overlapping baseline is never accepted as an overflow waiver');
    assert.equal(await frame.getAttribute('data-overflow'),'true');
  }finally{await page.close()}
});

test('adaptive freeform grows for 26 and 40 code lines and reports impossible 70-line content',async()=>{
  for(const lines of [26,40,70]){
    const c=content({blocks:[code(lines)],freeform:{heading:{x:48,y:60,w:1184,h:120},'block-0':{x:48,y:200,w:1184,h:430}}});
    const {page,frame}=await render(c);
    try{
      const text=await frame.locator('.kind-code p').textContent(),font=await frame.locator('.kind-code p').evaluate(e=>getComputedStyle(e).fontSize);
      const result=await frame.evaluate(fitSlide);
      if(lines<70){await assertValid(frame,result);assert.ok(result.height>720&&result.height<=1440)}
      else{assert.equal(result.overflow,true);assert.ok((await frame.evaluate(geometry)).issues.length>0)}
      assert.equal(await frame.locator('.kind-code p').textContent(),text);
      assert.equal(await frame.locator('.kind-code p').evaluate(e=>getComputedStyle(e).fontSize),font);
    }finally{await page.close()}
  }
});

test('fixed mode enforces 720px; an explicit common canvas controls freeform and automatic layouts',async()=>{
  for(const layout of ['freeform','editorial']){
    const {page,frame}=await render(content({layout,canvas_height:936}),{mode:'fixed'});
    try{
      const normal=await frame.evaluate(fitSlide);await assertValid(frame,normal);assert.equal(normal.height,720);
      const common=await frame.evaluate(fitSlide,{targetHeight:936});await assertValid(frame,common);assert.equal(common.height,936);
      assert.equal(await frame.evaluate(e=>e.dataset.canvasHeight),'936');
      const again=await frame.evaluate(fitSlide);assert.equal(again.height,720);
    }finally{await page.close()}
  }
});

test('code and independent media survive freeform reflow, scaling and a second fit',async()=>{
  let expected;
  for(const scale of [1,.43]){
    const c=content({blocks:[code(18)],image_id:'photo.png',image_origin:'source',diagram:{kind:'manim',scene:{}},
      freeform:{heading:{x:48,y:60,w:1184,h:120},'block-0':{x:48,y:200,w:700,h:400},
        visual:{x:780,y:200,w:452,h:230},image:{x:780,y:455,w:452,h:195}}});
    const {page,frame,errors}=await render(c,{scale,media:true});
    try{
      const text=await frame.textContent(),urls=await frame.locator('img').evaluateAll(nodes=>nodes.map(n=>n.src));
      const result=await frame.evaluate(fitSlide);await assertValid(frame,result);
      assert.deepEqual(result.placements.visual,c.freeform.visual);assert.deepEqual(result.placements.image,c.freeform.image);
      assert.equal(await frame.textContent(),text);assert.deepEqual(await frame.locator('img').evaluateAll(nodes=>nodes.map(n=>n.src)),urls);
      if(expected)assert.deepEqual({height:result.height,placements:result.placements},expected);
      expected={height:result.height,placements:result.placements};
      const repeated=await frame.evaluate(fitSlide);assert.deepEqual(repeated.placements,result.placements);assert.equal(repeated.height,result.height);
      assert.deepEqual(errors,[]);
    }finally{await page.close()}
  }
});
