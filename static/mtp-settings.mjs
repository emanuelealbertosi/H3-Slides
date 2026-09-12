// Local runtime capability only. Never add engine-specific fields to remote API calls.
export function createMtpSettings({root,status,model,load}){
  let revision=0,support=null,pending=false;
  const fields=()=>({enabled:root.querySelector('[data-setting="loading.mtp_enabled"]'),
    predictions:root.querySelector('[data-setting="loading.mtp_predictions"]')});
  function sync(){
    const {enabled,predictions}=fields();if(!enabled||!predictions)return;
    enabled.disabled=pending||(!support?.supported&&!enabled.checked);
    predictions.disabled=pending||!enabled.checked||!support?.supported;
  }
  root.addEventListener('change',sync);
  async function refresh(){
    const current=++revision,id=model.value,{enabled,predictions}=fields();
    support=null;pending=false;
    if(!enabled||!predictions||!id){status.hidden=true;return}
    status.hidden=false;status.textContent='Verifica MTP del runtime e del GGUF…';pending=true;sync();
    try{
      const result=await load(id);
      if(current!==revision||model.value!==id)return;
      support=result;
      status.textContent=(result.supported?'MTP disponibile. ':'MTP non disponibile. ')+result.reason+
        ' La scelta viene salvata per questo modello; nessun caricamento viene avviato da questo controllo.';
    }catch{
      if(current!==revision||model.value!==id)return;
      status.textContent='Controllo MTP non riuscito. Il modello resta utilizzabile senza MTP; verifica il runtime o riavvia l’app dopo un aggiornamento.';
    }finally{if(current===revision){pending=false;sync()}}
  }
  return {refresh};
}
