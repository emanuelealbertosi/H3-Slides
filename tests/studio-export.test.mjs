import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright-chromium';
import JSZip from 'jszip';
import {slideHTML,slideCSS,fitSlide} from '../static/deck.mjs';
import {buildExports} from '../scripts/export.mjs';
import {codeHTML} from '../static/code-blocks.mjs';

test('code is escaped and highlighted without execution',()=>{
  assert.match(codeHTML('return "<script>"','python'),/syntax-keyword/);
  assert.doesNotMatch(codeHTML('<script>alert(1)</script>','cpp'),/<script>/);
  assert.match(codeHTML('    print(1)\n','python'),/^    /);
});

test('adaptive code cards grow, retain every line and export to PDF/PPTX',async()=>{
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-studio-code-'));
  const code='def esempio():\n'+Array.from({length:25},(_,i)=>'    print("riga '+i+'")').join('\n');
  const project={title:'Codice leggibile',theme:'paper',graphic_style:'studio',canvas_mode:'adaptive',
    slides:[{content:{title:'Python con indentazione',layout:'content',blocks:[{kind:'code',language:'python',heading:'Esempio Python',text:code}],bullets:[],diagram:{kind:'none'}}},
      {content:{title:'C e C++',layout:'content',blocks:[{kind:'code',language:'cpp',heading:'Esempio C++',text:'#include <iostream>\nint main() {\n    std::cout << "Ciao";\n    return 0;\n}'}],bullets:[],diagram:{kind:'none'}}}]};
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    await page.setContent('<style>'+slideCSS+'</style>'+project.slides.map((s,i)=>slideHTML(project,s,i)).join(''));
    await page.evaluate(()=>document.fonts.ready);
    for(const frame of await page.locator('.slide-frame').all())await frame.evaluate(fitSlide);
    const heights=await page.locator('.slide-frame').evaluateAll(nodes=>nodes.map(n=>n.offsetHeight));
    assert.ok(heights[0]>720&&heights[0]<=1008,'Long card grows slightly');
    assert.equal(await page.locator('.kind-code p').first().textContent(),code);
    assert.equal(await page.locator('.slide-frame[data-overflow=true]').count(),0);
    const first=page.locator('.slide-frame').first();
    const saved=await first.evaluate(n=>({height:n.offsetHeight,box:n.querySelector('.kind-code').getBoundingClientRect().height}));
    await first.evaluate(n=>{
      const root=n.getBoundingClientRect(),scale=root.width/1280;
      for(const element of n.querySelectorAll('[data-free-key]')){
        const r=element.getBoundingClientRect(),p={x:Math.round((r.left-root.left)/scale),y:Math.round((r.top-root.top)/scale),w:Math.round(r.width/scale),h:Math.round(r.height/scale)};
        for(const key of ['x','y','w','h']){element.style.setProperty('--free-'+key,p[key]+'px');element.dataset['free'+key.toUpperCase()]=String(p[key])}
      }
      n.dataset.freeBase=n.dataset.layout;n.dataset.freeCompact=String(n.classList.contains('compact-spacing'));
      n.dataset.canvasHeight=String(n.offsetHeight);n.dataset.candidates='["freeform"]';
    });
    await first.evaluate(fitSlide);
    assert.equal(await first.evaluate(n=>n.offsetHeight),saved.height,'Switching to freeform preserves card height');
  }finally{await browser.close()}
  const pdf=await buildExports(project,out,path.join(out,'pdf'),'pdf');
  const probe='import fitz,json,sys; d=fitz.open(sys.argv[1]); print(json.dumps({"pages":len(d),"heights":[p.rect.height for p in d],"text":"".join(p.get_text() for p in d)}))';
  const parsed=JSON.parse(execFileSync(path.resolve('.venv/Scripts/python.exe'),['-c',probe,pdf],{encoding:'utf8'}).trim().split('\n').findLast(line=>line.startsWith('{')));
  assert.equal(parsed.pages,2);assert.ok(parsed.heights[0]>parsed.heights[1]);
  assert.match(parsed.text,/riga 24/);assert.match(parsed.text,/std::cout/);
  const pptx=await buildExports(project,out,path.join(out,'pptx'),'pptx'),zip=await JSZip.loadAsync(await fs.readFile(pptx));
  const xml=await zip.file('ppt/slides/slide1.xml').async('string');
  assert.match(xml,/riga 24/);assert.match(xml,/Consolas/);
});
