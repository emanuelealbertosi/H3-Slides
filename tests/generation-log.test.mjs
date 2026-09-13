import './browser-env.mjs';
import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright-chromium';

let browser,source;
before(async()=>{
  browser=await chromium.launch({headless:true});
  source=await readFile(new URL('../static/generation-log.mjs',import.meta.url),'utf8');
});
after(async()=>{await browser?.close()});
const lines=n=>Array.from({length:n},(_,i)=>`10:20:30  Generazione slide · evento ${i+1}`).join('\n');
const settle=page=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
async function create({open=true,hidden=false,width=900}={}){
  const page=await browser.newPage({viewport:{width,height:700}});
  await page.setContent(`<style>body{margin:0}#panel{margin-top:300px}pre{max-height:140px;overflow:auto;white-space:pre-wrap;font:14px/22px monospace}</style>
    <div id="panel" ${hidden?'hidden':''}><details ${open?'open':''}><summary>Log</summary><pre id="events" tabindex="0"></pre></details></div><div style="height:1500px"></div>`);
  await page.addScriptTag({type:'module',content:source+'\nwindow.logView=createGenerationLog(document.querySelector("#events"));'});
  await page.waitForFunction(()=>window.logView);
  return page;
}
async function update(page,n,id='job-1'){
  await page.evaluate(({id,text})=>window.logView.update(id,text),{id,text:lines(n)});
  await settle(page);
}
async function bottom(page){
  const distance=await page.locator('#events').evaluate(e=>e.scrollHeight-e.clientHeight-e.scrollTop);
  assert.ok(distance<=1,`Last line is ${distance}px below the viewport`);
}

for(const width of [900,390])test(`first load and new events follow the tail at ${width}px`,async()=>{
  const page=await create({width});
  try{
    await update(page,60);await bottom(page);
    await page.evaluate(()=>window.scrollTo(0,200));
    await update(page,70);await bottom(page);
    assert.equal(await page.evaluate(()=>window.scrollY),200,'Only the log scrolls');
    await page.evaluate(()=>window.firstText=document.querySelector('#events').firstChild);
    await update(page,70);
    assert.equal(await page.evaluate(()=>window.firstText===document.querySelector('#events').firstChild),true);
  }finally{await page.close()}
});

test('manual history reading stays in place; reaching the end resumes following',async()=>{
  const page=await create();
  try{
    await update(page,60);
    await page.locator('#events').evaluate(e=>{e.scrollTop=88});await settle(page);
    await update(page,75);
    assert.equal(await page.locator('#events').evaluate(e=>e.scrollTop),88);
    await page.locator('#events').evaluate(e=>{e.scrollTop=e.scrollHeight});await settle(page);
    await update(page,80);await bottom(page);
    await page.locator('#events').evaluate(e=>{e.scrollTop=0});await settle(page);
    await update(page,65,'job-2');await bottom(page);
  }finally{await page.close()}
});

test('collapsed and hidden panels show the latest events when reopened',async()=>{
  const page=await create({open:false,hidden:true});
  try{
    await update(page,60);
    await page.evaluate(()=>{document.querySelector('#panel').hidden=false;document.querySelector('details').open=true});
    await settle(page);await bottom(page);
    await page.evaluate(()=>{document.querySelector('details').open=false});await settle(page);
    await update(page,80);
    await page.evaluate(()=>{document.querySelector('details').open=true});await settle(page);await bottom(page);
    await page.evaluate(()=>{document.querySelector('#panel').hidden=true});await settle(page);
    await update(page,90);
    await page.evaluate(()=>{document.querySelector('#panel').hidden=false});await settle(page);await bottom(page);
    await page.setViewportSize({width:390,height:700});await settle(page);await bottom(page);
  }finally{await page.close()}
});

test('empty logs, batched updates and literal error messages remain safe',async()=>{
  const page=await create();
  try{
    await update(page,0);await update(page,1);await bottom(page);
    await page.evaluate(text=>{window.logView.update('job-1',text);window.logView.update('job-1',text+'\n<script>unsafe()</script> Errore finale')},lines(80));
    await settle(page);await bottom(page);
    assert.equal(await page.locator('#events script').count(),0);
    assert.match(await page.locator('#events').textContent(),/Errore finale$/);
  }finally{await page.close()}
});
