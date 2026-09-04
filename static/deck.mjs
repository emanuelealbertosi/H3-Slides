import {layoutCandidates,composerCSS} from './composer.mjs';
import katex from './vendor/katex/katex.mjs';
export {layouts,layoutCandidates,fitSlide,visualAnchorAt} from './composer.mjs';
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const formulaHTML=(source,displayMode=false)=>{
  try{return katex.renderToString(source,{displayMode,throwOnError:false,strict:'warn',trust:false,output:'htmlAndMathml'})}
  catch{return esc(source)}
};
export function mathHTML(value){
  const source=String(value??'');
  let found=false,last=0,html='';
  const pattern=/\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)/g;
  for(const match of source.matchAll(pattern)){
    found=true;html+=esc(source.slice(last,match.index));
    html+=formulaHTML(match[1]??match[2],match[1]!==undefined);
    last=match.index+match[0].length;
  }
  if(found)return html+esc(source.slice(last));
  if(/^\s*(?:[A-Za-z]\w*(?:\([^)]*\))?|[A-Za-z])\s*=/.test(source))
    return formulaHTML(source.replace(/^\s*y\s*=\s*/i,'y='),false);
  return esc(source);
}
const rawAttr=value=>' data-edit-raw="'+esc(value)+'"';
export const themes = {
  ink: {bg:'#141b2c',fg:'#f6f7fb',muted:'#c1c9d8',accent:'#b1f1ce'},
  paper: {bg:'#ffffff',fg:'#17243a',muted:'#526078',accent:'#18794e'},
  forest: {bg:'#153e35',fg:'#f6faf5',muted:'#d0dfd7',accent:'#e2edb0'}
};
const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
const mix=(a,b,t)=>'#'+rgb(a).map((v,i)=>Math.round(v*(1-t)+rgb(b)[i]*t).toString(16).padStart(2,'0')).join('');
const luminance=hex=>rgb(hex).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
export const contrast=(a,b)=>(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
export function autoText(bg){
  const dark='#17243a',light='#ffffff',a=contrast(bg,dark),b=contrast(bg,light);
  return a>=4.5&&a>=b?dark:b>=4.5?light:'#000000';
}
const validColor=value=>/^#[a-f0-9]{6}$/i.test(value);
export function themeFor(project){
  const base=themes[project.theme]||themes.ink;
  const bg=/^#[a-f0-9]{6}$/i.test(project.background_color)?project.background_color:base.bg;
  const d=project.theme_design||{},fg=validColor(d.text_color)?d.text_color:autoText(bg);
  const accent=/^#[a-f0-9]{6}$/i.test(project.accent_color)?project.accent_color:base.accent;
  return {bg,fg,heading:validColor(d.title_color)?d.title_color:fg,accent,muted:mix(bg,fg,.7),surface:mix(bg,fg,.065),line:mix(bg,fg,.18)};
}
export function visualFor(project,content,slide=null){
  const asset=project.use_manim_diagrams&&content.diagram?.kind!=='none'&&slide?.diagram_render?.engine==='manim'
    ?slide.diagram_render.asset:'';
  const diagram=Boolean(asset);
  return {diagram,image:asset||(!diagram&&project.use_source_images!==false?(content.image_id||''):'')};
}
export function templateFor(project,content,index=0,slide=null){
  const visual=visualFor(project,content,slide);
  return layoutCandidates(project,content,index,Boolean(visual.diagram||visual.image))[0];
}
export function blockColors(project,block,index=0){
  const t=themeFor(project),d=project.theme_design||{};
  const colors={explanation:mix(t.accent,'#ffffff',.78),example:'#dceeff',key:'#fff0c2',quote:'#eee2ff'};
  const custom=d[block.kind+'_color'];
  const bg=validColor(custom)?custom:block.kind==='explanation'&&index%2?mix(t.accent,'#ffffff',.9):(colors[block.kind]||colors.explanation);
  const fg=validColor(d.box_text_color)?d.box_text_color:autoText(bg);
  return {bg,fg,border:validColor(d.border_color)?d.border_color:mix(bg,fg,.3)};
}
export function contentBlocks(content){return content.blocks||[]}

export const slideCSS = '*{box-sizing:border-box}.slide-frame{width:1280px;height:720px;position:relative;overflow:hidden;font-family:var(--font,Arial),sans-serif;background:var(--bg);color:var(--fg);display:flex;flex-direction:column}.slide-frame .heading{flex:none}.slide-frame h1{color:var(--heading)}.slide-frame .slide-columns{display:flex}.slide-frame .footer{position:absolute;display:flex;justify-content:space-between;gap:20px;color:var(--muted);border-top:1px solid var(--line)}.slide-frame .footer span:first-child{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.slide-frame .katex-display{margin:.25em 0}.slide-frame .katex{font-size:1.04em}.slide-frame [data-edit-field] .katex{pointer-events:none}' + composerCSS;

export function slideHTML(project,slide,index,imageUrl=''){
  const c=slide.content,t=themeFor(project),visual=visualFor(project,c,slide),template=templateFor(project,c,index,slide);
  const candidates=layoutCandidates(project,c,index,Boolean(visual.diagram||visual.image));
  const font=['Arial','Calibri','Segoe UI','Georgia','Verdana','Consolas'].includes(project.font)?project.font:'Arial';
  const d=project.theme_design||{},card=blockColors(project,{kind:'explanation'});
  const style=Object.entries(t).map(([k,v])=>'--'+k+':'+v).join(';')+';--font:'+font+
    ';--card-bg:'+card.bg+';--card-fg:'+card.fg+';--card-border:'+card.border+';--card-border-width:'+(d.border_width??1)+'px'+
    ';--box-border-width:'+(d.border_width||0)+'px;--box-radius:'+(d.box_radius??18)+'px'+
    (d.title_size?';--title-size:'+d.title_size+'px':'')+(d.body_size?';--custom-body-size:'+d.body_size+'px':'');
  const point=(b,i)=>'<li><span class="bullet-mark">'+String(i+1).padStart(2,'0')+'</span><span class="bullet-text" data-edit-field="bullets" data-index="'+i+'"'+rawAttr(b)+'>'+mathHTML(b)+'</span></li>';
  const blocks=contentBlocks(c);
  const box=(b,i)=>{
    const colors=blockColors(project,b,i);
    return '<section class="prose-box kind-'+esc(b.kind)+'" data-block-index="'+i+'" style="--box-bg:'+colors.bg+';--box-fg:'+colors.fg+';--box-border:'+colors.border+'">'+
      '<div class="block-number">'+String(i+1).padStart(2,'0')+'</div>'+
      '<h2 data-edit-field="block-heading" data-index="'+i+'"'+rawAttr(b.heading)+'>'+mathHTML(b.heading)+'</h2>'+
      '<p data-edit-field="block-text" data-index="'+i+'"'+rawAttr(b.text)+'>'+mathHTML(b.text)+'</p>'+
      '<div class="prose-source" data-edit-field="block-source" data-index="'+i+'"'+rawAttr(b.source)+'>'+mathHTML(b.source)+'</div></section>';
  };
  return '<article class="slide-frame tpl-'+esc(template)+' density-'+esc(project.text_density||'detailed')+
    (visual.diagram||visual.image?' has-visual':'')+(visual.diagram?' has-diagram':'')+(blocks.reduce((n,b)=>n+b.text.length,0)>1100?' copy-dense':'')+
    ' heading-'+esc(c.heading_position||'top')+' heading-align-'+esc(c.heading_align||'left')+
    (d.title_size?' custom-title-size':'')+(d.body_size?' custom-body-size':'')+'" data-candidates="'+esc(JSON.stringify(candidates))+'" data-layout="'+esc(template)+'" style="'+style+';--item-count:'+(blocks.length||c.bullets?.length||1)+'">'+
    '<div class="slide-accent"></div>'+
    '<div class="kicker">H3 SLIDES <span>/ '+String(index+1).padStart(2,'0')+'</span></div><div class="heading">'+
    '<h1 data-edit-field="title"'+rawAttr(c.title)+'>'+mathHTML(c.title)+'</h1>'+
    (c.subtitle?'<p class="subtitle" data-edit-field="subtitle"'+rawAttr(c.subtitle)+'>'+mathHTML(c.subtitle)+'</p>':'')+'</div>'+
    '<div class="slide-columns"><div class="copy">'+(blocks.length?
      '<div class="prose-grid count-'+blocks.length+'">'+blocks.map(box).join('')+'</div>':
      '<ul>'+(c.bullets||[]).map((item,i)=>point(item,i).replace('<li>','<li data-bullet-index="'+i+'">')).join('')+'</ul>')+'</div>'+
    (visual.image&&imageUrl?'<img class="visual'+(visual.diagram?' diagram-render':'')+'" src="'+esc(imageUrl)+'" alt="'+
      (visual.diagram?'Diagramma renderizzato con Manim':'')+'">':'')+'</div>'+
    '<div class="footer"><span>'+esc(project.title)+'</span><span>'+String(index+1).padStart(2,'0')+'</span></div></article>';
}
