import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import pptxgen from 'pptxgenjs';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,themeFor,visualFor,fitSlide} from '../static/deck.mjs';

// Measure every layout, including bullets, illustrations, borders and footers.
export async function measureLayouts(page){
  for(const frame of await page.locator('.slide-frame').all())await frame.evaluate(fitSlide);
  return page.locator('.slide-frame').evaluateAll(nodes=>nodes.map(node=>{
    const origin=node.getBoundingClientRect();
    const rect=e=>{const r=e.getBoundingClientRect();return {x:(r.x-origin.x)/96,y:(r.y-origin.y)/96,w:r.width/96,h:r.height/96}};
    const visible=e=>e.textContent.trim()&&e.getClientRects().length&&getComputedStyle(e).display!=='none';
    const texts=[...node.querySelectorAll('.kicker,h1,.subtitle,.prose-box h2,.prose-box p,.prose-source,.block-number,.bullet-mark,.bullet-text,.footer span,.image-credit,.placeholder-title,.placeholder-query')].map((e,domIndex)=>({e,domIndex})).filter(({e})=>visible(e)).map(({e,domIndex})=>{
      const c=getComputedStyle(e);return {...rect(e),domIndex,formula:Boolean(e.querySelector('.katex')),
        value:e.dataset.editRaw??e.textContent,size:parseFloat(c.fontSize)*.75,
        font:c.fontFamily.split(',')[0].replaceAll('"',''),bold:Number(c.fontWeight)>=600,
        italic:c.fontStyle==='italic',color:c.color,lineHeight:parseFloat(c.lineHeight)*.75};
    });
    const boxes=[...node.querySelectorAll('.prose-box,.prose-box h2,li,.slide-accent,.image-placeholder')].map(e=>{
      const c=getComputedStyle(e);return {...rect(e),color:c.backgroundColor,radius:parseFloat(c.borderTopLeftRadius)/96,
        shadow:c.boxShadow!=='none',borders:['Top','Right','Bottom','Left'].map(side=>({
          color:c['border'+side+'Color'],width:parseFloat(c['border'+side+'Width'])*.75}))};
    });
    const visual=node.querySelector('.visual');
    const img=visual?.matches('img')?visual:visual?.querySelector('img');
    return {layout:node.dataset.layout,overflow:node.dataset.overflow==='true',texts,boxes,
      visual:img?rect(img):visual?rect(visual):null,
      image:img?{width:img.naturalWidth,height:img.naturalHeight}:null,
      footer:rect(node.querySelector('.footer'))};
  }));
}

