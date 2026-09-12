import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright-chromium';
import JSZip from 'jszip';
import {buildExports,loadMathStyles,measureLayouts} from '../scripts/export.mjs';
import {slideHTML,slideCSS,fitSlide} from '../static/deck.mjs';

const root=fileURLToPath(new URL('..',import.meta.url));
const pixel='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XMG8WQAAAABJRU5ErkJggg==';
const photo='00000000-0000-0000-0000-000000000001.jpg',diagram='manim-'+'1'.repeat(64)+'.png';
const code='def esempio():\n'+Array.from({length:25},(_,i)=>'    print("riga '+i+'")').join('\n');
const formula=String.raw`Le frazioni mantengono le dimensioni leggibili anche quando cambia la pagina. \[\frac{\displaystyle\sum_{k=1}^{n}\frac{1}{k^2}}{\sqrt{\frac{a^2+b^2}{c^2+d^2}}}\] Il denominatore deve essere diverso da zero.`;
const base=content=>({content:{layout:'content',bullets:[],blocks:[],diagram:{kind:'none'},...content}});
const project={title:'Verifica geometria adattiva',theme:'paper',font:'Arial',canvas_mode:'adaptive',
  graphic_style:'studio',use_manim_diagrams:true,use_source_images:true,slides:[
    base({title:'Codice Python con indentazione e tutte le istruzioni visibili',blocks:[{heading:'Esempio Python',kind:'code',language:'python',text:code}]}),
    base({title:'Formule con frazioni, radici e sommatorie in una spiegazione matematica completa',blocks:[{heading:'Frazione composta',text:formula}]}),
    {...base({title:'Codice, immagine e diagramma nella stessa slide',blocks:[{heading:'Esempio C++',kind:'code',language:'cpp',text:'#include <iostream>\nint main() {\n    std::cout << "Ciao";\n    return 0;\n}'}],
      image_id:photo,diagram:{kind:'manim',brief:'Diagramma di prova',scene:{}}}),diagram_render:{engine:'manim',asset:diagram}},
    base({title:'Elementi posizionati manualmente',layout:'freeform',layout_locked:true,canvas_height:720,
      freeform:{heading:{x:48,y:48,w:1184,h:130},'block-0':{x:48,y:220,w:900,h:200}},
      blocks:[{heading:'Contenuto modificabile',text:'Il testo resta modificabile. Il canvas comune riposiziona il piè di pagina senza perdere il contenuto.'}]}),
  ]};

async function temporary(){
  const logs=path.join(root,'logs');await fs.mkdir(logs,{recursive:true});
  return fs.mkdtemp(path.join(logs,'adaptive-export-'));
}
function sourceForSlidev(value){
  return JSON.parse(execFileSync(process.execPath,[path.join(root,'scripts/slidev_source.mjs')],{
    input:JSON.stringify(value),encoding:'utf8',maxBuffer:8*1024*1024,cwd:root,windowsHide:true,
  }));
}
function geometry(){
  return [...document.querySelectorAll('.slide-frame')].map(frame=>{
    const bounds=frame.getBoundingClientRect();
    const rect=element=>{const r=element.getBoundingClientRect();return {x:r.x-bounds.x,y:r.y-bounds.y,w:r.width,h:r.height}};
    return {height:frame.offsetHeight,layout:frame.dataset.layout,overflow:frame.dataset.overflow,
      heading:rect(frame.querySelector('.heading')),footer:rect(frame.querySelector('.footer')),
      objects:[...frame.querySelectorAll('h1,.prose-box,.prose-box p,.katex-html,.visual')].map(rect)};
  });
}

test('math fonts are embedded before measuring adaptive cards',async()=>{
  const css=await loadMathStyles();
  assert.equal((css.match(/data:font\/woff2/g)||[]).length,20);
  assert.doesNotMatch(css,/url\((?:file:|fonts\/)/);
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    await page.setContent('<style>'+css+slideCSS+'</style>'+slideHTML(project,project.slides[1],1));
    await page.evaluate(()=>document.fonts.ready);
    const fonts=await page.evaluate(()=>[...document.fonts].filter(font=>font.family.startsWith('KaTeX')&&font.status==='loaded').map(font=>font.family));
    assert.ok(fonts.includes('KaTeX_Main')&&fonts.includes('KaTeX_Math'),JSON.stringify(fonts));
    const [measured]=await measureLayouts(page);
    assert.equal(measured.overflow,false);
    assert.ok(measured.texts.some(item=>item.formula&&item.h>1));
    assert.ok(measured.texts.every(item=>item.size>=9),'Export keeps the measured font sizes');
  }finally{await browser.close()}
});

