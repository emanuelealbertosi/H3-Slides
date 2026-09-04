import {esc,slideHTML,slideCSS,themes,themeFor,blockColors,contrast,layouts,fitSlide} from './deck.mjs';
import {createRemoteModelSelector} from './remote-models.mjs';
import {createApiSettings} from './api-settings.mjs';
const $=id=>document.getElementById(id);
const layoutOptions=value=>'<option value="content">Automatico adattivo</option>'+Object.entries(layouts).map(([key,label])=>'<option value="'+key+'" '+(key===value?'selected':'')+'>'+label+'</option>').join('');
$('edit-layout').innerHTML=layoutOptions('content');
const style=document.createElement('style');style.textContent=slideCSS;document.head.append(style);
let current=null,projects=[],documents=[],jobs=[],editing=null,job=null,busy=false,dragged=null;
let polling=false;
let modelInfo=null;
let apiSettings=null,adminData=null,adminDirty=false,adminLoading=null;
const modelNotices=new Set();
const themeColors={text_color:'Testo principale',title_color:'Titoli',box_text_color:'Testo nei box',
  explanation_color:'Box spiegazione',example_color:'Box esempio',key_color:'Box da ricordare',
  quote_color:'Box citazione',border_color:'Bordi dei box'};
const themeNumbers={title_size:['Dimensione titolo · 0 automatica',0,76],
  body_size:['Dimensione testo · 0 automatica',0,32],border_width:['Spessore bordo',0,5],box_radius:['Raggio angoli',18,32]};
let themePresets=[];
$('theme-editor').innerHTML=Object.entries(themeColors).map(([key,label])=>
  '<div class="theme-color"><label>'+label+'<input type="color" data-theme-color="'+key+'" value="#ffffff"></label>'+
  '<label class="check"><input type="checkbox" data-theme-auto="'+key+'" checked>Automatico</label></div>').join('')+
  Object.entries(themeNumbers).map(([key,[label,value,max]])=>'<label>'+label+
  '<input type="number" data-theme-number="'+key+'" min="0" max="'+max+'" value="'+value+'"></label>').join('');
function readThemeDesign(){
  const d={};for(const key of Object.keys(themeColors))d[key]=$('theme-editor').querySelector('[data-theme-auto="'+key+'"]').checked?'':$('theme-editor').querySelector('[data-theme-color="'+key+'"]').value;
  for(const input of $('theme-editor').querySelectorAll('[data-theme-number]'))d[input.dataset.themeNumber]=Number(input.value);
  return d;
}
function fillThemeDesign(value={}){
  for(const key of Object.keys(themeColors)){
    const input=$('theme-editor').querySelector('[data-theme-color="'+key+'"]'),auto=$('theme-editor').querySelector('[data-theme-auto="'+key+'"]');
    auto.checked=!value[key];input.value=value[key]||'#ffffff';input.disabled=auto.checked;
  }
  for(const [key,[,fallback]]of Object.entries(themeNumbers))$('theme-editor').querySelector('[data-theme-number="'+key+'"]').value=value[key]??fallback;
}
fillThemeDesign();
const exporting=new Set();
const drafts=new Set();
const inlineSaves=new Set();
async function finishInlineEdits(){
  const field=$('slides').querySelector('[contenteditable]');
  if(field)field.blur();
  await Promise.all([...inlineSaves]);
  if($('slides').querySelector('[contenteditable]'))throw new Error('Salva o annulla il testo ancora in modifica.');
}
const designFields={'template':'template','font':'font','text-density':'text_density','background-color':'background_color','accent-color':'accent_color','source-images':'use_source_images','manim-diagrams':'use_manim_diagrams','pdf-scope':'pdf_scope',
  'web-enabled':'web_enabled','web-provider':'web_provider','web-query':'web_query','web-max-sources':'web_max_sources'};
const preferenceIds=['provider','model','api-url','api-model','vision',...Object.keys(designFields).filter(id=>!['web-query','web-enabled'].includes(id))];
const pref=JSON.parse(localStorage.getItem('h3slides-settings')||'{}');
for(const id of preferenceIds) {
  if(pref[id]!==undefined&&!['model','api-model'].includes(id)) { if($(id).type==='checkbox')$(id).checked=pref[id];else $(id).value=pref[id]; }
}
function savePrefs(){
  const values={};for(const id of preferenceIds)values[id]=$(id).type==='checkbox'?$(id).checked:$(id).value;
  values['api-model']=remoteModels.value();values.remote_models=remoteModels.preferences();
  apiSettings?.sync();values.api_profiles=apiSettings?.preferences()||pref.api_profiles||{};
  localStorage.setItem('h3slides-settings',JSON.stringify(values));
  updateModelSummary();
}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,7000)}
async function api(url,method='GET',data,signal){
  const options={method,headers:{'X-H3-Slides':'1'},signal};
  if(data instanceof FormData)options.body=data;
  else if(data!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}
  const response=await fetch(url,options);const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Errore HTTP '+response.status);
  return result;
}
const design=()=>({...Object.fromEntries(Object.entries(designFields).map(([id,key])=>[key,$(id).type==='checkbox'?$(id).checked:$(id).value])),theme_design:readThemeDesign()});
const brief=()=>({title:$('title').value,prompt:$('prompt').value,count:Number($('count').value),theme:$('theme').value,...design()});
const provider=()=>({mode:$('provider').value,model:$('provider').value==='local'?$('model').value:remoteModels.value(),
  base_url:$('api-url').value.trim(),api_key:$('api-key').value.trim(),remote_consent:$('consent').checked,vision:$('vision').checked,
  ...($('provider').value==='remote'?{inference:apiSettings.value()}:{})});
