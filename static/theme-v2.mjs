// App-owned visual recipes. Model values select bounded tokens, never HTML/CSS.
export const V2_THEME_FONTS=['Arial','Calibri','Segoe UI','Georgia','Verdana','Consolas'];
const families={
  classic:{title:50,body:24,radius:18,heading:'',weight:700},
  editorial:{title:58,body:25,radius:4,heading:'Georgia',weight:700},
  modern:{title:60,body:25,radius:24,heading:'Segoe UI',weight:800},
  playful:{title:64,body:25,radius:30,heading:'Verdana',weight:800},
  technical:{title:50,body:24,radius:8,heading:'Consolas',weight:700},
  minimal:{title:60,body:24,radius:10,heading:'Segoe UI',weight:600}
};
const roles=new Set(['auto','title','subtitle','eyebrow','lead','body','callout','example','quote','stat','step','caption']);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const valid=value=>typeof value==='string'&&/^#[a-f\d]{6}$/i.test(value);
const color=(value,fallback)=>valid(value)?value:fallback;
const number=(value,fallback,min,max)=>Number.isFinite(Number(value))?Math.max(min,Math.min(max,Number(value))):fallback;
const mix=(a,b,t)=>'#'+[1,3,5].map(i=>Math.round(parseInt(a.slice(i,i+2),16)*(1-t)+parseInt(b.slice(i,i+2),16)*t).toString(16).padStart(2,'0')).join('');
const luminance=value=>[1,3,5].map(i=>parseInt(value.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
export const themeV2Contrast=(a,b)=>(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
function readable(stops,preferred){
  const score=fg=>Math.min(...stops.map(bg=>themeV2Contrast(bg,fg)));
  if(valid(preferred)&&score(preferred)>=4.5)return preferred;
  return ['#17243a','#ffffff','#000000'].sort((a,b)=>score(b)-score(a))[0];
}
function paint(background,preferred,secondary=null,strength=.2){
  let end=secondary?mix(background,secondary,strength):background,stops=[background,end],foreground=readable(stops,preferred);
  while(secondary&&Math.min(...stops.map(bg=>themeV2Contrast(bg,foreground)))<4.5&&strength>.001){
    strength/=2;end=mix(background,secondary,strength);stops=[background,end];foreground=readable(stops,preferred);
  }
  return {background,foreground,stops,gradient:secondary?'linear-gradient(135deg, '+background+' 0%, '+end+' 100%)':''};
}
export function resolveV2Theme(project={},base={}){
  const d=project.theme_design||{},family=Object.hasOwn(families,d.visual_family)?d.visual_family:'classic',recipe=families[family];
  const enabled=family!=='classic'||d.background_style==='gradient'||valid(d.secondary_color)||V2_THEME_FONTS.includes(d.heading_font)||
    ['none','lifted'].includes(d.shadow_style)||['stripe','corner'].includes(d.decoration)||Boolean(d.design_note?.trim());
  const defaults={ink:['#141b2c','#b1f1ce'],paper:['#ffffff','#18794e'],forest:['#153e35','#e2edb0']}[project.theme]||['#141b2c','#b1f1ce'];
  const background=color(project.background_color,color(base.bg,defaults[0])),accent=color(project.accent_color,color(base.accent,defaults[1]));
  const secondary=color(d.secondary_color,mix(accent,background,.4)),canvas=paint(background,color(d.text_color,base.fg),d.background_style==='gradient'?secondary:null,.16);
  const font=V2_THEME_FONTS.includes(project.font)?project.font:'Arial',headingFont=V2_THEME_FONTS.includes(d.heading_font)?d.heading_font:recipe.heading||font;
  const size=value=>Number(value)>0;
  const titleSize=size(d.title_size)?number(d.title_size,recipe.title,28,76):recipe.title,bodySize=size(d.body_size)?number(d.body_size,recipe.body,18,32):recipe.body;
  const surfaces={
    soft:paint(color(d.explanation_color,mix(background,canvas.foreground,.075)),d.box_text_color),
    accent:paint(accent,d.box_text_color),
    dark:paint(mix(background,'#101b30',.8),d.box_text_color),
    paper:paint('#ffffff',d.box_text_color),
    example:paint(color(d.example_color,mix(secondary,'#ffffff',.83)),d.box_text_color),
    key:paint(color(d.key_color,mix(accent,'#ffffff',.82)),d.box_text_color),
    quote:paint(color(d.quote_color,mix(secondary,'#ffffff',.88)),d.box_text_color),
    gradient:paint(accent,d.box_text_color,secondary,.26)
  };
  const shadowStyle=['none','soft','lifted'].includes(d.shadow_style)?d.shadow_style:'soft';
  return {enabled,family,canvas,accent,secondary,font,headingFont,titleSize,bodySize,
    headingColor:readable(canvas.stops,color(d.title_color,canvas.foreground)),muted:readable(canvas.stops,mix(background,canvas.foreground,.72)),
    line:color(d.border_color,color(base.line,mix(background,canvas.foreground,.18))),
    radius:number(d.box_radius,recipe.radius,0,64),borderWidth:number(d.border_width,family==='technical'?1:0,0,6),
    shadow:shadowStyle==='none'?'none':shadowStyle==='lifted'?'0 16px 36px #10234324':'0 8px 22px #10234312',
    decoration:['stripe','corner'].includes(d.decoration)?d.decoration:'none',weight:recipe.weight,surfaces};
}
export function resolveV2Role(node,firstHeading){
  if(roles.has(node.role)&&node.role!=='auto')return node.role;
  if(node.kind==='heading')return node.id===firstHeading?'title':'subtitle';
  if(['image','diagram'].includes(node.kind))return 'caption';
  return node.kind==='group'?'auto':'body';
}
export function resolveV2Node(theme,node,role,parentPaint=theme.canvas){
  const s=node.style||{},media=['image','diagram'].includes(node.kind),card=['callout','example','quote','stat','step'].includes(role);
  const defaultSurface={callout:'soft',example:'example',quote:'quote',stat:['modern','playful'].includes(theme.family)?'gradient':'key',step:'soft'}[role]||
    (node.kind==='code'?'dark':'none');
  const surface=s.surface==='plain'?'none':Object.hasOwn(theme.surfaces,s.surface)?s.surface:defaultSurface;
  const ownPaint=theme.surfaces[surface]||null,currentPaint=ownPaint||parentPaint;
  const heading=['title','subtitle','stat'].includes(role);
  const sizes={title:theme.titleSize,subtitle:Math.min(44,theme.bodySize+10),eyebrow:18,lead:Math.min(34,theme.bodySize+4),stat:Math.min(76,theme.titleSize+6),caption:18};
  const preferred=heading?theme.headingColor:role==='eyebrow'?theme.accent:role==='caption'?theme.muted:currentPaint.foreground;
  const color=readable(currentPaint.stops,preferred);
  const style={...s,surface,font_size:Number(s.font_size)>0&&Number(s.font_size)!==24?s.font_size:sizes[role]||theme.bodySize,
    padding:Number(s.padding)>0?s.padding:card||node.kind==='code'?24:0,
    radius:Number(s.radius)>0?s.radius:ownPaint||media?theme.radius:0};
  const border=Boolean(s.border)||role==='step'&&theme.borderWidth>0;
  return {role,style,surface,paint:currentPaint,ownPaint,color,
    font:heading||role==='quote'&&theme.family==='editorial'?theme.headingFont:theme.font,
    weight:s.bold?700:heading?theme.weight:role==='eyebrow'?700:400,
    borderWidth:border?Math.max(1,theme.borderWidth):0,borderColor:theme.line,
    leftBorder:['callout','quote'].includes(role)?{width:role==='callout'?4:3,color:readable(currentPaint.stops,theme.accent)}:null,
    shadow:s.shadow||card||media?theme.shadow:'none',
    extra:(role==='eyebrow'?'letter-spacing:.13em;text-transform:uppercase;':'')+(role==='quote'?'font-style:italic;':'')+
      (heading?'letter-spacing:'+(theme.family==='technical'?'-.02em':'-.035em')+';':'')};
}
export function themeV2DecorationHTML(theme){
  if(!theme.enabled||theme.decoration==='none')return '';
  const style=theme.decoration==='stripe'?'position:absolute;left:0;top:0;width:100%;height:8px;background:'+theme.accent+';':
    'position:absolute;right:18px;top:18px;width:26px;height:26px;border-top:3px solid '+theme.accent+';border-right:3px solid '+theme.accent+';';
  return '<span data-v2-decoration="'+theme.decoration+'" aria-hidden="true" style="'+esc(style+'pointer-events:none;')+'"></span>';
}
export function themeV2PreviewHTML(project){
  const t=resolveV2Theme(project),panel=t.surfaces.soft,second=t.surfaces.example;
  return '<span class="theme-mini theme-v2-mini" aria-hidden="true" style="display:block;position:relative;aspect-ratio:16/10;overflow:hidden;padding:13px;text-align:left;'+
    esc('background-color:'+t.canvas.background+';'+(t.canvas.gradient?'background-image:'+t.canvas.gradient+';':'')+'color:'+t.canvas.foreground+';font-family:'+t.font+';border-radius:9px;')+'">'+
    themeV2DecorationHTML(t)+'<span style="display:block;font-size:9px;line-height:1.4;letter-spacing:.12em;margin:0 0 7px">'+esc(t.family.toUpperCase())+'</span>'+
    '<span style="display:block;'+esc('font-family:'+t.headingFont+';font-size:18px;font-weight:'+t.weight+';line-height:1.1;margin:0 0 10px;color:'+t.headingColor+';')+'">Idee che prendono forma</span>'+
    '<span style="display:grid;grid-template-columns:1.4fr 1fr;gap:7px">'+[panel,second].map((p,i)=>'<span style="'+esc('display:block;padding:8px;font-size:10px;line-height:1.35;border-radius:'+Math.min(10,t.radius)+'px;background:'+p.background+';color:'+p.foreground+';')+'">'+(i?'Un esempio':'Il punto chiave')+'</span>').join('')+'</span></span>';
}
