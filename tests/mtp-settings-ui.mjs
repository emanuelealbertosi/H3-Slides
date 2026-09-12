import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright-chromium';

const browser=await chromium.launch({headless:true});
const page=await browser.newPage();
try{
  await page.route('**/*',route=>route.abort());
  await page.setContent('<select id="model"><option>a</option><option>b</option></select><div id="settings">'+
    '<input type="checkbox" data-setting="loading.mtp_enabled"><input type="number" value="1" data-setting="loading.mtp_predictions"></div><p id="status"></p>');
  const source=await readFile(new URL('../static/mtp-settings.mjs',import.meta.url),'utf8');
  await page.addScriptTag({type:'module',content:source+'\nwindow.makeMtp=createMtpSettings;'});
  await page.waitForFunction(()=>window.makeMtp);
  await page.evaluate(()=>{
    window.requests=[];
    window.controller=window.makeMtp({root:document.querySelector('#settings'),status:document.querySelector('#status'),
      model:document.querySelector('#model'),load:model=>new Promise((resolve,reject)=>requests.push({model,resolve,reject}))});
    controller.refresh();
  });
  const toggle=page.locator('[type=checkbox]'),count=page.locator('[type=number]');
  assert.equal(await toggle.isDisabled(),true);assert.equal(await count.inputValue(),'1');
  await page.evaluate(()=>requests[0].resolve({supported:true,reason:'Testa MTP rilevata.'}));
  await page.waitForFunction(()=>!document.querySelector('[type=checkbox]').disabled);
  assert.equal(await count.isDisabled(),true);
  await toggle.check();assert.equal(await count.isDisabled(),false);
  await count.fill('4');assert.equal(await count.inputValue(),'4');
  // A late response for A cannot authorize MTP for B.
  await page.evaluate(()=>{controller.refresh();document.querySelector('#model').value='b';controller.refresh()});
  await page.evaluate(()=>requests[2].resolve({supported:false,reason:'Testa assente.'}));
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Testa assente'));
  await page.evaluate(()=>requests[1].resolve({supported:true,reason:'Risposta vecchia'}));
  assert.doesNotMatch(await page.locator('#status').textContent(),/Risposta vecchia/);
  assert.equal(await count.isDisabled(),true);
  assert.equal(await toggle.isChecked(),true,'An unsupported check does not silently rewrite a saved preference');
  await toggle.uncheck();assert.equal(await toggle.isDisabled(),true);
  await page.evaluate(()=>{document.querySelector('#model').value='a';controller.refresh()});
  await page.evaluate(()=>requests[3].reject(new Error('unavailable')));
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('non riuscito'));
  assert.equal(await toggle.isDisabled(),true);
  await page.evaluate(()=>{document.querySelector('#settings').replaceChildren();controller.refresh()});
  assert.equal(await page.locator('#status').isVisible(),false,'Legacy server schemas do not trigger broken controls');
  console.log('MTP Admin: default 1, opt-in, capability gating, stale responses, errors and legacy schemas passed');
}finally{await browser.close()}
