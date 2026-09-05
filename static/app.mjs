import {esc,slideHTML,slideCSS,themes,themeFor,blockColors,contrast,layouts,fitSlide,visualAnchorAt,visualFor} from './deck.mjs';
import {createRemoteModelSelector} from './remote-models.mjs';
import {createApiSettings} from './api-settings.mjs';
const $=id=>document.getElementById(id);
const layoutOptions=value=>'<option value="content">Automatico adattivo</option>'+Object.entries(layouts).map(([key,label])=>'<option value="'+key+'" '+(key===value?'selected':'')+'>'+label+'</option>').join('');
$('edit-layout').innerHTML=layoutOptions('content');
const style=document.createElement('style');style.textContent=slideCSS;document.head.append(style);
let current=null,projects=[],documents=[],jobs=[],editing=null,job=null,busy=false,dragged=null;
let componentDrag=null,itemPointer=null;
let imageUploadTarget=null;
const projectImages=()=>[...(current?.sources||[]).flatMap(source=>source.images),...(current?.visual_assets||[])];
const layoutEditors=new Set();
let libraryState={folders:[],order:[],assignments:{}},libraryDragged=null;
function setSidebarCollapsed(collapsed){
  document.body.classList.toggle('sidebar-collapsed',collapsed);
  $('toggle-sidebar').textContent=collapsed?'›':'‹';
  $('toggle-sidebar').title=collapsed?'Espandi menu':'Comprimi menu';
  $('toggle-sidebar').setAttribute('aria-label',$('toggle-sidebar').title);
  $('toggle-sidebar').setAttribute('aria-expanded',String(!collapsed));
  localStorage.setItem('h3slides-sidebar-collapsed',collapsed?'1':'0');
  requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
}
setSidebarCollapsed(localStorage.getItem('h3slides-sidebar-collapsed')==='1');
$('toggle-sidebar').onclick=()=>setSidebarCollapsed(!document.body.classList.contains('sidebar-collapsed'));
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
const designFields={'template':'template','font':'font','text-density':'text_density','background-color':'background_color','accent-color':'accent_color','source-images':'use_source_images','web-images':'use_web_images','openverse-images':'use_openverse_images','manim-diagrams':'use_manim_diagrams','pdf-scope':'pdf_scope',
  'web-enabled':'web_enabled','web-provider':'web_provider','web-query':'web_query','web-max-sources':'web_max_sources','source-priority':'source_priority','web-always-search':'web_always_search'};
