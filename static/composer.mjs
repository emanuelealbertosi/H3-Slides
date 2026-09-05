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
  return [...new Set([primary,...auto,visual?'visual-right':'editorial','cards','stack'])].filter(k=>
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
export function fitSlide(frame){
  const candidates=JSON.parse(frame.dataset.candidates||'["editorial"]');
  const apply=(layout,compact)=>{
    for(const c of [...frame.classList])if(c.startsWith('tpl-'))frame.classList.remove(c);
    frame.classList.add('tpl-'+layout);frame.classList.toggle('compact-spacing',compact);
    if(layout==='freeform'&&frame.dataset.freeBase)frame.classList.add('tpl-'+frame.dataset.freeBase);
    frame.dataset.layout=layout;
  };
  const inspect=()=>{
    const root=frame.getBoundingClientRect(),scale=root.width/1280||1;
    const footer=frame.querySelector('.footer').getBoundingClientRect();
    let excess=0;
    for(const e of frame.querySelectorAll('h1,.subtitle,.prose-box,.prose-box h2,.prose-box p,.prose-source,li,.bullet-text,.visual')){
      if(e.closest('.drag-preview-source'))continue;
      if(!e.getClientRects().length)continue;
      const r=e.getBoundingClientRect(),box=e.closest('.prose-box');
      const parent=box&&box!==e?box.getBoundingClientRect():null;
      excess+=Math.max(0,e.scrollWidth-e.clientWidth-2)+Math.max(0,e.scrollHeight-e.clientHeight-2);
      excess+=Math.max(0,(r.bottom-footer.top)/scale)+Math.max(0,(r.right-root.right)/scale);
      if(parent)excess+=Math.max(0,(r.bottom-parent.bottom)/scale)+Math.max(0,(r.right-parent.right)/scale);
    }
    return excess;
  };
  let best={layout:candidates[0],compact:false,excess:Infinity};
  const compactModes=candidates[0]==='freeform'?[frame.dataset.freeCompact==='true']:[false,true];
  for(const compact of compactModes)for(const layout of candidates){
    apply(layout,compact);const excess=inspect();
    if(excess<best.excess)best={layout,compact,excess};
    if(excess<1){frame.dataset.overflow='false';return {layout,overflow:false,adjusted:layout!==candidates[0],compact}}
  }
  apply(best.layout,best.compact);frame.dataset.overflow='true';
  return {layout:best.layout,overflow:true,adjusted:best.layout!==candidates[0],compact:best.compact};
}

export const composerCSS=`
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
.slide-frame.tpl-focus .prose-box:first-child h2{font-size:32px}
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
