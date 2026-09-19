import {slideHTML,slideCSS,visualFor,fitSlide} from '../static/deck.mjs';
import {pageAssets} from '../static/page-v2.mjs';
import {fileURLToPath} from 'node:url';
let input='';for await(const chunk of process.stdin)input+=chunk;
const project=JSON.parse(input);
process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));
const {chromium}=await import('playwright-chromium');
const {loadMathStyles}=await import('./export.mjs');
const sharedCSS=await loadMathStyles()+slideCSS;
const browser=await chromium.launch({headless:true});
let rendered,overflow=[],canvasHeight=720;
try{
  const page=await browser.newPage({viewport:{width:1280,height:720}});
  // Measure using the actual image proportions supplied by the asset packager.
  // A square 1px placeholder changes object-fit and gives the wrong layout.
  const placeholder=(id,kind)=>{
    const dim=project._media_dimensions?.[id];
    const valid=dim&&Number.isFinite(dim.width)&&Number.isFinite(dim.height)&&dim.width>0&&dim.height>0;
    const width=valid?dim.width:1800,height=valid?dim.height:1200;
    return 'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"></svg>`)+`#${kind}`;
  };
  const urls=project.slides.map(s=>{
    const media=visualFor(project,s.content,s);
    return {assets:Object.fromEntries(pageAssets(s.content.page).map(id=>[id,placeholder(id,id)])),diagram:media.diagramAsset?placeholder(media.diagramAsset,'diagram'):'',image:media.photo?placeholder(media.photo,'image'):''};
  });
  await page.setContent('<!doctype html><meta charset="utf-8"><style>'+sharedCSS+'body{margin:0}</style>'+
    project.slides.map((s,i)=>slideHTML(project,s,i,urls[i])).join(''));
  await page.evaluate(()=>document.fonts.ready);
  await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
  for(const frame of await page.locator('.slide-frame').all())await frame.evaluate(fitSlide);
  rendered=await page.locator('.slide-frame').evaluateAll(nodes=>nodes.map(n=>({html:n.outerHTML,height:n.offsetHeight,overflow:n.dataset.overflow==='true'})));
  canvasHeight=Math.max(720,...rendered.map(r=>r.height));
  // Slidev has one canvas for the whole deck. Reflow shorter cards to its
  // full height before freezing HTML, including their footer and freeform boxes.
  for(const frame of await page.locator('.slide-frame').all())await frame.evaluate(fitSlide,{targetHeight:canvasHeight});
  rendered=await page.locator('.slide-frame').evaluateAll(nodes=>nodes.map(n=>({html:n.outerHTML,height:n.offsetHeight,overflow:n.dataset.overflow==='true'})));
  overflow=rendered.flatMap((r,i)=>r.overflow?[i+1]:[]);
  if(overflow.length)throw new Error('Testo fuori dallo spazio nelle slide '+overflow.join(', ')+'. Dividi o modifica il contenuto prima di esportare; nessuna parte viene nascosta.');
  rendered=rendered.map((r,i)=>{
    const media=visualFor(project,project.slides[i].content,project.slides[i]);
    let html=r.html;
    for(const [id,url] of Object.entries(urls[i].assets))html=html.replaceAll(url,'./assets/'+id);
    if(urls[i].diagram)html=html.replace(urls[i].diagram,'./assets/'+media.diagramAsset);
    if(urls[i].image)html=html.replace(urls[i].image,'./assets/'+media.photo);
    return html;
  });
}finally{await browser.close()}
const lines=['---','theme: default','mcp: false','layout: none','canvasWidth: 1280','aspectRatio: '+(canvasHeight===720?'16/9':`1280/${canvasHeight}`),'title: '+JSON.stringify(project.title),'fonts:','  sans: '+(project.font||'Arial'),'  provider: none','drawings:','  enabled: false','---',''];
project.slides.forEach((s,i)=>{
  if(i)lines.push('','---','layout: none','---','');
  lines.push('<div v-pre>',rendered[i],'</div>','',
    '<!--',String(s.content.notes||'').replace(/-->/g,'—>'),'',...(s.content.sources||[]).map(s=>String(s).replace(/-->/g,'—>')),'-->','');
});
if(!project.slides.length)lines.push('# La presentazione è in preparazione');
process.stdout.write(JSON.stringify({markdown:lines.join('\n'),css:sharedCSS,overflow}));