const hex=value=>value.startsWith('#')?value.slice(1):value.match(/[\d.]+/g).slice(0,3).map(v=>Math.round(Number(v)).toString(16).padStart(2,'0')).join('');
const transparent=value=>value==='transparent'||/rgba\(.*,\s*0\)$/.test(value);
export async function buildExports(project,assetsDir,outDir,format){
  if(!['pdf','pptx'].includes(format))throw new Error('Formato non supportato');
  await fs.mkdir(outDir,{recursive:true});
  const imagePath=id=>{
    if(!(/^[a-f0-9-]+\.jpg$/.test(id)||/^manim-[a-f0-9]{64}\.png$/.test(id)))throw new Error('Riferimento immagine non valido');
    return path.join(assetsDir,id);
  };
  const articles=[];
  for(const [index,item] of project.slides.entries()){
    const image=visualFor(project,item.content,item).image;
    const mime=image.endsWith('.png')?'image/png':'image/jpeg';
    const url=image?'data:'+mime+';base64,'+(await fs.readFile(imagePath(image))).toString('base64'):'';
    articles.push(slideHTML(project,item,index,url));
  }
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    const katexRoot=fileURLToPath(new URL('../static/vendor/katex/',import.meta.url)).replaceAll('\\','/');
    const katexCSS=(await fs.readFile(new URL('../static/vendor/katex/katex.min.css',import.meta.url),'utf8'))
      .replaceAll('url(fonts/','url(file:///'+katexRoot+'/fonts/');
    await page.setContent('<!doctype html><meta charset="utf-8"><style>'+katexCSS+slideCSS+
      'html,body{margin:0}@page{size:1280px 720px;margin:0}.slide-frame{break-after:page;print-color-adjust:exact}</style>'+
      articles.join(''),{waitUntil:'load'});
    await page.evaluate(()=>document.fonts.ready);
    await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
    const measured=await measureLayouts(page);
    const textSelector='.kicker,h1,.subtitle,.prose-box h2,.prose-box p,.prose-source,.block-number,.bullet-mark,.bullet-text,.footer span,.image-credit,.placeholder-title,.placeholder-query';
    const formulaImages=[];
    for(const [slideIndex,layout] of measured.entries()){
      const items=[];
      for(const text of layout.texts){
        items.push(text.formula?'data:image/png;base64,'+(await page.locator('.slide-frame').nth(slideIndex)
          .locator(textSelector).nth(text.domIndex).screenshot({omitBackground:true})).toString('base64'):null);
      }
      formulaImages.push(items);
    }
    await fs.writeFile(path.join(outDir,'layout-report.json'),JSON.stringify(measured.map((m,i)=>({slide:i+1,layout:m.layout,overflow:m.overflow})),null,2));
    const bad=measured.flatMap((m,i)=>m.overflow?[i+1]:[]);
    if(bad.length)throw new Error('Testo fuori dallo spazio nelle slide '+bad.join(', ')+': il composer ha provato altre disposizioni. Dividi il contenuto in più slide o modifica il testo; nessuna parte viene nascosta nell’export.');
    if(format==='pdf'){
      const output=path.join(outDir,'presentazione.pdf');
      await page.pdf({path:output,preferCSSPageSize:true,printBackground:true});
      return output;
    }
    const pptx=new pptxgen();
    pptx.layout='LAYOUT_WIDE';pptx.author='H3-slides';pptx.subject=project.prompt;
    pptx.title=project.title;pptx.lang='it-IT';
    for(const [index,item] of project.slides.entries()){
      const c=item.content,t=themeFor(project),s=pptx.addSlide(),layout=measured[index],visual=visualFor(project,c,item);
      s.background={color:t.bg.slice(1)};
      for(const b of layout.boxes){
        if(!transparent(b.color))s.addShape(b.radius?pptx.ShapeType.roundRect:pptx.ShapeType.rect,{
          x:b.x,y:b.y,w:b.w,h:b.h,rectRadius:b.radius,fill:{color:hex(b.color)},line:{transparency:100},
          ...(b.shadow?{shadow:{type:'outer',color:'000000',blur:8,angle:90,distance:3,opacity:.10}}:{})});
        b.borders.forEach((edge,i)=>{
          if(!edge.width)return;
          s.addShape(pptx.ShapeType.line,{x:b.x+(i===1?b.w:0),y:b.y+(i===2?b.h:0),
            w:i%2?0:b.w,h:i%2?b.h:0,line:{color:hex(edge.color),width:edge.width}});
        });
      }
      for(const [textIndex,b] of layout.texts.entries()){
        if(b.formula)s.addImage({data:formulaImages[index][textIndex],x:b.x,y:b.y,w:b.w,h:b.h});
        else s.addText(b.value,{x:b.x,y:b.y,w:b.w,h:b.h+.025,fontFace:b.font,
          fontSize:b.size,bold:b.bold,italic:b.italic,color:hex(b.color),margin:0,breakLine:false,
          valign:'top',fit:'shrink',paraSpaceAfterPt:0,...(Number.isFinite(b.lineHeight)?{lineSpacingMultiple:b.lineHeight/b.size}:{} )});
      }
      s.addShape(pptx.ShapeType.line,{x:layout.footer.x,y:layout.footer.y,w:layout.footer.w,h:0,line:{color:t.line.slice(1),width:.75}});
      const frame=layout.visual;
      if(visual.image&&frame){
        const p=imagePath(visual.image),dims=layout.image;
        if(!dims||!Number.isFinite(dims.width)||!Number.isFinite(dims.height)||dims.width<=0||dims.height<=0)
          throw new Error('Immagine non decodificabile: esportazione annullata.');
        const ratio=Math.min(frame.w/dims.width,frame.h/dims.height);
        const w=dims.width*ratio,h=dims.height*ratio;
        s.addImage({path:p,x:frame.x+(frame.w-w)/2,y:frame.y+(frame.h-h)/2,w,h});
      }
      const credit=(project.visual_assets||[]).find(asset=>asset.id===visual.image&&asset.origin==='web');
      s.addNotes((c.notes||'')+'\n\n[Sources]\n'+(c.sources||[]).join('\n')+'\n[/Sources]'+
        (credit?'\n\n[Image attribution]\n'+[credit.label,credit.author,credit.license,credit.source,credit.license_url].join('\n'):''));
    }
    const output=path.join(outDir,'presentazione.pptx');
    await pptx.writeFile({fileName:output});return output;
  }finally{await browser.close()}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const [snapshot,assetsDir,outDir,format]=process.argv.slice(2);
  const project=JSON.parse(await fs.readFile(snapshot,'utf8'));
  try{console.log(await buildExports(project,assetsDir,outDir,format))}
  catch(error){console.error(error.message);process.exitCode=1}
}
