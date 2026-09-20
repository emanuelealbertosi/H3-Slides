import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS,themeFor,visualFor,fitSlide} from '../static/deck.mjs';
import {pageAssets} from '../static/page-v2.mjs';

// Measure every layout, including bullets, illustrations, borders and footers.
export async function measureLayouts(page,options={}){
  const reports=[];
  for(const frame of await page.locator('.slide-frame').all())reports.push(await frame.evaluate(fitSlide,options));
  const measured=await page.locator('.slide-frame').evaluateAll(nodes=>nodes.map(node=>{
    const origin=node.getBoundingClientRect();
    const rect=e=>{const r=e.getBoundingClientRect();return {x:(r.x-origin.x)/96,y:(r.y-origin.y)/96,w:r.width/96,h:r.height/96}};
    const paint=e=>{
      const c=getComputedStyle(e);
      // Only the application's two-stop gradient is accepted. No CSS or SVG
      // supplied by a model is reused when creating the PowerPoint background.
      const match=e.dataset.v2Gradient==='true'&&c.backgroundImage.match(/^linear-gradient\(135deg, (rgb\(\d{1,3}, \d{1,3}, \d{1,3}\)) 0%, (rgb\(\d{1,3}, \d{1,3}, \d{1,3}\)) 100%\)$/);
      const gradient=match&&match.slice(1).every(color=>color.match(/\d+/g).every(v=>Number(v)<=255))?match.slice(1):null;
      return {...rect(e),color:c.backgroundColor,gradient,opacity:Number(c.opacity),decoration:e.dataset.v2Decoration||null,
        radius:parseFloat(c.borderTopLeftRadius)/96,
        radii:['TopLeft','TopRight','BottomRight','BottomLeft'].map(corner=>parseFloat(c['border'+corner+'Radius'])/96),
        shadow:c.boxShadow!=='none',shadowCSS:c.boxShadow,borders:['Top','Right','Bottom','Left'].map(side=>({
          color:c['border'+side+'Color'],width:parseFloat(c['border'+side+'Width'])*.75}))};
    };
    const visible=e=>e.textContent.trim()&&e.getClientRects().length&&getComputedStyle(e).display!=='none';
    const texts=[...node.querySelectorAll('.kicker,h1,.subtitle,.prose-box h2,.prose-box p,.prose-source,.block-number,.bullet-mark,.bullet-text,.footer span,.image-credit,.placeholder-title,.placeholder-query,.v2-text')].map((e,domIndex)=>({e,domIndex})).filter(({e})=>visible(e)).map(({e,domIndex})=>{
      const c=getComputedStyle(e);return {...rect(e),domIndex,formula:Boolean(e.querySelector('.katex')),
        value:e.dataset.editRaw??e.textContent,size:parseFloat(c.fontSize)*.75,
        font:c.fontFamily.split(',')[0].replaceAll('"',''),bold:Number(c.fontWeight)>=600,
        italic:c.fontStyle==='italic',color:c.color,align:c.textAlign,lineHeight:parseFloat(c.lineHeight)*.75};
    });
    const boxes=[...node.querySelectorAll('.prose-box,.prose-box h2,li,.slide-accent,.image-placeholder,.v2-node,.v2-root,span[data-v2-decoration="stripe"],span[data-v2-decoration="corner"]')].map(paint);
    const visuals=[...node.querySelectorAll('.visual,.v2-media')].map(visual=>{
      const img=visual.matches('img')?visual:visual.querySelector('img');
      return {kind:visual.dataset.visualKind||'image',asset:visual.dataset.assetId,frame:img?rect(img):rect(visual),
        image:img?{width:img.naturalWidth,height:img.naturalHeight}:null};
    });
    const footer=node.querySelector('.footer'),footerStyle=getComputedStyle(footer);
    return {width:origin.width,height:origin.height,engine:node.dataset.engine||'classic',layout:node.dataset.layout,overflow:node.dataset.overflow==='true',texts,boxes,background:paint(node),
      visuals,visual:visuals[0]?.frame||null,image:visuals[0]?.image||null,
      footer:{...rect(footer),color:footerStyle.borderTopColor,width:parseFloat(footerStyle.borderTopWidth)*.75}};
  }));
  return measured.map((layout,index)=>{
    const report=reports[index]||{};
    const baseHeight=Number(report.baseHeight)||720,maxHeight=Number(report.maxHeight)||null;
    return {...layout,overflow:layout.overflow||layout.engine==='v2'&&maxHeight!==null&&(layout.height>maxHeight+1||layout.height<baseHeight-1),
      neededHeight:Number(report.neededHeight)||layout.height,baseHeight,maxHeight,fontScale:Number(report.fontScale)||1,
      adjusted:Boolean(report.adjusted),compact:Boolean(report.compact),reflowed:Boolean(report.reflowed),
      mediaOverflow:Boolean(report.mediaOverflow),nodes:Array.isArray(report.nodes)?report.nodes:[]};
  });
}

