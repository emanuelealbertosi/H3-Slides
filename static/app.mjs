import {esc,slideHTML,slideCSS} from './deck.mjs';
const $=id=>document.getElementById(id);
const style=document.createElement('style');style.textContent=slideCSS;document.head.append(style);
let current=null,projects=[],jobs=[],editing=null,job=null,busy=false,dragged=null;
let polling=false;
const exporting=new Set();
const drafts=new Set();
const pref=JSON.parse(localStorage.getItem('h3slides-settings')||'{}');
for(const id of ['provider','model','api-url','api-model','vision']) {
  if(pref[id]!==undefined&&id!=='model') { if(id==='vision')$(id).checked=pref[id];else $(id).value=pref[id]; }
}
function savePrefs(){
  const values={};for(const id of ['provider','model','api-url','api-model','vision'])values[id]=id==='vision'?$(id).checked:$(id).value;
  localStorage.setItem('h3slides-settings',JSON.stringify(values));
}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,7000)}
async function api(url,method='GET',data){
  const options={method,headers:{'X-H3-Slides':'1'}};
  if(data instanceof FormData)options.body=data;
  else if(data!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(data)}
  const response=await fetch(url,options);const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Errore HTTP '+response.status);
  return result;
}
const brief=()=>({title:$('title').value,prompt:$('prompt').value,count:Number($('count').value),theme:$('theme').value});
const provider=()=>({mode:$('provider').value,model:$('provider').value==='local'?$('model').value:$('api-model').value,
  base_url:$('api-url').value,api_key:$('api-key').value,remote_consent:$('consent').checked,vision:$('vision').checked});
