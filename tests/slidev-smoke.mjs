import {chromium} from 'playwright-chromium';
import assert from 'node:assert/strict';
const browser=await chromium.launch();
try{
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  await page.addInitScript(()=>localStorage.setItem('slidev-wake-lock','false'));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.argv[2],{waitUntil:'networkidle',timeout:60000});
  await page.locator('.slide-frame').first().waitFor();
  const style=await page.locator('.slide-frame').first().evaluate(e=>({
    width:getComputedStyle(e).width,height:getComputedStyle(e).height,
    background:getComputedStyle(e).backgroundColor
  }));
  assert.equal(style.width,'1280px');
  assert.equal(style.height,'720px');
  assert.notEqual(style.background,'rgba(0, 0, 0, 0)');
  assert.deepEqual(errors,[]);
  console.log('Slidev: CSS globale, pagina 1280×720 e compilazione verificati.');
}finally{await browser.close()}
