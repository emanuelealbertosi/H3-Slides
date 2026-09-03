// Credentials stay in memory. Saved choices contain only endpoint/model IDs.
export function createRemoteModelSelector({select,refresh,status,manualToggle,manualInput,getConnection,request,onSave,saved={},legacy={}}){
  const remembered=new Map(Object.entries(saved).filter(([,v])=>v&&typeof v.model==='string'));
  const normalize=url=>url.trim().replace(/\/+$/,'');
  if(legacy.url&&legacy.model&&!remembered.has(normalize(legacy.url)))
    remembered.set(normalize(legacy.url),{model:legacy.model,manual:false});
  let active=false,revision=0,controller=null,readyKey=null,currentUrl=null,loading=false;
  const connection=()=>{const value=getConnection();return {base_url:normalize(value.base_url),api_key:value.api_key.trim()}};
  const key=value=>JSON.stringify([value.base_url,value.api_key]);
  function option(value,label){
    const element=select.ownerDocument.createElement('option');element.value=value;element.textContent=label;return element;
  }
  function placeholder(label){select.replaceChildren(option('',label));select.disabled=true}
  function saveSelection(){
    const model=value();
    if(currentUrl)remembered.set(currentUrl,{model:model||remembered.get(currentUrl)?.model||'',manual:manualToggle.checked});
    onSave();
  }
  function invalidate(){
    revision++;controller?.abort();controller=null;readyKey=null;loading=false;refresh.disabled=false;
    const next=connection();
    if(currentUrl!==next.base_url){
      currentUrl=next.base_url;
      const previous=remembered.get(currentUrl);
      manualToggle.checked=Boolean(previous?.manual);
      manualInput.value=previous?.model||'';
    }
    manualInput.disabled=!manualToggle.checked;
    const manualSection=manualToggle.closest?.('details');
    if(manualSection&&manualToggle.checked)manualSection.open=true;
    placeholder(next.base_url?'Aggiorna l’elenco modelli':'Inserisci la Base URL API');
    status.textContent=next.base_url?'Premi Aggiorna modelli per leggere il catalogo del server.':
      'Inserisci la Base URL API e, se richiesta, la chiave. Nessun prompt o documento viene inviato per leggere il catalogo.';
    status.className='hint muted';refresh.disabled=!active||!next.base_url;
  }
  async function load(){
    invalidate();
    const config=connection();
    if(!active||!config.base_url)return;
    const mine=revision,requestKey=key(config);
    controller=new AbortController();loading=true;refresh.disabled=true;
    placeholder('Caricamento modelli…');status.textContent='Lettura del catalogo dal server…';
    try{
      const result=await request(config,controller.signal);
      if(mine!==revision||!active||key(connection())!==requestKey)return;
      const models=result.models||[],previous=remembered.get(currentUrl)?.model;
      select.replaceChildren(option('',models.length?'Scegli un modello':'Nessun modello disponibile'),
        ...models.map(model=>option(model.id,model.name!==model.id?model.id+' · '+model.name:model.id)));
      readyKey=requestKey;select.disabled=!models.length||manualToggle.checked;
      if(models.some(model=>model.id===previous))select.value=previous;
      status.textContent=models.length?
        models.length+' modelli disponibili. Scegli un modello per chat; il supporto Vision dipende dal modello.'+
        (previous&&!models.some(model=>model.id===previous)&&!manualToggle.checked?' Il modello precedente non è più nell’elenco: scegline un altro.':'')+
        (result.truncated?' Elenco limitato ai primi '+models.length+' modelli.':''):
        'Il server non espone modelli disponibili per queste credenziali. Verifica accesso e modelli abilitati.';
      onSave();
    }catch(error){
      if(mine!==revision||!active)return;
      placeholder('Catalogo non disponibile');
      status.textContent=error.name==='AbortError'?'Richiesta annullata. Riprova.':error.message;
      status.className='hint layout-warning';
    }finally{
      if(mine===revision){loading=false;refresh.disabled=false;controller=null}
    }
  }
  function value(){
    if(!active)return '';
    if(manualToggle.checked)return manualInput.value.trim();
    return !select.disabled&&readyKey===key(connection())?select.value:'';
  }
  select.addEventListener('change',saveSelection);
  manualInput.addEventListener('input',saveSelection);
  manualToggle.addEventListener('change',()=>{
    manualInput.disabled=!manualToggle.checked;
    select.disabled=manualToggle.checked||!readyKey||select.options.length<2;
    if(manualToggle.checked)manualInput.value=select.value||manualInput.value||remembered.get(currentUrl)?.model||'';
    saveSelection();
  });
  refresh.addEventListener('click',()=>load());
  return {
    activate(enabled){active=enabled;if(enabled)void load();else invalidate()},
    invalidate,load,value,
    preferences:()=>Object.fromEntries(remembered),
    requireSelection(){
      if(value())return;
      if(loading&&!manualToggle.checked)throw new Error('Attendi il caricamento dei modelli dal server.');
      throw new Error(manualToggle.checked?'Inserisci l’identificativo del modello.':'Scegli un modello dalla tendina del server.');
    },
  };
}