// Source priority belongs to the project: a previous web-first choice must not
// silently make new projects web-first as well.
const preferenceIds=['provider','model','api-url','api-model','vision',...Object.keys(designFields).filter(id=>!['web-query','web-enabled','source-priority'].includes(id))];
const pref=JSON.parse(localStorage.getItem('h3slides-settings')||'{}');
const remoteConsents={...(pref.remote_consents||{})};
const webConsents={...(pref.web_consents||{})};
let searchSettingsEndpoint=null;
function normalizedSearchEndpoint(value){
  try{
    const url=new URL(String(value||'').trim());
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)return '';
    return url.origin+url.pathname.replace(/\/+$/,'');
  }catch{return ''}
}
function webConsentKey(){
  const engine=$('web-provider').value;
  if(['wikipedia','duckduckgo'].includes(engine))return engine;
  const saved=normalizedSearchEndpoint(searchSettingsEndpoint);
  return engine==='searxng'&&saved&&saved===normalizedSearchEndpoint($('searxng-url').value)?'searxng|'+saved:'';
}
function restoreWebConsent(){
  const key=webConsentKey();
  $('web-consent').checked=Boolean(key&&webConsents[key]===true);
  $('web-consent').disabled=!key;
  $('web-consent-hint').textContent=key?
    'Scelta ricordata in questo browser per questo motore e, con SearXNG, per questo indirizzo. Deseleziona per revocarla. Non attiva la ricerca nei nuovi progetti.':
    'Carica o salva l’indirizzo SearXNG prima di autorizzarlo. Ogni nuova destinazione richiede una scelta esplicita.';
}
const remoteConsentKey=()=>String($('api-url').value||'').trim().replace(/\/+$/,'');
function restoreRemoteConsent(){
  $('consent').checked=Boolean(remoteConsentKey()&&remoteConsents[remoteConsentKey()]);
}
for(const id of preferenceIds) {
  if(pref[id]!==undefined&&!['model','api-model'].includes(id)) { if($(id).type==='checkbox')$(id).checked=pref[id];else $(id).value=pref[id]; }
}
function savePrefs(){
  const values={};for(const id of preferenceIds)values[id]=$(id).type==='checkbox'?$(id).checked:$(id).value;
  values['api-model']=remoteModels.value();values.remote_models=remoteModels.preferences();
  apiSettings?.sync();values.api_profiles=apiSettings?.preferences()||pref.api_profiles||{};
  values.remote_consents=remoteConsents;
  values.web_consents=webConsents;
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
  $(id).addEventListener('input',()=>{remoteModels.invalidate();apiSettings.sync();updateModelSummary();if(id==='api-url')restoreRemoteConsent()});
  $(id).addEventListener('change',()=>remoteModels.load());
}
$('consent').addEventListener('change',()=>{
  const key=remoteConsentKey();
  if(key){
    if($('consent').checked)remoteConsents[key]=true;
    else delete remoteConsents[key];
  }
  savePrefs();
});
restoreRemoteConsent();
restoreWebConsent();
$('web-consent').addEventListener('change',()=>{
  const key=webConsentKey();
  if(key){
    if($('web-consent').checked)webConsents[key]=true;
    else delete webConsents[key];
  }
  savePrefs();restoreWebConsent();
});
$('searxng-url').addEventListener('input',restoreWebConsent);
for(const id of ['title','prompt','count','theme'])$(id).addEventListener('input',()=>{drafts.add('brief');$('save-status').textContent='Brief non salvato'});
for(const id of Object.keys(designFields))$(id).addEventListener('input',()=>{
  if(id==='web-provider')restoreWebConsent();
  drafts.add('brief');$('save-status').textContent='Stile in anteprima · salva per conservarlo';savePrefs();render();
});
$('theme').addEventListener('change',()=>{const t=themes[$('theme').value];$('background-color').value=t.bg;$('accent-color').value=t.accent;render()});
async function loadProjects(){
  projects=await api('/api/projects');$('project-list').innerHTML='<option value="">Nuovo progetto</option>'+projects.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.title)+' · '+p.slide_count+'</option>').join('');
  if(current)$('project-list').value=current.id;
  renderLibrary();
}
async function loadLibrary(){
  libraryState=await api('/api/library');
  renderLibrary();
}
async function saveLibrary(){
  libraryState=await api('/api/library','POST',libraryState);
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
  $('restore-delete-confirmation').hidden=localStorage.getItem('h3slides-skip-delete-confirmation')!=='1';
  const byId=new Map(projects.map(project=>[project.id,project]));
  const ordered=[...libraryState.order,...projects.map(project=>project.id)]
    .filter((id,index,all)=>byId.has(id)&&all.indexOf(id)===index).map(id=>byId.get(id));
  const card=p=>{
    const when=new Date(p.updated_at),date=Number.isNaN(when.getTime())?'':when.toLocaleString('it-IT',{dateStyle:'medium',timeStyle:'short'});
    return '<article class="project-card" data-project="'+esc(p.id)+'" draggable="true"><div class="project-card-tools"><div class="project-card-mark">H3 / '+p.slide_count+'</div>'+
      '<button class="project-delete" type="button" data-delete-project="'+esc(p.id)+'" title="Elimina progetto" aria-label="Elimina '+esc(p.title)+'">🗑</button></div>'+
      '<h2>'+esc(p.title)+'</h2><p>'+p.slide_count+' slide</p><small>Aggiornato '+esc(date)+'</small>'+
      '<button class="secondary" type="button" data-open-project="'+esc(p.id)+'">Apri progetto →</button></article>';
  };
  const groups=[...libraryState.folders,{id:'',name:'Senza cartella'}];
  $('library-grid').innerHTML=(projects.length||libraryState.folders.length)?groups.map(folder=>{
    const items=ordered.filter(project=>(libraryState.assignments[project.id]||'')===folder.id);
    return '<section class="project-folder" data-folder-id="'+esc(folder.id)+'"><div class="project-folder-head"><h2>'+esc(folder.name)+
      '</h2><span>'+items.length+'</span>'+(folder.id?'<button class="quiet" type="button" data-rename-folder="'+esc(folder.id)+'">Rinomina</button>'+
      '<button class="quiet danger" type="button" data-delete-folder="'+esc(folder.id)+'">Elimina cartella</button>':'')+'</div>'+
      '<div class="folder-projects">'+(items.length?items.map(card).join(''):'<div class="folder-empty">Trascina qui un progetto</div>')+'</div></section>';
  }).join(''):'<section class="library-empty"><div class="empty-mark">H3 /</div><h2>Nessun progetto salvato.</h2><p>Inizia da un argomento, un PDF o un’immagine.</p></section>';
}
function confirmProjectDeletion(project){
  if(localStorage.getItem('h3slides-skip-delete-confirmation')==='1')return Promise.resolve(true);
  const dialog=$('delete-project-dialog');
  $('delete-project-name').textContent='«'+project.title+'»';
  $('skip-delete-confirmation').checked=false;dialog.returnValue='cancel';dialog.showModal();
  return new Promise(resolve=>dialog.addEventListener('close',()=>{
    const accepted=dialog.returnValue==='delete';
    if(accepted&&$('skip-delete-confirmation').checked){
      localStorage.setItem('h3slides-skip-delete-confirmation','1');
      $('restore-delete-confirmation').hidden=false;
    }
    resolve(accepted);
  },{once:true}));
}
$('restore-delete-confirmation').onclick=()=>{
  localStorage.removeItem('h3slides-skip-delete-confirmation');
  $('restore-delete-confirmation').hidden=true;toast('Conferma di eliminazione riattivata');
};
async function selectProject(id){
  await finishInlineEdits();
  if(drafts.has('brief')&&!confirm('Ci sono modifiche al brief non salvate. Cambiare progetto?'))return;
  current=await api('/api/projects/'+id);drafts.clear();
  $('project-list').value=id;
  for(const key of ['title','prompt','count','theme'])$(key).value=current[key];
  const defaults={template:'auto',font:'Arial',text_density:'detailed',background_color:themes[current.theme].bg,accent_color:themes[current.theme].accent,use_source_images:true,use_web_images:false,use_openverse_images:false,use_manim_diagrams:false,pdf_scope:'auto',
    web_enabled:false,web_provider:'wikipedia',web_query:'',web_max_sources:3,source_priority:'documents',web_always_search:false};
  for(const [id,key] of Object.entries(designFields)){const value=current[key]??defaults[key];if($(id).type==='checkbox')$(id).checked=value;else $(id).value=value||defaults[key]}
  restoreWebConsent();$('web-refresh').checked=false;
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
  $('web-enabled').checked=false;$('web-query').value='';$('source-priority').value='documents';restoreWebConsent();$('web-refresh').checked=false;render();
  navigatePage('create');
}
$('new').onclick=$('library-new').onclick=newProject;
$('project-list').onchange=e=>e.target.value&&selectProject(e.target.value).then(()=>navigatePage('create')).catch(e=>toast(e.message));
$('library-folder-new').onclick=()=>{
  const name=prompt('Nome della nuova cartella:','Nuova cartella')?.trim();if(!name)return;
  libraryState.folders.push({id:crypto.randomUUID(),name:name.slice(0,60)});
  saveLibrary().catch(error=>toast(error.message));
};
$('library-grid').onclick=async e=>{
  const open=e.target.closest('[data-open-project]');
  if(open){selectProject(open.dataset.openProject).then(()=>navigatePage('create')).catch(error=>toast(error.message));return}
  const remove=e.target.closest('[data-delete-project]');
  if(remove){
    const project=projects.find(item=>item.id===remove.dataset.deleteProject);if(!project)return;
    if(!await confirmProjectDeletion(project))return;
    remove.disabled=true;
    try{
      await api('/api/projects/'+encodeURIComponent(project.id),'DELETE');
      if(current?.id===project.id){current=null;localStorage.removeItem('h3slides-project')}
      await Promise.all([loadProjects(),loadDocuments(),loadLibrary()]);
      toast('Progetto eliminato definitivamente');
    }catch(error){toast(error.message);if(remove.isConnected)remove.disabled=false}
    return;
  }
  const rename=e.target.closest('[data-rename-folder]');
  if(rename){
    const folder=libraryState.folders.find(item=>item.id===rename.dataset.renameFolder);if(!folder)return;
    const name=prompt('Nuovo nome della cartella:',folder.name)?.trim();if(!name)return;
    folder.name=name.slice(0,60);saveLibrary().catch(error=>toast(error.message));return;
  }
  const deleteFolder=e.target.closest('[data-delete-folder]');
  if(deleteFolder){
    const folder=libraryState.folders.find(item=>item.id===deleteFolder.dataset.deleteFolder);if(!folder)return;
    if(!confirm('Eliminare la cartella «'+folder.name+'»? I progetti contenuti torneranno in “Senza cartella”.'))return;
    libraryState.folders=libraryState.folders.filter(item=>item.id!==folder.id);
    for(const [pid,fid] of Object.entries(libraryState.assignments))if(fid===folder.id)delete libraryState.assignments[pid];
    saveLibrary().catch(error=>toast(error.message));
  }
};
$('library-grid').ondragstart=e=>{
  const card=e.target.closest('[data-project]');if(!card)return;
  libraryDragged=card.dataset.project;card.classList.add('dragging');
  e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',libraryDragged);
};
$('library-grid').ondragover=e=>{
  if(!libraryDragged)return;e.preventDefault();e.dataTransfer.dropEffect='move';
  document.querySelectorAll('.project-drop-target,.folder-drop-target').forEach(item=>item.classList.remove('project-drop-target','folder-drop-target'));
  const card=e.target.closest('[data-project]');
  if(card&&card.dataset.project!==libraryDragged)card.classList.add('project-drop-target');
  else e.target.closest('[data-folder-id]')?.classList.add('folder-drop-target');
};
$('library-grid').ondrop=e=>{
  if(!libraryDragged)return;e.preventDefault();
  const pid=libraryDragged,targetCard=e.target.closest('[data-project]'),folder=e.target.closest('[data-folder-id]');
  libraryDragged=null;document.querySelectorAll('.dragging,.project-drop-target,.folder-drop-target').forEach(item=>item.classList.remove('dragging','project-drop-target','folder-drop-target'));
  const folderId=folder?.dataset.folderId||'';
  if(folderId)libraryState.assignments[pid]=folderId;else delete libraryState.assignments[pid];
  const order=[...libraryState.order,...projects.map(project=>project.id)].filter((id,index,all)=>id!==pid&&all.indexOf(id)===index);
  const targetIndex=targetCard?order.indexOf(targetCard.dataset.project):-1;
  if(targetIndex>=0)order.splice(targetIndex,0,pid);else order.push(pid);
  libraryState.order=order;saveLibrary().catch(error=>toast(error.message));
};
$('library-grid').ondragend=()=>{
  libraryDragged=null;document.querySelectorAll('.dragging,.project-drop-target,.folder-drop-target').forEach(item=>item.classList.remove('dragging','project-drop-target','folder-drop-target'));
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
let floatingGenerationFrame=0;
function updateFloatingGeneration(){
  floatingGenerationFrame=0;
  const header=document.querySelector('.studio-sidebar');
  // On narrow screens the sticky navigation can cover an otherwise visible button.
  const visibleTop=getComputedStyle(header).position==='sticky'?Math.max(0,header.getBoundingClientRect().bottom):0;
  const inlineVisible=['generate-top','generate'].some(id=>{
    const rect=$(id).getBoundingClientRect();
    return rect.width>0&&rect.height>0&&rect.top>=visibleTop&&rect.bottom<=innerHeight&&
      rect.left>=0&&rect.right<=innerWidth;
  });
  const show=!$('create-page').hidden&&!inlineVisible;
  $('floating-generation').hidden=!show;
  document.body.classList.toggle('generation-floating-visible',show);
}
function scheduleFloatingGeneration(){
  if(!floatingGenerationFrame)floatingGenerationFrame=requestAnimationFrame(updateFloatingGeneration);
}
window.addEventListener('scroll',scheduleFloatingGeneration,{passive:true});
window.addEventListener('resize',scheduleFloatingGeneration);
const generationResizeObserver=new ResizeObserver(scheduleFloatingGeneration);
for(const element of [$('create-page'),$('generate-top'),$('generate'),document.querySelector('.studio-sidebar')]){
  generationResizeObserver.observe(element);
}
function updateGenerationButtons(){
  const active=jobs.some(item=>['queued','running','paused'].includes(item.status));
  const regenerate=Boolean(current?.slides.length);
  for(const button of document.querySelectorAll('[data-generate-presentation]')){
    button.disabled=busy||active;
    const label=active?'Generazione in corso…':busy?'Preparazione…':
      regenerate?'Rigenera presentazione ↻':'Genera presentazione →';
    button.textContent=button.id==='generate-floating'?
      (active?'In corso…':busy?'Preparazione…':regenerate?'Rigenera ↻':'Genera →'):label;
    button.setAttribute('aria-label',label);
    button.setAttribute('aria-busy',String(busy||active));
    button.title=label;
  }
  scheduleFloatingGeneration();
}
async function generate(slideId=null,diagramOnly=false,regenerateAll=false,replaceDiagrams=false,providedInstructions=null,rebuildOutline=false){
  if(busy)return;busy=true;updateGenerationButtons();
  try{
    await finishInlineEdits();
    if(regenerateAll&&current?.slides.length&&!confirm(rebuildOutline?
      'Rigenerare la presentazione con prompt e parametri attuali? La scaletta e le slide saranno ricreate; gli allegati resteranno nel progetto.':
      'Rigenerare tutte le slide? I contenuti attuali saranno sostituiti; scaletta e ordine restano invariati.'))return;
    if(replaceDiagrams&&!slideId&&!confirm('Riprogettare tutti i diagrammi con il modello? I testi delle slide restano invariati.'))return;
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
    if(!diagramOnly&&current.web_enabled&&!$('web-consent').checked)throw new Error('Autorizza la ricerca: userò la query indicata oppure la ricaverò automaticamente dalle istruzioni');
    savePrefs();
    const instructions=providedInstructions??(slideId?prompt(diagramOnly?'Descrivi cosa deve spiegare il diagramma Manim:':'Istruzioni per rigenerare questa slide:',
      diagramOnly?(current.slides.find(s=>s.id===slideId)?.content.diagram?.brief||current.slides.find(s=>s.id===slideId)?.content.title||''):current.prompt):$('prompt').value);
    if(instructions===null)return;
    job=await api('/api/projects/'+current.id+'/generate','POST',{provider:selected,prompt:instructions,count:Number($('count').value),slide_id:slideId,
      diagram_only:diagramOnly,replace_diagrams:replaceDiagrams,regenerate_all:regenerateAll,rebuild_outline:rebuildOutline,
      web_consent:diagramOnly?false:$('web-consent').checked,web_refresh:diagramOnly?false:$('web-refresh').checked});
    $('web-refresh').checked=false;
    toast('Generazione avviata');await poll();
  }catch(e){toast(e.message)}finally{busy=false;updateGenerationButtons()}
}
for(const button of document.querySelectorAll('[data-generate-presentation]'))button.onclick=()=>{
  const regenerate=Boolean(current?.slides.length);
  return generate(null,false,regenerate,false,null,regenerate);
};
$('generate-missing-diagrams').onclick=()=>generate(null,true);
$('redesign-diagrams').onclick=()=>generate(null,true,false,true);
const initialSearchAddress=$('searxng-url').value;
api('/api/admin/search').then(settings=>{
  searchSettingsEndpoint=settings.searxng_url;
  if($('searxng-url').value===initialSearchAddress)$('searxng-url').value=settings.searxng_url;
  restoreWebConsent();
}).catch(e=>{$('search-settings-status').textContent=e.message;restoreWebConsent()});
$('save-search-settings').onclick=async()=>{
  try{
    const submitted=$('searxng-url').value;
    const settings=await api('/api/admin/search','POST',{searxng_url:submitted});
    searchSettingsEndpoint=settings.searxng_url;
    if($('searxng-url').value===submitted)$('searxng-url').value=settings.searxng_url;
    restoreWebConsent();
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
const resize=new ResizeObserver(entries=>{for(const entry of entries){
  entry.target.style.setProperty('--slide-scale',entry.contentRect.width/1280);
  const card=entry.target.closest('.slide-card');positionVisualActions(card);positionFreeformHandles(card);
}});
function elementDeleteButton(kind,index,label){
  const button=document.createElement('button');
  button.type='button';button.className='element-delete';button.dataset.action='delete-element';
  button.dataset.deleteKind=kind;if(index!==undefined)button.dataset.deleteIndex=String(index);
  button.title='Elimina '+label;button.setAttribute('aria-label',button.title);button.textContent='🗑';
  return button;
}
function positionVisualActions(card){
  const frame=card?.querySelector('.slide-frame');if(!frame)return;
  const root=frame.getBoundingClientRect();
  for(const actions of frame.querySelectorAll('.visual-actions')){
    const visual=frame.querySelector('.visual[data-visual-kind="'+actions.dataset.visualKind+'"]');
    if(!visual)continue;
    const box=visual.getBoundingClientRect();
    actions.style.left=((box.right-root.left)/Math.max(1,root.width)*100)+'%';
    actions.style.top=((box.top-root.top)/Math.max(1,root.height)*100)+'%';
  }
}
function positionFreeformHandles(card){
  const frame=card?.querySelector('.slide-frame');if(!frame)return;
  for(const handle of frame.querySelectorAll('.free-resize-handle')){
    const element=frame.querySelector('[data-free-key="'+handle.dataset.freeResize+'"]');
    if(!element)continue;
    const x=Number(element.dataset.freeX),y=Number(element.dataset.freeY);
    const w=Number(element.dataset.freeW),h=Number(element.dataset.freeH);
    handle.style.left=(x+w-13)+'px';handle.style.top=(y+h-13)+'px';
  }
}
function installFreeformHandles(card,slide){
  if(slide.content.layout!=='freeform')return;
  const frame=card.querySelector('.slide-frame');
  for(const element of frame.querySelectorAll('[data-free-key]')){
    const handle=document.createElement('span');handle.className='free-resize-handle';
    handle.dataset.freeResize=element.dataset.freeKey;handle.title='Trascina per ridimensionare';
    handle.setAttribute('aria-hidden','true');frame.append(handle);
  }
  positionFreeformHandles(card);
}
function installElementControls(card,slide){
  const targets=[
    [card.querySelector('.heading h1'),'title',undefined,'titolo'],
    [card.querySelector('.subtitle'),'subtitle',undefined,'sottotitolo'],
    ...[...card.querySelectorAll('[data-block-index]')].map(item=>[item,'block',Number(item.dataset.blockIndex),'blocco di testo']),
    ...[...card.querySelectorAll('[data-bullet-index]')].map(item=>[item,'bullet',Number(item.dataset.bulletIndex),'punto']),
  ];
  for(const [target,kind,index,label] of targets){
    if(!target)continue;
    if(target.matches('h1,[data-bullet-index]'))
      target.setAttribute('aria-label',target.dataset.editRaw??target.textContent.trim());
    target.classList.add('deletable-element');target.append(elementDeleteButton(kind,index,label));
  }
  const frame=card.querySelector('.slide-frame');
  for(const visual of frame.querySelectorAll('.visual')){
  const actions=document.createElement('div');actions.className='visual-actions';
  actions.dataset.visualKind=visual.dataset.visualKind;
  if(visual.dataset.visualKind==='diagram'){
    const redesign=document.createElement('button');redesign.type='button';redesign.className='diagram-live-action';
    redesign.dataset.action='diagram-live';redesign.textContent='↻ Riprogetta Manim';actions.append(redesign);
  }else{
    const upload=document.createElement('button');upload.type='button';upload.className='diagram-live-action image-upload-action';
    upload.dataset.action='upload-image';upload.textContent='↑ '+(visual.classList.contains('image-placeholder')?'Carica immagine':'Sostituisci immagine');
    upload.title='Carica dal computer · JPG, PNG o WebP · massimo 20 MB';
    actions.append(upload);
  }
  actions.append(elementDeleteButton(visual.dataset.visualKind,undefined,visual.dataset.visualKind==='diagram'?'diagramma':'immagine'));
  frame.append(actions);requestAnimationFrame(()=>positionVisualActions(card));
  }
}
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
  $('openverse-images').disabled=!$('web-images').checked;
  $('source-priority-option').hidden=!current?.sources.length;
  $('wikipedia-hint').hidden=$('web-provider').value!=='wikipedia';
  const research=current?.web_research;
  const documentFallback=research?.status==='document_fallback',researchFailed=research?.status==='failed';
  const researchSkipped=research?.status==='skipped',coverageUncertain=research?.skipped_reason==='coverage_uncertain';
  const noWebSources=documentFallback||researchFailed||researchSkipped;
  $('source-mode').textContent=$('web-enabled').checked?(documentFallback?
    'Documenti allegati · nessuna integrazione web nell’ultima generazione. La ricerca verrà ritentata alla prossima generazione.':
    researchFailed?'Ultima ricerca non completata: nessuna fonte web usata. Senza allegati la generazione si è fermata.':
    researchSkipped?(coverageUncertain?'Ultima generazione: solo documenti allegati. Verifica non conclusiva, nessuna ricerca web eseguita.':
      'Ultima generazione: documenti sufficienti per il brief, ricerca web saltata.'):
    current?.sources.length?($('source-priority').value==='web'?
      'Priorità al web, scelta esplicita per questo progetto. I documenti allegati integrano le fonti trovate.':
      $('web-always-search').checked?'Prima i documenti allegati. La ricerca web viene eseguita sempre, come richiesto, senza cambiare priorità.':
      'Prima i documenti allegati. La ricerca web integra solo gli argomenti mancanti; se bastano i documenti, viene saltata.'):
    'Ricerca web attiva: uso gli estratti delle pagine lette. Verifica le fonti prima dell’uso.'):
    current?.sources.length?'Con documenti allegati: il modello usa le fonti fornite. Le immagini richiedono vision.':'Nessun allegato: genera dalla conoscenza del modello. Nessuna ricerca web; verifica fatti e date importanti.';
  const attemptedQueries=research&&!researchSkipped?(Array.isArray(research.attempted_queries)&&research.attempted_queries.length?
    research.attempted_queries:[research.query].filter(Boolean)):[];
  const missingTopics=!noWebSources&&research?.coverage?.status==='missing'&&Array.isArray(research.coverage.missing_topics)?
    research.coverage.missing_topics.filter(topic=>typeof topic==='string').slice(0,8):[];
  $('web-sources').innerHTML=research?'<details open data-research-status="'+(documentFallback?'document_fallback':researchFailed?'failed':researchSkipped?'skipped':'completed')+
    '"><summary>'+(documentFallback?'Documenti allegati · nessuna integrazione web':researchFailed?'Ultima ricerca non completata':
      researchSkipped?(coverageUncertain?'Ricerca web saltata · verifica non conclusiva':'Ricerca web saltata · documenti sufficienti'):'Ultima ricerca completata')+
    ' · '+esc(research.provider)+'</summary>'+
    (documentFallback?'<p class="hint" role="status"><strong>Solo documenti allegati, nessuna fonte web usata.</strong></p>':
      researchFailed?'<p class="hint" role="status"><strong>Nessuna fonte web usata. Senza allegati la generazione si è fermata.</strong></p>':
      researchSkipped?'<p class="hint" role="status">'+(coverageUncertain?
        'La verifica non ha confermato lacune specifiche. Uso solo i documenti allegati, senza affermare che coprano tutto il brief.':
        'I documenti coprono il brief: nessuna query inviata e nessuna fonte web usata.')+'</p>':'')+
    '<p class="hint">'+(!researchSkipped&&research.query_mode==='automatic'?'Query automatica · ':'')+esc(new Date(research.created_at*1000).toLocaleString())+
    (!researchSkipped&&research.cache_used?' · cache locale':'')+'</p>'+
    (missingTopics.length?'<p class="hint" data-web-missing-topics>Integrazione mirata · argomenti mancanti: '+esc(missingTopics.join('; '))+'.</p>':'')+
    (attemptedQueries.length?'<p class="hint">'+(attemptedQueries.length>1?'Query tentate:':'Query tentata:')+'</p><ol>'+
      attemptedQueries.map(query=>'<li class="hint">'+esc(query)+'</li>').join('')+'</ol>':'')+
    (noWebSources?[]:research.sources||[]).map(s=>'<p class="hint"><a href="'+esc(/^https?:\/\//.test(s.url)?s.url:'#')+
      '" target="_blank" rel="noopener noreferrer">'+esc(s.id+' · '+s.title)+'</a></p>').join('')+
    (research.warnings||[]).map(w=>'<p class="hint">'+esc(w)+'</p>').join('')+
    '<small>'+(researchSkipped?'Valutazione dell’ultima generazione: modificare il brief richiede Rigenera per valutarlo di nuovo.':
      documentFallback||researchFailed?'Esito dell’ultimo tentativo. Rigenera per riprovare la ricerca.':
      'Fonti lette in quella generazione: modificare la query non aggiorna le slide già pronte.')+'</small></details>':'';
  $('empty').hidden=Boolean(current?.slides.length);$('slide-count').textContent=(current?.slides.length||0)+' slide';
  const container=$('slides'),ids=new Set();
  for(const [index,slide] of (current?.slides||[]).entries()){
    ids.add(slide.id);let card=document.getElementById('slide-'+slide.id);
    if(!card){card=document.createElement('section');card.id='slide-'+slide.id;card.draggable=true;container.append(card)}
    const arranging=layoutEditors.has(slide.id);
    card.className='slide-card '+slide.status+(arranging?' layout-editing':'');card.dataset.id=slide.id;card.draggable=!arranging;
    const signature=JSON.stringify([slide,display.theme,design(),index,arranging]);
    if(card.dataset.signature!==signature&&!card.dataset.saving&&!card.querySelector('[contenteditable="plaintext-only"]')){
      card.dataset.signature=signature;
      const media=visualFor(display,slide.content,slide),assetURL=id=>id?'/api/assets/'+current.id+'/'+id:'';
      card.innerHTML='<div class="slide-top"><span class="slide-label">⠿ '+String(index+1).padStart(2,'0')+' / '+esc(slide.status==='ready'?'Pronta':slide.status==='generating'?'Generazione…':'In attesa')+'</span>'+
        '<button class="quiet" data-action="up" aria-label="Sposta su">↑</button><button class="quiet" data-action="down" aria-label="Sposta giù">↓</button>'+
        '<button class="quiet" data-action="edit">Modifica</button><button class="quiet" data-action="regenerate">Rigenera</button>'+
        (current.use_manim_diagrams&&!slide.diagram_render?.asset?'<button class="quiet diagram-action" data-action="'+
          (slide.content.diagram?.kind==='manim'&&slide.content.diagram?.scene&&!slide.diagram_render?.asset?'render':'diagram')+'">'+
          (slide.diagram_render?.engine==='manim'?'Riprogetta Manim':slide.content.diagram?.kind==='manim'&&slide.content.diagram?.scene?'Renderizza Manim':'Progetta Manim')+'</button>':'')+'</div>'+
        '<div class="composition-tools"><label>Composizione <select data-slide-layout '+(slide.status!=='ready'?'disabled':'')+'>'+layoutOptions(slide.content.layout)+'</select></label>'+
        '<button class="'+(arranging?'secondary':'quiet')+'" data-action="arrange" '+(slide.status!=='ready'?'disabled':'')+'>'+(arranging?'✓ Fine disposizione':'⠿ Disponi nella slide')+'</button>'+
        '<button class="quiet" data-action="add-text" '+(slide.status!=='ready'||(slide.content.blocks||[]).length>=4?'disabled':'')+'>＋ Testo</button>'+
        '<select data-live-image '+(slide.status!=='ready'||!projectImages().length?'disabled':'')+' aria-label="Aggiungi o cambia immagine"><option value="">＋ Immagine…</option>'+
          projectImages().map(image=>'<option value="'+esc(image.id)+'">'+esc(image.label)+'</option>').join('')+'</select>'+
        '<button class="quiet" data-action="upload-image" '+(slide.status!=='ready'?'disabled':'')+'>↑ Carica immagine</button>'+
        '<button class="quiet" data-action="add-diagram" '+(slide.status!=='ready'?'disabled':'')+'>＋ Diagramma</button>'+
        '<button class="quiet" data-action="recompose" '+(slide.status!=='ready'?'disabled':'')+'>↻ Ricomponi</button>'+
        '<button class="quiet" data-action="split" '+(slide.status!=='ready'?'disabled':'')+'>Dividi</button><span class="composition-status" aria-live="polite"></span>'+
        (arranging||slide.content.layout==='freeform'?'<span class="arrange-hint">'+
          (slide.content.layout==='freeform'?'Modalità libera: trascina titolo, box, immagini e diagrammi in qualsiasi punto. La griglia resta invisibile.':
          'Trascina titolo e contenuti; immagini e diagrammi sono sempre spostabili.')+'</span>':'')+'</div>'+
        '<div class="slide-preview" title="'+(arranging?'Trascina gli elementi nelle zone evidenziate':'Doppio clic su un testo per modificarlo')+'">'+slideHTML(display,slide,index,
          {diagram:assetURL(media.diagramAsset),image:assetURL(media.photo)})+
          '<div class="anchor-indicator" aria-live="polite"></div></div>'+
        (slide.content.diagram?.kind!=='none'&&!slide.diagram_render?.asset?
          '<p class="diagram-pending">'+(slide.content.diagram?.kind==='manim'&&slide.content.diagram?.scene?
            'La scena è valida ma il render va aggiornato. Usa Renderizza Manim.':'Il vecchio diagramma va riprogettato con Manim.')+'</p>':'');
      const select=card.querySelector('[data-slide-layout]');
      select.value=({split:'visual-right',statement:'focus'})[slide.content.layout]||slide.content.layout||'content';
      for(const item of card.querySelectorAll('.prose-box,li'))item.draggable=false;
      const freeform=slide.content.layout==='freeform';
      const headingElement=card.querySelector('.heading');if(headingElement)headingElement.draggable=slide.status==='ready'&&!freeform;
      for(const visualElement of card.querySelectorAll('.visual'))visualElement.draggable=slide.status==='ready'&&!freeform&&!card.querySelector('.has-multiple-visuals');
      if(slide.status==='ready'){installElementControls(card,slide);installFreeformHandles(card,slide)}
      resize.observe(card.querySelector('.slide-preview'));
      const fit=()=>{
        if(!card.isConnected)return;
        const result=fitSlide(card.querySelector('.slide-frame'));
        positionVisualActions(card);
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
  updateGenerationButtons();
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
  $('edit-image').innerHTML='<option value="">Nessuna immagine</option>'+projectImages().map(i=>'<option value="'+esc(i.id)+'">'+esc(i.label)+'</option>').join('');
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
  function_plot:'Grafico di funzione',
  venn:'Diagramma di Venn',gantt:'Diagramma di Gantt',timeline:'Timeline',
  tree:'Albero / gerarchia',network:'Rete / grafo'};
const tones={accent:'Accento',blue:'Blu',amber:'Ambra',red:'Rosso',violet:'Viola',neutral:'Neutro'};
function options(values,current){return Object.entries(values).map(([value,label])=>'<option value="'+value+'" '+(value===current?'selected':'')+'>'+label+'</option>').join('')}
function addSceneElement(value={}){
  const n=$('scene-elements').children.length;
  const defaults={id:'oggetto'+(n+1),type:'box',x:2+(n%3)*4,y:2.4+Math.floor(n/3)*2.6,width:3,height:1.3,text:'',caption:'',tone:'accent',stage:n+1,values:[],labels:[],columns:4,expression:'',x_min:-5,x_max:5,y_min:-5,y_max:5,asymptotes:[]};
  value={...defaults,...value};const row=document.createElement('fieldset');row.className='scene-item';
  row.innerHTML='<div class="row"><label>ID<input data-scene="id" maxlength="32" pattern="[A-Za-z][A-Za-z0-9_-]{0,31}" required></label>'+
    '<label>Oggetto<select data-scene="type">'+options(elementTypes,value.type)+'</select></label>'+
    '<label>Tono<select data-scene="tone">'+options(tones,value.tone)+'</select></label></div>'+
    '<label>Testo<input data-scene="text" maxlength="80"></label><label>Didascalia<input data-scene="caption" maxlength="90"></label>'+
    '<div class="scene-geometry">'+['x','y','width','height','stage','columns'].map(key=>'<label>'+key+
      '<input data-scene="'+key+'" type="number" step="'+(key==='stage'||key==='columns'?'1':'.1')+'" required></label>').join('')+'</div>'+
    '<div class="row"><label>Valori · separati da virgola<textarea data-scene="values" rows="2"></textarea></label>'+
    '<label>Etichette · una per riga<textarea data-scene="labels" rows="2"></textarea></label></div>'+
    '<div class="math-fields"><label>Funzione di x (es. 1/x, sin(x), x^2)<input data-scene="expression" maxlength="120"></label>'+
    '<div class="scene-geometry">'+['x_min','x_max','y_min','y_max'].map(key=>'<label>'+key+
      '<input data-scene="'+key+'" type="number" step=".1" required></label>').join('')+'</div>'+
    '<label>Asintoti verticali · separati da virgola<input data-scene="asymptotes"></label></div>'+
    '<button type="button" class="quiet danger" data-remove-scene>Rimuovi oggetto</button>';
  for(const [key,item] of Object.entries(value)){const input=row.querySelector('[data-scene="'+key+'"]');if(input)input.value=Array.isArray(item)?item.join(key==='labels'?'\n':', '):item}
  const syncMathFields=()=>{
    const enabled=row.querySelector('[data-scene="type"]').value==='function_plot';
    row.querySelector('.math-fields').hidden=!enabled;
    if(!enabled)return;
    row.querySelector('[data-scene="width"]').value=Math.max(5,Number(row.querySelector('[data-scene="width"]').value));
    row.querySelector('[data-scene="height"]').value=Math.max(3.5,Number(row.querySelector('[data-scene="height"]').value));
    if(!row.querySelector('[data-scene="expression"]').value)row.querySelector('[data-scene="expression"]').value='1/x';
  };
  row.querySelector('[data-scene="type"]').onchange=syncMathFields;syncMathFields();
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
    for(const key of ['x','y','width','height','stage','columns','x_min','x_max','y_min','y_max'])item[key]=Number(item[key]);
    item.values=item.values.split(/[\s,;]+/).filter(Boolean).map(Number);
    item.labels=item.labels.split('\n').map(value=>value.trim()).filter(Boolean);
    item.asymptotes=item.asymptotes.split(/[\s,;]+/).filter(Boolean).map(Number);
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
async function saveContentChange(id,mutate,message){
  await finishInlineEdits();
  const pid=current.id,slide=current.slides.find(item=>item.id===id),content=structuredClone(slide.content);
  mutate(content);
  const card=document.getElementById('slide-'+id);card.dataset.saving='1';
  try{
    const updated=await api('/api/projects/'+pid+'/slides/'+id,'PATCH',{revision:slide.revision,content});
    if(current?.id===pid)current.slides[current.slides.findIndex(item=>item.id===id)]=updated;
    toast(message);
  }finally{delete card.dataset.saving;delete card.dataset.signature;render()}
}
function addTextBlock(id){
  return saveContentChange(id,content=>{
    content.blocks=content.blocks||[];
    if(content.blocks.length>=4)throw new Error('Massimo 4 blocchi di testo per slide');
    content.blocks.push({heading:'Nuovo blocco',text:'Doppio clic per scrivere il contenuto.',kind:'explanation',source:''});
  },'Blocco di testo aggiunto: fai doppio clic per modificarlo.');
}
function deleteSlideElement(id,kind,index){
  const labels={title:'il titolo',subtitle:'il sottotitolo',block:'questo blocco di testo',
    bullet:'questo punto',visual:'questo elemento visivo',diagram:'questo diagramma',image:'questa immagine'};
  if(!confirm('Eliminare '+(labels[kind]||'questo elemento')+'?'))return Promise.resolve();
  return saveContentChange(id,content=>{
    if(kind==='title'){content.title='\u00a0';content.subtitle=''}
    else if(kind==='subtitle')content.subtitle='';
    else if(kind==='block'){
      content.blocks.splice(index,1);shiftFreeformSlots(content,'block-',index);
    }else if(kind==='bullet'){
      content.bullets.splice(index,1);shiftFreeformSlots(content,'bullet-',index);
    }
    else if(kind==='diagram'||kind==='image'||kind==='visual'){
      const deleteDiagram=kind==='diagram'||kind==='visual'&&content.diagram?.kind&&content.diagram.kind!=='none';
      if(deleteDiagram){
        content.diagram={kind:'none',labels:[],brief:'',scene:null};
        if(content.freeform){
          delete content.freeform.visual;
          if(content.freeform.image){content.freeform.visual=content.freeform.image;delete content.freeform.image}
        }
      }else{
        content.image_id='';content.image_placeholder=false;content.image_query='';
        if(content.freeform){
          delete content.freeform.image;
          if(content.diagram?.kind==='none'||!content.diagram?.kind)delete content.freeform.visual;
        }
      }
      return;
    }
    content.layout='content';content.layout_locked=false;content.layout_variant=0;
  },'Elemento eliminato e composizione ricalcolata.');
}
function shiftFreeformSlots(content,prefix,removed){
  if(!content.freeform)return;
  const updated={};
  for(const [key,value] of Object.entries(content.freeform)){
    if(!key.startsWith(prefix)){updated[key]=value;continue}
    const index=Number(key.slice(prefix.length));
    if(index<removed)updated[key]=value;
    else if(index>removed)updated[prefix+(index-1)]=value;
  }
  content.freeform=updated;
}
async function addImageBlock(id,imageId){
  if(!imageId)return;
  const origin=projectImages().find(image=>image.id===imageId)?.origin||'source';
  if(origin==='source'&&!$('source-images').checked){$('source-images').checked=true;drafts.add('brief');await saveProject()}
  return saveContentChange(id,content=>{
    const hadVisual=content.image_id||content.image_placeholder;
    content.image_id=imageId;content.image_origin=origin;content.image_placeholder=false;
    if(!hadVisual&&content.layout!=='freeform'&&!String(content.layout||'').startsWith('visual-'))content.layout='visual-right';
  },'Immagine aggiunta e impaginazione ricalcolata.');
}
async function chooseSlideImage(id){
  await finishInlineEdits();
  const slide=current?.slides.find(item=>item.id===id);
  if(!slide?.revision)throw new Error('Attendi che la slide sia pronta');
  imageUploadTarget={pid:current.id,sid:id,revision:slide.revision};
  $('slide-image-file').value='';$('slide-image-file').click();
}
$('slide-image-file').onchange=async()=>{
  const file=$('slide-image-file').files[0],target=imageUploadTarget;
  imageUploadTarget=null;if(!file||!target)return;
  const card=document.getElementById('slide-'+target.sid);
  try{
    if(file.size>20*1024*1024)throw new Error('Usa un’immagine fino a 20 MB');
    if(card)card.dataset.saving='1';
    const form=new FormData();form.append('revision',String(target.revision));form.append('file',file);
    const result=await api('/api/projects/'+target.pid+'/slides/'+target.sid+'/image','POST',form);
    if(current?.id===target.pid){
      current.slides[current.slides.findIndex(item=>item.id===target.sid)]=result.slide;
      current.visual_assets=[...(current.visual_assets||[]).filter(item=>item.id!==result.visual_asset.id),result.visual_asset];
    }
    toast('Immagine salvata nella slide, disponibile anche nelle esportazioni.');
  }catch(error){toast(error.message)}
  finally{if(card){delete card.dataset.saving;delete card.dataset.signature}render()}
};
async function addDiagramBlock(id){
  if(!$('manim-diagrams').checked){$('manim-diagrams').checked=true;drafts.add('brief');await saveProject()}
  return generate(id,true,false,true);
}
async function saveHeadingLayout(id,position,align){
  return saveContentChange(id,content=>{content.heading_position=position;content.heading_align=align},
    'Titolo riposizionato e slide riadattata.');
}
function redesignLiveDiagram(id){
  const slide=current.slides.find(item=>item.id===id),card=document.getElementById('slide-'+id);
  const frame=card?.querySelector('.slide-frame'),visual=frame?.querySelector('.visual[data-visual-kind="diagram"]');
  if(!slide||!frame||!visual){toast('Il diagramma non è ancora visibile nella slide');return}
  const base=slide.content.diagram?.brief||slide.content.title||'';
  const correction=prompt('Cosa deve correggere o rappresentare il nuovo diagramma Manim?',base);
  if(correction===null)return;
  const frameRect=frame.getBoundingClientRect(),visualRect=visual.getBoundingClientRect();
  const scale=frameRect.width/1280||1,width=Math.round(visualRect.width/scale),height=Math.round(visualRect.height/scale);
  const instructions=correction.trim()+
    '\nCORREZIONE NELLA COMPOSIZIONE CORRENTE: il diagramma occupa uno spazio di circa '+width+' × '+height+
    ' px, posizione '+(layouts[frame.dataset.layout]||frame.dataset.layout)+
    '. Progetta la scena Manim per essere leggibile in questo riquadro: gerarchia, etichette, proporzioni e densità devono adattarsi. '+
    'Usa il canvas sicuro 12 × 8 previsto dall’app; non modificare i testi della slide.';
  generate(id,true,false,true,instructions);
}
$('slides').onclick=e=>{
  const button=e.target.closest('button[data-action]');if(!button)return;
  const id=button.closest('.slide-card').dataset.id,index=current.slides.findIndex(s=>s.id===id);
  if(button.dataset.action==='edit')editSlide(id);
  if(button.dataset.action==='arrange'){
    if(layoutEditors.has(id))layoutEditors.delete(id);else layoutEditors.add(id);
    delete button.closest('.slide-card').dataset.signature;render();
  }
  if(button.dataset.action==='regenerate')generate(id);
  if(button.dataset.action==='add-text')addTextBlock(id).catch(error=>toast(error.message));
  if(button.dataset.action==='upload-image')chooseSlideImage(id).catch(error=>toast(error.message));
  if(button.dataset.action==='add-diagram')addDiagramBlock(id).catch(error=>toast(error.message));
  if(button.dataset.action==='diagram')generate(id,true);
  if(button.dataset.action==='diagram-live')redesignLiveDiagram(id);
  if(button.dataset.action==='delete-element')deleteSlideElement(id,button.dataset.deleteKind,
    Number(button.dataset.deleteIndex)).catch(error=>toast(error.message));
  if(button.dataset.action==='render')rerenderDiagram(id).catch(error=>toast(error.message));
  if(button.dataset.action==='recompose')changeLayout(id,'content',true).catch(e=>toast(e.message));
  if(button.dataset.action==='split')splitSlide(id).catch(e=>toast(e.message));
  if(button.dataset.action==='up')move(id,index-1).catch(e=>toast(e.message));
  if(button.dataset.action==='down')move(id,index+1).catch(e=>toast(e.message));
};
function measureFreeform(card){
  const frame=card?.querySelector('.slide-frame'),root=frame?.getBoundingClientRect();
  if(!frame||!root?.width)return {};
  const scale=root.width/1280,placements={};
  for(const element of frame.querySelectorAll('[data-free-key]')){
    const box=element.getBoundingClientRect();
    let x=Math.round((box.left-root.left)/scale),y=Math.round((box.top-root.top)/scale);
    let w=Math.max(80,Math.round(box.width/scale)),h=Math.max(44,Math.round(box.height/scale));
    w=Math.min(1280,w);h=Math.min(680,h);
    x=Math.max(0,Math.min(1280-w,x));y=Math.max(0,Math.min(680-h,y));
    placements[element.dataset.freeKey]={x,y,w,h};
  }
  return placements;
}
async function changeLayout(id,layout,recompose=false){
  await finishInlineEdits();
  const pid=current.id,slide=current.slides.find(s=>s.id===id),content=structuredClone(slide.content);
  const card=document.getElementById('slide-'+id);
  if(layout==='freeform'&&content.layout!=='freeform'){
    const frame=card.querySelector('.slide-frame');
    content.freeform=measureFreeform(card);
    content.freeform_base=frame.dataset.layout==='freeform'?'editorial':frame.dataset.layout;
    content.freeform_compact=frame.classList.contains('compact-spacing');
  }
  content.layout=layout;content.layout_locked=!recompose&&Object.hasOwn(layouts,layout);
  content.layout_variant=recompose?((content.layout_variant||0)+1)%10001:0;
  card.dataset.saving='1';
  try{
    const updated=await api('/api/projects/'+pid+'/slides/'+id,'PATCH',{revision:slide.revision,content});
    if(current?.id===pid)current.slides[current.slides.findIndex(s=>s.id===id)]=updated;
    toast('Composizione salvata. Nessun testo riscritto e nessuna chiamata al modello.');
  }finally{delete card.dataset.saving;delete card.dataset.signature;render()}
}
async function reorderSlideItems(id,field,from,to){
  await finishInlineEdits();
  const pid=current.id,slide=current.slides.find(s=>s.id===id),content=structuredClone(slide.content);
  const items=content[field];
  if(!Array.isArray(items)||from===to||from<0||to<0||from>=items.length||to>=items.length)return;
  const prefix=field==='blocks'?'block-':'bullet-';
  const placements=items.map((_,index)=>content.freeform?.[prefix+index]);
  const [item]=items.splice(from,1);items.splice(to,0,item);
  const [placement]=placements.splice(from,1);placements.splice(to,0,placement);
  if(content.freeform)for(let index=0;index<placements.length;index++){
    delete content.freeform[prefix+index];
    if(placements[index])content.freeform[prefix+index]=placements[index];
  }
  const card=document.getElementById('slide-'+id);card.dataset.saving='1';
  try{
    const updated=await api('/api/projects/'+pid+'/slides/'+id,'PATCH',{revision:slide.revision,content});
    if(current?.id===pid)current.slides[current.slides.findIndex(s=>s.id===id)]=updated;
    toast('Ordine dei testi salvato; impaginazione ricalcolata.');
  }finally{delete card.dataset.saving;delete card.dataset.signature;render()}
}
async function saveFreePlacement(id,key,placement,adaptive=null,placements=null){
  return saveContentChange(id,content=>{
    content.layout='freeform';content.layout_locked=true;
    content.freeform={...(content.freeform||{}),...(placements||adaptive?.placements||{}),[key]:placement};
    if(adaptive){content.freeform_base=adaptive.base;content.freeform_compact=adaptive.compact}
  },'Posizione libera salvata.');
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
  if(e.target.matches('[data-live-image]'))addImageBlock(e.target.closest('.slide-card').dataset.id,e.target.value).catch(error=>toast(error.message));
};
$('slides').ondblclick=e=>{
  if(e.target.closest('button'))return;
  const field=e.target.closest('[data-edit-field]');if(!field||field.isContentEditable)return;
  const card=field.closest('.slide-card'),slide=current.slides.find(s=>s.id===card.dataset.id);
  if(slide.status!=='ready'){toast('Attendi che questa scheda sia pronta');return}
  const original=field.dataset.editRaw??field.textContent,content=structuredClone(slide.content),revision=slide.revision,pid=current.id;
  field.textContent=original;
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
function finishItemDragPreview(drag,restore){
  if(!drag?.placeholder||!drag.source)return;
  const {placeholder,source,originalParent,originalNext,originalAriaHidden}=drag;
  source.classList.remove('drag-preview-source');
  if(originalAriaHidden===null)source.removeAttribute('aria-hidden');
  else source.setAttribute('aria-hidden',originalAriaHidden);
  if(restore){
    if(originalNext?.parentNode===originalParent)originalParent.insertBefore(source,originalNext);
    else originalParent?.append(source);
  }else if(placeholder.parentNode)placeholder.parentNode.insertBefore(source,placeholder);
  placeholder.remove();
  const card=document.getElementById('slide-'+drag.id);
  const frame=card?.querySelector('.slide-frame');
  if(frame)fitSlide(frame);
  positionVisualActions(card);
}
function applyFreePlacement(element,placement){
  for(const key of ['x','y','w','h']){
    element.dataset['free'+key.toUpperCase()]=String(placement[key]);
    element.style.setProperty('--free-'+key,placement[key]+'px');
  }
  positionFreeformHandles(element.closest('.slide-card'));
}
function beginFreePointerDrag(pointer){
  const {card,item}=pointer;
  const frame=card.querySelector('.slide-frame');
  let adaptive=null;
  if(frame.dataset.layout!=='freeform'){
    adaptive={placements:measureFreeform(card),base:frame.dataset.layout,compact:frame.classList.contains('compact-spacing'),
      candidates:frame.dataset.candidates,freeBase:frame.dataset.freeBase};
    for(const element of frame.querySelectorAll('[data-free-key]'))applyFreePlacement(element,adaptive.placements[element.dataset.freeKey]);
    frame.dataset.freeBase=adaptive.base;frame.dataset.candidates='["freeform"]';
    frame.dataset.freeCompact=String(adaptive.compact);fitSlide(frame);
  }
  const placement={
    x:Number(item.dataset.freeX),y:Number(item.dataset.freeY),
    w:Number(item.dataset.freeW),h:Number(item.dataset.freeH)
  };
  const root=frame.getBoundingClientRect(),box=item.getBoundingClientRect();
  const scale=root.width/1280||1;
  componentDrag={type:'freeform',id:card.dataset.id,key:item.dataset.freeKey,source:item,
    original:{...placement},placement:{...placement},adaptive,placements:measureFreeform(card)};
  pointer.offsetX=(pointer.startX-box.left)/scale;pointer.offsetY=(pointer.startY-box.top)/scale;
  card.classList.add('component-dragging');item.classList.add('dragging','free-item-dragging');
  const indicator=card.querySelector('.anchor-indicator');
  if(indicator)indicator.textContent=pointer.mode==='resize'?'Dimensioni libere · trascina l’angolo':
    'Posizione libera · trascina, rilascio per salvare';
}
function previewFreePosition(card,x,y){
  const drag=componentDrag,frame=card.querySelector('.slide-frame'),root=frame.getBoundingClientRect();
  if(drag?.type!=='freeform'||!root.width)return;
  const scale=root.width/1280,snap=8;
  let placement;
  if(itemPointer.mode==='resize'){
    const w=Math.max(80,Math.min(1280-drag.original.x,
      Math.round(((x-root.left)/scale-drag.original.x)/snap)*snap));
    const h=Math.max(44,Math.min(680-drag.original.y,
      Math.round(((y-root.top)/scale-drag.original.y)/snap)*snap));
    placement={...drag.original,w,h};
  }else{
    const {w,h}=drag.original;
    const rawX=(x-root.left)/scale-itemPointer.offsetX,rawY=(y-root.top)/scale-itemPointer.offsetY;
    placement={x:Math.max(0,Math.min(1280-w,Math.round(rawX/snap)*snap)),
      y:Math.max(0,Math.min(680-h,Math.round(rawY/snap)*snap)),w,h};
  }
  drag.placement=placement;applyFreePlacement(drag.source,placement);positionVisualActions(card);
  const indicator=card.querySelector('.anchor-indicator');
  if(indicator)indicator.textContent=itemPointer.mode==='resize'?
    placement.w+' × '+placement.h+' px · rilascio per salvare':
    'x '+placement.x+' · y '+placement.y+' · rilascio per salvare';
}
function beginItemPointerDrag(pointer){
  const {card,item,block}=pointer;
  const placeholder=item.cloneNode(true);
  placeholder.classList.remove('deletable-element','dragging');
  placeholder.classList.add('item-drag-placeholder');
  placeholder.removeAttribute('draggable');placeholder.removeAttribute('data-block-index');
  placeholder.removeAttribute('data-bullet-index');placeholder.setAttribute('aria-hidden','true');
  placeholder.querySelectorAll('button,[draggable]').forEach(element=>element.remove());
  const box=item.getBoundingClientRect(),frame=card.querySelector('.slide-frame');
  const scale=frame?.getBoundingClientRect().width/1280||1;
  placeholder.style.minHeight=Math.max(44,Math.round(box.height/scale))+'px';
  item.parentNode.insertBefore(placeholder,item);
  componentDrag={type:block?'blocks':'bullets',id:card.dataset.id,
    from:Number(block?item.dataset.blockIndex:item.dataset.bulletIndex),
    to:Number(block?item.dataset.blockIndex:item.dataset.bulletIndex),
    source:item,placeholder,originalParent:item.parentNode,originalNext:item.nextSibling,
    originalAriaHidden:item.getAttribute('aria-hidden')};
  card.classList.add('component-dragging');item.classList.add('dragging','drag-preview-source');
  item.setAttribute('aria-hidden','true');
  const indicator=card.querySelector('.anchor-indicator');
  if(indicator)indicator.textContent='Posizione '+(componentDrag.to+1)+' · sposta per vedere la nuova composizione';
}
function previewItemOrder(card,x,y){
  if(!componentDrag?.placeholder)return;
  const selector=componentDrag.type==='blocks'?'[data-block-index]':'[data-bullet-index]';
  const parent=componentDrag.placeholder.parentNode;
  const items=[...parent.querySelectorAll(selector)].filter(item=>item!==componentDrag.source);
  if(!items.length)return;
  let target=null,distance=Infinity;
  for(const item of items){
    const box=item.getBoundingClientRect();
    const dx=x-Math.max(box.left,Math.min(x,box.right));
    const dy=y-Math.max(box.top,Math.min(y,box.bottom));
    const next=dx*dx+dy*dy;
    if(next<distance){distance=next;target=item}
  }
  if(!target)return;
  document.querySelectorAll('.item-drop-target').forEach(element=>element.classList.remove('item-drop-target'));
  target.classList.add('item-drop-target');
  const box=target.getBoundingClientRect();
  const sameRow=Math.abs(y-(box.top+box.height/2))<box.height*.48;
  const after=sameRow?x>box.left+box.width/2:y>box.top+box.height/2;
  const targetIndex=items.indexOf(target),to=targetIndex+(after?1:0);
  parent.insertBefore(componentDrag.placeholder,items[to]||null);
  componentDrag.to=to;
  const frame=card.querySelector('.slide-frame');if(frame)fitSlide(frame);
  positionVisualActions(card);
  const indicator=card.querySelector('.anchor-indicator');
  if(indicator)indicator.textContent='Posizione '+(to+1)+' · anteprima live, rilascia per salvare';
}
function endItemPointer(){
  if(!itemPointer)return;
  const {item,pointerId,card,originalCardDraggable}=itemPointer;
  try{if(item.hasPointerCapture(pointerId))item.releasePointerCapture(pointerId)}catch{}
  card.draggable=originalCardDraggable;itemPointer=null;
}
function clearComponentDrag(restore=true){
  const drag=componentDrag;componentDrag=null;
  finishItemDragPreview(drag,restore);
  if(restore&&drag?.type==='freeform'&&drag.source)applyFreePlacement(drag.source,drag.original);
  if(restore&&drag?.adaptive){
    const frame=drag.source.closest('.slide-frame');
    frame.dataset.candidates=drag.adaptive.candidates;frame.dataset.freeBase=drag.adaptive.freeBase;fitSlide(frame);
  }
  document.querySelectorAll('.slide-frame[data-drag-candidates]').forEach(frame=>{
    if(restore){frame.dataset.candidates=frame.dataset.dragCandidates;fitSlide(frame)}
    delete frame.dataset.dragCandidates;
  });
  document.querySelectorAll('.component-dragging,.visual-dragging,.item-drop-target,.drag-preview-source,.free-item-dragging').forEach(element=>
    element.classList.remove('component-dragging','visual-dragging','item-drop-target','drag-preview-source','free-item-dragging'));
  document.querySelectorAll('.anchor-indicator').forEach(element=>element.textContent='');
  if(restore&&drag?.type==='heading'){
    const frame=document.getElementById('slide-'+drag.id)?.querySelector('.slide-frame');
    if(frame){
      for(const name of [...frame.classList])if(name.startsWith('heading-align-')||name==='heading-top'||name==='heading-bottom')frame.classList.remove(name);
      frame.classList.add('heading-'+drag.originalPosition,'heading-align-'+drag.originalAlign);fitSlide(frame);
    }
  }
}
function previewVisualLayout(card,layout){
  const frame=card.querySelector('.slide-frame');if(!frame)return;
  if(!frame.dataset.dragCandidates)frame.dataset.dragCandidates=frame.dataset.candidates;
  frame.dataset.candidates=JSON.stringify([layout]);fitSlide(frame);
  const indicator=card.querySelector('.anchor-indicator');
  if(indicator)indicator.textContent=layouts[layout]+' · rilascio per salvare';
  componentDrag.layout=layout;
}
function previewHeadingLayout(card,x,y){
  const frame=card.querySelector('.slide-frame'),rect=card.querySelector('.slide-preview').getBoundingClientRect();
  const position=y-rect.top>rect.height*.58?'bottom':'top';
  const ratio=(x-rect.left)/Math.max(1,rect.width),align=ratio<.34?'left':ratio>.66?'right':'center';
  for(const name of [...frame.classList])if(name.startsWith('heading-align-')||name==='heading-top'||name==='heading-bottom')frame.classList.remove(name);
  frame.classList.add('heading-'+position,'heading-align-'+align);fitSlide(frame);
  card.querySelector('.anchor-indicator').textContent='Titolo '+(position==='top'?'in alto':'in basso')+' · '+({left:'sinistra',center:'centro',right:'destra'})[align];
  componentDrag.position=position;componentDrag.align=align;
}
$('slides').ondragstart=e=>{
  if(e.target.closest('button,input,select,textarea')){e.preventDefault();return}
  const card=e.target.closest('.slide-card');
  const visual=e.target.closest('.visual');
  if(card&&visual){
    componentDrag={type:'visual',id:card.dataset.id,layout:card.querySelector('.slide-frame')?.dataset.layout};
    card.classList.add('component-dragging','visual-dragging');
    e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain','visual');return;
  }
  if(card){
    const heading=e.target.closest('.heading'),block=e.target.closest('[data-block-index]'),bullet=e.target.closest('[data-bullet-index]');
    if(heading){
      const slide=current.slides.find(item=>item.id===card.dataset.id);
      componentDrag={type:'heading',id:card.dataset.id,position:slide.content.heading_position||'top',
        align:slide.content.heading_align||'left',originalPosition:slide.content.heading_position||'top',
        originalAlign:slide.content.heading_align||'left'};
      card.classList.add('component-dragging');heading.classList.add('dragging');
      e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain','heading');return;
    }
    const item=block||bullet;
    if(item){
      e.preventDefault();return;
    }
  }
  if(card){dragged=card.dataset.id;card.classList.add('dragging')}
};
function commitComponentDrag(event,pointedOnly=false){
  if(!componentDrag)return false;
  const drag={...componentDrag};
  const pointed=document.elementFromPoint(event.clientX||0,event.clientY||0);
  const card=pointed?.closest('.slide-card')||(pointedOnly?null:event.target?.closest?.('.slide-card'));
  const validCard=card?.dataset.id===drag.id;
  clearComponentDrag(!validCard);
  if(!validCard)return true;
  if(drag.type==='freeform'){
    saveFreePlacement(drag.id,drag.key,drag.placement,drag.adaptive,drag.placements).catch(error=>toast(error.message));
  }else if(drag.type==='visual'){
    let layout=drag.layout;
    if(!layout){
      const rect=card.querySelector('.slide-preview').getBoundingClientRect();
      layout=visualAnchorAt(event.clientX-rect.left,event.clientY-rect.top,rect.width,rect.height);
    }
    changeLayout(drag.id,layout).catch(error=>toast(error.message));
  }else if(drag.type==='heading'){
    saveHeadingLayout(drag.id,drag.position,drag.align).catch(error=>toast(error.message));
  }else{
    const selector=drag.type==='blocks'?'[data-block-index]':'[data-bullet-index]';
    const target=pointed?.closest(selector)||event.target?.closest?.(selector);
    const key=drag.type==='blocks'?'blockIndex':'bulletIndex';
    const to=Number.isInteger(drag.to)?drag.to:Number(target?.dataset[key]);
    if(Number.isInteger(to))reorderSlideItems(drag.id,drag.type,drag.from,to).catch(error=>toast(error.message));
  }
  return true;
}
$('slides').ondragend=e=>{
  document.querySelectorAll('.dragging').forEach(c=>c.classList.remove('dragging'));
  dragged=null;
  if(!commitComponentDrag(e))clearComponentDrag();
};
$('slides').ondragover=e=>{
  if(componentDrag){
    const card=e.target.closest('.slide-card');if(!card||card.dataset.id!==componentDrag.id)return;
    e.preventDefault();e.dataTransfer.dropEffect='move';
    document.querySelectorAll('.item-drop-target').forEach(element=>element.classList.remove('item-drop-target'));
    if(componentDrag.type==='visual'){
      const rect=card.querySelector('.slide-preview').getBoundingClientRect();
      previewVisualLayout(card,visualAnchorAt(e.clientX-rect.left,e.clientY-rect.top,rect.width,rect.height));
    }else if(componentDrag.type==='heading'){
      previewHeadingLayout(card,e.clientX,e.clientY);
    }else{
      previewItemOrder(card,e.clientX,e.clientY);
    }
    return;
  }
  e.preventDefault();
};
$('slides').onpointerdown=e=>{
  if(e.button!==0||e.target.closest('button,input,select,textarea,[contenteditable]'))return;
  const resizeHandle=e.target.closest('[data-free-resize]');
  const candidate=resizeHandle||e.target.closest('[data-free-key],[data-block-index],[data-bullet-index]');
  const frame=candidate?.closest('.slide-frame');
  const adaptiveVisual=frame?.classList.contains('has-multiple-visuals')?e.target.closest('.visual'):null;
  const freeItem=frame?.dataset.layout==='freeform'?
    (resizeHandle?frame.querySelector('[data-free-key="'+resizeHandle.dataset.freeResize+'"]'):e.target.closest('[data-free-key]')):null;
  const item=freeItem||adaptiveVisual||e.target.closest('[data-block-index],[data-bullet-index]');
  const card=item?.closest('.slide-card');
  if(!item||!card||!card.classList.contains('ready'))return;
  const originalCardDraggable=card.draggable;card.draggable=false;
  itemPointer={item,card,mode:resizeHandle?'resize':freeItem||adaptiveVisual?'freeform':'order',block:item.hasAttribute('data-block-index'),pointerId:e.pointerId,
    startX:e.clientX,startY:e.clientY,active:false,originalCardDraggable};
};
$('slides').onpointermove=e=>{
  if(!itemPointer||e.pointerId!==itemPointer.pointerId)return;
  if(!itemPointer.active){
    if(Math.hypot(e.clientX-itemPointer.startX,e.clientY-itemPointer.startY)<7)return;
    itemPointer.active=true;
    try{itemPointer.item.setPointerCapture(e.pointerId)}catch{}
    if(itemPointer.mode==='freeform'||itemPointer.mode==='resize')beginFreePointerDrag(itemPointer);
    else beginItemPointerDrag(itemPointer);
  }
  e.preventDefault();
  if(componentDrag?.type==='freeform')previewFreePosition(itemPointer.card,e.clientX,e.clientY);
  else previewItemOrder(itemPointer.card,e.clientX,e.clientY);
};
$('slides').onpointerup=e=>{
  if(!itemPointer||e.pointerId!==itemPointer.pointerId)return;
  const active=itemPointer.active;
  if(active){e.preventDefault();commitComponentDrag(e,true)}
  endItemPointer();
};
$('slides').onpointercancel=e=>{
  if(!itemPointer||e.pointerId!==itemPointer.pointerId)return;
  if(itemPointer.active)clearComponentDrag();
  endItemPointer();
};
$('slides').ondrop=e=>{
  e.preventDefault();
  if(commitComponentDrag(e))return;
  const card=e.target.closest('.slide-card');
  if(card&&dragged)move(dragged,current.slides.findIndex(s=>s.id===card.dataset.id)).catch(error=>toast(error.message));
  dragged=null;
};
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
    updateGenerationButtons();
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
  try{await Promise.all([loadProjects(),loadLibrary(),loadDocuments(),models()]);const id=new URLSearchParams(location.search).get('project')||localStorage.getItem('h3slides-project');
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
  updateFloatingGeneration();
  $('open-admin').setAttribute('aria-current',admin?'page':'false');
  $('open-library').setAttribute('aria-current',library?'page':'false');
  $('open-create').setAttribute('aria-current',!admin&&!library?'page':'false');
  document.title=admin?'Admin · H3-slides':library?'Progetti · H3-slides':'H3-slides · Studio';
  const path=admin?'/admin':library?'/library':'/';
  if(push&&location.pathname!==path)history.pushState({},'',path+location.search);
  if(admin)loadAdmin();else if(library){Promise.all([loadProjects(),loadLibrary()]).catch(error=>toast(error.message))}else{render();requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))}
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
