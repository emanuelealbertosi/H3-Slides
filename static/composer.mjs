// Shared semantic composition: model chooses meaning, renderer owns geometry.
export const layouts = {
  cover:'Copertina', editorial:'Editoriale', comparison:'Confronto', cards:'Griglia di concetti',
  steps:'Passaggi numerati', timeline:'Cronologia', focus:'Idea + approfondimento',
  quote:'Citazione in evidenza', 'visual-left':'Immagine a sinistra',
  'visual-right':'Immagine a destra', 'visual-left-wide':'Immagine grande a sinistra',
  'visual-right-wide':'Immagine grande a destra', 'visual-top':'Immagine panoramica in alto',
  'visual-bottom':'Immagine panoramica in basso', stack:'Paragrafi a fasce',
  freeform:'Libero · griglia invisibile'
};
const aliases={content:'auto',split:'visual-right',statement:'focus',minimal:'focus',prose:'editorial'};
export function layoutCandidates(project,content,index=0,visual=false){
  const blocks=content.blocks||[],items=blocks.length||content.bullets?.length||0;
  const length=blocks.reduce((n,b)=>n+b.text.length,0)||(content.bullets||[]).join('').length;
  const requested=aliases[content.layout]||content.layout||'auto';
  const preference=aliases[project.template]||project.template||'auto';
  let auto;
  if(visual)auto=length<550?['visual-left','visual-right','visual-top']:['visual-right','visual-left','editorial'];
  else if(blocks.some(b=>b.kind==='quote'))auto=['quote','editorial','stack'];
  else if(items<=1)auto=['focus','editorial','stack'];
  else if(items===2)auto=length>1000?['comparison','editorial','stack']:['editorial','focus','comparison','stack'];
  else auto=['cards','editorial','stack'];
  // A short panoramic strip is useful for photos, but makes diagram labels too small.
  if(project.use_manim_diagrams&&content.diagram?.kind&&content.diagram.kind!=='none')
    auto=auto.filter(k=>k!=='visual-top');
  if(content.layout_locked&&Object.hasOwn(layouts,requested)&&(!requested.startsWith('visual-')||visual))
    return [requested];
  const rotation=(index+Number(content.layout_variant||0))%auto.length;
  auto=[...auto.slice(rotation),...auto.slice(0,rotation)];
  const primary=Object.hasOwn(layouts,requested)?requested:content.layout_variant?auto[0]:Object.hasOwn(layouts,preference)?preference:auto[0];
  return [...new Set([primary,...auto,...(visual?['visual-left-wide','visual-right-wide','visual-bottom','visual-top']:[]),visual?'visual-right':'editorial','cards','stack'])].filter(k=>
    Object.hasOwn(layouts,k)&&(!k.startsWith('visual-')||visual)&&
    (k!=='comparison'||items===2)&&(k!=='timeline'||items>=2)&&
    (k!=='quote'||blocks.some(b=>b.kind==='quote')));
}

export function visualAnchorAt(x,y,width,height){
  const nx=Math.max(0,Math.min(1,x/Math.max(1,width)));
  const ny=Math.max(0,Math.min(1,y/Math.max(1,height)));
  if(ny<.3)return 'visual-top';
  if(ny>.7)return 'visual-bottom';
  if(nx<.2)return 'visual-left-wide';
  if(nx<.5)return 'visual-left';
  if(nx>.8)return 'visual-right-wide';
  return 'visual-right';
}