function fields(){const remote=$('provider').value==='remote';$('remote-fields').hidden=!remote;$('local-fields').hidden=remote;savePrefs()}
$('provider').addEventListener('change',fields);fields();
for(const id of ['model','api-url','api-model','vision'])$(id).addEventListener('change',savePrefs);
for(const id of ['title','prompt','count','theme'])$(id).addEventListener('input',()=>{drafts.add('brief');$('save-status').textContent='Brief non salvato'});
async function loadProjects(){
  projects=await api('/api/projects');$('project-list').innerHTML='<option value="">I tuoi progetti</option>'+projects.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.title)+' · '+p.slide_count+'</option>').join('');
  if(current)$('project-list').value=current.id;
}
async function selectProject(id){
  if(drafts.has('brief')&&!confirm('Ci sono modifiche al brief non salvate. Cambiare progetto?'))return;
  current=await api('/api/projects/'+id);drafts.clear();
  for(const key of ['title','prompt','count','theme'])$(key).value=current[key];
  localStorage.setItem('h3slides-project',id);$('save-status').textContent='Salvato sul PC';render();
}
async function saveProject(){
  if(!current) current=await api('/api/projects','POST',brief());
  else current=await api('/api/projects/'+current.id,'PATCH',brief());
  drafts.delete('brief');$('save-status').textContent='Salvato sul PC';
  localStorage.setItem('h3slides-project',current.id);await loadProjects();render();return current;
}
$('save-project').onclick=()=>saveProject().catch(e=>toast(e.message));
$('new').onclick=async()=>{
  if(drafts.size&&!confirm('Lasciare le modifiche non salvate?'))return;
  current=null;drafts.clear();$('title').value='Nuova presentazione';$('prompt').value='';$('project-list').value='';render();
};
$('project-list').onchange=e=>e.target.value&&selectProject(e.target.value).catch(e=>toast(e.message));
$('files').onchange=async e=>{
  const files=[...e.target.files];e.target.value='';if(!files.length)return;
  try{await saveProject();for(const file of files){const form=new FormData();form.append('file',file);toast('Lettura di '+file.name+'…');current=await api('/api/projects/'+current.id+'/sources','POST',form)}render();toast('Fonti aggiunte')}catch(error){toast(error.message)}
};
async function models(){
  const data=await api('/api/models'),previous=$('model').value||pref.model;
  $('model').innerHTML='<option value="">Scegli il modello locale</option>'+data.models.map(m=>
    '<option value="'+esc(m.id)+'">'+esc(m.name)+' · '+m.size_gb+' GB'+(m.vision?' · vision':'')+'</option>').join('');
  if(data.models.some(m=>m.id===previous))$('model').value=previous;
  else { const candidate=data.models.find(m=>m.vision&&m.name.startsWith('gemma'));if(candidate)$('model').value=candidate.id; }
  $('llama-status').textContent=data.status.running?'llama.cpp caricato · porta '+data.status.port:'Avvio integrato alla generazione · scarico dopo 5 minuti inattivi';
}
$('refresh-models').onclick=()=>models().catch(e=>toast(e.message));
$('unload').onclick=async()=>{try{await api('/api/llm/stop','POST',{});await models();toast('Modello di H3-slides scaricato')}catch(e){toast(e.message)}};
async function generate(slideId=null){
  if(busy)return;busy=true;$('generate').disabled=true;
  try{
    if(!current||drafts.has('brief'))await saveProject();
    const selected=provider();
    if(!selected.model)throw new Error('Seleziona un modello');
    if(selected.mode==='remote'&&!selected.remote_consent)throw new Error('Conferma l’invio dei documenti al provider remoto');
    savePrefs();
    const instructions=slideId?prompt('Istruzioni per rigenerare questa slide:',current.prompt):$('prompt').value;
    if(instructions===null)return;
    job=await api('/api/projects/'+current.id+'/generate','POST',{provider:selected,prompt:instructions,count:Number($('count').value),slide_id:slideId});
    toast('Generazione avviata');await poll();
  }catch(e){toast(e.message)}finally{busy=false;$('generate').disabled=false}
}
$('generate').onclick=()=>generate();
$('open-slidev').onclick=async()=>{
  if(!current){toast('Crea prima un progetto');return}
  const tab=window.open('about:blank','_blank');
  try{const result=await api('/api/projects/'+current.id+'/slidev','POST',{});
    if(tab)tab.location.href=result.url;else toast('Slidev pronto: '+result.url);
  }catch(error){if(tab)tab.close();toast(error.message)}
};
function sourceHTML(s){
  return '<div class="source"><strong>'+esc(s.name)+'</strong><br>'+s.images.slice(0,8).map(i=>'<img src="/api/assets/'+current.id+'/'+i.id+'" alt="'+esc(i.label)+'" title="'+esc(i.label)+'">').join('')+
    (s.images.length>8?'<small>+'+(s.images.length-8)+' pagine</small>':'')+
    (s.warnings.length?'<div class="warning">'+esc(s.warnings[0])+'</div>':'')+'</div>';
}
const resize=new ResizeObserver(entries=>{for(const entry of entries)entry.target.style.setProperty('--slide-scale',entry.contentRect.width/1280)});
function render(){
  $('deck-title').textContent=current?.title||'Spazio alle idee.';
  $('sources').innerHTML=current?current.sources.map(sourceHTML).join(''):'';
  $('empty').hidden=Boolean(current?.slides.length);$('slide-count').textContent=(current?.slides.length||0)+' slide';
  const container=$('slides'),ids=new Set();
  for(const [index,slide] of (current?.slides||[]).entries()){
    ids.add(slide.id);let card=document.getElementById('slide-'+slide.id);
    if(!card){card=document.createElement('section');card.id='slide-'+slide.id;card.draggable=true;container.append(card)}
    card.className='slide-card '+slide.status;card.dataset.id=slide.id;
    const signature=JSON.stringify([slide,current.theme,index]);
    if(card.dataset.signature!==signature){
      card.dataset.signature=signature;
      card.innerHTML='<div class="slide-top"><span class="slide-label">⠿ '+String(index+1).padStart(2,'0')+' / '+esc(slide.status==='ready'?'Pronta':slide.status==='generating'?'Generazione…':'In attesa')+'</span>'+
        '<button class="quiet" data-action="up" aria-label="Sposta su">↑</button><button class="quiet" data-action="down" aria-label="Sposta giù">↓</button>'+
        '<button class="quiet" data-action="edit">Modifica</button><button class="quiet" data-action="regenerate">Rigenera</button></div>'+
        '<div class="slide-preview">'+slideHTML(current,slide,index,slide.content.image_id?'/api/assets/'+current.id+'/'+slide.content.image_id:'')+'</div>';
      resize.observe(card.querySelector('.slide-preview'));
    }
    container.append(card);
  }
  for(const card of [...container.children])if(!ids.has(card.dataset.id))card.remove();
  document.querySelectorAll('[data-export]').forEach(b=>b.disabled=!current?.slides.length||exporting.has(b.dataset.export));
}
function editSlide(id){
  const slide=current.slides.find(s=>s.id===id);editing=structuredClone(slide);
  for(const field of ['title','subtitle','layout','animation','notes'])$('edit-'+field).value=slide.content[field];
  $('edit-bullets').value=slide.content.bullets.join('\n');$('edit-sources').value=slide.content.sources.join('\n');
  $('edit-image').innerHTML='<option value="">Nessuna immagine</option>'+current.sources.flatMap(s=>s.images).map(i=>'<option value="'+i.id+'">'+esc(i.label)+'</option>').join('');
  $('edit-image').value=slide.content.image_id;$('edit-error').textContent='';$('editor').showModal();
}
$('close-editor').onclick=()=>$('editor').close();
$('edit-form').onsubmit=async e=>{
  e.preventDefault();
  const content={...editing.content};
  for(const field of ['title','subtitle','layout','animation','notes'])content[field]=$('edit-'+field).value;
  content.bullets=$('edit-bullets').value.split('\n').map(s=>s.trim()).filter(Boolean);
  content.sources=$('edit-sources').value.split('\n').map(s=>s.trim()).filter(Boolean);content.image_id=$('edit-image').value;
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
  if(button.dataset.action==='up')move(id,index-1).catch(e=>toast(e.message));
  if(button.dataset.action==='down')move(id,index+1).catch(e=>toast(e.message));
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
  try{const result=await api('/api/projects/'+current.id+'/export/'+button.dataset.export,'POST',{});
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
  try{await Promise.all([loadProjects(),models()]);const id=localStorage.getItem('h3slides-project');
    if(projects.some(p=>p.id===id))await selectProject(id);await poll();
  }catch(error){toast(error.message)}
  setInterval(poll,1500);
}
init();
