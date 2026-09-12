import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright-chromium';

const browser=await chromium.launch({headless:true}),page=await browser.newPage();
const code=await readFile(new URL('../static/image-search.mjs',import.meta.url),'utf8');
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
  await page.route('**/*',route=>route.fulfill({status:404,body:''}));
  await page.setContent('<html><body></body></html>');
  await page.addScriptTag({type:'module',content:code.replace('export function','function')+`
    window.calls=[];window.pending=[];window.insertions=[];
    window.picker=createImageSearch({api:(url,method,body,signal)=>new Promise((resolve,reject)=>{
      calls.push({url,method,body});pending.push({resolve,reject});
    }),inserted:(target,result)=>insertions.push({target,result})});
    window.show=()=>picker.open({pid:'p',sid:'s',revision:7,query:'Odysseus',openverse:true});
    window.answer=(index,label='Result',has_more=false)=>pending[index].resolve({search_id:'search-'+index,page:0,
      has_more,results:[{id:'r',label,source:'https://commons.wikimedia.org/wiki/File:X',license:'CC0',author:'A',image_provider:'Wikimedia Commons'}]});
  `});
  await page.waitForFunction(()=>!!window.picker);await page.evaluate(()=>show());
  const dialog=page.locator('#image-search-dialog'),query=dialog.locator('[name="query"]');
  assert.equal(await dialog.locator('[name="source"]').inputValue(),'web','Existing callers still default to Internet');
  assert.equal(await dialog.locator('[name="include_pages"]').isVisible(),false);
  assert.equal(await dialog.locator('[name="openverse"]').isChecked(),true);
  await query.fill('Troy');await dialog.locator('[type="submit"]').click();
  await page.evaluate(()=>answer(1,'New query'));
  await dialog.locator('.image-search-result').waitFor();
  await page.evaluate(()=>answer(0,'Old query'));
  assert.equal(await dialog.locator('.image-search-result strong').textContent(),'New query','Stale response must be ignored');
  await dialog.locator('.image-search-result button').click();
  assert.equal(await dialog.locator('[data-close]').isDisabled(),true,'Selection cannot be cancelled mid-save');
  assert.equal(await dialog.locator('[name="source"]').isDisabled(),true,'Origin is locked during insertion');
  await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),true);
  await page.evaluate(()=>pending[2].reject(new Error('La slide è cambiata')));
  await page.waitForFunction(()=>document.querySelector('[data-status]').textContent==='La slide è cambiata');
  assert.equal(await dialog.locator('.image-search-result').count(),1,'Failed insertion retains results');
  assert.equal(await query.isDisabled(),false);
  await dialog.locator('[data-close]').click();await page.evaluate(()=>show());
  await dialog.locator('[data-close]').click();await page.evaluate(()=>answer(3,'Closed response'));
  assert.equal(await dialog.isVisible(),false,'Late response must not reopen dialog');
  await page.evaluate(()=>show());await page.evaluate(()=>answer(4,'<img src=x onerror=alert(1)>'));
  await dialog.locator('.image-search-result').waitFor();
  assert.equal(await dialog.locator('.image-search-result strong img').count(),0,'Untrusted titles are text, not HTML');
  assert.equal(await dialog.locator('.image-search-result strong').textContent(),'<img src=x onerror=alert(1)>');
  await dialog.locator('.image-search-result button').click();
  await page.evaluate(()=>pending[5].resolve({slide:{id:'s',revision:8},visual_asset:{id:'photo.jpg'}}));
  await dialog.waitFor({state:'hidden'});
  assert.deepEqual(await page.evaluate(()=>insertions[0].target),{pid:'p',sid:'s',revision:7,query:'Odysseus',openverse:true});
  assert.deepEqual(errors,[]);
  console.log('Image search dialog: race protection, editable query, opt-in, errors, selection lock and safe titles passed.');
}finally{await browser.close()}
