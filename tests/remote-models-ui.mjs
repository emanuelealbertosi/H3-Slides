import './browser-env.mjs';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-chromium';

const url=process.argv[2];
assert.ok(/^http:\/\/127\.0\.0\.1:\d+\/?$/.test(url),'Only an isolated local test app is allowed');
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',error=>errors.push(error.message));
const ready=()=>page.waitForFunction(()=>document.querySelector('#api-model').options.length===3);
try{
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('#model').options[0].textContent!=='Caricamento catalogo…');
  if(await page.locator('#model-setup').isVisible())await page.locator('#close-model-setup').click();
  await page.locator('#open-create').click();
  await page.locator('#prompt').fill('Brief ancora non salvato');
  await page.locator('#open-admin').click();
  assert.equal(new URL(page.url()).pathname,'/admin');
  assert.equal(await page.locator('#create-page #provider, #create-page #model, #create-page #api-url, #create-page #vision').count(),0);
  assert.equal(await page.locator('#admin').evaluate(el=>el.tagName),'MAIN');
  await page.locator('#provider').selectOption('remote');
  await page.locator('#api-url').fill('https://provider.example/v1');
  await page.locator('#api-key').fill('test-only');
  await page.locator('#api-key').press('Tab');
  await ready();
  assert.equal(await page.locator('#api-model').evaluate(el=>el.tagName),'SELECT');
  await page.locator('#api-model').selectOption('demo/chat-vision');
  await page.locator('#api-max-tokens').fill('12000');
  await page.locator('#api-temperature').fill('0.6');
  await page.locator('#api-timeout').fill('900');
  await page.locator('#api-model').selectOption('demo/chat-small');
  assert.equal(await page.locator('#api-max-tokens').inputValue(),'3500');
  await page.locator('#api-server-tokens').check();
  assert.equal(await page.locator('#api-max-tokens').isDisabled(),true);
  await page.locator('#api-model').selectOption('demo/chat-vision');
  assert.equal(await page.locator('#api-max-tokens').inputValue(),'12000');
  assert.equal(await page.locator('#api-server-tokens').isChecked(),false);
  await page.locator('#close-admin').click();
  assert.equal(await page.locator('#prompt').inputValue(),'Brief ancora non salvato');
  assert.equal(await page.locator('#api-key').inputValue(),'test-only');
  await page.goBack();
  assert.equal(await page.locator('#admin').isVisible(),true);
  await page.goForward();
  assert.equal(await page.locator('#create-page').isVisible(),true);
  await page.locator('#open-admin').click();
  await page.locator('#refresh-remote-models').click();await ready();
  assert.equal(await page.locator('#api-model').inputValue(),'demo/chat-vision');
  assert.equal(await page.locator('#api-max-tokens').inputValue(),'12000');

  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#remote-model-status').textContent.includes('negato'));
  assert.equal(await page.locator('#api-key').inputValue(),'');
  await page.locator('#api-key').fill('test-only');await page.locator('#api-key').press('Tab');await ready();
  assert.equal(await page.locator('#api-model').inputValue(),'demo/chat-vision');
  assert.ok(!await page.evaluate(()=>localStorage.getItem('h3slides-settings').includes('test-only')));
  assert.equal(await page.locator('#api-max-tokens').inputValue(),'12000');
  assert.equal(await page.locator('#api-temperature').inputValue(),'0.6');
  assert.equal(await page.locator('#api-timeout').inputValue(),'900');

  await page.locator('#api-url').fill('https://other.example/v1');
  assert.equal(await page.locator('#api-model').isDisabled(),true);
  await page.locator('#api-url').press('Tab');await ready();
  assert.equal(await page.locator('#api-model').inputValue(),'');
  await page.locator('#api-model').selectOption('demo/chat-small');
  assert.equal(await page.locator('#api-server-tokens').isChecked(),false); // Other server has its own profile.
  await page.locator('#api-url').fill('https://provider.example/v1');await page.locator('#api-url').press('Tab');await ready();
  assert.equal(await page.locator('#api-model').inputValue(),'demo/chat-vision');

  // Capture the actual submitted selection without contacting an LLM.
  let resolveGeneration;
  const generation=new Promise(resolve=>resolveGeneration=resolve);
  await page.route('**/api/projects/*/generate',async route=>{
    resolveGeneration(route.request().postDataJSON());
    await route.fulfill({json:{id:'test-only-job',status:'queued',progress:0,events:[]}});
  });
  await page.locator('#consent').check();
  await page.locator('#close-admin').click();
  await page.locator('#prompt').fill('Presentazione di prova per verificare il selettore');
  await page.locator('#generate').click();
  const payload=await generation;
  assert.equal(payload.provider.model,'demo/chat-vision');
  assert.equal(payload.provider.base_url,'https://provider.example/v1');
  assert.equal(payload.provider.api_key,'test-only');
  assert.deepEqual(payload.provider.inference,{max_tokens:12000,temperature:.6,top_p:.95,timeout_seconds:900});

  await page.locator('#open-admin').click();
  await page.locator('#api-model').selectOption('demo/chat-small');
  assert.equal(await page.locator('#api-server-tokens').isChecked(),true);
  const defaultGeneration=new Promise(resolve=>resolveGeneration=resolve);
  await page.locator('#close-admin').click();
  await page.locator('#generate').click();
  assert.equal((await defaultGeneration).provider.inference.max_tokens,null);
  await page.locator('#open-admin').click();
  await page.locator('#api-model').selectOption('demo/chat-vision');
  await page.locator('#api-max-tokens').fill('');
  await page.locator('#close-admin').click();
  await page.locator('#generate').click();
  await page.locator('#admin').waitFor({state:'visible'});
  assert.match(await page.locator('#toast').textContent(),/parametri.*Admin/);
  await page.locator('#api-max-tokens').fill('12000');
  await page.locator('#api-key').fill('wrong-test-key');await page.locator('#api-key').press('Tab');
  await page.waitForFunction(()=>document.querySelector('#remote-model-status').textContent.includes('negato'));
  assert.equal(await page.locator('#api-model').isDisabled(),true);
  await page.getByText('Alternativa: ID manuale',{exact:true}).click();
  await page.locator('#api-model-manual').check();
  await page.locator('#api-model-id').fill('custom/model');
  await page.locator('#api-model-id').press('Tab');
  assert.equal(await page.locator('#api-model-id').isDisabled(),false);
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#api-model-id').value==='custom/model');
  assert.equal(await page.locator('#api-model-manual').isChecked(),true);
  assert.equal(await page.locator('#api-key').inputValue(),'');
  await page.locator('#provider').selectOption('local');
  assert.equal(await page.locator('#remote-fields').isVisible(),false);
  assert.equal(await page.locator('#local-fields').isVisible(),true);
  await page.setViewportSize({width:390,height:844});
  const mobileLayout=await page.evaluate(()=>({fits:document.documentElement.scrollWidth<=window.innerWidth,
    width:document.documentElement.scrollWidth,viewport:window.innerWidth,
    offenders:[...document.querySelectorAll('body *')].filter(element=>element.getBoundingClientRect().right>window.innerWidth+1)
      .slice(0,8).map(element=>({tag:element.tagName,id:element.id,class:element.className,right:Math.round(element.getBoundingClientRect().right)}))}));
  assert.equal(mobileLayout.fits,true,JSON.stringify(mobileLayout));
  assert.deepEqual(errors,[]);
  console.log('Model selector UI passed: discovery, refresh, per-server memory, reload, submitted model, credentials, manual fallback and local mode.');
}finally{await browser.close()}
