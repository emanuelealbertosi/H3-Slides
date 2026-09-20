// Page-level structure. Existing controls keep their IDs and event handlers.
export function installStudioShell(){
  const settings=document.querySelector('.settings');
  const header=document.createElement('div');header.className='setup-heading';
  header.innerHTML='<button type="button" class="quiet" id="setup-back" hidden>← Torna alla presentazione</button><span class="eyebrow">IL TUO PROGETTO</span><h1>Che cosa vuoi raccontare?</h1><p>Parti da un’idea, scegli una direzione visiva e aggiungi le tue fonti.</p>';
  settings.prepend(header);
  const recovery=document.createElement('details');recovery.id='recovery-projects';recovery.className='model-panel recovery-projects';recovery.open=true;recovery.hidden=true;
  recovery.innerHTML='<summary>Progetti da recuperare <span id="recovery-count"></span></summary><p>I tentativi falliti o interrotti restano salvati, con istruzioni e allegati.</p><div id="recovery-list"></div>';
  header.after(recovery);
  const active=document.createElement('section');active.id='active-generation-home';active.className='model-panel active-generation-home';active.hidden=true;
  active.innerHTML='<h2>Generazione in corso</h2><p>Puoi lasciare questa pagina: il lavoro continua. Riapri il progetto per vedere slide e log.</p><div id="active-generation-list"></div>';
  header.after(active);
  const jobPanel=document.querySelector('#job-panel');settings.before(jobPanel);
  const retry=document.createElement('div');retry.id='recovery-help';retry.hidden=true;
  retry.innerHTML='<p id="recovery-description"></p><button type="button" id="recovery-restart" class="quiet">Ricrea da zero in una nuova versione</button>';
  jobPanel.append(retry);
  const themes=document.createElement('section');themes.className='theme-picker-panel';
  const engine=document.createElement('label');engine.innerHTML='Motore di creazione <select id="creation-engine"><option value="v2">V2 · pagina progettata dall’AI (anteprima)</option><option value="classic">Classico · layout automatici</option></select><small>V2: composizione libera a sezioni, senza il limite di quattro blocchi. I progetti esistenti mantengono il loro motore.</small>';
  header.after(engine);
  themes.innerHTML='<h2>Scegli un’atmosfera</h2><p class="muted">Otto direzioni visive, ognuna con una propria identità. Un clic aggiorna l’anteprima; salva il brief per conservarla.</p>'+
    '<div class="theme-current"><div class="theme-preview-heading"><span>IL TEMA CORRENTE</span><strong id="theme-current-name">Il tuo tema</strong></div><div id="theme-current-preview" class="theme-large-preview" aria-label="Anteprima del tema corrente"></div></div>'+
    '<div id="theme-gallery" class="theme-gallery" role="group" aria-label="Temi pronti e personali"></div>'+
    '<details class="theme-ai-panel"><summary>✦ Crea un tema con AI</summary><p>Descrivi l’atmosfera. Il modello propone colori e stile, senza cambiare la presentazione.</p>'+
    '<label>La tua idea visiva<textarea id="theme-ai-prompt" maxlength="2000" rows="4" placeholder="Es. Una rivista scientifica elegante: fondo avorio, verde profondo, titoli editoriali ed esempi ben distinti"></textarea></label>'+
    '<div class="theme-ai-provider"><small id="theme-ai-model"></small><button type="button" id="theme-ai-configure" class="quiet">Configura modello →</button></div>'+
    '<small>Usa il modello e le autorizzazioni configurati in Admin. Viene inviata solo questa descrizione, non i contenuti del progetto.</small>'+
    '<button type="button" id="theme-ai-generate" class="secondary">Crea anteprima con AI</button><p id="theme-ai-status" class="hint" role="status" aria-live="polite"></p>'+
    '<section id="theme-ai-result" class="theme-ai-result" hidden><strong id="theme-ai-name"></strong><div id="theme-ai-preview" class="theme-large-preview" aria-label="Anteprima del tema proposto dall’AI"></div><p id="theme-ai-note"></p><div class="theme-ai-actions"><button type="button" id="theme-ai-apply" class="primary">Applica questo tema</button><button type="button" id="theme-ai-save" class="quiet">Salva nella galleria</button></div></section></details>'+
    '<input id="theme-preset-name" type="hidden"><div class="row">'+
    '<label>Composizione grafica<select id="graphic-style"><option value="studio">Studio · varia e ariosa</option><option value="vivid">Vivace · colore e contrasti</option><option value="editorial">Magazine · testo e immagini</option><option value="classic">Classica</option></select></label>'+
    '<label>Altezza delle slide<select id="canvas-mode"><option value="adaptive">Adattivo · massimo +15%</option><option value="fixed">Fisso · formato esatto</option></select></label></div>'+
    '<label>Formato di base<select id="slide-format"><option value="16:9">16:9 · panoramico</option><option value="4:3">4:3 · classico</option><option value="16:10">16:10 · ampio</option><option value="1:1">1:1 · quadrato</option></select></label>'+
    '<small id="slide-format-help">V2 mantiene il formato scelto. Adattivo consente al massimo il 15% di altezza in più; se serve spazio, la generazione può aggiungere fino a 2 slide.</small>';
  const stylePanel=document.querySelector('#template').closest('details');stylePanel.before(themes);stylePanel.open=false;
  stylePanel.querySelector('summary').textContent='Personalizzazione avanzata · layout, font e colori';
  const overlay=document.createElement('details');overlay.className='editor-menubar';overlay.id='editor-menu';
  overlay.innerHTML='<summary>☰ Presentazione <span>opzioni ed esportazioni</span></summary><div class="editor-menu-content"><div class="editor-project-details"><strong id="editor-project-name"></strong><small id="editor-project-meta"></small></div><button id="editor-settings" class="primary" type="button">↶ Visualizza richiesta della fonte</button><p class="editor-source-hint">Riapri il brief originale e crea una nuova versione con un prompt o impostazioni diversi.</p><button id="editor-back" class="quiet" type="button">Torna alla presentazione</button><h3 class="editor-export-heading">Esporta la presentazione</h3></div>';
  overlay.querySelector('div').append(document.querySelector('.toolbar'));document.body.append(overlay);
  const format=document.createElement('label');format.className='grid-preference';
  format.innerHTML='Altezza della presentazione <select id="editor-canvas-mode"><option value="adaptive">Adattivo · massimo +15%</option><option value="fixed">Fisso · formato esatto</option></select><small>Salva la misura senza riscrivere i contenuti. Se una pagina non entra, un avviso indica che va ridotta o rigenerata.</small>';
  overlay.querySelector('div').append(format);
  const ratio=document.createElement('label');ratio.className='grid-preference slide-format-preference';
  ratio.innerHTML='Formato di base <select id="editor-slide-format"><option value="16:9">16:9 · panoramico</option><option value="4:3">4:3 · classico</option><option value="16:10">16:10 · ampio</option><option value="1:1">1:1 · quadrato</option></select><small id="editor-slide-format-help">I formati aggiuntivi sono disponibili con V2. Una modifica del formato non rigenera le slide.</small>';
  overlay.querySelector('div').append(ratio);
  overlay.addEventListener('toggle',()=>{if(overlay.open)document.body.classList.remove('navigation-away')});
  let last=0;
  window.addEventListener('scroll',()=>{
    const y=window.scrollY;document.body.classList.toggle('navigation-away',y>100&&y>last&&!overlay.open);last=y;
  },{passive:true});
  document.querySelector('.studio-sidebar').addEventListener('pointerenter',()=>document.body.classList.remove('navigation-away'));
  const grid=document.createElement('label');grid.className='grid-preference';grid.innerHTML='Precisione spostamenti <select id="editor-grid"><option value="2">Fine · 2 px</option><option value="8">Standard · 8 px</option><option value="16">Ampia · 16 px</option></select><small>Alt durante il trascinamento: nessun aggancio. Le maniglie agli angoli ridimensionano anche il testo.</small>';
  overlay.querySelector('div').append(grid);
}