export function exportPageFormat(project){
  const format=project.slide_format||'16:9',heights={'16:9':720,'4:3':960,'16:10':800,'1:1':1280};
  if(!Object.hasOwn(heights,format))throw new Error('Formato della pagina non supportato');
  const slides=project.slides||[],hasClassic=slides.some(slide=>!slide.content?.page&&!slide.page_draft);
  if(format!=='16:9'&&hasClassic)throw new Error('I formati diversi da 16:9 richiedono pagine V2. Converti le slide classiche prima di esportare.');
  return {format,width:1280,height:heights[format]};
}

export function exportCanvasHeight(project,layouts){
  const base=exportPageFormat(project).height,height=Math.max(base,...layouts.map(layout=>layout.height));
  const bounded=layouts.filter(layout=>layout.engine==='v2');
  if(bounded.length){
    const maximum=Math.min(...bounded.map(layout=>layout.maxHeight||(project.canvas_mode==='fixed'?base:Math.round(base*1.15))));
    if(height>maximum+1)throw new Error('Le pagine non possono condividere il formato di esportazione entro il limite del 15%. Riduci la slide più alta o separa le pagine classiche dalle pagine V2.');
  }
  return height;
}

let mathStyles;
export async function loadMathStyles(){
  if(!mathStyles)mathStyles=(async()=>{
    const root=new URL('../static/vendor/katex/',import.meta.url);
    let css=await fs.readFile(new URL('katex.min.css',root),'utf8');
    // About:blank documents cannot reliably load file:// fonts. Embedded WOFF2
    // works identically in the measuring browser, PDF, and portable Slidev CSS.
    for(const declaration of new Set(css.match(/src:[^;}]+(?=[;}])/g)||[])){
      const file=declaration.match(/url\(fonts\/([A-Za-z0-9_.-]+\.woff2)\)/)?.[1];
      if(!file)continue;
      const data=(await fs.readFile(new URL('fonts/'+file,root))).toString('base64');
      css=css.replaceAll(declaration,'src:url(data:font/woff2;base64,'+data+') format("woff2")');
    }
    return css;
  })();
  try{return await mathStyles}catch(error){mathStyles=null;throw error}
}

const hex=value=>value.startsWith('#')?value.slice(1):value.match(/[\d.]+/g).slice(0,3).map(v=>Math.round(Number(v)).toString(16).padStart(2,'0')).join('');
const transparent=value=>value==='transparent'||/rgba\(.*,\s*0\)$/.test(value);
const fillFor=(color,opacity=1)=>({color:hex(color),transparency:100*(1-opacity*(color.startsWith('rgba(')?Number(color.match(/[\d.]+/g)[3]):1))});
const shadowFor=box=>{
  const match=box.shadowCSS.match(/^(rgba?\([^)]+\)) (-?[\d.]+)px (-?[\d.]+)px ([\d.]+)px -?[\d.]+px$/);
  if(!match)return box.shadow?{type:'outer',color:'000000',blur:8,angle:90,offset:3,opacity:.10}:undefined;
  const [,color,x,y,blur]=match;
  return {type:'outer',color:hex(color),blur:Number(blur)*.75,
    angle:(Math.atan2(Number(y),Number(x))*180/Math.PI+360)%360,
    offset:Math.hypot(Number(x),Number(y))*.75,opacity:1-fillFor(color,box.opacity).transparency/100};
};

