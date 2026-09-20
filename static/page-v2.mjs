// Declarative HTML only. Model text is escaped; no arbitrary tags, CSS or URLs.
import {resolveV2Theme,resolveV2Role,resolveV2Node,themeV2DecorationHTML} from './theme-v2.mjs';
export const pageAssets=page=>[...new Set((page?.nodes||[]).map(n=>n.asset_id).filter(Boolean))];
export function pageHTML(project,slide,index,urls,helpers){
  const {esc,mathHTML,codeHTML,themeFor,autoText}=helpers,page=slide.page_draft||slide.content.page,t=themeFor(project);
  const theme=resolveV2Theme(project,t),rich=theme.enabled,firstHeading=page.nodes.find(n=>n.kind==='heading')?.id;
  const baseHeight={'16:9':720,'4:3':960,'16:10':800,'1:1':1280}[project.slide_format]||720;
  const maxHeight=project.canvas_mode==='fixed'?baseHeight:Math.ceil(baseHeight*1.15);
  const num=(v,d,a,b)=>Number.isFinite(Number(v))?Math.max(a,Math.min(b,Number(v))):d;
  const styles=(s={},parent={},appearance=null)=>{
    const bg={soft:t.surface,accent:t.accent,dark:'#17243a',paper:'#ffffff'}[s.surface];
    const columns=(s.columns||[1,1]).slice(0,12).map(v=>'minmax(0,'+num(v,1,.1,20)+'fr)').join(' ');
    return 'display:grid;align-content:start;align-items:start;grid-template-columns:'+
      (s.flow==='columns'?columns:s.flow==='row'?'repeat('+Math.max(1,(page.nodes||[]).filter(n=>n.parent===s._id).length)+',minmax(0,1fr))':'minmax(0,1fr)')+';'+
      'gap:'+num(s.gap,24,0,100)+'px;padding:'+num(s.padding,0,0,100)+'px;border-radius:'+num(s.radius,0,0,64)+'px;'+
      'font-size:'+num(s.font_size,24,18,80)+'px;text-align:'+(['left','center','right'].includes(s.align)?s.align:'left')+';'+
      'font-weight:'+(s.bold?'700':'400')+';min-height:'+num(s.min_height,0,0,1600)+'px;'+
      'grid-column:span '+num(s.span,1,1,parent.flow==='columns'?(parent.columns||[1,1]).length:1)+';'+
      (appearance?((appearance.ownPaint?'background-color:'+appearance.ownPaint.background+';'+(appearance.ownPaint.gradient?'background-image:'+appearance.ownPaint.gradient+';':''):'')+
        'color:'+appearance.color+';font-family:'+appearance.font+';font-weight:'+appearance.weight+';'+
        (appearance.borderWidth?'border:'+appearance.borderWidth+'px solid '+appearance.borderColor+';':'')+
        (appearance.leftBorder?'border-left:'+appearance.leftBorder.width+'px solid '+appearance.leftBorder.color+';':'')+
        'box-shadow:'+appearance.shadow+';'+appearance.extra):
        (bg?'background:'+bg+';color:'+autoText(bg)+';':'')+(s.border?'border:1px solid '+t.line+';':'')+(s.shadow?'box-shadow:0 10px 30px #00000018;':''));
  };
  const children=parent=>page.nodes.filter(n=>n.parent===parent);
  const render=(node,parentStyle,depth=0,parentPaint=theme.canvas)=>{
    if(depth>8)return '';
    const role=resolveV2Role(node,firstHeading),appearance=rich?resolveV2Node(theme,node,role,parentPaint):null;
    const style=appearance?.style||node.style||{},text=String(node.text||''),media=['image','diagram'].includes(node.kind);
    let body='';
    if(node.kind==='group')body=children(node.id).map(n=>render(n,style,depth+1,appearance?.paint||parentPaint)).join('');
    else if(media){
      const url=urls.assets?.[node.asset_id];
      const diagram=slide.page_diagrams?.[node.id];
      const diagramStatus=diagram?.status==='failed'?'failed':diagram?.status==='disabled'||project.use_manim_diagrams===false?'disabled':slide.status==='generating'?'generating':'empty';
      const detail=String(diagram?.error||'').replace(/\s+/g,' ').trim().slice(0,200);
      const placeholder=node.kind==='image'?'Immagine da scegliere':diagramStatus==='failed'?
        'Diagramma non disponibile'+(detail?'\n'+detail:'')+'\nRiprogetta per riprovare':diagramStatus==='disabled'?
        'Diagrammi Manim disattivati':diagramStatus==='generating'?'Diagramma Manim in preparazione':'Diagramma da creare';
      body=(url?'<figure class="v2-media" data-asset-id="'+esc(node.asset_id)+'" data-visual-kind="'+node.kind+'"><img src="'+esc(url)+'" alt="'+esc(node.kind==='image'?text:'Diagramma Manim')+'"></figure>':
        '<div class="v2-placeholder"'+(node.kind==='diagram'?' data-diagram-status="'+diagramStatus+'"':'')+'><span class="v2-text">'+esc(placeholder)+'</span></div>')+
        (node.kind==='image'&&text?'<div class="v2-text v2-caption" data-page-text="'+esc(node.id)+'" data-edit-field="page-text" data-edit-raw="'+esc(text)+'">'+mathHTML(text)+'</div>':'');
    }else{
      const tag=node.kind==='heading'?'h2':'div';
      body='<'+tag+' class="v2-text '+(node.kind==='code'?'v2-code kind-code':'')+'" data-page-text="'+esc(node.id)+'" data-edit-field="page-text" data-edit-raw="'+esc(text)+'">'+
        (node.kind==='code'?codeHTML(text,node.language||'text'):mathHTML(text))+'</'+tag+'>';
    }
    if(node.source)body+='<div class="v2-source v2-text">'+esc(node.source)+'</div>';
    return '<section class="v2-node '+(node.kind==='group'?'v2-group':'')+'" data-page-node="'+esc(node.id)+'" data-node-kind="'+esc(node.kind)+'"'+
      ' data-v2-role="'+role+'"'+(appearance?.ownPaint?.gradient?' data-v2-gradient="true"':'')+
      ' style="'+esc(styles({...style,_id:node.id},parentStyle,appearance))+'">'+body+'</section>';
  };
  const font=['Arial','Calibri','Segoe UI','Georgia','Verdana','Consolas'].includes(project.font)?project.font:'Arial';
  const rootAppearance=rich?resolveV2Node(theme,{id:'root',kind:'group',style:page.style},'auto'):null,rootStyle=rootAppearance?.style||page.style||{};
  return '<article class="slide-frame page-v2" data-engine="v2" data-layout="ai-page" data-canvas-mode="'+(project.canvas_mode==='fixed'?'fixed':'adaptive')+'"'+
    ' data-page-base-height="'+baseHeight+'" data-page-max-height="'+maxHeight+'"'+
    (rich?' data-visual-family="'+theme.family+'"'+(theme.canvas.gradient?' data-v2-gradient="true"':''):'')+
    ' style="--page-base-height:'+baseHeight+'px;--bg:'+(rich?theme.canvas.background:t.bg)+';--fg:'+(rich?theme.canvas.foreground:t.fg)+';--line:'+(rich?theme.line:t.line)+';--muted:'+(rich?theme.muted:t.muted)+';--font:'+font+';'+
    (rich&&theme.canvas.gradient?'background-image:'+esc(theme.canvas.gradient)+';':'')+'">'+
    (rich?themeV2DecorationHTML(theme):'')+
    '<div class="v2-root"'+(rootAppearance?.ownPaint?.gradient?' data-v2-gradient="true"':'')+' style="'+esc(styles({...rootStyle,_id:'root'},{},rootAppearance))+'">'+children('root').map(n=>render(n,rootStyle,0,rootAppearance?.paint||theme.canvas)).join('')+'</div>'+
    '<div class="footer"><span>'+esc(project.title)+'</span><span>'+String(index+1).padStart(2,'0')+'</span></div></article>';
}
export const pageCSS=`
.slide-preview:has(>.page-v2){width:100%;max-width:100%;aspect-ratio:auto}
.v2-waiting-preview{min-height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:40px;text-align:center;border:1px dashed #cbd3cd;border-radius:12px;background:#fff;color:#17243a}
.v2-waiting-preview strong{font-size:24px}.v2-waiting-preview p{margin:0;font-size:18px}.v2-waiting-preview span{font-size:14px;color:#596579}
.slide-frame.page-v2{height:auto;min-height:var(--page-base-height,720px);padding:44px 48px 26px;gap:30px;overflow:visible}
.page-v2 .v2-root{flex:1;min-width:0}.page-v2 .v2-node{min-width:0;position:relative;margin:0}
.page-v2 .v2-text{font:inherit;line-height:1.4;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;min-width:0;max-width:100%;color:inherit}
.page-v2 h2.v2-text{font-weight:700;line-height:1.14;letter-spacing:-.025em}
.page-v2 .v2-code{font-family:Consolas,monospace;line-height:1.4;white-space:pre-wrap}.page-v2 .v2-code pre,.page-v2 .v2-code code{font:inherit;white-space:pre-wrap;margin:0;padding:0;background:none;color:inherit}
.page-v2 .v2-source{font-size:14px;line-height:1.35;opacity:.85}.page-v2 .v2-caption{font-size:18px;line-height:1.35}
.page-v2 .v2-media{margin:0;min-width:0;width:100%;position:relative}.page-v2 .v2-media img{display:block;width:100%;height:auto;object-fit:contain;border-radius:inherit}
.page-v2 .v2-placeholder{min-height:220px;display:grid;place-items:center;border:1px dashed var(--muted);border-radius:16px;opacity:.7}
.slide-frame.page-v2 .footer{position:static;margin-top:auto;width:100%;padding-top:12px;font-size:14px;flex:none}
.page-v2 .v2-node:hover{outline:1px solid #7566dd88;outline-offset:4px}
.page-v2[data-visual-family] h2.v2-text{font-weight:inherit;line-height:1.12;letter-spacing:inherit}
.page-v2[data-visual-family] .v2-source{font-size:16px;opacity:1}
.page-v2[data-visual-family] [data-v2-role=quote]>.v2-text{line-height:1.5}
.page-v2[data-visual-family] [data-v2-role=stat]>.v2-text{line-height:1.05}
.v2-tools{position:absolute;right:0;top:-22px;z-index:8;display:none;gap:3px;background:#fff;color:#17243a;border-radius:6px;box-shadow:0 2px 10px #0003;padding:3px}
.v2-node:hover>.v2-tools,.v2-node:focus-within>.v2-tools{display:flex}.v2-tools button{font:16px Arial;padding:4px 8px;border:0;min-height:24px;background:#f0eefb;color:#17243a;cursor:pointer}.v2-tools [draggable]{cursor:grab}
.v2-node:has(.v2-node:hover)>.v2-tools{display:none}.v2-node:has(.v2-node:hover){outline:none}
.v2-editor{width:min(780px,94vw);max-height:90vh;overflow:auto}.v2-editor textarea{width:100%}
.page-v2 .v2-drop{outline:3px solid #7566dd;background:#7566dd22}
@media print{.v2-tools{display:none!important}.page-v2 .v2-node:hover{outline:none}}
`;