// Self-contained: same measured-fit code in preview, PDF, PPTX and Slidev.
export function fitSlide(frame,options={}){
  // Keep every helper inside this function: preview/export serialize it with evaluate().
  // Editor chrome is not slide content. In particular, a 34px delete button in a
  // 27px subtitle must not inflate its scrollHeight or trigger a false overflow.
  const controls=[...frame.querySelectorAll('.element-delete,.visual-actions,.free-resize-handle')]
    .map(element=>({element,style:element.getAttribute('style')}));
  for(const {element} of controls)element.style.setProperty('display','none','important');
  try{
  options=options&&typeof options==='object'?options:{};
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const candidates=JSON.parse(frame.dataset.candidates||'["editorial"]');
  const free=candidates[0]==='freeform',adaptive=frame.dataset.canvasMode==='adaptive';
  const imposed=Number.isFinite(options.targetHeight)?Math.round(clamp(options.targetHeight,720,1440)):null;
  const initialHeight=free&&adaptive?Math.round(clamp(Number(frame.dataset.canvasHeight)||720,720,1440)):720;
  const heights=imposed!==null?[imposed]:adaptive?[...new Set([initialHeight,...[720,792,864,936,1008,1152,1296,1440].filter(h=>h>=initialHeight)])]:[720];
  const visible=e=>e.getClientRects().length&&!e.closest('.drag-preview-source');
  const media=[...frame.querySelectorAll('.visual')].map(element=>{
    const img=element.matches('img')?element:element.querySelector('img');
    const aspect=img?.naturalWidth&&img?.naturalHeight?img.naturalWidth/img.naturalHeight:
      Number(element.dataset.mediaAspect)||1.5;
    let w=Number(element.dataset.mediaMinWidth)||0,h=Number(element.dataset.mediaMinHeight)||0;
    if(img&&element.dataset.visualKind==='image'){
      // Size the actual contained photograph, not its surrounding empty frame.
      w=Math.sqrt(90000*aspect);h=w/aspect;
      const limit=Math.min(1,1100/w,760/h);w*=limit;h*=limit;
    }
    // Freeform is an explicit manual override. In particular, never force a
    // previously valid 180px photo to grow to 300px while the user is shrinking
    // its empty surrounding frame. Automatic composition enforces readability.
    if(free){w=0;h=0}
    const credit=element.querySelector('.image-credit');
    return {element,img,aspect,w:Math.ceil(w),h:Math.ceil(h),credit:credit?credit.offsetHeight+6:0};
  });
  const diagram=media.find(m=>m.element.dataset.visualKind==='diagram');
  const photo=media.find(m=>m.element.dataset.visualKind==='image');
  frame.classList.toggle('media-stacked',!free&&media.length>1&&media.reduce((sum,m)=>sum+m.w,0)>1156);
  frame.style.setProperty('--diagram-height',Math.max(200,(diagram?.h||0)+(diagram?.credit||0))+'px');
  frame.style.setProperty('--photo-height',Math.max(180,(photo?.h||0)+(photo?.credit||0))+'px');
  frame.style.setProperty('--media-min-width',Math.max(0,...media.map(m=>m.w))+'px');
  frame.style.setProperty('--media-height',Math.max(180,...media.map(m=>m.h+m.credit))+'px');
  frame.style.setProperty('--diagram-column',diagram?.w?Math.min(900,Math.max(400,diagram.w))+'px':'1fr');
  const apply=(layout,compact)=>{
    for(const c of [...frame.classList])if(c.startsWith('tpl-'))frame.classList.remove(c);
    frame.classList.add('tpl-'+layout);frame.classList.toggle('compact-spacing',compact);
    if(layout==='freeform'&&frame.dataset.freeBase)frame.classList.add('tpl-'+frame.dataset.freeBase);
    frame.dataset.layout=layout;
  };
  const syncHeight=()=>{
    frame.dataset.canvasHeight=String(frame.offsetHeight);
    const preview=frame.parentElement;
    if(preview?.classList.contains('slide-preview'))preview.style.aspectRatio='1280 / '+frame.offsetHeight;
  };
  const intersection=(a,b)=>({w:Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x),h:Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)});
  const collision=(a,b)=>{const r=intersection(a,b);return r.w>1&&r.h>1};
  const inspect=()=>{
    const root=frame.getBoundingClientRect(),scale=root.width/1280||1;
    const footer=frame.querySelector('.footer')?.getBoundingClientRect();
    const bottom=footer?.top??root.bottom;
    const outside=(r,p)=>Math.max(0,(p.left-r.left)/scale-1)+Math.max(0,(p.top-r.top)/scale-1)+
      Math.max(0,(r.right-p.right)/scale-1)+Math.max(0,(r.bottom-p.bottom)/scale-1);
    let excess=0;
    let mediaExcess=0;
    for(const m of media){
      if(!m.img||!visible(m.element))continue;
      const box=m.img.getBoundingClientRect();
      const w=Math.min(box.width/scale,box.height/scale*m.aspect),h=w/m.aspect;
      mediaExcess+=Math.max(0,m.w-w-1)+Math.max(0,m.h-h-1);
    }
    excess+=mediaExcess;frame.dataset.mediaOverflow=String(mediaExcess>=1);
    for(const e of frame.querySelectorAll('.heading,h1,.subtitle,.prose-box,.prose-box h2,.prose-box p,.prose-source,li,.bullet-text,.visual')){
      if(!visible(e))continue;
      const r=e.getBoundingClientRect(),owner=e.closest('.heading,.prose-box,li,.visual');
      excess+=Math.max(0,e.scrollWidth-e.clientWidth-2)+Math.max(0,e.scrollHeight-e.clientHeight-2);
      excess+=outside(r,{left:root.left,top:root.top,right:root.right,bottom});
      if(owner&&owner!==e)excess+=outside(r,owner.getBoundingClientRect());
      if(e.closest('.prose-box')&&e.matches('h2,p,.prose-source')&&!e.querySelector('.katex')){
        const range=document.createRange();range.selectNodeContents(e);
        const bounds=(owner||e).getBoundingClientRect();
        for(const line of range.getClientRects())if(line.width&&line.height)excess+=outside(line,bounds);
      }
    }
    const objects=[...frame.querySelectorAll('.heading,.prose-box,li,.visual,.kicker')].filter(visible);
    for(let i=0;i<objects.length;i++)for(let j=i+1;j<objects.length;j++){
      if(objects[i].contains(objects[j])||objects[j].contains(objects[i]))continue;
      const a=objects[i].getBoundingClientRect(),b=objects[j].getBoundingClientRect();
      const w=(Math.min(a.right,b.right)-Math.max(a.left,b.left))/scale,h=(Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top))/scale;
      if(w>1&&h>1)excess+=Math.min(w,h);
    }
    return excess;
  };
  if(free){
    const compact=frame.dataset.freeCompact==='true';apply('freeform',compact);
    const root=frame.getBoundingClientRect(),scale=root.width/1280||1;
    // Recursive resize probes share intrinsic measurements only within this
    // call. Content, fonts and template stay identical throughout the gesture
    // projection, so repeated widths need not trigger repeated layout reads.
    const measurements=options._resizeMeasurements instanceof Map?options._resizeMeasurements:new Map();
    const entries=[...frame.querySelectorAll('[data-free-key]')].filter(visible).map((element,index)=>{
      const r=element.getBoundingClientRect(),value=(key,fallback)=>Number.isFinite(Number(element.dataset[key]))?Math.round(Number(element.dataset[key])):Math.round(fallback);
      const sizes=measurements.get(element.dataset.freeKey)||new Map();measurements.set(element.dataset.freeKey,sizes);
      return {element,key:element.dataset.freeKey,index,text:!element.matches('.visual'),originalStyle:element.getAttribute('style'),
        original:{x:value('freeX',(r.left-root.left)/scale),y:value('freeY',(r.top-root.top)/scale),
          w:Math.max(80,value('freeW',r.width/scale)),h:Math.max(44,value('freeH',r.height/scale))},sizes};
    });
    const put=(entry,p)=>{for(const key of ['x','y','w','h'])entry.element.style.setProperty('--free-'+key,p[key]+'px')};
    const sizeAt=(entry,width)=>{
      width=Math.round(width);if(entry.sizes.has(width))return entry.sizes.get(width);
      if(!entry.text){const m=media.find(m=>m.element===entry.element);return {h:Math.max(44,(m?.h||0)+(m?.credit||0)),horizontal:width<(m?.w||0)}}
      const e=entry.element,oldW=e.style.getPropertyValue('--free-w'),oldH=e.style.getPropertyValue('--free-h');
      e.style.setProperty('--free-w',width+'px');e.style.setProperty('--free-h','auto');
      // Natural box height includes padding, grid/flex rows, code lines and rendered math.
      const required=Math.ceil(Math.max(e.offsetHeight,e.scrollHeight));
      const horizontal=[e,...e.querySelectorAll('h1,h2,p,.subtitle,.prose-source,.bullet-text')]
        .some(child=>visible(child)&&child.scrollWidth>child.clientWidth+2);
      e.style.setProperty('--free-w',oldW);e.style.setProperty('--free-h',oldH);
      const result={h:Math.max(44,required),horizontal};entry.sizes.set(width,result);return result;
    };
    const minimumWidth=entry=>{
      if(!entry.text)return Math.max(80,media.find(m=>m.element===entry.element)?.w||0);
      if(entry.minimumWidth!==undefined)return entry.minimumWidth;
      if(!sizeAt(entry,80).horizontal)return entry.minimumWidth=80;
      // Code lines, formulas and unbreakable headings have a real horizontal
      // minimum. Trying only full-canvas widths misses small, repairable spills.
      if(sizeAt(entry,1280).horizontal)return entry.minimumWidth=1281;
      let low=80,high=1280;
      while(low<high){const middle=Math.floor((low+high)/2);if(sizeAt(entry,middle).horizontal)low=middle+1;else high=middle}
      return entry.minimumWidth=low;
    };
    const resizing=entries.find(e=>e.key===options.resizeKey);
    const resizeHandle=/^(n|ne|e|se|s|sw|w|nw)$/.test(options.resizeHandle)?options.resizeHandle:'se';
    const fromWest=resizeHandle.includes('w'),fromNorth=resizeHandle.includes('n');
    const footerRect=frame.querySelector('.footer')?.getBoundingClientRect();
    const footerInset=Math.max(40,footerRect?Math.ceil((root.bottom-footerRect.top)/scale):40);
    const expanded=entry=>{
      const maximumWidth=fromWest?entry.original.x+entry.original.w:1280-entry.original.x;
      const w=entry===resizing?Math.min(maximumWidth,Math.max(entry.original.w,minimumWidth(entry))):entry.text?entry.original.w:Math.max(entry.original.w,minimumWidth(entry));
      const maximumHeight=fromNorth?entry.original.y+entry.original.h:(imposed??(adaptive?1440:720))-footerInset-entry.original.y;
      const h=Math.max(entry===resizing?Math.min(entry.original.h,maximumHeight):entry.original.h,sizeAt(entry,w).h);
      const x=entry===resizing&&fromWest?entry.original.x+entry.original.w-w:entry.original.x;
      const y=entry===resizing&&fromNorth?entry.original.y+entry.original.h-h:entry.original.y;
      return {...entry.original,x,y,w,h};
    };
    const anchor=resizing||entries.find(e=>e.key===options.anchorKey);
    const ordered=[...entries].sort((a,b)=>(a===anchor?-1:b===anchor?1:0)||
      (a.key==='heading'?-1:b.key==='heading'?1:0)||a.original.y-b.original.y||a.original.x-b.original.x||a.index-b.index);
    const fixedObstacles=()=>{
      const r=frame.getBoundingClientRect(),s=r.width/1280||1;
      return [...frame.querySelectorAll('.kicker')].filter(visible).map(e=>{const b=e.getBoundingClientRect();return {x:(b.left-r.left)/s,y:(b.top-r.top)/s,w:b.width/s,h:b.height/s}});
    };
    let best=null;
    for(const height of heights){
      frame.style.height=height+'px';
      const r=frame.getBoundingClientRect(),s=r.width/1280||1;
      const footer=frame.querySelector('.footer')?.getBoundingClientRect();
      const bottom=Math.floor(footer?(footer.top-r.top)/s:height);
      const accepted=fixedObstacles(),placements={},deferred=[];
      const inside=p=>p.x>=0&&p.y>=0&&p.x+p.w<=1280&&p.y+p.h<=bottom;
      const fits=(entry,p)=>inside(p)&&!sizeAt(entry,p.w).horizontal&&!accepted.some(other=>collision(p,other));
      // Reserve every still-valid rectangle before moving anything. An enlarged anchor
      // has first claim, but unrelated boxes retain their exact original coordinates.
      for(const entry of ordered){
        const p=expanded(entry);
        if(fits(entry,p)){placements[entry.key]=p;accepted.push(p)}else deferred.push(entry);
      }
      for(const entry of deferred){
        const origin=expanded(entry);
        // Moving/resizing an item must not silently move that same item elsewhere.
        // Try a taller adaptive canvas first; the caller rejects impossible drops.
        if(entry===anchor){placements[entry.key]=origin;accepted.push(origin);continue}
        const widths=entry.text?[entry.original.w,Math.min(1184,1280-entry.original.x),1184,1280]:[entry.original.w,minimumWidth(entry)];
        if(entry.text&&sizeAt(entry,entry.original.w).horizontal)widths.push(minimumWidth(entry));
        if(entry.text)for(const rect of accepted)widths.push(rect.x-48-12,1232-(rect.x+rect.w+12));
        const alternatives=[];
        for(const w of [...new Set(widths.map(Math.round))].filter(w=>w>=80&&w<=1280)){
          const natural=sizeAt(entry,w);if(natural.horizontal)continue;
          const h=Math.max(entry.original.h,natural.h);
          const xs=[entry.original.x,48,0,1280-w,1232-w],ys=[entry.original.y,48,0,bottom-h];
          for(const rect of accepted){xs.push(rect.x,rect.x+rect.w+12,rect.x-w-12);ys.push(rect.y,rect.y+rect.h+12,rect.y-h-12)}
          for(const x of [...new Set(xs.map(Math.round))])for(const y of [...new Set(ys.map(Math.round))]){
            const p={x,y,w,h};if(!fits(entry,p))continue;
            const cost=Math.abs(x-entry.original.x)+Math.abs(y-entry.original.y)+2*Math.abs(w-entry.original.w)+(y<entry.original.y?12:0);
            alternatives.push({p,cost});
          }
        }
        alternatives.sort((a,b)=>a.cost-b.cost||a.p.y-b.p.y||a.p.x-b.p.x||a.p.w-b.p.w);
        const p=alternatives[0]?.p||origin;placements[entry.key]=p;accepted.push(p);
      }
      for(const entry of entries)put(entry,placements[entry.key]);
      const excess=inspect();
      const changed=entries.some(entry=>['x','y','w','h'].some(key=>placements[entry.key][key]!==entry.original[key]));
      const result={layout:'freeform',overflow:excess>=1,adjusted:changed,compact,height,placements};
      if(resizing){
        const requested={...resizing.original},effective={...placements[resizing.key]},constraints=[];
        const minWidth=minimumWidth(resizing),minHeight=sizeAt(resizing,effective.w).h;
        if(requested.w!==effective.w)constraints.push('width');
        if(requested.h!==effective.h)constraints.push('height');
        if(requested.x!==effective.x)constraints.push('left');
        if(requested.y!==effective.y)constraints.push('top');
        result.resize={key:resizing.key,handle:resizeHandle,requested,effective,minWidth,minHeight,
          constrained:constraints.length>0,constraints,
          reason:constraints.length?(requested.w<minWidth||requested.h<minHeight?'content-minimum':'canvas-limit'):''};
      }
      if(!best||excess<best.excess)best={excess,result};
      if(excess<1)break;
    }
    const result=best.result;frame.style.height=result.height+'px';
    for(const entry of entries){
      const p=result.placements[entry.key];
      if(['x','y','w','h'].every(key=>p[key]===entry.original[key])){
        if(entry.originalStyle===null)entry.element.removeAttribute('style');else entry.element.setAttribute('style',entry.originalStyle);
      }else put(entry,p);
      for(const key of ['x','y','w','h'])entry.element.dataset['free'+key.toUpperCase()]=String(p[key]);
    }
    frame.dataset.overflow=String(result.overflow);syncHeight();
    if(resizing&&result.overflow&&options.resizeFallback){
      const baseline=options.resizeFallback,requested={...resizing.original};
      const base=baseline.placements?.[resizing.key],height=Number(baseline.height);
      const legal=p=>p&&['x','y','w','h'].every(key=>Number.isFinite(p[key]))&&
        p.x>=0&&p.y>=0&&p.w>=80&&p.h>=44&&p.x+p.w<=1280&&p.y+p.h<=height-40;
      if(Number.isFinite(height)&&height>=720&&height<=1440&&(adaptive||height===720)&&
          entries.every(entry=>legal(baseline.placements?.[entry.key]))){
        const initial={placements:result.placements,height:result.height};
        const restore=(state)=>{
          frame.style.height=state.height+'px';frame.dataset.canvasHeight=String(state.height);
          for(const entry of entries){const p=state.placements[entry.key];put(entry,p);
            for(const key of ['x','y','w','h'])entry.element.dataset['free'+key.toUpperCase()]=String(p[key]);}
        };
        const anchorRect=(w,h)=>({...requested,w,h,
          x:fromWest?requested.x+requested.w-w:requested.x,
          y:fromNorth?requested.y+requested.h-h:requested.y});
        const trials=new Map();
        const trial=p=>{
          const identity=['x','y','w','h'].map(key=>p[key]).join(',');
          if(trials.has(identity))return trials.get(identity);
          restore(baseline);put(resizing,p);
          for(const key of ['x','y','w','h'])resizing.element.dataset['free'+key.toUpperCase()]=String(p[key]);
          // No fallback passed recursively: every trial uses the full normal
          // clipping/collision checks, without bypasses or recursive searches.
          const tested=fitSlide(frame,{resizeKey:resizing.key,resizeHandle,targetHeight:options.targetHeight,
            _resizeMeasurements:measurements});
          trials.set(identity,tested);return tested;
        };
        const baseResult=trial(base);
        const exactBaseline=!baseResult.overflow&&entries.every(entry=>['x','y','w','h']
          .every(key=>Math.abs(baseResult.placements[entry.key][key]-baseline.placements[entry.key][key])<=1));
        if(exactBaseline){
          let closest=baseResult;
          const distance=candidate=>['x','y','w','h'].reduce((sum,key)=>sum+Math.pow(candidate.placements[resizing.key][key]-requested[key],2),0);
          const consider=candidate=>{if(!candidate.overflow&&(distance(candidate)<distance(closest)||
            (distance(candidate)===distance(closest)&&candidate.height<closest.height)))closest=candidate};
          // Two axis probes can approach a blocked corner from either side.
          // At most eleven bisections reach pixel precision over a 1280px
          // canvas. Cached duplicate probes keep ordinary edge gestures cheap.
          consider(trial(anchorRect(requested.w,base.h)));
          consider(trial(anchorRect(base.w,requested.h)));
          const start={...closest.placements[resizing.key]};let low=0,high=1;
          for(let step=0;step<11;step++){
            const ratio=(low+high)/2,w=Math.round(start.w+(requested.w-start.w)*ratio),
              h=Math.round(start.h+(requested.h-start.h)*ratio);
            const candidate=trial(anchorRect(w,h));
            if(candidate.overflow)high=ratio;else{low=ratio;consider(candidate)}
          }
          restore(closest);frame.dataset.overflow='false';syncHeight();
          const effective={...closest.placements[resizing.key]},constraints=[];
          for(const [key,name] of [['w','width'],['h','height'],['x','left'],['y','top']])
            if(effective[key]!==requested[key])constraints.push(name);
          return {...closest,adjusted:true,resize:{...closest.resize,key:resizing.key,handle:resizeHandle,
            requested,effective,constrained:constraints.length>0,constraints,reason:constraints.length?'space-limit':''}};
        }
        restore(initial);frame.dataset.overflow=String(result.overflow);syncHeight();
      }
    }
    return result;
  }
  let best={layout:candidates[0],compact:false,excess:Infinity,height:720};
  for(const height of heights){frame.style.height=height+'px';
    for(const compact of [false,true])for(const layout of candidates){
      apply(layout,compact);const excess=inspect();
      if(excess<best.excess)best={layout,compact,excess,height};
      if(excess<1){frame.dataset.overflow='false';syncHeight();return {layout,overflow:false,adjusted:layout!==candidates[0],compact,height}}
    }
  }
  frame.style.height=best.height+'px';apply(best.layout,best.compact);syncHeight();frame.dataset.overflow='true';
  return {layout:best.layout,overflow:true,adjusted:best.layout!==candidates[0],compact:best.compact,height:best.height};
  }finally{
    for(const {element,style} of controls){
      if(style===null)element.removeAttribute('style');else element.setAttribute('style',style);
    }
  }
}