async function gradientImages(page,layouts){
  // Drawing an empty canvas guarantees that all non-formula text remains
  // editable: the PNG contains only the measured background and rounded clip.
  return page.evaluate(items=>items.map(layout=>[layout.background,...layout.boxes].map(box=>{
    if(!box.gradient||box.w<=0||box.h<=0)return null;
    const w=box.w*96,h=box.h*96,canvas=document.createElement('canvas');
    canvas.width=Math.ceil(w*2);canvas.height=Math.ceil(h*2);
    const ctx=canvas.getContext('2d');ctx.scale(canvas.width/w,canvas.height/h);
    ctx.beginPath();ctx.roundRect(0,0,w,h,box.radii.map(radius=>Math.max(0,radius*96)));ctx.clip();
    // CSS's 135-degree gradient line extends to the projected corners,
    // including on wide or tall rectangles (it is not corner-to-corner).
    const gradient=ctx.createLinearGradient((w-h)/4,(h-w)/4,(3*w+h)/4,(w+3*h)/4);
    box.gradient.forEach((color,index)=>gradient.addColorStop(index,color));
    ctx.globalAlpha=box.opacity;ctx.fillStyle=gradient;ctx.fillRect(0,0,w,h);
    const data=canvas.toDataURL('image/png');canvas.width=0;canvas.height=0;
    return data;
  })),layouts);
}
export async function buildExports(project,assetsDir,outDir,format){
  if(!['pdf','pptx'].includes(format))throw new Error('Formato non supportato');
  const canvas=exportPageFormat(project);
  await fs.mkdir(outDir,{recursive:true});
  const imagePath=id=>{
    if(!(/^[a-f0-9-]+\.jpg$/.test(id)||/^manim-[a-f0-9]{64}\.png$/.test(id)))throw new Error('Riferimento immagine non valido');
    return path.join(assetsDir,id);
  };
  const articles=[];
  for(const [index,item] of project.slides.entries()){
    const visual=visualFor(project,item.content,item),urls={};
    urls.assets={};
    for(const id of pageAssets(item.content.page))urls.assets[id]='data:'+(id.endsWith('.png')?'image/png':'image/jpeg')+';base64,'+(await fs.readFile(imagePath(id))).toString('base64');
    for(const [kind,id] of [['diagram',visual.diagramAsset],['image',visual.photo]]){
      if(id)urls[kind]='data:'+(id.endsWith('.png')?'image/png':'image/jpeg')+';base64,'+
        (await fs.readFile(imagePath(id))).toString('base64');
    }
    articles.push(slideHTML(project,item,index,urls));
  }
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:canvas.width,height:canvas.height}});
    await page.route('**/*',route=>route.abort());
    const katexCSS=await loadMathStyles();
    await page.setContent('<!doctype html><meta charset="utf-8"><style>'+katexCSS+slideCSS+
      'html,body{margin:0}@page{size:1280px '+canvas.height+'px;margin:0}.slide-frame{break-after:page;print-color-adjust:exact}</style>'+
      articles.join(''),{waitUntil:'load'});
    await page.evaluate(()=>document.fonts.ready);
    await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
    let measured=await measureLayouts(page);
    const deckHeight=format==='pptx'?exportCanvasHeight(project,measured):Math.max(canvas.height,...measured.map(m=>m.height));
    if(format==='pptx'&&deckHeight>5376)throw new Error('Una pagina supera il limite fisico di PowerPoint (56 pollici). Suddividila o riduci la struttura; il PDF mantiene il formato adattivo.');
    if(format==='pptx')measured=await measureLayouts(page,{targetHeight:deckHeight});
    await fs.writeFile(path.join(outDir,'layout-report.json'),JSON.stringify(measured.map((m,i)=>({
      slide:i+1,layout:m.layout,overflow:m.overflow,width:1280,height:m.height,neededHeight:m.neededHeight,
      baseHeight:m.baseHeight,maxHeight:m.maxHeight,fontScale:m.fontScale,footer:m.footer})),null,2));
    const bad=measured.flatMap((m,i)=>m.overflow?[i+1]:[]);
    if(bad.length)throw new Error('Testo fuori dallo spazio nelle slide '+bad.join(', ')+': '+(project.slides.some(s=>s.content.page)?'la pagina V2 supera il formato disponibile e il limite adattivo del 15%. Riduci o dividi il contenuto; nessuna parte viene nascosta nell’export.':'il composer ha provato altre disposizioni. Dividi il contenuto in più slide o modifica il testo; nessuna parte viene nascosta nell’export.'));
    const textSelector='.kicker,h1,.subtitle,.prose-box h2,.prose-box p,.prose-source,.block-number,.bullet-mark,.bullet-text,.footer span,.image-credit,.placeholder-title,.placeholder-query,.v2-text';
    const formulaImages=[];
    for(const [slideIndex,layout] of (format==='pptx'?measured:[]).entries()){
      const items=[];
      for(const text of layout.texts){
        items.push(text.formula?'data:image/png;base64,'+(await page.locator('.slide-frame').nth(slideIndex)
          .locator(textSelector).nth(text.domIndex).screenshot({omitBackground:true})).toString('base64'):null);
      }
      formulaImages.push(items);
    }
    if(format==='pdf'){
      // CSS named pages preserve each adaptive card's measured height.
      await page.addStyleTag({content:measured.map((m,i)=>'@page slide'+i+'{size:1280px '+m.height+'px;margin:0}.slide-frame:nth-of-type('+(i+1)+'){page:slide'+i+'}').join('')});
      const output=path.join(outDir,'presentazione.pdf');
      await page.pdf({path:output,preferCSSPageSize:true,printBackground:true});
      return output;
    }
    const {default:pptxgen}=await import('pptxgenjs');
    const pptx=new pptxgen();
    pptx.layout='LAYOUT_WIDE';pptx.author='H3-slides';pptx.subject=project.prompt;
    pptx.defineLayout({name:'H3_PAGE',width:canvas.width/96,height:deckHeight/96});pptx.layout='H3_PAGE';
    pptx.title=project.title;pptx.lang='it-IT';
    const backgrounds=await gradientImages(page,measured);
    for(const [index,item] of project.slides.entries()){
      const c=item.content,t=themeFor(project),s=pptx.addSlide(),layout=measured[index],visual=visualFor(project,c,item);
      s.background={color:transparent(layout.background.color)?t.bg.slice(1):hex(layout.background.color)};
      if(backgrounds[index][0])s.addImage({data:backgrounds[index][0],x:0,y:0,w:layout.background.w,h:layout.background.h});
      for(const [boxIndex,b] of layout.boxes.entries()){
        const gradient=backgrounds[index][boxIndex+1],shadow=shadowFor(b);
        if(!transparent(b.color))s.addShape(b.radius?pptx.ShapeType.roundRect:pptx.ShapeType.rect,{
          x:b.x,y:b.y,w:b.w,h:b.h,rectRadius:b.radius,fill:fillFor(b.color,b.opacity),line:{transparency:100},
          ...(!gradient&&shadow?{shadow}:{})});
        if(gradient)s.addImage({data:gradient,x:b.x,y:b.y,w:b.w,h:b.h,...(shadow?{shadow}:{})});
        b.borders.forEach((edge,i)=>{
          if(!edge.width)return;
          s.addShape(pptx.ShapeType.line,{x:b.x+(i===1?b.w:0),y:b.y+(i===2?b.h:0),
            w:i%2?0:b.w,h:i%2?b.h:0,line:{color:hex(edge.color),width:edge.width}});
        });
      }
      for(const [textIndex,b] of layout.texts.entries()){
        if(b.formula)s.addImage({data:formulaImages[index][textIndex],x:b.x,y:b.y,w:b.w,h:b.h});
        else s.addText(b.value,{x:b.x,y:b.y,w:b.w,h:b.h+.025,fontFace:b.font,
          fontSize:b.size,bold:b.bold,italic:b.italic,color:hex(b.color),align:['center','right','justify'].includes(b.align)?b.align:'left',margin:0,breakLine:false,
          valign:'top',fit:'shrink',paraSpaceAfterPt:0,...(Number.isFinite(b.lineHeight)?{lineSpacingMultiple:b.lineHeight/b.size}:{} )});
      }
      if(layout.footer.width)s.addShape(pptx.ShapeType.line,{x:layout.footer.x,y:layout.footer.y,w:layout.footer.w,h:0,line:{color:hex(layout.footer.color),width:layout.footer.width}});
      for(const media of layout.visuals){
        const id=media.asset||(media.kind==='diagram'?visual.diagramAsset:visual.photo);
        if(!id)continue;
        const frame=media.frame,p=imagePath(id),dims=media.image;
        if(!dims||!Number.isFinite(dims.width)||!Number.isFinite(dims.height)||dims.width<=0||dims.height<=0)
          throw new Error('Immagine non decodificabile: esportazione annullata.');
        const ratio=Math.min(frame.w/dims.width,frame.h/dims.height);
        const w=dims.width*ratio,h=dims.height*ratio;
        s.addImage({path:p,x:frame.x+(frame.w-w)/2,y:frame.y+(frame.h-h)/2,w,h});
      }
      const credit=(project.visual_assets||[]).find(asset=>asset.id===visual.photo&&asset.origin==='web');
      s.addNotes((c.page?.notes||c.notes||'')+'\n\n[Sources]\n'+(c.page?.sources||c.sources||[]).join('\n')+'\n[/Sources]'+
        (c.page?'\n'+c.page.nodes.filter(n=>n.source).map(n=>n.source).join('\n'):'')+
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
