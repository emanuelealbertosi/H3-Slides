import test from 'node:test';
import assert from 'node:assert/strict';
import {apiDefaults,validateApiSettings,createApiSettings} from '../static/api-settings.mjs';

class Input extends EventTarget{
  constructor(){super();this.value='';this.checked=false;this.disabled=false;this.textContent=''}
  get value(){return this._value}
  set value(value){this._value=String(value)}
  checkValidity(){return true}
}
function setup(saved){
  const selection={url:'http://localhost:1234/v1',model:'model-a',active:true};
  const fields=Object.fromEntries(Object.keys(apiDefaults).map(key=>[key,new Input()]));
  const serverTokens=new Input(),fieldset=new Input(),status=new Input();
  let saves=0;
  const control=createApiSettings({getSelection:()=>selection,fields,serverTokens,fieldset,status,saved,onSave:()=>saves++});
  control.sync();
  const edit=(key,value)=>{fields[key].value=String(value);fields[key].dispatchEvent(new Event('input'))};
  return {selection,fields,serverTokens,fieldset,status,control,edit,saves:()=>saves};
}

test('API defaults and whitelisted preference fields',()=>{
  assert.deepEqual(validateApiSettings({...apiDefaults,api_key:'test-secret'}),apiDefaults);
  assert.deepEqual(validateApiSettings({...apiDefaults,max_tokens:null}),{...apiDefaults,max_tokens:null});
});
test('valid changes persist by endpoint and model, including server default',()=>{
  const ui=setup();
  ui.edit('max_tokens',12000);ui.edit('temperature',.6);
  ui.selection.model='model-b';ui.control.sync();
  assert.equal(ui.control.value().max_tokens,3500);
  ui.serverTokens.checked=true;ui.serverTokens.dispatchEvent(new Event('input'));
  assert.equal(ui.control.value().max_tokens,null);
  ui.selection.model='model-a';ui.control.sync();
  assert.equal(ui.control.value().max_tokens,12000);
  ui.selection.url='http://other-server:1234/v1';ui.control.sync();
  assert.equal(ui.control.value().max_tokens,3500);
  const restored=setup(ui.control.preferences());
  assert.equal(restored.control.value().max_tokens,12000);
  assert.equal(restored.control.value().temperature,.6);
  assert.equal(ui.saves(),3);
});
test('invalid/blank values block generation and never replace valid saved values',()=>{
  const ui=setup();ui.edit('max_tokens',12000);
  ui.edit('max_tokens','');
  assert.throws(()=>ui.control.value(),/Admin/);
  assert.equal(ui.saves(),1);
  assert.equal(setup(ui.control.preferences()).control.value().max_tokens,12000);
  for(const change of [{max_tokens:127},{max_tokens:131073},{max_tokens:200.5},{temperature:NaN},
    {temperature:3},{top_p:0},{top_p:1.1},{timeout_seconds:29},{timeout_seconds:3601}]){
    assert.throws(()=>validateApiSettings({...apiDefaults,...change}),/Admin/);
  }
});
test('no model means disabled controls and no inference request',()=>{
  const ui=setup();ui.selection.model='';ui.control.sync();
  assert.equal(ui.fieldset.disabled,true);
  assert.throws(()=>ui.control.value(),/Seleziona/);
});
test('malformed saved profiles ignored; extra credential fields discarded',()=>{
  const key=JSON.stringify(['http://localhost:1234/v1','model-a']);
  assert.deepEqual(setup({[key]:{max_tokens:-1}}).control.value(),apiDefaults);
  const ui=setup({[key]:{...apiDefaults,api_key:'test-secret'}});
  assert.ok(!JSON.stringify(ui.control.preferences()).includes('test-secret'));
});