const remoteModels=createRemoteModelSelector({
  select:$('api-model'),refresh:$('refresh-remote-models'),status:$('remote-model-status'),
  manualToggle:$('api-model-manual'),manualInput:$('api-model-id'),
  getConnection:()=>({base_url:$('api-url').value,api_key:$('api-key').value}),
  request:(config,signal)=>api('/api/remote-models','POST',config,signal),onSave:savePrefs,
  saved:pref.remote_models,legacy:{url:pref['api-url'],model:pref['api-model']},
});
apiSettings=createApiSettings({
  getSelection:()=>({url:$('api-url').value,model:remoteModels.value(),active:$('provider').value==='remote'}),
  fields:{max_tokens:$('api-max-tokens'),temperature:$('api-temperature'),top_p:$('api-top-p'),timeout_seconds:$('api-timeout')},
  serverTokens:$('api-server-tokens'),fieldset:$('api-inference-fields'),status:$('api-inference-status'),
  saved:pref.api_profiles,onSave:savePrefs,
});
function updateModelSummary(){
  const remote=$('provider').value==='remote';
  const name=remote?remoteModels.value():$('model').selectedOptions[0]?.textContent;
  $('active-model').textContent=(remote?'Server API':'llama.cpp integrato')+' · '+(name||'Da configurare in Admin');
}
function fields(){
  const remote=$('provider').value==='remote';
  $('remote-fields').hidden=!remote;$('local-fields').hidden=remote;
  $('remote-inference').hidden=!remote;$('admin-form').hidden=remote;
  remoteModels.activate(remote);savePrefs();
}
$('provider').addEventListener('change',fields);fields();
$('provider').addEventListener('change',()=>{if($('provider').value==='local')models().catch(e=>toast(e.message))});
for(const id of ['api-url','vision'])$(id).addEventListener('change',savePrefs);
$('model').addEventListener('change',()=>{
  if(adminDirty&&!confirm('Scartare le modifiche al profilo locale prima di cambiare modello?')){
    $('model').value=$('model').dataset.previous||'';return;
  }
  adminDirty=false;$('model').dataset.previous=$('model').value;savePrefs();loadAdmin();
});
for(const id of ['api-url','api-key']){
  $(id).addEventListener('input',()=>{remoteModels.invalidate();apiSettings.sync();updateModelSummary();if(id==='api-url')$('consent').checked=false});
  $(id).addEventListener('change',()=>remoteModels.load());
}
for(const id of ['title','prompt','count','theme'])$(id).addEventListener('input',()=>{drafts.add('brief');$('save-status').textContent='Brief non salvato'});
for(const id of Object.keys(designFields))$(id).addEventListener('input',()=>{
  if(id.startsWith('web-'))$('web-consent').checked=false;
  drafts.add('brief');$('save-status').textContent='Stile in anteprima · salva per conservarlo';savePrefs();render();
});
$('theme').addEventListener('change',()=>{const t=themes[$('theme').value];$('background-color').value=t.bg;$('accent-color').value=t.accent;render()});
async function loadProjects(){
  projects=await api('/api/projects');$('project-list').innerHTML='<option value="">Nuovo progetto</option>'+projects.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.title)+' · '+p.slide_count+'</option>').join('');
  if(current)$('project-list').value=current.id;
  renderLibrary();
}
async function loadDocuments(){
  documents=await api('/api/documents');
  renderDocumentLibrary();
}
function renderDocumentLibrary(){
  const container=$('document-library'),attached=new Set((current?.sources||[]).map(s=>s.library_id||s.id));
  $('document-library-count').textContent=documents.length?'· '+documents.length:'';
  container.innerHTML=documents.length?documents.map(doc=>{
    const present=attached.has(doc.library_id);
    const details=doc.page_count?doc.page_count+' pagine':doc.image_count?doc.image_count+' immagini':String(doc.kind||'documento').toUpperCase();
    return '<div class="library-document"><div><strong>'+esc(doc.name)+'</strong><small>'+esc(details)+' · da '+esc(doc.project_title)+'</small></div><div class="library-document-actions">'+
      (doc.viewable?'<a class="quiet button-link" href="/api/documents/'+encodeURIComponent(doc.project_id)+'/'+encodeURIComponent(doc.source_id)+'" target="_blank" rel="noopener">Apri</a>':'')+
      '<button type="button" class="quiet" data-reuse-project="'+esc(doc.project_id)+'" data-reuse-source="'+esc(doc.source_id)+'" '+(present?'disabled':'')+'>'+
      (present?'Già nel progetto':'Usa nel progetto')+'</button></div></div>';
  }).join(''):'<p class="muted hint">La libreria è vuota. Il primo documento aggiunto comparirà qui.</p>';
}
function renderLibrary(){
  $('library-grid').innerHTML=projects.length?projects.map(p=>{
    const when=new Date(p.updated_at),date=Number.isNaN(when.getTime())?'':when.toLocaleString('it-IT',{dateStyle:'medium',timeStyle:'short'});
    return '<article class="project-card" data-project="'+esc(p.id)+'"><div class="project-card-mark">H3 / '+p.slide_count+'</div>'+
      '<h2>'+esc(p.title)+'</h2><p>'+p.slide_count+' slide</p><small>Aggiornato '+esc(date)+'</small>'+
      '<button class="secondary" type="button">Apri progetto →</button></article>';
  }).join(''):'<section class="library-empty"><div class="empty-mark">H3 /</div><h2>Nessun progetto salvato.</h2><p>Inizia da un argomento, un PDF o un’immagine.</p></section>';
}
async function selectProject(id){
  await finishInlineEdits();
  if(drafts.has('brief')&&!confirm('Ci sono modifiche al brief non salvate. Cambiare progetto?'))return;
  current=await api('/api/projects/'+id);drafts.clear();
  $('project-list').value=id;
  for(const key of ['title','prompt','count','theme'])$(key).value=current[key];
  const defaults={template:'auto',font:'Arial',text_density:'detailed',background_color:themes[current.theme].bg,accent_color:themes[current.theme].accent,use_source_images:true,use_manim_diagrams:false,pdf_scope:'auto',
    web_enabled:false,web_provider:'searxng',web_query:'',web_max_sources:3};
  for(const [id,key] of Object.entries(designFields)){const value=current[key]??defaults[key];if($(id).type==='checkbox')$(id).checked=value;else $(id).value=value||defaults[key]}
  $('web-consent').checked=false;$('web-refresh').checked=false;
  fillThemeDesign(current.theme_design);$('theme-presets').value='';
  localStorage.setItem('h3slides-project',id);$('save-status').textContent='Salvato sul PC';render();
}
async function saveProject(){
  if(!current) current=await api('/api/projects','POST',brief());
  else current=await api('/api/projects/'+current.id,'PATCH',brief());
  drafts.delete('brief');$('save-status').textContent='Salvato sul PC';
  localStorage.setItem('h3slides-project',current.id);await loadProjects();render();return current;
}
$('save-project').onclick=()=>saveProject().catch(e=>toast(e.message));
async function newProject(){
  try{await finishInlineEdits()}catch(error){toast(error.message);return}
  if(drafts.size&&!confirm('Lasciare le modifiche non salvate?'))return;
  current=null;drafts.clear();$('title').value='Nuova presentazione';$('prompt').value='';$('project-list').value='';
  $('web-enabled').checked=false;$('web-query').value='';$('web-consent').checked=false;$('web-refresh').checked=false;render();
  navigatePage('create');
}
$('new').onclick=$('library-new').onclick=newProject;
$('project-list').onchange=e=>e.target.value&&selectProject(e.target.value).then(()=>navigatePage('create')).catch(e=>toast(e.message));
$('library-grid').onclick=e=>{
  const card=e.target.closest('[data-project]');if(!card)return;
  selectProject(card.dataset.project).then(()=>navigatePage('create')).catch(error=>toast(error.message));
};
$('files').onchange=async e=>{
  const files=[...e.target.files];e.target.value='';if(!files.length)return;
  try{await saveProject();for(const file of files){const form=new FormData();form.append('file',file);toast('Lettura di '+file.name+'…');current=await api('/api/projects/'+current.id+'/sources','POST',form)}await loadDocuments();render();toast('Fonti aggiunte')}catch(error){toast(error.message)}
};
function openModelSetup(reason='Scegli un modello GGUF gia presente sul disco.'){
  navigatePage(true);
  $('model-setup-reason').textContent=reason;$('model-setup-status').textContent='';
  if(!$('model-setup').open)$('model-setup').showModal();
}
async function models(preferred=null){
  const data=await api('/api/models'),previous=preferred||$('model').value||pref.model||data.default_model;
  modelInfo=data;
  $('model').innerHTML='<option value="">Scegli il modello locale</option>'+data.models.map(m=>
    '<option value="'+esc(m.id)+'">'+esc(m.name)+' · '+m.size_gb+' GB'+(m.vision?' · vision':'')+'</option>').join('');
  if(data.models.some(m=>m.id===previous))$('model').value=previous;
  else if(!previous){const candidate=data.models.find(m=>m.vision&&m.name.startsWith('gemma'))||data.models[0];if(candidate)$('model').value=candidate.id}
  const missing=!data.models.length?'Nessun modello GGUF trovato. Scegli un file dal disco per generare localmente.':
    previous&&!data.models.some(m=>m.id===previous)?'Il modello scelto non e piu disponibile: potrebbe essere stato spostato o il disco scollegato. Scegli il file aggiornato.':'';
  const runtime=data.runtime_available===false?'Manca il motore llama.cpp: aggiungi llama-server.exe e le DLL in runtime/llama, oppure usa una API remota.':'';
  $('model-warning').textContent=[missing,runtime].filter(Boolean).join(' ');
  $('model-warning').hidden=!missing&&!runtime;
  if(missing&&$('provider').value==='local'&&!modelNotices.has(missing)){
    modelNotices.add(missing);openModelSetup(missing);
  }
  $('llama-status').textContent=data.status.running?'llama.cpp caricato · porta '+data.status.port:'Avvio integrato alla generazione · scarico dopo 5 minuti inattivi';
  $('model').dataset.previous=$('model').value;
  updateModelSummary();
  if(!$('admin').hidden&&!adminDirty)await loadAdmin();
}
$('add-local-model').onclick=()=>openModelSetup();
$('close-model-setup').onclick=()=>$('model-setup').close();
$('setup-remote').onclick=()=>{$('provider').value='remote';fields();$('model-setup').close();$('api-url').focus()};
async function connectLocalModel(action){
  $('browse-model').disabled=true;$('register-model').disabled=true;
  $('model-setup-status').textContent=action==='pick'?'Scegli il GGUF nella finestra di Windows…':'Controllo del file…';
  try{
    const result=await api('/api/local-models/'+action,'POST',action==='register'?{path:$('local-model-path').value}:{});
    if(result.cancelled){$('model-setup-status').textContent='Selezione annullata. Nessun modello modificato.';return}
    pref.model=result.model;await models(result.model);savePrefs();$('model-setup').close();
    toast('Modello collegato e scelta salvata. Il file originale non e stato copiato.');
  }catch(error){$('model-setup-status').textContent=error.message}
  finally{$('browse-model').disabled=false;$('register-model').disabled=false}
}
$('browse-model').onclick=()=>connectLocalModel('pick');
$('register-model').onclick=()=>connectLocalModel('register');
$('refresh-models').onclick=()=>models().catch(e=>toast(e.message));
$('unload').onclick=async()=>{try{await api('/api/llm/stop','POST',{});await models();toast('Modello di H3-slides scaricato')}catch(e){toast(e.message)}};
async function generate(slideId=null,diagramOnly=false,regenerateAll=false,replaceDiagrams=false){
  if(busy)return;busy=true;$('generate').disabled=true;
  try{
    await finishInlineEdits();
    if(regenerateAll&&current?.slides.length&&!confirm('Rigenerare tutte le slide? I contenuti attuali saranno sostituiti; brief, fonti, tema, ordine e scaletta restano invariati.'))return;
    if(replaceDiagrams&&!confirm('Riprogettare tutti i diagrammi con il modello? I testi delle slide restano invariati.'))return;
    if($('provider').value==='local'&&adminDirty){
      navigatePage(true);throw new Error('Salva il profilo llama.cpp modificato in Admin prima di generare.');
    }
    if(!current||drafts.has('brief'))await saveProject();
    if($('provider').value==='local')await models();
    else try{remoteModels.requireSelection();apiSettings.value()}catch(error){navigatePage(true);throw error}
    const selected=provider();
    if(!selected.model){
      if(selected.mode==='local')openModelSetup('Prima di generare, scegli un modello GGUF dal disco.');
      throw new Error('Seleziona un modello');
    }
    if(selected.mode==='local'&&modelInfo?.runtime_available===false){navigatePage(true);throw new Error($('model-warning').textContent)}
    if(selected.mode==='remote'&&!selected.remote_consent){
      navigatePage(true);$('consent').focus();
      throw new Error('In Admin autorizza l’invio al server scelto, poi torna a Crea e premi Genera.');
    }
    if(!diagramOnly&&current.web_enabled&&!$('web-consent').checked)throw new Error('Conferma la query da inviare al motore di ricerca');
    savePrefs();
    const instructions=slideId?prompt(diagramOnly?'Descrivi cosa deve spiegare il diagramma Manim:':'Istruzioni per rigenerare questa slide:',
      diagramOnly?(current.slides.find(s=>s.id===slideId)?.content.diagram?.brief||current.slides.find(s=>s.id===slideId)?.content.title||''):current.prompt):$('prompt').value;
    if(instructions===null)return;
    job=await api('/api/projects/'+current.id+'/generate','POST',{provider:selected,prompt:instructions,count:Number($('count').value),slide_id:slideId,
      diagram_only:diagramOnly,replace_diagrams:replaceDiagrams,regenerate_all:regenerateAll,
      web_consent:diagramOnly?false:$('web-consent').checked,web_refresh:diagramOnly?false:$('web-refresh').checked});
    $('web-consent').checked=false;$('web-refresh').checked=false;
    toast('Generazione avviata');await poll();
  }catch(e){toast(e.message)}finally{busy=false;$('generate').disabled=false}
}
$('generate').onclick=()=>generate();
$('regenerate-all').onclick=()=>generate(null,false,true);
$('generate-missing-diagrams').onclick=()=>generate(null,true);
$('redesign-diagrams').onclick=()=>generate(null,true,false,true);
api('/api/admin/search').then(settings=>{$('searxng-url').value=settings.searxng_url}).catch(e=>{$('search-settings-status').textContent=e.message});
$('save-search-settings').onclick=async()=>{
  try{
    const settings=await api('/api/admin/search','POST',{searxng_url:$('searxng-url').value});
    $('searxng-url').value=settings.searxng_url;$('web-consent').checked=false;
    $('search-settings-status').textContent='Indirizzo salvato solo su questo computer. Nessun servizio avviato automaticamente.';
  }catch(e){$('search-settings-status').textContent=e.message}
};
$('open-slidev').onclick=async()=>{
  if(!current){toast('Crea prima un progetto');return}
  const tab=window.open('about:blank','_blank');
  try{await finishInlineEdits();if(drafts.has('brief'))await saveProject();const result=await api('/api/projects/'+current.id+'/slidev','POST',{});
    if(tab)tab.location.href=result.url;else toast('Slidev pronto: '+result.url);
  }catch(error){if(tab)tab.close();toast(error.message)}
};
function sourceHTML(s){
  return '<div class="source"><div class="source-head"><strong>'+esc(s.name)+'</strong>'+
    '<span class="source-actions"><a class="quiet button-link" href="/api/documents/'+encodeURIComponent(current.id)+'/'+encodeURIComponent(s.id)+'" target="_blank" rel="noopener">Apri</a>'+
    '<button type="button" class="quiet danger" data-remove-source="'+esc(s.id)+'">Rimuovi</button></span></div>'+
    (s.page_count?'<div class="muted">'+s.page_count+' pagine indicizzate · ricerca locale</div>':'')+
    (s.selection?'<details open><summary>Pagine usate: '+esc(s.selection.summary)+'</summary><small>'+esc(s.selection.reason)+'</small></details>':
      s.page_count?'<small>La sezione verrà individuata dal modello alla generazione.</small>':'')+
    '<br>'+s.images.filter(i=>!s.selection||s.selection.pdf_pages.includes(i.pdf_page)).slice(0,8).map(i=>'<img src="/api/assets/'+current.id+'/'+i.id+'" alt="'+esc(i.label)+'" title="'+esc(i.label)+'">').join('')+
    (s.images.length>8?'<small>+'+(s.images.length-8)+' pagine</small>':'')+
    (s.warnings.length?'<div class="warning">'+esc(s.warnings[0])+'</div>':'')+'</div>';
}
$('sources').onclick=async event=>{
  const button=event.target.closest('[data-remove-source]');if(!button||!current)return;
  const source=current.sources.find(item=>item.id===button.dataset.removeSource);if(!source)return;
  if(!confirm('Rimuovere «'+source.name+'» dal progetto? Le slide già create resteranno; le immagini di questo documento verranno scollegate.'))return;
  button.disabled=true;
  try{
    current=await api('/api/projects/'+current.id+'/sources/'+encodeURIComponent(source.id),'DELETE');
    await loadDocuments();render();toast('Documento rimosso dal progetto');
  }catch(error){
    toast(error.message);if(button.isConnected)button.disabled=false;
  }
};
$('document-library').onclick=async event=>{
  const button=event.target.closest('[data-reuse-source]');if(!button)return;
  button.disabled=true;
  try{
    if(!current||drafts.has('brief'))await saveProject();
    current=await api('/api/projects/'+current.id+'/sources/reuse','POST',{
      project_id:button.dataset.reuseProject,source_id:button.dataset.reuseSource});
    await loadDocuments();render();toast('Documento aggiunto al progetto dalla libreria locale');
  }catch(error){toast(error.message);if(button.isConnected)button.disabled=false}
};
const resize=new ResizeObserver(entries=>{for(const entry of entries)entry.target.style.setProperty('--slide-scale',entry.contentRect.width/1280)});
function render(){
  const display=current?{...current,...design(),theme:$('theme').value}:null;
  const preview=display||brief(),t=themeFor(preview),box=blockColors(preview,{kind:'explanation'});
  const low=contrast(t.bg,t.fg)<4.5||contrast(t.bg,t.heading)<4.5||
    ['explanation','example','key','quote'].some(kind=>{const b=blockColors(preview,{kind});return contrast(b.bg,b.fg)<4.5});
  $('theme-contrast').textContent=low?'Attenzione: una combinazione manuale ha poco contrasto. Riattiva Automatico per migliorarla.':'Contrasto del testo verificato · anteprima immediata.';
  const autoValues={text_color:t.fg,title_color:t.heading,box_text_color:box.fg,border_color:box.border,
    ...Object.fromEntries(['explanation','example','key','quote'].map(kind=>[kind+'_color',blockColors(preview,{kind}).bg]))};
  for(const key of Object.keys(themeColors))if($('theme-editor').querySelector('[data-theme-auto="'+key+'"]').checked)
    $('theme-editor').querySelector('[data-theme-color="'+key+'"]').value=autoValues[key];
  $('deck-title').textContent=current?.title||'Spazio alle idee.';
  $('sources').innerHTML=current?current.sources.map(sourceHTML).join(''):'';
  renderDocumentLibrary();
  $('web-options').hidden=!$('web-enabled').checked;
  $('source-mode').textContent=$('web-enabled').checked?'Ricerca web attiva: estratti delle pagine lette ed eventuali allegati. Verifica le fonti prima dell’uso.':
    current?.sources.length?'Con documenti allegati: il modello usa le fonti fornite. Le immagini richiedono vision.':'Nessun allegato: genera dalla conoscenza del modello. Nessuna ricerca web; verifica fatti e date importanti.';
  const research=current?.web_research;
  $('web-sources').innerHTML=research?'<details open><summary>Ultima ricerca completata · '+esc(research.provider)+'</summary>'+
    '<p class="hint">'+esc(research.query)+' · '+esc(new Date(research.created_at*1000).toLocaleString())+
    (research.cache_used?' · cache locale':'')+'</p>'+
    research.sources.map(s=>'<p class="hint"><a href="'+esc(/^https?:\/\//.test(s.url)?s.url:'#')+
      '" target="_blank" rel="noopener noreferrer">'+esc(s.id+' · '+s.title)+'</a></p>').join('')+
    (research.warnings||[]).map(w=>'<p class="hint">'+esc(w)+'</p>').join('')+
    '<small>Fonti lette in quella generazione: modificare la query non aggiorna le slide già pronte.</small></details>':'';
  $('empty').hidden=Boolean(current?.slides.length);$('slide-count').textContent=(current?.slides.length||0)+' slide';
  const container=$('slides'),ids=new Set();
  for(const [index,slide] of (current?.slides||[]).entries()){
    ids.add(slide.id);let card=document.getElementById('slide-'+slide.id);
    if(!card){card=document.createElement('section');card.id='slide-'+slide.id;card.draggable=true;container.append(card)}
    card.className='slide-card '+slide.status;card.dataset.id=slide.id;
    const signature=JSON.stringify([slide,display.theme,design(),index]);
    if(card.dataset.signature!==signature&&!card.dataset.saving&&!card.querySelector('[contenteditable="plaintext-only"]')){
      card.dataset.signature=signature;
      card.innerHTML='<div class="slide-top"><span class="slide-label">⠿ '+String(index+1).padStart(2,'0')+' / '+esc(slide.status==='ready'?'Pronta':slide.status==='generating'?'Generazione…':'In attesa')+'</span>'+
        '<button class="quiet" data-action="up" aria-label="Sposta su">↑</button><button class="quiet" data-action="down" aria-label="Sposta giù">↓</button>'+
        '<button class="quiet" data-action="edit">Modifica</button><button class="quiet" data-action="regenerate">Rigenera</button>'+
        (current.use_manim_diagrams?'<button class="quiet diagram-action" data-action="'+
          (slide.content.diagram?.kind==='manim'&&slide.content.diagram?.scene&&!slide.diagram_render?.asset?'render':'diagram')+'">'+
          (slide.diagram_render?.engine==='manim'?'Riproggetta Manim':slide.content.diagram?.kind==='manim'&&slide.content.diagram?.scene?'Renderizza Manim':'Progetta Manim')+'</button>':'')+'</div>'+
        '<div class="composition-tools"><label>Composizione <select data-slide-layout '+(slide.status!=='ready'?'disabled':'')+'>'+layoutOptions(slide.content.layout)+'</select></label>'+
        '<button class="quiet" data-action="recompose" '+(slide.status!=='ready'?'disabled':'')+'>↻ Ricomponi</button>'+
        '<button class="quiet" data-action="split" '+(slide.status!=='ready'?'disabled':'')+'>Dividi</button><span class="composition-status" aria-live="polite"></span></div>'+
        '<div class="slide-preview" title="Doppio clic su un testo per modificarlo">'+slideHTML(display,slide,index,
          slide.diagram_render?.asset?'/api/assets/'+current.id+'/'+slide.diagram_render.asset:
          slide.content.image_id?'/api/assets/'+current.id+'/'+slide.content.image_id:'')+'</div>'+
        (slide.content.diagram?.kind!=='none'&&!slide.diagram_render?.asset?
          '<p class="diagram-pending">'+(slide.content.diagram?.kind==='manim'&&slide.content.diagram?.scene?
            'La scena è valida ma il render va aggiornato. Usa Renderizza Manim.':'Il vecchio diagramma va riprogettato con Manim.')+'</p>':'');
      const select=card.querySelector('[data-slide-layout]');
      select.value=({split:'visual-right',statement:'focus'})[slide.content.layout]||slide.content.layout||'content';
      resize.observe(card.querySelector('.slide-preview'));
      const fit=()=>{
        if(!card.isConnected)return;
        const result=fitSlide(card.querySelector('.slide-frame'));
        card.querySelector('.composition-status').textContent=layouts[result.layout]+(result.adjusted?' · adattato allo spazio':'')+' · testi invariati';
        card.querySelector('.layout-warning')?.remove();
        if(result.overflow){
          const warning=document.createElement('p');warning.className='layout-warning';
          warning.textContent='Questo contenuto non entra nelle disposizioni provate. Dividilo in più slide o modifica il testo. L’export si ferma invece di tagliarlo.';
          card.append(warning);
        }
      };
      requestAnimationFrame(fit);
      document.fonts.ready.then(fit);
    }
    if(container.children[index]!==card)container.insertBefore(card,container.children[index]||null);
  }
  for(const card of [...container.children])if(!ids.has(card.dataset.id))card.remove();
  document.querySelectorAll('[data-export]').forEach(b=>b.disabled=!current?.slides.length||exporting.has(b.dataset.export));
  const hasSlides=Boolean(current?.slides.length);
  $('regenerate-all').disabled=!current||busy;
  $('regenerate-all').textContent=hasSlides?'↻ Rigenera tutte le slide':'↻ Riprova generazione';
  const missingDiagrams=(current?.slides||[]).filter(slide=>slide.content?.layout!=='cover'&&slide.status==='ready'&&!slide.diagram_render?.asset).length;
  $('generate-missing-diagrams').hidden=!current?.use_manim_diagrams;
  $('generate-missing-diagrams').disabled=!missingDiagrams||busy;
  $('generate-missing-diagrams').textContent='◇ Crea diagrammi mancanti'+(missingDiagrams?' · '+missingDiagrams:'');
  const diagramSlides=(current?.slides||[]).filter(slide=>slide.content?.layout!=='cover'&&slide.status==='ready').length;
  $('redesign-diagrams').hidden=!current?.use_manim_diagrams;
  $('redesign-diagrams').disabled=!diagramSlides||busy;
  $('redesign-diagrams').textContent='✦ Riprogetta tutti i diagrammi'+(diagramSlides?' · '+diagramSlides:'');
}
async function rerenderDiagram(id){
  if(busy)throw new Error('Attendi la generazione in corso');
  const slide=current.slides.find(item=>item.id===id);if(!slide)throw new Error('Slide non trovata');
  busy=true;render();
  try{
    current=await api('/api/projects/'+current.id+'/slides/'+id,'PATCH',
      {revision:slide.revision,content:slide.content});
    render();toast('Render Manim aggiornato');
  }finally{busy=false;render()}
}
function editSlide(id){
  const slide=current.slides.find(s=>s.id===id);editing=structuredClone(slide);
  for(const field of ['title','subtitle','layout','animation','notes'])$('edit-'+field).value=slide.content[field];
  $('edit-layout').value=({split:'visual-right',statement:'focus'})[slide.content.layout]||slide.content.layout||'content';
  $('edit-bullets').value=slide.content.bullets.join('\n');$('edit-sources').value=slide.content.sources.join('\n');
  $('edit-image').innerHTML='<option value="">Nessuna immagine</option>'+current.sources.flatMap(s=>s.images).map(i=>'<option value="'+i.id+'">'+esc(i.label)+'</option>').join('');
  $('edit-image').value=slide.content.image_id;$('edit-error').textContent='';$('editor').showModal();
  $('edit-diagram-kind').value=slide.content.diagram?.kind||'none';
  $('edit-diagram-labels').value=(slide.content.diagram?.labels||[]).join('\n');
  $('edit-diagram-brief').value=slide.content.diagram?.brief||'';
  fillSceneEditor(slide.content.diagram?.scene);
  showSceneEditor();
  $('edit-blocks').innerHTML='';
  for(const block of slide.content.blocks||[])addBlockEditor(block);
}
const elementTypes={box:'Riquadro',decision:'Decisione',circle:'Entità',database:'Archivio',document:'Documento',
  text:'Annotazione',grid:'Griglia / pixel',bars:'Grafico a barre',plot:'Grafico lineare',
  venn:'Diagramma di Venn',gantt:'Diagramma di Gantt',timeline:'Timeline',
  tree:'Albero / gerarchia',network:'Rete / grafo'};
const tones={accent:'Accento',blue:'Blu',amber:'Ambra',red:'Rosso',violet:'Viola',neutral:'Neutro'};
function options(values,current){return Object.entries(values).map(([value,label])=>'<option value="'+value+'" '+(value===current?'selected':'')+'>'+label+'</option>').join('')}
function addSceneElement(value={}){
  const n=$('scene-elements').children.length;
  const defaults={id:'oggetto'+(n+1),type:'box',x:2+(n%3)*4,y:2.4+Math.floor(n/3)*2.6,width:3,height:1.3,text:'',caption:'',tone:'accent',stage:n+1,values:[],labels:[],columns:4};
  value={...defaults,...value};const row=document.createElement('fieldset');row.className='scene-item';
  row.innerHTML='<div class="row"><label>ID<input data-scene="id" maxlength="32" pattern="[A-Za-z][A-Za-z0-9_-]{0,31}" required></label>'+
    '<label>Oggetto<select data-scene="type">'+options(elementTypes,value.type)+'</select></label>'+
    '<label>Tono<select data-scene="tone">'+options(tones,value.tone)+'</select></label></div>'+
    '<label>Testo<input data-scene="text" maxlength="80"></label><label>Didascalia<input data-scene="caption" maxlength="90"></label>'+
    '<div class="scene-geometry">'+['x','y','width','height','stage','columns'].map(key=>'<label>'+key+
      '<input data-scene="'+key+'" type="number" step="'+(key==='stage'||key==='columns'?'1':'.1')+'" required></label>').join('')+'</div>'+
    '<div class="row"><label>Valori · separati da virgola<textarea data-scene="values" rows="2"></textarea></label>'+
    '<label>Etichette · una per riga<textarea data-scene="labels" rows="2"></textarea></label></div>'+
    '<button type="button" class="quiet danger" data-remove-scene>Rimuovi oggetto</button>';
  for(const [key,item] of Object.entries(value)){const input=row.querySelector('[data-scene="'+key+'"]');if(input)input.value=Array.isArray(item)?item.join(key==='labels'?'\n':', '):item}
  row.querySelector('[data-remove-scene]').onclick=()=>row.remove();$('scene-elements').append(row);
}
function addSceneConnection(value={}){
  value={source:'',target:'',label:'',tone:'neutral',...value};const row=document.createElement('fieldset');row.className='scene-item scene-edge';
  row.innerHTML='<div class="row"><label>Da ID<input data-edge="source" maxlength="32" required></label><label>A ID<input data-edge="target" maxlength="32" required></label>'+
    '<label>Tono<select data-edge="tone">'+options(tones,value.tone)+'</select></label></div>'+
    '<label>Significato della relazione<input data-edge="label" maxlength="34"></label><button type="button" class="quiet danger" data-remove-edge>Rimuovi relazione</button>';
  for(const [key,item]of Object.entries(value)){const input=row.querySelector('[data-edge="'+key+'"]');if(input)input.value=item}
  row.querySelector('[data-remove-edge]').onclick=()=>row.remove();$('scene-connections').append(row);
}
function fillSceneEditor(scene){
  $('scene-elements').replaceChildren();$('scene-connections').replaceChildren();
  $('scene-title').value=scene?.title||'';$('scene-takeaway').value=scene?.takeaway||'';
  for(const element of scene?.elements||[])addSceneElement(element);
  for(const edge of scene?.connections||[])addSceneConnection(edge);
}
function showSceneEditor(){
  const manim=$('edit-diagram-kind').value==='manim';
  $('scene-editor').hidden=!manim;$('legacy-diagram-labels').hidden=manim||$('edit-diagram-kind').value==='none';
}
function sceneFromEditor(){
  const elements=[...$('scene-elements').children].map(row=>{
    const item=Object.fromEntries([...row.querySelectorAll('[data-scene]')].map(input=>[input.dataset.scene,input.value.trim()]));
    for(const key of ['x','y','width','height','stage','columns'])item[key]=Number(item[key]);
    item.values=item.values.split(/[\s,;]+/).filter(Boolean).map(Number);
    item.labels=item.labels.split('\n').map(value=>value.trim()).filter(Boolean);
    return item;
  });
  const connections=[...$('scene-connections').children].map(row=>
    Object.fromEntries([...row.querySelectorAll('[data-edge]')].map(input=>[input.dataset.edge,input.value.trim()])));
  return {title:$('scene-title').value.trim(),takeaway:$('scene-takeaway').value.trim(),elements,connections};
}
$('edit-diagram-kind').onchange=showSceneEditor;
$('add-scene-element').onclick=()=>addSceneElement();
$('add-scene-connection').onclick=()=>addSceneConnection();
function addBlockEditor(block={heading:'',text:'',kind:'explanation',source:''}){
  if($('edit-blocks').children.length>=4){toast('Massimo 4 box per slide');return}
  const row=document.createElement('fieldset');row.className='block-editor';
  row.innerHTML='<label>Titolo del box<input data-block="heading" maxlength="70"></label>'+
    '<label>Tipo / colore<select data-block="kind"><option value="explanation">Spiegazione · accento del tema</option><option value="example">Esempio · azzurro</option><option value="key">Da ricordare · ambra</option><option value="quote">Citazione · viola</option></select></label>'+
    '<label>Paragrafo<textarea data-block="text" rows="7" maxlength="1600" required></textarea></label>'+
    '<label>Fonte e pagina<input data-block="source" maxlength="220"></label>'+
    '<button type="button" class="quiet danger" data-remove-block>Rimuovi box</button>';
  for(const [key,value]of Object.entries(block)){const input=row.querySelector('[data-block="'+key+'"]');if(input)input.value=value}
  row.querySelector('[data-remove-block]').onclick=()=>row.remove();
  $('edit-blocks').append(row);
}
$('add-block').onclick=()=>addBlockEditor();
$('close-editor').onclick=()=>$('editor').close();
$('edit-form').onsubmit=async e=>{
  e.preventDefault();
  const content={...editing.content};
  for(const field of ['title','subtitle','layout','animation','notes'])content[field]=$('edit-'+field).value;
  if(content.layout!==editing.content.layout)content.layout_variant=0;
  content.bullets=$('edit-bullets').value.split('\n').map(s=>s.trim()).filter(Boolean);
  content.blocks=[...$('edit-blocks').children].map(row=>Object.fromEntries(
    [...row.querySelectorAll('[data-block]')].map(field=>[field.dataset.block,field.value.trim()])));
  content.sources=$('edit-sources').value.split('\n').map(s=>s.trim()).filter(Boolean);content.image_id=$('edit-image').value;
  const kind=$('edit-diagram-kind').value;
  content.diagram={kind,labels:$('edit-diagram-labels').value.split('\n').map(s=>s.trim()).filter(Boolean),
    brief:$('edit-diagram-brief').value.trim(),scene:kind==='manim'?sceneFromEditor():null};
  if(kind==='none'){content.diagram.labels=[];content.diagram.brief=''}
  try{
    const updated=await api('/api/projects/'+current.id+'/slides/'+editing.id,'PATCH',{revision:editing.revision,content});
    current.slides[current.slides.findIndex(s=>s.id===updated.id)]=updated;$('editor').close();render();toast('Slide salvata');
  }catch(error){$('edit-error').textContent=error.message}
};
async function move(id,index){
  const ids=current.slides.map(s=>s.id),old=ids.indexOf(id);ids.splice(old,1);ids.splice(Math.max(0,Math.min(ids.length,index)),0,id);
  current=await api('/api/projects/'+current.id+'/reorder','POST',{ids});render();
}
$('slides').onclick=e=>{
  const button=e.target.closest('button[data-action]');if(!button)return;
  const id=button.closest('.slide-card').dataset.id,index=current.slides.findIndex(s=>s.id===id);
  if(button.dataset.action==='edit')editSlide(id);
  if(button.dataset.action==='regenerate')generate(id);
  if(button.dataset.action==='diagram')generate(id,true);
  if(button.dataset.action==='render')rerenderDiagram(id).catch(error=>toast(error.message));
  if(button.dataset.action==='recompose')changeLayout(id,'content',true).catch(e=>toast(e.message));
  if(button.dataset.action==='split')splitSlide(id).catch(e=>toast(e.message));
  if(button.dataset.action==='up')move(id,index-1).catch(e=>toast(e.message));
  if(button.dataset.action==='down')move(id,index+1).catch(e=>toast(e.message));
};
async function changeLayout(id,layout,recompose=false){
  await finishInlineEdits();
  const pid=current.id,slide=current.slides.find(s=>s.id===id),content=structuredClone(slide.content);
  content.layout=layout;content.layout_variant=recompose?((content.layout_variant||0)+1)%10001:0;
  const card=document.getElementById('slide-'+id);card.dataset.saving='1';
  try{
    const updated=await api('/api/projects/'+pid+'/slides/'+id,'PATCH',{revision:slide.revision,content});
    if(current?.id===pid)current.slides[current.slides.findIndex(s=>s.id===id)]=updated;
    toast('Composizione salvata. Nessun testo riscritto e nessuna chiamata al modello.');
  }finally{delete card.dataset.saving;delete card.dataset.signature;render()}
}
async function splitSlide(id){
  await finishInlineEdits();
  if(!confirm('Dividere questa slide in più pagine, conservando testi, immagini e fonti? Non viene usato il modello.'))return;
  const pid=current.id,slide=current.slides.find(s=>s.id===id);
  const result=await api('/api/projects/'+pid+'/slides/'+id+'/split','POST',{revision:slide.revision});
  if(current?.id===pid){current=result;$('count').value=result.count;render();await loadProjects()}
  toast('Contenuto distribuito su più slide, senza riscritture.');
}
$('slides').onchange=e=>{
  if(e.target.matches('[data-slide-layout]'))changeLayout(e.target.closest('.slide-card').dataset.id,e.target.value).catch(error=>toast(error.message));
};
$('slides').ondblclick=e=>{
  const field=e.target.closest('[data-edit-field]');if(!field||field.isContentEditable)return;
  const card=field.closest('.slide-card'),slide=current.slides.find(s=>s.id===card.dataset.id);
  if(slide.status!=='ready'){toast('Attendi che questa scheda sia pronta');return}
  const original=field.textContent,content=structuredClone(slide.content),revision=slide.revision,pid=current.id;
  field.contentEditable='plaintext-only';field.focus();card.draggable=false;
  let cancelled=false;
  field.onkeydown=event=>{if(event.key==='Escape'){cancelled=true;field.textContent=original;field.blur()}else if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();field.blur()}};
  field.onblur=async()=>{
    const value=field.textContent.trim();field.removeAttribute('contenteditable');card.draggable=true;
    if(cancelled||value===original){render();return}
    if(field.dataset.editField==='bullets')content.bullets[Number(field.dataset.index)]=value;
    else if(field.dataset.editField.startsWith('block-'))content.blocks[Number(field.dataset.index)][field.dataset.editField.slice(6)]=value;
    else content[field.dataset.editField]=value;
    card.dataset.saving='1';
    const pending=api('/api/projects/'+pid+'/slides/'+slide.id,'PATCH',{revision,content});inlineSaves.add(pending);
    try{
      const updated=await pending;
      if(current?.id===pid)current.slides[current.slides.findIndex(s=>s.id===updated.id)]=updated;
      render();toast('Testo salvato');
    }catch(error){field.textContent=value;field.contentEditable='plaintext-only';field.focus();card.draggable=false;toast(error.message+' — testo non salvato. Premi Esc per annullare.');}
    finally{inlineSaves.delete(pending);delete card.dataset.saving;render()}
  };
};
$('slides').ondragstart=e=>{const card=e.target.closest('.slide-card');if(card){dragged=card.dataset.id;card.classList.add('dragging')}};
$('slides').ondragend=()=>document.querySelectorAll('.dragging').forEach(c=>c.classList.remove('dragging'));
$('slides').ondragover=e=>e.preventDefault();
$('slides').ondrop=e=>{e.preventDefault();const card=e.target.closest('.slide-card');if(card&&dragged)move(dragged,current.slides.findIndex(s=>s.id===card.dataset.id)).catch(e=>toast(e.message));dragged=null};
for(const action of ['pause','cancel'])$(action).onclick=async()=>{
  if(!job)return;try{const command=action==='pause'&&job.status==='paused'?'resume':action;
  await api('/api/jobs/'+job.id+'/'+command,'POST',{});await poll()}catch(e){toast(e.message)}
};
document.querySelectorAll('[data-export]').forEach(button=>button.onclick=async()=>{
  if(!current)return;const old=button.textContent;exporting.add(button.dataset.export);button.disabled=true;button.textContent='Preparazione…';
  try{await finishInlineEdits();if(drafts.has('brief'))await saveProject();const result=await api('/api/projects/'+current.id+'/export/'+button.dataset.export,'POST',{});
    const a=document.createElement('a');a.href=result.url;a.download=result.filename;a.click();toast('Esportazione pronta');
  }catch(error){toast(error.message)}finally{exporting.delete(button.dataset.export);button.textContent=old;button.disabled=false}
});
async function poll(){
  if(polling)return;polling=true;
  try{
    jobs=await api('/api/jobs');$('connection').textContent='● Locale · salvato sul PC';
    if(current){
      const requested=current.id;
      const fresh=await api('/api/projects/'+requested);
      if(current?.id!==requested)return;
      current=fresh;render();
      job=jobs.find(j=>j.project_id===current.id)||null;
    }
    $('job-panel').hidden=!job;
    if(job){
      const active=['queued','running','paused'].includes(job.status);
      $('job-status').textContent=job.error||job.events.at(-1)?.message||job.status;
      $('job-percent').textContent=Math.round(job.progress*100)+'% · '+job.status;
      $('progress').value=job.progress;
      $('events').textContent=job.events.map(e=>new Date(e.at*1000).toLocaleTimeString()+'  '+e.message).join('\n');
      $('pause').hidden=!active;$('cancel').hidden=!active;$('pause').textContent=job.status==='paused'?'Riprendi':'Pausa';
    }
  }catch(error){$('connection').textContent='● App non raggiungibile'}finally{polling=false}
}
async function init(){
  try{await Promise.all([loadProjects(),loadDocuments(),models()]);const id=new URLSearchParams(location.search).get('project')||localStorage.getItem('h3slides-project');
    if(projects.some(p=>p.id===id))await selectProject(id);await poll();
  }catch(error){toast(error.message)}
  setInterval(poll,1500);
}
init();

