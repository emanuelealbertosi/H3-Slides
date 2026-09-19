// Independent dialog: polling the deck cannot reset the query or its result pages.
export function createImageSearch({api,inserted}){
  const dialog=document.createElement('dialog');dialog.id='image-search-dialog';
  dialog.setAttribute('aria-labelledby','image-search-title');
  dialog.innerHTML='<div class="row between"><h2 id="image-search-title">Cerca un’immagine</h2>'+
    '<button type="button" data-close aria-label="Chiudi ricerca">×</button></div>'+
    '<form><label>Origine<select name="source"><option value="document">Documenti del progetto</option><option value="web">Internet</option></select></label>'+
    '<label>Query di ricerca<input name="query" maxlength="180" minlength="2" required autocomplete="off"></label>'+
    '<div class="row"><button class="primary" type="submit">Cerca</button>'+
    '<label class="check"><input type="checkbox" name="openverse">Aggiungi Openverse a Wikimedia</label>'+
    '<label class="check" hidden><input type="checkbox" name="include_pages">Includi pagine intere</label></div></form>'+
    '<p class="hint muted" data-hint></p>'+
    '<p data-status role="status" aria-live="polite"></p><div class="image-search-results"></div>'+
    '<button type="button" data-more hidden>Altro · 10 risultati</button>';
  document.body.append(dialog);
  const form=dialog.querySelector('form'),query=form.elements.query,extended=form.elements.openverse;
  const origin=form.elements.source,includePages=form.elements.include_pages,hint=dialog.querySelector('[data-hint]');
  const results=dialog.querySelector('.image-search-results'),status=dialog.querySelector('[data-status]');
  const more=dialog.querySelector('[data-more]'),close=dialog.querySelector('[data-close]');
  let target=null,searchId='',page=0,version=0,controller=null,selecting=false,loading=false;
  const endpoint=()=>'/api/projects/'+target.pid+'/slides/'+target.sid+'/image-search';
  function cancel(){version++;controller?.abort();controller=null}
  function reset(){cancel();results.replaceChildren();searchId='';page=0;more.hidden=true;status.textContent='';loading=false}
  function controls(){
    more.disabled=loading||selecting;form.querySelector('button').disabled=selecting;
    query.disabled=selecting;extended.disabled=selecting;close.disabled=selecting;
    origin.disabled=selecting;includePages.disabled=selecting;
    for(const button of results.querySelectorAll('button'))button.disabled=selecting;
  }
  function mode(){
    const local=origin.value==='document';
    query.required=!local;query.minLength=local?0:2;
    query.placeholder=local?'Facoltativa: lascia vuoto per vedere tutte le immagini':'Es. Odysseus';
    extended.closest('label').hidden=local;includePages.closest('label').hidden=!local;
    hint.textContent=local?
      'Ricerca locale sul PC, senza inviare documenti in Internet. La query è facoltativa e ordina le immagini per pertinenza. '+
      'Uso le pagine dell’ultima elaborazione: tutte se è stato lavorato il documento intero.':
      'Invia solo la query, non i documenti. Immagini con licenze aperte; autore e fonte vengono conservati. '+
      'La licenza Openverse viene verificata sulla fonte prima dell’inserimento.';
  }
  function resultCard(row,base,id,local){
    const card=document.createElement('article');card.className='image-search-result';
    const image=document.createElement('img');image.alt=row.label;image.loading='lazy';
    image.src=base+'/'+encodeURIComponent(id)+'/'+encodeURIComponent(row.id)+'/preview';
    image.onerror=()=>{image.hidden=true;card.classList.add('preview-missing')};
    const title=document.createElement('strong');title.textContent=row.label;
    const meta=document.createElement('small');
    const source=document.createElement(local?'small':'a');
    if(local){
      const kind=({figure:'Figura',page:'Pagina intera',image:'Immagine'})[row.kind]||'Immagine';
      meta.textContent='Documento locale · '+kind;
      source.textContent=String(row.document||row.source||'Documento del progetto')+
        (Number.isInteger(row.pdf_page)&&row.pdf_page>0?' · pagina PDF '+row.pdf_page:'');
    }else{
      meta.textContent=row.image_provider+' · '+row.license+' · '+(row.author||'Autore indicato nella fonte');
      source.textContent='Fonte e licenza';source.target='_blank';source.rel='noopener noreferrer';
      // The server validates sources; also refuse unsafe schemes in this view.
      try{const url=new URL(row.source);if(url.protocol==='https:')source.href=url.href}catch{}
    }
    const choose=document.createElement('button');choose.type='button';choose.textContent='Usa questa immagine';
    choose.onclick=()=>select(row.id);
    card.append(image,title,meta,source,choose);return card;
  }
  async function search(next=false){
    if(selecting||next&&loading)return;
    if(!next){if(!form.reportValidity())return;reset()}
    const token=++version,base=endpoint(),local=origin.value==='document';controller=new AbortController();loading=true;controls();
    status.textContent='Ricerca in corso…';
    try{
      const body=next?{search_id:searchId,page}:local?{query:query.value.trim()}:{query:query.value.trim(),openverse:extended.checked};
      if(local)Object.assign(body,{source:'document',include_pages:includePages.checked});
      const data=await api(base,'POST',body,controller.signal);
      if(token!==version||!dialog.open)return;
      searchId=data.search_id;page=data.page+1;
      for(const row of data.results)results.append(resultCard(row,base,searchId,local));
      more.hidden=!data.has_more;
      status.textContent=(data.message?data.message+' ':'')+(results.children.length?
        results.children.length+(Number.isInteger(data.total)&&data.total>=results.children.length?' di '+data.total:'')+' immagini. Scegline una per inserirla nella slide.':
        local?'Nessuna immagine disponibile in questo ambito. Prova a includere le pagine intere.':
        'Nessun risultato utilizzabile in questo blocco. '+(data.has_more?'Prova Altro o cambia query.':'Prova una query più breve o diversa.'));
    }catch(error){if(token===version&&error.name!=='AbortError')status.textContent=error.message}
    finally{if(token===version){loading=false;controls()}}
  }
  async function select(resultId){
    if(selecting||loading)return;
    selecting=true;controls();status.textContent=origin.value==='document'?'Inserimento dell’immagine dal documento…':'Verifica licenza e inserimento dell’immagine…';
    const destination={...target};
    try{
      const data=await api(endpoint()+'/select','POST',{search_id:searchId,result_id:resultId,revision:destination.revision,...(destination.node_id?{node_id:destination.node_id}:{})});
      inserted(destination,data);dialog.close();
    }catch(error){status.textContent=error.message}
    finally{selecting=false;controls()}
  }
  form.onsubmit=event=>{event.preventDefault();search()};more.onclick=()=>search(true);
  // Editing the query/provider starts a fresh search and invalidates pending responses.
  for(const input of [query,extended])input.addEventListener('input',()=>{reset();controls()});
  origin.addEventListener('change',()=>{
    reset();mode();controls();
    if(origin.value==='document'||query.value.trim().length>=2)search();
  });
  includePages.addEventListener('change',()=>{reset();controls();if(origin.value==='document')search()});
  close.onclick=()=>dialog.close();
  dialog.addEventListener('cancel',event=>{if(selecting)event.preventDefault()});
  dialog.addEventListener('close',()=>{if(!dialog.open){cancel();target=null}});
  return {open(value){
    if(selecting)return;
    reset();target={...value};query.value=(value.query||'').slice(0,180);extended.checked=!!value.openverse;
    origin.value=value.source==='document'?'document':'web';includePages.checked=!!value.include_pages;mode();
    controls();dialog.showModal();query.focus();query.select();if(origin.value==='document'||query.value.trim().length>=2)search();
  }};
}
