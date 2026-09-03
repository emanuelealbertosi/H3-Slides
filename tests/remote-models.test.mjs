import test from 'node:test';
import assert from 'node:assert/strict';
import {createRemoteModelSelector} from '../static/remote-models.mjs';

class Element extends EventTarget{
  constructor(){super();this.disabled=false;this.checked=false;this.value='';this.textContent=''}
}
class Select extends Element{
  constructor(){super();this.options=[];this.ownerDocument={createElement:()=>({value:'',textContent:''})}}
  replaceChildren(...options){this.options=options;this.value=options[0]?.value||''}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const catalog=(...ids)=>({models:ids.map(id=>({id,name:id})),truncated:false});
function setup({saved,legacy,request=async()=>catalog('chat-a','chat-b')}={}){
  const select=new Select(),refresh=new Element(),status=new Element(),manualToggle=new Element(),manualInput=new Element();
  const connection={base_url:'https://one.example/v1',api_key:'test-credential'};
  let saves=0;
  const control=createRemoteModelSelector({select,refresh,status,manualToggle,manualInput,getConnection:()=>connection,
    request,onSave:()=>saves++,saved,legacy});
  const change=(element,value)=>{element.value=value;element.dispatchEvent(new Event('change'))};
  return {control,select,refresh,status,manualToggle,manualInput,connection,change,saves:()=>saves};
}

test('loads catalog automatically, restores old selection, remembers no API keys',async()=>{
  const ui=setup({legacy:{url:'https://one.example/v1/',model:'chat-b'}});
  ui.control.activate(true);await tick();
  assert.equal(ui.select.value,'chat-b');assert.equal(ui.control.value(),'chat-b');
  ui.change(ui.select,'chat-a');
  assert.deepEqual(ui.control.preferences(),{'https://one.example/v1':{model:'chat-a',manual:false}});
  assert.ok(!JSON.stringify(ui.control.preferences()).includes('test-credential'));
  assert.match(ui.status.textContent,/2 modelli/);assert.equal(ui.refresh.disabled,false);
});

test('model labels remain text, not HTML',async()=>{
  const ui=setup({request:async()=>({models:[{id:'<img onerror=alert(1)>',name:'<script>'}]})});
  ui.control.activate(true);await tick();
  assert.equal(ui.select.options[1].textContent,'<img onerror=alert(1)> · <script>');
});

test('endpoint changes clear stale selection and restore choices per server',async()=>{
  const ui=setup();ui.control.activate(true);await tick();ui.change(ui.select,'chat-b');
  ui.connection.base_url='https://two.example/v1';ui.control.invalidate();
  assert.equal(ui.control.value(),'');assert.equal(ui.select.disabled,true);
  await ui.control.load();assert.equal(ui.select.value,'');
  ui.change(ui.select,'chat-a');
  ui.connection.base_url='https://one.example/v1';await ui.control.load();
  assert.equal(ui.control.value(),'chat-b');
});

test('late response cannot replace new endpoint catalog',async()=>{
  const pending=[];
  const ui=setup({request:config=>new Promise(resolve=>pending.push({config,resolve}))});
  ui.control.activate(true);
  ui.connection.base_url='https://two.example/v1';const newest=ui.control.load();
  pending[1].resolve(catalog('new-model'));await newest;
  pending[0].resolve(catalog('stale-model'));await tick();
  assert.deepEqual(ui.select.options.map(o=>o.value),['','new-model']);
});

test('credential edits invalidate selection immediately',async()=>{
  const ui=setup();ui.control.activate(true);await tick();ui.change(ui.select,'chat-a');
  ui.connection.api_key='different-test-credential';ui.control.invalidate();
  assert.equal(ui.control.value(),'');assert.throws(()=>ui.control.requireSelection(),/tendina/);
  await ui.control.load();assert.equal(ui.control.value(),'chat-a');
});

test('missing remembered model is not silently replaced by another model',async()=>{
  const ui=setup({legacy:{url:'https://one.example/v1',model:'removed'}});
  ui.control.activate(true);await tick();
  assert.equal(ui.control.value(),'');assert.match(ui.status.textContent,/non è più/);
});

test('errors and empty catalogs are explicit, manual mode is an opt-in fallback',async()=>{
  const ui=setup({request:async()=>{throw new Error('Accesso negato')}});
  ui.control.activate(true);await tick();
  assert.match(ui.status.textContent,/Accesso negato/);assert.equal(ui.control.value(),'');
  ui.manualToggle.checked=true;ui.manualToggle.dispatchEvent(new Event('change'));
  ui.manualInput.value='custom-model';ui.manualInput.dispatchEvent(new Event('input'));
  assert.equal(ui.control.value(),'custom-model');
  assert.deepEqual(ui.control.preferences()['https://one.example/v1'],{model:'custom-model',manual:true});
  ui.manualToggle.checked=false;ui.manualToggle.dispatchEvent(new Event('change'));
  assert.equal(ui.control.value(),'');
  assert.equal(ui.control.preferences()['https://one.example/v1'].manual,false);
  const empty=setup({request:async()=>catalog()});empty.control.activate(true);await tick();
  assert.match(empty.status.textContent,/non espone modelli/);assert.equal(empty.select.disabled,true);
});

test('manual mode and choice can be restored after a reload',async()=>{
  const ui=setup({saved:{'https://one.example/v1':{model:'custom-model',manual:true}}});
  ui.control.activate(true);await tick();
  assert.equal(ui.control.value(),'custom-model');assert.equal(ui.manualToggle.checked,true);
  assert.equal(ui.select.disabled,true);assert.equal(ui.manualInput.disabled,false);
});

test('switching local aborts a pending fetch and loading blocks generation',async()=>{
  let complete;
  const ui=setup({request:()=>new Promise(resolve=>complete=resolve)});
  ui.control.activate(true);assert.throws(()=>ui.control.requireSelection(),/Attendi/);
  ui.control.activate(false);complete(catalog('remote-model'));await tick();
  assert.equal(ui.control.value(),'');assert.equal(ui.select.disabled,true);
});