const adminLabels={context_size:'Contesto (token)',gpu_layers:'Layer sulla GPU',threads:'Thread CPU',batch_size:'Batch logico',ubatch_size:'Micro-batch',flash_attention:'Flash Attention',cache_type_k:'Cache K',cache_type_v:'Cache V',load_mode:'Modalità di caricamento',cpu_moe_layers:'Layer MoE da tenere su CPU',temperature:'Temperatura',top_p:'Top-p',top_k:'Top-k',min_p:'Min-p',repeat_penalty:'Penalità ripetizione',max_tokens:'Massimo token di output',seed:'Seed (-1 = casuale)',thinking:'Ragionamento esteso (thinking)'};
function fillAdmin(){
  const profile=adminData.profiles[$('admin-model').value];
  $('admin-form').querySelectorAll('button').forEach(button=>button.disabled=!profile);
  if(!profile){$('admin-loading').replaceChildren();$('admin-inference').replaceChildren();$('admin-status').textContent='Aggiungi un GGUF per configurare il profilo locale.';return}
  adminDirty=false;$('admin-model').dataset.previous=profile.model;
  for(const group of ['loading','inference']){
    $('admin-'+group).innerHTML=Object.entries(adminData[group+'_schema'].properties).map(([key,schema])=>{
      const value=profile[group][key],name=group+'.'+key;let input;
      if(schema.enum)input='<select data-setting="'+name+'">'+schema.enum.map(v=>'<option '+(v===value?'selected':'')+'>'+esc(v)+'</option>').join('')+'</select>';
      else if(schema.type==='boolean')input='<input type="checkbox" data-setting="'+name+'" '+(value?'checked':'')+'>';
      else input='<input type="number" data-setting="'+name+'" step="'+(schema.type==='integer'?'1':'.01')+'" value="'+value+'"'+
        (schema.minimum!==undefined?' min="'+schema.minimum+'"':'')+(schema.exclusiveMinimum!==undefined?' min="0.01"':'')+(schema.maximum!==undefined?' max="'+schema.maximum+'"':'')+'>';
      return '<label class="'+(schema.type==='boolean'?'check':'')+'">'+esc(adminLabels[key]||key)+input+'</label>';
    }).join('');
  }
  $('admin-status').textContent=adminData.status.running?'Modello attualmente caricato: '+adminData.status.model:'Nessun modello caricato.';
}
async function loadAdmin(){
  if(adminDirty)return;
  if(adminLoading)return adminLoading;
  adminLoading=(async()=>{
    const fresh=await api('/api/admin/llm');
    if(adminDirty)return;
    adminData=fresh;$('admin-model').innerHTML=adminData.models.map(m=>'<option value="'+esc(m.id)+'">'+esc(m.name)+' · '+m.size_gb+' GB</option>').join('');
    if(adminData.profiles[$('model').value])$('admin-model').value=$('model').value;
    fillAdmin();
  })().catch(error=>{$('admin-status').textContent=error.message}).finally(()=>{adminLoading=null});
  return adminLoading;
}
function navigatePage(page,push=true){
  if(typeof page==='boolean')page=page?'admin':'create';
  const admin=page==='admin',library=page==='library';
  $('admin').hidden=!admin;$('library').hidden=!library;$('create-page').hidden=admin||library;
  $('open-admin').setAttribute('aria-current',admin?'page':'false');
  $('open-library').setAttribute('aria-current',library?'page':'false');
  $('open-create').setAttribute('aria-current',!admin&&!library?'page':'false');
  document.title=admin?'Admin · H3-slides':library?'Progetti · H3-slides':'H3-slides · Studio';
  const path=admin?'/admin':library?'/library':'/';
  if(push&&location.pathname!==path)history.pushState({},'',path+location.search);
  if(admin)loadAdmin();else if(library){loadProjects()}else{render();requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))}
}
$('open-admin').onclick=()=>navigatePage('admin');
$('open-library').onclick=()=>navigatePage('library');
$('configure-model').onclick=()=>navigatePage('admin');
$('open-create').onclick=$('close-admin').onclick=()=>navigatePage('create');
document.querySelector('.brand').onclick=event=>{event.preventDefault();navigatePage('create')};
window.addEventListener('popstate',()=>navigatePage(location.pathname.replace(/\/$/,'')==='/admin'?'admin':location.pathname.replace(/\/$/,'')==='/library'?'library':'create',false));
$('admin-form').addEventListener('input',event=>{
  if(event.target.dataset.setting){adminDirty=true;$('admin-status').textContent='Profilo modificato · premi Salva profilo prima di generare.'}
});
window.addEventListener('beforeunload',event=>{if(adminDirty){event.preventDefault();event.returnValue=''}});
$('admin-model').onchange=()=>{
  if(adminDirty&&!confirm('Scartare le modifiche non salvate a questo profilo?')){$('admin-model').value=$('admin-model').dataset.previous;return}
  fillAdmin();
};
navigatePage(location.pathname.replace(/\/$/,'')==='/admin'?'admin':location.pathname.replace(/\/$/,'')==='/library'?'library':'create',false);
async function saveAdmin(){
  const profile={model:$('admin-model').value,loading:{},inference:{}};
  for(const input of $('admin').querySelectorAll('[data-setting]')){
    const [group,key]=input.dataset.setting.split('.');
    profile[group][key]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;
  }
  const saved=await api('/api/admin/llm','POST',profile);adminData.profiles[saved.model]=saved;
  adminDirty=false;
  $('model').value=saved.model;$('model').dataset.previous=saved.model;savePrefs();
  $('admin-status').textContent='Profilo salvato. Caricamento applicato al prossimo Carica/Genera; nessun processo riavviato ora.';
  return saved;
}
$('admin-form').onsubmit=async e=>{e.preventDefault();try{await saveAdmin()}catch(error){$('admin-status').textContent=error.message}};
$('admin-load').onclick=async()=>{
  $('admin-load').disabled=true;
  try{const p=await saveAdmin();$('admin-status').textContent='Caricamento del modello…';await api('/api/llm/start','POST',{model:p.model});await models();$('admin-status').textContent='Modello caricato con il profilo scelto.'}
  catch(error){$('admin-status').textContent=error.message}finally{$('admin-load').disabled=false}
};
$('admin-stop').onclick=async()=>{try{await api('/api/llm/stop','POST',{});await models();$('admin-status').textContent='Modello di H3-slides scaricato.'}catch(error){$('admin-status').textContent=error.message}};
$('theme-editor').oninput=e=>{
  if(e.target.dataset.themeAuto){
    $('theme-editor').querySelector('[data-theme-color="'+e.target.dataset.themeAuto+'"]').disabled=e.target.checked;
  }
  drafts.add('brief');$('theme-presets').value='';$('save-status').textContent='Tema in anteprima · salva il brief';render();
};
async function loadThemes(){
  const [builtins,personal]=await Promise.all([fetch('/static/theme-presets.json').then(r=>r.json()),api('/api/themes')]);
  themePresets=[...builtins,...personal];
  $('theme-presets').innerHTML='<option value="">Personalizzato / tema corrente</option>'+themePresets.map((p,i)=>
    '<option value="'+i+'">'+esc(p.name)+(i>=builtins.length?' · personale':'')+'</option>').join('');
}
$('theme-presets').onchange=()=>{
  const preset=themePresets[Number($('theme-presets').value)];if(!preset||$('theme-presets').value==='')return;
  for(const key of ['theme','font','template'])$(key).value=preset.values[key];
  $('background-color').value=preset.values.background_color;$('accent-color').value=preset.values.accent_color;
  fillThemeDesign(preset.values.theme_design);$('theme-name').value=preset.name;
  drafts.add('brief');$('save-status').textContent='Tema applicato in anteprima · salva il brief';render();
};
$('save-theme').onclick=async()=>{
  try{
    const values={theme:$('theme').value,font:$('font').value,template:$('template').value,
      background_color:$('background-color').value,accent_color:$('accent-color').value,theme_design:readThemeDesign()};
    await api('/api/themes','POST',{name:$('theme-name').value,values});
    await loadThemes();$('theme-status').textContent='Tema salvato sul PC, riutilizzabile negli altri progetti. Salva il brief per applicarlo al progetto corrente.';
  }catch(e){$('theme-status').textContent=e.message}
};
loadThemes().catch(e=>{$('theme-status').textContent=e.message});
