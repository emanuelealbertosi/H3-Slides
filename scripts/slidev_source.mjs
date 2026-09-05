import {slideHTML,slideCSS,visualFor,fitSlide} from '../static/deck.mjs';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs/promises';
let input='';for await(const chunk of process.stdin)input+=chunk;
const project=JSON.parse(input);
process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));
const {chromium}=await import('playwright-chromium');
const browser=await chromium.launch({headless:true});
let rendered,overflow=[];
try{
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  const placeholder='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
  await page.setContent('<!doctype html><meta charset="utf-8"><style>'+slideCSS+'body{margin:0}</style>'+
    project.slides.map((s,i)=>{
      const media=visualFor(project,s.content,s);
      return slideHTML(project,s,i,{diagram:media.diagramAsset?placeholder+'#diagram':'',image:media.photo?placeholder+'#image':''});
    }).join(''));
  await page.evaluate(()=>document.fonts.ready);
  for(const frame of await page.locator('.slide-frame').all())await frame.evaluate(fitSlide);
  rendered=await page.locator('.slide-frame').evaluateAll(nodes=>nodes.map(n=>({html:n.outerHTML,overflow:n.dataset.overflow==='true'})));
  overflow=rendered.flatMap((r,i)=>r.overflow?[i+1]:[]);
  rendered=rendered.map((r,i)=>{
    const media=visualFor(project,project.slides[i].content,project.slides[i]);
    return r.html.replace(placeholder+'#diagram','./assets/'+media.diagramAsset).replace(placeholder+'#image','./assets/'+media.photo);
  });
}finally{await browser.close()}
const lines=['---','theme: default','mcp: false','layout: none','canvasWidth: 1280','aspectRatio: 16/9','title: '+JSON.stringify(project.title),'fonts:','  sans: '+(project.font||'Arial'),'  provider: none','drawings:','  enabled: false','---',''];
project.slides.forEach((s,i)=>{
  if(i)lines.push('','---','layout: none','---','');
  lines.push('<div v-pre>',rendered[i],'</div>','',
    '<!--',String(s.content.notes||'').replace(/-->/g,'—>'),'',...(s.content.sources||[]).map(s=>String(s).replace(/-->/g,'—>')),'-->','');
});
if(!project.slides.length)lines.push('# La presentazione è in preparazione');
const katexCSS=await fs.readFile(new URL('../static/vendor/katex/katex.min.css',import.meta.url),'utf8');
process.stdout.write(JSON.stringify({markdown:lines.join('\n'),css:katexCSS+slideCSS,overflow}));
