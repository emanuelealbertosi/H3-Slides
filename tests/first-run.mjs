import assert from 'node:assert/strict';
import {chromium} from 'playwright-chromium';
import fs from 'node:fs/promises';
const [url,model]=process.argv.slice(2);
const browser=await chromium.launch({headless:true});
const page=await browser.newPage();
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
try{
  await page.goto(url);
  await page.locator('#model-setup').waitFor({state:'visible'});
  assert.match(await page.locator('#model-setup-reason').textContent(),/Nessun modello/);
  await page.locator('#browse-model').click();
  await page.getByText('Selezione annullata. Nessun modello modificato.',{exact:true}).waitFor();
  await page.locator('#local-model-path').fill(model+'.missing');
  await page.locator('#register-model').click();
  await page.waitForFunction(()=>document.querySelector('#model-setup-status').textContent.includes('non trovato'));
  await page.locator('#local-model-path').fill(model);
  await page.locator('#register-model').click();
  await page.locator('#model-setup').waitFor({state:'hidden'});
  assert.equal(await page.locator('#model').inputValue(),model);
  assert.match(await page.locator('#model-warning').textContent(),/Manca il motore/);
  await page.reload();
  await page.waitForFunction(m=>document.querySelector('#model').value===m,model);
  assert.equal(await page.locator('#model-setup').isVisible(),false);
  // Only this test's temporary fixture is moved, then restored.
  await fs.rename(model,model+'.test-moved');
  try{
    await page.reload();
    await page.locator('#model-setup').waitFor({state:'visible'});
    await page.locator('#setup-remote').click();
    assert.equal(await page.locator('#provider').inputValue(),'remote');
    await page.reload();
    await page.locator('#remote-fields').waitFor({state:'visible'});
    await page.waitForFunction(()=>document.querySelector('#model-warning').textContent.includes('Nessun modello'));
    assert.equal(await page.locator('#model-setup').isVisible(),false);
  }finally{await fs.rename(model+'.test-moved',model)}
  assert.deepEqual(errors,[]);
  console.log('Primo avvio: modello assente, annullamento, file non valido, scelta salvata, disco mancante e API remota verificati.');
}finally{await browser.close()}