export const composerCSS=`
.slide-frame.style-studio .prose-box:nth-child(even),.slide-frame.style-editorial .prose-box{background:transparent;color:var(--fg);border:0;border-left:4px solid var(--accent);border-radius:0;box-shadow:none}
.slide-frame.style-studio .prose-box:nth-child(3){border-radius:36px 8px 36px 8px}
.slide-frame.style-vivid .prose-box{border:0;border-radius:28px 6px 28px 6px;box-shadow:0 15px 25px #0002}
.slide-frame.style-vivid .prose-box:nth-child(even){border-radius:6px 28px 6px 28px}
.slide-frame.style-editorial .prose-box h2{color:var(--heading);font-family:Georgia,serif}
.slide-frame:not(.style-classic) .slide-accent{height:12px;width:38%;border-radius:0 0 12px 0}
.slide-frame:not(.style-classic).tpl-cover .heading{padding-bottom:22px;border-bottom:7px solid var(--accent)}
.slide-frame{padding:36px 48px 60px;--body-size:22px;isolation:isolate}
.slide-frame .slide-accent{position:absolute;top:0;left:0;width:100%;height:7px;background:var(--accent);z-index:-1}
.slide-frame .kicker{font:700 12px var(--font);letter-spacing:2px;margin-bottom:14px;color:var(--muted)}
.slide-frame .kicker{order:0}.slide-frame .heading{order:1}.slide-frame .slide-columns{order:2}
.slide-frame.heading-bottom .heading{order:3;margin-top:16px}.slide-frame.heading-bottom .slide-columns{margin-top:8px}
.slide-frame.heading-align-center .heading{text-align:center}.slide-frame.heading-align-right .heading{text-align:right}
.slide-frame h1{font-size:46px;line-height:1.3;max-height:none;overflow:visible;letter-spacing:-1px;margin:0 0 12px;font-weight:800}
.slide-frame .subtitle{font-size:21px;line-height:1.3;max-height:none;overflow:visible;margin:0}
.slide-frame .slide-columns{margin-top:22px;gap:28px;align-items:stretch;flex:1;min-height:0}
.slide-frame .copy{display:flex;flex:1;min-width:0;min-height:0}
.slide-frame .prose-grid{display:grid;width:100%;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;align-items:stretch;min-height:0}
.slide-frame .prose-grid.count-1{grid-template-columns:1fr}
.slide-frame .prose-box{padding:24px;background:var(--box-bg);color:var(--box-fg);border:var(--box-border-width) solid var(--box-border);border-radius:var(--box-radius);box-shadow:0 8px 20px #00000018;display:flex;flex-direction:column;gap:12px;min-width:0;min-height:0}
.slide-frame .prose-box h2{font-size:25px;font-weight:800;line-height:1.3;margin:0;letter-spacing:-.3px}
.slide-frame .prose-box p{font-size:22px;line-height:1.3;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
.slide-frame .prose-box.kind-quote p{font-style:italic}
.slide-frame .prose-source{font:12px/1.2 var(--font);margin-top:auto;padding-top:6px;overflow-wrap:anywhere}
.slide-frame .prose-box h2:empty,.slide-frame .prose-source:empty{display:none}
.slide-frame .visual{width:33%;height:100%;max-height:none;min-height:0;object-fit:contain;align-self:stretch;border-radius:var(--box-radius)}
.slide-frame .visual.diagram svg{display:block;width:100%;height:100%}
.slide-frame ul{margin:0;padding:0;list-style:none;display:grid;align-content:start;gap:22px;width:100%;min-height:0}
.slide-frame li{font-size:26px;line-height:1.32;display:flex;gap:16px;min-width:0;min-height:0}
.slide-frame .bullet-text{white-space:pre-wrap;overflow-wrap:anywhere}
.slide-frame .bullet-mark{color:var(--muted);font:700 20px var(--font);padding-top:3px;flex:none}
.slide-frame .block-number{display:none;font:800 25px var(--font)}
.slide-frame .footer{left:48px;right:48px;bottom:21px;font:12px var(--font);padding-top:10px}
.slide-frame.density-complete .prose-box p,.slide-frame.copy-dense .prose-box p{font-size:20px;line-height:1.3}
.slide-frame.has-visual .prose-box{padding:20px}
.slide-frame.has-visual .prose-box p{font-size:20px;line-height:1.3}
.slide-frame.has-visual .prose-box h2{font-size:23px}
.slide-frame.has-visual li{font-size:23px}
.slide-frame.tpl-cover h1{font-size:64px;max-width:1050px;letter-spacing:-1.8px}
.slide-frame.tpl-cover .prose-box{box-shadow:none;border-left:5px solid var(--box-border);border-radius:0}
.slide-frame.tpl-cover .prose-grid{align-content:start}
.slide-frame.tpl-cover.has-visual{padding-left:480px;position:relative}
.slide-frame.tpl-cover.has-visual .visual{position:absolute;left:48px;top:75px;width:390px;height:540px}
.slide-frame.tpl-cover.has-visual .prose-grid{grid-template-columns:1fr}
.slide-frame.tpl-editorial:not(.has-visual) .prose-grid.count-2{grid-template-columns:1.25fr 1fr}
.slide-frame.tpl-editorial:not(.has-visual) .prose-grid.count-3{grid-template-columns:1.15fr 1fr}
.slide-frame.tpl-editorial:not(.has-visual) .prose-grid.count-3 .prose-box:first-child{grid-row:span 2}
.slide-frame.tpl-editorial .prose-box:first-child{box-shadow:none;border-left:5px solid var(--box-border);border-radius:0}
.slide-frame.tpl-comparison .prose-box{border-top:5px solid var(--box-border);border-radius:0 0 var(--box-radius) var(--box-radius)}
.slide-frame.tpl-comparison .prose-box h2{padding-bottom:10px;border-bottom:1px solid var(--box-border)}
.slide-frame.tpl-comparison ul{grid-template-columns:repeat(2,minmax(0,1fr))}
.slide-frame.tpl-cards .prose-grid.count-3{grid-template-columns:repeat(3,minmax(0,1fr))}
.slide-frame.tpl-cards ul{grid-template-columns:repeat(2,minmax(0,1fr));align-content:stretch}
.slide-frame.tpl-cards li{padding:24px;background:var(--card-bg);color:var(--card-fg);border-radius:var(--box-radius);border:var(--card-border-width) solid var(--card-border);box-shadow:0 8px 20px #00000018}
.slide-frame.tpl-cards .bullet-mark{display:none}
.slide-frame.tpl-steps .prose-grid,.slide-frame.tpl-stack .prose-grid{grid-template-columns:1fr}
.slide-frame.tpl-steps .prose-box{display:grid;grid-template-columns:42px minmax(0,1fr);gap:8px 16px;align-content:center}
.slide-frame.tpl-steps .block-number{display:block;grid-row:span 3}
.slide-frame.tpl-steps .prose-source{grid-column:2;margin:0}
.slide-frame.tpl-steps .bullet-mark{display:block}
.slide-frame.tpl-timeline .prose-grid{grid-template-columns:repeat(var(--item-count),minmax(0,1fr));align-items:start}
.slide-frame.tpl-timeline .prose-box{border-top:5px solid var(--box-border);border-radius:0;padding-top:20px;box-shadow:none}
.slide-frame.tpl-timeline .block-number{display:block;font-size:36px;line-height:1}
.slide-frame.tpl-timeline ul{grid-template-columns:repeat(var(--item-count),minmax(0,1fr))}
.slide-frame.tpl-timeline li{flex-direction:column;border-top:4px solid var(--accent);padding-top:20px}
.slide-frame.tpl-focus:not(.has-visual) .prose-grid.count-2{grid-template-columns:1.6fr 1fr}
.slide-frame.tpl-focus .prose-grid.count-1 .prose-box h2{font-size:32px}
.slide-frame.tpl-focus .prose-grid.count-1{max-width:1000px;align-self:center;margin:auto}
.slide-frame.tpl-focus .prose-grid.count-1 p{font-size:28px}
.slide-frame.tpl-focus .prose-box:first-child{border-left:6px solid var(--box-border)}
.slide-frame.tpl-quote .prose-box.kind-quote{border-left:6px solid var(--box-border);box-shadow:none}
.slide-frame.tpl-quote .prose-box.kind-quote p{font-family:Georgia,serif;font-size:25px;line-height:1.35}
.slide-frame.tpl-visual-left .slide-columns{flex-direction:row-reverse}
.slide-frame.tpl-visual-left-wide .slide-columns{flex-direction:row-reverse}
.slide-frame.tpl-visual-left .prose-grid,.slide-frame.tpl-visual-right .prose-grid,.slide-frame.tpl-visual-left-wide .prose-grid,.slide-frame.tpl-visual-right-wide .prose-grid{grid-template-columns:1fr}
.slide-frame.tpl-visual-left .visual,.slide-frame.tpl-visual-right .visual{width:37%}
.slide-frame.tpl-visual-left-wide .visual,.slide-frame.tpl-visual-right-wide .visual{width:52%}
.slide-frame.tpl-visual-top .slide-columns{display:grid;grid-template-columns:1fr;grid-template-rows:180px minmax(0,1fr);gap:20px}
.slide-frame.tpl-visual-top .visual{grid-row:1;width:100%;height:180px}
.slide-frame.tpl-visual-top .copy{grid-row:2}
.slide-frame.tpl-visual-top.has-diagram .slide-columns{grid-template-rows:280px minmax(0,1fr)}
.slide-frame.tpl-visual-top.has-diagram .visual{height:280px}
.slide-frame.tpl-visual-bottom .slide-columns{display:grid;grid-template-columns:1fr;grid-template-rows:minmax(0,1fr) 180px;gap:20px}
.slide-frame.tpl-visual-bottom .copy{grid-row:1}
.slide-frame.tpl-visual-bottom .visual{grid-row:2;width:100%;height:180px}
.slide-frame.tpl-visual-bottom.has-diagram .slide-columns{grid-template-rows:minmax(0,1fr) 280px}
.slide-frame.tpl-visual-bottom.has-diagram .visual{height:280px}
.slide-frame.tpl-stack .prose-box{display:grid;grid-template-columns:minmax(130px,23%) minmax(0,1fr);gap:12px 25px;align-content:center;border-radius:var(--box-radius);padding:20px 26px;box-shadow:none}
.slide-frame.tpl-stack .prose-source{grid-column:2}
.slide-frame.compact-spacing{padding-top:28px}
.slide-frame.compact-spacing .kicker{margin-bottom:9px}
.slide-frame.compact-spacing .slide-columns{margin-top:14px;gap:18px}
.slide-frame.compact-spacing .prose-grid{gap:14px}
.slide-frame.compact-spacing .prose-box{padding:16px;gap:8px}
.slide-frame.custom-title-size h1{font-size:var(--title-size)}
.slide-frame.custom-body-size .prose-box p,.slide-frame.custom-body-size li{font-size:var(--custom-body-size)!important}
.slide-frame.has-multiple-visuals:not(.tpl-freeform){padding-left:48px}
.slide-frame.has-multiple-visuals:not(.tpl-freeform) .slide-columns{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);grid-template-rows:minmax(0,1.25fr) minmax(0,1fr);gap:20px 28px}
.slide-frame.has-multiple-visuals:not(.tpl-freeform) .copy{grid-column:1;grid-row:1 / 3}
.slide-frame.has-multiple-visuals:not(.tpl-freeform) .prose-grid{grid-template-columns:1fr}
.slide-frame.has-multiple-visuals:not(.tpl-freeform) .visual{position:static;grid-column:2;width:100%;height:100%;min-width:0;min-height:0}
.slide-frame.has-multiple-visuals:not(.tpl-freeform) [data-visual-kind="diagram"]{grid-row:1}
.slide-frame.has-multiple-visuals:not(.tpl-freeform) [data-visual-kind="image"]{grid-row:2}
.slide-frame.has-multiple-visuals.tpl-visual-left:not(.tpl-freeform) .slide-columns,.slide-frame.has-multiple-visuals.tpl-visual-left-wide:not(.tpl-freeform) .slide-columns{grid-template-columns:minmax(0,1fr) minmax(0,1.45fr)}
.slide-frame.has-multiple-visuals.tpl-visual-left:not(.tpl-freeform) .copy,.slide-frame.has-multiple-visuals.tpl-visual-left-wide:not(.tpl-freeform) .copy{grid-column:2}
.slide-frame.has-multiple-visuals.tpl-visual-left:not(.tpl-freeform) .visual,.slide-frame.has-multiple-visuals.tpl-visual-left-wide:not(.tpl-freeform) .visual{grid-column:1}
.slide-frame.has-multiple-visuals.tpl-visual-top:not(.tpl-freeform) .slide-columns,.slide-frame.has-multiple-visuals.tpl-visual-bottom:not(.tpl-freeform) .slide-columns{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:260px minmax(0,1fr)}
.slide-frame.has-multiple-visuals.tpl-visual-top:not(.tpl-freeform) .copy{grid-column:1 / 3;grid-row:2}
.slide-frame.has-multiple-visuals.tpl-visual-bottom:not(.tpl-freeform) .slide-columns{grid-template-rows:minmax(0,1fr) 260px}
.slide-frame.has-multiple-visuals.tpl-visual-bottom:not(.tpl-freeform) .copy{grid-column:1 / 3;grid-row:1}
.slide-frame.has-multiple-visuals.tpl-visual-top:not(.tpl-freeform) .visual{grid-row:1}
.slide-frame.has-multiple-visuals.tpl-visual-bottom:not(.tpl-freeform) .visual{grid-row:2}
.slide-frame.has-multiple-visuals:is(.tpl-visual-top,.tpl-visual-bottom):not(.tpl-freeform) [data-visual-kind="diagram"]{grid-column:1}
.slide-frame.has-multiple-visuals:is(.tpl-visual-top,.tpl-visual-bottom):not(.tpl-freeform) [data-visual-kind="image"]{grid-column:2}
.slide-frame.has-multiple-visuals:is(.tpl-visual-top,.tpl-visual-bottom):not(.tpl-freeform) .prose-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
/* Reserve readable media dimensions, keeping the original aspect ratio. */
.slide-frame.has-visual:not(.tpl-freeform) .visual{min-width:min(var(--media-min-width,0px),100%)}
.slide-frame.has-multiple-visuals:not(.tpl-freeform) .visual{min-width:0}
.slide-frame:is(.tpl-visual-top,.tpl-visual-bottom):not(.tpl-freeform) .visual{height:100%}
.slide-frame.has-visual.tpl-visual-top:not(.tpl-freeform) .slide-columns{grid-template-rows:var(--media-height,280px) minmax(0,1fr)}
.slide-frame.has-visual.tpl-visual-bottom:not(.tpl-freeform) .slide-columns{grid-template-rows:minmax(0,1fr) var(--media-height,280px)}
.slide-frame.has-multiple-visuals:is(.tpl-visual-top,.tpl-visual-bottom):not(.tpl-freeform) .slide-columns{grid-template-columns:minmax(0,var(--diagram-column,1fr)) minmax(0,1fr)}
.slide-frame.media-stacked:is(.tpl-visual-top,.tpl-visual-bottom):not(.tpl-freeform) .slide-columns{grid-template-columns:1fr}
.slide-frame.media-stacked.tpl-visual-top:not(.tpl-freeform) .slide-columns{grid-template-rows:var(--diagram-height) var(--photo-height) minmax(0,1fr)}
.slide-frame.media-stacked.tpl-visual-bottom:not(.tpl-freeform) .slide-columns{grid-template-rows:minmax(0,1fr) var(--diagram-height) var(--photo-height)}
.slide-frame.media-stacked:is(.tpl-visual-top,.tpl-visual-bottom):not(.tpl-freeform) :is(.copy,[data-visual-kind]){grid-column:1}
.slide-frame.media-stacked.tpl-visual-top:not(.tpl-freeform) .copy{grid-row:3}
.slide-frame.media-stacked.tpl-visual-top:not(.tpl-freeform) [data-visual-kind=diagram]{grid-row:1}
.slide-frame.media-stacked.tpl-visual-top:not(.tpl-freeform) [data-visual-kind=image]{grid-row:2}
.slide-frame.media-stacked.tpl-visual-bottom:not(.tpl-freeform) [data-visual-kind=diagram]{grid-row:2}
.slide-frame.media-stacked.tpl-visual-bottom:not(.tpl-freeform) [data-visual-kind=image]{grid-row:3}
/* Dense rows keep the citation beside the paragraph, not in an
   extra row below it. This preserves font sizes and leaves manual frames alone. */
.slide-frame.has-multiple-visuals.tpl-stack.compact-spacing:not(.tpl-freeform) .slide-columns{grid-template-columns:minmax(0,1.8fr) minmax(0,1fr)}
.slide-frame.tpl-stack.compact-spacing:not(.tpl-freeform) .prose-box{padding:8px;gap:4px 12px;grid-template-columns:minmax(160px,25%) minmax(0,1fr)}
.slide-frame.tpl-stack.compact-spacing:not(.tpl-freeform) .prose-box h2{overflow-wrap:anywhere;align-self:start;grid-column:1;grid-row:1}
.slide-frame.tpl-stack.compact-spacing:not(.tpl-freeform) .prose-source{grid-column:1;grid-row:2;padding-top:0;margin-top:0;align-self:end}
.slide-frame.tpl-stack.compact-spacing:not(.tpl-freeform) .prose-box p{grid-column:2;grid-row:1 / span 2}
.slide-frame.has-visual:is(.tpl-stack,.tpl-cards).compact-spacing:not(.has-multiple-visuals):not(.tpl-freeform) .visual{width:24%}
.slide-frame.has-visual.tpl-stack.compact-spacing:not(.has-multiple-visuals):not(.tpl-freeform) .prose-box{grid-template-columns:minmax(160px,28%) minmax(0,1fr)}
.slide-frame.has-visual.tpl-cards.compact-spacing:not(.has-multiple-visuals):not(.tpl-freeform):has(.prose-grid.count-4) .prose-box{padding:8px;gap:4px}
.slide-frame.has-visual.tpl-cards.compact-spacing:not(.has-multiple-visuals):not(.tpl-freeform) .prose-box h2{overflow-wrap:anywhere}
/* Four longer headings can use two rows of cards instead of narrow stack labels. */
.slide-frame.has-multiple-visuals.tpl-cards.compact-spacing:not(.tpl-freeform):has(.prose-grid.count-4) .slide-columns{grid-template-columns:minmax(0,2.1fr) minmax(0,1fr)}
.slide-frame.has-multiple-visuals.tpl-cards.compact-spacing:not(.tpl-freeform):has(.prose-grid.count-4) .prose-grid.count-4{grid-template-columns:repeat(2,minmax(0,1fr))}
.slide-frame.has-multiple-visuals.tpl-cards.compact-spacing:not(.tpl-freeform):has(.prose-grid.count-4) .prose-box{padding:8px;gap:4px}
.slide-frame.has-multiple-visuals.tpl-cards.compact-spacing:not(.tpl-freeform):has(.prose-grid.count-4) .prose-box h2{overflow-wrap:anywhere}
.slide-frame [contenteditable="plaintext-only"]{outline:2px solid var(--accent);outline-offset:4px;min-width:40px;cursor:text}
.slide-frame.tpl-freeform{display:block;padding:0!important}
.slide-frame.tpl-freeform .kicker{position:absolute;left:48px;top:24px;margin:0}
.slide-frame.tpl-freeform .slide-columns,.slide-frame.tpl-freeform .copy,.slide-frame.tpl-freeform .prose-grid,.slide-frame.tpl-freeform ul{display:contents}
.slide-frame.tpl-freeform .heading,.slide-frame.tpl-freeform .prose-box,.slide-frame.tpl-freeform li,.slide-frame.tpl-freeform .visual{
  position:absolute!important;left:var(--free-x);top:var(--free-y);
  width:var(--free-w)!important;height:var(--free-h)!important;
  min-width:0;min-height:0;max-width:none;max-height:none;margin:0!important;overflow:hidden
}
.slide-frame.tpl-freeform .heading{display:flex;flex-direction:column;justify-content:center}
.slide-frame.tpl-freeform .heading h1{margin:0}.slide-frame.tpl-freeform .heading .subtitle{margin-top:8px}
.slide-frame.tpl-freeform .visual{object-fit:contain;align-self:auto}
.slide-frame.tpl-freeform .footer{left:48px;right:48px;bottom:21px}
`;
