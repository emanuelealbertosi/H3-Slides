// Inference preferences only: never persist credentials or consent.
export const apiDefaults=Object.freeze({max_tokens:3500,temperature:.35,top_p:.95,timeout_seconds:360});
export function validateApiSettings(value){
  if(!value||typeof value!=='object')throw new Error('Parametri API non validi');
  const result={};
  for(const [key,min,max,integer] of [['max_tokens',128,131072,true],['temperature',0,2,false],
    ['top_p',Number.MIN_VALUE,1,false],['timeout_seconds',30,3600,true]]){
    const number=value[key];
    if(key==='max_tokens'&&number===null){result[key]=null;continue}
    if(typeof number!=='number'||!Number.isFinite(number)||number<min||number>max||(integer&&!Number.isInteger(number)))
      throw new Error('Controlla i parametri di inferenza API in Admin: '+key);
    result[key]=number;
  }
  return result;
}
export function createApiSettings({getSelection,fields,serverTokens,fieldset,status,saved,onSave}){
  const profiles=new Map();
  for(const [key,value] of Object.entries(saved||{})){
    try{profiles.set(key,validateApiSettings(value))}catch{} // Ignore obsolete/invalid browser preferences.
  }
  let currentKey='';
  function sync(){
    const {url,model,active}=getSelection();
    const key=active&&url.trim()&&model?JSON.stringify([url.trim().replace(/\/+$/,''),model]):'';
    fieldset.disabled=!key;
    if(key===currentKey)return;
    currentKey=key;
    const value=profiles.get(key)||apiDefaults;
    serverTokens.checked=value.max_tokens===null;
    for(const [name,input] of Object.entries(fields))input.value=value[name]??apiDefaults[name];
    fields.max_tokens.disabled=serverTokens.checked;
    status.textContent=key?'Parametri del modello selezionato · salvataggio automatico.':'Seleziona un modello per impostare i parametri API.';
  }
  function value(){
    sync();
    if(!currentKey)throw new Error('Seleziona un modello API in Admin');
    const result={};
    for(const [name,input] of Object.entries(fields)){
      if(name==='max_tokens'&&serverTokens.checked){result[name]=null;continue}
      if(!input.value.trim()||!input.checkValidity())throw new Error('Correggi i parametri di inferenza API in Admin');
      result[name]=Number(input.value);
    }
    return validateApiSettings(result);
  }
  function changed(){
    fields.max_tokens.disabled=serverTokens.checked;
    try{
      profiles.set(currentKey,value());
      status.textContent='Parametri salvati in questo browser per server e modello.';
      onSave();
    }catch(error){status.textContent=error.message}
  }
  for(const input of [...Object.values(fields),serverTokens])input.addEventListener('input',changed);
  return {sync,value,preferences:()=>Object.fromEntries(profiles)};
}
