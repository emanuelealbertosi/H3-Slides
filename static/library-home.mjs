// Home uses the existing project/folder API and delegated project actions.
export function createLibraryHome({root,sidebar,esc,onNew,onImport,onMove}){
  const $=id=>document.getElementById(id),grid=$('library-grid');
  let data={projects:[],libraryState:{folders:[],order:[],assignments:{}},jobs:[]};
  let folder=null,filter='all',query='',layout=localStorage.getItem('h3slides-home-layout')==='list'?'list':'grid';
  $('library-title').textContent='Le tue creazioni';
  root.querySelector('.eyebrow').textContent='IL TUO SPAZIO DI LAVORO';
  root.querySelector('.page-head p').textContent='Tutte le tue idee, ordinate. Apri una presentazione o inizia qualcosa di nuovo.';
  $('library-new').textContent='＋ Crea con l’AI';
  const importButton=document.createElement('button');importButton.type='button';importButton.id='library-import';importButton.className='secondary compact';importButton.textContent='↥ Importa';importButton.onclick=onImport;
  $('library-new').after(importButton);
  const controls=document.createElement('div');controls.id='library-controls';
  controls.innerHTML='<div class="home-search"><span aria-hidden="true">⌕</span><input id="home-search" type="search" placeholder="Cerca una presentazione…" aria-label="Cerca una presentazione"></div><div class="home-filter-tabs" role="group" aria-label="Filtra creazioni"><button type="button" data-home-filter="all">Tutte</button><button type="button" data-home-filter="recent">Recenti</button><button type="button" data-home-filter="recovery">Da recuperare</button></div><div class="home-layout-toggle" role="group" aria-label="Vista dei progetti"><button type="button" data-home-layout="grid">▦ Griglia</button><button type="button" data-home-layout="list">☰ Elenco</button></div>';
  grid.before(controls);
  const notice=document.createElement('p');notice.id='home-notice';notice.hidden=true;notice.setAttribute('role','alert');controls.after(notice);
  const folders=document.createElement('section');folders.id='home-folders';folders.innerHTML='<div class="home-folders-label"><span>CARTELLE</span><button type="button" id="home-folder-add" aria-label="Nuova cartella">＋</button></div><div id="home-folder-links"></div><p>Trascina qui una creazione per spostarla.</p>';
  sidebar.append(folders);$('home-folder-add').onclick=()=>$('library-folder-new').click();
  $('home-search').oninput=e=>{query=e.target.value;render()};
  controls.onclick=e=>{const tab=e.target.closest('[data-home-filter]'),view=e.target.closest('[data-home-layout]');if(tab){filter=tab.dataset.homeFilter;render()}if(view){layout=view.dataset.homeLayout;localStorage.setItem('h3slides-home-layout',layout);render()}};
  function selectFolder(id){folder=id==='all'?null:id;render()}
  folders.onclick=e=>{const b=e.target.closest('[data-home-folder]');if(b)selectFolder(b.dataset.homeFolder)};
  grid.addEventListener('click',e=>{const b=e.target.closest('[data-home-folder]');if(b)selectFolder(b.dataset.homeFolder);if(e.target.closest('[data-home-create]'))onNew?.()});
  folders.ondragover=e=>{if(!e.target.closest('[data-folder-id]'))return;e.preventDefault();e.dataTransfer.dropEffect='move';};
  folders.ondrop=async e=>{const target=e.target.closest('[data-folder-id]'),pid=e.dataTransfer.getData('text/plain');if(!target||!data.projects.some(p=>p.id===pid))return;e.preventDefault();try{await onMove(pid,target.dataset.folderId);notice.hidden=true}catch(error){notice.textContent=error.message;notice.hidden=false}};
  const date=value=>{const d=new Date(typeof value==='number'&&value<1e12?value*1000:value);return Number.isNaN(d.getTime())?'':d.toLocaleDateString('it-IT',{day:'numeric',month:'short',year:'numeric'})};
  const time=value=>typeof value==='number'&&value<1e12?value*1000:new Date(value).getTime()||0;
  const recoverable=status=>['failed','interrupted','cancelled'].includes(status);
  function render(){
    const {projects,libraryState:state,jobs}=data,byId=new Map(projects.map(p=>[p.id,p]));
    if(folder&&!state.folders.some(f=>f.id===folder))folder=null;
    let ordered=[...(state.order||[]),...projects.map(p=>p.id)].filter((id,i,all)=>byId.has(id)&&all.indexOf(id)===i).map(id=>byId.get(id));
    const latest=id=>jobs.find(j=>j.project_id===id),count=id=>projects.filter(p=>(state.assignments[p.id]||'')===id).length;
    if(filter==='recent')ordered.sort((a,b)=>time(b.updated_at)-time(a.updated_at));
    if(filter==='recovery')ordered=ordered.filter(p=>recoverable(latest(p.id)?.status));
    if(folder!==null)ordered=ordered.filter(p=>(state.assignments[p.id]||'')===folder);
    if(query.trim())ordered=ordered.filter(p=>p.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
    root.dataset.homeLayout=layout;
    for(const b of controls.querySelectorAll('[data-home-filter]'))b.setAttribute('aria-pressed',String(b.dataset.homeFilter===filter));
    for(const b of controls.querySelectorAll('[data-home-layout]'))b.setAttribute('aria-pressed',String(b.dataset.homeLayout===layout));
    const sideLink=(id,name,total)=>'<button type="button" data-home-folder="'+esc(id)+'" '+(id!=='all'?'data-folder-id="'+esc(id)+'"':'')+' aria-current="'+((id==='all'&&folder===null||folder===id)?'page':'false')+'"><span aria-hidden="true">'+(id==='all'?'▦':'▱')+'</span><strong>'+esc(name)+'</strong><small>'+total+'</small></button>';
    $('home-folder-links').innerHTML=sideLink('all','Tutte le creazioni',projects.length)+state.folders.map(f=>sideLink(f.id,f.name,count(f.id))).join('')+sideLink('','Senza cartella',count(''));
    const selected=state.folders.find(f=>f.id===folder);
    const folderHeader=selected?'<div class="home-folder-heading"><button type="button" class="quiet" data-home-folder="all">← Tutte</button><h2>'+esc(selected.name)+'</h2><button type="button" class="quiet" data-rename-folder="'+esc(selected.id)+'">Rinomina</button><button type="button" class="quiet danger" data-delete-folder="'+esc(selected.id)+'">Elimina cartella</button></div>':'';
    const strip=folder===null&&!query&&state.folders.length?'<section class="home-folder-strip" aria-label="Cartelle">'+state.folders.map(f=>'<button type="button" data-home-folder="'+esc(f.id)+'" data-folder-id="'+esc(f.id)+'"><span aria-hidden="true">▱</span><strong>'+esc(f.name)+'</strong><small>'+count(f.id)+' creazioni</small></button>').join('')+'</section>':'';
    const card=(p,index)=>{
      const job=latest(p.id),recover=recoverable(job?.status),active=['queued','running','paused'].includes(job?.status);
      const status=recover?({failed:'Fallito',interrupted:'Interrotto',cancelled:'Annullato'})[job.status]:active?'In corso · '+Math.round((job.progress||0)*100)+'%':p.slide_count?'Presentazione':'Brief salvato';
      const assigned=state.folders.find(f=>f.id===state.assignments[p.id]);
      return '<article class="project-card" data-project="'+esc(p.id)+'" data-folder-id="'+esc(state.assignments[p.id]||'')+'" draggable="true"><div class="home-cover home-cover-'+index%5+'" aria-hidden="true"><span>H3 / STUDIO</span><strong>'+esc(p.title)+'</strong><i></i><b></b></div><div class="home-card-body"><div class="home-card-status '+(recover?'needs-recovery':active?'is-active':'')+'">'+esc(status)+'</div><h2>'+esc(p.title)+'</h2><p>'+Number(p.slide_count||0)+' slide'+(assigned?' · '+esc(assigned.name):'')+'</p><small>Aggiornato '+esc(date(p.updated_at))+'</small><div class="home-card-actions"><button class="quiet" type="button" data-open-project="'+esc(p.id)+'">'+(recover?'Recupera progetto':active?'Apri generazione':'Apri progetto')+' →</button><button class="project-delete" type="button" data-delete-project="'+esc(p.id)+'" title="Elimina progetto" aria-label="Elimina '+esc(p.title)+'">⌫</button></div></div></article>';
    };
    grid.innerHTML=folderHeader+strip+'<div class="home-results-heading"><h2>'+esc(selected?.name||(folder===''?'Senza cartella':filter==='recovery'?'Da recuperare':filter==='recent'?'Aggiornate di recente':'Tutte le creazioni'))+'</h2><span>'+ordered.length+' '+(ordered.length===1?'progetto':'progetti')+'</span></div><section class="home-projects" data-folder-id="'+esc(folder||'')+'">'+(ordered.length?ordered.map(card).join(''):'<div class="home-empty"><span>✦</span><h2>'+(!projects.length?'Il prossimo progetto comincia qui.':'Nessuna creazione in questa vista.')+'</h2><p>'+(!projects.length?'Un’idea, un documento o qualche appunto: scegli da dove iniziare.':'Cambia ricerca o cartella. Puoi trascinare qui i tuoi progetti.')+'</p><button type="button" class="primary compact" data-home-create>＋ Crea una presentazione</button></div>')+'</section>';
  }
  return {update(value){data=value;render()}};
}
