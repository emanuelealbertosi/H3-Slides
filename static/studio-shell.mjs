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
  themes.innerHTML='<h2>Scegli un’atmosfera</h2><p class="muted">Un clic imposta colori, caratteri e stile. I dettagli rimangono personalizzabili.</p><div id="theme-gallery" class="theme-gallery"></div>'+
    '<input id="theme-preset-name" type="hidden"><div class="row">'+
    '<label>Composizione grafica<select id="graphic-style"><option value="studio">Studio · varia e ariosa</option><option value="vivid">Vivace · colore e contrasti</option><option value="editorial">Magazine · testo e immagini</option><option value="classic">Classica</option></select></label>'+
    '<label>Formato delle schede<select id="canvas-mode"><option value="adaptive">Adattivo · cresce con il contenuto</option><option value="fixed">Fisso · 16:9</option></select></label></div>'+
    '<small>Le schede adattive crescono quanto serve, fino a 1440 px, per testi e immagini leggibili. Il PDF conserva le altezze; PowerPoint usa un formato comune senza tagli.</small>';
  const stylePanel=document.querySelector('#template').closest('details');stylePanel.before(themes);stylePanel.open=false;
  stylePanel.querySelector('summary').textContent='Personalizzazione avanzata · layout, font e colori';
  const overlay=document.createElement('details');overlay.className='editor-menubar';overlay.id='editor-menu';
  overlay.innerHTML='<summary>☰ Presentazione <span>download e impostazioni</span></summary><div class="editor-menu-content"><button id="editor-settings" class="primary" type="button">⚙ Impostazioni e nuova versione</button><button id="editor-back" class="quiet" type="button">Torna alla presentazione</button></div>';
  overlay.querySelector('div').append(document.querySelector('.toolbar'));document.body.append(overlay);
  const format=document.createElement('label');format.className='grid-preference';
  format.innerHTML='Formato della presentazione <select id="editor-canvas-mode"><option value="adaptive">Adattivo · altezza automatica</option><option value="fixed">Fisso · 16:9</option></select><small>Applica alle slide esistenti senza rigenerare testi o immagini.</small>';
  overlay.querySelector('div').prepend(format);
  overlay.addEventListener('toggle',()=>{if(overlay.open)document.body.classList.remove('navigation-away')});
  let last=0;
  window.addEventListener('scroll',()=>{
    const y=window.scrollY;document.body.classList.toggle('navigation-away',y>100&&y>last&&!overlay.open);last=y;
  },{passive:true});
  document.querySelector('.studio-sidebar').addEventListener('pointerenter',()=>document.body.classList.remove('navigation-away'));
  const grid=document.createElement('label');grid.className='grid-preference';grid.innerHTML='Precisione spostamenti <select id="editor-grid"><option value="2">Fine · 2 px</option><option value="8">Standard · 8 px</option><option value="16">Ampia · 16 px</option></select><small>Alt durante il trascinamento: nessun aggancio. Le maniglie agli angoli ridimensionano anche il testo.</small>';
  overlay.querySelector('div').prepend(grid);
}
