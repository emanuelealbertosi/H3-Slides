// Screen structure only: project state and mutations stay in app.mjs.
export function installCreationFlow(){
  const $=id=>document.getElementById(id),settings=document.querySelector('.settings');
  const start=document.createElement('main');start.id='creation-start';start.hidden=true;start.className='flow-screen';
  start.innerHTML=`<div class="flow-heading"><span class="flow-kicker">DALLE IDEE ALLE SLIDE</span><h1>Da dove vuoi partire?</h1><p>Scegli il punto di partenza. Al resto diamo forma insieme.</p></div>
    <div class="start-cards">
    <button type="button" class="start-card" data-start-method="prompt"><span class="start-art art-idea" aria-hidden="true">✦<i></i></span><strong>Da un’idea</strong><span>Scrivi un argomento o un prompt. Il modello costruisce la presentazione.</span><b>Inizia a scrivere →</b></button>
    <button type="button" class="start-card" data-start-method="paste"><span class="start-art art-text" aria-hidden="true">Aa<i></i></span><strong>Incolla un testo</strong><span>Trasforma appunti, una scaletta o un testo già pronto in slide.</span><b>Incolla il contenuto →</b></button>
    <button type="button" class="start-card" data-start-method="import"><span class="start-art art-import" aria-hidden="true">↥<i></i></span><strong>Importa file o link</strong><span>Parti da PDF, immagini, documenti di testo o una pagina web pubblica.</span><b>Scegli le fonti →</b></button>
    <button type="button" class="start-card" data-start-method="theme"><span class="start-art art-theme" aria-hidden="true">▤<i></i></span><strong>Parti da un tema</strong><span>Scegli una combinazione visiva e personalizza contenuti e impostazioni.</span><b>Esplora i temi →</b></button></div><div id="start-recovery"></div>`;
  document.querySelector('#create-page').before(start);
  const imports=document.createElement('main');imports.id='import-page';imports.hidden=true;imports.className='flow-screen';
  imports.innerHTML=`<button type="button" class="quiet flow-back" data-flow-back>← Indietro</button><div class="flow-heading"><span class="flow-kicker">01 / LE TUE FONTI</span><h1>Porta i tuoi contenuti</h1><p>Carica, collega o riusa. I documenti restano disponibili nei tuoi progetti.</p></div>
  <div class="import-tabs" role="group" aria-label="Tipo di importazione"><button type="button" data-import-mode="file" aria-pressed="true">↥ File</button><button type="button" data-import-mode="url" aria-pressed="false">↗ Link web</button><button type="button" data-import-mode="paste" aria-pressed="false">Aa Incolla testo</button></div>
  <section id="import-file-panel" class="import-panel"><div id="import-upload-slot"></div></section>
  <form id="import-url-panel" class="import-panel" hidden><label>Link a una pagina pubblica<input id="import-url" type="url" required placeholder="https://…" maxlength="2000"></label><p>Importa il testo di una pagina web, senza account. Per i PDF usa File. Le immagini della pagina non vengono importate.</p><button type="submit" id="import-url-submit" class="primary">Importa il link →</button></form>
  <section id="import-paste-panel" class="import-panel" hidden><label>Nome del contenuto<input id="paste-name" maxlength="120" value="Appunti"></label><label>Il tuo testo<textarea id="paste-content" rows="12" maxlength="240000" placeholder="Incolla qui appunti, contenuti o codice. Le istruzioni per il modello si scrivono nel passaggio successivo."></textarea></label><button type="button" id="import-paste-submit" class="primary">Aggiungi il testo →</button></section>
  <section id="import-progress" class="import-panel" role="status" aria-live="polite" hidden><strong id="import-progress-label"></strong><progress id="import-progress-bar" max="100"></progress><p id="import-progress-detail"></p></section>
  <p id="import-error" class="flow-error" role="alert" hidden></p><div id="import-selected-slot"></div>
  <div class="import-next"><span id="import-summary">Scegli un file, un link o un documento dallo storico.</span><button type="button" id="import-continue" class="primary" disabled>Continua al briefing →</button></div>
  <section id="import-history-slot" class="import-history"></section>`;
  start.after(imports);
  const original=[...settings.children],guide=document.createElement('section'),content=document.createElement('section'),design=document.createElement('section');
  guide.id='brief-guide';guide.className='brief-column brief-guide';
  content.id='brief-content';content.className='brief-column brief-content';
  design.id='brief-design';design.className='brief-column brief-design';
  guide.innerHTML='<div class="brief-label">01 · DIREZIONE</div><h2>Il tuo brief</h2>';
  content.innerHTML='<div class="brief-label">02 · CONTENUTI</div><h2>Le fonti del progetto</h2><p class="flow-description">Il modello sceglie le pagine pertinenti seguendo il prompt. Puoi anche lavorare sull’intero documento, oppure partire soltanto dalla tua idea.</p><div id="brief-upload-slot"></div><div id="brief-selected-slot"></div><div id="brief-history-slot"></div>';
  design.innerHTML='<div class="brief-label">03 · STILE E STRUMENTI</div><h2>Dai forma alla storia</h2>';
  const header=$('setup-back').closest('.setup-heading');
  header.innerHTML='<button type="button" class="quiet" id="brief-back">← Indietro</button><div><span class="flow-kicker">IL TUO PROGETTO</span><h1>Un buon brief, una bella presentazione.</h1><p>Decidi cosa raccontare, poi lascia che le slide prendano forma.</p></div><button type="button" class="quiet" id="setup-back" hidden>Apri presentazione →</button>';
  const title=$('title').closest('label'),prompt=$('prompt').closest('label'),count=$('count').closest('label'),theme=$('theme').closest('label');
  prompt.firstChild.textContent='Prompt guida';$('prompt').rows=9;$('prompt').maxLength=12000;
  guide.append(prompt,count,title,$('creation-engine').closest('label'),$('text-density').closest('label'),$('save-project'));
  const status=document.createElement('p');status.className='brief-save-note';status.innerHTML='<span id="brief-save-status">Impostazioni conservate nel progetto quando salvi o generi.</span>';guide.append(status);
  const model=document.createElement('div');model.className='brief-model';model.innerHTML='<span id="brief-model-status"></span><button type="button" class="quiet" id="brief-configure">Configura modello →</button>';guide.append(model);
  content.append($('pdf-scope').closest('label'),$('source-mode'));
  const upload=$('files').closest('label'),sources=$('sources'),history=$('document-library').closest('details');
  history.open=true;history.querySelector('summary').firstChild.textContent='Storico dei documenti ';
  for(const element of original){
    if([header,upload,sources,history].includes(element)||element.id==='recovery-projects'||element.id==='active-generation-home'||element.classList.contains('project-switcher'))continue;
    if(element.parentNode!==settings)continue;
    if(element.matches('.eyebrow,h2')||element.classList.contains('row'))continue;
    design.append(element);
  }
  design.append(theme);
  settings.replaceChildren(header,guide,content,design,...original.filter(e=>['active-generation-home','recovery-projects'].includes(e.id)));
  $('brief-upload-slot').append(upload);$('brief-selected-slot').append(sources);$('brief-history-slot').append(history);
  // Keep the compact project switcher for keyboard use and saved-project recovery.
  const switcher=original.find(e=>e.classList.contains('project-switcher'));guide.append(switcher);
  const top=document.querySelector('#create-page>.generation-actions');top.classList.add('brief-top-actions');
  top.querySelector('.hint').textContent='Controlla il brief, poi genera. Le slide appariranno nell’editor in tempo reale.';
  const nav=document.createElement('aside');nav.id='slide-navigator';nav.hidden=true;nav.setAttribute('aria-label','Navigazione slide');
  nav.innerHTML='<button type="button" id="toggle-slide-navigator" class="quiet" aria-expanded="true">▤ Le tue slide <span>‹</span></button><div id="slide-navigator-list"></div><p id="slide-navigator-status"></p>';
  document.body.append(nav);
  $('toggle-slide-navigator').onclick=()=>{const closed=nav.classList.toggle('navigator-collapsed');$('toggle-slide-navigator').setAttribute('aria-expanded',String(!closed))};
  $('slide-navigator-list').onclick=e=>{const link=e.target.closest('[data-slide-jump]');if(!link)return;e.preventDefault();document.getElementById('slide-'+link.dataset.slideJump)?.scrollIntoView({behavior:'smooth',block:'start'})};
  let handlers={},importMode='file',loading=false,currentProject=null,slideSignature='';
  const error=message=>{$('import-error').textContent=message||'';$('import-error').hidden=!message};
  function mode(value){importMode=value;for(const key of ['file','url','paste'])$('import-'+key+'-panel').hidden=key!==value;for(const button of imports.querySelectorAll('[data-import-mode]'))button.setAttribute('aria-pressed',String(button.dataset.importMode===value));error('')}
  function progress(label,percent=null,detail=''){loading=Boolean(label);$('import-progress').hidden=!loading;$('import-progress-label').textContent=label||'';$('import-progress-detail').textContent=detail;if(percent===null)$('import-progress-bar').removeAttribute('value');else $('import-progress-bar').value=percent;for(const control of imports.querySelectorAll('.import-panel button,.import-panel input,.import-panel textarea,.import-tabs button'))control.disabled=loading;$('import-continue').disabled=loading||!currentProject?.sources?.length;$('files').disabled=loading;handlers.loading?.();}
  async function run(action){if(loading)return;error('');try{await action()}catch(e){error(e.message);handlers.toast?.(e.message)}finally{progress('')}}
  start.querySelectorAll('[data-start-method]').forEach(button=>button.onclick=()=>handlers.start?.(button.dataset.startMethod));
  imports.querySelectorAll('[data-import-mode]').forEach(button=>button.onclick=()=>mode(button.dataset.importMode));
  imports.querySelector('[data-flow-back]').onclick=()=>handlers.navigate?.('new');
  $('brief-back').onclick=()=>handlers.navigate?.(currentProject?.sources?.length?'import':'new');
  $('brief-configure').onclick=()=>handlers.navigate?.('admin');
  $('import-url-panel').onsubmit=e=>{e.preventDefault();run(()=>handlers.url?.($('import-url').value.trim()))};
  $('import-paste-submit').onclick=()=>run(async()=>{const text=$('paste-content').value;if(!text.trim())throw Error('Incolla prima il testo da usare.');await handlers.files?.([new File([text],($('paste-name').value.trim()||'Appunti')+'.md',{type:'text/markdown'})]);$('paste-content').value=''});
  $('import-continue').onclick=()=>run(()=>handlers.continue?.());
  upload.addEventListener('dragover',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();upload.classList.add('file-dragover')}});
  upload.addEventListener('dragleave',()=>upload.classList.remove('file-dragover'));
  upload.addEventListener('drop',e=>{e.preventDefault();upload.classList.remove('file-dragover');if(!loading&&e.dataTransfer.files.length)run(()=>handlers.files?.([...e.dataTransfer.files]))});
  return {
    bind(callbacks){handlers=callbacks},mode,progress,error,run,get loading(){return loading},
    reset(){mode('file');$('paste-content').value='';$('paste-name').value='Appunti';$('import-url').value='';error('')},
    show(view){
      start.hidden=view!=='new';imports.hidden=view!=='import';nav.hidden=view!=='editor';
      const importing=view==='import';$(importing?'import-upload-slot':'brief-upload-slot').append(upload);$(importing?'import-selected-slot':'brief-selected-slot').append(sources);$(importing?'import-history-slot':'brief-history-slot').append(history);
      if(importing)history.open=true;
      const recoveryTarget=view==='library'?$('library'):view==='new'?$('start-recovery'):settings;
      if(view==='library')$('library-grid').before($('active-generation-home'),$('recovery-projects'));
      else recoveryTarget.append($('active-generation-home'),$('recovery-projects'));
    },
    update(project){
      currentProject=project;$('import-continue').disabled=loading||!project?.sources?.length;
      const n=project?.sources?.length||0;$('import-summary').textContent=n?n+' '+(n===1?'fonte pronta':'fonti pronte')+' · puoi aggiungerne altre o continuare.':'Scegli un file, un link o un documento dallo storico.';
      $('brief-model-status').textContent=$('active-model').textContent;
      $('brief-save-status').textContent=$('save-status').textContent||'Impostazioni conservate nel progetto quando salvi o generi.';
      const signature=JSON.stringify([project?.id,(project?.slides||[]).map(s=>[s.id,s.status,s.content?.title])]);
      if(slideSignature!==signature){slideSignature=signature;const list=$('slide-navigator-list');list.replaceChildren(...(project?.slides||[]).map((slide,index)=>{const link=document.createElement('a');link.href='#slide-'+slide.id;link.dataset.slideJump=slide.id;link.className='slide-nav-card '+slide.status;const number=document.createElement('span');number.className='slide-nav-number';number.textContent=String(index+1).padStart(2,'0');const title=document.createElement('strong');title.textContent=slide.content?.title||'Slide in preparazione';const state=document.createElement('small');state.textContent=({ready:'Pronta',generating:'In creazione…',failed:'Da completare',pending:'In attesa'})[slide.status]||slide.status;link.append(number,title,state);return link}));}
      const slides=project?.slides||[];$('slide-navigator-status').textContent=(slides.length?slides.filter(s=>s.status==='ready').length+' / '+slides.length+' slide pronte':'La scaletta apparirà qui.')+
        (project?.engine==='v2'?' · obiettivo '+project.count+' · '+(project.slide_format||'16:9'):'');
    },
  };
}
