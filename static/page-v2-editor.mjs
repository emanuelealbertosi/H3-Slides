import {esc,slideHTML,fitSlide} from './deck.mjs';
import {pageAssets} from './page-v2.mjs';

export function orderPage(nodes){
  const result=[],seen=new Set();
  function visit(parent){for(const n of nodes.filter(n=>n.parent===parent)){if(seen.has(n.id))throw Error('Gruppo circolare');seen.add(n.id);result.push(n);visit(n.id)}}
  visit('root');if(result.length!==nodes.length)throw Error('Non puoi spostare un gruppo dentro sé stesso');return result;
}
export function movePageNode(page,id,target,inside=false){
  const nodes=page.nodes,node=nodes.find(n=>n.id===id),to=nodes.find(n=>n.id===target);
  if(!node||!to||node===to)return;
  node.parent=inside&&to.kind==='group'?to.id:to.parent;
  nodes.splice(nodes.indexOf(node),1);nodes.splice(nodes.indexOf(to)+(inside?1:0),0,node);
  page.nodes=orderPage(nodes);
}
function descendants(page,id){const ids=new Set([id]);for(const n of page.nodes)if(ids.has(n.parent))ids.add(n.id);return ids}

export function renderPageCard(card,project,slide,index,{save,toast,observe,upload,search,diagram,refresh}){
  card.v2Controller?.abort();card.v2Controller=new AbortController();
  const events={signal:card.v2Controller.signal};
  const ready=slide.status==='ready',page=slide.page_draft||slide.content.page;
  const urls={assets:Object.fromEntries(pageAssets(page).map(id=>[id,'/api/assets/'+project.id+'/'+id]))};
  card.innerHTML='<div class="slide-top"><span class="slide-label">'+(index+1)+' · V2 · '+esc(ready?'Pronta':slide.status==='failed'?'Bozza interrotta':'Composizione AI…')+'</span>'+
    '<button class="quiet" data-action="up">↑</button><button class="quiet" data-action="down">↓</button><button class="quiet" data-action="regenerate">Rigenera pagina</button></div>'+
    '<div class="composition-tools"><span class="composition-status">Pagina progettata dall’AI</span>'+
    (ready?'<button class="quiet" data-v2-add="text">＋ Testo</button><button class="quiet" data-v2-add="image">＋ Immagine</button><button class="quiet" data-v2-add="group">＋ Sezione</button><button class="quiet" data-v2-edit="root">Struttura pagina</button>':'')+'</div>'+
    '<div class="slide-preview">'+slideHTML(project,slide,index,urls)+'</div>'+
    (slide.page_error?'<p class="diagram-pending">'+esc(slide.page_error)+'</p>':'');
  card.draggable=false;
  const frame=card.querySelector('.slide-frame'),preview=card.querySelector('.slide-preview');
  const fit=()=>{if(!frame.isConnected)return;const r=fitSlide(frame);card.querySelector('.composition-status').textContent=
    'V2 · '+page.nodes.length+' elementi · '+r.height+' px'+(r.overflow?' · contenuto oltre il formato, scegli Adattivo':'');
    const scale=preview.clientWidth/1280;frame.style.transform='scale('+scale+')';frame.style.transformOrigin='top left';preview.style.height=r.height*scale+'px';};
  observe(preview);requestAnimationFrame(fit);document.fonts.ready.then(fit);
  frame.querySelectorAll('img').forEach(img=>img.addEventListener('load',fit,{once:true}));
  if(!ready)return;
  for(const element of frame.querySelectorAll('[data-page-node]')){
    const controls=document.createElement('div');controls.className='v2-tools';
    controls.innerHTML='<button title="Trascina prima di un altro elemento; Maiusc per inserire in una sezione" draggable="true" data-v2-drag>⠿</button><button title="Modifica elemento" data-v2-edit="'+esc(element.dataset.pageNode)+'">✎</button><button title="Elimina elemento" data-v2-delete="'+esc(element.dataset.pageNode)+'">×</button>';
    if(element.dataset.nodeKind==='image')controls.innerHTML+='<button title="Carica immagine" data-v2-upload="'+esc(element.dataset.pageNode)+'">↑</button><button title="Cerca nel documento o in Internet" data-v2-search="'+esc(element.dataset.pageNode)+'">⌕</button>';
    if(element.dataset.nodeKind==='diagram')controls.innerHTML+='<button title="Riprogetta questo diagramma con Manim" data-v2-diagram="'+esc(element.dataset.pageNode)+'">↻ Manim</button>';
    element.append(controls);
  }
  card.addEventListener('click',async e=>{
    const button=e.target.closest('[data-v2-add],[data-v2-edit],[data-v2-delete],[data-v2-upload],[data-v2-search],[data-v2-diagram]');if(!button)return;
    e.preventDefault();e.stopPropagation();
    try{
      if(button.dataset.v2Upload)await upload(button.dataset.v2Upload);
      else if(button.dataset.v2Diagram)await diagram(button.dataset.v2Diagram);
      else if(button.dataset.v2Search)await search(button.dataset.v2Search);
      else if(button.dataset.v2Add){
        const kind=button.dataset.v2Add;
        await save(content=>{content.page.nodes.push({id:'n'+crypto.randomUUID().replaceAll('-','').slice(0,16),parent:'root',kind,text:kind==='text'?'Nuovo testo':'',style:{}})},'Elemento aggiunto');
      }else if(button.dataset.v2Delete){
        await save(content=>{const ids=descendants(content.page,button.dataset.v2Delete);content.page.nodes=content.page.nodes.filter(n=>!ids.has(n.id));if(!content.page.nodes.length)throw Error('Mantieni almeno un elemento nella pagina')},'Elemento eliminato');
      }else editNode(button.dataset.v2Edit);
    }catch(error){toast(error.message)}
  },events);
  function editNode(id){
    const node=id==='root'?{kind:'group',style:page.style}:page.nodes.find(n=>n.id===id),s=node.style||{};
    const dialog=document.createElement('dialog');dialog.className='v2-editor';
    const images=[...(project.visual_assets||[]).map(a=>({id:a.id,label:a.label})),...(project.sources||[]).flatMap(s=>(s.images||[]).map(a=>({id:a.id,label:s.name+' · '+(a.label||a.id)}))),...page.nodes.filter(n=>n.asset_id).map(n=>({id:n.asset_id,label:n.text||n.asset_id}))];
    dialog.innerHTML='<form method="dialog"><h2>'+ (id==='root'?'Struttura pagina':'Modifica elemento')+'</h2>'+
      (node.kind!=='group'?'<label>Testo<textarea name="text" rows="7">'+esc(node.text)+'</textarea></label>':'')+
      (node.kind==='image'?'<label>Immagine del progetto<select name="asset"><option value="">Segnaposto</option>'+images.map(a=>'<option value="'+esc(a.id)+'" '+(a.id===node.asset_id?'selected':'')+'>'+esc(a.label)+'</option>').join('')+'</select></label>':'')+
      (node.kind==='group'?'<label>Disposizione<select name="flow">'+['stack','columns','row'].map((v,i)=>'<option value="'+v+'" '+(v===(s.flow||'stack')?'selected':'')+'>'+['Verticale','Colonne con proporzioni','Riga uniforme'][i]+'</option>').join('')+'</select></label><label>Proporzioni colonne (es. 2, 1, 1)<input name="columns" value="'+esc((s.columns||[1,1]).join(', '))+'"></label>':'')+
      '<div class="row">'+[['font_size','Dimensione testo',s.font_size||24,18,80],['padding','Spazio interno',s.padding||0,0,100],['gap','Distanza elementi',s.gap??24,0,100],['span','Colonne occupate',s.span||1,1,12],['min_height','Altezza minima',s.min_height||0,0,1600]].map(([name,label,value,min,max])=>'<label>'+label+'<input name="'+name+'" type="number" min="'+min+'" max="'+max+'" value="'+value+'"></label>').join('')+'</div>'+
      '<label>Sfondo<select name="surface">'+['none','soft','accent','dark','paper'].map((v,i)=>'<option value="'+v+'" '+(v===(s.surface||'none')?'selected':'')+'>'+['Trasparente','Tenue','Accento del tema','Scuro','Bianco'][i]+'</option>').join('')+'</select></label>'+
      '<div class="row"><button value="cancel" class="quiet">Annulla</button><button value="save" class="primary">Salva</button></div></form>';
    document.body.append(dialog);dialog.showModal();
    dialog.addEventListener('close',async()=>{
      if(dialog.returnValue==='save'){
        const values=new FormData(dialog.querySelector('form'));
        try{await save(content=>{
          const target=id==='root'?content.page:content.page.nodes.find(n=>n.id===id);if(!target)throw Error('Elemento non trovato');
          target.style||={};for(const key of ['font_size','padding','gap','span','min_height'])target.style[key]=Number(values.get(key));
          target.style.surface=values.get('surface');
          if(values.has('flow')){target.style.flow=values.get('flow');target.style.columns=String(values.get('columns')).split(',').map(Number)}
          if(values.has('text'))target.text=String(values.get('text'));
          if(values.has('asset'))target.asset_id=String(values.get('asset'));
        },'Pagina aggiornata')}catch(error){toast(error.message)}
      }dialog.remove();
    },{once:true});
  }
  let dragged=null,drop=null,dropping=false;
  card.addEventListener('dragstart',e=>{
    if(!e.target.closest('[data-v2-drag]')){e.preventDefault();return}e.stopPropagation();
    dragged=e.target.closest('[data-page-node]');e.dataTransfer.setData('text/plain',dragged.dataset.pageNode);e.dataTransfer.effectAllowed='move';card.dataset.saving='drag';
  },events);
  card.addEventListener('dragover',e=>{
    if(!dragged)return;e.preventDefault();e.stopPropagation();const target=e.target.closest('[data-page-node]');
    if(!target||target===dragged||dragged.contains(target))return;
    frame.querySelectorAll('.v2-drop').forEach(n=>n.classList.remove('v2-drop'));target.classList.add('v2-drop');
    drop={id:target.dataset.pageNode,inside:e.shiftKey&&target.dataset.nodeKind==='group'};
    if(drop.inside)target.insertBefore(dragged,target.querySelector(':scope>.v2-tools'));else target.before(dragged);
    fit();
  },events);
  card.addEventListener('drop',async e=>{
    if(!dragged)return;e.preventDefault();e.stopPropagation();const id=dragged.dataset.pageNode,target=drop;dragged=null;dropping=true;
    try{if(target)await save(content=>movePageNode(content.page,id,target.id,target.inside),'Disposizione salvata')}
    catch(error){toast(error.message)}finally{dropping=false;delete card.dataset.saving;refresh?.()}
  },events);
  card.addEventListener('dragend',()=>{if(dropping)return;dragged=null;delete card.dataset.saving;refresh?.()},events);
}
