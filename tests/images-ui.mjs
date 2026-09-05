import './browser-env.mjs';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-chromium';

const [url,pid]=process.argv.slice(2);
assert.ok(/^http:\/\/127\.0\.0\.1:\d+\/?$/.test(url),'Isolated test server only');
const browser=await chromium.launch({headless:true});
try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(id=>localStorage.setItem('h3slides-project',id),pid);
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('#model').options[0].textContent!=='Caricamento catalogo…');
  if(await page.locator('#model-setup').isVisible())await page.locator('#close-model-setup').click();
  await page.locator('#open-create').click();
  const frame=page.locator('#slide-slide-test .slide-frame');
  await frame.locator('.image-placeholder').waitFor();
  assert.equal(await page.locator('#web-provider').inputValue(),'wikipedia');
  assert.equal(await page.locator('#source-images').isChecked(),true);
  assert.equal(await page.locator('#web-images').isChecked(),true);
  await page.locator('#source-images').uncheck();
  assert.equal(await page.locator('#web-images').isChecked(),true);
  await page.locator('#save-project').click();
  await page.waitForFunction(()=>document.querySelector('#save-status').textContent==='Salvato sul PC');
  await frame.scrollIntoViewIfNeeded();
  await page.mouse.move(1,1);
  const actions=frame.locator('.visual-actions');
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.visual-actions')).opacity==='0');
  const before=await frame.locator('.visual').boundingBox();
  await frame.locator('.image-placeholder').hover();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.visual-actions')).opacity==='1');
  const chooser=page.waitForEvent('filechooser');
  await actions.locator('[data-action="upload-image"]').click();
  await (await chooser).setFiles({name:'test.png',mimeType:'image/png',
    buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64')});
  await frame.locator('.photo-visual img').waitFor();
  await page.waitForFunction(()=>document.querySelector('.photo-visual img').naturalWidth>0);
  const after=await frame.locator('.visual').boundingBox();
  for(const key of ['x','y','width','height'])assert.ok(Math.abs(after[key]-before[key])<2,'Geometry retained: '+key);
  assert.equal(await frame.locator('.image-placeholder').count(),0);
  assert.equal(await frame.locator('.bullet-text').textContent(),'Testo che resta invariato.');
  await page.reload();
  await frame.locator('.photo-visual img').waitFor();
  assert.equal(await page.locator('#web-images').isChecked(),true);
  assert.equal(await page.locator('#source-images').isChecked(),false);
  assert.equal(await page.locator('[data-live-image] option').count(),2);
  assert.deepEqual(errors,[]);
}finally{await browser.close()}
