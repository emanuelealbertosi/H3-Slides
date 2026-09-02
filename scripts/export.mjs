import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import pptxgen from 'pptxgenjs';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,themes} from '../static/deck.mjs';

export async function buildExports(project, assetsDir, outDir, format) {
  await fs.mkdir(outDir,{recursive:true});
  const imagePath = id => {
    if (!/^[a-f0-9-]+\.jpg$/.test(id)) throw new Error('Riferimento immagine non valido');
    return path.join(assetsDir,id);
  };
  if (format==='pptx') {
    const pptx = new pptxgen();
    pptx.layout='LAYOUT_WIDE';
    pptx.author='H3-slides'; pptx.subject=project.prompt; pptx.title=project.title;
    pptx.lang='it-IT';
    for (const [index,item] of project.slides.entries()) {
      const c=item.content, t=themes[project.theme]||themes.ink, s=pptx.addSlide();
      s.background={color:t.bg.slice(1)};
      const text=(value,x,y,w,h,size,color=t.fg,bold=false)=>s.addText(value,{
        x,y,w,h,fontFace:'Arial',fontSize:size,color:color.slice(1),bold,
        margin:0,breakLine:false,vertAnchor:'top',paraSpaceAfterPt:10,fit:'shrink'
      });
      text(c.title,.73,c.layout==='cover'?1.05:.6,11.85,1.2,c.layout==='cover'?50:38,t.fg,true);
      if(c.subtitle) text(c.subtitle,.73,1.95,11.7,.8,21,t.muted);
      const y=c.subtitle?2.9:2.2, width=c.image_id?6.15:11.6;
      if(c.bullets.length) {
        s.addText(c.bullets.map((b,i)=>({text:b,options:{bullet:true,breakLine:i<c.bullets.length-1}})),{
          x:.8,y,w:width,h:3.9,fontFace:'Arial',fontSize:c.image_id?19:22,
          color:t.fg.slice(1),margin:0,paraSpaceAfterPt:16,vertAnchor:'top',fit:'shrink'
        });
      }
      if(c.image_id) {
        const p=imagePath(c.image_id);
        s.addImage({path:p,...pptxgen.imageSizingContain(p,7.25,2.2,5.3,4.1)});
      }
      text(project.title,.73,7.06,10,.18,10,t.muted);
      text(String(index+1),12,7.06,.4,.18,10,t.muted);
      s.addNotes((c.notes||'')+'\n\n[Sources]\n'+(c.sources||[]).join('\n')+'\n[/Sources]');
    }
    const output=path.join(outDir,'presentazione.pptx');
    await pptx.writeFile({fileName:output});
    return output;
  }
  if(format==='pdf') {
    const articles=[];
    for(const [index,item] of project.slides.entries()) {
      const image=item.content.image_id;
      const url=image?'data:image/jpeg;base64,'+(await fs.readFile(imagePath(image))).toString('base64'):'';
      articles.push(slideHTML(project,item,index,url));
    }
    const browser=await chromium.launch({headless:true});
    try {
      const page=await browser.newPage({viewport:{width:1280,height:720}});
      await page.setContent('<!doctype html><meta charset="utf-8"><style>'+slideCSS+
        'html,body{margin:0} @page{size:1280px 720px;margin:0}.slide-frame{break-after:page;print-color-adjust:exact}</style>'+
        articles.join(''),{waitUntil:'load'});
      await page.evaluate(()=>document.fonts.ready);
      await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
      const overflow=await page.locator('.slide-frame').evaluateAll(nodes=>nodes.map((node,i)=>({
        slide:i+1,overflow:[...node.querySelectorAll('h1,.subtitle,li')].some(e=>
          e.scrollHeight>e.clientHeight+2||e.getBoundingClientRect().bottom>node.getBoundingClientRect().bottom-46)
      })).filter(x=>x.overflow));
      if(overflow.length) throw new Error('Testo troppo lungo nelle slide '+overflow.map(x=>x.slide).join(', ')+': accorcia il contenuto prima di esportare');
      const output=path.join(outDir,'presentazione.pdf');
      await page.pdf({path:output,preferCSSPageSize:true,printBackground:true});
      return output;
    } finally { await browser.close(); }
  }
  throw new Error('Formato non supportato');
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const [snapshot,assetsDir,outDir,format]=process.argv.slice(2);
  const project=JSON.parse(await fs.readFile(snapshot,'utf8'));
  try { console.log(await buildExports(project,assetsDir,outDir,format)); }
  catch(error) { console.error(error.message); process.exitCode=1; }
}
