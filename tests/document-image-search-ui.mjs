import './browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright-chromium';

const browser=await chromium.launch({headless:true}),page=await browser.newPage();
const code=await readFile(new URL('../static/image-search.mjs',import.meta.url),'utf8');
const errors=[];page.on('pageerror',error=>errors.push(error.message));
try{
  await page.route('**/*',route=>route.fulfill({status:404,body:''}));
  await page.setContent('<html><body></body></html>');
  await page.addScriptTag({type:'module',content:code.replace('export function','function')+`
    window.calls=[];window.pending=[];window.insertions=[];
    window.picker=createImageSearch({api:(url,method,body,signal)=>new Promise((resolve,reject)=>{
      calls.push({url,method,body});pending.push({resolve,reject,signal});
    }),inserted:(target,result)=>insertions.push({target,result})});
    window.show=()=>picker.open({pid:'p',sid:'s',revision:7,source:'document',query:''});
    window.answer=(index,start=0,count=10,more=true,kind='figure')=>pending[index].resolve({
      search_id:'local-'+index,page:Math.floor(start/10),has_more:more,total:21,
      message:'Ambito: pagine PDF 2–4 selezionate per il lavoro.',
      results:Array.from({length:count},(_,offset)=>({id:'local-'+(start+offset),label:'Figura '+(start+offset),
        document:offset===0?'<img src=x onerror=alert(1)>':'Libro di testo.pdf',pdf_page:2,kind,
        source:'javascript:alert(1)',image_provider:'Documento locale',license:'',author:''}))});
    window.webAnswer=index=>pending[index].resolve({search_id:'web-'+index,page:0,has_more:false,
      results:[{id:'old-web',label:'Vecchio risultato Internet',source:'https://example.org/image',
        license:'CC0',author:'Autore web',image_provider:'Wikimedia Commons'}]});
  `});
  await page.waitForFunction(()=>!!window.picker);await page.evaluate(()=>show());
  const dialog=page.locator('#image-search-dialog'),query=dialog.locator('[name="query"]'),origin=dialog.locator('[name="source"]');
  const include=dialog.locator('[name="include_pages"]'),extended=dialog.locator('[name="openverse"]');
  const submit=dialog.locator('[type="submit"]'),more=dialog.locator('[data-more]');
  assert.equal(await origin.inputValue(),'document');assert.equal(await extended.isVisible(),false);
  assert.equal(await include.isVisible(),true);assert.equal(await query.getAttribute('required'),null);
  assert.match(await dialog.locator('[data-hint]').textContent(),/Ricerca locale sul PC/);
  assert.deepEqual(await page.evaluate(()=>calls.map(call=>call.body)),[{query:'',source:'document',include_pages:false}],
    'Document opening never starts a web search');
  await page.evaluate(()=>answer(0));await dialog.locator('.image-search-result').first().waitFor();
  assert.equal(await dialog.locator('.image-search-result').count(),10);
  assert.equal(await dialog.locator('.image-search-result a').count(),0,'Local metadata never links to an external source');
  assert.equal(await dialog.locator('.image-search-result small img').count(),0,'Document labels are escaped');
  assert.match(await dialog.locator('.image-search-result').first().textContent(),/<img src=x onerror=alert\(1\)> · pagina PDF 2/);
  assert.doesNotMatch(await dialog.locator('.image-search-result').first().textContent(),/Fonte e licenza|Autore indicato|CC0/);
  assert.match(await dialog.locator('[data-status]').textContent(),/10 di 21 immagini/);
  assert.match(await dialog.locator('[data-status]').textContent(),/pagine PDF 2–4/);
  await more.click();
  assert.deepEqual(await page.evaluate(()=>calls[1].body),{search_id:'local-0',page:1,source:'document',include_pages:false});
  await page.evaluate(()=>answer(1,10));await page.waitForFunction(()=>document.querySelectorAll('.image-search-result').length===20);
  await more.click();await page.evaluate(()=>answer(2,20,1,false));
  await page.waitForFunction(()=>document.querySelectorAll('.image-search-result').length===21);
  assert.equal(await more.isVisible(),false);
  await include.check();
  assert.deepEqual(await page.evaluate(()=>calls[3].body),{query:'',source:'document',include_pages:true});
  await page.evaluate(()=>answer(3,0,10,true,'page'));
  await page.waitForFunction(()=>document.querySelector('.image-search-result small')?.textContent.includes('Pagina intera'));
  await query.fill('x');await submit.click();
  assert.equal(await page.evaluate(()=>calls[4].body.query),'x','Local queries may contain a single character');
  await page.evaluate(()=>answer(4));await dialog.locator('.image-search-result').first().waitFor();
  await query.fill('');await submit.click();
  assert.equal(await page.evaluate(()=>calls[5].body.query),'','Clearing a local query lists all images');
  await page.evaluate(()=>answer(5));await dialog.locator('.image-search-result').first().waitFor();
  await origin.selectOption('web');
  assert.equal(await page.evaluate(()=>calls.length),6,'An empty web query never starts a request');
  assert.equal(await extended.isVisible(),true);assert.equal(await include.isVisible(),false);
  assert.equal(await query.getAttribute('required'),'');
  await query.fill('Odysseus');await submit.click();
  assert.deepEqual(await page.evaluate(()=>calls[6].body),{query:'Odysseus',openverse:false});
  await origin.selectOption('document');
  assert.equal(await page.evaluate(()=>pending[6].signal.aborted),true,'Switching source cancels pending Internet request');
  assert.deepEqual(await page.evaluate(()=>calls[7].body),{query:'Odysseus',source:'document',include_pages:true});
  await page.evaluate(()=>answer(7));await dialog.locator('.image-search-result').first().waitFor();
  await page.evaluate(()=>webAnswer(6));
  assert.equal(await dialog.locator('.image-search-result').count(),10);
  assert.doesNotMatch(await dialog.locator('.image-search-results').textContent(),/Vecchio risultato Internet/);
  await dialog.locator('.image-search-result button').first().click();
  for(const control of [origin,include,extended,query,dialog.locator('[data-close]')])assert.equal(await control.isDisabled(),true);
  assert.match(await dialog.locator('[data-status]').textContent(),/dal documento/);
  assert.doesNotMatch(await dialog.locator('[data-status]').textContent(),/licenza/);
  await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),true);
  await page.evaluate(()=>pending[8].reject(new Error('Le pagine selezionate sono cambiate')));
  await page.waitForFunction(()=>document.querySelector('[data-status]').textContent==='Le pagine selezionate sono cambiate');
  assert.equal(await origin.isDisabled(),false);assert.equal(await dialog.locator('.image-search-result').count(),10);
  await dialog.locator('.image-search-result button').first().click();
  await page.evaluate(()=>pending[9].resolve({slide:{id:'s',revision:8},source_image:{id:'source-figure.jpg',label:'Figura nel PDF'},use_source_images:true}));
  await dialog.waitFor({state:'hidden'});
  assert.deepEqual(await page.evaluate(()=>insertions[0]),{
    target:{pid:'p',sid:'s',revision:7,source:'document',query:''},
    result:{slide:{id:'s',revision:8},source_image:{id:'source-figure.jpg',label:'Figura nel PDF'},use_source_images:true},
  });
  assert.equal(await page.evaluate(()=>calls[9].body.result_id),'local-0');
  await page.evaluate(()=>show());await dialog.locator('[data-close]').click();
  await page.waitForFunction(()=>pending[10].signal.aborted);
  await page.evaluate(()=>answer(10));assert.equal(await dialog.isVisible(),false,'Cancelled local search cannot reopen dialog');
  await page.evaluate(()=>show());await page.evaluate(()=>answer(11));
  await dialog.locator('.image-search-result').first().waitFor();assert.equal(await dialog.locator('.image-search-result').count(),10);
  assert.equal(await page.evaluate(()=>insertions.length),1);
  assert.deepEqual(errors,[]);
  console.log('Document image search: local-only opening, optional query, page scope, 10-result pagination, safe metadata, source races, selection lock and insertion passed.');
}finally{await browser.close()}