test('PDF keeps card heights while PPTX recomposes all cards onto a common canvas',async()=>{
  const out=await temporary();
  await fs.writeFile(path.join(out,photo),Buffer.from(pixel,'base64'));
  await fs.writeFile(path.join(out,diagram),Buffer.from(pixel,'base64'));
  const pdf=await buildExports(project,out,path.join(out,'pdf'),'pdf');
  const pdfReport=JSON.parse(await fs.readFile(path.join(out,'pdf/layout-report.json'),'utf8'));
  assert.ok(new Set(pdfReport.map(item=>item.height)).size>1);
  const probe='import fitz,json,sys;d=fitz.open(sys.argv[1]);print(json.dumps({"sizes":[[p.rect.width,p.rect.height] for p in d],"text":"".join(p.get_text() for p in d),"fonts":[f[3] for p in d for f in p.get_fonts()],"outside":[i+1 for i,p in enumerate(d) if any(b[0]<-1 or b[1]<-1 or b[2]>p.rect.width+1 or b[3]>p.rect.height+1 for b in p.get_text("blocks") if b[6]==0)]}))';
  const parsed=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-B','-c',probe,pdf],{encoding:'utf8',windowsHide:true}).trim().split('\n').findLast(line=>line.startsWith('{')));
  assert.equal(parsed.sizes.length,project.slides.length);
  parsed.sizes.forEach((size,index)=>{
    assert.ok(Math.abs(size[0]-960)<.1);
    assert.ok(Math.abs(size[1]-pdfReport[index].height*.75)<.1);
  });
  assert.deepEqual(parsed.outside,[]);assert.match(parsed.text,/riga 24/);assert.match(parsed.text,/std::cout/);
  assert.ok(parsed.fonts.some(font=>font.includes('KaTeX')),'PDF embeds actual math font glyphs');
  const pptx=await buildExports(project,out,path.join(out,'pptx'),'pptx');
  const report=JSON.parse(await fs.readFile(path.join(out,'pptx/layout-report.json'),'utf8'));
  const height=Math.max(...pdfReport.map(item=>item.height));
  assert.ok(report.every(item=>item.height===height&&!item.overflow));
  assert.ok(report.every(item=>Math.abs(item.footer.y+item.footer.h-(height-21)/96)<.02),'Every footer sits at the common bottom');
  const zip=await JSZip.loadAsync(await fs.readFile(pptx));
  const presentation=await zip.file('ppt/presentation.xml').async('string');
  const dimensions=presentation.match(/<p:sldSz cx="(\d+)" cy="(\d+)"/);
  assert.ok(dimensions);
  assert.equal(Number(dimensions[1]),1280*9525);assert.equal(Number(dimensions[2]),height*9525);
  for(let i=1;i<=project.slides.length;i++){
    const xml=await zip.file('ppt/slides/slide'+i+'.xml').async('string');
    const positions=[...xml.matchAll(/<a:xfrm[^>]*>[\s\S]*?<a:off x="(-?\d+)" y="(-?\d+)"\/>[\s\S]*?<a:ext cx="(\d+)" cy="(\d+)"\/>/g)];
    assert.ok(positions.length>0);
    for(const position of positions){
      const [,x,y,w,h]=position.map(Number);
      assert.ok(x>=-9525&&y>=-9525&&x+w<=1280*9525+9525&&y+h<=height*9525+9525,'PPTX shape outside canvas on slide '+i);
    }
    if(i===1)assert.match(xml,/riga 24/);
    if(i===2)assert.match(xml,/<p:pic>/,'Math remains a sharply rendered image at its measured size');
    if(i===3)assert.equal((xml.match(/<p:pic>/g)||[]).length,2,'Image and diagram coexist');
  }
});

test('Slidev freezes the measured math layout only after font loading and common-canvas reflow',async()=>{
  const output=sourceForSlidev(project);
  assert.deepEqual(output.overflow,[]);
  assert.equal(output.css,await loadMathStyles()+slideCSS);
  const articles=output.markdown.match(/<article\b[\s\S]*?<\/article>/g);
  assert.equal(articles.length,project.slides.length);
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    const markup=articles.join('').replaceAll('./assets/'+photo,'data:image/png;base64,'+pixel).replaceAll('./assets/'+diagram,'data:image/png;base64,'+pixel);
    await page.setContent('<style>'+output.css+'body{margin:0}</style>'+markup);
    await page.evaluate(()=>document.fonts.ready);
    await page.evaluate(()=>Promise.all([...document.images].map(image=>image.decode())));
    const before=await page.evaluate(geometry),height=Math.max(...before.map(item=>item.height));
    assert.ok(height>720&&height<=1008);
    assert.match(output.markdown,new RegExp('aspectRatio: 1280/'+height));
    assert.ok(before.every(item=>item.height===height&&item.overflow==='false'));
    assert.ok(before.every(item=>Math.abs(item.footer.y+item.footer.h-(height-21))<1));
    for(const frame of await page.locator('.slide-frame').all())await frame.evaluate(fitSlide,{targetHeight:height});
    const after=await page.evaluate(geometry);
    assert.deepEqual(after,before,'Loading the final styles/fonts does not change frozen geometry');
    const loaded=await page.evaluate(()=>[...document.fonts].filter(font=>font.family.startsWith('KaTeX')&&font.status==='loaded').length);
    assert.ok(loaded>1);
  }finally{await browser.close()}
});

test('oversized content is rejected in all exports without freezing clipped text',async()=>{
  const tooLong={...project,slides:[base({title:'Contenuto troppo alto',blocks:[{kind:'code',language:'python',text:Array.from({length:80},()=> 'print(1)').join('\n')} ]})]};
  const out=await temporary();
  for(const format of ['pdf','pptx']){
    await assert.rejects(buildExports(tooLong,out,path.join(out,format),format),/Testo fuori dallo spazio/);
    await assert.rejects(fs.access(path.join(out,format,'presentazione.'+format)));
  }
  assert.throws(()=>sourceForSlidev(tooLong),/Testo fuori dallo spazio/);
});
